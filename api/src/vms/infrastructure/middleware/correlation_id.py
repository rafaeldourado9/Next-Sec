"""
Correlation ID Middleware — Request tracking and structured logging.

Generates a unique X-Request-ID for every request and injects it into
structlog context variables so all log lines include the request ID.

Also logs request method, path, status code, and duration in JSON format.

Usage:
    # In main.py
    from vms.infrastructure.middleware.correlation_id import CorrelationIdMiddleware
    app.add_middleware(CorrelationIdMiddleware)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware que gera correlation ID e loga requests automaticamente.

    Para cada request:
    1. Gera X-Request-ID (ou usa o header enviado)
    2. Bind no structlog contextvars
    3. Loga request start
    4. Executa handler
    5. Loga request end com status e duration
    6. Adiciona X-Request-ID no response header
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # 1. Gerar ou reutilizar correlation ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # 2. Bind no structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # 3. Log request start
        start_time = time.monotonic()
        logger.debug("Request started", extra={"request_id": request_id})

        # 4. Executar handler
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.exception(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise

        # 5. Log request end
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )

        # 6. Adicionar correlation ID no response
        response.headers["X-Request-ID"] = request_id
        return response
