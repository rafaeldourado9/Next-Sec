"""Rotas do módulo Analytics — catálogo, instalação e eventos."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from vms.shared.api.dependencies import CurrentUser, DbSession, GestorUser
from vms.analytics.service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _get_tenant_id(current_user: CurrentUser) -> str:
    """Extrai tenant_id do usuário atual."""
    return str(current_user.tenant_id)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class PluginCatalogItem(BaseModel):
    """Item no catálogo de plugins disponíveis."""

    id: str
    name: str
    description: str
    version: str
    category: str
    model_size: str
    fps_cost: int
    is_available: bool
    classes: list[str] = []


class PluginInstallRequest(BaseModel):
    """Requisição para instalar plugin."""

    edge_agent_id: str
    settings: dict = {}
    fps_target: int = 1


class PluginInstallationResponse(BaseModel):
    """Resposta de instalação de plugin."""

    id: str
    plugin_id: str
    plugin_name: str
    version: str
    edge_agent_id: str
    status: str
    fps_target: int
    created_at: datetime


class PluginStatusResponse(BaseModel):
    """Status de um plugin instalado."""

    id: str
    plugin_id: str
    plugin_name: str
    status: str
    edge_agent_id: str
    created_at: datetime
    updated_at: datetime


class AnalyticsEventResponse(BaseModel):
    """Evento de analytics."""

    id: str
    plugin_id: str
    camera_id: str
    camera_name: str | None
    event_type: str
    severity: str
    confidence: float | None
    payload: dict
    occurred_at: datetime
    created_at: datetime
    snapshot_url: str | None = None


class AnalyticsStatsResponse(BaseModel):
    """Estatísticas de analytics."""

    total: int
    by_severity: dict[str, int]
    by_plugin: dict[str, int]
    top_cameras: list[dict]
    period_hours: int


# ─── Catálogo de Plugins ──────────────────────────────────────────────────────

CATALOG = [
    PluginCatalogItem(
        id="intrusion",
        name="Cerca Virtual",
        description="Detecta quando pessoas ou veículos cruzam uma linha ou perímetro definido. Ideal para cercas virtuais e controle de acesso.",
        version="1.0.0",
        category="security",
        model_size="3.2 MB",
        fps_cost=1,
        is_available=True,
        classes=["person", "car", "truck"],
    ),
    PluginCatalogItem(
        id="people_count",
        name="Contagem de Pessoas",
        description="Contagem de pessoas em tempo real. Controle de lotação, heatmaps e fluxo de pedestres.",
        version="1.0.0",
        category="traffic",
        model_size="3.2 MB",
        fps_cost=1,
        is_available=True,
        classes=["person"],
    ),
]

CATALOG_MAP = {item.id: item for item in CATALOG}


@router.get("/catalog", response_model=list[PluginCatalogItem])
async def get_plugin_catalog() -> list[PluginCatalogItem]:
    """Retorna catálogo de plugins disponíveis para download."""
    return CATALOG


@router.get("/catalog/{plugin_id}", response_model=PluginCatalogItem)
async def get_plugin_detail(plugin_id: str) -> PluginCatalogItem:
    """Detalhes de um plugin específico."""
    plugin = CATALOG_MAP.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' não encontrado")
    return plugin


# ─── Instalação de Plugins ────────────────────────────────────────────────────


@router.post("/install", response_model=PluginInstallationResponse, status_code=201)
async def install_plugin(
    body: PluginInstallRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> PluginInstallationResponse:
    """
    Instala plugin no edge agent do tenant.

    Registra a instalação e envia comando para o edge agent
    baixar o modelo e iniciar o processamento.
    """
    tenant_id = _get_tenant_id(current_user)
    plugin_info = CATALOG_MAP.get(body.plugin_id)
    if not plugin_info:
        raise HTTPException(status_code=404, detail=f"Plugin '{body.plugin_id}' não encontrado")

    svc = AnalyticsService(db)
    installation = await svc.create_installation(
        tenant_id=tenant_id,
        plugin_id=body.plugin_id,
        plugin_name=plugin_info.name,
        edge_agent_id=body.edge_agent_id,
        settings=body.settings,
    )

    # TODO: Enviar comando via WebSocket para edge_agent baixar modelo e iniciar
    logger.info(
        "Plugin %s instalado no edge %s (tenant %s)",
        body.plugin_id,
        body.edge_agent_id,
        tenant_id,
    )

    return PluginInstallationResponse(
        id=str(installation.id),
        plugin_id=installation.plugin_id,
        plugin_name=installation.plugin_name,
        version=installation.version,
        edge_agent_id=installation.edge_agent_id,
        status=installation.status,
        fps_target=installation.fps_target,
        created_at=installation.created_at,
    )


@router.get("/installations", response_model=list[PluginStatusResponse])
async def list_installations(
    db: DbSession,
    current_user: CurrentUser,
) -> list[PluginStatusResponse]:
    """Lista plugins instalados do tenant."""
    svc = AnalyticsService(db)
    installations = await svc.list_installations(_get_tenant_id(current_user))

    return [
        PluginStatusResponse(
            id=str(inst.id),
            plugin_id=inst.plugin_id,
            plugin_name=inst.plugin_name,
            status=inst.status,
            edge_agent_id=inst.edge_agent_id,
            created_at=inst.created_at,
            updated_at=inst.updated_at,
        )
        for inst in installations
    ]


@router.delete("/installations/{installation_id}", status_code=204)
async def uninstall_plugin(
    installation_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Remove plugin do edge agent."""
    svc = AnalyticsService(db)

    # Verificar se instalação pertence ao tenant
    installations = await svc.list_installations(_get_tenant_id(current_user))
    installation = next((i for i in installations if i.id == installation_id), None)
    if not installation:
        raise HTTPException(status_code=404, detail="Instalação não encontrada")

    await svc.delete_installation(installation_id)

    # TODO: Enviar comando via WebSocket para edge_agent parar e remover modelo
    logger.info("Plugin removido: %s (tenant %s)", installation_id, _get_tenant_id(current_user))


