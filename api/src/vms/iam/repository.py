"""Ports (interfaces) e implementações SQLAlchemy para o IAM."""

import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vms.iam.domain import ApiKey, ApiKeyOwnerType, Tenant, User, UserRole
from vms.iam.models import ApiKeyModel, TenantModel, UserModel


# ─── Ports (interfaces) ───────────────────────────────────────────────────────

class TenantRepositoryPort(Protocol):
    """Interface do repositório de tenants."""

    async def get_by_id(self, tenant_id: str) -> Tenant | None: ...
    async def get_by_slug(self, slug: str) -> Tenant | None: ...
    async def create(self, tenant: Tenant) -> Tenant: ...
    async def list_all(self) -> list[Tenant]: ...


class UserRepositoryPort(Protocol):
    """Interface do repositório de usuários."""

    async def get_by_id(self, user_id: str, tenant_id: str) -> User | None: ...
    async def get_by_email(self, email: str, tenant_id: str) -> User | None: ...
    async def create(self, user: User) -> User: ...
    async def patch(self, user_id: str, tenant_id: str, **fields: object) -> User | None: ...
    async def list_by_tenant(self, tenant_id: str) -> list[User]: ...


class ApiKeyRepositoryPort(Protocol):
    """Interface do repositório de API keys."""

    async def get_by_prefix(self, prefix: str) -> ApiKey | None: ...
    async def create(self, api_key: ApiKey) -> ApiKey: ...
    async def revoke(self, api_key_id: str, tenant_id: str) -> bool: ...
    async def update_last_used(self, api_key_id: str) -> None: ...


# ─── Conversores ORM ↔ Domain ─────────────────────────────────────────────────

def _tenant_to_domain(m: TenantModel) -> Tenant:
    return Tenant(
        id=m.id,
        name=m.name,
        slug=m.slug,
        is_active=m.is_active,
        facial_recognition_enabled=m.facial_recognition_enabled,
        facial_recognition_consent_at=m.facial_recognition_consent_at,
        created_at=m.created_at,
    )


def _user_to_domain(m: UserModel) -> User:
    return User(
        id=m.id,
        tenant_id=m.tenant_id,
        email=m.email,
        hashed_password=m.hashed_password,
        full_name=m.full_name,
        role=UserRole(m.role),
        is_active=m.is_active,
        created_at=m.created_at,
    )


def _api_key_to_domain(m: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=m.id,
        tenant_id=m.tenant_id,
        owner_type=ApiKeyOwnerType(m.owner_type),
        owner_id=m.owner_id,
        key_hash=m.key_hash,
        prefix=m.prefix,
        is_active=m.is_active,
        last_used_at=m.last_used_at,
        created_at=m.created_at,
    )


# ─── Implementações SQLAlchemy ────────────────────────────────────────────────

class TenantRepository:
    """Repositório SQLAlchemy para Tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: str) -> Tenant | None:
        """Busca tenant por ID."""
        result = await self._session.get(TenantModel, tenant_id)
        return _tenant_to_domain(result) if result else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Busca tenant por slug único."""
        stmt = select(TenantModel).where(TenantModel.slug == slug)
        result = await self._session.scalar(stmt)
        return _tenant_to_domain(result) if result else None

    async def create(self, tenant: Tenant) -> Tenant:
        """Persiste novo tenant."""
        model = TenantModel(
            id=tenant.id or str(uuid.uuid4()),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _tenant_to_domain(model)

    async def list_all(self) -> list[Tenant]:
        """Lista todos os tenants ativos."""
        stmt = select(TenantModel).where(TenantModel.is_active.is_(True))
        result = await self._session.scalars(stmt)
        return [_tenant_to_domain(m) for m in result.all()]


class UserRepository:
    """Repositório SQLAlchemy para User."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: str, tenant_id: str) -> User | None:
        """Busca usuário por ID — sempre filtrado por tenant."""
        stmt = select(UserModel).where(
            UserModel.id == user_id,
            UserModel.tenant_id == tenant_id,
        )
        result = await self._session.scalar(stmt)
        return _user_to_domain(result) if result else None

    async def get_by_email(self, email: str, tenant_id: str) -> User | None:
        """Busca usuário por email dentro do tenant."""
        stmt = select(UserModel).where(
            UserModel.email == email.lower(),
            UserModel.tenant_id == tenant_id,
        )
        result = await self._session.scalar(stmt)
        return _user_to_domain(result) if result else None

    async def create(self, user: User) -> User:
        """Persiste novo usuário."""
        model = UserModel(
            id=user.id or str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            email=user.email.lower(),
            hashed_password=user.hashed_password,
            full_name=user.full_name,
            role=user.role.value,
            is_active=user.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _user_to_domain(model)

    async def patch(self, user_id: str, tenant_id: str, **fields: object) -> User | None:
        """Atualiza campos arbitrários do usuário. Retorna None se não encontrado."""
        stmt = select(UserModel).where(
            UserModel.id == user_id,
            UserModel.tenant_id == tenant_id,
        )
        model = await self._session.scalar(stmt)
        if not model:
            return None
        for key, val in fields.items():
            setattr(model, key, val)
        await self._session.flush()
        await self._session.refresh(model)
        return _user_to_domain(model)

    async def list_by_tenant(self, tenant_id: str) -> list[User]:
        """Lista todos os usuários ativos de um tenant."""
        stmt = select(UserModel).where(
            UserModel.tenant_id == tenant_id,
            UserModel.is_active.is_(True),
        )
        result = await self._session.scalars(stmt)
        return [_user_to_domain(m) for m in result.all()]


class ApiKeyRepository:
    """Repositório SQLAlchemy para ApiKey."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_prefix(self, prefix: str) -> ApiKey | None:
        """Busca API key pelo prefixo (para lookup antes da verificação do hash)."""
        stmt = select(ApiKeyModel).where(
            ApiKeyModel.prefix == prefix,
            ApiKeyModel.is_active.is_(True),
        )
        result = await self._session.scalar(stmt)
        return _api_key_to_domain(result) if result else None

    async def create(self, api_key: ApiKey) -> ApiKey:
        """Persiste nova API key."""
        model = ApiKeyModel(
            id=api_key.id or str(uuid.uuid4()),
            tenant_id=api_key.tenant_id,
            owner_type=api_key.owner_type.value,
            owner_id=api_key.owner_id,
            key_hash=api_key.key_hash,
            prefix=api_key.prefix,
            is_active=True,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _api_key_to_domain(model)

    async def revoke(self, api_key_id: str, tenant_id: str) -> bool:
        """Revoga API key. Retorna False se não encontrada."""
        stmt = (
            update(ApiKeyModel)
            .where(ApiKeyModel.id == api_key_id, ApiKeyModel.tenant_id == tenant_id)
            .values(is_active=False)
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def update_last_used(self, api_key_id: str) -> None:
        """Atualiza timestamp de último uso (fire-and-forget)."""
        stmt = (
            update(ApiKeyModel)
            .where(ApiKeyModel.id == api_key_id)
            .values(last_used_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)
