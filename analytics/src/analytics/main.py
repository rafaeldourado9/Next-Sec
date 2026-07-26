"""Ponto de entrada do analytics_service — FastAPI app + lifespan."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from analytics.core.config import get_settings
from analytics.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

orchestrator = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Inicializa plugins, descobre câmeras e inicia captura."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    await orchestrator.load_plugins()
    logger.info(
        "Analytics service iniciado com %d plugins",
        len(orchestrator.plugins),
    )

    # Inicia captura — descobre câmeras via VMS API pública
    await orchestrator.start()

    yield

    await orchestrator.stop()
    logger.info("Analytics service encerrado")


class HealthResponse(BaseModel):
    """Resposta do health check."""

    status: str
    plugins_loaded: int
    plugin_names: list[str]


def create_app() -> FastAPI:
    """Factory da aplicação FastAPI do analytics_service."""
    application = FastAPI(
        title="VMS Analytics Service",
        description="Plugin-based video analytics — standalone, conecta ao VMS via API pública",
        version="2.0.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        """Status dos plugins carregados."""
        return HealthResponse(
            status="healthy",
            plugins_loaded=len(orchestrator.plugins),
            plugin_names=[p.name for p in orchestrator.plugins],
        )

    application.include_router(router)
    return application


app = create_app()
