"""
⚠️ DEPRECATED: vms.core.logging_config foi movido para vms.infrastructure.logging.config

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.logging import setup_logging

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.logging.config import setup_logging  # noqa: F401

__all__ = ["setup_logging"]
