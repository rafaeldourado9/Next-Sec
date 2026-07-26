"""Schemas Pydantic para o bounded context de event_clips."""
from __future__ import annotations

from pydantic import BaseModel


class EventClipResponse(BaseModel):
    """Resposta com o status/URL de um clipe de evento."""

    id: str
    vms_event_id: str
    storage_provider: str
    storage_url: str | None
    status: str
    duration_seconds: int

    model_config = {"from_attributes": True}
