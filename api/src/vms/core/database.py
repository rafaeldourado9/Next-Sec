"""
⚠️ DEPRECATED: vms.core.database foi movido para vms.infrastructure.database.connection

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.database import Base, create_engine, get_session_factory, ...

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.database.connection import (  # noqa: F401
    Base,
    close_db,
    create_engine,
    get_db_context,
    get_session_factory,
    init_db,
)

__all__ = [
    "Base",
    "close_db",
    "create_engine",
    "get_db_context",
    "get_session_factory",
    "init_db",
]
