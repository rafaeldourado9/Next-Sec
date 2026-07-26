"""Application services do IAM — casos de uso de identidade e acesso."""

import uuid

from vms.shared.exceptions import AuthenticationError, ConflictError, NotFoundError, UnauthorizedError
from vms.infrastructure.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    extract_key_prefix,
    generate_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)
from vms.iam.domain import ApiKey, ApiKeyOwnerType, Tenant, User, UserRole
from vms.iam.repository import ApiKeyRepositoryPort, TenantRepositoryPort, UserRepositoryPort


class TenantService:
    """Casos de uso de gerenciamento de tenants."""

    def __init__(self, tenant_repo: TenantRepositoryPort) -> None:
        self._tenants = tenant_repo

    async def create_tenant(self, name: str, slug: str) -> Tenant:
        """
        Cria novo tenant.

        Lança DuplicateError se o slug já estiver em uso.
        """
        existing = await self._tenants.get_by_slug(slug)
        if existing:
            raise ConflictError(f"Slug '{slug}' já está em uso")

        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=name,
            slug=slug,
        )
        return await self._tenants.create(tenant)

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """Retorna tenant por ID. Lança NotFoundError se não existir."""
        tenant = await self._tenants.get_by_id(tenant_id)
        if not tenant:
            raise NotFoundError("Tenant", tenant_id)
        return tenant


class UserService:
    """Casos de uso de gerenciamento de usuários."""

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        tenant_repo: TenantRepositoryPort,
    ) -> None:
        self._users = user_repo
        self._tenants = tenant_repo

    async def create_user(
        self,
        tenant_id: str,
        email: str,
        password: str,
        full_name: str,
        role: UserRole = UserRole.VIEWER,
    ) -> User:
        """
        Cria usuário no tenant.

        Lança NotFoundError se o tenant não existir.
        Lança DuplicateError se o email já estiver em uso no tenant.
        """
        tenant = await self._tenants.get_by_id(tenant_id)
        if not tenant:
            raise NotFoundError("Tenant", tenant_id)

        existing = await self._users.get_by_email(email, tenant_id)
        if existing:
            raise ConflictError(f"Email '{email}' já cadastrado neste tenant")

        user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
        )
        return await self._users.create(user)

    async def get_user(self, user_id: str, tenant_id: str) -> User:
        """Retorna usuário por ID dentro do tenant."""
        user = await self._users.get_by_id(user_id, tenant_id)
        if not user:
            raise NotFoundError("Usuário", user_id)
        return user

    async def update_user(
        self,
        user_id: str,
        tenant_id: str,
        role: UserRole | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> User:
        """Atualiza role, status ou senha do usuário."""
        fields: dict[str, object] = {}
        if role is not None:
            fields["role"] = role.value
        if is_active is not None:
            fields["is_active"] = is_active
        if password is not None:
            fields["hashed_password"] = hash_password(password)
        if not fields:
            return await self.get_user(user_id, tenant_id)
        user = await self._users.patch(user_id, tenant_id, **fields)
        if not user:
            raise NotFoundError("Usuário", user_id)
        return user


class AuthService:
    """Casos de uso de autenticação."""

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        api_key_repo: ApiKeyRepositoryPort,
    ) -> None:
        self._users = user_repo
        self._api_keys = api_key_repo

    async def authenticate_user(
        self,
        email: str,
        password: str,
        tenant_id: str,
    ) -> tuple[str, str]:
        """
        Autentica usuário e retorna (access_token, refresh_token).

        Lança UnauthorizedError se credenciais inválidas.
        """
        user = await self._users.get_by_email(email, tenant_id)
        if not user or not user.is_active:
            raise AuthenticationError("Credenciais inválidas")

        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Credenciais inválidas")

        access = create_access_token(user.id, user.tenant_id, user.role.value)
        refresh = create_refresh_token(user.id, user.tenant_id)
        return access, refresh

    async def refresh_access_token(self, refresh_token: str) -> tuple[str, str]:
        """
        Renova tokens a partir de um refresh token válido.

        Lança UnauthorizedError se o refresh token for inválido.
        """
        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                raise AuthenticationError("Token de refresh inválido")

            user = await self._users.get_by_id(payload["sub"], payload["tenant_id"])
            if not user or not user.is_active:
                raise AuthenticationError("Usuário inativo")

            access = create_access_token(user.id, user.tenant_id, user.role.value)
            new_refresh = create_refresh_token(user.id, user.tenant_id)
            return access, new_refresh

        except KeyError as exc:
            raise AuthenticationError("Claims do token ausentes") from exc
        except Exception as exc:
            raise AuthenticationError("Token de refresh inválido") from exc

    async def issue_viewer_token(self, tenant_id: str, camera_id: str) -> str:
        """Emite token JWT de curta duração para um viewer de stream."""
        from vms.infrastructure.security import create_viewer_token
        return create_viewer_token(tenant_id, camera_id)

    async def authenticate_api_key(self, plain_key: str) -> ApiKey:
        """
        Autentica API key e retorna entidade.

        Lança UnauthorizedError se a key for inválida ou revogada.
        """
        prefix = extract_key_prefix(plain_key)
        api_key = await self._api_keys.get_by_prefix(prefix)

        if not api_key or not api_key.is_active:
            raise UnauthorizedError("API key inválida")

        if not verify_api_key(plain_key, api_key.key_hash):
            raise UnauthorizedError("API key inválida")

        # Atualiza last_used de forma assíncrona (best-effort)
        await self._api_keys.update_last_used(api_key.id)
        return api_key


class ApiKeyService:
    """Casos de uso de gerenciamento de API keys."""

    def __init__(self, api_key_repo: ApiKeyRepositoryPort) -> None:
        self._api_keys = api_key_repo

    async def issue_api_key(
        self,
        tenant_id: str,
        owner_type: ApiKeyOwnerType,
        owner_id: str,
    ) -> tuple[ApiKey, str]:
        """
        Emite nova API key.

        Retorna (api_key_entity, plain_key).
        O plain_key deve ser exibido ao usuário uma única vez.
        """
        plain_key, key_hash, prefix = generate_api_key()

        api_key = ApiKey(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            key_hash=key_hash,
            prefix=prefix,
        )
        saved = await self._api_keys.create(api_key)
        return saved, plain_key

    async def revoke_api_key(self, api_key_id: str, tenant_id: str) -> None:
        """Revoga API key. Lança NotFoundError se não encontrada no tenant."""
        revoked = await self._api_keys.revoke(api_key_id, tenant_id)
        if not revoked:
            raise NotFoundError("ApiKey", api_key_id)
