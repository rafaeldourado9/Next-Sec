"""Cliente HTTP para a API de controle interna do hub WireGuard.

Espelha o estilo de `mediamtx.py::MediaMTXClient` — cliente fino, sem estado,
uma responsabilidade (falar com o serviço de infra correspondente).
"""
from __future__ import annotations

import logging

import httpx

from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class WireGuardHubClient:
    """Cliente assíncrono pra API de controle do hub WireGuard (add/remove peer)."""

    def __init__(self, base_url: str | None = None, control_token: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.wg_hub_internal_url).rstrip("/")
        self._token = control_token or settings.wg_control_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"ApiKey {self._token}"}

    async def add_peer(self, public_key: str, tunnel_ip: str) -> None:
        """Registra (ou atualiza) um peer no wg0 do hub.

        Levanta `httpx.HTTPError` se o hub estiver inacessível ou recusar —
        o chamador (`AgentService.create_agent_with_tunnel`) trata isso como
        fatal e desfaz a criação do agent (não deixa um agent órfão sem túnel).
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/peers",
                json={"public_key": public_key, "tunnel_ip": tunnel_ip},
                headers=self._headers(),
            )
            resp.raise_for_status()

    async def get_hub_info(self) -> dict[str, str]:
        """Retorna `{"public_key", "endpoint"}` do hub — a chave é gerada no
        primeiro boot do container do hub; a API não tem outra forma de
        descobrir esse valor."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._base_url}/hub-info", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def remove_peer(self, public_key: str) -> None:
        """Remove um peer do wg0 do hub — best-effort, chamador decide se é fatal."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/peers/remove",
                json={"public_key": public_key},
                headers=self._headers(),
            )
            resp.raise_for_status()
