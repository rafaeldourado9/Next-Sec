"""Schemas Pydantic para o bounded context de contatos."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


class CreateContactRequest(BaseModel):
    """Payload para cadastro de contato."""

    phone_number: str = Field(
        ..., description="Telefone em formato E.164", examples=["+5511999999999"]
    )
    name: str = Field(..., min_length=1, max_length=255)
    camera_id: str | None = Field(
        default=None,
        description="Câmera específica — null = recebe alertas de todas as câmeras do tenant",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_e164(cls, v: str) -> str:
        """Valida formato E.164 (+ código do país + número, sem espaços)."""
        if not _E164_RE.match(v):
            raise ValueError("phone_number deve estar no formato E.164, ex: +5511999999999")
        return v


class UpdateContactRequest(BaseModel):
    """Payload para atualização parcial de contato."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class ContactResponse(BaseModel):
    """Resposta com dados de um contato."""

    id: str
    tenant_id: str
    camera_id: str | None
    phone_number: str
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
