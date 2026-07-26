"""Cliente HTTP para comunicação com a VMS API via contrato público de plugins."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from analytics.core.config import get_settings

logger = logging.getLogger(__name__)


class VMSClient:
    """
    Cliente assíncrono para o contrato público de plugins do VMS.

    Autentica com API key de plugin via header Authorization: ApiKey <key>.
    Todos os endpoints usados são públicos — nenhum endpoint interno.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.vms_api_url
        self._api_key = settings.vms_api_key
        self._mediamtx_host = settings.mediamtx_host
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Inicializa o cliente HTTP."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"ApiKey {self._api_key}",
                "X-MediaMTX-Host": self._mediamtx_host,
            },
            timeout=httpx.Timeout(10.0),
        )

    async def close(self) -> None:
        """Fecha o cliente HTTP."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_cameras(self) -> list[dict[str, Any]]:
        """
        Busca câmeras ativas do tenant via GET /api/v1/plugins/cameras.

        Retorna lista de dicts com id, name, stream_protocol, is_online, mediamtx_path.
        """
        if not self._client:
            return []

        try:
            resp = await self._client.get("/api/v1/plugins/cameras")
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.exception("Erro ao listar câmeras do VMS")
            return []

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
        """
        if not self._client:
            return []
        try:
            params = {"camera_id": camera_id} if camera_id else {}
            resp = await self._client.get("/api/v1/plugins/rois", params=params)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPError:
            logger.exception("Erro ao buscar ROIs para câmera %s", camera_id)
            return []

    async def ingest_event(
        self,
        camera_id: str,
        event_type: str,
        payload: dict[str, Any],
        confidence: float | None = None,
        occurred_at: str | None = None,
        snapshot_path: str | None = None,
    ) -> bool:
        """
        Envia evento detectado pelo plugin via POST /api/v1/plugins/events.

        Retorna True se aceito com sucesso.
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

        try:
            resp = await self._client.post("/api/v1/plugins/events", json=body)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Erro ao enviar evento de plugin para o VMS")
            return False

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
