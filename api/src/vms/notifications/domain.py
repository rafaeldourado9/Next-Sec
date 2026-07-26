"""Entidades de domínio de notificações e dispatch de webhooks."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from fnmatch import fnmatch


class NotificationStatus(StrEnum):
    """Status possíveis de uma tentativa de dispatch."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class NotificationRule:
    """Regra que determina quando e para onde enviar webhook."""

    id: str
    tenant_id: str
    name: str
    event_type_pattern: str  # fnmatch: "alpr.*", "camera.*", "*"
    destination_url: str
    webhook_secret: str  # HMAC-SHA256 signing key
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    def matches(self, event_type: str) -> bool:
        """Verifica se o tipo de evento bate com o padrão desta regra."""
        return fnmatch(event_type, self.event_type_pattern)


@dataclass
class NotificationLog:
    """Log de tentativa de dispatch de webhook."""

    id: str
    tenant_id: str
    rule_id: str
    vms_event_id: str
    status: NotificationStatus
    response_code: int | None = None
    response_body: str | None = None
    attempt: int = 1
    dispatched_at: datetime = field(default_factory=datetime.utcnow)
