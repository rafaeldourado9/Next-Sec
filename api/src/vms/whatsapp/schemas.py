"""Schemas Pydantic para o proxy de conexão WhatsApp (Arcanum)."""
from __future__ import annotations

from pydantic import BaseModel


class WhatsAppStatusResponse(BaseModel):
    """Estado da sessão WhatsApp do tenant."""

    connected: bool
    status: str


class WhatsAppQrResponse(BaseModel):
    """QR code para escanear e conectar o WhatsApp."""

    qr: str | None
    status: str
