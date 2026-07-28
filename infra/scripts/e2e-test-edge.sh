#!/usr/bin/env bash
# ─── E2E — worker de edge gera um clipe real via ffmpeg (Nível 1) ─────────
# Cobre o que o smoke test (smoke-test-edge.sh) não cobre: aqui a stack
# fica de pé de verdade (docker-compose.edge.yml) e um evento real
# atravessa o caminho inteiro do protocolo de sync (ver ADR-017 §1):
#
#   1. um JPEG real é escrito no volume compartilhado /snapshots
#   2. o job ARQ `task_render_and_upload_edge_clip` é enfileirado no Redis
#      da stack — o MESMO caminho que `VMSClient._enqueue_local_clip_task`
#      usa depois de um `ingest_event` confirmado (não simulamos o
#      analytics inteiro, só o ponto de entrada real da fila)
#   3. o worker de edge (EdgeWorkerSettings) pega o job, roda ffmpeg de
#      VERDADE (mesmo binário/imagem de produção) e faz o PUT do MP4
#   4. um mock mínimo da VPS central recebe o PUT e grava o corpo — o teste
#      confirma que o payload recebido é um MP4 real (assinatura "ftyp")
#
# Só a VPS central é mockada (fronteira correta — mesmo padrão do S4-05:
# "mock apenas do Arcanum, MinIO real via container"). Tudo mais
# (Redis, ffmpeg, rede Docker, o worker de produção) é real.
#
# Os scripts auxiliares (mock da VPS, enqueue do job) são passados via
# variável de ambiente (base64) e executados por `python -` (stdin), em
# vez de bind mount de arquivo do host — Git Bash/MSYS no Windows reescreve
# incorretamente paths de container dentro de flags `-v` (`/foo` vira
# `C:\...\foo`), então bind mount de arquivo avulso não é confiável aqui;
# stdin/env não tem esse problema e funciona igual em Linux/macOS.
#
# Uso: ./infra/scripts/e2e-test-edge.sh
# ────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="docker-compose.edge.yml"
PROJECT_NAME="next_sec_edge_e2e"
NETWORK_NAME="${PROJECT_NAME}_next_sec_edge"
SNAPSHOTS_VOLUME="${PROJECT_NAME}_snapshots"
WORKER_IMAGE="${PROJECT_NAME}-worker"
MOCK_CONTAINER="${PROJECT_NAME}-vps-mock"
EVENT_ID="e2e-test-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"

export VMS_API_URL="http://vps-mock:9000"
export VMS_API_KEY="e2e-test-dummy-key"
export ANALYTICS_TARGET="cpu"

cleanup() {
    echo "[e2e-edge] Limpando..."
    docker rm -f "$MOCK_CONTAINER" >/dev/null 2>&1 || true
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[e2e-edge] 1/6 — subindo stack (redis, mediamtx, analytics, worker)..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --build

echo "[e2e-edge] 2/6 — subindo mock da VPS central (recebe o PUT .../clip)..."
MOCK_SRC_B64=$(base64 <<'PYEOF' | tr -d '\n'
import http.server
import os

RECEIVED_DIR = "/received"
os.makedirs(RECEIVED_DIR, exist_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        parts = self.path.rstrip("/").split("/")
        event_id = parts[-2] if len(parts) >= 2 else "unknown"
        with open(f"{RECEIVED_DIR}/{event_id}.raw", "wb") as fh:
            fh.write(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"[]")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id": "mock-event-id"}')

    def log_message(self, fmt, *args):
        print("[vps-mock] " + (fmt % args), flush=True)


http.server.HTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
PYEOF
)

docker rm -f "$MOCK_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$MOCK_CONTAINER" \
    --network "$NETWORK_NAME" --network-alias vps-mock \
    -e MOCK_SRC_B64="$MOCK_SRC_B64" \
    python:3.12-slim sh -c 'echo "$MOCK_SRC_B64" | base64 -d | python -' >/dev/null
sleep 1
if [ "$(docker inspect --format='{{.State.Running}}' "$MOCK_CONTAINER" 2>/dev/null)" != "true" ]; then
    echo "[e2e-edge] FALHA — mock da VPS não subiu"
    docker logs "$MOCK_CONTAINER" 2>&1 | tail -20
    exit 1
fi

echo "[e2e-edge] 3/6 — aguardando stack ficar healthy..."
deadline=$((SECONDS + 240))
services="redis mediamtx analytics worker"
while true; do
    all_healthy=true
    for svc in $services; do
        cid=$(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps -q "$svc")
        status=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "unknown")
        [ "$status" = "unhealthy" ] && { echo "[e2e-edge] FALHA — '$svc' unhealthy"; docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs "$svc" | tail -40; exit 1; }
        [ "$status" != "healthy" ] && all_healthy=false
    done
    [ "$all_healthy" = true ] && break
    [ "$SECONDS" -ge "$deadline" ] && { echo "[e2e-edge] FALHA — timeout esperando health"; exit 1; }
    sleep 5
done
echo "[e2e-edge] stack healthy."

echo "[e2e-edge] 4/6 — escrevendo snapshot JPEG real no volume compartilhado..."
docker run --rm -v "${SNAPSHOTS_VOLUME}:/snapshots" "$WORKER_IMAGE" sh -c \
    "mkdir -p /snapshots/e2e-test && ffmpeg -y -f lavfi -i color=c=blue:s=320x240 -frames:v 1 -update 1 /snapshots/e2e-test/frame.jpg" \
    || { echo "[e2e-edge] FALHA — não gerou o snapshot de teste"; exit 1; }

echo "[e2e-edge] 5/6 — enfileirando task_render_and_upload_edge_clip (evento=$EVENT_ID)..."
ENQUEUE_SRC_B64=$(base64 <<PYEOF | tr -d '\n'
import asyncio
from arq import create_pool
from arq.connections import RedisSettings


async def main():
    pool = await create_pool(RedisSettings(host="redis", port=6379))
    await pool.enqueue_job(
        "task_render_and_upload_edge_clip", "$EVENT_ID", "/snapshots/e2e-test/frame.jpg"
    )
    await pool.close()


asyncio.run(main())
PYEOF
)
docker run --rm --network "$NETWORK_NAME" -e ENQUEUE_SRC_B64="$ENQUEUE_SRC_B64" "$WORKER_IMAGE" \
    sh -c 'echo "$ENQUEUE_SRC_B64" | base64 -d | python -'

echo "[e2e-edge] 6/6 — aguardando o worker renderizar (ffmpeg) e enviar o clipe pro mock..."
deadline=$((SECONDS + 60))
while true; do
    if docker exec "$MOCK_CONTAINER" sh -c "test -s /received/${EVENT_ID}.raw" 2>/dev/null; then
        break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "[e2e-edge] FALHA — timeout esperando o clipe chegar no mock da VPS"
        echo "--- logs: worker ---"
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs worker | tail -60
        echo "--- logs: vps-mock ---"
        docker logs "$MOCK_CONTAINER" | tail -20
        exit 1
    fi
    sleep 2
done

if docker exec "$MOCK_CONTAINER" sh -c "grep -qa ftyp /received/${EVENT_ID}.raw"; then
    size=$(docker exec "$MOCK_CONTAINER" sh -c "wc -c < /received/${EVENT_ID}.raw" | tr -d ' \r')
    echo "[e2e-edge] OK — clipe MP4 real recebido pelo mock da VPS (${size} bytes, assinatura ftyp confirmada)"
    exit 0
else
    echo "[e2e-edge] FALHA — corpo recebido não parece um MP4 válido (sem 'ftyp')"
    exit 1
fi
