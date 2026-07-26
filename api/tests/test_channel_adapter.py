"""Testes do ChannelAdapter (WhatsApp/Arcanum) — ver ADR-009."""
from __future__ import annotations

import httpx
import pytest

from vms.notifications.channel_adapter import WhatsAppArcanumAdapter, build_channel_adapter


def _client_with_response(status_code: int, body: str = "ok") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body, request=request)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://arcanum:3100")


class TestWhatsAppArcanumAdapter:
    async def test_send_text_success(self) -> None:
        client = _client_with_response(200)
        adapter = WhatsAppArcanumAdapter(client=client)
        success, status_code, body = await adapter.send(
            destination="+5511999999999", message="Alerta de intrusão"
        )
        assert success is True
        assert status_code == 200

    async def test_send_media_uses_sendmedia_endpoint(self) -> None:
        captured: dict[str, httpx.Request] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            return httpx.Response(200, text="ok", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://arcanum:3100")
        adapter = WhatsAppArcanumAdapter(client=client)
        await adapter.send(
            destination="+5511999999999", message="Veja o clipe", media_url="https://x.local/clip.mp4"
        )
        assert "sendMedia" in str(captured["request"].url)

    async def test_send_text_uses_sendtext_endpoint(self) -> None:
        captured: dict[str, httpx.Request] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            return httpx.Response(200, text="ok", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://arcanum:3100")
        adapter = WhatsAppArcanumAdapter(client=client)
        await adapter.send(destination="+5511999999999", message="Sem mídia")
        assert "sendText" in str(captured["request"].url)

    async def test_strips_plus_from_phone_number(self) -> None:
        captured: dict[str, httpx.Request] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            return httpx.Response(200, text="ok", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://arcanum:3100")
        adapter = WhatsAppArcanumAdapter(client=client)
        await adapter.send(destination="+5511999999999", message="Oi")
        assert b"5511999999999" in captured["request"].content
        assert b"+5511999999999" not in captured["request"].content

    async def test_failure_response_returns_success_false(self) -> None:
        client = _client_with_response(500, "internal error")
        adapter = WhatsAppArcanumAdapter(client=client)
        success, status_code, _ = await adapter.send(destination="+5511999999999", message="Oi")
        assert success is False
        assert status_code == 500

    async def test_network_error_returns_success_false_without_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://arcanum:3100")
        adapter = WhatsAppArcanumAdapter(client=client)
        success, status_code, _ = await adapter.send(destination="+5511999999999", message="Oi")
        assert success is False
        assert status_code is None


class TestBuildChannelAdapter:
    def test_whatsapp_returns_arcanum_adapter(self) -> None:
        adapter = build_channel_adapter("whatsapp")
        assert isinstance(adapter, WhatsAppArcanumAdapter)

    def test_unknown_channel_raises(self) -> None:
        with pytest.raises(ValueError):
            build_channel_adapter("telegram")
