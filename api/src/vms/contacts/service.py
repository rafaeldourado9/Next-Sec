"""Application service de contatos — casos de uso de cadastro de destinatários."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.repository import CameraRepository
from vms.contacts.domain import Contact
from vms.contacts.repository import ContactRepository, ContactRepositoryPort
from vms.shared.exceptions import NotFoundError


class ContactService:
    """Casos de uso de gerenciamento de contatos (destinatários de alerta)."""

    def __init__(
        self,
        contact_repo: ContactRepositoryPort,
        camera_repo: CameraRepository,
    ) -> None:
        self._contacts = contact_repo
        self._cameras = camera_repo

    async def list_contacts(self, tenant_id: str, camera_id: str | None) -> list[Contact]:
        """Lista contatos do tenant, opcionalmente filtrando por câmera."""
        return await self._contacts.list_by_tenant(tenant_id, camera_id=camera_id)

    async def create_contact(
        self,
        tenant_id: str,
        phone_number: str,
        name: str,
        camera_id: str | None,
    ) -> Contact:
        """Cadastra novo contato.

        Se `camera_id` for informado, valida que a câmera pertence ao
        tenant — nunca revela a existência de uma câmera de outro tenant.
        """
        if camera_id:
            camera = await self._cameras.get_by_id(camera_id, tenant_id)
            if not camera:
                raise NotFoundError("Câmera", camera_id)

        contact = Contact(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            camera_id=camera_id,
            phone_number=phone_number,
            name=name,
        )
        return await self._contacts.create(contact)

    async def update_contact(
        self,
        contact_id: str,
        tenant_id: str,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> Contact:
        """Atualiza nome/status de um contato. Lança NotFoundError se não existir."""
        updated = await self._contacts.update(
            contact_id, tenant_id, name=name, is_active=is_active
        )
        if not updated:
            raise NotFoundError("Contact", contact_id)
        return updated

    async def delete_contact(self, contact_id: str, tenant_id: str) -> None:
        """Remove contato (soft delete). Lança NotFoundError se não existir."""
        deleted = await self._contacts.soft_delete(contact_id, tenant_id)
        if not deleted:
            raise NotFoundError("Contact", contact_id)


def build_contact_service(session: AsyncSession) -> ContactService:
    """Factory que constrói ContactService com implementações concretas."""
    return ContactService(
        contact_repo=ContactRepository(session),
        camera_repo=CameraRepository(session),
    )
