-- VMS MVP — PostgreSQL init
-- Executado uma única vez na criação do banco (docker-entrypoint-initdb.d)

-- ─── Extensões ───────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- busca trigrama (LIKE rápido em textos)
CREATE EXTENSION IF NOT EXISTS "btree_gin";      -- índices GIN em tipos escalares

-- ─── Configurações de performance ────────────────────────────────────────────

-- Aumenta work_mem para queries de analytics com GROUP BY / ORDER BY
ALTER SYSTEM SET work_mem = '16MB';

-- Log de queries lentas (> 1s) — útil em produção
ALTER SYSTEM SET log_min_duration_statement = '1000';

-- ─── Índices serão criados pelo Alembic após as migrations ───────────────────
-- Os índices críticos estão definidos nos models SQLAlchemy:
--   (tenant_id, camera_id) em vms_events, recording_segments, stream_sessions
--   (tenant_id, occurred_at) em vms_events
--   (tenant_id, is_online) em cameras
--   (prefix) em api_keys (lookup por prefixo)
--   (plate, camera_id) em vms_events (dedup ALPR)

-- ─── Health check table (usada pelo /health endpoint) ────────────────────────

-- Nenhuma tabela extra necessária — health check usa SELECT 1
