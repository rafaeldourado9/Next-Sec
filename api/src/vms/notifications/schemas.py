"""Schemas Pydantic para o bounded context de notificações."""
from __future__ import annotations

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class CreateRuleRequest(BaseModel):
    """Payload para criação de regra de notificação.

    `destination_type='webhook'` (padrão, comportamento herdado) exige
    `destination_url`+`webhook_secret`. `destination_type='contact'` (novo,
    ver ADR-009) exige `contact_id` — mutuamente exclusivo com webhook.
    """

    name: str = Field(..., min_length=1, max_length=255, description="Nome da regra")
    event_type_pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Padrão fnmatch: 'alpr.*', 'analytics.intrusion.*', '*'",
        examples=["alpr.*", "analytics.intrusion.*", "*"],
    )
    destination_type: str = Field(default="webhook", pattern="^(webhook|contact)$")
    destination_url: AnyHttpUrl | None = Field(
        default=None, description="Obrigatório se destination_type=webhook"
    )
    webhook_secret: str | None = Field(
        default=None, min_length=16,
        description="Chave secreta HMAC-SHA256 (mín. 16 chars) — obrigatório se destination_type=webhook",
    )
    contact_id: str | None = Field(
        default=None, description="Obrigatório se destination_type=contact"
    )
    channel: str = Field(default="whatsapp", pattern="^whatsapp$")


class RuleResponse(BaseModel):
    """Resposta com dados de uma regra de notificação."""

    id: str
    name: str
    event_type_pattern: str
    destination_type: str
    destination_url: str | None
    contact_id: str | None
    channel: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("destination_url", mode="before")
    @classmethod
    def coerce_url(cls, v: object) -> str | None:
        """Converte AnyHttpUrl para string na serialização."""
        return str(v) if v is not None else None


class LogResponse(BaseModel):
    """Resposta com dados de um log de dispatch."""

    id: str
    rule_id: str
    vms_event_id: str
    status: str
    response_code: int | None
    dispatched_at: datetime

    model_config = {"from_attributes": True}
