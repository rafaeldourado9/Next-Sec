"""Rotas do contrato público de plugins — acesso por API key."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.repository import CameraRepository
from vms.shared.api.dependencies import ApiKeyHeader, DbSession
from vms.infrastructure.exceptions import AuthenticationError
from vms.shared.exceptions import NotFoundError
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import AuthService
from vms.plugins.schemas import (
    PluginCameraResponse,
    PluginEventRequest,
    PluginEventResponse,
    StreamTokenResponse,
)
from vms.plugins.service import PluginService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plugins"])

# API key do analytics service (configurada via env)
_ANALYTICS_API_KEY = os.environ.get("VMS_API_KEY", "dev-analytics-key")


# ─── Dependência de autenticação por API key ──────────────────────────────────

async def _resolve_plugin_tenant(api_key: ApiKeyHeader, db: DbSession) -> str:
    """Autentica API key e retorna tenant_id associado.

    Aceita tanto API keys do banco quanto a chave env do analytics service.
    """
    # Fast-path: chave do analytics service via env (sem lookup no banco)
    if api_key == _ANALYTICS_API_KEY:
        result = await db.execute(
            text("SELECT tenant_id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1")
        )
        row = result.first()
        if row:
            return str(row[0])
        # Nenhum usuário ainda — analytics aguarda onboarding
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nenhum tenant configurado. Conclua o onboarding primeiro.",
        )

    # Lookup normal no banco (API keys de agentes/integrações)
    auth_svc = AuthService(
        user_repo=None,  # type: ignore[arg-type]
        api_key_repo=ApiKeyRepository(db),
    )
    try:
        key_entity = await auth_svc.authenticate_api_key(api_key)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou revogada",
        ) from exc
    return key_entity.tenant_id


def _plugin_svc(db: AsyncSession) -> PluginService:
    return PluginService(CameraRepository(db))


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "/plugins/cameras",
    response_model=list[PluginCameraResponse],
    summary="Câmeras disponíveis para o plugin",
)
async def list_plugin_cameras(api_key: ApiKeyHeader, db: DbSession) -> list[PluginCameraResponse]:
    """
    Lista câmeras ativas do tenant associado à API key.

    O plugin usa este endpoint para descobrir quais streams processar.
    """
    tenant_id = await _resolve_plugin_tenant(api_key, db)
    cameras = await _plugin_svc(db).list_cameras(tenant_id)
    return [
        PluginCameraResponse(
            id=c.id,
            name=c.name,
            manufacturer=c.manufacturer,
            stream_protocol=c.stream_protocol,
            is_online=c.is_online,
            mediamtx_path=c.mediamtx_path,
            location=c.location,
        )
        for c in cameras
        if c.is_active
    ]


@router.get(
    "/plugins/stream-token",
    response_model=StreamTokenResponse,
    summary="Token de acesso ao stream RTSP",
)
async def get_stream_token(
    camera_id: str,
    api_key: ApiKeyHeader,
    db: DbSession,
    request: Request,
) -> StreamTokenResponse:
    """
    Gera token JWT de curta duração para o plugin acessar o stream RTSP no MediaMTX.

    O plugin monta a URL como: rtsp://<token>@<host>:8554/<mediamtx_path>
    O token expira no mesmo intervalo que os access tokens de usuário.
    """
    tenant_id = await _resolve_plugin_tenant(api_key, db)
    mediamtx_host = request.headers.get("X-MediaMTX-Host", "mediamtx")

    try:
        result = await _plugin_svc(db).get_stream_token(camera_id, tenant_id, mediamtx_host)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return StreamTokenResponse(**result)


@router.post(
    "/plugins/events",
    response_model=PluginEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingestão de evento detectado pelo plugin",
)
async def ingest_plugin_event(
    body: PluginEventRequest,
    api_key: ApiKeyHeader,
    db: DbSession,
) -> PluginEventResponse:
    """
    Recebe evento detectado pelo plugin e persiste como VmsEvent.

    O `event_type` é livre — convenção recomendada: `<plugin>.<acao>`.
    Exemplos: `intrusion.detected`, `lpr.detected`, `people.count`.

    O `payload` aceita qualquer estrutura — o VMS não valida o conteúdo.
    """
    # Autentica via API key (valida que a chave existe)
    await _resolve_plugin_tenant(api_key, db)

    # Resolve tenant a partir da câmera — garante isolamento correto em multi-tenant
    from sqlalchemy import select as _sa_select
    from vms.cameras.models import CameraModel
    cam_row = await db.scalar(
        _sa_select(CameraModel.tenant_id).where(CameraModel.id == body.camera_id)
    )
    if cam_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Câmera não encontrada")
    tenant_id = str(cam_row)

    event_id = await _plugin_svc(db).ingest_event(
        db=db,
        tenant_id=tenant_id,
        camera_id=body.camera_id,
        event_type=body.event_type,
        confidence=body.confidence,
        occurred_at=body.occurred_at,
        payload=body.payload,
        snapshot_path=body.snapshot_path,
    )

    # SSE em tempo real para o frontend
    try:
        from vms.infrastructure.messaging.event_bus import publish_event
        severity = (body.payload or {}).get("severity", "info")
        await publish_event(
            "analytics.event",
            {
                "event_type": body.event_type,
                "camera_id": body.camera_id,
                "severity": severity,
                "confidence": body.confidence,
                "occurred_at": body.occurred_at.isoformat() if body.occurred_at else None,
            },
            tenant_id=tenant_id,
        )
    except Exception:
        logger.debug("Falha ao publicar SSE para evento analytics (não crítico)", exc_info=True)

    # Persiste em analytic_events (tabela unificada — lida por /analytics/events e /search/video)
    try:
        from datetime import datetime, timezone, timedelta
        from vms.analytics.analytic_event_model import AnalyticEvent
        analytic_event = AnalyticEvent(
            tenant_id=tenant_id,
            camera_id=body.camera_id,
            event_type=body.event_type,
            attributes=body.payload or {},
            confidence=body.confidence,
            thumbnail_key=body.snapshot_path,
            occurred_at=body.occurred_at or datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(analytic_event)
        await db.flush()
    except Exception:
        logger.warning("Falha ao criar AnalyticEvent (não crítico)", exc_info=True)

    return PluginEventResponse(id=event_id)


@router.get(
    "/plugins/rois",
    summary="ROIs configuradas para as câmeras do tenant",
)
async def list_plugin_rois(
    api_key: ApiKeyHeader,
    db: DbSession,
    camera_id: str | None = None,
) -> list[dict]:
    """Retorna ROIs (zonas de detecção) para uso pelos plugins.

    Resultado cacheado por 60s em memória — analytics bate neste endpoint
    a cada câmera processada, então evitar o round-trip ao banco é crítico.
    """
    from vms.plugins import roi_cache

    tenant_id = await _resolve_plugin_tenant(api_key, db)

    cached = roi_cache.get(tenant_id, camera_id)
    if cached is not None:
        return cached

    from sqlalchemy import select
    from vms.analytics.models import AnalyticsROI, ROISchedule
    from vms.analytics.schedule import is_armed_now

    stmt = select(AnalyticsROI).where(
        AnalyticsROI.tenant_id == tenant_id,
        AnalyticsROI.is_active.is_(True),
    )
    if camera_id:
        stmt = stmt.where(AnalyticsROI.camera_id == camera_id)
    result = await db.execute(stmt)
    rois = result.scalars().all()

    data = []
    for r in rois:
        sched_result = await db.execute(
            select(ROISchedule).where(ROISchedule.roi_id == r.id)
        )
        schedules = sched_result.scalars().all()
        data.append({
            "id": str(r.id),
            "name": r.name,
            "camera_id": r.camera_id,
            "plugin_id": r.plugin_id,
            "polygon_points": r.polygon,
            "config": r.config,
            "schedules": [
                {
                    "day_of_week": s.day_of_week,
                    "start_time": s.start_time.isoformat(),
                    "end_time": s.end_time.isoformat(),
                }
                for s in schedules
                if s.is_active
            ],
            # Zona sem horário cadastrado = sempre armada (comportamento anterior preservado)
            "is_armed_now": is_armed_now(list(schedules)),
        })
    roi_cache.set(tenant_id, camera_id, data)
    return data


@router.get(
    "/plugins/watchlist",
    summary="Rostos da watchlist para reconhecimento facial",
)
async def list_plugin_watchlist(
    api_key: ApiKeyHeader,
    db: DbSession,
) -> list[dict]:
    """Retorna a watchlist facial do tenant para uso pelo plugin `face_recognition`.

    Gate de LGPD: se `tenant.facial_recognition_enabled=False`, retorna lista
    vazia — é este endpoint, não um mecanismo de enable/disable separado, que
    garante que o plugin nunca compute embedding para um tenant sem
    consentimento (ver ADR-014 e reuse-plan.md).

    Resultado cacheado por 60s — o serviço de analytics baixa cada imagem de
    referência e computa o embedding localmente (ver ADR-010/ADR-014).
    """
    from sqlalchemy import select
    from vms.iam.models import TenantModel
    from vms.plugins import watchlist_cache
    from vms.watchlist.models import FaceProfileModel

    tenant_id = await _resolve_plugin_tenant(api_key, db)

    cached = watchlist_cache.get(tenant_id)
    if cached is not None:
        return cached

    tenant = await db.scalar(select(TenantModel).where(TenantModel.id == tenant_id))
    if not tenant or not tenant.facial_recognition_enabled:
        watchlist_cache.set(tenant_id, [])
        return []

    result = await db.execute(
        select(FaceProfileModel).where(
            FaceProfileModel.tenant_id == tenant_id,
            FaceProfileModel.is_active.is_(True),
            FaceProfileModel.deleted_at.is_(None),
        )
    )
    profiles = result.scalars().all()

    from vms.infrastructure.config import get_settings
    from vms.infrastructure.object_storage import ObjectStorage

    storage = ObjectStorage()
    bucket = get_settings().minio_bucket_analytics
    data = []
    for p in profiles:
        if not p.reference_image_path:
            continue
        try:
            image_url = storage.get_presigned_url(bucket, p.reference_image_path, expires=300)
        except Exception:
            logger.warning("Falha ao gerar URL de imagem da watchlist %s", p.id)
            continue
        data.append({"id": str(p.id), "name": p.name, "image_url": image_url})

    watchlist_cache.set(tenant_id, data)
    return data


@router.get(
    "/plugins/cameras/{camera_id}/active-plugins",
    summary="Plugins ativos para uma câmera",
)
async def get_active_plugins_for_camera(
    camera_id: str,
    api_key: ApiKeyHeader,
    db: DbSession,
) -> dict:
    """
    Retorna lista de plugins com status='running' para uma câmera específica.

    Usa as ROIs configuradas para determinar quais plugins estão ativos.
    Se não houver ROIs, retorna todos os plugins conhecidos (fallback).
    """
    tenant_id = await _resolve_plugin_tenant(api_key, db)

    from sqlalchemy import select
    from vms.analytics.models import AnalyticsROI, PluginInstallation

    # Buscar ROIs ativas para esta câmera
    stmt = select(AnalyticsROI.plugin_id).where(
        AnalyticsROI.tenant_id == tenant_id,
        AnalyticsROI.camera_id == camera_id,
        AnalyticsROI.is_active.is_(True),
    )
    result = await db.execute(stmt)
    roi_plugin_ids = [row[0] for row in result.all()]

    # Buscar instalações com status='running'
    install_stmt = select(PluginInstallation.plugin_id).where(
        PluginInstallation.tenant_id == tenant_id,
        PluginInstallation.status == "running",
    )
    install_result = await db.execute(install_stmt)
    running_plugins = [row[0] for row in install_result.all()]

    # Interseção: plugins que têm ROI E estão rodando
    if roi_plugin_ids:
        active_plugins = list(set(roi_plugin_ids) & set(running_plugins))
    else:
        # Sem ROIs — fallback: todos os plugins rodando
        active_plugins = running_plugins

    return {"camera_id": camera_id, "active_plugins": active_plugins}


# ─── LGPD: Face Recognition ──────────────────────────────────────────────────

@router.post(
    "/plugins/cameras/{camera_id}/face-recognition/consent",
    summary="Registrar consentimento LGPD para face recognition",
)
async def register_face_recognition_consent(
    camera_id: str,
    api_key: ApiKeyHeader,
    db: DbSession,
) -> dict:
    """
    Registra consentimento explícito para reconhecimento facial (LGPD Art. 11).

    Body esperado: {"consent": true, "tenant_id": "..."}
    """
    from fastapi import Body
    body = await Body()
    consent = body.get("consent", False)
    tenant_id = body.get("tenant_id")

    if not tenant_id:
        tenant_id = await _resolve_plugin_tenant(api_key, db)

    from vms.iam.models import TenantModel
    from sqlalchemy import update as sa_update
    from datetime import datetime, timezone

    stmt = (
        sa_update(TenantModel)
        .where(TenantModel.id == tenant_id)
        .values(
            facial_recognition_enabled=consent,
            facial_recognition_consent_at=datetime.now(timezone.utc) if consent else None,
        )
    )
    await db.execute(stmt)
    await db.flush()

    return {
        "camera_id": camera_id,
        "tenant_id": tenant_id,
        "consent_registered": consent,
    }
