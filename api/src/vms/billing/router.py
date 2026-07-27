"""Rotas HTTP do bounded context de licenciamento."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from vms.billing.schemas import ActivateLicenseRequest, LicenseStatusResponse
from vms.billing.service import BillingService, build_billing_service
from vms.shared.api.dependencies import CurrentUser, DbSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _svc(db: DbSession) -> BillingService:
    """Constrói BillingService com sessão do banco injetada."""
    return build_billing_service(db)


@router.get("/status", response_model=LicenseStatusResponse, summary="Status de licença do tenant")
async def get_status(claims: CurrentUser, db: DbSession) -> LicenseStatusResponse:
    """Consulta o status de licença/onboarding do tenant autenticado."""
    return await _svc(db).get_status(claims.tenant_id)


@router.post("/activate", response_model=LicenseStatusResponse, summary="Ativar chave de licença")
async def activate(
    body: ActivateLicenseRequest,
    claims: CurrentUser,
    db: DbSession,
) -> LicenseStatusResponse:
    """Ativa uma chave de licença para o tenant autenticado."""
    return await _svc(db).activate(claims.tenant_id, body.license_key)
