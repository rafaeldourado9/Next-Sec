"""
⚠️ DEPRECATED: vms.core.dlq foi movido para vms.infrastructure.messaging.dlq

Este módulo existe apenas para compatibilidade durante a migração.
Todos os imports devem ser atualizados para:
    from vms.infrastructure.messaging.dlq import record_failure

Este arquivo será removido na Sprint A3.
"""
# Compatibilidade — redireciona para novo local
from vms.infrastructure.messaging.dlq import record_failure  # noqa: F401

__all__ = ["record_failure"]
