FROM postgres:16-alpine

# Script de inicialização (cria extensões, schemas iniciais)
COPY init.sql /docker-entrypoint-initdb.d/init.sql

# Variáveis padrão de desenvolvimento — sobrescrever em produção via env
ENV POSTGRES_DB=vms \
    POSTGRES_USER=vms \
    POSTGRES_PASSWORD=vmsdev

# Porta padrão do PostgreSQL
EXPOSE 5432

HEALTHCHECK --interval=5s --timeout=5s --retries=10 \
    CMD pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} || exit 1
