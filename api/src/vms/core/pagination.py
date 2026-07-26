"""
⚠️ DEPRECATED: vms.core.pagination foi movido para vms.shared.api.pagination

Este módulo existe apenas para compatibilidade durante a migração.
NOTA: pagination.py não é usado por ninguém no projeto — considere remoção.

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.shared.api.pagination import Page, PaginationParams  # noqa: F401

__all__ = ["PaginationParams", "Page"]
