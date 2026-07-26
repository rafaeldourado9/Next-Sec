"""Rotas HTTP para controle PTZ de câmeras ONVIF."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.ptz.domain import PtzCommand, PtzPreset
from vms.cameras.ptz.service import PtzService
from vms.cameras.repository import CameraRepository
from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PtzMoveRequest(BaseModel):
    """Parâmetros para movimento contínuo PTZ."""

    pan: float = Field(default=0.0, ge=-1.0, le=1.0, description="Velocidade horizontal (-1 esq, +1 dir)")
    tilt: float = Field(default=0.0, ge=-1.0, le=1.0, description="Velocidade vertical (-1 baixo, +1 cima)")
    zoom: float = Field(default=0.0, ge=-1.0, le=1.0, description="Velocidade de zoom (-1 out, +1 in)")
    speed: float = Field(default=0.5, ge=0.0, le=1.0, description="Velocidade geral 0.0–1.0")


class GotoPresetRequest(BaseModel):
    """Parâmetros para ir a um preset."""

    speed: float = Field(default=0.5, ge=0.0, le=1.0)


class SavePresetRequest(BaseModel):
    """Parâmetros para salvar preset."""

    name: str = Field(..., min_length=1, max_length=64)


class PtzPresetResponse(BaseModel):
    """Resposta com dados de um preset PTZ."""

    token: str
    name: str | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ptz_svc(db: AsyncSession) -> PtzService:
    """Constrói PtzService com repositório."""
    return PtzService(CameraRepository(db))


def _handle_ptz_errors(exc: Exception) -> HTTPException:
    """Converte exceções de domínio para HTTPException."""
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro PTZ: {exc}")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/cameras/{camera_id}/ptz/move",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mover câmera PTZ (movimento contínuo)",
    tags=["ptz"],
)
async def ptz_move(
    camera_id: str,
    body: PtzMoveRequest,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Inicia movimento contínuo pan/tilt/zoom. Enviar velocidade 0,0,0 equivale a parar."""
    svc = _ptz_svc(db)
    command = PtzCommand(pan=body.pan, tilt=body.tilt, zoom=body.zoom, speed=body.speed)
    try:
        await svc.move(camera_id, claims.tenant_id, command)
    except Exception as exc:
        raise _handle_ptz_errors(exc) from exc


@router.post(
    "/cameras/{camera_id}/ptz/stop",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Parar movimento PTZ",
    tags=["ptz"],
)
async def ptz_stop(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Para qualquer movimento PTZ em curso na câmera."""
    svc = _ptz_svc(db)
    try:
        await svc.stop(camera_id, claims.tenant_id)
    except Exception as exc:
        raise _handle_ptz_errors(exc) from exc


@router.get(
    "/cameras/{camera_id}/ptz/presets",
    response_model=list[PtzPresetResponse],
    summary="Listar presets PTZ",
    tags=["ptz"],
)
async def list_ptz_presets(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> list[PtzPresetResponse]:
    """Lista presets PTZ salvos na câmera."""
    svc = _ptz_svc(db)
    try:
        presets = await svc.list_presets(camera_id, claims.tenant_id)
    except Exception as exc:
        raise _handle_ptz_errors(exc) from exc
    return [PtzPresetResponse(token=p.token, name=p.name) for p in presets]


@router.post(
    "/cameras/{camera_id}/ptz/presets/{preset_token}/goto",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Ir para preset PTZ",
    tags=["ptz"],
)
async def goto_ptz_preset(
    camera_id: str,
    preset_token: str,
    body: GotoPresetRequest,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Move câmera para a posição de um preset salvo."""
    svc = _ptz_svc(db)
    try:
        await svc.goto_preset(camera_id, claims.tenant_id, preset_token, body.speed)
    except Exception as exc:
        raise _handle_ptz_errors(exc) from exc


@router.post(
    "/cameras/{camera_id}/ptz/presets/{preset_token}/save",
    response_model=PtzPresetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Salvar posição atual como preset PTZ",
    tags=["ptz"],
)
async def save_ptz_preset(
    camera_id: str,
    preset_token: str,
    body: SavePresetRequest,
    claims: CurrentUser,
    db: DbSession,
) -> PtzPresetResponse:
    """Salva a posição atual da câmera como preset com o nome fornecido."""
    svc = _ptz_svc(db)
    try:
        preset = await svc.save_preset(camera_id, claims.tenant_id, body.name)
    except Exception as exc:
        raise _handle_ptz_errors(exc) from exc
    return PtzPresetResponse(token=preset.token, name=preset.name)
