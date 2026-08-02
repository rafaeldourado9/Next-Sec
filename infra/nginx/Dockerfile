FROM nginx:1.25-alpine

# NOTA (Next Sec): apk add curl removido — o entrypoint usa wget (já vem na
# imagem base), evitando depender do repositório apk (achado durante teste
# local: dl-cdn.alpinelinux.org falhava por erro de certificado TLS neste
# ambiente). Ver .genesis/architecture/reuse-plan.md.
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
# Locations compartilhadas entre :80 e :443 — ver comentário no topo do arquivo.
COPY locations.conf /etc/nginx/locations.conf
# Bloco :443 renderizado pelo entrypoint só quando o certificado existir.
COPY ssl-server.conf.template /etc/nginx/ssl-server.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh && mkdir -p /etc/nginx/ssl

# /recordings e /tmp/vod removidos — gravação contínua/VOD fora do escopo
RUN mkdir -p /var/www/certbot

EXPOSE 80 443

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/api/v1/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
