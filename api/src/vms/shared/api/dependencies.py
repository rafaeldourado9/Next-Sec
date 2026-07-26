"""FastAPI dependencies: banco de dados, autenticação, tenant."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from vms.infrastructure.database.connection import get_session_factory
from vms.infrastructure.security import decode_token

_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


# ─── Sessão de banco ──────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency que fornece sessão async do banco."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


# ─── Claims do token ──────────────────────────────────────────────────────────

class TokenClaims:
    """Claims extraídos do JWT após validação."""

    def __init__(self, user_id: str, tenant_id: str, role: str) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role

    @property
    def is_admin(self) -> bool:
        """Retorna True se o usuário tem role admin."""
        return self.role == "admin"


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2)] = None,
) -> TokenClaims:
    """Valida JWT e retorna claims do usuário autenticado."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação obrigatório",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("Tipo de token inválido")
        return TokenClaims(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload["role"],
        )
    except (JWTError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentUser = Annotated[TokenClaims, Depends(get_current_user)]


# Hierarquia de roles: admin > gestor > operador/viewer
_ROLE_HIERARCHY: dict[str, int] = {
    "admin": 3,
    "gestor": 2,
    "operador": 1,
    "viewer": 1,
}


def require_role(*allowed_roles: str):
    """Factory que retorna Depends exigindo um dos roles (ou superior na hierarquia).

    Exemplo:
        require_role('gestor')  → gestor e admin têm acesso
        require_role('admin')   → somente admin
        require_role('operador') → qualquer autenticado
    """
    min_level = min(_ROLE_HIERARCHY.get(r, 0) for r in allowed_roles)

    def _check(claims: CurrentUser) -> TokenClaims:
        user_level = _ROLE_HIERARCHY.get(claims.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permissão insuficiente. Requer: {' ou '.join(allowed_roles)}",
            )
        return claims

    return Depends(_check)


def require_admin(claims: CurrentUser) -> TokenClaims:
    """Dependency que exige role admin."""
    if not claims.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissão de administrador necessária",
        )
    return claims


AdminUser = Annotated[TokenClaims, Depends(require_admin)]
GestorUser = Annotated[TokenClaims, require_role("gestor")]
OperadorUser = Annotated[TokenClaims, require_role("operador")]


# ─── API Key (agents, analytics) ─────────────────────────────────────────────

async def get_api_key(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Extrai API key do header Authorization: ApiKey vms_xxx."""
    if not authorization or not authorization.startswith("ApiKey "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'Authorization: ApiKey <key>' obrigatório",
        )
    return authorization.removeprefix("ApiKey ").strip()


ApiKeyHeader = Annotated[str, Depends(get_api_key)]
