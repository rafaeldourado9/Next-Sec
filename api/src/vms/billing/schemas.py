"""Schemas Pydantic para o bounded context de licenciamento."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_LICENSE_KEY_RE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$")


class ActivateLicenseRequest(BaseModel):
    """Payload para ativação de uma chave de licença."""

    license_key: str = Field(..., examples=["ABCD-12345-ABCDE-12345-ABCDE"])

    @field_validator("license_key")
    @classmethod
    def validate_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not _LICENSE_KEY_RE.match(v):
            raise ValueError("license_key deve estar no formato XXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        return v


class LicenseStatusResponse(BaseModel):
    """Resposta com o status de licença do tenant autenticado."""

    active: bool
    onboarding_complete: bool
    deployment_model: str | None = None
    license_key: str | None = None
    max_cameras: int | None = None
    expires_at: datetime | None = None
    status: str | None = None

    model_config = {"from_attributes": True}
