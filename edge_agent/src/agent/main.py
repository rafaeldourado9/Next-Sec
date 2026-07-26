"""Loop principal do Edge Agent."""
from __future__ import annotations

import asyncio
import logging
import signal

import structlog

from agent.cloud_client import CloudClient
from agent.config import get_settings
from agent.health_checker import HealthChecker
from agent.stream_manager import StreamManager

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _configure_logging(level: str) -> None:
    """Configura structlog para saída JSON em produção."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


class EdgeAgent:
    """Orquestra Cloud Client, Stream Manager e Health Checker.

    Ciclo de vida:
    1. startup() — cria clientes, busca config inicial
    2. run() — loops de poll + heartbeat + health check
    3. shutdown() — para streams e fecha conexões
    """

    def __init__(self) -> None:
        """Inicializa o agent com as configurações do ambiente."""
        self._settings = get_settings()
        self._client = CloudClient(self._settings)
        self._stream_manager = StreamManager(self._settings.mediamtx_rtmp_url)
        self._health_checker = HealthChecker(self._stream_manager)
        self._running = False

    async def startup(self) -> None:
        """Inicializa componentes e carrega config inicial."""
        await self._client.start()
        await self._health_checker.start()
        await self._sync_config()
        await self._client.send_heartbeat("online")
        self._running = True
        logger.info("EdgeAgent iniciado", agent_id=self._settings.agent_id)

    async def shutdown(self) -> None:
        """Encerra o agent graciosamente."""
        self._running = False
        try:
            await self._client.send_heartbeat("offline")
        except Exception:  # noqa: BLE001
            pass
        await self._health_checker.stop()
        await self._stream_manager.stop_all()
        await self._client.stop()
        logger.info("EdgeAgent encerrado")

    async def run(self) -> None:
        """Executa loops de polling, heartbeat e config push até sinal de shutdown."""
        poll_interval = self._settings.config_poll_interval
        heartbeat_interval = self._settings.heartbeat_interval

        poll_task = asyncio.create_task(self._poll_loop(poll_interval), name="config_poll")
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(heartbeat_interval), name="heartbeat"
        )
        ws_task = asyncio.create_task(
            self._client.listen_for_config_push(self._on_config_push), name="ws_push"
        )

        try:
            await asyncio.gather(poll_task, heartbeat_task, ws_task)
        except asyncio.CancelledError:
            for task in (poll_task, heartbeat_task, ws_task):
                task.cancel()
            await asyncio.gather(poll_task, heartbeat_task, ws_task, return_exceptions=True)

    async def _on_config_push(self, event: dict) -> None:
        """Processa evento de config push recebido via WebSocket."""
        event_type = event.get("event", "")
        if event_type in ("config_updated", "camera_added", "camera_removed", "restart_stream"):
            logger.info("Config push recebido", event=event_type)
            await self._sync_config()

    async def _poll_loop(self, interval: int) -> None:
        """Faz polling de configuração periodicamente."""
        while self._running:
            await asyncio.sleep(interval)
            await self._sync_config()

    async def _heartbeat_loop(self, interval: int) -> None:
        """Envia heartbeat periodicamente."""
        while self._running:
            await asyncio.sleep(interval)
            await self._client.send_heartbeat("online")

    async def _sync_config(self) -> None:
        """Busca config da API e reconcilia streams."""
        try:
            config = await self._client.get_config()
            desired = {
                cam.camera_id: (cam.rtsp_url, cam.mediamtx_path)
                for cam in config.cameras
                if cam.is_active
            }
            await self._stream_manager.reconcile(desired)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao sincronizar config", error=str(exc))


async def _main() -> None:
    """Ponto de entrada assíncrono do Edge Agent."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    agent = EdgeAgent()
    loop = asyncio.get_running_loop()

    # Graceful shutdown em SIGINT/SIGTERM
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Sinal de desligamento recebido")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await agent.startup()

    run_task = asyncio.create_task(agent.run())

    await shutdown_event.wait()
    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)
    await agent.shutdown()


def main() -> None:
    """Entry point síncrono."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
