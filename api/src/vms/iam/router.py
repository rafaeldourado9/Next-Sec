"""Rotas HTTP do IAM — autenticação, tenants, usuários."""

from fastapi import APIRouter, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from vms.infrastructure.config import get_settings
from vms.shared.api.dependencies import AdminUser, CurrentUser, DbSession, GestorUser
from vms.infrastructure.middleware.audit_action import audit_action
from vms.shared.api.rate_limit import limiter
from vms.iam.repository import ApiKeyRepository, TenantRepository, UserRepository
from vms.iam.schemas import (
    CreateTenantRequest,
    CreateUserRequest,
    LoginRequest,
    RefreshRequest,
    TenantBrandingRequest,
    TenantBrandingResponse,
    TenantResponse,
    TokenResponse,
    UpdateUserRequest,
    UserResponse,
)
from vms.iam.service import ApiKeyService, AuthService, TenantService, UserService

router = APIRouter()


def _make_auth_service(db: AsyncSession) -> AuthService:
    return AuthService(UserRepository(db), ApiKeyRepository(db))


def _make_user_service(db: AsyncSession) -> UserService:
    return UserService(UserRepository(db), TenantRepository(db))


# ─── Auth ─────────────────────────────────────────────────────────────────────

@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="Obter tokens JWT",
    tags=["auth"],
)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: DbSession) -> TokenResponse:
    """
    Autentica usuário e retorna access + refresh tokens.

    Rate limit: 5/min por IP (configurado no middleware).
    """
    settings = get_settings()

    # Em instalações single-tenant, o tenant vem do slug no subdomínio.
    # Para simplificar no MVP, usamos o tenant do usuário encontrado por email.
    # TODO: suporte a multi-tenant por subdomínio no header X-Tenant
    user_repo = UserRepository(db)

    # Busca em todos os tenants pelo email (fallback para MVP single-instance)
    from sqlalchemy import select
    from vms.iam.models import UserModel
    stmt = select(UserModel).where(
        UserModel.email == body.email.lower(),
        UserModel.is_active.is_(True),
    )
    user_model = await db.scalar(stmt)
    if not user_model:
        from vms.infrastructure.exceptions import AuthenticationError
        raise AuthenticationError()

    svc = _make_auth_service(db)
    access, refresh = await svc.authenticate_user(
        body.email, body.password, user_model.tenant_id
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Renovar tokens JWT",
    tags=["auth"],
)
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshRequest, db: DbSession) -> TokenResponse:
    """Renova access + refresh tokens a partir de um refresh token válido."""
    settings = get_settings()
    svc = _make_auth_service(db)
    access, refresh = await svc.refresh_access_token(body.refresh_token)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


# ─── Tenants ─────────────────────────────────────────────────────────────────

@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar tenant",
    tags=["tenants"],
)
async def create_tenant(
    body: CreateTenantRequest,
    db: DbSession,
    _claims: AdminUser,
) -> TenantResponse:
    """Cria novo tenant. Requer role admin."""
    svc = TenantService(TenantRepository(db))
    tenant = await svc.create_tenant(body.name, body.slug)
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )


# ─── Usuários ─────────────────────────────────────────────────────────────────

@router.get(
    "/iam/branding",
    response_model=TenantBrandingResponse,
    summary="Dados de branding do tenant",
    tags=["tenants"],
)
async def get_branding(claims: CurrentUser, db: DbSession) -> TenantBrandingResponse:
    """Retorna dados de identidade visual do tenant (usados nos PDFs)."""
    from sqlalchemy import select
    from vms.iam.models import TenantModel
    tenant = await db.scalar(select(TenantModel).where(TenantModel.id == claims.tenant_id))
    if not tenant:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return TenantBrandingResponse(
        company_name=tenant.company_name,
        cnpj=tenant.cnpj,
        company_address=tenant.company_address,
        logo_url=tenant.logo_url,
    )


