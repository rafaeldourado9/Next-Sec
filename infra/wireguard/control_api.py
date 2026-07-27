"""API de controle interna do hub WireGuard.

Só stdlib de propósito — este container é o "hub" de rede, não faz sentido
puxar um framework HTTP pra uma superfície tão pequena (3 rotas). Nunca é
publicada no host (sem `ports:` no docker-compose pra esta porta) — só a API
principal (`vms/cameras/wireguard_client.py`) fala com ela, dentro da rede
Docker interna.

Rotas:
- GET    /health          — healthcheck do compose
- GET    /hub-info        — chave pública do hub (pra API incluir no bundle
  do agent — a chave é gerada aqui dentro no primeiro boot, a API principal
  não tem como saber esse valor sem perguntar)
- POST   /peers           - {"public_key", "tunnel_ip"} — adiciona/atualiza peer
- POST   /peers/remove    - {"public_key"} — remove peer (evita "/" da chave
  base64 quebrando um path DELETE /peers/{key})
- POST   /resync          - {"peers": [{"public_key","tunnel_ip"}, ...]} —
  reconcilia o estado vivo do wg0 pra bater exatamente com essa lista
  (usado no boot do container, já que o Postgres é a fonte de verdade, não
  o estado do container WireGuard).
"""
from __future__ import annotations

import hmac
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WG_IFACE = os.environ.get("WG_IFACE", "wg0")
CONTROL_TOKEN = os.environ.get("WG_CONTROL_TOKEN", "")
CONTROL_PORT = int(os.environ.get("WG_CONTROL_PORT", "8080"))
VMS_API_INTERNAL_URL = os.environ.get("VMS_API_INTERNAL_URL", "http://api:8000").rstrip("/")


def _run_wg(*args: str) -> None:
    subprocess.run(["wg", *args], check=True, capture_output=True, text=True)


def _add_peer(public_key: str, tunnel_ip: str) -> None:
    ip = tunnel_ip.split("/")[0]
    _run_wg("set", WG_IFACE, "peer", public_key, "allowed-ips", f"{ip}/32")


def _remove_peer(public_key: str) -> None:
    subprocess.run(
        ["wg", "set", WG_IFACE, "peer", public_key, "remove"],
        capture_output=True, text=True,
    )  # sem check=True — remover peer que não existe não é erro


def _current_peers() -> set[str]:
    """Chaves públicas atualmente configuradas no wg0 (`wg show <iface> peers`)."""
    result = subprocess.run(
        ["wg", "show", WG_IFACE, "peers"], check=True, capture_output=True, text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _resync(desired: list[dict]) -> None:
    desired_keys = {p["public_key"] for p in desired}
    for key in _current_peers() - desired_keys:
        _remove_peer(key)
    for peer in desired:
        _add_peer(peer["public_key"], peer["tunnel_ip"])


def reconcile_from_api() -> None:
    """Busca a lista completa de túneis ativos na API principal e reconcilia.

    Chamado no boot do entrypoint.sh — o container recém-criado sobe com o
    wg0 vazio (sem peers), então precisa puxar o estado real do Postgres
    (via API) em vez de assumir que não há nenhum agent provisionado ainda.
    """
    req = urllib.request.Request(
        f"{VMS_API_INTERNAL_URL}/api/v1/agents/internal/tunnels",
        headers={"Authorization": f"ApiKey {CONTROL_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        peers = json.loads(resp.read())
    _resync(peers)
    print(f"[control_api] reconcile inicial: {len(peers)} peer(s) aplicado(s)", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        expected = f"ApiKey {CONTROL_TOKEN}"
        return hmac.compare_digest(auth, expected)

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/hub-info":
            if not self._authorized():
                self._send_json(401, {"detail": "unauthorized"})
                return
            try:
                with open("/etc/wireguard/hub_publickey") as f:
                    public_key = f.read().strip()
            except OSError:
                self._send_json(503, {"detail": "hub key ainda não gerada"})
                return
            self._send_json(200, {
                "public_key": public_key,
                "endpoint": os.environ.get("WG_PUBLIC_ENDPOINT", ""),
            })
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if self.path != "/health" and not self._authorized():
            self._send_json(401, {"detail": "unauthorized"})
            return
        try:
            body = self._read_body()
            if self.path == "/peers":
                _add_peer(body["public_key"], body["tunnel_ip"])
                self._send_json(200, {"status": "ok"})
            elif self.path == "/peers/remove":
                _remove_peer(body["public_key"])
                self._send_json(200, {"status": "ok"})
            elif self.path == "/resync":
                _resync(body.get("peers", []))
                self._send_json(200, {"status": "ok", "count": len(body.get("peers", []))})
            else:
                self._send_json(404, {"detail": "not found"})
        except subprocess.CalledProcessError as exc:
            self._send_json(502, {"detail": f"wg command failed: {exc.stderr}"})
        except (KeyError, json.JSONDecodeError) as exc:
            self._send_json(400, {"detail": f"invalid request: {exc}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"[control_api] {self.address_string()} {format % args}", file=sys.stderr)


if __name__ == "__main__":
    if not CONTROL_TOKEN:
        print("[control_api] AVISO: WG_CONTROL_TOKEN vazio — API de controle sem autenticação real", file=sys.stderr)
    server = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Handler)
    print(f"[control_api] escutando em :{CONTROL_PORT}", file=sys.stderr)
    server.serve_forever()
