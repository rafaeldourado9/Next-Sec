"""Entidades de domínio do clipe de evento (event_clips)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ClipStatus(StrEnum):
    """Status do ciclo de vida do clipe."""

    PENDING = "pending"
    STAGED = "staged"
    UPLOADED = "uploaded"
    FAILED = "failed"


@dataclass
class EventClip:
    """Clipe de 5-10s gerado a partir de um evento (analytics.intrusion/face)."""

    id: str
    vms_event_id: str
    storage_provider: str = "local"
    storage_ref: str | None = None
    storage_url: str | None = None
    status: ClipStatus = ClipStatus.PENDING
    duration_seconds: int = 8
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
