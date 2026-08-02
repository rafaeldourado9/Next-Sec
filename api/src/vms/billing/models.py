"""Modelo SQLAlchemy ORM para licenciamento (Next Sec).

Versão mínima do módulo billing herdado do vms/: só o necessário para o
LicenseGate/onboarding funcionarem (ativação de chave por tenant). GMV,
faturas, planos e analytics_pricing continuam fora do escopo do MVP
(ver .genesis/architecture/reuse-plan.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from vms.infrastructure.database import Base

_UUID_TYPE = UUID(as_uuid=False).with_variant(String(36), "sqlite")


def _uuid() -> str:
    return str(uuid.uuid4())


class LicenseKeyModel(Base):
    """Tabela de chaves de licença (formato XXXX-XXXXX-XXXXX-XXXXX-XXXXX).

    A partir da ADR-018 a licença acumula um segundo papel além do comercial:
    é a **credencial de bootstrap do agente de edge**. `POST /edge/activate`
    troca a chave digitada pelo cliente por uma API key, vinculando-a à
    máquina (`hardware_fingerprint`) — é esse vínculo que impede uma licença
    de virar N instalações. As colunas de limite (`events_per_minute` em
    diante) viajam na resposta da ativação e é o agente quem as respeita.
    """

    __tablename__ = "license_keys"

    id: Mapped[str] = mapped_column(_UUID_TYPE, primary_key=True, default=_uuid)
    license_key: Mapped[str] = mapped_column(String(29), unique=True, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(_UUID_TYPE, nullable=True, index=True)
    deployment_model: Mapped[str] = mapped_column(String(20), nullable=False, default="self_hosted")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    max_cameras: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ─── Ativação do edge (ADR-018 §1) ────────────────────────────────────
    hardware_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activated_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(_UUID_TYPE, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ─── Limites operacionais (ADR-018 §4/§5) ─────────────────────────────
    events_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    clip_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    clip_max_height: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    clip_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=5120)
