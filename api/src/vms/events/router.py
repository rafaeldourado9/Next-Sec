"""Rotas HTTP do bounded context de eventos — webhooks e consultas."""
from __future__ import annotations

import logging
import re
from datetime import datetime

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy import select

from vms.cameras.models import CameraModel
from vms.cameras.repository import CameraRepository
from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.shared.api.rate_limit import limiter
from vms.events.domain import AlprDetection
from vms.events.normalizers.base import registry
# Importa normalizers para forçar auto-registro
import vms.events.normalizers.hikvision  # noqa: F401
import vms.events.normalizers.intelbras  # noqa: F401
import vms.events.normalizers.generic    # noqa: F401
from vms.events.repository import EventRepository
from vms.events.schemas import (
    AlprWebhookRequest,
    EventListResponse,
    MediaMTXOnNotReadyPayload,
    MediaMTXOnReadyPayload,
    MediaMTXSegmentPayload,
    VmsEventResponse,
)
from vms.events.service import EventService

logger = logging.getLogger(__name__)
router = APIRouter()

_MEDIAMTX_PATH_RE = re.compile(r"tenant-(?P<tenant_id>[^/]+)/cam-(?P<camera_id>.+)")
_LIVE_PATH_RE     = re.compile(r"live/(?P<stream_key>[^/]+?)(?:\.stream)?$")


async def _get_redis(request: Request) -> Redis:
    """Extrai cliente Redis do state da aplicação."""
    return request.app.state.redis


def _event_svc(db: DbSession) -> EventService:
    """Constrói EventService com repositório."""
    return EventService(EventRepository(db))


# ─── Webhooks ALPR ────────────────────────────────────────────────────────────

@router.post(
    "/webhooks/alpr",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Webhook ALPR genérico",
    tags=["webhooks"],
)
@limiter.limit("500/minute")
async def webhook_alpr_generic(
    request: Request,
    body: AlprWebhookRequest,
    db: DbSession,
    redis: Redis = Depends(_get_redis),
) -> dict:
    """Recebe detecção ALPR no formato normalizado."""
    tenant_id = await _resolve_tenant(body.camera_id)
    detection = AlprDetection(
        camera_id=body.camera_id,
        tenant_id=tenant_id,
        plate=body.plate.upper(),
        confidence=body.confidence,
        manufacturer="generic",
        timestamp=body.timestamp,
        raw_payload=body.model_dump(mode="json"),
        image_b64=body.image_b64,
    )
    svc = _event_svc(db)
    event = await svc.ingest_alpr(detection, redis)
    return {"accepted": event is not None, "event_id": event.id if event else None}


@router.post(
    "/webhooks/alpr/{manufacturer}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Webhook ALPR por fabricante",
    tags=["webhooks"],
)
@limiter.limit("500/minute")
async def webhook_alpr_vendor(
    request: Request,
    manufacturer: str,
    body: dict,
    db: DbSession,
    camera_id: str = Query(...),
    tenant_id: str = Query(...),
    redis: Redis = Depends(_get_redis),
) -> dict:
    """Recebe payload raw do fabricante e normaliza internamente."""
    normalizer = registry.get(manufacturer)
    if not normalizer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fabricante não suportado: '{manufacturer}'",
        )
    try:
        detection = normalizer.normalize(body, camera_id, tenant_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Payload inválido para {manufacturer}: {exc}",
        ) from exc

    svc = _event_svc(db)
    event = await svc.ingest_alpr(detection, redis)
    return {"accepted": event is not None, "event_id": event.id if event else None}


# ─── Webhooks MediaMTX ────────────────────────────────────────────────────────

