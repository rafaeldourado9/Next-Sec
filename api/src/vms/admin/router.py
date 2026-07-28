"""Admin Panel — endpoints exclusivos do franqueado (role: admin).

Gestão de tenants e impersonation.

NOTA (Next Sec): a versão original deste router (vms/) também tinha seções de
billing GMV, faturas e planos de preço, todas dependentes de `vms.billing.models`.
O módulo `billing` não foi copiado para o Next Sec (fora do escopo do MVP —
ver .genesis/architecture/reuse-plan.md), então essas seções foram removidas
para não quebrar a inicialização da API com um ImportError. Se billing for
reintroduzido no futuro, a versão original está preservada em
`vms/api/src/vms/admin/router.py` (projeto `vms/`, intocado).
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.models import TenantModel, UserModel
from vms.audit.models import AuditLogModel
from vms.billing.models import LicenseKeyModel
from vms.cameras.models import CameraModel
from vms.cameras.repository import AgentRepository, AgentTunnelRepository, CameraRepository
from vms.cameras.service import AgentService
from vms.cameras.wireguard_client import WireGuardHubClient
from vms.iam.domain import UserRole
from vms.iam.repository import ApiKeyRepository, TenantRepository, UserRepository
from vms.iam.service import ApiKeyService, TenantService, UserService
from vms.shared.api.dependencies import AdminUser, DbSession
from vms.infrastructure.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_LICENSE_KEY_ALPHABET = string.ascii_uppercase + string.digits
_PASSWORD_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _generate_license_key() -> str:
    """Mesmo formato usado por `scripts/create_license.py` (XXXX-XXXXX-XXXXX-XXXXX-XXXXX)."""
    groups = [4, 5, 5, 5, 5]
    return "-".join(
        "".join(secrets.choice(_LICENSE_KEY_ALPHABET) for _ in range(n)) for n in groups
    )


def _generate_default_password() -> str:
    """Senha padrão legível (3 grupos de 4) — trocada obrigatoriamente no primeiro login."""
    groups = [4, 4, 4]
    return "-".join(
        "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(n)) for n in groups
    )


def _agent_svc(db: AsyncSession) -> AgentService:
    """Mesma factory de `cameras/router.py::_agent_svc` — construída aqui também
    porque o onboarding de cliente Nível 1 (`POST /admin/onboard-client`) precisa
    do provisionamento de agent+túnel WireGuard, sem importar o router de câmeras."""
    return AgentService(
        AgentRepository(db),
        CameraRepository(db),
        ApiKeyService(ApiKeyRepository(db)),
        AgentTunnelRepository(db),
        WireGuardHubClient(),
    )


# ─── Tenants ──────────────────────────────────────────────────────────────────

@router.get("/tenants", summary="Listar todos os tenants")
async def list_tenants(
    claims: AdminUser,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    offset = (page - 1) * page_size
    total = await db.scalar(
        select(func.count(TenantModel.id)).where(TenantModel.deleted_at.is_(None))
    ) or 0
    rows = (await db.execute(
        select(TenantModel)
        .where(TenantModel.deleted_at.is_(None))
        .order_by(TenantModel.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )).scalars().all()

    items = []
    for t in rows:
        cam_count = await db.scalar(
            select(func.count(CameraModel.id)).where(CameraModel.tenant_id == t.id)
        ) or 0
        items.append({
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "cnpj": t.cnpj,
            "is_active": t.is_active,
            "cameras_count": cam_count,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/tenants", status_code=status.HTTP_201_CREATED, summary="Criar novo tenant")
async def create_tenant(body: dict, claims: AdminUser, db: DbSession) -> dict:
    name = body.get("name", "").strip()
    slug = body.get("slug", "").strip()
    gestor_email = body.get("gestor_email", "").strip()
    gestor_name = body.get("gestor_name", "Gestor").strip()
    gestor_password = body.get("gestor_password", "")
    cnpj = body.get("cnpj")

    if not name or not slug or not gestor_email or not gestor_password:
        raise HTTPException(status_code=400, detail="name, slug, gestor_email e gestor_password são obrigatórios")

    # Verificar slug único
    existing = await db.scalar(select(TenantModel).where(TenantModel.slug == slug))
    if existing:
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' já está em uso")

    from vms.infrastructure.security import hash_password
    tenant = TenantModel(name=name, slug=slug, cnpj=cnpj, is_active=True)
    db.add(tenant)
    await db.flush()  # popula tenant.id

    gestor = UserModel(
        tenant_id=tenant.id,
        email=gestor_email,
        full_name=gestor_name,
        hashed_password=hash_password(gestor_password),
        role="gestor",
        is_active=True,
    )
    db.add(gestor)

    db.add(AuditLogModel(
        tenant_id=tenant.id,
        user_id=claims.user_id,
        action="admin.tenant.created",
        resource_type="tenant",
        resource_id=tenant.id,
        payload={"name": name, "slug": slug, "gestor_email": gestor_email},
    ))

    await db.commit()
    await db.refresh(tenant)

    logger.info("Admin %s criou tenant %s (%s)", claims.user_id, tenant.id, slug)
    return {"id": tenant.id, "name": tenant.name, "slug": tenant.slug, "is_active": tenant.is_active}


@router.post(
    "/onboard-client",
    status_code=status.HTTP_201_CREATED,
    summary="Onboarding de cliente Nível 1 (licença + tenant + agent Docker + túnel WireGuard)",
)
async def onboard_client(body: dict, claims: AdminUser, db: DbSession) -> dict:
    """
    Cria, numa tacada só, tudo que um cliente Nível 1 (Docker dedicado)
    precisa pra começar: tenant, usuário gestor com senha padrão (troca
    obrigatória no primeiro login — ver `must_change_password`), licença já
    ativa (pula o fluxo manual de `POST /billing/activate`) e o agent com
    túnel WireGuard provisionado (reaproveita `AgentService.
    create_agent_with_tunnel`, mesmo código de `POST /agents`).

    Retorna tudo — inclusive os segredos de uma vez só (senha padrão, API
    key, chave privada WireGuard) — pro frontend montar o pacote de
    instalação (.zip) sem nenhuma chamada adicional ao servidor com esses
    segredos.
    """
    name = body.get("name", "").strip()
    slug = body.get("slug", "").strip().lower()
    cnpj = body.get("cnpj")
    gestor_email = body.get("gestor_email", "").strip().lower()
    gestor_name = body.get("gestor_name", "Gestor").strip()
    max_cameras = int(body.get("max_cameras") or 0)

    if not name or not slug or not gestor_email:
        raise HTTPException(status_code=400, detail="name, slug e gestor_email são obrigatórios")

    default_password = _generate_default_password()

    tenant = await TenantService(TenantRepository(db)).create_tenant(name, slug)
    if cnpj:
        tenant_model = await db.get(TenantModel, tenant.id)
        tenant_model.cnpj = cnpj

    gestor = await UserService(UserRepository(db), TenantRepository(db)).create_user(
        tenant_id=tenant.id,
        email=gestor_email,
        password=default_password,
        full_name=gestor_name,
        role=UserRole.GESTOR,
        must_change_password=True,
    )

    license_key_value = _generate_license_key()
    license_key = LicenseKeyModel(
        license_key=license_key_value,
        tenant_id=tenant.id,
        status="active",
        deployment_model="self_hosted",
        max_cameras=max_cameras,
        activated_at=datetime.now(UTC),
    )
    db.add(license_key)
    await db.flush()

    tenant_model = await db.get(TenantModel, tenant.id)
    tenant_model.license_key_id = license_key.id
    tenant_model.onboarding_complete = True

    # Provisiona agent + túnel WireGuard — mesmo código de POST /agents
    # (create_agent_with_tunnel já desfaz agent+api_key se o hub falhar).
    bundle = await _agent_svc(db).create_agent_with_tunnel(tenant.id, name=f"{slug}-docker")

    db.add(AuditLogModel(
        tenant_id=tenant.id,
        user_id=claims.user_id,
        action="admin.client.onboarded",
        resource_type="tenant",
        resource_id=tenant.id,
        payload={"name": name, "slug": slug, "gestor_email": gestor_email},
    ))

    # Commit explícito — o peer WG já foi registrado no hub como side-effect
    # externo antes deste ponto (ver create_agent_with_tunnel), fora da
    # transação SQL (mesmo padrão de POST /agents em cameras/router.py).
    await db.commit()

    logger.info(
        "Admin %s fez onboarding do cliente '%s' (tenant=%s, gestor=%s, agent=%s)",
        claims.user_id, slug, tenant.id, gestor.id, bundle.agent.id,
    )

    return {
        "tenant": {"id": tenant.id, "name": name, "slug": slug},
        "gestor_email": gestor_email,
        "gestor_default_password": default_password,
        "license_key": license_key_value,
        "agent": {
            "id": bundle.agent.id,
            "name": bundle.agent.name,
            "api_key": bundle.api_key,
            "wg_private_key": bundle.wg_private_key,
            "wg_public_key_hub": bundle.wg_public_key_hub,
            "wg_endpoint": bundle.wg_endpoint,
            "wg_tunnel_ip": bundle.wg_tunnel_ip,
            "wg_allowed_ips": bundle.wg_allowed_ips,
        },
    }


@router.get("/tenants/{tenant_id}", summary="Detalhe do tenant")
async def get_tenant(tenant_id: str, claims: AdminUser, db: DbSession) -> dict:
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    cam_count = await db.scalar(
        select(func.count(CameraModel.id)).where(CameraModel.tenant_id == tenant_id)
    ) or 0
    online_count = await db.scalar(
        select(func.count(CameraModel.id)).where(
            CameraModel.tenant_id == tenant_id, CameraModel.is_online.is_(True)
        )
    ) or 0

    audit_logs = (await db.execute(
        select(AuditLogModel)
        .where(AuditLogModel.tenant_id == tenant_id)
        .order_by(AuditLogModel.occurred_at.desc())
        .limit(10)
    )).scalars().all()

    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "cnpj": tenant.cnpj,
        "company_name": tenant.company_name,
        "is_active": tenant.is_active,
        "facial_recognition_enabled": tenant.facial_recognition_enabled,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "usage": {
            "cameras_total": cam_count,
            "cameras_online": online_count,
        },
        "recent_audit": [
            {
                "action": log.action,
                "user_id": log.user_id,
                "created_at": log.occurred_at.isoformat() if log.occurred_at else None,
            }
            for log in audit_logs
        ],
    }


@router.put("/tenants/{tenant_id}", summary="Editar dados do tenant")
async def update_tenant(tenant_id: str, body: dict, claims: AdminUser, db: DbSession) -> dict:
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    for field in ("name", "cnpj", "company_name", "company_address", "logo_url"):
        if field in body:
            setattr(tenant, field, body[field])

    db.add(AuditLogModel(
        tenant_id=tenant_id,
        user_id=claims.user_id,
        action="admin.tenant.updated",
        resource_type="tenant",
        resource_id=tenant_id,
        payload={"fields_changed": list(body.keys())},
    ))

    await db.commit()
    return {"id": tenant.id, "name": tenant.name}


@router.post("/tenants/{tenant_id}/suspend", summary="Suspender tenant")
async def suspend_tenant(tenant_id: str, claims: AdminUser, db: DbSession) -> dict:
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    if not tenant.is_active:
        raise HTTPException(status_code=409, detail="Tenant já está suspenso")

    tenant.is_active = False
    db.add(AuditLogModel(
        tenant_id=tenant_id,
        user_id=claims.user_id,
        action="admin.tenant.suspended",
        resource_type="tenant",
        resource_id=tenant_id,
        payload={},
    ))
    await db.commit()
    logger.info("Admin %s suspendeu tenant %s", claims.user_id, tenant_id)
    return {"id": tenant_id, "is_active": False}


@router.post("/tenants/{tenant_id}/reactivate", summary="Reativar tenant")
async def reactivate_tenant(tenant_id: str, claims: AdminUser, db: DbSession) -> dict:
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    if tenant.is_active:
        raise HTTPException(status_code=409, detail="Tenant já está ativo")

    tenant.is_active = True
    db.add(AuditLogModel(
        tenant_id=tenant_id,
        user_id=claims.user_id,
        action="admin.tenant.reactivated",
        resource_type="tenant",
        resource_id=tenant_id,
        payload={},
    ))
    await db.commit()
    return {"id": tenant_id, "is_active": True}


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft delete de tenant")
async def delete_tenant(tenant_id: str, claims: AdminUser, db: DbSession) -> None:
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    tenant.deleted_at = datetime.now(UTC)
    tenant.is_active = False
    db.add(AuditLogModel(
        tenant_id=tenant_id,
        user_id=claims.user_id,
        action="admin.tenant.deleted",
        resource_type="tenant",
        resource_id=tenant_id,
        payload={},
    ))
    await db.commit()
    logger.info("Admin %s deletou (soft) tenant %s", claims.user_id, tenant_id)


@router.post("/tenants/{tenant_id}/impersonate", summary="Impersonar gestor do tenant")
async def impersonate_tenant(tenant_id: str, claims: AdminUser, db: DbSession) -> dict:
    """Gera JWT 15min com claim impersonated_by para o Admin operar como Gestor do tenant."""
    tenant = await db.scalar(
        select(TenantModel).where(TenantModel.id == tenant_id, TenantModel.deleted_at.is_(None))
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    if not tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant suspenso — não é possível impersonar")

    # Buscar Gestor principal do tenant
    gestor = await db.scalar(
        select(UserModel).where(
            UserModel.tenant_id == tenant_id,
            UserModel.role == "gestor",
            UserModel.is_active.is_(True),
        )
    )
    if not gestor:
        raise HTTPException(status_code=404, detail="Nenhum gestor ativo encontrado neste tenant")

    token = create_access_token(
        subject=gestor.id,
        tenant_id=tenant_id,
        role="gestor",
        expire_minutes=15,
        extra_claims={"impersonated_by": claims.user_id},
    )

    db.add(AuditLogModel(
        tenant_id=tenant_id,
        user_id=claims.user_id,
        action="admin.tenant.impersonated",
        resource_type="tenant",
        resource_id=tenant_id,
        payload={"gestor_id": gestor.id, "gestor_email": gestor.email},
    ))
    await db.commit()

    logger.info("Admin %s impersonou gestor %s do tenant %s", claims.user_id, gestor.id, tenant_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 900,
        "tenant_name": tenant.name,
        "impersonated_user": {"id": gestor.id, "email": gestor.email},
    }
