"""Ports (interfaces) e implementação SQLAlchemy para contatos."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.contacts.domain import Contact
from vms.contacts.models import ContactModel


class ContactRepositoryPort(Protocol):
    """Interface do repositório de contatos."""

    async def list_by_tenant(
        self, tenant_id: str, camera_id: str | None = None
    ) -> list[Contact]: ...

    async def get_by_id(self, contact_id: str, tenant_id: str) -> Contact | None: ...

    async def create(self, contact: Contact) -> Contact: ...

    async def update(
        self, contact_id: str, tenant_id: str, *, name: str | None, is_active: bool | None
    ) -> Contact | None: ...

    async def soft_delete(self, contact_id: str, tenant_id: str) -> bool: ...


def _to_domain(m: ContactModel) -> Contact:
    """Converte modelo ORM para entidade de domínio."""
    return Contact(
        id=m.id,
        tenant_id=m.tenant_id,
        camera_id=m.camera_id,
        phone_number=m.phone_number,
        name=m.name,
        is_active=m.is_active,
        created_at=m.created_at,
        updated_at=m.updated_at,
        deleted_at=m.deleted_at,
    )


class ContactRepository:
    """Repositório SQLAlchemy para Contact."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_tenant(
        self, tenant_id: str, camera_id: str | None = None
    ) -> list[Contact]:
        """Lista contatos ativos do tenant, opcionalmente filtrando por câmera.

        Quando `camera_id` é informado, inclui também os contatos globais
        do tenant (`camera_id IS NULL`), já que esses recebem alertas de
        todas as câmeras.
        """
        stmt = select(ContactModel).where(
            ContactModel.tenant_id == tenant_id,
            ContactModel.deleted_at.is_(None),
        )
        if camera_id:
            stmt = stmt.where(
                (ContactModel.camera_id == camera_id) | (ContactModel.camera_id.is_(None))
            )
        result = await self._session.scalars(stmt.order_by(ContactModel.created_at.desc()))
        return [_to_domain(m) for m in result.all()]

    async def get_by_id(self, contact_id: str, tenant_id: str) -> Contact | None:
        """Busca contato por ID dentro do tenant (não retorna removidos)."""
        stmt = select(ContactModel).where(
            ContactModel.id == contact_id,
            ContactModel.tenant_id == tenant_id,
            ContactModel.deleted_at.is_(None),
        )
        result = await self._session.scalar(stmt)
        return _to_domain(result) if result else None

    async def create(self, contact: Contact) -> Contact:
        """Persiste novo contato."""
        model = ContactModel(
            id=contact.id or str(uuid.uuid4()),
            tenant_id=contact.tenant_id,
            camera_id=contact.camera_id,
            phone_number=contact.phone_number,
            name=contact.name,
            is_active=contact.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def update(
        self, contact_id: str, tenant_id: str, *, name: str | None, is_active: bool | None
    ) -> Contact | None:
        """Atualiza campos parciais de um contato. Retorna None se não encontrado."""
        stmt = select(ContactModel).where(
            ContactModel.id == contact_id,
            ContactModel.tenant_id == tenant_id,
            ContactModel.deleted_at.is_(None),
        )
        model = await self._session.scalar(stmt)
        if not model:
            return None
        if name is not None:
            model.name = name
        if is_active is not None:
            model.is_active = is_active
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def soft_delete(self, contact_id: str, tenant_id: str) -> bool:
        """Marca contato como removido (deleted_at). Retorna False se não encontrado."""
        stmt = select(ContactModel).where(
            ContactModel.id == contact_id,
            ContactModel.tenant_id == tenant_id,
            ContactModel.deleted_at.is_(None),
        )
        model = await self._session.scalar(stmt)
        if not model:
            return False
        model.deleted_at = datetime.now(UTC)
        model.is_active = False
        await self._session.flush()
        return True
