"""Modelos de Analytics — ROIs, plugins instalados e eventos."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, SmallInteger, String, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vms.infrastructure.database import Base


_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


class AnalyticsROI(Base):
    """Região de interesse (zona de detecção) para um plugin em uma câmera."""

    __tablename__ = "analytics_rois"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(_UUID_TYPE, nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    plugin_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Polígono normalizado: [[x, y], ...] onde x, y ∈ [0, 1]
    polygon: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ROISchedule(Base):
    """Horário de ativação (turno) de uma ROI — múltiplos por ROI."""

    __tablename__ = "roi_schedules"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    roi_id: Mapped[str] = mapped_column(
        _UUID_TYPE, ForeignKey("analytics_rois.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PluginInstallation(Base):
    """Plugin instalado em um edge agent."""

    __tablename__ = "plugin_installations"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    plugin_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    edge_agent_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(_UUID_TYPE, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="installed", index=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fps_target: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    events: Mapped[list[AnalyticsEvent]] = relationship(
        back_populates="plugin_installation", lazy="select"
    )


class AnalyticsEvent(Base):
    """Evento gerado por plugin de analytics."""

    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Nullable: eventos do analytics service não precisam de instalação registrada
    plugin_installation_id: Mapped[str | None] = mapped_column(
        _UUID_TYPE,
        ForeignKey("plugin_installations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(_UUID_TYPE, nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    camera_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    plugin_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    snapshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    plugin_installation: Mapped[PluginInstallation | None] = relationship(
        back_populates="events", lazy="select"
    )
