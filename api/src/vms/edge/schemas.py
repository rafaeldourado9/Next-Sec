"""Contratos HTTP do edge — ativação por licença e ingestão em lote (ADR-018)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Formato emitido por `admin/router.py::_generate_license_key` e por
# `scripts/create_license.py`: XXXX-XXXXX-XXXXX-XXXXX-XXXXX (A-Z0-9).
_LICENSE_KEY_RE = re.compile(r"^[A-Z0-9]{4}(-[A-Z0-9]{5}){4}$")

# Teto de itens por request de `:batch`. O agente recebe esse número em
# `EdgePolicy.batch_max_events` e não deveria estourá-lo; o servidor valida de
# novo porque o cliente é código que roda na máquina de outra pessoa.
BATCH_MAX_EVENTS = 100


class EdgeActivateRequest(BaseModel):
    """Corpo de `POST /edge/activate` — o único segredo que o cliente digita."""

    license_key: str = Field(..., description="XXXX-XXXXX-XXXXX-XXXXX-XXXXX")
    hardware_fingerprint: str = Field(
        ...,
        min_length=16,
        max_length=64,
        description=(
            "Hash estável da máquina, gerado pelo agente. Vincula a licença a "
            "uma instalação — ver ADR-018 §1."
        ),
    )
    hostname: str = Field(default="", max_length=255)
    agent_version: str = Field(default="", max_length=32)

    @field_validator("license_key")
    @classmethod
    def normalize_license_key(cls, v: str) -> str:
        """Aceita a chave como o cliente digitou (minúscula, com espaço).

        O usuário final copia isso de um email ou de um papel; recusar por
        causa de um espaço colado no fim seria atrito gratuito num passo que
        só acontece uma vez e sem ninguém do suporte por perto.
        """
        normalized = v.strip().upper().replace(" ", "")
        if not _LICENSE_KEY_RE.match(normalized):
            msg = "Formato de licença inválido — esperado XXXX-XXXXX-XXXXX-XXXXX-XXXXX"
            raise ValueError(msg)
        return normalized

    @field_validator("hardware_fingerprint")
    @classmethod
    def normalize_fingerprint(cls, v: str) -> str:
        return v.strip().lower()


class EdgePolicy(BaseModel):
    """Limites que a VPS impõe a este cliente — o agente é quem os respeita.

    Viajam na resposta da ativação (e são reconfirmados a cada heartbeat) em
    vez de ficarem hardcoded no agente: mudar o teto de um cliente não pode
    exigir reinstalar nada na máquina dele.
    """

    events_per_minute: int
    batch_max_events: int = BATCH_MAX_EVENTS
    clip_seconds: int
    clip_max_height: int
    clip_retention_days: int
    storage_quota_mb: int
    heartbeat_seconds: int = 60
    config_poll_seconds: int = 300


class EdgeActivateResponse(BaseModel):
    """Resposta da ativação — única vez que a API key trafega."""

    agent_id: str
    api_key: str = Field(
        ..., description="Guarde: não é recuperável. Reativar emite uma nova e revoga esta."
    )
    tenant_id: str
    tenant_name: str
    api_base_url: str
    rtmp_url: str = Field(
        ...,
        description=(
            "Base RTMP pública para onde o agente empurra o vídeo das câmeras "
            "(ex.: rtmp://vm-server.duckdns.org:1935)."
        ),
    )
    policy: EdgePolicy


class EdgeEventItem(BaseModel):
    """Um evento no lote. Sem mídia — foto e clipe sobem depois, só para os
    eventos que a VPS aceitou (ADR-018 §5)."""

    client_event_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="UUID gerado no edge — chave de idempotência do reenvio.",
    )
    camera_id: str
    event_type: str = Field(..., max_length=100)
    occurred_at: datetime
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    plate: str | None = Field(default=None, max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict)
    has_snapshot: bool = False
    has_clip: bool = False


class EdgeBatchRequest(BaseModel):
    """Corpo de `POST /edge/events:batch`."""

    events: list[EdgeEventItem] = Field(..., min_length=1, max_length=BATCH_MAX_EVENTS)


class EdgeBatchItemResult(BaseModel):
    """Resultado de um item do lote.

    O edge só remove do outbox o que voltou `accepted` ou `duplicate` —
    `rejected` é definitivo (não adianta reenviar) e `duplicate` significa que
    a VPS já tinha o evento, provavelmente de uma tentativa cuja resposta se
    perdeu.
    """

    client_event_id: str
    status: Literal["accepted", "duplicate", "rejected"]
    event_id: str | None = None
    reason: str | None = None


class EdgeBatchResponse(BaseModel):
    """Resposta de `POST /edge/events:batch`."""

    accepted: int
    duplicates: int
    rejected: int
    results: list[EdgeBatchItemResult]


class EdgeHeartbeatRequest(BaseModel):
    """Heartbeat do agente — carrega o que a VPS precisa pra diagnosticar o
    edge sem acessá-lo (a fila local é o sintoma mais útil: se ela cresce, ou
    a rede do cliente está ruim ou a cota dele está apertada demais)."""

    agent_version: str = Field(default="", max_length=32)
    uptime_seconds: int = Field(default=0, ge=0)
    cameras_online: int = Field(default=0, ge=0)
    cameras_total: int = Field(default=0, ge=0)
    outbox_pending: int = Field(default=0, ge=0)
    outbox_dropped: int = Field(
        default=0, ge=0, description="Eventos descartados por cap de fila desde o último heartbeat."
    )
    disk_free_mb: int = Field(default=0, ge=0)


class EdgeHeartbeatResponse(BaseModel):
    """Resposta do heartbeat — devolve a policy vigente para o agente se
    reconfigurar sem reinstalação, e sinaliza quando a licença deixou de valer."""

    policy: EdgePolicy
    license_status: str
