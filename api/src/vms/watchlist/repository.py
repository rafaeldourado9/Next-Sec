"""Ports (interfaces) e implementação SQLAlchemy para a watchlist facial."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.watchlist.domain import FaceProfile
from vms.watchlist.models import FaceProfileModel


class FaceProfileRepositoryPort(Protocol):
    """Interface do repositório da watchlist facial."""

    async def list_by_tenant(self, tenant_id: str) -> list[FaceProfile]: ...

    async def get_by_id(self, profile_id: str, tenant_id: str) -> FaceProfile | None: ...

    async def create(self, profile: FaceProfile) -> FaceProfile: ...

    async def soft_delete(self, profile_id: str, tenant_id: str) -> FaceProfile | None: ...


def _to_domain(m: FaceProfileModel) -> FaceProfile:
    """Converte modelo ORM para entidade de domínio."""
    return FaceProfile(
        id=m.id,
        tenant_id=m.tenant_id,
        name=m.name,
        reference_image_path=m.reference_image_path,
        is_active=m.is_active,
        created_at=m.created_at,
        updated_at=m.updated_at,
        deleted_at=m.deleted_at,
    )


class FaceProfileRepository:
    """Repositório SQLAlchemy para FaceProfile."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_tenant(self, tenant_id: str) -> list[FaceProfile]:
        """Lista perfis ativos (não removidos) do tenant."""
        stmt = select(FaceProfileModel).where(
            FaceProfileModel.tenant_id == tenant_id,
            FaceProfileModel.deleted_at.is_(None),
        ).order_by(FaceProfileModel.created_at.desc())
        result = await self._session.scalars(stmt)
        return [_to_domain(m) for m in result.all()]

    async def get_by_id(self, profile_id: str, tenant_id: str) -> FaceProfile | None:
        """Busca perfil por ID dentro do tenant (não retorna removidos)."""
        stmt = select(FaceProfileModel).where(
            FaceProfileModel.id == profile_id,
            FaceProfileModel.tenant_id == tenant_id,
            FaceProfileModel.deleted_at.is_(None),
        )
        result = await self._session.scalar(stmt)
        return _to_domain(result) if result else None

    async def create(self, profile: FaceProfile) -> FaceProfile:
        """Persiste novo perfil na watchlist."""
        model = FaceProfileModel(
            id=profile.id or str(uuid.uuid4()),
            tenant_id=profile.tenant_id,
            name=profile.name,
            reference_image_path=profile.reference_image_path,
            is_active=profile.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def soft_delete(self, profile_id: str, tenant_id: str) -> FaceProfile | None:
        """Marca perfil como removido. Retorna o perfil removido, ou None se não encontrado."""
        stmt = select(FaceProfileModel).where(
            FaceProfileModel.id == profile_id,
            FaceProfileModel.tenant_id == tenant_id,
            FaceProfileModel.deleted_at.is_(None),
        )
        model = await self._session.scalar(stmt)
        if not model:
            return None
        model.deleted_at = datetime.now(UTC)
        model.is_active = False
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)
