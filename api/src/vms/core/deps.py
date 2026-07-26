"""
⚠️ DEPRECATED: vms.core.deps foi movido para vms.shared.api.dependencies

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.shared.api.dependencies import DbSession, CurrentUser, ...

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.shared.api.dependencies import (  # noqa: F401
    AdminUser,
    ApiKeyHeader,
    CurrentUser,
    DbSession,
    TokenClaims,
    get_api_key,
    get_current_user,
    get_db,
    require_admin,
)

__all__ = [
    "TokenClaims",
    "get_db",
    "get_current_user",
    "require_admin",
    "get_api_key",
    "DbSession",
    "CurrentUser",
    "AdminUser",
    "ApiKeyHeader",
]
