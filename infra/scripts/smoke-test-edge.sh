#!/usr/bin/env bash
# ─── Smoke test — docker-compose.edge.yml (Nível 1, ver ADR-016/017) ──────
# Sobe o stack de edge de verdade (redis + mediamtx + analytics + worker,
# SEM postgres/rabbitmq/api local — ver comentário no topo do compose) com
# valores dummy de VMS_API_URL/VMS_API_KEY (nenhum dos health checks depende
# de alcançar a VPS central de fato — ver analytics/src/analytics/main.py
# `/health`), espera todos ficarem healthy e falha se algum não subir.
#
# Uso: ./infra/scripts/smoke-test-edge.sh
# (roda a partir de qualquer diretório — resolve o repo root sozinho)
# ────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="docker-compose.edge.yml"
PROJECT_NAME="next_sec_edge_smoke"
# >150s (start_period do healthcheck do analytics, ver docker-compose.edge.yml)
# + margem pro pior caso do retry de descoberta de câmeras no startup.
TIMEOUT_SECONDS=240

export VMS_API_URL="http://10.60.0.1:8000"
export VMS_API_KEY="smoke-test-dummy-key"
export ANALYTICS_TARGET="cpu"

cleanup() {
    echo "[smoke-edge] Limpando (down -v)..."
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[smoke-edge] 1/3 — validando sintaxe do compose (docker compose config)..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" config --quiet

echo "[smoke-edge] 2/3 — subindo stack (redis, mediamtx, analytics, worker)..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --build

echo "[smoke-edge] 3/3 — aguardando health (timeout ${TIMEOUT_SECONDS}s)..."
deadline=$((SECONDS + TIMEOUT_SECONDS))
services="redis mediamtx analytics worker"

while true; do
    all_healthy=true
    for svc in $services; do
        cid=$(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps -q "$svc")
        if [ -z "$cid" ]; then
            all_healthy=false
            break
        fi
        status=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "unknown")
        if [ "$status" = "unhealthy" ]; then
            echo "[smoke-edge] FALHA — serviço '$svc' ficou unhealthy"
            docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs "$svc" | tail -50
            exit 1
        fi
        if [ "$status" != "healthy" ]; then
            all_healthy=false
        fi
    done

    if [ "$all_healthy" = true ]; then
        echo "[smoke-edge] OK — redis, mediamtx, analytics e worker todos healthy"
        exit 0
    fi

    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "[smoke-edge] FALHA — timeout esperando health"
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps
        for svc in $services; do
            echo "--- logs: $svc ---"
            docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs "$svc" | tail -30
        done
        exit 1
    fi

    sleep 5
done
