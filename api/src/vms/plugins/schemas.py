"""Schemas de entrada/saída do bounded context de plugins."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PluginCameraResponse(BaseModel):
    """Câmera retornada ao plugin."""

    id: str
    tenant_id: str
    name: str
    manufacturer: str
    stream_protocol: str
    is_online: bool
    mediamtx_path: str
    rtsp_url: str | None = None
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
    edge_generates_clip: bool = Field(
        default=False,
        description=(
            "True quando o evento vem de um analytics Nível 1 (Docker dedicado "
            "no cliente, ver ADR-016/017) — o worker local já vai gerar o clipe "
            "MP4 e enviá-lo via PUT /plugins/events/{id}/clip, então a VPS "
            "central pula a geração via ffmpeg para este evento."
        ),
    )


class PluginEventResponse(BaseModel):
    """Confirmação de recebimento do evento."""

    id: str
    status: str = "accepted"
