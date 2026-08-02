"""Gerenciador de processos ffmpeg para streaming RTSP→RTMP."""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Backoff exponencial com teto, retry indefinido — mesmo padrão já usado em
# `analytics/core/outbox.py` (5s, 10s, 20s... até 5min). Até 2026-08-02 este
# módulo desistia de vez depois de `_MAX_RESTART_ATTEMPTS` tentativas com
# delay fixo (25s de janela total) — achado testando uma câmera Wi-Fi real:
# a conexão RTSP cai por instabilidade de rede (comum em câmera doméstica),
# se recupera sozinha minutos depois, mas o agent já tinha desistido pra
# sempre daquela câmera até alguém reiniciar o serviço inteiro. Nenhum
# cliente real deveria depender de reiniciar o agent porque o Wi-Fi da
# câmera piscou.
_INITIAL_RESTART_DELAY_SECONDS = 5.0
_MAX_RESTART_DELAY_SECONDS = 300.0
# Últimos N bytes do stderr do ffmpeg mantidos em memória por processo —
# o bastante pra uma mensagem de erro típica, sem acumular um vazamento se
# o processo rodar (e falhar) por muito tempo.
_STDERR_TAIL_BYTES = 4096


@dataclass
class StreamProcess:
    """Estado de um processo ffmpeg ativo."""

    camera_id: str
    rtsp_url: str
    rtmp_url: str
    process: asyncio.subprocess.Process | None = None
    restart_count: int = 0
    # Timestamp monotônico (`time.monotonic()`) de quando a próxima
    # tentativa é permitida — backoff sem bloquear `restart_dead_streams`
    # (ver nota em `restart_dead_streams`).
    next_retry_at: float = 0.0
    # Últimas linhas do stderr do ffmpeg — só existe pra aparecer no log
    # quando o processo morre; nunca lido em operação normal.
    _stderr_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _stderr_tail: bytes = field(default=b"", init=False, repr=False)
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

    def __init__(self, mediamtx_rtmp_base: str, ffmpeg_path: str | None = None) -> None:
        """Inicializa o gerenciador.

        Args:
            mediamtx_rtmp_base: URL base RTMP, ex.: rtmp://mediamtx:1935
            ffmpeg_path: caminho do binário ffmpeg. None busca no PATH
                (padrão no container Docker) — o instalador nativo passa o
                caminho absoluto do ffmpeg bundlado.
        """
        self._rtmp_base = mediamtx_rtmp_base.rstrip("/")
        self._ffmpeg_path = ffmpeg_path or "ffmpeg"
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
        """Reinicia processos ffmpeg que morreram inesperadamente.

        Backoff exponencial com teto (5s → 10s → 20s... até 5min),
        **nunca desiste de vez**: uma câmera Wi-Fi instável se recupera
        sozinha minutos depois, e nenhum cliente deveria precisar reiniciar
        o serviço inteiro porque uma câmera piscou (achado testando uma
        câmera doméstica real — ver nota em `_INITIAL_RESTART_DELAY_SECONDS`).

        Não bloqueia com `sleep`: cada câmera guarda seu próprio
        `next_retry_at` e é pulada até a hora chegar. Um `sleep` aqui dentro
        atrasaria a checagem de TODAS as outras câmeras no mesmo ciclo —
        inofensivo com o delay fixo antigo (5s), mas seria grave com o teto
        de 5min desta versão.
        """
        now = time.monotonic()
        for camera_id, sp in list(self._streams.items()):
            if sp.process is None:
                continue

            if sp._running:  # noqa: SLF001
                if sp.process.returncode is None:
                    continue  # ainda rodando normalmente

                # Acabou de morrer nesta checagem — registra e agenda a
                # próxima tentativa, mas não relança no mesmo ciclo (o
                # health_checker roda de novo em 10s; esperar por ele em
                # vez de um `sleep` aqui evita atrasar a checagem das
                # outras câmeras neste mesmo `restart_dead_streams`).
                tail = sp._stderr_tail.decode("utf-8", errors="replace").strip()  # noqa: SLF001
                logger.warning(
                    "ffmpeg morreu para câmera %s (código %s)%s",
                    camera_id, sp.process.returncode,
                    f" — stderr: {tail[-500:]}" if tail else "",
                )
                sp._running = False  # noqa: SLF001
                # `min(sp.restart_count, 6)` no expoente: acima disso o
                # delay já bateu no teto de qualquer forma (2**6*5s=320s >
                # 300s), e sem o cap, um expoente crescendo por dias de
                # falha contínua eventualmente estoura (`OverflowError` ao
                # converter um int gigante pra float) — sem necessidade,
                # já que o resultado seria descartado pelo `min` de fora.
                delay = min(
                    _INITIAL_RESTART_DELAY_SECONDS * (2 ** min(sp.restart_count, 6)),
                    _MAX_RESTART_DELAY_SECONDS,
                )
                sp.next_retry_at = now + delay
                logger.info("Câmera %s: nova tentativa em %.0fs", camera_id, delay)
                continue

            # Já estava marcado como morto de um ciclo anterior — só
            # relança quando o backoff tiver vencido.
            if now < sp.next_retry_at:
                continue

            sp.restart_count += 1
            await self._launch(sp)

    async def _launch(self, sp: StreamProcess) -> None:
        """Lança o processo ffmpeg para um StreamProcess."""
        ffmpeg_bin = self._ffmpeg_path
        if ffmpeg_bin == "ffmpeg" and not shutil.which("ffmpeg"):
            logger.error("ffmpeg não encontrado no PATH")
            return

        cmd = [
            ffmpeg_bin,
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
            sp._stderr_tail = b""  # noqa: SLF001
            sp._stderr_task = asyncio.create_task(self._drain_stderr(sp))  # noqa: SLF001
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
    async def _drain_stderr(sp: StreamProcess) -> None:
        """Lê o stderr do ffmpeg continuamente, guardando só o final.

        Duas razões pra existir, não só diagnóstico: um pipe do SO tem
        buffer limitado (tipicamente 64KB) — se ninguém lê o stderr, o
        ffmpeg pode travar esperando espaço pra escrever nele assim que o
        buffer enche. Sem isto, a mensagem de erro real (ex.: o `-10054`
        que expôs o gap de retry-para-sempre acima) nunca aparecia em
        lugar nenhum — só foi possível descobrir reproduzindo o comando na
        mão fora do agent.
        """
        assert sp.process is not None and sp.process.stderr is not None
        try:
            async for line in sp.process.stderr:
                sp._stderr_tail = (sp._stderr_tail + line)[-_STDERR_TAIL_BYTES:]  # noqa: SLF001
        except Exception:
            pass

    @staticmethod
    async def _terminate(sp: StreamProcess) -> None:
        """Encerra um processo ffmpeg graciosamente."""
        sp._running = False  # noqa: SLF001
        if sp._stderr_task is not None:  # noqa: SLF001
            sp._stderr_task.cancel()  # noqa: SLF001
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
