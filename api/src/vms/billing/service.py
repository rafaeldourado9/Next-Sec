"""Application service de licenciamento — ativação e status de chave por tenant."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.billing.models import LicenseKeyModel
from vms.billing.schemas import LicenseStatusResponse
from vms.iam.models import TenantModel
from vms.shared.exceptions import NotFoundError, ValidationError


class BillingService:
    """Casos de uso de licenciamento (ativação de chave, consulta de status)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_status(self, tenant_id: str) -> LicenseStatusResponse:
        """Retorna o status de licença do tenant autenticado."""
        tenant = await self._session.get(TenantModel, tenant_id)
        if not tenant:
            raise NotFoundError("Tenant", tenant_id)

        if not tenant.license_key_id:
            return LicenseStatusResponse(active=False, onboarding_complete=tenant.onboarding_complete)

        license_key = await self._session.get(LicenseKeyModel, tenant.license_key_id)
        if not license_key:
            return LicenseStatusResponse(active=False, onboarding_complete=tenant.onboarding_complete)

        active = license_key.status == "active" and not self._is_expired(license_key)
        return LicenseStatusResponse(
            active=active,
            onboarding_complete=tenant.onboarding_complete,
            deployment_model=license_key.deployment_model,
            license_key=license_key.license_key,
            max_cameras=license_key.max_cameras,
            expires_at=license_key.expires_at,
            status=license_key.status,
        )

    async def activate(self, tenant_id: str, license_key_value: str) -> LicenseStatusResponse:
        """Ativa uma chave de licença para o tenant autenticado.

        A chave precisa existir, estar com status 'active', não expirada, e
        não estar atrelada a outro tenant (uma chave só pode ser usada uma vez).
        """
        stmt = select(LicenseKeyModel).where(LicenseKeyModel.license_key == license_key_value)
        license_key = await self._session.scalar(stmt)

        if not license_key or license_key.status != "active" or self._is_expired(license_key):
            raise ValidationError("Chave inválida ou já utilizada.")

        if license_key.tenant_id and license_key.tenant_id != tenant_id:
            raise ValidationError("Chave inválida ou já utilizada.")

        tenant = await self._session.get(TenantModel, tenant_id)
        if not tenant:
            raise NotFoundError("Tenant", tenant_id)

        license_key.tenant_id = tenant_id
        license_key.activated_at = datetime.now(timezone.utc)
        tenant.license_key_id = license_key.id
        tenant.onboarding_complete = True

        return await self.get_status(tenant_id)

    @staticmethod
    def _is_expired(license_key: LicenseKeyModel) -> bool:
        if not license_key.expires_at:
            return False
        return license_key.expires_at < datetime.now(timezone.utc)


def build_billing_service(session: AsyncSession) -> BillingService:
    """Factory que constrói BillingService com a sessão do banco injetada."""
    return BillingService(session)
