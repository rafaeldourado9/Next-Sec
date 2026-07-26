"""Monitor de saúde dos processos ffmpeg com reinicialização automática."""
from __future__ import annotations

import asyncio
import logging

from agent.stream_manager import StreamManager

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 10.0


class HealthChecker:
    """Verifica periodicamente processos ffmpeg e reinicia os que morreram.

    Roda como task assíncrona em loop enquanto o agent está ativo.
    """

    def __init__(self, stream_manager: StreamManager) -> None:
        """Inicializa o health checker.

        Args:
            stream_manager: instância do StreamManager a monitorar.
        """
        self._stream_manager = stream_manager
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Inicia a task de monitoramento em background."""
        self._task = asyncio.create_task(self._loop(), name="health_checker")
        logger.info("HealthChecker iniciado (intervalo=%ds)", int(_CHECK_INTERVAL_SECONDS))

    async def stop(self) -> None:
        """Para a task de monitoramento."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HealthChecker encerrado")

    async def _loop(self) -> None:
        """Loop principal de verificação de saúde."""
        while True:
            try:
                await self._stream_manager.restart_dead_streams()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Erro no health check: %s", exc)
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