@router.patch(
    "/iam/branding",
    response_model=TenantBrandingResponse,
    summary="Atualizar dados de branding do tenant",
    tags=["tenants"],
)
async def update_branding(
    body: TenantBrandingRequest,
    claims: CurrentUser,
    db: DbSession,
) -> TenantBrandingResponse:
    """Atualiza dados de identidade visual para PDFs de relatório."""
    from sqlalchemy import select
    from vms.iam.models import TenantModel
    tenant = await db.scalar(select(TenantModel).where(TenantModel.id == claims.tenant_id))
    if not tenant:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tenant não encontrado")

    if body.company_name is not None:
        tenant.company_name = body.company_name
    if body.cnpj is not None:
        tenant.cnpj = body.cnpj
    if body.company_address is not None:
        tenant.company_address = body.company_address
    if body.logo_url is not None:
        tenant.logo_url = body.logo_url

    await db.commit()
    await db.refresh(tenant)
    return TenantBrandingResponse(
        company_name=tenant.company_name,
        cnpj=tenant.cnpj,
        company_address=tenant.company_address,
        logo_url=tenant.logo_url,
    )


@router.get(
    "/users",
    response_model=list[UserResponse],
    summary="Listar usuários do tenant",
    tags=["users"],
)
async def list_users(
    claims: CurrentUser,
    db: DbSession,
    email_filter: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> list[UserResponse]:
    """Lista usuários do tenant do usuário autenticado. Admins veem todos."""
    from vms.iam.domain import UserRole
    from vms.iam.models import UserModel
    from vms.iam.service import UserService
    from sqlalchemy import select
    
    svc = UserService(UserRepository(db), TenantRepository(db))
    
    # Monta query com filtros opcionais
    stmt = select(UserModel).where(UserModel.tenant_id == claims.tenant_id)
    
    if email_filter:
        stmt = stmt.where(UserModel.email.ilike(f"%{email_filter}%"))
    if role:
        stmt = stmt.where(UserModel.role == UserRole(role))
    if is_active is not None:
        stmt = stmt.where(UserModel.is_active.is_(is_active))
    
    # Admin pode ver todos os tenants, outros veem só o seu
    # claims.role é string (não enum)
    if claims.role != "admin":
        stmt = stmt.where(UserModel.tenant_id == claims.tenant_id)
    
    stmt = stmt.order_by(UserModel.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    return [
        UserResponse(
            id=u.id,
            tenant_id=u.tenant_id,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.get(
    "/users/me",
    response_model=UserResponse,
    summary="Perfil do usuário atual",
    tags=["users"],
)
async def get_me(claims: CurrentUser, db: DbSession) -> UserResponse:
    """Retorna dados do usuário autenticado."""
    svc = _make_user_service(db)
    user = await svc.get_user(claims.user_id, claims.tenant_id)
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar usuário",
    tags=["users"],
)
@audit_action("user.created", resource_type="user", name_param="body.email")
async def create_user(
    body: CreateUserRequest,
    claims: GestorUser,
    db: DbSession,
) -> UserResponse:
    """Cria usuário no tenant do admin autenticado."""
    from vms.iam.domain import UserRole
    svc = _make_user_service(db)
    user = await svc.create_user(
        tenant_id=claims.tenant_id,
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        role=UserRole(body.role),
    )
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Atualizar usuário",
    tags=["users"],
)
@audit_action("user.updated", resource_type="user", id_param="user_id")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    claims: GestorUser,
    db: DbSession,
) -> UserResponse:
    """Atualiza role, status ativo ou senha de um usuário. Admin only."""
    from vms.iam.domain import UserRole
    svc = _make_user_service(db)
    user = await svc.update_user(
        user_id=user_id,
        tenant_id=claims.tenant_id,
        role=UserRole(body.role) if body.role else None,
        is_active=body.is_active,
        password=body.password,
    )
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )
