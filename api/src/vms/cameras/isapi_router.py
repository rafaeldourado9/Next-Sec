"""Rotas HTTP para integração ISAPI Hikvision."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from vms.cameras.domain import Camera
from vms.cameras.repository import CameraRepository
from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.infrastructure.cameras.isapi_client import ISAPIClient
from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cameras/{camera_id}/isapi", tags=["cameras-isapi"])


def _get_isapi_client(camera: Camera) -> ISAPIClient | None:
    """Cria ISAPIClient a partir dos dados da câmera."""
    if not camera.isapi_enabled or not camera.isapi_base_url:
        return None
    if not camera.isapi_username or not camera.isapi_password:
        return None

    settings = get_settings()
    # Decrypt password se necessário (assumindo que já está encryptado no DB)
    password = camera.isapi_password
    # Se usar encryption, descomentar:
    # from vms.infrastructure.encryption import decrypt
    # password = decrypt(camera.isapi_password)

    return ISAPIClient(
        base_url=camera.isapi_base_url,
        username=camera.isapi_username,
        password=password,
        timeout=getattr(settings, 'isapi_timeout_seconds', 10),
        retry_count=getattr(settings, 'isapi_retry_count', 3),
    )


@router.post(
    "/probe",
    summary="Provar conexão ISAPI e descobrir capacidades",
)
async def probe_isapi(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """
    Conecta à câmera via ISAPI e descobre:
    - Modelo, firmware, serial number
    - Capacidades (Smart Events, PTZ, etc.)
    Salva os dados descobertos no banco.
    """
    repo = CameraRepository(db)
    camera = await repo.get_by_id(camera_id, claims.tenant_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    client = _get_isapi_client(camera)
    if not client:
        raise HTTPException(
            status_code=400,
            detail="ISAPI não configurado. Habilite e configure URL/credenciais.",
        )

    try:
        probe_data = await client.probe()

        # Atualizar câmera com dados descobertos
        camera.model_name = probe_data.get("model_name")
        camera.serial_number = probe_data.get("serial_number")
        camera.firmware_version = probe_data.get("firmware_version")
        camera.isapi_capabilities = probe_data.get("capabilities", {})
        await repo.update(camera)
        await db.commit()

        return probe_data

    except Exception as exc:
        logger.error("Falha no probe ISAPI: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao conectar via ISAPI: {exc}",
        )


@router.get(
    "/capabilities",
    summary="Consultar capacidades ISAPI da câmera",
)
async def get_capabilities(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Retorna capacidades cached da câmera ou consulta ao vivo."""
    repo = CameraRepository(db)
    camera = await repo.get_by_id(camera_id, claims.tenant_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    # Retorna cache se disponível
    if camera.isapi_capabilities:
        return {
            "cached": True,
            "capabilities": camera.isapi_capabilities,
            "model_name": camera.model_name,
            "firmware_version": camera.firmware_version,
        }

    # Consulta ao vivo
    client = _get_isapi_client(camera)
    if not client:
        raise HTTPException(status_code=400, detail="ISAPI não configurado")

    try:
        caps = await client.get_capabilities()
        return {"cached": False, "capabilities": caps}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ISAPI: {exc}")


@router.post(
    "/configure-push",
    summary="Configurar Alarm Server na câmera",
)
async def configure_push(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
    request: dict = {"webhook_url": None},
) -> dict:
    """
    Configura Alarm Server na câmera para push de Smart Events.

    A câmera passará a enviar eventos para a URL do webhook configurada.
    """
    repo = CameraRepository(db)
    camera = await repo.get_by_id(camera_id, claims.tenant_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    client = _get_isapi_client(camera)
    if not client:
        raise HTTPException(status_code=400, detail="ISAPI não configurado")

    # URL do webhook (pode vir do request ou usar default)
    webhook_url = request.get("webhook_url")
    if not webhook_url:
        settings = get_settings()
        # URL pública do VMS para webhooks
        webhook_url = f"{settings.vms_api_url}/webhooks/hik_pro_connect"

    try:
        success = await client.configure_alarm_server(webhook_url)
        if success:
            return {"ok": True, "webhook_url": webhook_url}
        else:
            raise HTTPException(status_code=502, detail="Falha ao configurar Alarm Server")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ISAPI: {exc}")


@router.post(
    "/sync-time",
    summary="Sincronizar relógio da câmera",
)
async def sync_time(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Sincroniza o relógio da câmera com o servidor."""
    repo = CameraRepository(db)
    camera = await repo.get_by_id(camera_id, claims.tenant_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    client = _get_isapi_client(camera)
    if not client:
        raise HTTPException(status_code=400, detail="ISAPI não configurado")

    try:
        success = await client.sync_time()
        return {"ok": success}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ISAPI: {exc}")


@router.get(
    "/snapshot",
    summary="Capturar snapshot via ISAPI",
)
async def get_snapshot(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
):
    """Captura snapshot via ISAPI (fallback para ONVIF)."""
    from fastapi.responses import Response

    repo = CameraRepository(db)
    camera = await repo.get_by_id(camera_id, claims.tenant_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Câmera não encontrada")

    client = _get_isapi_client(camera)
    if not client:
        raise HTTPException(status_code=400, detail="ISAPI não configurado")

    try:
        image_bytes = await client.get_snapshot()
        return Response(content=image_bytes, media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ISAPI: {exc}")
