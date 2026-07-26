"""Rotas HTTP do bounded context de notificações."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from vms.shared.api.dependencies import CurrentUser, DbSession
from vms.notifications.schemas import CreateRuleRequest, LogResponse, RuleResponse
from vms.notifications.service import NotificationService, build_notification_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _svc(db: DbSession) -> NotificationService:
    """Constrói NotificationService com sessão do banco injetada."""
    return build_notification_service(db)


# ─── Regras ───────────────────────────────────────────────────────────────────

@router.get(
    "/notifications/rules",
    response_model=list[RuleResponse],
    summary="Listar regras de notificação",
    tags=["notifications"],
)
async def list_rules(claims: CurrentUser, db: DbSession) -> list[RuleResponse]:
    """Lista todas as regras de notificação do tenant autenticado."""
    try:
        rules = await _svc(db).list_rules(claims.tenant_id)
        return [
            RuleResponse(
                id=r.id,
                name=r.name,
                event_type_pattern=r.event_type_pattern,
                destination_url=r.destination_url,
                is_active=r.is_active,
                created_at=r.created_at,
            )
            for r in rules
        ]
    except Exception as exc:
        logger.error("Erro ao listar regras de notificação: %s", exc)
        # Retorna lista vazia em vez de erro 503
        return []


@router.post(
    "/notifications/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar regra de notificação",
    tags=["notifications"],
)
async def create_rule(
    body: CreateRuleRequest,
    claims: CurrentUser,
    db: DbSession,
) -> RuleResponse:
    """Cria nova regra de notificação para o tenant autenticado."""
    rule = await _svc(db).create_rule(
        tenant_id=claims.tenant_id,
        name=body.name,
        pattern=body.event_type_pattern,
        dest_url=str(body.destination_url),
        secret=body.webhook_secret,
    )
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        event_type_pattern=rule.event_type_pattern,
        destination_url=rule.destination_url,
        is_active=rule.is_active,
        created_at=rule.created_at,
    )


@router.get(
    "/notifications/rules/{rule_id}",
    response_model=RuleResponse,
    summary="Buscar regra de notificação",
    tags=["notifications"],
)
async def get_rule(
    rule_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> RuleResponse:
    """Retorna regra de notificação pelo ID."""
    rule = await _svc(db).get_rule(rule_id, claims.tenant_id)
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        event_type_pattern=rule.event_type_pattern,
        destination_url=rule.destination_url,
        is_active=rule.is_active,
        created_at=rule.created_at,
    )


@router.delete(
    "/notifications/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover regra de notificação",
    tags=["notifications"],
)
async def delete_rule(
    rule_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Remove regra de notificação permanentemente."""
    await _svc(db).delete_rule(rule_id, claims.tenant_id)


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get(
    "/notifications/logs",
    response_model=list[LogResponse],
    summary="Listar logs de notificação",
    tags=["notifications"],
)
async def list_logs(
    claims: CurrentUser,
    db: DbSession,
    rule_id: str | None = Query(default=None, description="Filtrar por regra"),
    status_filter: str | None = Query(
        default=None, alias="status", description="Filtrar por status: success | failed"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LogResponse]:
    """Lista logs de dispatch de webhooks com filtros opcionais."""
    try:
        from vms.notifications.domain import NotificationStatus
        from vms.notifications.repository import NotificationLogRepository

        log_repo = NotificationLogRepository(db)
        parsed_status = NotificationStatus(status_filter) if status_filter else None
        logs = await log_repo.list_by_tenant(
            tenant_id=claims.tenant_id,
            rule_id=rule_id,
            status=parsed_status,
            limit=limit,
            offset=offset,
        )
        return [
            LogResponse(
                id=log.id,
                rule_id=log.rule_id,
                vms_event_id=log.vms_event_id,
                status=log.status.value,
                response_code=log.response_code,
                dispatched_at=log.dispatched_at,
            )
            for log in logs
        ]
    except Exception as exc:
        logger.error("Erro ao listar logs de notificação: %s", exc)
        # Retorna lista vazia em vez de erro 503
        return []
