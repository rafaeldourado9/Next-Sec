"""Loop principal do Edge Agent."""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from collections.abc import Callable
from typing import Any

import structlog

from agent.cloud_client import CloudClient
from agent.config import get_settings
from agent.health_checker import HealthChecker
from agent.stream_manager import StreamManager
from agent.webhook_relay import WebhookRelay

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
        self._stream_manager = StreamManager(self._settings.mediamtx_rtmp_url, self._settings.ffmpeg_path)
        self._health_checker = HealthChecker(self._stream_manager)
        self._webhook_relay = (
            WebhookRelay(
                str(self._settings.vms_api_url),
                self._settings.webhook_relay_host,
                self._settings.webhook_relay_port,
            )
            if self._settings.webhook_relay_enabled
            else None
        )
        self._running = False

    async def startup(self) -> None:
        """Inicializa componentes e carrega config inicial."""
        await self._client.start()
        await self._health_checker.start()
        if self._webhook_relay is not None:
            self._webhook_relay.start()
        await self._sync_config()
        await self._client.send_heartbeat("online")
        self._running = True
        logger.info("EdgeAgent iniciado", agent_id=self._settings.agent_id)

    async def shutdown(self) -> None:
        """Encerra o agent graciosamente."""
        self._running = False
        if self._webhook_relay is not None:
            self._webhook_relay.stop()
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

    async def _on_config_push(self, event: dict, send: Callable[[str], Any]) -> None:
        """Processa evento/comando recebido via WebSocket.

        Dois tipos de mensagem no mesmo canal: config push (fire-and-forget,
        já existia) e comandos que esperam resposta (onvif_probe_request/
        onvif_discover_request — a API/dashboard rodam na VPS e não alcançam
        a LAN do cliente por causa do CGNAT; o agent, que já está na LAN,
        executa e responde pelo mesmo WebSocket).
        """
        event_type = event.get("event", "")
        if event_type in ("config_updated", "camera_added", "camera_removed", "restart_stream"):
            logger.info("Config push recebido", event=event_type)
            await self._sync_config()
            return

        msg_type = event.get("type", "")
        request_id = event.get("request_id")
        if msg_type == "onvif_probe_request" and request_id:
            from agent.onvif_client import probe as onvif_probe

            logger.info("Comando onvif_probe_request recebido", request_id=request_id)
            result = await onvif_probe(
                event.get("onvif_url", ""),
                event.get("username", ""),
                event.get("password", ""),
            )
            await send(json.dumps({
                "type": "onvif_probe_response", "request_id": request_id, **result,
            }))
        elif msg_type == "onvif_discover_request" and request_id:
            from agent.onvif_client import discover as onvif_discover

            logger.info("Comando onvif_discover_request recebido", request_id=request_id)
            timeout = int(event.get("timeout_seconds", 3))
            discovered = await asyncio.to_thread(onvif_discover, timeout)
            await send(json.dumps({
                "type": "onvif_discover_response", "request_id": request_id,
                "cameras": discovered,
            }))

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


async def _main(ready_callback: Callable[[asyncio.AbstractEventLoop, asyncio.Event], None] | None = None) -> None:
    """Ponto de entrada assíncrono do Edge Agent.

    `ready_callback`: usado só pelo serviço Windows (`native_installer/windows/
    agent_service.py`), que precisa parar o agent a partir de uma thread
    diferente (o SCM entrega o stop request numa thread própria, não na
    thread do event loop) — chamar `shutdown_event.set()` direto de outra
    thread não é seguro; é preciso `loop.call_soon_threadsafe(...)`. Esse
    callback entrega `(loop, shutdown_event)` pro chamador guardar as
    referências ANTES de qualquer await, garantindo que ambas já pertencem
    à thread certa. Uma Windows service não recebe SIGINT/SIGTERM como um
    processo de console recebe, então os handlers de sinal abaixo não valem
    nesse caso — por isso o serviço precisa desse mecanismo à parte.
    """
    settings = get_settings()
    _configure_logging(settings.log_level)

    agent = EdgeAgent()
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    if ready_callback is not None:
        ready_callback(loop, shutdown_event)

    def _handle_signal() -> None:
        logger.info("Sinal de desligamento recebido")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows: ProactorEventLoop/SelectorEventLoop não suportam
            # add_signal_handler — só SIGINT funciona, via signal.signal
            # (executando como processo de console, não como serviço).
            if sig == signal.SIGINT:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_handle_signal))

    await agent.startup()

    run_task = asyncio.create_task(agent.run())

    await shutdown_event.wait()
    run_task.cancel()
    await asyncio.gather(run_task, return_exceptions=True)
    await agent.shutdown()


def main(ready_callback: Callable[[asyncio.AbstractEventLoop, asyncio.Event], None] | None = None) -> None:
    """Entry point síncrono. `ready_callback` — ver docstring de `_main`."""
    asyncio.run(_main(ready_callback))


if __name__ == "__main__":
    main()
