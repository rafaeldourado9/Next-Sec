"""
⚠️ DEPRECATED: vms.core.config foi movido para vms.infrastructure.config.settings

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.config import get_settings, Settings

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.config.settings import Settings, get_settings  # noqa: F401

__all__ = ["Settings", "get_settings"]