@router.patch("/installations/{installation_id}/status", response_model=PluginStatusResponse)
async def update_plugin_status(
    installation_id: uuid.UUID,
    status_update: dict,  # {"status": "running" | "stopped" | "error"}
    db: DbSession,
    current_user: CurrentUser,
) -> PluginStatusResponse:
    """Atualiza status de um plugin (start/stop)."""
    new_status = status_update.get("status")
    if new_status not in ("running", "stopped", "installed", "error"):
        raise HTTPException(status_code=400, detail="Status inválido")

    svc = AnalyticsService(db)
    installation = await svc.update_installation_status(installation_id, new_status)
    if not installation:
        raise HTTPException(status_code=404, detail="Instalação não encontrada")

    return PluginStatusResponse(
        id=str(installation.id),
        plugin_id=installation.plugin_id,
        plugin_name=installation.plugin_name,
        status=installation.status,
        edge_agent_id=installation.edge_agent_id,
        created_at=installation.created_at,
        updated_at=installation.updated_at,
    )


# ─── Eventos de Analytics ─────────────────────────────────────────────────────


class CreateEventRequest(BaseModel):
    """Requisição para criar evento (usada por edge agents)."""

    plugin_id: str
    camera_id: str
    camera_name: str | None = None
    event_type: str
    severity: str = "info"
    confidence: float | None = None
    payload: dict = {}
    occurred_at: datetime | None = None
    snapshot_path: str | None = None


