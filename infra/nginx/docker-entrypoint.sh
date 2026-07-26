#!/bin/sh
set -e

echo "[nginx] Aguardando API ficar disponível..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://api:8000/api/v1/health 2>/dev/null || echo "000")
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "[nginx] API está saudável — iniciando Nginx"
        break
    fi
    echo "[nginx] API respondeu $HTTP_STATUS — aguardando ($((RETRY_COUNT + 1))/$MAX_RETRIES)"
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 3
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "[nginx] Timeout aguardando API — iniciando mesmo assim"
fi

exec nginx -g 'daemon off;'
