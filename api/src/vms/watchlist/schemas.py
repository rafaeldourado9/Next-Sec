"""Schemas Pydantic para o bounded context de watchlist facial."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FaceProfileResponse(BaseModel):
    """Resposta com dados de um perfil da watchlist."""

    id: str
    tenant_id: str
    name: str
    reference_image_path: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
