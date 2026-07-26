#!/usr/bin/env bash
# ─── VMS PostgreSQL Backup Script ───────────────────────────────────────
# Uso: ./backup_db.sh
# Env vars: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, BACKUP_DIR
# Recomendado: rodar via cron diariamente
#   0 2 * * * /opt/vms/infra/scripts/backup_db.sh >> /var/log/vms/backup.log 2>&1
# ────────────────────────────────────────────────────────────────────────

set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-vms}"
POSTGRES_USER="${POSTGRES_USER:-vms}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

echo "[$(date -Iseconds)] Iniciando backup do banco ${POSTGRES_DB}..."

# Garante que o diretório de backup existe
mkdir -p "${BACKUP_DIR}"

# Faz dump compactado
pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-owner \
    --no-acl \
    --format=plain \
    | gzip > "${BACKUP_FILE}"

FILESIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date -Iseconds)] Backup concluído: ${BACKUP_FILE} (${FILESIZE})"

# Limpa backups antigos
DELETED=$(find "${BACKUP_DIR}" -name "${POSTGRES_DB}_*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete -print | wc -l)
if [ "${DELETED}" -gt 0 ]; then
    echo "[$(date -Iseconds)] Removidos ${DELETED} backups com mais de ${RETENTION_DAYS} dias"
fi

echo "[$(date -Iseconds)] Backup completo"
