"""Orchestrator — descobre câmeras, captura frames e roteia para plugins."""

from __future__ import annotations

import asyncio
import gc
import importlib
import logging
import pkgutil
import re
from pathlib import Path
from typing import Any

from analytics.core.config import get_settings
from analytics.core.detection_cache import DetectionCache
from analytics.core.frame_source import FrameSource
from analytics.core.metrics import MetricsCollector
from analytics.core.plugin_base import (
    AnalyticsPlugin,
    AnalyticsResult,
    FrameMetadata,
    ROIConfig,
)
from analytics.core.shared_inference import (
    PLUGIN_CLASSES,
    SharedInferenceEngine,
)
from analytics.core.vms_client import VMSClient
from analytics.core.zones import load_zones_config  # fallback local

logger = logging.getLogger(__name__)

# Modelos que podem ser compartilhados entre plugins
SHARED_MODELS = {
    "object.pt": {
        "intrusion",
        "people_count",
        "person_detection",
        "vehicle_detection",
        "vehicle_count",
        "speed",
    },
}


class Orchestrator:
    """
    Coordena captura de frames e roteamento para plugins.

    Fluxo standalone:
    1. Descobre câmeras via GET /api/v1/plugins/cameras
    2. Obtém token RTSP via GET /api/v1/plugins/stream-token por câmera
    3. Captura frames de cada câmera a 1fps (configurável)
    4. Todos os plugins processam todos os frames
    5. Plugins usam zonas locais (zones.yaml ou env var) — sem dependência do VMS para config
    6. Resultados enviados via POST /api/v1/plugins/events
    """

    # Janela de coleta do batch: aguarda até 50ms por mais frames antes de rodar inferência
    _BATCH_WINDOW: float = 0.05
    # Máximo de câmeras por chamada ao modelo (limita VRAM de ativação)
    _MAX_BATCH: int = 8

    def __init__(self) -> None:
        self._plugins: list[AnalyticsPlugin] = []
        self._shared_engines: dict[str, SharedInferenceEngine] = {}
        self._plugin_uses_shared: dict[str, str] = {}  # plugin_name -> engine_name
        self._vms_client = VMSClient()
        self._running = False
        self._camera_tasks: dict[str, asyncio.Task[None]] = {}
        self._discovery_task: asyncio.Task[None] | None = None
        self._detection_cache = DetectionCache(max_empty_frames=30, ttl_seconds=60.0)
        self._metrics = MetricsCollector()
        self._gpu_semaphore: asyncio.Semaphore | None = None
        # Batch inference: fila de (engine, frame, future) — uma entrada por câmera por tick
        self._frame_queue: asyncio.Queue[tuple] = asyncio.Queue(maxsize=64)
        self._batch_task: asyncio.Task[None] | None = None

    @property
    def plugins(self) -> list[AnalyticsPlugin]:
        """Plugins carregados."""
        return list(self._plugins)

    # face_recognition não roda mais como plugin contínuo (frame a frame) — virou
    # busca sob demanda (POST /face-search, ver analytics/core/face_search.py),
    # disparada pelo usuário a partir de um rosto já cadastrado na watchlist,
    # contra snapshots de eventos já existentes. Rodar isso em todo frame de
    # toda câmera era caro e não era o que fazia sentido pro produto.
    _LIVE_PLUGIN_BLOCKLIST = {"face_recognition"}

    async def load_plugins(self) -> None:
        """Escaneia analytics/plugins/*/plugin.py e carrega todos os plugins."""
        settings = get_settings()
        plugins_pkg = importlib.import_module("analytics.plugins")
        plugins_path = Path(plugins_pkg.__path__[0])

        for _finder, name, ispkg in pkgutil.iter_modules([str(plugins_path)]):
            if not ispkg or name in self._LIVE_PLUGIN_BLOCKLIST:
                continue
            try:
                mod = importlib.import_module(f"analytics.plugins.{name}.plugin")
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, AnalyticsPlugin)
                        and attr is not AnalyticsPlugin
                        and not getattr(attr, "__abstractmethods__", set())
                    ):
                        plugin = attr()
                        config: dict[str, Any] = {
                            "model_path": settings.yolo_model_path,
                            "imgsz": settings.yolo_imgsz,
                            "conf": settings.yolo_conf,
                        }

                        # Configurar modelo específico por plugin
                        if plugin.name == "lpr":
                            config["model_path"] = settings.lpr_model_path
                        elif plugin.name == "fire_smoke":
                            config["model_path"] = settings.fire_smoke_model_path
                        elif plugin.name == "ppe_detection":
                            config["model_path"] = settings.ppe_model_path
                        elif plugin.name == "biker_detection":
                            config["model_path"] = settings.biker_model_path
                        elif plugin.name == "horse_cart":
                            config["model_path"] = settings.horse_cart_model_path
                        elif plugin.name in ("person_detection", "vehicle_detection"):
                            # Usa modelo YOLO padrão (object.pt / yolov8n.pt)
                            pass
                        elif plugin.name == "motion":
                            # MOG2 — não precisa de modelo YOLO
                            config["model_path"] = None
                        await plugin.initialize(config)
                        self._plugins.append(plugin)
                        logger.info(
                            "Plugin carregado: %s v%s",
                            plugin.name,
                            plugin.version,
                        )
            except Exception:
                logger.exception("Erro ao carregar plugin %s", name)

        # Criar shared inference engines para plugins que compartilham modelo
        await self._build_shared_engines(settings)

    async def _build_shared_engines(self, settings: Any) -> None:
        """
        Cria SharedInferenceEngine para modelos compartilhados.

        Plugins que usam o mesmo modelo (ex: object.pt) compartilham
        uma única engine. A união de todas as classes necessárias
        é computada para maximizar eficiência.
        """
        # Determinar quais plugins podem usar shared inference
        model_path = settings.yolo_model_path
        model_key = model_path.split("/")[-1]  # "object.pt"

        if model_key in SHARED_MODELS:
            plugin_names = SHARED_MODELS[model_key]
            # Filtrar apenas plugins que foram carregados
            loaded_plugin_names = {p.name for p in self._plugins}
            active_plugin_names = plugin_names & loaded_plugin_names

            if active_plugin_names:
                # Unir todas as classes necessárias
                all_classes: set[int] = set()
                for pname in active_plugin_names:
                    all_classes |= PLUGIN_CLASSES.get(pname, set())

                engine = SharedInferenceEngine(
                    model_path=model_path,
                    imgsz=settings.yolo_imgsz,
                    name=f"shared:{model_key}",
                )
                engine_key = f"shared:{model_key}"
                self._shared_engines[engine_key] = engine
                logger.info(
                    "Shared engine criada para %s: %d classes (%s) para plugins: %s",
                    model_key,
                    len(all_classes),
                    sorted(all_classes),
                    sorted(active_plugin_names),
                )

                # Registrar quais plugins usam esta engine
                for pname in active_plugin_names:
                    self._plugin_uses_shared[pname] = engine_key

                # Armazenar classes unidas na engine para acesso rápido
                engine._all_classes = all_classes  # type: ignore[attr-defined]

    async def _compute_gpu_semaphore(self) -> asyncio.Semaphore:
        """Calcula concorrência segura baseada na VRAM livre.

        Em CPU-only, usa settings.analytics_workers como fallback estático.
        """
        settings = get_settings()
        try:
            import torch

            if torch.cuda.is_available():
                free_mb = torch.cuda.mem_get_info()[0] // (1024**2)
                model_vram_mb = 800  # YOLOv8n em inferência consome ~800 MB VRAM
                concurrency = max(1, min(8, int(free_mb * 0.8) // model_vram_mb))
                logger.info(
                    "GPU: %d MB VRAM livre → semaphore=%d workers paralelos",
                    free_mb,
                    concurrency,
                )
                return asyncio.Semaphore(concurrency)
        except Exception:
            logger.debug("torch.cuda indisponível — usando concorrência estática")
        concurrency = max(1, settings.analytics_workers)
        logger.info("CPU mode: semaphore=%d (analytics_workers)", concurrency)
        return asyncio.Semaphore(concurrency)

    async def start(self) -> None:
        """Descobre câmeras via VMS API e inicia captura."""
        await self._vms_client.start()
        self._running = True
        self._gpu_semaphore = await self._compute_gpu_semaphore()

        # Retry until VMS API is reachable (race condition at container startup)
        cameras: list[dict] = []
        for attempt in range(1, 11):
            cameras = await self._vms_client.list_cameras()
            if cameras:
                break
            logger.warning("VMS API sem câmeras (tentativa %d/10) — aguardando 10s", attempt)
            await asyncio.sleep(10)
        if not cameras:
            logger.warning("Nenhuma câmera disponível via VMS API após 10 tentativas")

        zones_config = await self._fetch_zones_config()

        for cam in cameras:
            await self._maybe_start_camera_task(cam, zones_config)

        self._batch_task = asyncio.create_task(self._batch_inference_loop(), name="batch-inference")
        # Câmeras adicionadas/ativadas depois do startup não eram descobertas
        # nunca mais — o ROI delas nunca chegava a rodar (achado durante teste
        # local: câmera criada com o processo já no ar ficava sem análise até
        # reiniciar o container). Re-varre periodicamente.
        self._discovery_task = asyncio.create_task(
            self._camera_discovery_loop(), name="camera-discovery"
        )

        logger.info(
            "Orchestrator iniciado: %d câmeras online, %d plugins ativos",
            len(self._camera_tasks),
            len(self._plugins),
        )

    async def _fetch_zones_config(self) -> dict[str, list[ROIConfig]]:
        """Busca ROIs da API (todas as câmeras); fallback para zones.yaml local."""
        api_rois = await self._vms_client.list_rois()
        if not api_rois:
            zones_config = load_zones_config()
            logger.info("ROIs locais (zones.yaml): %d câmeras configuradas", len(zones_config))
            return zones_config

        zones_config: dict[str, list[ROIConfig]] = {}
        for roi in api_rois:
            # Zona com horário de ativação fora da janela atual — não processar.
            # A API já resolve isso em `is_armed_now` (ver vms.analytics.schedule);
            # o refresh de 60s abaixo garante que a zona volta a ser considerada
            # assim que a janela armada começar.
            if not roi.get("is_armed_now", True):
                continue
            cam_id = roi["camera_id"]
            zones_config.setdefault(cam_id, []).append(
                ROIConfig(
                    id=roi["id"],
                    name=roi["name"],
                    ia_type=roi["plugin_id"],
                    polygon_points=roi["polygon_points"],
                    config=roi.get("config", {}),
                )
            )
        logger.info(
            "ROIs carregadas da API: %d zonas em %d câmeras", len(api_rois), len(zones_config)
        )
        return zones_config

    async def _maybe_start_camera_task(
        self, cam: dict, zones_config: dict[str, list[ROIConfig]]
    ) -> None:
        """Inicia a task de processamento da câmera, se online e ainda não rastreada."""
        cam_id = cam["id"]
        if cam_id in self._camera_tasks:
            return
        if not cam.get("is_online", False):
            logger.debug("Câmera %s offline — ignorando", cam_id)
            return

        settings = get_settings()

        # Volta a ler pelo MediaMTX (como era antes) em vez de conectar direto
        # na câmera. Cheguei a mudar pra conexão direta pra não depender do
        # ciclo de vida do path "sourceOnDemand" (só existe com viewer
        # assistindo) — mas isso criava uma SEGUNDA conexão RTSP simultânea
        # à câmera (MediaMTX + analytics), e essa câmera especificamente não
        # tolera bem 2 clientes concorrentes (achado em teste local: aumento
        # de reconexões, e depois o próprio muxer HLS do MediaMTX passou a
        # crashar com "too many reordered frames"). Como o analytics agora
        # é um leitor PERMANENTE do path (roda em loop enquanto a câmera
        # estiver online), ele sozinho já mantém o path sempre "quente" —
        # não fica mais refém de um viewer humano estar olhando. Isso resolve
        # o problema original (captura não pode depender do streaming) sem
        # precisar de uma segunda conexão física à câmera.
        rtsp_url = self._build_mediamtx_rtsp(cam)
        if not rtsp_url:
            # Câmeras sem path MediaMTX ainda provisionado: cai pro RTSP
            # nativo direto como último recurso.
            rtsp_url = cam.get("rtsp_url")
        if not rtsp_url:
            token_data = await self._vms_client.get_stream_token(cam_id)
            if not token_data:
                logger.warning("Sem token de stream para câmera %s", cam_id)
                return
            rtsp_url = token_data["rtsp_url"]

        task = asyncio.create_task(
            self._process_camera(
                camera_id=cam_id,
                tenant_id=cam.get("tenant_id", ""),
                rtsp_url=rtsp_url,
                fps=settings.analytics_fps,
                zones=zones_config.get(cam_id, []),
            )
        )
        self._camera_tasks[cam_id] = task
        logger.info("Câmera %s entrou online — processamento iniciado", cam_id)

    async def _camera_discovery_loop(self, interval: float = 20.0) -> None:
        """Re-varre a lista de câmeras periodicamente.

        Pega câmeras que ficaram online (ou foram criadas) depois do startup,
        e derruba a task de câmeras que saíram/foram desativadas.
        """
        while self._running:
            await asyncio.sleep(interval)
            try:
                cameras = await self._vms_client.list_cameras()
            except Exception:
                logger.exception("Falha ao re-listar câmeras — tentando de novo em %ds", interval)
                continue

            zones_config = await self._fetch_zones_config()
            online_ids = {cam["id"] for cam in cameras if cam.get("is_online", False)}

            for cam in cameras:
                await self._maybe_start_camera_task(cam, zones_config)

            for cam_id in list(self._camera_tasks):
                if cam_id not in online_ids:
                    logger.info("Câmera %s saiu — encerrando processamento", cam_id)
                    task = self._camera_tasks.pop(cam_id)
                    task.cancel()

    def _prefer_substream(self, rtsp_url: str, manufacturer: str | None) -> str:
        """Reescreve URL RTSP da Hikvision pro sub-stream (ex: .../Channels/101 -> .../Channels/102).

        Convenção Hikvision: "Channels/{canal}01" é o stream principal (full
        HD, usado por MediaMTX/preview), "Channels/{canal}02" é o sub-stream
        (resolução menor, mesmo encoder de vídeo mas perfil mais leve).
        Só reescreve se o padrão bater e o fabricante for hikvision — outras
        marcas/URLs ficam como estão.
        """
        if (manufacturer or "").lower() != "hikvision":
            return rtsp_url
        match = re.search(r"/Streaming/Channels/(\d+)01(?=$|[/?])", rtsp_url)
        if not match:
            return rtsp_url
        return rtsp_url[: match.start(1)] + match.group(1) + "02" + rtsp_url[match.end(1) + 2 :]

    def _build_mediamtx_rtsp(self, camera: dict) -> str | None:
        """
        Constrói URL RTSP direto do MediaMTX para câmera online.

        Usa mediamtx_path da câmera (ex: tenant-xxx/cam-yyy) para montar:
        rtsp://mediamtx:8554/tenant-xxx/cam-yyy

        Retorna None se não há mediamtx_path ou mediamtx_host configurado.
        """
        mediamtx_path = camera.get("mediamtx_path")
        if not mediamtx_path:
            logger.debug(
                "Câmera %s sem mediamtx_path — impossível construir RTSP local",
                camera.get("id"),
            )
            return None

        settings = get_settings()
        host = settings.mediamtx_host
        rtsp_port = getattr(settings, "mediamtx_rtsp_port", 8554)

        # URL RTSP simples (sem token JWT)
        rtsp_url = f"rtsp://{host}:{rtsp_port}/{mediamtx_path}"
        logger.info(
            "RTSP local construído para câmera %s: %s",
            camera.get("id"),
            rtsp_url,
        )
        return rtsp_url

    async def stop(self) -> None:
        """Para captura e encerra todos os plugins."""
        self._running = False

        all_tasks: list[asyncio.Task] = list(self._camera_tasks.values())
        if self._batch_task:
            all_tasks.append(self._batch_task)
        if self._discovery_task:
            all_tasks.append(self._discovery_task)

        for task in all_tasks:
            task.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)

        self._camera_tasks.clear()
        self._batch_task = None
        self._discovery_task = None

        for plugin in self._plugins:
            await plugin.shutdown()
        self._plugins.clear()

        await self._vms_client.close()
        logger.info("Orchestrator encerrado")

    async def _batch_inference_loop(self) -> None:
        """Coleta frames de múltiplas câmeras e executa inferência em batch.

        Cada câmera deposita (engine, frame, future) na _frame_queue e suspende.
        Este loop acumula até _MAX_BATCH itens dentro de _BATCH_WINDOW segundos,
        chama engine.predict_batch([frames]), e resolve cada future com seu resultado.

        Ganho: overhead fixo do YOLO (sync GPU, kernel launch) é pago uma vez
        por batch em vez de uma vez por câmera — reduz tempo total ≈30–50% com
        4+ câmeras simultâneas.
        """
        import time as _time
        from collections import defaultdict

        while True:
            batch: list[tuple] = []
            try:
                # Bloqueia até o primeiro frame
                item = await self._frame_queue.get()
                batch.append(item)

                # Coleta mais frames dentro da janela
                deadline = asyncio.get_event_loop().time() + self._BATCH_WINDOW
                while len(batch) < self._MAX_BATCH:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._frame_queue.get(), timeout=remaining)
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

            except asyncio.CancelledError:
                # Drain e resolve pending futures com lista vazia
                while not self._frame_queue.empty():
                    try:
                        batch.append(self._frame_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                for *_, future in batch:
                    if not future.done():
                        future.set_result([])
                raise

            if not batch:
                continue

            # Agrupa por engine (geralmente 1, mas futuro-proof para múltiplos modelos)
            by_engine: dict[str, list] = defaultdict(list)
            for item in batch:
                by_engine[item[0].name].append(item)

            for engine_name, items in by_engine.items():
                engine: SharedInferenceEngine = items[0][0]
                frames = [item[1] for item in items]
                futures = [item[2] for item in items]
                all_classes = getattr(engine, "_all_classes", None)

                try:
                    t0 = _time.monotonic()
                    async with self._gpu_semaphore:
                        all_detections = engine.predict_batch(frames, classes=all_classes)
                    elapsed_ms = (_time.monotonic() - t0) * 1000
                    logger.debug(
                        "Batch: %d frames → %.0fms total (%.1fms/frame)",
                        len(frames),
                        elapsed_ms,
                        elapsed_ms / len(frames),
                    )
                    for future, detections in zip(futures, all_detections):
                        if not future.done():
                            future.set_result(detections)
                except Exception as exc:
                    logger.exception("Erro em batch inference: %d frames", len(frames))
                    for future in futures:
                        if not future.done():
                            future.set_exception(exc)
                finally:
                    del frames  # libera referências — camera tasks mantêm a sua própria ref

    async def _process_camera(
        self,
        camera_id: str,
        tenant_id: str,
        rtsp_url: str,
        fps: int,
        zones: list[ROIConfig],
    ) -> None:
        """Loop de processamento de uma câmera individual."""
        source = FrameSource(rtsp_url, fps=fps)
        if not source.open():
            logger.error("Não foi possível abrir câmera %s: %s", camera_id, rtsp_url)
            return

        # Separar plugins que usam shared inference vs standalone
        shared_plugins: list[AnalyticsPlugin] = []
        standalone_plugins: list[AnalyticsPlugin] = []
        for plugin in self._plugins:
            if plugin.name in self._plugin_uses_shared:
                shared_plugins.append(plugin)
            else:
                standalone_plugins.append(plugin)

        # Buscar plugins ativos para esta câmera (filtro por PluginInstallation)
        active_plugin_names = await self._vms_client.get_active_plugins_for_camera(camera_id)
        # Se API retornar vazio (endpoint não existe ou falha), usar todos os plugins
        use_plugin_filter = len(active_plugin_names) > 0

        def is_plugin_active(plugin_name: str) -> bool:
            if not use_plugin_filter:
                return True
            return plugin_name in active_plugin_names

        # Filtrar plugins ativos
        shared_plugins = [p for p in shared_plugins if is_plugin_active(p.name)]
        standalone_plugins = [p for p in standalone_plugins if is_plugin_active(p.name)]

        if not shared_plugins and not standalone_plugins:
            logger.debug(
                "Nenhum plugin ativo para câmera %s — pulando processamento",
                camera_id,
            )
            source.close()
            return

        import time as _time

        _last_zone_refresh = 0.0
        _ZONE_REFRESH_INTERVAL = 60.0
        current_zones: list[ROIConfig] = list(zones)

        try:
            _gc_counter = 0
            while self._running:
                # Refresh zones every 60s so newly configured ROIs are picked up
                _now = _time.monotonic()
                if _now - _last_zone_refresh > _ZONE_REFRESH_INTERVAL:
                    fresh_rois = await self._vms_client.list_rois(camera_id)
                    current_zones = [
                        ROIConfig(
                            id=roi["id"],
                            name=roi["name"],
                            ia_type=roi["plugin_id"],
                            polygon_points=roi["polygon_points"],
                            config=roi.get("config", {}),
                        )
                        for roi in fresh_rois
                        if roi.get("is_armed_now", True)
                    ]
                    _last_zone_refresh = _now
                    if current_zones:
                        logger.debug(
                            "Zonas atualizadas para câmera %s: %d ROIs",
                            camera_id,
                            len(current_zones),
                        )

                frame = source.read()
                if frame is None:
                    await asyncio.sleep(0.05)
                    continue

                metadata = FrameMetadata(
                    camera_id=camera_id,
                    tenant_id=tenant_id,
                    timestamp=__import__("datetime").datetime.utcnow(),
                    stream_url=rtsp_url,
                )

                # 1. Shared inference via batch queue — sem GPU semaphore aqui.
                #    O _batch_inference_loop coleta frames de N câmeras e chama
                #    engine.predict_batch([...]) uma única vez sob o semaphore.
                if shared_plugins and self._shared_engines:
                    engine_key = next(iter(self._shared_engines))
                    engine = self._shared_engines[engine_key]
                    all_classes = getattr(engine, "_all_classes", set())

                    future: asyncio.Future[list] = asyncio.get_running_loop().create_future()
                    await self._frame_queue.put((engine, frame, future))

                    t_sub = _time.monotonic()
                    try:
                        shared_detections = await asyncio.wait_for(future, timeout=30.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Batch inference timeout câmera %s — frame descartado", camera_id
                        )
                        shared_detections = []

                    self._metrics.record_inference(
                        camera_id,
                        (_time.monotonic() - t_sub) * 1000,
                        len(shared_detections),
                    )

                    should_process = self._detection_cache.should_process(
                        camera_id, shared_detections
                    )

                    if should_process:
                        # Save one snapshot per processed frame — shared across all plugins
                        frame_snap: str | None = None
                        frame_snap_saved = False

                        for plugin in shared_plugins:
                            try:
                                plugin_classes = PLUGIN_CLASSES.get(plugin.name, set())
                                plugin_detections = engine.filter_by_class(
                                    shared_detections, plugin_classes
                                )
                                results = await plugin.process_shared_frame(
                                    plugin_detections, frame, metadata, current_zones
                                )
                                if results and not frame_snap_saved:
                                    frame_snap = await self._save_snapshot(frame, tenant_id, camera_id)
                                    frame_snap_saved = True
                                for result in results:
                                    await self._send_result(result, snapshot_path=frame_snap)
                                    self._metrics.record_event(result.plugin, result.event_type)
                            except Exception:
                                logger.exception(
                                    "Erro no plugin shared %s câmera %s",
                                    plugin.name,
                                    camera_id,
                                )

                # 2. Standalone inference: plugins com modelo próprio usam semaphore direto
                if standalone_plugins:
                    async with self._gpu_semaphore:
                        standalone_snap: str | None = None
                        standalone_snap_saved = False
                        for plugin in standalone_plugins:
                            try:
                                results = await plugin.process_frame(frame, metadata, current_zones)
                                if results and not standalone_snap_saved:
                                    standalone_snap = await self._save_snapshot(frame, tenant_id, camera_id)
                                    standalone_snap_saved = True
                                for result in results:
                                    await self._send_result(result, snapshot_path=standalone_snap)
                                    self._metrics.record_event(result.plugin, result.event_type)
                            except Exception:
                                logger.exception(
                                    "Erro no plugin standalone %s câmera %s",
                                    plugin.name,
                                    camera_id,
                                )

                del frame
                _gc_counter += 1
                if _gc_counter >= 30:
                    gc.collect(0)
                    _gc_counter = 0
        finally:
            source.close()

    async def _save_snapshot(
        self,
        frame: "np.ndarray",
        tenant_id: str,
        camera_id: str,
    ) -> str | None:
        """Salva frame como JPEG na resolução original da câmera.

        `frame` aqui é sempre o frame cheio vindo de source.read() — o
        downscale pra 640px (SharedInferenceEngine._downscale_if_needed) só
        existe DENTRO da inferência YOLO e nunca troca essa variável; as
        bboxes retornadas já vêm normalizadas (0.0-1.0), então escalam
        corretamente pra qualquer resolução (achado: investigação confirmou
        que o snapshot salvo já é full-res — 1920x1080 verificado direto no
        arquivo — a baixa qualidade percebida era falta de bounding box e
        compressão JPEG mais agressiva que o necessário, não downscale).

        O bbox do evento (normalizado [x1,y1,x2,y2], 0.0-1.0) vai salvo à
        parte no payload do evento — o retângulo vermelho é desenhado como
        overlay no frontend (ver `AnalyticsEventsPage.tsx`), nunca gravado
        nos pixels do arquivo. Gravar a box no JPEG contaminava tanto a
        evidência bruta quanto o recorte usado pela IA no "Analisar Evento":
        a linha vermelha cruzando o sujeito atrapalhava a detecção de rosto
        do GFPGAN (derrubando pro fallback EDSR) e o upscale reproduzia as
        bordas da box como se fossem parte da cena real.
        """
        import os
        import uuid
        import cv2
        from datetime import date as _date

        try:
            today = _date.today().isoformat()
            snap_dir = f"/snapshots/{tenant_id}/{camera_id}/{today}"
            os.makedirs(snap_dir, exist_ok=True)
            filename = f"{uuid.uuid4()}.jpg"
            full_path = f"{snap_dir}/{filename}"

            # Qualidade 95 (era 80) — o arquivo já é full-res, não faz
            # sentido perder detalhe extra na compressão por cima disso.
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                return None
            with open(full_path, "wb") as fh:
                fh.write(buf.tobytes())
            return f"{tenant_id}/{camera_id}/{today}/{filename}"
        except Exception:
            logger.exception("Erro ao salvar snapshot: camera=%s", camera_id)
            return None

    async def _send_result(
        self,
        result: AnalyticsResult,
        *,
        snapshot_path: str | None = None,
    ) -> None:
        """Envia resultado do plugin ao VMS via contrato público."""
        payload: dict[str, Any] = {
            "plugin": result.plugin,
            **result.payload,
        }
        if result.roi_id:
            payload["roi_id"] = result.roi_id

        await self._vms_client.ingest_event(
            camera_id=result.camera_id,
            event_type=result.event_type,
            payload=payload,
            confidence=result.confidence,
            occurred_at=result.occurred_at.isoformat(),
            snapshot_path=snapshot_path,
        )
