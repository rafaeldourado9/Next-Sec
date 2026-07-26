"""Entidades de domínio de eventos VMS e detecção ALPR."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VmsEvent:
    """Evento registrado no VMS."""

    id: str
    tenant_id: str
    event_type: str
    payload: dict
    camera_id: str | None = None
    plate: str | None = None
    confidence: float | None = None
    image_path: str | None = None
    occurred_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AlprDetection:
    """Detecção ALPR normalizada (de câmera inteligente ou analytics)."""

    camera_id: str
    tenant_id: str
    plate: str
    confidence: float
    manufacturer: str
    timestamp: datetime
    raw_payload: dict
    image_b64: str | None = None
    bbox: list[float] | None = None
