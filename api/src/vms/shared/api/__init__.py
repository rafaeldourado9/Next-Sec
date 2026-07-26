"""
Shared API — Dependências, rate limiting e paginação para endpoints FastAPI.

Este módulo contém:
- dependencies.py: Type aliases para Depends (DbSession, CurrentUser, etc.)
- rate_limit.py: Singleton do limiter (slowapi)
- pagination.py: Modelos de paginação (Page, PaginationParams)

REGRA: Este módulo é compartilhado entre bounded contexts para uso em routers.
       Não contém lógica de domínio — apenas utilitários de API.
"""
from vms.shared.api.dependencies import (
    ApiKeyHeader,
    AdminUser,
    CurrentUser,
    DbSession,
    TokenClaims,
    get_api_key,
    get_current_user,
    get_db,
    require_admin,
)
from vms.shared.api.rate_limit import limiter
from vms.shared.api.pagination import PaginationParams, Page

__all__ = [
    # Dependencies
    "ApiKeyHeader",
    "AdminUser",
    "CurrentUser",
    "DbSession",
    "TokenClaims",
    "get_api_key",
    "get_current_user",
    "get_db",
    "require_admin",
    # Rate limit
    "limiter",
    # Pagination
    "PaginationParams",
    "Page",
]
