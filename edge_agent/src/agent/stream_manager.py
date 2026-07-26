"""Gerenciador de processos ffmpeg para streaming RTSP→RTMP."""
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Constantes
_MAX_RESTART_ATTEMPTS = 5
_RESTART_DELAY_SECONDS = 5.0


@dataclass
class StreamProcess:
    """Estado de um processo ffmpeg ativo."""

    camera_id: str
    rtsp_url: str
    rtmp_url: str
    process: asyncio.subprocess.Process | None = None
    restart_count: int = 0
    _running: bool = field(default=False, init=False)

    @property
    def is_running(self) -> bool:
        """Retorna True se o processo está ativo."""
        return self._running and self.process is not None


class StreamManager:
    """Gerencia processos ffmpeg: start, stop e restart de streams.

    Cada câmera ativa tem um processo ffmpeg que captura o RTSP
    e faz push para o MediaMTX via RTMP.
    """

    def __init__(self, mediamtx_rtmp_base: str) -> None:
        """Inicializa o gerenciador.

        Args:
            mediamtx_rtmp_base: URL base RTMP, ex.: rtmp://mediamtx:1935
        """
        self._rtmp_base = mediamtx_rtmp_base.rstrip("/")
        self._streams: dict[str, StreamProcess] = {}

    @property
    def active_streams(self) -> list[str]:
        """Retorna IDs das câmeras com stream ativo."""
        return [cid for cid, sp in self._streams.items() if sp.is_running]

    def _build_rtmp_url(self, mediamtx_path: str) -> str:
        """Monta a URL RTMP completa para o MediaMTX."""
        return f"{self._rtmp_base}/{mediamtx_path}"

    async def start_stream(self, camera_id: str, rtsp_url: str, mediamtx_path: str) -> None:
        """Inicia ffmpeg para uma câmera.

        Args:
            camera_id: ID único da câmera.
            rtsp_url: URL RTSP da câmera.
            mediamtx_path: caminho no MediaMTX (ex.: tenant-x/cam-y).
        """
        if camera_id in self._streams and self._streams[camera_id].is_running:
            logger.debug("Stream %s já ativo — ignorando", camera_id)
            return

        rtmp_url = self._build_rtmp_url(mediamtx_path)
        sp = StreamProcess(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            rtmp_url=rtmp_url,
        )
        self._streams[camera_id] = sp
        await self._launch(sp)

    async def stop_stream(self, camera_id: str) -> None:
        """Para o ffmpeg de uma câmera.

        Args:
            camera_id: ID da câmera a parar.
        """
        sp = self._streams.pop(camera_id, None)
        if sp is None:
            return
        await self._terminate(sp)
        logger.info("Stream parado: %s", camera_id)

    async def stop_all(self) -> None:
        """Para todos os streams ativos."""
        camera_ids = list(self._streams.keys())
        for camera_id in camera_ids:
            await self.stop_stream(camera_id)
        logger.info("Todos os streams encerrados")

    async def reconcile(
        self,
        desired: dict[str, tuple[str, str]],
    ) -> None:
        """Reconcilia streams ativos com a lista desejada.

        Args:
            desired: mapa {camera_id: (rtsp_url, mediamtx_path)} das
                     câmeras que devem estar ativas.
        """
        current = set(self._streams.keys())
        desired_ids = set(desired.keys())

        # Remover câmeras que não estão mais na config
        for camera_id in current - desired_ids:
            logger.info("Câmera removida da config: %s — parando stream", camera_id)
            await self.stop_stream(camera_id)

        # Iniciar câmeras novas
        for camera_id in desired_ids - current:
            rtsp_url, mediamtx_path = desired[camera_id]
            logger.info("Nova câmera: %s — iniciando stream", camera_id)
            await self.start_stream(camera_id, rtsp_url, mediamtx_path)

    async def restart_dead_streams(self) -> None:
        """Reinicia processos ffmpeg que morreram inesperadamente."""
        for camera_id, sp in list(self._streams.items()):
            if sp.process is None:
                continue
            if sp.process.returncode is not None and sp._running:
                logger.warning(
                    "ffmpeg morreu para câmera %s (código %s) — reiniciando",
                    camera_id,
                    sp.process.returncode,
                )
                sp._running = False  # noqa: SLF001
                if sp.restart_count >= _MAX_RESTART_ATTEMPTS:
                    logger.error("Câmera %s atingiu limite de reinicializações", camera_id)
                    continue
                await asyncio.sleep(_RESTART_DELAY_SECONDS)
                sp.restart_count += 1
                await self._launch(sp)

    async def _launch(self, sp: StreamProcess) -> None:
        """Lança o processo ffmpeg para um StreamProcess."""
        if not shutil.which("ffmpeg"):
            logger.error("ffmpeg não encontrado no PATH")
            return

        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-i", sp.rtsp_url,
            "-c", "copy",
            "-f", "flv",
            sp.rtmp_url,
        ]
        try:
            sp.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            sp._running = True  # noqa: SLF001
            logger.info(
                "ffmpeg iniciado para câmera %s → %s (pid=%s)",
                sp.camera_id,
                sp.rtmp_url,
                sp.process.pid,
            )
        except OSError as exc:
            logger.error("Falha ao iniciar ffmpeg para câmera %s: %s", sp.camera_id, exc)
            sp._running = False  # noqa: SLF001

    @staticmethod
    async def _terminate(sp: StreamProcess) -> None:
        """Encerra um processo ffmpeg graciosamente."""
        sp._running = False  # noqa: SLF001
        if sp.process is None:
            return
        try:
            sp.process.terminate()
            await asyncio.wait_for(sp.process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                sp.process.kill()
            except ProcessLookupError:
                pass
