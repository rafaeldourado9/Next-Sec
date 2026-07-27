"""Application service da watchlist facial — cadastro com gate de LGPD."""
from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.models import TenantModel
from vms.infrastructure.config import get_settings
from vms.infrastructure.object_storage import ObjectStorage
from vms.shared.exceptions import NotFoundError, UnauthorizedError
from vms.watchlist.domain import FaceProfile
from vms.watchlist.repository import FaceProfileRepository, FaceProfileRepositoryPort

logger = logging.getLogger(__name__)


class WatchlistService:
    """Casos de uso de gerenciamento da watchlist de reconhecimento facial."""

    def __init__(
        self,
        profile_repo: FaceProfileRepositoryPort,
        session: AsyncSession,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._profiles = profile_repo
        self._session = session
        self._storage = storage or ObjectStorage()

    async def _facial_recognition_enabled(self, tenant_id: str) -> bool:
        tenant = await self._session.scalar(
            select(TenantModel).where(TenantModel.id == tenant_id)
        )
        return bool(tenant and tenant.facial_recognition_enabled)

    async def list_profiles(self, tenant_id: str) -> list[FaceProfile]:
        """Lista rostos cadastrados na watchlist do tenant."""
        return await self._profiles.list_by_tenant(tenant_id)

    async def create_profile(
        self,
        tenant_id: str,
        name: str,
        image_bytes: bytes,
        content_type: str,
    ) -> FaceProfile:
        """Cadastra um rosto na watchlist.

        Gate de LGPD: exige `tenant.facial_recognition_enabled=True` (ligado
        via consentimento em `POST /lgpd/consent` com `data_type=face`) —
        mesmo gate que o plugin `face_recognition` do serviço de analytics
        usa antes de processar qualquer inferência.
        """
        if not await self._facial_recognition_enabled(tenant_id):
            raise UnauthorizedError(
                "Reconhecimento facial não habilitado para este tenant — "
                "registre o consentimento em POST /lgpd/consent (data_type=face) primeiro"
            )

        profile_id = str(uuid.uuid4())
        settings = get_settings()
        bucket = settings.minio_bucket_analytics
        key = f"watchlist/{tenant_id}/{profile_id}.jpg"
        self._storage.upload_bytes(bucket, key, image_bytes, content_type=content_type or "image/jpeg")

        profile = FaceProfile(
            id=profile_id,
            tenant_id=tenant_id,
            name=name,
            reference_image_path=key,
        )
        created = await self._profiles.create(profile)

        from vms.plugins import watchlist_cache
        watchlist_cache.invalidate(tenant_id)

        return created

    async def search_faces(
        self,
        profile_id: str,
        tenant_id: str,
        *,
        camera_id: str | None = None,
        since_hours: int = 24 * 30,
        limit: int = 200,
    ) -> list[dict]:
        """Busca o rosto cadastrado entre os snapshots de eventos já existentes.

        Não roda mais reconhecimento facial ao vivo — o usuário cadastra o
        rosto e dispara essa busca pontual contra eventos que já têm snapshot
        (ex: cruzamentos de cerca virtual), delegando o matching pro serviço
        `analytics/` (que tem o InsightFace carregado).
        """
        from datetime import datetime, timedelta, timezone

        from vms.events.models import VmsEventModel

        profile = await self._profiles.get_by_id(profile_id, tenant_id)
        if not profile or not profile.reference_image_path:
            raise NotFoundError("FaceProfile", profile_id)

        settings = get_settings()
        reference_image_url = self._storage.get_presigned_url(
            settings.minio_bucket_analytics, profile.reference_image_path, expires=300
        )

        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        stmt = (
            select(VmsEventModel)
            .where(
                VmsEventModel.tenant_id == tenant_id,
                VmsEventModel.image_path.is_not(None),
                VmsEventModel.occurred_at >= since,
            )
            .order_by(VmsEventModel.occurred_at.desc())
            .limit(limit)
        )
        if camera_id:
            stmt = stmt.where(VmsEventModel.camera_id == camera_id)

        result = await self._session.execute(stmt)
        events = {str(e.id): e for e in result.scalars().all()}
        if not events:
            return []

        candidates = [{"event_id": eid, "image_path": e.image_path} for eid, e in events.items()]

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.analytics_internal_url}/face-search",
                    json={
                        "reference_image_url": reference_image_url,
                        "candidates": candidates,
                        "threshold": 0.5,
                    },
                )
                resp.raise_for_status()
                matches = resp.json()["matches"]
        except httpx.HTTPError:
            logger.exception("Falha ao buscar rosto no serviço de analytics")
            return []

        return [
            {
                "event_id": m["event_id"],
                "similarity": m["similarity"],
                "camera_id": events[m["event_id"]].camera_id,
                "occurred_at": events[m["event_id"]].occurred_at,
            }
            for m in matches
            if m["event_id"] in events
        ]

    async def delete_profile(self, profile_id: str, tenant_id: str) -> None:
        """Remove um rosto da watchlist (soft delete + apaga a imagem do storage)."""
        deleted = await self._profiles.soft_delete(profile_id, tenant_id)
        if not deleted:
            raise NotFoundError("FaceProfile", profile_id)

        from vms.plugins import watchlist_cache
        watchlist_cache.invalidate(tenant_id)

        if deleted.reference_image_path:
            settings = get_settings()
            try:
                self._storage.delete_object(settings.minio_bucket_analytics, deleted.reference_image_path)
            except Exception:
                # Falha ao limpar o storage não deve impedir o soft delete no banco
                # (já removido logicamente) — fica como órfão para limpeza manual.
                pass


def build_watchlist_service(session: AsyncSession) -> WatchlistService:
    """Factory que constrói WatchlistService com implementações concretas."""
    return WatchlistService(
        profile_repo=FaceProfileRepository(session),
        session=session,
    )
