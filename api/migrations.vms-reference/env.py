"""Configuração do Alembic para migrações async com SQLAlchemy."""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

# Importa todos os models para garantir que estão registrados no metadata
from vms.iam.models import TenantModel, UserModel, ApiKeyModel  # noqa: F401
from vms.cameras.models import CameraModel, AgentModel  # noqa: F401
from vms.events.models import VmsEventModel  # noqa: F401
from vms.recordings.models import RecordingSegmentModel, ClipModel  # noqa: F401
from vms.notifications.models import NotificationRuleModel, NotificationLogModel  # noqa: F401
from vms.streaming.models import StreamSessionModel  # noqa: F401
from vms.core.database import Base

# Objeto de configuração do Alembic com acesso ao alembic.ini
config = context.config

# Lê URL do banco da variável de ambiente (sobrescreve alembic.ini)
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    # Alembic usa URL síncrona — converte asyncpg → psycopg2
    config.set_main_option(
        "sqlalchemy.url",
        _db_url.replace("+asyncpg", "+psycopg2"),
    )

# Configura logging do alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata alvo para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Executa migrações no modo offline (sem conexão ativa).

    Gera SQL para aplicar manualmente ou inspecionar.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Executa migrações na conexão fornecida."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa migrações no modo online (com conexão ativa)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
