"""Serviço central de auditoria."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from vms.audit.domain import AuditLog, AuditLogCreated
from vms.audit.repository import AuditRepositoryPort
from vms.shared.kernel import AuditId, EntityId, TenantId

logger = logging.getLogger(__name__)


class AuditService:
    """
    Serviço central de auditoria.

    Responsabilidades:
    1. Persistir AuditLog no banco
    2. Publicar domain event AuditLogCreated
    3. Sanitizar payload (não logar senhas, tokens, etc.)
    """

    SENSITIVE_FIELDS = {"password", "token", "secret", "api_key", "authorization", "cookie"}

    def __init__(self, repo: AuditRepositoryPort) -> None:
        self._repo = repo

    async def log(
        self,
        tenant_id: TenantId | str,
        action: str,
        user_id: EntityId | str | None = None,
        user_email: str | None = None,
        user_role: str | None = None,
        resource_type: str | None = None,
        resource_id: EntityId | str | None = None,
        resource_name: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: UUID | None = None,
        payload: dict | None = None,
        result: str = "success",
        occurred_at: datetime | None = None,
    ) -> AuditLog:
        """
        Registra uma entrada de auditoria.

        Args:
            tenant_id: ID do tenant
            action: Ação semântica (ex: "camera.created", "user.deleted")
            user_id: ID do usuário que realizou a ação (None para webhooks/sistema)
            user_email: Email do usuário (denormalizado para imutabilidade)
            user_role: Role do usuário no momento da ação
            resource_type: Tipo do recurso (ex: "camera", "user", "recording")
            resource_id: ID do recurso afetado
            resource_name: Nome legível do recurso
            ip_address: IP real do cliente
            user_agent: User-Agent do cliente
            request_id: Correlation ID do request
            payload: Dados adicionais da ação (sanitizado)
            result: "success", "error", ou "denied"
            occurred_at: Timestamp da ação (default: agora)

        Returns:
            AuditLog criado
        """
        # Sanitizar payload
        safe_payload = self._sanitize(payload) if payload else {}

        # Converter tipos
        tenant_id_str = tenant_id.value if hasattr(tenant_id, 'value') else tenant_id
        user_id_str = user_id.value if hasattr(user_id, 'value') else user_id
        resource_id_str = resource_id.value if hasattr(resource_id, 'value') else resource_id

        audit_log = AuditLog(
            tenant_id=TenantId(tenant_id_str) if isinstance(tenant_id_str, str) and tenant_id_str else tenant_id,
            user_id=EntityId(user_id_str) if user_id_str else None,
            user_email=user_email,
            user_role=user_role,
            action=action,
            resource_type=resource_type,
            resource_id=EntityId(resource_id_str) if resource_id_str else None,
            resource_name=resource_name,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            payload=safe_payload,
            result=result,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )

        # Persistir
        saved = await self._repo.create(audit_log)

        # Publicar domain event
        saved.record_event(AuditLogCreated(
            audit_id=saved.id,
            tenant_id=saved.tenant_id,
            action=saved.action,
            resource_type=saved.resource_type or "",
        ))

        logger.debug(
            "Audit log: %s %s:%s by %s result=%s",
            action,
            resource_type or "unknown",
            resource_id_str or "unknown",
            user_email or "system",
            result,
        )

        return saved

    @classmethod
    def _sanitize(cls, payload: dict) -> dict:
        """Remove campos sensíveis do payload.

        Não loga senhas, tokens, secrets, etc.
        """
        if not payload:
            return {}

        safe = {}
        for key, value in payload.items():
            if key.lower() in cls.SENSITIVE_FIELDS:
                safe[key] = "[REDACTED]"
            elif isinstance(value, dict):
                safe[key] = cls._sanitize(value)
            else:
                safe[key] = value
        return safe
