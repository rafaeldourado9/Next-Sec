"""Casos de uso do edge: ativação por licença e ingestão em lote (ADR-018)."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.audit.models import AuditLogModel
from vms.billing.models import LicenseKeyModel
from vms.cameras.models import CameraModel
from vms.cameras.repository import AgentRepository, CameraRepository
from vms.cameras.service import AgentService
from vms.edge.schemas import (
    BATCH_MAX_EVENTS,
    EdgeBatchItemResult,
    EdgeEventItem,
    EdgePolicy,
)
from vms.events.models import VmsEventModel
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.models import TenantModel
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService
from vms.infrastructure.config import get_settings
from vms.shared.exceptions import BusinessRuleViolation, ConflictError, NotFoundError

logger = logging.getLogger(__name__)


def policy_from_license(license_key: LicenseKeyModel) -> EdgePolicy:
    """Traduz os limites persistidos na licença para o contrato do agente."""
    return EdgePolicy(
        events_per_minute=license_key.events_per_minute,
        batch_max_events=BATCH_MAX_EVENTS,
        clip_seconds=license_key.clip_seconds,
        clip_max_height=license_key.clip_max_height,
        clip_retention_days=license_key.clip_retention_days,
        storage_quota_mb=license_key.storage_quota_mb,
    )


class EdgeActivationService:
    """Troca uma chave de licença digitada pelo cliente por credenciais de agente.

    É o único caminho pelo qual uma API key de edge passa a existir a partir da
    ADR-018 — nenhum segredo viaja mais dentro do instalador.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._agents = AgentService(
            AgentRepository(db),
            CameraRepository(db),
            ApiKeyService(ApiKeyRepository(db)),
        )
        self._api_keys = ApiKeyService(ApiKeyRepository(db))

    async def activate(
        self,
        *,
        license_key_value: str,
        hardware_fingerprint: str,
        hostname: str,
        agent_version: str,
    ) -> tuple[str, str, TenantModel, EdgePolicy]:
        """Ativa (ou reativa) um edge. Retorna `(agent_id, api_key, tenant, policy)`.

        Reativação com o **mesmo** fingerprint é idempotente e reemite a API
        key, revogando a anterior — é o que cobre reinstalação do Windows,
        restauração de backup e o cliente que perdeu o `agent.json`. Só o
        fingerprint diferente é recusado.
        """
        license_key = await self._db.scalar(
            select(LicenseKeyModel).where(LicenseKeyModel.license_key == license_key_value)
        )
        if license_key is None:
            msg = "Licença não encontrada. Confira a chave digitada."
            raise NotFoundError(msg)

        self._assert_usable(license_key)
        tenant = await self._load_active_tenant(license_key)

        bound = license_key.hardware_fingerprint
        if bound and bound != hardware_fingerprint:
            # 409, não 400: o cliente não digitou nada errado — o estado do
            # servidor é que impede, e existe uma ação clara de saída
            # (`POST /admin/licenses/{id}/unbind`).
            msg = (
                "Esta licença já está ativada em outra máquina. Peça ao suporte "
                "para desvinculá-la antes de instalar aqui."
            )
            raise ConflictError(msg)

        agent_id, plain_key = await self._issue_agent_credentials(
            license_key, tenant, hostname, reactivating=bool(bound)
        )

        now = datetime.now(UTC)
        license_key.hardware_fingerprint = hardware_fingerprint
        license_key.activated_hostname = hostname or license_key.activated_hostname
        license_key.agent_id = agent_id
        license_key.agent_version = agent_version or license_key.agent_version
        license_key.last_seen_at = now
        if license_key.activated_at is None:
            license_key.activated_at = now

        # Ativar o edge conclui o onboarding do tenant: é o momento em que ele
        # deixa de ser um cadastro e passa a ter uma instalação real rodando.
        tenant.onboarding_complete = True
        if license_key.tenant_id and not tenant.license_key_id:
            tenant.license_key_id = license_key.id

        self._db.add(AuditLogModel(
            tenant_id=tenant.id,
            user_id=None,
            action="edge.activated" if not bound else "edge.reactivated",
            resource_type="license_key",
            resource_id=license_key.id,
            payload={
                "agent_id": agent_id,
                "hostname": hostname,
                "agent_version": agent_version,
                "hardware_fingerprint": hardware_fingerprint,
            },
        ))
        await self._db.commit()

        logger.info(
            "Edge ativado — tenant=%s agent=%s host=%s (reativação=%s)",
            tenant.id, agent_id, hostname, bool(bound),
        )
        return agent_id, plain_key, tenant, policy_from_license(license_key)

    async def unbind(self, license_key_id: str, actor_user_id: str) -> None:
        """Desfaz o vínculo com a máquina e revoga as credenciais do agente.

        Chamado por um admin quando o cliente troca de hardware. Revogar junto
        é o ponto: desvincular sem revogar deixaria a instalação antiga
        continuar enviando eventos indefinidamente.
        """
        license_key = await self._db.get(LicenseKeyModel, license_key_id)
        if license_key is None:
            msg = f"Licença '{license_key_id}' não encontrada"
            raise NotFoundError(msg)

        if license_key.agent_id and license_key.tenant_id:
            await self._api_keys.revoke_api_keys_for_owner(
                ApiKeyOwnerType.AGENT, license_key.agent_id, license_key.tenant_id
            )

        previous_fingerprint = license_key.hardware_fingerprint
        license_key.hardware_fingerprint = None
        license_key.activated_hostname = None
        license_key.agent_id = None

        self._db.add(AuditLogModel(
            tenant_id=license_key.tenant_id,
            user_id=actor_user_id,
            action="edge.unbound",
            resource_type="license_key",
            resource_id=license_key.id,
            payload={"previous_fingerprint": previous_fingerprint},
        ))
        await self._db.commit()
        logger.info("Licença %s desvinculada por %s", license_key_id, actor_user_id)

    # ─── Internos ────────────────────────────────────────────────────────

    def _assert_usable(self, license_key: LicenseKeyModel) -> None:
        """Recusa licença suspensa, expirada ou ainda não vendida a um cliente."""
        if license_key.status != "active":
            msg = f"Licença com status '{license_key.status}' — não pode ser ativada."
            raise BusinessRuleViolation(msg)

        if license_key.expires_at is not None:
            expires_at = license_key.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                msg = "Licença expirada."
                raise BusinessRuleViolation(msg)

        if not license_key.tenant_id:
            msg = "Licença ainda não vinculada a um cliente. Fale com o suporte."
            raise BusinessRuleViolation(msg)

    async def _load_active_tenant(self, license_key: LicenseKeyModel) -> TenantModel:
        tenant = await self._db.get(TenantModel, license_key.tenant_id)
        if tenant is None or tenant.deleted_at is not None:
            msg = "Cliente desta licença não existe mais. Fale com o suporte."
            raise NotFoundError(msg)
        if not tenant.is_active:
            msg = "Conta suspensa. Fale com o suporte."
            raise BusinessRuleViolation(msg)
        return tenant

    async def _issue_agent_credentials(
        self,
        license_key: LicenseKeyModel,
        tenant: TenantModel,
        hostname: str,
        *,
        reactivating: bool,
    ) -> tuple[str, str]:
        """Reaproveita o agent existente numa reativação; cria um novo na primeira.

        Reaproveitar importa: as câmeras do cliente estão ligadas ao
        `agent_id`, então criar um agent novo a cada reinstalação órfãnaria
        toda a configuração que ele já tinha feito.
        """
        if reactivating and license_key.agent_id:
            agent = await self._agents.get_agent(license_key.agent_id, tenant.id)
            await self._api_keys.revoke_api_keys_for_owner(
                ApiKeyOwnerType.AGENT, agent.id, tenant.id
            )
            _, plain_key = await self._api_keys.issue_api_key(
                tenant_id=tenant.id,
                owner_type=ApiKeyOwnerType.AGENT,
                owner_id=agent.id,
            )
            return agent.id, plain_key

        agent, plain_key = await self._agents.create_agent(
            tenant.id, name=hostname or f"{tenant.slug}-edge"
        )
        return agent.id, plain_key


