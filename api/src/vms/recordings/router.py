"""Rotas HTTP do bounded context de recordings."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from jose import JWTError

from vms.infrastructure.security import decode_token
from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.recordings.repository import RecordingWindowRepository
from vms.recordings.service import build_recording_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/cameras/{camera_id}/recordings/availability",
    summary="Intervalos com gravação disponível",
    tags=["recordings"],
)
async def get_availability(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
    start: datetime = Query(...),
    end: datetime = Query(...),
) -> dict:
    """Lista os intervalos de tempo com cobertura de gravação — pra sombrear a timeline."""
    svc = build_recording_service(RecordingWindowRepository(db))
    ranges = await svc.get_available_ranges(camera_id, claims.tenant_id, start, end)
    return {"camera_id": camera_id, "ranges": ranges}


@router.get(
    "/cameras/{camera_id}/recordings/playback-url",
    summary="URL assinada de playback pra um intervalo",
    tags=["recordings"],
)
async def get_playback_url(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
    start: datetime = Query(...),
    end: datetime = Query(...),
) -> dict:
    """Assina uma URL de VOD (via /mediamtx-playback/) pro intervalo pedido.

    O token embute tenant/câmera/intervalo — não dá acesso a nenhum outro
    trecho ou câmera além do que foi pedido aqui.
    """
    svc = build_recording_service(RecordingWindowRepository(db))
    result = svc.build_playback_url(camera_id, claims.tenant_id, start, end)
    return {**result, "camera_id": camera_id, "expires_in": 3600}


@router.get(
    "/internal/verify-playback-token",
    summary="[interno] Valida token de playback pro nginx auth_request",
    tags=["internal"],
    include_in_schema=False,
)
async def verify_playback_token(
    token: str | None = Query(default=None),
    path: str | None = Query(default=None),
) -> Response:
    """Usado exclusivamente pelo nginx via auth_request — só o status importa
    (200 libera, qualquer outro bloqueia). Não é alcançável de fora do nginx
    (bloqueado por `deny all` em /internal/ no nginx.conf, exceto este path
    exato que é `internal;` — subrequest apenas)."""
    if not token:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        claims = decode_token(token)
    except JWTError:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    if claims.get("type") != "playback":
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # `path` vem do mesmo query string que o token (?path=...&token=...) —
    # confirma que o token não está sendo reaproveitado pra outra câmera.
    camera_id = claims.get("camera_id")
    tenant_id = claims.get("tenant_id")
    if path and camera_id and tenant_id:
        expected_path = f"tenant-{tenant_id}/cam-{camera_id}"
        if path != expected_path:
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    return Response(status_code=status.HTTP_200_OK)
