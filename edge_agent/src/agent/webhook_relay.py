"""Relay de webhook local — recebe eventos de câmeras físicas na rede local
do cliente e repassa pro sistema central através do túnel WireGuard.

Por quê: câmeras ALPR físicas (Hikvision "Alarm Server", Intelbras ITSCAM/
ITCPUSH) só permitem configurar UM endereço de destino pro webhook — em
geral um IP:porta simples na própria rede local, sem suporte a domínio
público, HTTPS ou headers de autenticação customizados. Sem esse relay, uma
câmera atrás de CGNAT não tem como entregar seu evento pro sistema central.

Este listener escuta na LAN, traduz os paths "alias" (os mesmos que o nginx
já expõe pro caso de câmera com acesso direto à internet — ver
`infra/nginx/nginx.conf` e `api/src/vms/webhooks_public/router.py`) pros
paths reais `/webhooks/...`, e repassa a requisição pro `vms_api_url`
configurado (que já aponta pro IP do hub dentro do túnel quando o túnel
está ativo), preservando IP de origem via `X-Forwarded-For` — a resolução
de câmera do lado do servidor (`_get_real_ip`) já lê esse header.

Só stdlib (`http.server`) — mesmo padrão já usado no hub WireGuard
(`infra/wireguard/control_api.py`), mantém o build nativo leve sem puxar
aiohttp/starlette só pra isso.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

logger = logging.getLogger(__name__)

# Espelha as rotas "alias" (sem prefixo) que o nginx expõe hoje pra câmeras
# com acesso direto à internet — ver infra/nginx/nginx.conf. Câmeras físicas
# são configuradas com esses paths (documentado nos docstrings de
# api/src/vms/webhooks_public/router.py), nunca com o path /webhooks/ real.
_EXACT_ALIASES = {
    "/hik_pro_connect": "/webhooks/hik_pro_connect",
    "/Event": "/webhooks/Event",
    "/Event/notification/alertStream": "/webhooks/Event/notification/alertStream",
    "/ISAPI/Event/notification/alertStream": "/webhooks/ISAPI/Event/notification/alertStream",
    "/EventNotificationAlert": "/webhooks/EventNotificationAlert",
    "/intelbras_events": "/webhooks/intelbras_events",
    "/camera_events": "/webhooks/camera_events",
    "/NotificationInfo/TollgateInfo": "/webhooks/intelbras_events",
    "/NotificationInfo/KeepAlive": "/webhooks/intelbras_keepalive",
}
_PREFIX_ALIASES = {
    "/intelbras_events/": "/webhooks/intelbras_events/",
}
_HOP_BY_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


def _translate_path(path: str) -> str:
    """Traduz um path "alias" (o que a câmera manda) pro path real da API.

    Se já vier prefixado com `/webhooks/` (alguém configurou a câmera com o
    path real diretamente), repassa sem mudar nada.
    """
    path_only, _, query = path.partition("?")

    if path_only.startswith("/webhooks/"):
        translated = path_only
    elif path_only in _EXACT_ALIASES:
        translated = _EXACT_ALIASES[path_only]
    else:
        translated = path_only
        for prefix, target_prefix in _PREFIX_ALIASES.items():
            if path_only.startswith(prefix):
                translated = target_prefix + path_only[len(prefix):]
                break

    return f"{translated}?{query}" if query else translated


class WebhookRelay:
    """Escuta na LAN, repassa requisições pro sistema central através do túnel."""

    def __init__(self, vms_api_url: str, host: str, port: int) -> None:
        self._base_url = vms_api_url.rstrip("/")
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Sobe o listener numa thread separada — `http.server` é bloqueante
        por natureza, não dá pra rodar direto no event loop do agent."""
        self._loop = asyncio.get_running_loop()
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                relay._handle(self)

            def do_GET(self) -> None:
                relay._handle(self)

            def log_message(self, fmt: str, *args: object) -> None:
                logger.debug("webhook_relay: %s %s", self.address_string(), fmt % args)

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("WebhookRelay escutando em %s:%s", self._host, self._port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        """Chamado na thread do `http.server` — despacha o forward de volta
        pro event loop do agent (onde o httpx/asyncio já roda) via
        `run_coroutine_threadsafe`, e espera o resultado antes de responder
        a câmera (ela espera uma resposta síncrona)."""
        assert self._loop is not None
        length = int(handler.headers.get("Content-Length", 0))
        body = handler.rfile.read(length) if length else b""
        client_ip = handler.client_address[0]

        future = asyncio.run_coroutine_threadsafe(
            self._forward(handler.command, handler.path, dict(handler.headers), body, client_ip),
            self._loop,
        )
        try:
            status_code, response_body = future.result(timeout=15)
        except Exception:
            logger.exception("webhook_relay: falha ao repassar requisição de %s", client_ip)
            status_code, response_body = 502, b'{"detail":"relay failed"}'

        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_body)))
        handler.end_headers()
        handler.wfile.write(response_body)

    async def _forward(
        self, method: str, path: str, headers: dict[str, str], body: bytes, client_ip: str,
    ) -> tuple[int, bytes]:
        url = f"{self._base_url}{_translate_path(path)}"
        forward_headers = {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
        # A resolução de câmera do servidor já lê X-Forwarded-For antes de
        # cair pro IP de conexão direto (ver webhooks_public/router.py::
        # _get_real_ip) — preserva o IP real da câmera na LAN, não o do agent.
        forward_headers["X-Forwarded-For"] = client_ip

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(method, url, headers=forward_headers, content=body)
            return resp.status_code, resp.content
