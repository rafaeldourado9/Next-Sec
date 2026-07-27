"""Modelos SQLAlchemy ORM para o bounded context de câmeras e agents."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vms.infrastructure.database import Base

_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")
_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    """Gera UUID v4 como string."""
    return str(uuid.uuid4())


class AgentModel(Base):
    """Tabela de agents locais."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    streams_running: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streams_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cameras: Mapped[list["CameraModel"]] = relationship("CameraModel", back_populates="agent")
    tunnel: Mapped["AgentTunnelModel | None"] = relationship(
        "AgentTunnelModel", back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )


class AgentTunnelModel(Base):
    """Túnel WireGuard de um agent — só guarda a chave PÚBLICA.

    A chave privada é gerada em memória na criação do agent e devolvida uma
    única vez na resposta da API (ver `AgentService.create_agent_with_tunnel`)
    — nunca persistida, mesmo padrão já usado por `ApiKeyModel` pra não
    guardar a chave em texto puro.
    """

    __tablename__ = "agent_tunnels"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tunnel_ip: Mapped[str] = mapped_column(String(18), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped["AgentModel"] = relationship("AgentModel", back_populates="tunnel")


class CameraModel(Base):
    """Tabela de câmeras de segurança."""

    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        _UUID_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        _UUID_TYPE,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    ia_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stream_protocol: Mapped[str] = mapped_column(String(50), nullable=False, default="rtsp_pull")
    rtsp_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    rtmp_stream_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    onvif_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    onvif_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    onvif_password: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manufacturer: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    camera_type: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stream_quality: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ptz_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ISAPI Integration (Hikvision)
    isapi_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    isapi_base_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    isapi_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isapi_password: Mapped[str | None] = mapped_column(String(500), nullable=True)  # Encrypted
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    isapi_capabilities: Mapped[dict | None] = mapped_column(
        _JSON_TYPE, nullable=True, server_default="{}"
    )

    agent: Mapped[AgentModel | None] = relationship("AgentModel", back_populates="cameras")
