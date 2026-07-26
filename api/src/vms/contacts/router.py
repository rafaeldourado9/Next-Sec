"""Rotas HTTP do bounded context de contatos."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from vms.contacts.schemas import ContactResponse, CreateContactRequest, UpdateContactRequest
from vms.contacts.service import ContactService, build_contact_service
from vms.shared.api.dependencies import CurrentUser, DbSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _svc(db: DbSession) -> ContactService:
    """Constrói ContactService com sessão do banco injetada."""
    return build_contact_service(db)


@router.get("", response_model=list[ContactResponse], summary="Listar contatos")
async def list_contacts(
    claims: CurrentUser,
    db: DbSession,
    camera_id: str | None = Query(
        default=None, description="Filtra contatos de uma câmera específica (inclui os globais)"
    ),
) -> list[ContactResponse]:
    """Lista contatos cadastrados pelo cliente final no tenant autenticado."""
    contacts = await _svc(db).list_contacts(claims.tenant_id, camera_id)
    return [ContactResponse.model_validate(c) for c in contacts]


@router.post(
    "", response_model=ContactResponse, status_code=status.HTTP_201_CREATED,
    summary="Cadastrar contato",
)
async def create_contact(
    body: CreateContactRequest,
    claims: CurrentUser,
    db: DbSession,
) -> ContactResponse:
    """Cadastra um novo contato (telefone) para receber alertas."""
    contact = await _svc(db).create_contact(
        tenant_id=claims.tenant_id,
        phone_number=body.phone_number,
        name=body.name,
        camera_id=body.camera_id,
    )
    return ContactResponse.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactResponse, summary="Atualizar contato")
async def update_contact(
    contact_id: str,
    body: UpdateContactRequest,
    claims: CurrentUser,
    db: DbSession,
) -> ContactResponse:
    """Atualiza nome e/ou status de um contato."""
    contact = await _svc(db).update_contact(
        contact_id, claims.tenant_id, name=body.name, is_active=body.is_active
    )
    return ContactResponse.model_validate(contact)


@router.delete(
    "/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover contato"
)
async def delete_contact(
    contact_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Remove um contato (soft delete)."""
    await _svc(db).delete_contact(contact_id, claims.tenant_id)
