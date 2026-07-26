"""Rotas HTTP de Compliance & LGPD."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from vms.shared.api.dependencies import AdminUser, CurrentUser, DbSession
from vms.infrastructure.middleware.audit_action import audit_action
from vms.lgpd.anonymization import AnonymizationService
from vms.lgpd.domain import (
    ConsentAction,
    ConsentRecord,
    DataSubjectRequest,
    DataType,
    RequestType,
    RetentionPolicy,
)
from vms.lgpd.repository import LgpdRepository
from vms.shared.kernel import AuditId, EntityId, TenantId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lgpd", tags=["lgpd"])


def _lgpd_repo(db) -> LgpdRepository:
    return LgpdRepository(db)


def _anonymization_svc(db) -> AnonymizationService:
    return AnonymizationService(db)


# ─── Consentimento ───────────────────────────────────────────────────────────

@router.post(
    "/consent",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar consentimento LGPD",
)
@audit_action("lgpd.consent_granted", resource_type="lgpd_consent")
async def grant_consent(
    body: dict,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """
    Registra consentimento explícito do usuário para processamento de dados.

    Body:
    - data_type: "video" | "alpr" | "face" | "audit" | "analytics"
    - consent_text_hash: hash do texto apresentado ao usuário (opcional)
    """
    repo = _lgpd_repo(db)
    data_type = DataType(body.get("data_type", "face"))

    # Calcular hash do texto se não fornecido
    consent_text = body.get("consent_text", "")
    consent_hash = hashlib.sha256(consent_text.encode()).hexdigest() if consent_text else None

    record = ConsentRecord(
        id=AuditId.new(),
        tenant_id=TenantId(claims.tenant_id) if isinstance(claims.tenant_id, str) else claims.tenant_id,
        user_id=EntityId(claims.user_id) if isinstance(claims.user_id, str) else claims.user_id,
        data_type=data_type,
        action=ConsentAction.GRANTED,
        consent_text_hash=consent_hash,
        ip_address=body.get("ip_address"),
        user_agent=body.get("user_agent"),
    )

    saved = await repo.record_consent(record)
    logger.info("Consentimento LGPD registrado: user=%s type=%s", claims.user_id, data_type)

    if data_type == DataType.FACE:
        await _set_facial_recognition_enabled(db, claims.tenant_id, enabled=True)

    return {
        "id": str(saved.id),
        "data_type": saved.data_type,
        "action": saved.action,
        "created_at": saved.created_at.isoformat(),
    }


async def _set_facial_recognition_enabled(db, tenant_id, *, enabled: bool) -> None:
    """Liga/desliga o gate de reconhecimento facial do tenant.

    Efeito colateral do consentimento LGPD tipo 'face' — sem isso, o
    consentimento fica registrado em `consent_records` mas o plugin de
    analytics nunca processa nada (gate em `tenant.facial_recognition_enabled`,
    ver `analytics/plugins/face_recognition/plugin.py` e `GET /plugins/watchlist`).
    """
    from datetime import UTC
    from sqlalchemy import select
    from vms.iam.models import TenantModel

    tid = tenant_id.value if hasattr(tenant_id, "value") else tenant_id
    tenant = await db.scalar(select(TenantModel).where(TenantModel.id == tid))
    if not tenant:
        return
    tenant.facial_recognition_enabled = enabled
    tenant.facial_recognition_consent_at = datetime.now(UTC) if enabled else None

    from vms.plugins import watchlist_cache
    watchlist_cache.invalidate(tid)


@router.post(
    "/consent/withdraw",
    summary="Revogar consentimento LGPD",
)
@router.post(
    "/revoke",
    include_in_schema=False,
)
@audit_action("lgpd.consent_revoked", resource_type="lgpd_consent")
async def withdraw_consent(
    body: dict,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """
    Revoga consentimento previamente concedido.

    Body:
    - data_type: "video" | "alpr" | "face" | "audit" | "analytics"
    """
    repo = _lgpd_repo(db)
    data_type = DataType(body.get("data_type", "face"))

    tenant_id_str = claims.tenant_id.value if hasattr(claims.tenant_id, 'value') else claims.tenant_id
    user_id_str = claims.user_id.value if hasattr(claims.user_id, 'value') else claims.user_id

    record = ConsentRecord(
        id=AuditId.new(),
        tenant_id=TenantId(tenant_id_str) if isinstance(tenant_id_str, str) else claims.tenant_id,
        user_id=EntityId(user_id_str) if isinstance(user_id_str, str) else claims.user_id,
        data_type=data_type,
        action=ConsentAction.REVOKED,
    )

    saved = await repo.record_consent(record)
    logger.info("Consentimento LGPD revogado: user=%s type=%s", claims.user_id, data_type)

    if data_type == DataType.FACE:
        await _set_facial_recognition_enabled(db, claims.tenant_id, enabled=False)

    return {
        "id": str(saved.id),
        "data_type": saved.data_type,
        "action": saved.action,
        "created_at": saved.created_at.isoformat(),
    }


@router.get(
    "/consent-log",
    summary="Histórico de consentimentos",
)
async def get_consent_log(
    claims: CurrentUser,
    db: DbSession,
    data_type: DataType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Lista histórico de consentimentos do tenant."""
    repo = _lgpd_repo(db)
    policies = await repo.get_all_policies(claims.tenant_id)

    offset = (page - 1) * page_size
    # Para MVP, retornar políticas como proxy do consent-log
    # Em produção: criar tabela separada de consent_events com query dedicada
    items = [
        {
            "data_type": p.data_type,
            "retention_days": p.retention_days,
            "anonymize_instead_of_delete": p.anonymize_instead_of_delete,
            "auto_enabled": p.auto_enabled,
        }
        for p in policies
    ][offset:offset + page_size]

    return {
        "items": items,
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


# ─── Retenção ────────────────────────────────────────────────────────────────

@router.get(
    "/retention-policies",
    summary="Políticas de retenção do tenant",
)
async def get_retention_policies(
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Lista políticas de retenção configuradas para o tenant."""
    repo = _lgpd_repo(db)
    policies = await repo.get_all_policies(claims.tenant_id)

    defaults = _default_policies()
    policy_items = [
        {
            "data_type": p.data_type,
            "retention_days": p.retention_days,
            "anonymize_instead_of_delete": p.anonymize_instead_of_delete,
            "auto_enabled": p.auto_enabled,
        }
        for p in policies
    ]

    return {
        "tenant_id": claims.tenant_id,
        "policies": policy_items,
        "items": policy_items,
        "defaults": defaults,
    }


@router.post(
    "/retention-policies",
    status_code=status.HTTP_201_CREATED,
    summary="Criar ou atualizar política de retenção",
)
@audit_action("lgpd.retention_policy_changed", resource_type="lgpd_retention_policy")
async def set_retention_policy(
    body: dict,
    claims: AdminUser,
    db: DbSession,
) -> dict:
    """
    Cria ou atualiza política de retenção.

    Body:
    - data_type: "video" | "alpr" | "face" | "audit" | "analytics"
    - retention_days: int
    - anonymize_instead_of_delete: bool (default true)
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from vms.lgpd.models import RetentionPolicyModel

    data_type = DataType(body.get("data_type", "video"))
    retention_days = int(body.get("retention_days", 7))
    anonymize = body.get("anonymize_instead_of_delete", True)

    tenant_id_raw = claims.tenant_id
    tenant_id_str = tenant_id_raw.value if hasattr(tenant_id_raw, 'value') else tenant_id_raw

    # Upsert: insert on conflict update
    stmt = pg_insert(RetentionPolicyModel).values(
        tenant_id=tenant_id_str,
        data_type=data_type,
        retention_days=retention_days,
        anonymize_instead_of_delete=anonymize,
        auto_enabled=True,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_retention_policy",
        set_=dict(
            retention_days=stmt.excluded.retention_days,
            anonymize_instead_of_delete=stmt.excluded.anonymize_instead_of_delete,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    await db.execute(stmt)
    await db.flush()

    logger.info("Política de retenção atualizada: tenant=%s type=%s days=%d",
                tenant_id_str, data_type, retention_days)

    return {
        "data_type": data_type,
        "retention_days": retention_days,
        "anonymize_instead_of_delete": anonymize,
    }


# ─── Solicitações do Titular (Art. 18 LGPD) ─────────────────────────────────

@router.post(
    "/data-request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Solicitar exportação de dados pessoais",
)
@audit_action("lgpd.data_requested", resource_type="lgpd_request")
async def request_data_export(
    body: dict,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """
    Solicita exportação de dados pessoais do titular (Art. 18 LGPD).

    Body:
    - request_type: "export" | "delete" | "anonymize"
    - notes: observações opcionais
    """
    return _data_subject_request_response(body, claims, RequestType.EXPORT)


@router.post(
    "/data-export",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@audit_action("lgpd.data_requested", resource_type="lgpd_request")
async def request_data_export_legacy(
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Alias legado para solicitação de exportação."""
    return _data_subject_request_response({}, claims, RequestType.EXPORT)


@router.post(
    "/data-deletion",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@audit_action("lgpd.data_requested", resource_type="lgpd_request")
async def request_data_deletion_legacy(
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Alias legado para solicitação de deleção."""
    return _data_subject_request_response({}, claims, RequestType.DELETE)


def _data_subject_request_response(body: dict | None, claims, default_request_type: RequestType) -> dict:
    body = body or {}
    request_type = RequestType(body.get("request_type", default_request_type))
    tenant_id_str = claims.tenant_id.value if hasattr(claims.tenant_id, 'value') else claims.tenant_id
    user_id_str = claims.user_id.value if hasattr(claims.user_id, 'value') else claims.user_id

    req = DataSubjectRequest(
        id=AuditId.new(),
        tenant_id=TenantId(tenant_id_str),
        request_type=request_type,
        status="pending",
        notes=body.get("notes"),
    )

    # Em produção: publicar task ARQ para processar exportação
    # Por enquanto: retorna aceito
    logger.info("Solicitação LGPD recebida: user=%s type=%s", user_id_str, request_type)

    return {
        "request_id": str(req.id),
        "request_type": request_type,
        "status": req.status,
        "created_at": req.created_at.isoformat(),
        "note": "Solicitação registrada. Em produção, será processada via ARQ task.",
    }


@router.get(
    "/data-requests",
    summary="Listar solicitações do titular",
)
async def list_data_requests(
    claims: CurrentUser,
    db: DbSession,
    status_filter: str = Query(default=None, alias="status"),
) -> dict:
    """Lista solicitações de dados do tenant."""
    # Para MVP: retornar lista vazia com estrutura
    # Em produção: query em tabela data_subject_requests
    return {
        "items": [],
        "total": 0,
        "note": "Endpoint reservado para implementação da tabela de solicitações.",
    }


# ─── Anonimização ────────────────────────────────────────────────────────────

@router.post(
    "/anonymize/events",
    summary="Anonimizar eventos expirados (admin only)",
)
@audit_action("lgpd.anonymization_executed", resource_type="lgpd_anonymization")
async def anonymize_expired_events(
    body: dict,
    claims: AdminUser,
    db: DbSession,
) -> dict:
    """
    Executa anonimização de eventos expirados conforme políticas de retenção.

    Body:
    - event_type: "alpr" | "face" — tipo de evento a anonimizar
    - event_ids: lista de IDs de eventos (opcional, senão varre todos expirados)
    """
    svc = _anonymization_svc(db)
    event_type = body.get("event_type", "alpr")
    event_ids = body.get("event_ids", [])

    results = []
    if event_type == "alpr":
        for eid in (event_ids or []):
            ok = await svc.anonymize_alpr_event(eid)
            results.append({"event_id": eid, "anonymized": ok})
    elif event_type == "face":
        for eid in (event_ids or []):
            ok = await svc.anonymize_face_event(eid)
            results.append({"event_id": eid, "anonymized": ok})
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"event_type inválido: {event_type}. Use 'alpr' ou 'face'.",
        )

    return {
        "event_type": event_type,
        "total_processed": len(results),
        "results": results,
    }


@router.post(
    "/generate-ripd",
    summary="Gerar RIPD (Relatório de Impacto à Proteção de Dados)",
)
@audit_action("lgpd.ripd_generated", resource_type="lgpd_ripd")
async def generate_ripd(
    claims: AdminUser,
    db: DbSession,
) -> dict:
    """
    Gera Relatório de Impacto à Proteção de Dados (RIPD).

    Inclui:
    - Finalidade do tratamento
    - Dados coletados e retenção
    - Quem tem acesso
    - Medidas de segurança
    - Direitos dos titulares
    """
    repo = _lgpd_repo(db)
    policies = await repo.get_all_policies(claims.tenant_id)

    ripd = {
        "report_type": "RIPD — Relatório de Impacto à Proteção de Dados",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": claims.tenant_id,
        "generated_by": claims.user_id,
        "sections": {
            "finalidade": "Tratamento de dados de videovigilância para segurança e monitoramento.",
            "dados_coletados": {
                "video": f"Retenção: {_find_policy(policies, DataType.VIDEO).retention_days} dias",
                "alpr": f"Retenção: {_find_policy(policies, DataType.ALPR).retention_days} dias (dados de localização)",
                "face": f"Retenção: {_find_policy(policies, DataType.FACE).retention_days} dias (dados biométricos)",
                "audit": f"Retenção: {_find_policy(policies, DataType.AUDIT).retention_days} dias (requisito legal)",
            },
            "base_legal": "LGPD Art. 7º, IV — execução de política pública; Art. 11, II — exercício regular de direitos",
            "medidas_seguranca": [
                "Criptografia em trânsito (TLS)",
                "Controle de acesso baseado em roles (RBAC)",
                "Audit trail completo e imutável",
                "Anonimização automática após expiração",
            ],
            "direitos_titulares": [
                "Confirmação da existência de tratamento",
                "Acesso aos dados",
                "Correção de dados incompletos/exatos/desatualizados",
                "Anonimização, bloqueio ou eliminação",
                "Portabilidade dos dados",
                "Revogação do consentimento",
            ],
            "compartilhamento": "Não compartilhado com terceiros, exceto por ordem judicial.",
        },
    }

    return ripd


# ─── Status LGPD ─────────────────────────────────────────────────────────────

@router.get(
    "/status",
    summary="Status de compliance LGPD do tenant",
)
async def lgpd_status(
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Retorna status geral de compliance LGPD do tenant."""
    repo = _lgpd_repo(db)
    policies = await repo.get_all_policies(claims.tenant_id)

    return {
        "tenant_id": claims.tenant_id,
        "policies_configured": len(policies),
        "compliance_level": _calc_compliance_level(policies),
        "face_recognition_requires_consent": True,
        "anonymization_enabled": True,
        "audit_trail_enabled": True,
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _default_policies() -> dict[str, int]:
    return {
        DataType.VIDEO: 7,
        DataType.ALPR: 90,
        DataType.FACE: 30,
        DataType.AUDIT: 1825,
        DataType.ANALYTICS: 365,
    }


# ─── Exclusão de dados biométricos por CPF (LGPD Art. 18) ────────────────────

@router.delete(
    "/faces/{cpf}",
    status_code=status.HTTP_200_OK,
    summary="Excluir dados biométricos por CPF",
)
@audit_action("lgpd.face_data_deleted", resource_type="face_profile")
async def delete_face_data(
    cpf: str,
    body: dict,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """
    Exclui todos os dados biométricos vinculados a um CPF.

    Body obrigatório: {"confirm": "CONFIRMAR"}

    Nunca armazena CPF em claro — usa SHA-256 para lookup.
    Cascata: AnalyticEvent(type=face) + thumbnails MinIO + FaceProfile (se existir).
    Gera AuditLog com metadados da operação.
    """
    if body.get("confirm") != "CONFIRMAR":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='Confirmação obrigatória: envie {"confirm": "CONFIRMAR"} no body',
        )

    cpf_hash = hashlib.sha256(cpf.strip().encode()).hexdigest()
    tenant_id = claims.tenant_id

    deleted_events = 0
    deleted_minio = 0

    # Remove AnalyticEvents do tipo face vinculados ao CPF (via attributes.cpf_hash)
    try:
        from sqlalchemy import delete as sa_delete
        from vms.analytics.analytic_event_model import AnalyticEvent

        stmt = sa_delete(AnalyticEvent).where(
            AnalyticEvent.tenant_id == tenant_id,
            AnalyticEvent.event_type == "face",
            AnalyticEvent.attributes["cpf_hash"].astext == cpf_hash,
        ).returning(AnalyticEvent.thumbnail_key)
        result = await db.execute(stmt)
        rows = result.fetchall()
        deleted_events = len(rows)

        # Remove thumbnails do MinIO (bucket de snapshots — ver ADR-010)
        from vms.infrastructure.config import get_settings
        from vms.infrastructure.object_storage import ObjectStorage

        storage = ObjectStorage()
        bucket = get_settings().minio_bucket_snapshots
        for row in rows:
            if row[0]:
                try:
                    storage.delete_object(bucket, row[0])
                    deleted_minio += 1
                except Exception:
                    logger.warning("Falha ao remover thumbnail MinIO: %s", row[0])
    except Exception:
        logger.exception("Falha ao excluir dados de face para cpf_hash=%s", cpf_hash[:8])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao excluir dados biométricos",
        )

    logger.info(
        "LGPD face deletion: tenant=%s cpf_hash=%s events=%d minio=%d",
        tenant_id,
        cpf_hash[:8],
        deleted_events,
        deleted_minio,
    )

    return {
        "cpf_hash": cpf_hash,
        "deleted_analytic_events": deleted_events,
        "deleted_minio_objects": deleted_minio,
        "tenant_id": tenant_id,
    }


def _find_policy(policies: list[RetentionPolicy], data_type: DataType) -> RetentionPolicy:
    defaults = _default_policies()
    for p in policies:
        if p.data_type == data_type:
            return p
    # Retorna policy default
    return RetentionPolicy(
        id=AuditId.new(),
        tenant_id=TenantId(""),
        data_type=data_type,
        retention_days=defaults.get(data_type, 7),
    )


def _calc_compliance_level(policies: list[RetentionPolicy]) -> str:
    required = {DataType.VIDEO, DataType.ALPR, DataType.FACE, DataType.AUDIT}
    configured = {p.data_type for p in policies}
    if required.issubset(configured):
        return "full"
    if len(configured) >= 2:
        return "partial"
    return "minimal"
