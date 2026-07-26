"""Configuração de structured logging com structlog."""
from __future__ import annotations

import logging
import sys

import structlog

from vms.infrastructure.config.settings import get_settings


def setup_logging() -> None:
    """
    Configura structlog para logging estruturado.

    - Em produção: JSON puro (para parsing por ferramentas de log)
    - Em desenvolvimento: saída colorida legível
    """
    settings = get_settings()
    is_prod = settings.is_production

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_prod:
        # JSON em produção
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Colorido em desenvolvimento
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Silenciar loggers ruidosos
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "aio_pika"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
