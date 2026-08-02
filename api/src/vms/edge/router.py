"""Rotas do edge — ativação por licença e ingestão em lote (ADR-018).

Separado de `plugins/router.py` de propósito: aquele é o contrato público de
plugins/integrações de terceiros (item único, multipart com mídia, sem cota) e
continua valendo para setups Nível 3. Este é o contrato de um agente **nosso**
rodando na máquina de um cliente — em lote, idempotente, com cota por tenant e
backpressure explícito. Misturar os dois obrigaria a fazer o caminho antigo
carregar regras que ele não tem como cumprir.
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.billing.models import LicenseKeyModel
from vms.edge.quota import IngestQuota
from vms.edge.schemas import (
    EdgeActivateRequest,
    EdgeActivateResponse,
    EdgeBatchRequest,
    EdgeBatchResponse,
    EdgeHeartbeatRequest,
    EdgeHeartbeatResponse,
)
from vms.edge.service import (
    EdgeActivationService,
    EdgeIngestService,
    StorageQuota,
    edge_public_api_url,
    edge_public_rtmp_url,
    policy_from_license,
)
from vms.events.models import VmsEventModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import AuthService
from vms.infrastructure.exceptions import AuthenticationError
from vms.shared.api.dependencies import ApiKeyHeader, DbSession
from vms.shared.api.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/edge", tags=["edge"])


async def _resolve_agent_tenant(api_key: str, db: AsyncSession) -> str:
    """Autentica a API key emitida na ativação e devolve o tenant.

    Ao contrário de `plugins/router.py::_resolve_plugin_tenant`, **não** aceita
    a chave de env do analytics: aqui a identidade precisa ser de uma
    instalação concreta, senão a cota por tenant não teria como ser aplicada
    (a chave de env é compartilhada e resolve pro primeiro admin do banco).
    """
    auth_svc = AuthService(user_repo=None, api_key_repo=ApiKeyRepository(db))  # type: ignore[arg-type]
    try:
        key_entity = await auth_svc.authenticate_api_key(api_key)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou revogada — reative o agente com a licença.",
        ) from exc
    return key_entity.tenant_id


async def _license_for_tenant(tenant_id: str, db: AsyncSession) -> LicenseKeyModel | None:
    """Licença ativa do tenant — de onde saem os limites operacionais."""
    return await db.scalar(
        select(LicenseKeyModel).where(
            LicenseKeyModel.tenant_id == tenant_id,
            LicenseKeyModel.status == "active",
        )
    )


@router.post(
    "/activate",
    response_model=EdgeActivateResponse,
    summary="Ativa uma instalação de edge a partir da chave de licença",
)
@limiter.limit("10/minute")
async def activate_edge(
    request: Request,
    body: EdgeActivateRequest,
    db: DbSession,
) -> EdgeActivateResponse:
    """
    Único endpoint público do fluxo de instalação (ADR-018 §1): o cliente digita
    a licença no instalador e recebe de volta as credenciais do agente. Nenhum
    segredo viaja dentro do instalador — ele é idêntico para todos os clientes.

    Rate limit por IP (10/min) porque a chave de licença é o único segredo aqui
    e o endpoint é anônimo: sem isso, o espaço de chaves seria varrível.
    Mesmo assim ele não é um oráculo útil — licença inexistente, suspensa e
    expirada devolvem mensagens diferentes de propósito (o cliente precisa
    saber o que fazer), mas todas exigem já conhecer uma chave bem-formada.

    Reativar na **mesma** máquina é idempotente e reemite a API key (cobre
    reinstalação do Windows); em máquina diferente devolve 409 até um admin
    desvincular.
    """
    agent_id, api_key, tenant, policy = await EdgeActivationService(db).activate(
        license_key_value=body.license_key,
        hardware_fingerprint=body.hardware_fingerprint,
        hostname=body.hostname,
        agent_version=body.agent_version,
    )
    return EdgeActivateResponse(
        agent_id=agent_id,
        api_key=api_key,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        api_base_url=edge_public_api_url(),
        rtmp_url=edge_public_rtmp_url(),
        policy=policy,
    )


@router.post(
    "/events:batch",
    response_model=EdgeBatchResponse,
    summary="Ingestão em lote de eventos do edge",
)
async def ingest_events_batch(
    body: EdgeBatchRequest,
    api_key: ApiKeyHeader,
    db: DbSession,
    request: Request,
    response: Response,
) -> EdgeBatchResponse:
    """
    Recebe até 100 eventos por request (ADR-018 §5). Sem mídia: foto e clipe
    sobem depois, em requisições próprias, só para os eventos aceitos — assim
    um lote grande não fica refém do upload de um JPEG.

    **Cota por tenant** avaliada antes de qualquer trabalho de banco, custando
    1 token por evento. Ao estourar, devolve `429` com `Retry-After` e **não
    grava nada** — o lote inteiro volta pro outbox do agente, que respeita o
    header. Recusar o lote todo (em vez de aceitar parcialmente) mantém o
    contrato simples do lado do agente: ou ele tem o veredito de cada item, ou
    tenta de novo mais tarde.
    """
    tenant_id = await _resolve_agent_tenant(api_key, db)
    license_key = await _license_for_tenant(tenant_id, db)
    events_per_minute = license_key.events_per_minute if license_key else 120

    quota = IngestQuota(request.app.state.redis)
    decision = await quota.check(tenant_id, events_per_minute, cost=len(body.events))
    if not decision.allowed:
        logger.warning(
            "Cota de ingestão estourada — tenant=%s lote=%d retry_after=%ds",
            tenant_id, len(body.events), decision.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Cota de eventos excedida — reenvie após o intervalo indicado.",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(events_per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )

    response.headers["X-RateLimit-Limit"] = str(events_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)

    results = await EdgeIngestService(db).ingest_batch(tenant_id, body.events)
    accepted = [r for r in results if r.status == "accepted"]

    await _publish_batch_side_effects(request, tenant_id, body, results)

    return EdgeBatchResponse(
        accepted=len(accepted),
        duplicates=sum(1 for r in results if r.status == "duplicate"),
        rejected=sum(1 for r in results if r.status == "rejected"),
        results=results,
    )


async def _publish_batch_side_effects(
    request: Request, tenant_id: str, body: EdgeBatchRequest, results: list
) -> None:
    """SSE + notificação dos eventos aceitos.

    Best-effort de propósito: o evento já está persistido quando isto roda, e
    uma falha de Redis aqui não pode transformar um lote gravado com sucesso
    num erro que faria o agente reenviar tudo (e duplicar o trabalho, ainda que
    a idempotência evite duplicar o dado).
    """
    accepted_ids = {r.client_event_id: r.event_id for r in results if r.status == "accepted"}
    if not accepted_ids:
        return

    by_client_id = {e.client_event_id: e for e in body.events}
    arq_pool = getattr(request.app.state, "arq_redis", None)

    for client_event_id, event_id in accepted_ids.items():
        event = by_client_id[client_event_id]
        severity = (event.payload or {}).get("severity", "info")

        # SSE só para o que o operador precisa ver na hora. Publicar todo
        # evento de todo tenant num pub/sub compartilhado é justamente o tipo
        # de custo por evento que a ADR-018 §5 quer tirar do caminho.
        if severity != "info":
            try:
                from vms.infrastructure.messaging.event_bus import publish_event

                await publish_event(
                    "analytics.event",
                    {
                        "event_type": event.event_type,
                        "camera_id": event.camera_id,
                        "severity": severity,
                        "confidence": event.confidence,
                        "occurred_at": event.occurred_at.isoformat(),
                    },
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.debug("Falha ao publicar SSE do evento %s", event_id, exc_info=True)

        # Notificação só faz sentido com imagem — o edge marca `has_snapshot`
        # e sobe o JPEG logo em seguida (`PUT /edge/events/{id}/snapshot`),
        # que é quem enfileira o dispatch de fato.
        if not event.has_snapshot and arq_pool is not None:
            try:
                await arq_pool.enqueue_job(
                    "task_dispatch_event_notifications",
                    tenant_id,
                    event.event_type,
                    event_id,
                    event.payload or {},
                    None,
                    event.camera_id,
                    True,
                )
            except Exception:
                logger.exception("Falha ao enfileirar notificação do evento %s", event_id)


async def _event_of_tenant(event_id: str, tenant_id: str, db: AsyncSession) -> VmsEventModel:
    """Carrega o evento garantindo que ele pertence ao tenant da API key.

    Isolamento de tenant é checado aqui, não confiado ao chamador: o `event_id`
    é um UUID que viaja no path, e cada cliente tem sua própria key — sem esta
    verificação, a key de um tenant anexaria mídia ao evento de outro bastando
    conhecer o ID (mesmo achado da auditoria de S6-06 em `PUT /plugins/
    events/{id}/clip`).
    """
    event = await db.get(VmsEventModel, event_id)
    if event is None or str(event.tenant_id) != str(tenant_id):
        # 404 e não 403: dizer "existe, mas não é seu" já vazaria a informação
        # de que aquele ID é válido em algum lugar do sistema.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado")
    return event


@router.put(
    "/events/{event_id}/snapshot",
    summary="Anexa a foto de um evento já aceito no lote",
)
async def upload_event_snapshot(
    event_id: str,
    api_key: ApiKeyHeader,
    db: DbSession,
    request: Request,
    snapshot_file: UploadFile = File(...),
) -> dict:
    """
    Segundo passo do fluxo em lote (ADR-018 §5): o `:batch` sobe só metadado, e
    a foto vem aqui — **só para os eventos que a VPS aceitou**. Separar os dois
    é o que impede um lote de 100 eventos de ficar refém do upload de um JPEG.

    É este endpoint, e não o `:batch`, que enfileira a notificação: o alerta de
    WhatsApp manda a imagem junto, então notificar antes dela chegar produziria
    uma mensagem sem a evidência.
    """
    tenant_id = await _resolve_agent_tenant(api_key, db)
    event = await _event_of_tenant(event_id, tenant_id, db)

    content = await snapshot_file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Arquivo de snapshot vazio")

    from vms.plugins.router import _save_uploaded_snapshot

    snapshot_path = _save_uploaded_snapshot(tenant_id, str(event.camera_id), content)
    if snapshot_path is None:
        raise HTTPException(status_code=500, detail="Falha ao gravar o snapshot")

    event.image_path = snapshot_path
    await db.commit()

    arq_pool = getattr(request.app.state, "arq_redis", None)
    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job(
                "task_dispatch_event_notifications",
                tenant_id,
                event.event_type,
                event_id,
                event.payload or {},
                snapshot_path,
                str(event.camera_id),
                True,  # edge_generates_clip: nenhum ffmpeg roda na VPS
            )
        except Exception:
            logger.exception("Falha ao enfileirar notificação do evento %s", event_id)

    return {"event_id": event_id, "snapshot_path": snapshot_path}


@router.put(
    "/events/{event_id}/clip",
    summary="Anexa o clipe de 15 s de um evento já aceito no lote",
)
async def upload_event_clip(
    event_id: str,
    api_key: ApiKeyHeader,
    db: DbSession,
    clip_file: UploadFile = File(...),
) -> dict:
    """
    Recebe o MP4 **já cortado e reencodado pelo edge** (15 s, 480 p — ver
    ADR-018 §4). Nenhum ffmpeg roda aqui.

    Recusa com `413` quando o cliente estourou `storage_quota_mb`. Recusar só o
    clipe, mantendo evento e foto, é deliberado: o cliente continua enxergando
    o que aconteceu e recebendo alerta — perde a evidência em vídeo, que é o
    item caro, não o registro.
    """
    tenant_id = await _resolve_agent_tenant(api_key, db)
    await _event_of_tenant(event_id, tenant_id, db)

    content = await clip_file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Arquivo de clipe vazio")

    license_key = await _license_for_tenant(tenant_id, db)
    quota_mb = license_key.storage_quota_mb if license_key else 0
    if not await StorageQuota(db).has_room_for(tenant_id, quota_mb, len(content)):
        logger.warning("Cota de storage estourada — tenant=%s clipe=%d bytes", tenant_id, len(content))
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Cota de armazenamento de clipes excedida.",
        )

    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    with open(tmp_path, "wb") as fh:
        fh.write(content)

    from vms.event_clips.service import build_event_clip_service

    clip = await build_event_clip_service(db).receive_pregenerated_clip(
        vms_event_id=event_id, tenant_id=tenant_id, local_mp4_path=tmp_path,
    )
    return {"event_id": event_id, "clip_id": clip.id, "status": clip.status.value}


@router.post(
    "/heartbeat",
    response_model=EdgeHeartbeatResponse,
    summary="Heartbeat do agente de edge",
)
async def edge_heartbeat(
    body: EdgeHeartbeatRequest,
    api_key: ApiKeyHeader,
    db: DbSession,
) -> EdgeHeartbeatResponse:
    """
    Mantém `last_seen_at` da licença e devolve a policy vigente.

    Devolver a policy a cada batida é o que permite mudar a cota ou a duração
    do clipe de um cliente pelo painel e ver o efeito na instalação dele em um
    minuto, sem ninguém tocar na máquina. `outbox_pending`/`outbox_dropped`
    sobem no corpo porque é o sintoma mais útil que a VPS tem de um edge com
    problema — ela não consegue olhar lá dentro.
    """
    tenant_id = await _resolve_agent_tenant(api_key, db)
    license_key = await _license_for_tenant(tenant_id, db)
    if license_key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nenhuma licença ativa para este cliente.",
        )

    license_key.last_seen_at = datetime.now(UTC)
    if body.agent_version:
        license_key.agent_version = body.agent_version
    await db.commit()

    if body.outbox_dropped > 0:
        logger.warning(
            "Edge descartou %d eventos por cap de fila — tenant=%s pendentes=%d",
            body.outbox_dropped, tenant_id, body.outbox_pending,
        )

    return EdgeHeartbeatResponse(
        policy=policy_from_license(license_key),
        license_status=license_key.status,
    )
