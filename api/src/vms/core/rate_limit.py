"""
⚠️ DEPRECATED: vms.core.rate_limit foi movido para vms.shared.api.rate_limit

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.shared.api.rate_limit import limiter

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.shared.api.rate_limit import limiter  # noqa: F401

__all__ = ["limiter"]
