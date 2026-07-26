FROM nginx:1.25-alpine

RUN apk add --no-cache curl

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

RUN mkdir -p /var/www/certbot /recordings /tmp/vod

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/api/v1/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
