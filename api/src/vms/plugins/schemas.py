"""Schemas de entrada/saída do bounded context de plugins."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PluginCameraResponse(BaseModel):
    """Câmera retornada ao plugin."""

    id: str
    name: str
    manufacturer: str
    stream_protocol: str
    is_online: bool
    mediamtx_path: str
    location: str | None = None

    model_config = {"from_attributes": True}


class StreamTokenResponse(BaseModel):
    """Token de acesso ao stream RTSP via MediaMTX."""

    camera_id: str
    rtsp_url: str
    token: str
    expires_at: datetime


class PluginEventRequest(BaseModel):
    """Evento detectado pelo plugin."""

    camera_id: str = Field(..., description="ID da câmera onde ocorreu o evento")
    event_type: str = Field(
        ...,
        description="Tipo do evento (ex: 'intrusion.detected', 'lpr.detected')",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    occurred_at: datetime | None = Field(
        default=None,
        description="Timestamp do evento. Usa horário atual se não informado.",
    )
    payload: dict = Field(
        default_factory=dict,
        description="Dados arbitrários do plugin (zonas, placas, contagens, etc.)",
    )
    snapshot_path: str | None = Field(
        default=None,
        description="Caminho relativo do snapshot JPEG (relativo a /snapshots/)",
    )


class PluginEventResponse(BaseModel):
    """Confirmação de recebimento do evento."""

    id: str
    status: str = "accepted"
