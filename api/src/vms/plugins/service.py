"""Casos de uso do bounded context de plugins."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from vms.cameras.domain import Camera
from vms.cameras.repository import CameraRepositoryPort
from vms.infrastructure.config import get_settings
from vms.shared.exceptions import NotFoundError
from vms.infrastructure.security import create_viewer_token

logger = logging.getLogger(__name__)


class PluginService:
    """Casos de uso expostos ao contrato público de plugins."""

    def __init__(self, camera_repo: CameraRepositoryPort) -> None:
        self._cameras = camera_repo

    async def list_cameras(self, tenant_id: str) -> list[Camera]:
        """Retorna câmeras ativas do tenant para o plugin processar."""
        return await self._cameras.list_by_tenant(tenant_id, is_online=None)

    async def get_stream_token(
        self,
        camera_id: str,
        tenant_id: str,
        mediamtx_host: str,
    ) -> dict:
        """
        Gera token de acesso ao stream RTSP do MediaMTX para um plugin.

        Retorna dict com rtsp_url, token e expires_at.
        Lança NotFoundError se a câmera não pertencer ao tenant.
        """
        camera = await self._cameras.get_by_id(camera_id, tenant_id)
        if not camera:
            raise NotFoundError("Câmera", camera_id)

        settings = get_settings()
        token = create_viewer_token(tenant_id, camera_id)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
        rtsp_url = f"rtsp://{token}@{mediamtx_host}:8554/{camera.mediamtx_path}"

        return {
            "camera_id": camera_id,
            "rtsp_url": rtsp_url,
            "token": token,
            "expires_at": expires_at,
        }

    async def ingest_event(
        self,
        db,
        tenant_id: str,
        camera_id: str,
        event_type: str,
        confidence: float | None,
        occurred_at: datetime | None,
        payload: dict,
        snapshot_path: str | None = None,
    ) -> str:
        """
        Persiste evento enviado pelo plugin e publica no event bus.

        Retorna ID do evento criado.
        """
        from vms.events.models import VmsEventModel

        event_id = str(uuid.uuid4())
        timestamp = occurred_at or datetime.now(UTC)

        enriched_payload = {**payload}
        if confidence is not None:
            enriched_payload["confidence"] = confidence

        # Se houver imagem base64 no payload, salvar em disco
        image_path = snapshot_path
        if not image_path:
            image_b64 = payload.get("image_b64") or payload.get("imagem")
            if image_b64:
                from vms.events.images import save_event_image
                image_path = save_event_image(
                    tenant_id=tenant_id,
                    event_id=event_id,
                    image_b64=image_b64,
                    occurred_at=timestamp,
                )

        event = VmsEventModel(
            id=event_id,
            tenant_id=tenant_id,
            camera_id=camera_id,
            event_type=event_type,
            payload=enriched_payload,
            image_path=image_path,
            occurred_at=timestamp,
        )
        db.add(event)
        await db.commit()

        try:
            from vms.infrastructure.messaging import publish_event

            await publish_event(
                event_type,
                {"event_id": event_id, "camera_id": camera_id, **enriched_payload},
                tenant_id=tenant_id,
            )
        except Exception:
            logger.warning("Falha ao publicar evento de plugin no event bus (non-fatal)")

        logger.info("Plugin event ingerido: type=%s camera=%s tenant=%s", event_type, camera_id, tenant_id)
        return event_id
