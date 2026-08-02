"""Cliente HTTP para comunicação com a VMS API via contrato público de plugins."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from analytics.core.config import get_settings
from analytics.core.outbox import EventOutbox, SendOutcome, run_retry_loop

logger = logging.getLogger(__name__)

# Base local dos snapshots — mesma convenção hardcoded usada por
# `Orchestrator._save_snapshot` (analytics) e `SNAPSHOTS_DIR` (api, mesmo
# valor default). Só relevante quando `edge_deployment=True`: é onde o
# JPEG referenciado por `snapshot_path` existe de fato, no disco local.
_SNAPSHOTS_BASE_DIR = Path(os.environ.get("SNAPSHOTS_PATH", "/snapshots"))

# Teto do `Retry-After` que aceitamos da VPS. Um valor absurdo (bug do lado
# dela, ou header hostil de um proxy no meio do caminho) congelaria a fila
# inteira do cliente por horas sem que ninguém percebesse.
_MAX_RETRY_AFTER_SECONDS = 900
_DEFAULT_RETRY_AFTER_SECONDS = 30


def _retry_after_seconds(response: httpx.Response) -> int:
    """Lê `Retry-After` da resposta, com default e teto sensatos.

    Só a forma em segundos é interpretada — a variante HTTP-date do RFC 9110
    exige confiar no relógio do cliente, que num mini-PC sem NTP é justamente
    o que não dá pra assumir.
    """
    raw = response.headers.get("Retry-After", "")
    try:
        seconds = int(float(raw))
    except (TypeError, ValueError):
        seconds = _DEFAULT_RETRY_AFTER_SECONDS
    return max(1, min(seconds, _MAX_RETRY_AFTER_SECONDS))


class _RetryableError(Exception):
    """Erro transitório (rede, timeout, 5xx da VPS) — vale enfileirar para retry.

    Distinto de um `httpx.HTTPStatusError` 4xx, que indica um problema no
    próprio conteúdo do evento (validação) — reenfileirar não ajudaria.
    """


class _ThrottledError(_RetryableError):
    """A VPS recusou por cota (429) e disse por quanto tempo esperar.

    É um 4xx que, ao contrário dos outros, **deve** ser reenfileirado: não há
    nada errado com o evento, só com o ritmo. Carrega o `Retry-After` para o
    outbox adiar a fila inteira em vez de queimar tentativas item a item (ver
    ADR-018 §5 e `EventOutbox.defer_all`).
    """

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Cota de ingestão excedida — aguardar {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class VMSClient:
    """
    Cliente assíncrono para o contrato público de plugins do VMS.

    Autentica com API key de plugin via header Authorization: ApiKey <key>.
    Todos os endpoints usados são públicos — nenhum endpoint interno.

    Resiliência a queda de rede (ver ADR-017 §2/§3 — motivada pelo Nível 1,
    onde a VPS central fica a um túnel WireGuard de distância):
    - `list_cameras`/`list_rois`/`list_watchlist` mantêm um cache em memória
      do último resultado bem-sucedido e o retornam (em vez de lista vazia)
      quando a chamada de rede falha.
    - `ingest_event` grava numa fila de retry local (SQLite, `EventOutbox`)
      quando o POST falha por erro de rede/timeout/5xx, e um loop assíncrono
      em background reenvia com backoff exponencial até confirmar sucesso.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.vms_api_url
        self._api_key = settings.vms_api_key
        self._mediamtx_host = settings.mediamtx_host
        self._edge_deployment = settings.edge_deployment
        self._client: httpx.AsyncClient | None = None

        # Cache last-known-good (ver ADR-017 §3, gap corrigido neste sprint).
        self._cameras_cache: list[dict[str, Any]] = []
        self._rois_cache: dict[str | None, list[dict[str, Any]]] = {}
        self._watchlist_cache: list[dict[str, Any]] = []

        # Fila de retry local (ver ADR-017 §2, com cap da ADR-018 §5).
        self._outbox = EventOutbox(
            settings.outbox_db_path,
            max_rows=settings.outbox_max_rows,
            max_age_seconds=settings.outbox_max_age_seconds,
        )
        self._retry_task: asyncio.Task[None] | None = None

        # ARQ pool pro Redis LOCAL — só usado quando edge_deployment=True,
        # pra avisar o worker de edge (EdgeWorkerSettings, api/vms/worker_edge.py)
        # que um evento foi confirmadamente ingerido e o clipe pode ser gerado
        # localmente (ver ADR-017 §1). Nunca aponta pro Redis da VPS central.
        self._arq_pool: Any | None = None

    async def start(
        self,
        transport: httpx.BaseTransport | None = None,
        retry_poll_interval: float = 5.0,
    ) -> None:
        """Inicializa o cliente HTTP e o loop de retry do outbox.

        `transport`/`retry_poll_interval` existem para permitir testes reais
        de queda de rede (ver `analytics/tests/test_vms_client_resilience.py`)
        sem depender de rede de verdade nem esperar o intervalo de poll
        default inteiro.
        """
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"ApiKey {self._api_key}",
                "X-MediaMTX-Host": self._mediamtx_host,
            },
            timeout=httpx.Timeout(10.0),
            transport=transport,
        )
        self._retry_task = asyncio.create_task(
            run_retry_loop(self._outbox, self._post_event_payload, poll_interval=retry_poll_interval)
        )

        if self._edge_deployment:
            from arq import create_pool
            from arq.connections import RedisSettings as ArqRedisSettings

            self._arq_pool = await create_pool(
                ArqRedisSettings.from_dsn(get_settings().redis_url)
            )

    async def close(self) -> None:
        """Fecha o cliente HTTP e cancela o loop de retry do outbox."""
        if self._retry_task:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
            self._retry_task = None
        if self._arq_pool:
            await self._arq_pool.close()
            self._arq_pool = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_cameras(self) -> list[dict[str, Any]]:
        """
        Busca câmeras ativas do tenant via GET /api/v1/plugins/cameras.

        Retorna lista de dicts com id, name, stream_protocol, is_online, mediamtx_path.
        Em erro de rede, retorna o último resultado bem-sucedido (cache
        last-known-good) — ou lista vazia se nunca houve sucesso.
        """
        if not self._client:
            return self._cameras_cache

        try:
            resp = await self._client.get("/api/v1/plugins/cameras")
            resp.raise_for_status()
            data = resp.json()
            self._cameras_cache = data
            return data  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.warning(
                "Erro ao listar câmeras do VMS — usando cache last-known-good (%d itens)",
                len(self._cameras_cache),
                exc_info=True,
            )
            return self._cameras_cache

    async def get_stream_token(self, camera_id: str) -> dict[str, Any] | None:
        """
        Obtém token de acesso RTSP para uma câmera via GET /api/v1/plugins/stream-token.

        Retorna dict com rtsp_url, token e expires_at, ou None em caso de erro.
        """
        if not self._client:
            return None

        try:
            resp = await self._client.get(
                "/api/v1/plugins/stream-token",
                params={"camera_id": camera_id},
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.exception("Erro ao obter stream token para câmera %s", camera_id)
            return None

    async def list_rois(self, camera_id: str | None = None) -> list[dict[str, Any]]:
        """
        Busca ROIs configuradas via GET /api/v1/plugins/rois.

        Retorna lista de dicts com id, name, camera_id, plugin_id, polygon_points, config.
        Em erro de rede, retorna o cache last-known-good (por `camera_id`).
        """
        if not self._client:
            return self._rois_cache.get(camera_id, [])
        try:
            params = {"camera_id": camera_id} if camera_id else {}
            resp = await self._client.get("/api/v1/plugins/rois", params=params)
            resp.raise_for_status()
            data = resp.json()
            self._rois_cache[camera_id] = data
            return data  # type: ignore[no-any-return]
        except httpx.HTTPError:
            cached = self._rois_cache.get(camera_id, [])
            logger.warning(
                "Erro ao buscar ROIs para câmera %s — usando cache last-known-good (%d itens)",
                camera_id,
                len(cached),
                exc_info=True,
            )
            return cached

    async def list_watchlist(self) -> list[dict[str, Any]]:
        """
        Busca a watchlist de reconhecimento facial via GET /api/v1/plugins/watchlist.

        Retorna lista vazia se o tenant não tiver consentimento LGPD ativo
        (gate aplicado do lado da API — ver ADR-014). Em erro de rede,
        retorna o cache last-known-good.
        """
        if not self._client:
            return self._watchlist_cache
        try:
            resp = await self._client.get("/api/v1/plugins/watchlist")
            resp.raise_for_status()
            data = resp.json()
            self._watchlist_cache = data
            return data  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.warning(
                "Erro ao buscar watchlist facial — usando cache last-known-good (%d itens)",
                len(self._watchlist_cache),
                exc_info=True,
            )
            return self._watchlist_cache

    async def ingest_event(
        self,
        camera_id: str,
        event_type: str,
        payload: dict[str, Any],
        confidence: float | None = None,
        occurred_at: str | None = None,
        snapshot_path: str | None = None,
        mediamtx_path: str | None = None,
    ) -> bool:
        """
        Envia evento detectado pelo plugin via POST /api/v1/plugins/events.

        Quando `edge_deployment=True` (Nível 1, ver ADR-017 §1), envia como
        multipart (JSON + arquivo do snapshot local) em vez de JSON puro —
        o JPEG só existe no disco de quem o gerou, então precisa viajar na
        mesma requisição — e inclui `edge_generates_clip=true` no corpo, pra
        a VPS central nunca rodar ffmpeg pra esse evento.

        Retorna `True` se o evento foi aceito pela VPS **agora** OU se foi
        enfileirado com sucesso na fila de retry local (SQLite) para reenvio
        automático em background — do ponto de vista do chamador
        (`Orchestrator`), os dois casos significam "nada mais a fazer aqui,
        o evento está a caminho". Só retorna `False` se não há client
        (`start()` não foi chamado) ou se a VPS rejeitou o evento por erro do
        próprio conteúdo (4xx) — reenfileirar não ajudaria nesse caso, o
        problema não é de rede.
        """
        if not self._client:
            return False

        body: dict[str, Any] = {
            "camera_id": camera_id,
            "event_type": event_type,
            "payload": payload,
        }
        if confidence is not None:
            body["confidence"] = confidence
        if occurred_at is not None:
            body["occurred_at"] = occurred_at
        if snapshot_path is not None:
            body["snapshot_path"] = snapshot_path
        if self._edge_deployment:
            body["edge_generates_clip"] = True

        local_snapshot_path: str | None = None
        if self._edge_deployment and snapshot_path:
            local_snapshot_path = str(_SNAPSHOTS_BASE_DIR / snapshot_path)

        # `mediamtx_path`/`occurred_at` não vão no corpo do evento — são só o
        # que a task local de clipe precisa pra achar a gravação contínua da
        # câmera (ADR-018 §4). Viajam junto no payload enfileirado pra
        # sobreviverem a um reenvio depois de queda de rede.
        clip_context = {"mediamtx_path": mediamtx_path, "occurred_at": occurred_at}

        try:
            result = await self._send_event(body, local_snapshot_path)
        except _RetryableError as exc:
            queued_payload = {
                "body": body,
                "local_snapshot_path": local_snapshot_path,
                "clip_context": clip_context,
            }
            try:
                await asyncio.to_thread(self._outbox.enqueue, queued_payload)
                if isinstance(exc, _ThrottledError):
                    # Adia a fila junto: sem isso, o loop de retry tentaria o
                    # backlog inteiro no próximo ciclo e tomaria 429 em cada
                    # item — exatamente o comportamento que a cota existe pra
                    # evitar (ADR-018 §5).
                    await asyncio.to_thread(self._outbox.defer_all, exc.retry_after_seconds)
                    logger.warning(
                        "VPS pediu backpressure (%ds) — evento enfileirado e fila adiada",
                        exc.retry_after_seconds,
                    )
                else:
                    logger.warning(
                        "Falha de rede ao enviar evento (camera=%s tipo=%s) — "
                        "enfileirado para retry local",
                        camera_id, event_type,
                    )
                return True
            except Exception:
                logger.exception("Falha ao enfileirar evento na fila local de retry")
                return False
        except httpx.HTTPStatusError:
            logger.exception(
                "VPS rejeitou o evento de plugin (erro do próprio conteúdo, não reenfileirado)"
            )
            return False

        if self._edge_deployment and local_snapshot_path:
            event_id = result.get("id") if isinstance(result, dict) else None
            if event_id:
                await self._enqueue_local_clip_task(event_id, local_snapshot_path, clip_context)

        return True

    async def _send_event(
        self, body: dict[str, Any], local_snapshot_path: str | None
    ) -> dict[str, Any]:
        """Faz o POST de fato (JSON ou multipart) e retorna o corpo da resposta.

        Levanta `_RetryableError` para falhas de rede/timeout/5xx (vale
        reenfileirar) e deixa `httpx.HTTPStatusError` (4xx) subir sem
        modificação — quem chama decide o que fazer com cada caso.
        """
        assert self._client is not None
        try:
            if local_snapshot_path and os.path.isfile(local_snapshot_path):
                with open(local_snapshot_path, "rb") as fh:
                    files = {
                        "snapshot_file": (
                            os.path.basename(local_snapshot_path),
                            fh.read(),
                            "image/jpeg",
                        )
                    }
                data = {"payload": json.dumps(body, default=str)}
                resp = await self._client.post("/api/v1/plugins/events", data=data, files=files)
            else:
                resp = await self._client.post("/api/v1/plugins/events", json=body)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise _ThrottledError(_retry_after_seconds(exc.response)) from exc
            if exc.response.status_code >= 500:
                raise _RetryableError(str(exc)) from exc
            raise
        except httpx.HTTPError as exc:
            raise _RetryableError(str(exc)) from exc

    async def _post_event_payload(self, queued_payload: dict[str, Any]) -> SendOutcome:
        """Callback usado pelo loop de retry do outbox (`run_retry_loop`).

        Mesma lógica de envio de `ingest_event`, mas nunca levanta: sucesso
        vira `delivered=True` (a linha é removida da fila) e qualquer falha
        vira `delivered=False` (a linha é reagendada com backoff). A única
        distinção que o outbox precisa fazer é entre "falhou" e "a VPS mandou
        esperar" — só o segundo caso adia a fila inteira (ADR-018 §5).
        """
        try:
            result = await self._send_event(
                queued_payload["body"], queued_payload.get("local_snapshot_path")
            )
        except _ThrottledError as exc:
            return SendOutcome(delivered=False, retry_after_seconds=exc.retry_after_seconds)
        except Exception:
            logger.debug("Outbox: reenvio ainda falhando", exc_info=True)
            return SendOutcome(delivered=False)

        local_snapshot_path = queued_payload.get("local_snapshot_path")
        if self._edge_deployment and local_snapshot_path:
            event_id = result.get("id") if isinstance(result, dict) else None
            if event_id:
                await self._enqueue_local_clip_task(
                    event_id, local_snapshot_path, queued_payload.get("clip_context") or {}
                )
        return SendOutcome(delivered=True)

    async def _enqueue_local_clip_task(
        self, event_id: str, local_snapshot_path: str, clip_context: dict[str, Any] | None = None
    ) -> None:
        """Avisa o worker de edge local (EdgeWorkerSettings, ver ADR-017 §1) que
        um evento foi confirmadamente ingerido pela VPS central — o worker
        gera o MP4 localmente (ffmpeg, mesmo hardware) e faz o PUT do clipe
        pra VPS. Enfileira no Redis LOCAL (mesmo Redis do compose de edge),
        nunca no da VPS central. Best-effort: falha aqui não afeta o retorno
        de `ingest_event` (o evento em si já foi confirmado).

        `clip_context` leva `mediamtx_path`/`occurred_at` — sem eles o worker
        não localiza a gravação contínua e o clipe volta a ser o freeze-frame
        do JPEG (ADR-018 §4)."""
        if not self._arq_pool:
            return
        context = clip_context or {}
        settings = get_settings()
        try:
            await self._arq_pool.enqueue_job(
                "task_render_and_upload_edge_clip",
                event_id,
                local_snapshot_path,
                settings.edge_clip_seconds,
                context.get("mediamtx_path"),
                context.get("occurred_at"),
            )
        except Exception:
            logger.exception(
                "Falha ao enfileirar task de clipe local pro evento %s (não crítico)", event_id
            )

    async def get_active_plugins_for_camera(self, camera_id: str) -> list[str]:
        """
        Busca plugins ativos para uma câmera específica.

        Retorna lista de nomes de plugins com status='running' para esta câmera.
        Se o endpoint não existir ou falhar, retorna lista vazia (fallback: todos ativos).
        """
        if not self._client:
            return []

        try:
            resp = await self._client.get(
                f"/api/v1/plugins/cameras/{camera_id}/active-plugins"
            )
            if resp.status_code == 404:
                # Endpoint não existe — fallback: todos os plugins ativos
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("active_plugins", [])
        except httpx.HTTPError:
            logger.debug(
                "Erro ao buscar plugins ativos para câmera %s (fallback: todos ativos)",
                camera_id,
            )
            return []
