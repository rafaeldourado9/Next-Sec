"""Fixtures compartilhadas — banco SQLite em memória para testes de repository/service.

Não sobe Postgres/Redis/RabbitMQ real — testa a camada de domínio/repository
isoladamente. Testes de contrato HTTP completos (com auth, SSE, etc.) ficam
para uma suíte de integração futura que suba os serviços via docker compose
(marcador `@pytest.mark.integration`, ver pyproject.toml).
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from vms.infrastructure.database.connection import Base, init_db

# Importa todos os models para que Base.metadata os conheça antes do create_all
from vms.iam.models import TenantModel, UserModel, ApiKeyModel  # noqa: F401
from vms.cameras.models import CameraModel, AgentModel  # noqa: F401
from vms.contacts.models import ContactModel  # noqa: F401
from vms.analytics.models import AnalyticsROI, ROISchedule, PluginInstallation, AnalyticsEvent  # noqa: F401
from vms.events.models import VmsEventModel  # noqa: F401
from vms.notifications.models import NotificationRuleModel, NotificationLogModel  # noqa: F401
from vms.watchlist.models import FaceProfileModel  # noqa: F401
from vms.event_clips.models import EventClipModel  # noqa: F401
from vms.audit.models import AuditLogModel  # noqa: F401
from vms.billing.models import LicenseKeyModel  # noqa: F401


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Sessão async contra um SQLite em memória, schema recriado a cada teste."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = init_db(engine)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def tenant_a(db_session: AsyncSession) -> TenantModel:
    """Cria um tenant de teste ('A')."""
    tenant = TenantModel(id=str(uuid.uuid4()), name="Tenant A", slug=f"tenant-a-{uuid.uuid4().hex[:6]}")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest_asyncio.fixture
async def tenant_b(db_session: AsyncSession) -> TenantModel:
    """Cria um segundo tenant de teste ('B') — usado para testes de isolamento."""
    tenant = TenantModel(id=str(uuid.uuid4()), name="Tenant B", slug=f"tenant-b-{uuid.uuid4().hex[:6]}")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest_asyncio.fixture
async def camera_a(db_session: AsyncSession, tenant_a: TenantModel) -> CameraModel:
    """Câmera pertencente ao tenant A."""
    camera = CameraModel(id=str(uuid.uuid4()), tenant_id=tenant_a.id, name="Câmera Entrada")
    db_session.add(camera)
    await db_session.flush()
    return camera
