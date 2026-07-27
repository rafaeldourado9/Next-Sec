#!/bin/sh
set -e

WG_IFACE=wg0
CONF_DIR=/etc/wireguard
CONF_FILE="$CONF_DIR/${WG_IFACE}.conf"
mkdir -p "$CONF_DIR"
chmod 700 "$CONF_DIR"

WG_HUB_ADDRESS="${WG_HUB_ADDRESS:-10.60.0.1/24}"
WG_LISTEN_PORT="${WG_LISTEN_PORT:-51820}"
VMS_API_INTERNAL_URL="${VMS_API_INTERNAL_URL:-http://api:8000}"
MEDIAMTX_RTMP_INTERNAL="${MEDIAMTX_RTMP_INTERNAL:-mediamtx:1935}"

PRIVKEY_FILE="$CONF_DIR/hub_privatekey"

# Gera a chave do hub uma única vez — persiste no volume, reaproveitada entre
# restarts do container. Regenerar orfanaria todo peer já provisionado (a
# confiança do lado do agente é fixada na chave pública do hub).
if [ ! -f "$PRIVKEY_FILE" ]; then
    umask 077
    wg genkey > "$PRIVKEY_FILE"
fi
HUB_PRIVATE_KEY=$(cat "$PRIVKEY_FILE")
wg pubkey < "$PRIVKEY_FILE" > "$CONF_DIR/hub_publickey"
echo "[entrypoint] hub public key: $(cat "$CONF_DIR/hub_publickey")"

# wg0.conf sem [Peer] — peers são adicionados/removidos dinamicamente via
# `wg set` (API de controle), nunca escritos neste arquivo estático.
cat > "$CONF_FILE" <<EOF
[Interface]
PrivateKey = $HUB_PRIVATE_KEY
Address = $WG_HUB_ADDRESS
ListenPort = $WG_LISTEN_PORT
EOF
chmod 600 "$CONF_FILE"

wg-quick down "$WG_IFACE" 2>/dev/null || true
wg-quick up "$WG_IFACE"

HUB_IP="${WG_HUB_ADDRESS%%/*}"

# Encaminha só as duas portas necessárias, amarradas no IP do próprio wg0 —
# nunca 0.0.0.0. Isso é o que mantém o design "só encaminhamento": nenhum
# outro serviço/porta do docker network fica alcançável através do túnel.
API_HOST_PORT=$(echo "$VMS_API_INTERNAL_URL" | sed -E 's#^[a-z]+://##')
API_HOST=$(echo "$API_HOST_PORT" | cut -d: -f1)
API_PORT=$(echo "$API_HOST_PORT" | cut -d: -f2)
[ "$API_PORT" = "$API_HOST" ] && API_PORT=8000
RTMP_HOST=$(echo "$MEDIAMTX_RTMP_INTERNAL" | cut -d: -f1)
RTMP_PORT=$(echo "$MEDIAMTX_RTMP_INTERNAL" | cut -d: -f2)

echo "[entrypoint] forward ${HUB_IP}:${API_PORT} -> ${API_HOST}:${API_PORT}"
socat TCP-LISTEN:${API_PORT},bind=${HUB_IP},fork,reuseaddr TCP:${API_HOST}:${API_PORT} &
echo "[entrypoint] forward ${HUB_IP}:${RTMP_PORT} -> ${RTMP_HOST}:${RTMP_PORT}"
socat TCP-LISTEN:${RTMP_PORT},bind=${HUB_IP},fork,reuseaddr TCP:${RTMP_HOST}:${RTMP_PORT} &

export WG_IFACE

# Reconcilia peers a partir do Postgres (via API) — o wg0 recém-criado sobe
# sem peer nenhum; tenta algumas vezes já que a API pode ainda não estar de
# pé na primeira tentativa (mesmo com depends_on/healthcheck).
i=0
until python3 -c "from control_api import reconcile_from_api; reconcile_from_api()" 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 5 ]; then
        echo "[entrypoint] aviso: reconcile inicial falhou após 5 tentativas — a API de controle vai continuar disponível pra tentativas manuais/futuras"
        break
    fi
    echo "[entrypoint] reconcile falhou, tentando de novo em 3s (${i}/5)..."
    sleep 3
done

exec python3 /app/control_api.py
