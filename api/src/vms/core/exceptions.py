"""
⚠️ DEPRECATED: vms.core.exceptions foi movido para vms.infrastructure.exceptions

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.exceptions import NotFoundError, ValidationError, ...

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.exceptions import (  # noqa: F401
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
    VmsError,
    register_exception_handlers,
)

__all__ = [
    "VmsError",
    "NotFoundError",
    "ConflictError",
    "ForbiddenError",
    "ValidationError",
    "AuthenticationError",
    "ServiceUnavailableError",
    "register_exception_handlers",
]
