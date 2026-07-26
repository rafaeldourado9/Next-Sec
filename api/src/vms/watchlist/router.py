"""Rotas HTTP do bounded context de watchlist facial."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, UploadFile, status

from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.watchlist.schemas import FaceProfileResponse
from vms.watchlist.service import WatchlistService, build_watchlist_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _svc(db: DbSession) -> WatchlistService:
    """Constrói WatchlistService com sessão do banco injetada."""
    return build_watchlist_service(db)


@router.get("/faces", response_model=list[FaceProfileResponse], summary="Listar watchlist")
async def list_faces(claims: CurrentUser, db: DbSession) -> list[FaceProfileResponse]:
    """Lista rostos cadastrados na watchlist do tenant autenticado."""
    profiles = await _svc(db).list_profiles(claims.tenant_id)
    return [FaceProfileResponse.model_validate(p) for p in profiles]


@router.post(
    "/faces", response_model=FaceProfileResponse, status_code=status.HTTP_201_CREATED,
    summary="Cadastrar rosto na watchlist",
)
async def create_face(
    claims: CurrentUser,
    db: DbSession,
    name: str = Form(...),
    image: UploadFile = File(...),
) -> FaceProfileResponse:
    """Cadastra um rosto na watchlist.

    Requer que o tenant tenha consentimento LGPD ativo para reconhecimento
    facial (`POST /lgpd/consent` com `data_type=face`) — ver
    WatchlistService.create_profile.
    """
    image_bytes = await image.read()
    profile = await _svc(db).create_profile(
        tenant_id=claims.tenant_id,
        name=name,
        image_bytes=image_bytes,
        content_type=image.content_type or "image/jpeg",
    )
    return FaceProfileResponse.model_validate(profile)


@router.delete(
    "/faces/{profile_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover rosto da watchlist",
)
async def delete_face(
    profile_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Remove um rosto da watchlist (soft delete + apaga a imagem do storage)."""
    await _svc(db).delete_profile(profile_id, claims.tenant_id)
