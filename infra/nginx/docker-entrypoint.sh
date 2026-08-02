#!/bin/sh
set -e

# ── TLS (opcional) ────────────────────────────────────────────────────────────
# O bloco :443 vive num template renderizado aqui, e só se o certificado
# existir de fato. Deixá-lo fixo em nginx.conf criaria um impasse: emitir o
# certificado exige o desafio ACME servido pelo :80, mas o nginx nem subiria
# sem o arquivo que ainda não foi emitido. Assim o primeiro start serve só
# HTTP, o certbot roda, e o restart seguinte já sobe com HTTPS.
mkdir -p /etc/nginx/ssl
rm -f /etc/nginx/ssl/*.conf

DOMAIN="${DOMAIN:-localhost}"
CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

if [ -f "$CERT" ]; then
    echo "[nginx] Certificado encontrado para ${DOMAIN} — habilitando HTTPS"
    sed "s|\${DOMAIN}|${DOMAIN}|g" /etc/nginx/ssl-server.conf.template \
        > /etc/nginx/ssl/ssl-server.conf
else
    echo "[nginx] Sem certificado em ${CERT} — subindo só HTTP."
    echo "[nginx] Emita com certbot (ver docs/DEPLOY_VPS.md) e reinicie este container."
fi

echo "[nginx] Aguardando API ficar disponível..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if wget -q --spider http://api:8000/api/v1/health 2>/dev/null; then
        echo "[nginx] API está saudável — iniciando Nginx"
        break
    fi
    echo "[nginx] API ainda não respondeu 200 — aguardando ($((RETRY_COUNT + 1))/$MAX_RETRIES)"
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 3
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "[nginx] Timeout aguardando API — iniciando mesmo assim"
fi

exec nginx -g 'daemon off;'
