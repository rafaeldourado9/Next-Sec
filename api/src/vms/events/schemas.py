"""Schemas Pydantic v2 para o bounded context de eventos."""
from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, Field


class AlprWebhookRequest(BaseModel):
    """Payload normalizado para webhook ALPR genérico."""

    camera_id: str
    plate: str = Field(..., min_length=1, max_length=20)
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime
    image_b64: str | None = None


class VmsEventResponse(BaseModel):
    """Resposta com dados de um evento VMS."""

    model_config = {"from_attributes": True}

    id: str
    event_type: str
    plate: str | None
    confidence: float | None
    camera_id: str | None
    payload: dict
    image_url: str | None = None
    occurred_at: datetime


class EventListResponse(BaseModel):
    """Resposta paginada de lista de eventos."""

    items: list[VmsEventResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls,
        items: list[VmsEventResponse],
        total: int,
        page: int,
        page_size: int,
    ) -> "EventListResponse":
        """Constrói resposta calculando total de páginas."""
        pages = math.ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


class MediaMTXOnReadyPayload(BaseModel):
    """Payload do webhook MediaMTX on_ready."""

    path: str
    query: str | None = None


class MediaMTXOnNotReadyPayload(BaseModel):
    """Payload do webhook MediaMTX on_not_ready."""

    path: str


class MediaMTXSegmentPayload(BaseModel):
    """Payload do webhook MediaMTX segment_ready."""

    path: str
    segment_path: str
    duration: float | None = None
