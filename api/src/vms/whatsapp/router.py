"""Rotas HTTP — proxy da conexão WhatsApp (Arcanum), ver ADR-009.

O Arcanum roda só na rede interna do docker-compose (sem porta exposta ao
host) — o frontend nunca fala com ele diretamente, sempre via essas rotas.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, status as http_status

from vms.infrastructure.config import get_settings
from vms.shared.api.dependencies import AdminUser, CurrentUser
from vms.whatsapp.schemas import WhatsAppQrResponse, WhatsAppStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def _arcanum_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.arcanum_base_url.rstrip('/')}{path}"


def _instance_name() -> str:
    return get_settings().arcanum_instance_name


@router.get("/status", response_model=WhatsAppStatusResponse, summary="Status da conexão WhatsApp")
async def get_status(claims: CurrentUser) -> WhatsAppStatusResponse:
    """Consulta o estado atual da sessão WhatsApp (sem gerar QR novo)."""
    instance = _instance_name()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_arcanum_url("/api/instance/fetchInstances"))
        resp.raise_for_status()
        instances = resp.json()
    except httpx.HTTPError:
        logger.warning("Arcanum indisponível ao consultar status")
        return WhatsAppStatusResponse(connected=False, status="unavailable")

    entry = next((i for i in instances if i.get("instanceName") == instance), None)
    if not entry:
        return WhatsAppStatusResponse(connected=False, status="not_created")

    state = str(entry.get("status") or "unknown")
    return WhatsAppStatusResponse(connected=state in ("open", "connected"), status=state)


@router.post("/connect", response_model=WhatsAppQrResponse, summary="Conectar WhatsApp (gera QR)")
async def connect(claims: AdminUser) -> WhatsAppQrResponse:
    """Garante que a instância existe e retorna um QR novo para escanear."""
    instance = _instance_name()
    async with httpx.AsyncClient(timeout=15.0) as client:
        create_resp = await client.post(
            _arcanum_url("/api/instance/create"), json={"instanceName": instance}
        )
        if create_resp.status_code not in (200, 201, 409):
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível criar a instância no Arcanum",
            )
        try:
            connect_resp = await client.get(_arcanum_url(f"/api/instance/connect/{instance}"))
            connect_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Arcanum indisponível",
            ) from exc

    data = connect_resp.json()
    return WhatsAppQrResponse(qr=data.get("qr"), status=str(data.get("status") or "qr"))


@router.post(
    "/disconnect", status_code=http_status.HTTP_204_NO_CONTENT, summary="Desconectar WhatsApp"
)
async def disconnect(claims: AdminUser) -> None:
    """Desconecta (logout) a sessão WhatsApp atual."""
    instance = _instance_name()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.delete(_arcanum_url(f"/api/instance/logout/{instance}"))
        except httpx.HTTPError:
            logger.warning("Falha ao desconectar instância '%s' no Arcanum", instance)
