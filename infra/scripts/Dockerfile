FROM postgres:16-alpine

# Instala ferramentas utilitárias
RUN apk add --no-cache bash gzip coreutils

# Copia scripts de manutenção
COPY backup_db.sh /usr/local/bin/backup_db.sh
RUN chmod +x /usr/local/bin/backup_db.sh

# Variáveis padrão (sobrescrever via env em produção)
ENV POSTGRES_HOST=postgres \
    POSTGRES_PORT=5432 \
    POSTGRES_DB=vms \
    POSTGRES_USER=vms \
    BACKUP_DIR=/backups \
    RETENTION_DAYS=7

# Volume para armazenar os backups
VOLUME ["/backups"]

# Container roda o script de backup e encerra
# Ideal para uso com `docker run` ou `docker compose run`
CMD ["backup_db.sh"]
