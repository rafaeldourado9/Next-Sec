"""Cliente HTTP para comunicação com a VMS API Cloud."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    """Configuração de uma câmera recebida da API."""

    camera_id: str
    name: str
    rtsp_url: str
    is_active: bool
    mediamtx_path: str


@dataclass
class AgentConfig:
    """Configuração completa do agent recebida da API."""

    agent_id: str
    cameras: list[CameraConfig] = field(default_factory=list)


class CloudClient:
    """Cliente HTTP para a VMS API.

    Responsável por:
    - Buscar configuração de câmeras (poll)
    - Enviar heartbeat periódico
    """

    def __init__(self, settings: Settings) -> None:
        """Inicializa o cliente com as configurações do agent."""
        self._settings = settings
        self._base_url = str(settings.vms_api_url).rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.agent_api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Cria o cliente HTTP assíncrono."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._settings.http_timeout,
        )
        logger.info("CloudClient iniciado — VMS API: %s", self._base_url)

    async def stop(self) -> None:
        """Fecha o cliente HTTP."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("CloudClient encerrado")

    async def get_config(self) -> AgentConfig:
        """Busca configuração de câmeras do agent na API.

        Usa o endpoint /agents/me/config autenticado via API key.

        Returns:
            AgentConfig com lista de câmeras ativas.

        Raises:
            httpx.HTTPStatusError: se a API retornar erro HTTP.
        """
        client = self._ensure_client()
        agent_id = self._settings.agent_id

        response = await client.get("/api/v1/agents/me/config")
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        cameras = [
            CameraConfig(
                camera_id=cam["id"],
                name=cam["name"],
                rtsp_url=cam["rtsp_url"],
                is_active=cam.get("enabled", cam.get("is_active", True)),
                mediamtx_path=cam.get("rtmp_push_url", f"cam-{cam['id']}"),
            )
            for cam in data.get("cameras", [])
        ]
        logger.debug("Config recebida: %d câmeras", len(cameras))
        return AgentConfig(agent_id=agent_id, cameras=cameras)

    async def send_heartbeat(self, status: str = "online") -> None:
        """Envia heartbeat para a API.

        Usa o endpoint /agents/me/heartbeat autenticado via API key.

        Args:
            status: status atual do agent ("online" | "offline").
        """
        client = self._ensure_client()

        try:
            response = await client.post(
                "/api/v1/agents/me/heartbeat",
                json={
                    "version": "1.0.0",
                    "streams_running": 0,
                    "streams_failed": 0,
                    "uptime_seconds": 0,
                },
            )
            response.raise_for_status()
            logger.debug("Heartbeat enviado: %s", status)
        except httpx.HTTPError as exc:
            logger.warning("Falha ao enviar heartbeat: %s", exc)

    async def listen_for_config_push(self, on_update: Callable[[dict], Any]) -> None:
        """
        Conecta ao WebSocket e recebe config push em tempo real.

        Reconecta automaticamente se a conexão cair.
        Chama on_update(event_data) para cada evento recebido.
        """
        import websockets

        ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/v1/agents/me/ws?api_key={self._settings.agent_api_key}"
        backoff = 1.0

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    logger.info("WebSocket conectado — aguardando config push")
                    backoff = 1.0
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await on_update(data)
                        except Exception as exc:
                            logger.warning("Erro ao processar mensagem WS: %s", exc)
            except Exception as exc:
                logger.warning("WebSocket desconectado (%s) — reconectando em %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def _ensure_client(self) -> httpx.AsyncClient:
        """Garante que o cliente está inicializado."""
        if self._client is None:
            msg = "CloudClient não iniciado — chame await start() primeiro"
            raise RuntimeError(msg)
        return self._client
