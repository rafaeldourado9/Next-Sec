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
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from vms.iam.models import TenantModel, UserModel
from vms.audit.models import AuditLogModel
from vms.cameras.models import CameraModel
from vms.shared.api.dependencies import AdminUser, DbSession
from vms.infrastructure.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


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
