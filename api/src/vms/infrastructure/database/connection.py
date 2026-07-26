"""Configuração do SQLAlchemy async e gerenciamento de sessões."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from vms.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base para todos os modelos ORM."""

    pass


# Instâncias globais — inicializadas no lifespan da aplicação
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _pool_budget(workers: int) -> tuple[int, int]:
    """
    Calcula pool_size e max_overflow para não estourar max_connections do Postgres.

    Orçamento: 70 conexões para API (30 reservadas para worker + admin + migrations).
    Com N workers Uvicorn, cada processo recebe no máximo 70 // N conexões,
    limitado a 20 para não desperdiçar conexões em modo single-worker.
    """
    per_worker = min(20, max(7, 70 // workers))
    pool_size = max(5, int(per_worker * 0.6))
    max_overflow = per_worker - pool_size
    return pool_size, max_overflow


def create_engine(database_url: str | None = None, *, for_worker: bool = False) -> AsyncEngine:
    """Cria engine assíncrono com pool dimensionado para o número de processos.

    Use ``for_worker=True`` no ARQ worker para reservar um budget menor.
    """
    settings = get_settings()
    url = database_url or settings.database_url

    if for_worker:
        # Worker ARQ: processo único, jobs são async — 10 conexões são suficientes
        pool_size, max_overflow = 5, 5
    else:
        workers = int(os.getenv("WEB_CONCURRENCY", "1"))
        pool_size, max_overflow = _pool_budget(workers)

    logger.info(
        "DB pool: pool_size=%d max_overflow=%d (WEB_CONCURRENCY=%s, for_worker=%s)",
        pool_size,
        max_overflow,
        os.getenv("WEB_CONCURRENCY", "1"),
        for_worker,
    )

    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,   # descarta conexões ociosas após 30min
        pool_timeout=30,     # falha rápido se pool esgotado (evita hang silencioso)
        echo=settings.debug,
        connect_args={
            "server_settings": {
                "application_name": f"vms-{'worker' if for_worker else 'api'}-{os.getpid()}",
                "statement_timeout": "30000",   # 30s por query
            }
        },
    )


def init_db(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Inicializa a fábrica de sessões."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    return _session_factory


async def close_db() -> None:
    """Fecha a engine (chamado no shutdown da aplicação)."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retorna a fábrica de sessões. Lança erro se não inicializada."""
    if _session_factory is None:
        raise RuntimeError("Banco de dados não inicializado. Chame init_db() primeiro.")
    return _session_factory


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager para criar sessão com commit/rollback automático."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