class EdgeIngestService:
    """Persiste lotes de eventos vindos do edge (ADR-018 §5)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def ingest_batch(
        self, tenant_id: str, events: list[EdgeEventItem]
    ) -> list[EdgeBatchItemResult]:
        """Insere o lote inteiro numa transação e devolve o veredito por item.

        Duas consultas fixas (câmeras do tenant, IDs já vistos) em vez de duas
        por evento — é o que faz um lote de 100 custar quase o mesmo que um de
        1, e é o motivo de o endpoint em lote existir.
        """
        camera_ids = {e.camera_id for e in events}
        valid_cameras = set((await self._db.scalars(
            select(CameraModel.id).where(
                CameraModel.tenant_id == tenant_id,
                CameraModel.id.in_(camera_ids),
            )
        )).all())

        client_ids = [e.client_event_id for e in events]
        existing = dict((await self._db.execute(
            select(VmsEventModel.client_event_id, VmsEventModel.id).where(
                VmsEventModel.tenant_id == tenant_id,
                VmsEventModel.client_event_id.in_(client_ids),
            )
        )).all())

        results: list[EdgeBatchItemResult] = []
        # Um lote pode trazer o mesmo client_event_id duas vezes (retry que se
        # cruzou com o envio original dentro do próprio outbox) — sem esta
        # checagem em memória, os dois passariam pelo filtro de `existing` e o
        # INSERT violaria o índice único, derrubando o lote inteiro.
        seen_in_batch: set[str] = set()
        to_insert: list[VmsEventModel] = []

        for event in events:
            if event.client_event_id in existing:
                results.append(EdgeBatchItemResult(
                    client_event_id=event.client_event_id,
                    status="duplicate",
                    event_id=existing[event.client_event_id],
                ))
                continue
            if event.client_event_id in seen_in_batch:
                results.append(EdgeBatchItemResult(
                    client_event_id=event.client_event_id,
                    status="duplicate",
                    reason="Repetido dentro do próprio lote",
                ))
                continue
            if event.camera_id not in valid_cameras:
                results.append(EdgeBatchItemResult(
                    client_event_id=event.client_event_id,
                    status="rejected",
                    reason="Câmera não encontrada neste cliente",
                ))
                continue

            event_id = str(uuid.uuid4())
            seen_in_batch.add(event.client_event_id)
            to_insert.append(VmsEventModel(
                id=event_id,
                tenant_id=tenant_id,
                camera_id=event.camera_id,
                event_type=event.event_type,
                plate=event.plate,
                confidence=event.confidence,
                client_event_id=event.client_event_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            ))
            results.append(EdgeBatchItemResult(
                client_event_id=event.client_event_id,
                status="accepted",
                event_id=event_id,
            ))

        if to_insert:
            self._db.add_all(to_insert)
            await self._db.commit()

        return results


class StorageQuota:
    """Cota de storage de clipe por cliente (ADR-018 §4).

    Complementa a cota de *ingestão* (`edge/quota.py`, token bucket no Redis):
    aquela limita ritmo, esta limita volume acumulado. São controles diferentes
    porque falham diferente — um cliente dentro do ritmo contratado ainda pode
    encher o disco da VPS ao longo de semanas.

    Contabiliza sobre `event_clips.size_bytes` (denormalizado com `tenant_id`
    na migration 0015), não sobre o storage real: consultar o MinIO a cada
    upload custaria uma chamada de rede no caminho crítico, e a retenção já
    mantém os dois em sincronia ao apagar linha e objeto juntos.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def used_bytes(self, tenant_id: str) -> int:
        from vms.event_clips.models import EventClipModel

        return int(await self._db.scalar(
            select(func.coalesce(func.sum(EventClipModel.size_bytes), 0)).where(
                EventClipModel.tenant_id == tenant_id
            )
        ) or 0)

    async def has_room_for(self, tenant_id: str, quota_mb: int, incoming_bytes: int) -> bool:
        """Cota 0 = ilimitada (usada por clientes internos/demonstração)."""
        if quota_mb <= 0:
            return True
        return (await self.used_bytes(tenant_id)) + incoming_bytes <= quota_mb * 1024 * 1024


def edge_public_api_url() -> str:
    """URL que o agente passa a usar depois de ativado (sem barra final)."""
    return get_settings().edge_public_api_url.rstrip("/")