@router.post(
    "/webhooks/mediamtx/on_ready",
    status_code=status.HTTP_200_OK,
    summary="Webhook MediaMTX — stream pronto",
    tags=["webhooks"],
)
async def mediamtx_on_ready(
    body: MediaMTXOnReadyPayload, request: Request, db: DbSession
) -> dict:
    """Marca câmera como online quando stream está disponível."""
    ids = _parse_mediamtx_path(body.path) or await _resolve_live_path(body.path, db)
    if not ids:
        logger.warning("Path MediaMTX inválido em on_ready: %s", body.path)
        return {"ok": True}

    tenant_id, camera_id = ids
    logger.info("Stream pronto: tenant=%s camera=%s", tenant_id, camera_id)

    from sqlalchemy import update as sa_update
    from vms.cameras.models import CameraModel
    stmt = (
        sa_update(CameraModel)
        .where(CameraModel.id == camera_id, CameraModel.tenant_id == tenant_id)
        .values(is_online=True, last_seen_at=datetime.utcnow())
    )
    await db.execute(stmt)
    await db.commit()

    try:
        from vms.core.event_bus import publish_event
        await publish_event(
            "camera.online",
            {"camera_id": camera_id, "path": body.path},
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("Falha ao publicar camera.online (não crítico): %s", exc)

    return {"ok": True}


@router.post(
    "/webhooks/mediamtx/on_not_ready",
    status_code=status.HTTP_200_OK,
    summary="Webhook MediaMTX — stream encerrado",
    tags=["webhooks"],
)
async def mediamtx_on_not_ready(body: MediaMTXOnNotReadyPayload, db: DbSession) -> dict:
    """Marca câmera como offline quando stream é encerrado."""
    ids = _parse_mediamtx_path(body.path) or await _resolve_live_path(body.path, db)
    if not ids:
        return {"ok": True}

    tenant_id, camera_id = ids
    logger.info("Stream encerrado: tenant=%s camera=%s", tenant_id, camera_id)

    from sqlalchemy import update as sa_update
    from vms.cameras.models import CameraModel
    stmt = (
        sa_update(CameraModel)
        .where(CameraModel.id == camera_id, CameraModel.tenant_id == tenant_id)
        .values(is_online=False)
    )
    await db.execute(stmt)
    await db.commit()

    try:
        from vms.core.event_bus import publish_event
        await publish_event(
            "camera.offline",
            {"camera_id": camera_id, "path": body.path},
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning("Falha ao publicar camera.offline (não crítico): %s", exc)

    return {"ok": True}


@router.post(
    "/webhooks/mediamtx/on_record_segment_complete",
    status_code=status.HTTP_200_OK,
    summary="Webhook MediaMTX — segmento de gravação completo",
    tags=["webhooks"],
)
async def mediamtx_on_record_segment_complete(
    body: MediaMTXSegmentPayload, db: DbSession
) -> dict:
    """Estende o índice de cobertura (recording_windows) da câmera.

    Só afeta câmeras com gravação ligada — pra as demais o hook nem chega a
    disparar (MediaMTX só grava segmento se `record: true` no path).
    """
    ids = _parse_mediamtx_path(body.path)
    if not ids:
        return {"ok": True}
    tenant_id, camera_id = ids

    from vms.recordings.repository import RecordingWindowRepository
    from vms.recordings.service import build_recording_service

    try:
        svc = build_recording_service(RecordingWindowRepository(db))
        await svc.record_segment_complete(camera_id, tenant_id, body.segment_path)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Falha ao indexar segmento de gravação: camera=%s segment=%s",
            camera_id, body.segment_path,
        )
    return {"ok": True}


# ─── Consulta de Eventos ──────────────────────────────────────────────────────

@router.get(
    "/events",
    response_model=EventListResponse,
    summary="Listar eventos",
    tags=["events"],
)
async def list_events(
    claims: CurrentUser,
    db: DbSession,
    event_type: str | None = Query(default=None),
    plate: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    source: str | None = Query(default=None, description="'lpr' ou 'analytics'"),
    occurred_after: datetime | None = Query(default=None),
    occurred_before: datetime | None = Query(default=None),
    confidence_min: float | None = Query(default=None, ge=0.0, le=1.0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> EventListResponse:
    """Lista eventos do tenant com paginação e filtros opcionais."""
    offset = (page - 1) * page_size
    svc = _event_svc(db)
    events, total = await svc.list_events(
        tenant_id=claims.tenant_id,
        event_type=event_type,
        plate=plate,
        camera_id=camera_id,
        source=source,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        confidence_min=confidence_min,
        limit=page_size,
        offset=offset,
    )
    items = []
    for e in events:
        item = VmsEventResponse.model_validate(e)
        if e.image_path:
            item.image_url = f"/api/v1/events/{e.id}/image"
        items.append(item)
    return EventListResponse.build(items, total, page, page_size)


# ─── Exportação (CSV / PDF) ────────────────────────────────────────────────────

_EXPORT_MAX_ROWS = 5000


async def _fetch_export_rows(
    db: DbSession,
    tenant_id: str,
    *,
    event_type: str | None,
    plate: str | None,
    camera_id: str | None,
    source: str | None,
    occurred_after: datetime | None,
    occurred_before: datetime | None,
    confidence_min: float | None,
) -> list:
    """Busca eventos pros mesmos filtros de /events, sem o teto de page_size=100 —
    exportação precisa de tudo que bate no filtro (até um teto de sanidade), não
    só a página atual."""
    svc = _event_svc(db)
    events, _total = await svc.list_events(
        tenant_id=tenant_id,
        event_type=event_type,
        plate=plate,
        camera_id=camera_id,
        source=source,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        confidence_min=confidence_min,
        limit=_EXPORT_MAX_ROWS,
        offset=0,
    )
    return events


async def _camera_names(db: DbSession, tenant_id: str) -> dict[str, str]:
    """Mapa camera_id -> nome, pra exibir nome legível na exportação."""
    stmt = select(CameraModel.id, CameraModel.name).where(CameraModel.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return {row.id: row.name for row in result.all()}


@router.get(
    "/events/export/csv",
    summary="Exportar eventos filtrados em CSV",
    tags=["events"],
)
async def export_events_csv(
    claims: CurrentUser,
    db: DbSession,
    event_type: str | None = Query(default=None),
    plate: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    occurred_after: datetime | None = Query(default=None),
    occurred_before: datetime | None = Query(default=None),
    confidence_min: float | None = Query(default=None, ge=0.0, le=1.0),
) -> Response:
    """Exporta os eventos que batem nos filtros ativos (até 5000 linhas) em CSV."""
    import csv
    import io

    events = await _fetch_export_rows(
        db, claims.tenant_id,
        event_type=event_type, plate=plate, camera_id=camera_id, source=source,
        occurred_after=occurred_after, occurred_before=occurred_before,
        confidence_min=confidence_min,
    )
    cam_names = await _camera_names(db, claims.tenant_id)

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Placa", "Câmera", "Tipo", "Data/Hora", "Confiança (%)"])
    for e in events:
        writer.writerow([
            e.plate or "",
            cam_names.get(e.camera_id, e.camera_id or ""),
            e.event_type,
            e.occurred_at.strftime("%d/%m/%Y %H:%M:%S"),
            f"{round(e.confidence * 100)}" if e.confidence is not None else "",
        ])

    filename = f"deteccoes_alpr_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content="﻿" + buf.getvalue(),  # BOM — Excel abre acentuação correta
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/events/export/pdf",
    summary="Exportar eventos filtrados em PDF (padrão ABNT, P&B)",
    tags=["events"],
)
async def export_events_pdf(
    claims: CurrentUser,
    db: DbSession,
    event_type: str | None = Query(default=None),
    plate: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    occurred_after: datetime | None = Query(default=None),
    occurred_before: datetime | None = Query(default=None),
    confidence_min: float | None = Query(default=None, ge=0.0, le=1.0),
) -> Response:
    """Exporta os eventos que batem nos filtros ativos (até 5000 linhas) em PDF."""
    from vms.reports.pdf_generator import generate_pdf, render_template

    events = await _fetch_export_rows(
        db, claims.tenant_id,
        event_type=event_type, plate=plate, camera_id=camera_id, source=source,
        occurred_after=occurred_after, occurred_before=occurred_before,
        confidence_min=confidence_min,
    )
    cam_names = await _camera_names(db, claims.tenant_id)

    from vms.iam.models import TenantModel
    tenant_row = await db.scalar(select(TenantModel).where(TenantModel.id == claims.tenant_id))
    tenant_name = tenant_row.name if tenant_row else ""

    if occurred_after and occurred_before:
        period_label = f"{occurred_after.strftime('%d/%m/%Y %H:%M')} até {occurred_before.strftime('%d/%m/%Y %H:%M')}"
    elif occurred_after:
        period_label = f"a partir de {occurred_after.strftime('%d/%m/%Y %H:%M')}"
    elif occurred_before:
        period_label = f"até {occurred_before.strftime('%d/%m/%Y %H:%M')}"
    else:
        period_label = "Todo o histórico"

    camera_label = cam_names.get(camera_id, camera_id) if camera_id else "Todas"
    confidence_label = f"≥ {round(confidence_min * 100)}%" if confidence_min is not None else "Sem filtro"

    items = [
        {
            "plate": e.plate,
            "camera_name": cam_names.get(e.camera_id, e.camera_id or "—"),
            "occurred_at": e.occurred_at.strftime("%d/%m/%Y %H:%M:%S"),
            "confidence": f"{round(e.confidence * 100)}%" if e.confidence is not None else "—",
        }
        for e in events
    ]

    html = render_template("alpr_export", {
        "tenant_name": tenant_name,
        "period_label": period_label,
        "camera_label": camera_label,
        "plate_filter": plate,
        "confidence_label": confidence_label,
        "items": items,
    })
    pdf_bytes = generate_pdf(html)

    filename = f"deteccoes_alpr_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/events/{event_id}/clip",
    summary="Status/URL do clipe gerado para o evento",
    tags=["events"],
)
async def get_event_clip(
    event_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Retorna o clipe (5-10s) gerado a partir do evento, se já existir.

    Ver ADR-010 — clipe é armazenado no MinIO da própria VPS (sem provider
    externo no MVP). 404 se o evento não existir/não for do tenant, ou se o
    clipe ainda não foi gerado (processamento é assíncrono).
    """
    from vms.event_clips.schemas import EventClipResponse
    from vms.event_clips.service import build_event_clip_service

    svc = _event_svc(db)
    # Lança NotFoundError (→ 404) se o evento não existir ou não for do tenant
    await svc.get_event(event_id, claims.tenant_id)

    # Lança NotFoundError (→ 404) se o clipe ainda não foi gerado
    clip = await build_event_clip_service(db).get_clip(event_id)
    return EventClipResponse.model_validate(clip).model_dump()


@router.get("/events/{event_id}/image", include_in_schema=False)
async def get_event_image(
    event_id: str,
    db: DbSession,
    current_user: CurrentUser,
) -> Response:
    """Serve imagem JPEG de um evento VMS (autenticado)."""
    svc = _event_svc(db)
    event = await svc.get_event(event_id, current_user.tenant_id)

    if not event or not event.image_path:
        raise HTTPException(status_code=404, detail="Imagem não encontrada")

    full_path = f"/snapshots/{event.image_path}"
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado")

    return FileResponse(full_path, media_type="image/jpeg")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_mediamtx_path(path: str) -> tuple[str, str] | None:
    """
    Extrai (tenant_id, camera_id) do path MediaMTX.

    Suporta dois formatos:
    - tenant-{tid}/cam-{cid} → extração direta
    - live/{stream_key}      → requer lookup no DB (ver _resolve_live_path)
    """
    match = _MEDIAMTX_PATH_RE.match(path)
    if not match:
        return None
    return match.group("tenant_id"), match.group("camera_id")


async def _resolve_live_path(path: str, db) -> tuple[str, str] | None:
    """
    Resolve (tenant_id, camera_id) para paths no formato live/{stream_key}.

    Faz lookup no banco pelo rtmp_stream_key da câmera.
    """
    live_match = _LIVE_PATH_RE.match(path)
    if not live_match:
        return None
    stream_key = live_match.group("stream_key")
    repo = CameraRepository(db)
    camera = await repo.get_by_stream_key(stream_key)
    if not camera:
        return None
    return camera.tenant_id, camera.id


async def _resolve_tenant(camera_id: str) -> str:
    """Resolve tenant_id a partir do camera_id via repositório."""
    from vms.infrastructure.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        camera = await session.scalar(select(CameraModel).where(CameraModel.id == camera_id))
        if camera:
            return camera.tenant_id
    return "unknown"
