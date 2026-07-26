"""Schemas Pydantic para o bounded context de notificações."""
from __future__ import annotations

from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


class CreateRuleRequest(BaseModel):
    """Payload para criação de regra de notificação."""

    name: str = Field(..., min_length=1, max_length=255, description="Nome da regra")
    event_type_pattern: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Padrão fnmatch: 'alpr.*', 'camera.*', '*'",
        examples=["alpr.*", "camera.offline", "*"],
    )
    destination_url: AnyHttpUrl = Field(..., description="URL destino do webhook")
    webhook_secret: str = Field(
        ...,
        min_length=16,
        description="Chave secreta para assinatura HMAC-SHA256 (mínimo 16 chars)",
    )


class RuleResponse(BaseModel):
    """Resposta com dados de uma regra de notificação."""

    id: str
    name: str
    event_type_pattern: str
    destination_url: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("destination_url", mode="before")
    @classmethod
    def coerce_url(cls, v: object) -> str:
        """Converte AnyHttpUrl para string na serialização."""
        return str(v)


class LogResponse(BaseModel):
    """Resposta com dados de um log de dispatch."""

    id: str
    rule_id: str
    vms_event_id: str
    status: str
    response_code: int | None
    dispatched_at: datetime

    model_config = {"from_attributes": True}
