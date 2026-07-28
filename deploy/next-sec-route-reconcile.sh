#!/usr/bin/env bash
# next-sec-route-reconcile.sh
# Reaplica a rota HTTP(S) do Next Sec no nginx do FastOS caso ela caia
# (ex.: apos recriar/redeployar o fastos-prod-nginx, que zera as mudancas
# efemeras). Idempotente: so age quando o health publico != 200.
# Nao ha cron configurado para este script ainda (nem para o civix,
# que nao tem um script equivalente no servidor) - rodar manualmente ou
# agendar via cron/systemd timer quando for produzir a automacao real.
set -u
HOST="vm-server.duckdns.org"
NGINX="fastos-prod-nginx-1"
NET="next_sec_edge"
VHOST_SRC="/opt/next_sec/deploy/next-sec-prod-vhost.conf"
SSLCONF="/etc/nginx/nginx-ssl.conf"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://${HOST}/api/v1/health/" 2>/dev/null || echo 000)
if [ "$code" = "200" ]; then exit 0; fi
echo "$(date -Is) rota Next Sec down (health=$code) -> reaplicando"

docker inspect "$NGINX" >/dev/null 2>&1 || { echo "  $NGINX inexistente, abortando"; exit 1; }

docker network connect "$NET" "$NGINX" 2>/dev/null && echo "  conectado a $NET"

tmp="/tmp/nextsec-ssl.$$"; tmp2="/tmp/nextsec-ssl2.$$"
docker cp "${NGINX}:${SSLCONF}" "$tmp" 2>/dev/null
if [ -f "$tmp" ]; then
  grep -vF 'include /etc/nginx/conf.d/*.conf;' "$tmp" > "$tmp2"
  awk 'NR==FNR{ if($0 ~ /^[[:space:]]*}[[:space:]]*$/) last=FNR; next } { if(FNR==last) print "    include /etc/nginx/conf.d/*.conf;"; print }' "$tmp2" "$tmp2" > "$tmp"
  docker cp "$tmp" "${NGINX}:${SSLCONF}" && echo "  include conf.d normalizado (fim do http)"
fi
rm -f "$tmp" "$tmp2"

docker cp "$VHOST_SRC" "${NGINX}:/etc/nginx/conf.d/next-sec.conf" && echo "  next-sec.conf instalado"

docker run --rm -v fastos_letsencrypt_certs:/etc/letsencrypt alpine sh -c \
  'chmod 644 /etc/letsencrypt/archive/vm-server.duckdns.org/privkey*.pem 2>/dev/null || true'

if docker exec "$NGINX" nginx -t -c "$SSLCONF" 2>&1 | grep -q successful; then
  docker exec "$NGINX" nginx -s reload && echo "  reload OK"
else
  echo "  nginx -t FALHOU; nao recarregado:"; docker exec "$NGINX" nginx -t -c "$SSLCONF" 2>&1 | tail -3
fi