@router.post("/events", response_model=dict, status_code=201)
async def create_event(
    body: CreateEventRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> dict:
    """Cria evento detectado por plugin (edge agent)."""
    from datetime import timezone, timedelta
    from vms.analytics.analytic_event_service import AnalyticEventService

    svc = AnalyticEventService(db)
    event = await svc.create_event(
        tenant_id=_get_tenant_id(current_user),
        camera_id=body.camera_id,
        event_type=body.event_type,
        attributes={**body.payload, "plugin_id": body.plugin_id, "severity": body.severity},
        confidence=body.confidence,
        thumbnail_key=body.snapshot_path,
        occurred_at=body.occurred_at,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    return {"id": str(event.id), "status": "created"}


@router.get("/events", response_model=list[AnalyticsEventResponse])
async def list_events(
    db: DbSession,
    current_user: CurrentUser,
    camera_id: str | None = Query(None),
    plugin_id: str | None = Query(None),
    severity: str | None = Query(None),
    occurred_after: datetime | None = Query(None),
    occurred_before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[AnalyticsEventResponse]:
    """Lista eventos detectados pelos plugins do tenant."""
    from vms.analytics.analytic_event_service import AnalyticEventService

    svc = AnalyticEventService(db)
    events, _ = await svc.search_video(
        tenant_id=_get_tenant_id(current_user),
        camera_ids=[camera_id] if camera_id else None,
        start=occurred_after,
        end=occurred_before,
        event_types=[plugin_id] if plugin_id else None,
        confidence_min=0.0,
        page=1,
        page_size=limit,
    )

    return [
        AnalyticsEventResponse(
            id=str(e.id),
            plugin_id=(e.attributes or {}).get("plugin_id", e.event_type.split(".")[0]),
            camera_id=e.camera_id,
            camera_name=None,
            event_type=e.event_type,
            severity=(e.attributes or {}).get("severity", "info"),
            confidence=e.confidence,
            payload=e.attributes or {},
            occurred_at=e.occurred_at,
            created_at=e.created_at,
            snapshot_url=None,
        )
        for e in events
    ]


@router.get("/events/{event_id}/snapshot", include_in_schema=False)
async def get_event_snapshot(
    event_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> "Response":
    """Serve snapshot JPEG de um evento de analytics (autenticado via Bearer token)."""
    import os
    from fastapi import Response
    from fastapi.responses import FileResponse
    from sqlalchemy import select
    from vms.analytics.models import AnalyticsEvent

    tenant_id = _get_tenant_id(current_user)
    stmt = select(AnalyticsEvent).where(
        AnalyticsEvent.id == event_id,
        AnalyticsEvent.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event or not event.snapshot_path:
        raise HTTPException(status_code=404, detail="Snapshot não encontrado")

    full_path = f"/snapshots/{event.snapshot_path}"
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Arquivo de snapshot não encontrado")

    return FileResponse(full_path, media_type="image/jpeg")


# ─── Dashboard / Estatísticas ─────────────────────────────────────────────────

# ─── ROIs ─────────────────────────────────────────────────────────────────────


class ROICreateRequest(BaseModel):
    camera_id: str
    plugin_id: str | None = None
    ia_type: str | None = None
    name: str
    polygon: list[list[float]] | None = None  # [[x, y], ...] normalizados 0-1
    polygon_points: list[list[float]] | None = None
    config: dict = {}


class ROIResponse(BaseModel):
    id: str
    camera_id: str
    plugin_id: str
    ia_type: str
    name: str
    polygon: list[list[float]]
    config: dict
    is_active: bool
    created_at: datetime


@router.get("/rois", response_model=list[ROIResponse])
async def list_rois(
    db: DbSession,
    current_user: CurrentUser,
    camera_id: str | None = None,
    plugin_id: str | None = None,
) -> list[ROIResponse]:
    """Lista ROIs do tenant, opcionalmente filtrado por câmera e plugin."""
    from sqlalchemy import select
    from vms.analytics.models import AnalyticsROI

    tenant_id = _get_tenant_id(current_user)
    stmt = select(AnalyticsROI).where(
        AnalyticsROI.tenant_id == tenant_id,
    )
    if camera_id:
        stmt = stmt.where(AnalyticsROI.camera_id == camera_id)
    if plugin_id:
        stmt = stmt.where(AnalyticsROI.plugin_id == plugin_id)
    result = await db.execute(stmt)
    rois = result.scalars().all()
    return [
        ROIResponse(
            id=str(r.id),
            camera_id=r.camera_id,
            plugin_id=r.plugin_id,
            ia_type=r.plugin_id,
            name=r.name,
            polygon=r.polygon,
            config=r.config,
            is_active=r.is_active,
            created_at=r.created_at,
        )
        for r in rois
    ]


@router.post("/rois", response_model=ROIResponse, status_code=201)
async def create_roi(
    body: ROICreateRequest,
    db: DbSession,
    current_user: GestorUser,
) -> ROIResponse:
    """Cria uma ROI (zona de detecção) para uma câmera.

    Também garante que haja uma PluginInstallation ativa para o plugin,
    para que o analytics service comece a processar esta câmera.
    """
    from vms.analytics.models import AnalyticsROI, PluginInstallation
    from vms.plugins import roi_cache
    from sqlalchemy import select

    tenant_id = _get_tenant_id(current_user)
    plugin_id = body.plugin_id or body.ia_type
    polygon = body.polygon or body.polygon_points
    if not plugin_id or not polygon:
        raise HTTPException(
            status_code=422, detail="plugin_id/ia_type e polygon/polygon_points são obrigatórios"
        )

    # Criar ROI
    roi = AnalyticsROI(
        tenant_id=tenant_id,
        camera_id=body.camera_id,
        plugin_id=plugin_id,
        name=body.name,
        polygon=polygon,
        config=body.config,
    )
    db.add(roi)
    await db.flush()

    # Garantir que existe uma PluginInstallation ativa para este plugin
    install_stmt = select(PluginInstallation).where(
        PluginInstallation.tenant_id == tenant_id,
        PluginInstallation.plugin_id == plugin_id,
    )
    install_result = await db.execute(install_stmt)
    existing = install_result.scalar_one_or_none()

    plugin_info = CATALOG_MAP.get(plugin_id)
    if not existing:
        installation = PluginInstallation(
            tenant_id=tenant_id,
            plugin_id=plugin_id,
            plugin_name=plugin_info.name if plugin_info else plugin_id,
            edge_agent_id="default",
            status="running",
        )
        db.add(installation)
        await db.flush()
    elif existing.status != "running":
        existing.status = "running"
        await db.flush()

    roi_cache.invalidate(str(tenant_id), body.camera_id)
    return ROIResponse(
        id=str(roi.id),
        camera_id=roi.camera_id,
        plugin_id=roi.plugin_id,
        ia_type=roi.plugin_id,
        name=roi.name,
        polygon=roi.polygon,
        config=roi.config,
        is_active=roi.is_active,
        created_at=roi.created_at,
    )


@router.put("/rois/{roi_id}", response_model=ROIResponse)
async def update_roi(
    roi_id: uuid.UUID,
    body: ROICreateRequest,
    db: DbSession,
    current_user: GestorUser,
) -> ROIResponse:
    """Atualiza uma ROI existente."""
    from sqlalchemy import select
    from vms.analytics.models import AnalyticsROI
    from vms.plugins import roi_cache

    tenant_id = _get_tenant_id(current_user)
    result = await db.execute(
        select(AnalyticsROI).where(
            AnalyticsROI.id == roi_id,
            AnalyticsROI.tenant_id == tenant_id,
        )
    )
    roi = result.scalar_one_or_none()
    if not roi:
        raise HTTPException(status_code=404, detail="ROI não encontrada")
    roi.camera_id = body.camera_id
    roi.plugin_id = body.plugin_id or body.ia_type
    roi.name = body.name
    roi.polygon = body.polygon or body.polygon_points
    roi.config = body.config
    await db.flush()
    roi_cache.invalidate(str(tenant_id), body.camera_id)
    return ROIResponse(
        id=str(roi.id),
        camera_id=roi.camera_id,
        plugin_id=roi.plugin_id,
        ia_type=roi.plugin_id,
        name=roi.name,
        polygon=roi.polygon,
        config=roi.config,
        is_active=roi.is_active,
        created_at=roi.created_at,
    )


@router.delete("/rois/{roi_id}", status_code=204)
async def delete_roi(
    roi_id: uuid.UUID,
    db: DbSession,
    current_user: GestorUser,
) -> None:
    """Remove uma ROI."""
    from sqlalchemy import select
    from vms.analytics.models import AnalyticsROI
    from vms.plugins import roi_cache

    tenant_id = _get_tenant_id(current_user)
    result = await db.execute(
        select(AnalyticsROI).where(
            AnalyticsROI.id == roi_id,
            AnalyticsROI.tenant_id == tenant_id,
        )
    )
    roi = result.scalar_one_or_none()
    if not roi:
        raise HTTPException(status_code=404, detail="ROI não encontrada")
    roi_cache.invalidate(str(tenant_id), roi.camera_id)
    await db.delete(roi)


@router.get("/stats", response_model=AnalyticsStatsResponse)
async def get_dashboard_stats(
    db: DbSession,
    current_user: CurrentUser,
    hours: int = Query(24, ge=1, le=720),
) -> AnalyticsStatsResponse:
    """Retorna estatísticas para o dashboard de analytics."""
    from vms.analytics.analytic_event_service import AnalyticEventService

    svc = AnalyticEventService(db)
    stats = await svc.get_event_stats(_get_tenant_id(current_user), hours=hours)

    return AnalyticsStatsResponse(**stats)

