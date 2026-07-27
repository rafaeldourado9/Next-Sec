"""Channel Adapter — canal de notificação ao contato (ADR-009).

Interface isolada do canal concreto: hoje só existe `WhatsAppArcanumAdapter`
(usa o gateway Arcanum, já pronto na raiz do workspace). Telegram/outro canal
pode ser adicionado depois como uma segunda implementação, sem tocar em quem
consome a interface.
"""
from __future__ import annotations

import base64
import logging
from typing import Protocol

import httpx

from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class ChannelAdapter(Protocol):
    """Canal de envio de notificação para um contato (telefone)."""

    async def send(
        self,
        *,
        destination: str,
        message: str,
        media_bytes: bytes | None = None,
        media_type: str = "image",
        mime_type: str = "image/jpeg",
    ) -> tuple[bool, int | None, str]:
        """Envia a notificação. Retorna (sucesso, status_code, corpo_da_resposta)."""
        ...


class WhatsAppArcanumAdapter:
    """Envia mensagens via Arcanum (gateway WhatsApp self-hosted, ver ADR-009)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.arcanum_base_url.rstrip("/")
        self._instance = settings.arcanum_instance_name
        self._client = client

    async def send(
        self,
        *,
        destination: str,
        message: str,
        media_bytes: bytes | None = None,
        media_type: str = "image",
        mime_type: str = "image/jpeg",
    ) -> tuple[bool, int | None, str]:
        """Envia texto (e mídia, se `media_bytes` for informado) via Arcanum.

        `destination` é o telefone em E.164 (ex: +5511999999999) — o Arcanum
        espera o número sem o `+` no path da API. Mídia vai em base64 no
        campo `media` — o Arcanum não busca URL (`SendMedia` recusa com
        "URL-based media send not supported" — achado em teste local: era
        por isso que nenhuma foto/vídeo de evento chegava, o adapter mandava
        uma URL de storage que o gateway simplesmente rejeitava).
        """
        phone = destination.lstrip("+")
        endpoint = "sendMedia" if media_bytes else "sendText"
        url = f"{self._base_url}/api/message/{endpoint}/{self._instance}"

        body: dict[str, object] = {"number": phone}
        if media_bytes:
            body.update({
                "mediatype": media_type,
                "mimetype": mime_type,
                "caption": message,
                "media": base64.b64encode(media_bytes).decode("ascii"),
            })
        else:
            body["text"] = message

        try:
            if self._client is not None:
                resp = await self._client.post(url, json=body, timeout=15.0)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=body)
            return resp.is_success, resp.status_code, resp.text[:500]
        except Exception as exc:
            logger.exception("Falha ao enviar mensagem via Arcanum para %s", destination)
            return False, None, str(exc)[:500]


def build_channel_adapter(channel: str, client: httpx.AsyncClient | None = None) -> ChannelAdapter:
    """Factory — seleciona o adapter ativo pelo nome do canal."""
    if channel == "whatsapp":
        return WhatsAppArcanumAdapter(client=client)
    raise ValueError(f"Canal '{channel}' desconhecido — implementações disponíveis: 'whatsapp'")
