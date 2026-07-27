"""Ponto de entrada do analytics_service — FastAPI app + lifespan."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from analytics.core.config import get_settings
from analytics.core.face_search import search_faces
from analytics.core.frame_enhance import enhance_event_frame
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


class FaceSearchCandidate(BaseModel):
    """Evento candidato — precisa ter um snapshot já capturado."""

    event_id: str
    image_path: str


class FaceSearchRequest(BaseModel):
    """Busca facial sob demanda contra eventos já existentes."""

    reference_image_url: str
    candidates: list[FaceSearchCandidate]
    threshold: float = 0.5


class FaceSearchMatch(BaseModel):
    """Um evento onde o rosto de referência foi encontrado."""

    event_id: str
    similarity: float


class FaceSearchResponse(BaseModel):
    matches: list[FaceSearchMatch]


class EnhanceFrameRequest(BaseModel):
    """Melhoria de frame sob demanda ('Analisar Evento')."""

    image_path: str
    bbox: list[float] | None = None


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

    @router.post("/face-search", response_model=FaceSearchResponse, tags=["face-search"])
    async def face_search(body: FaceSearchRequest) -> FaceSearchResponse:
        """Busca sob demanda: compara um rosto de referência contra snapshots de eventos.

        Chamado internamente pela API (POST /watchlist/{id}/search) — não é
        exposto ao frontend diretamente.
        """
        matches = await search_faces(
            reference_image_url=body.reference_image_url,
            candidates=[c.model_dump() for c in body.candidates],
            threshold=body.threshold,
        )
        return FaceSearchResponse(matches=[FaceSearchMatch(**m) for m in matches])

    @router.post("/enhance-frame", tags=["face-search"])
    async def enhance_frame(body: EnhanceFrameRequest) -> Response:
        """Aplica super-resolução (GFPGAN/EDSR) no snapshot de um evento.

        Chamado internamente pela API (POST /analytics/events/{id}/enhance).
        GFPGAN é CPU-bound e pode levar dezenas de segundos — roda em thread
        separada pra não travar o event loop (que também processa a captura
        contínua das câmeras nesse mesmo processo).
        """
        png_bytes = await asyncio.to_thread(enhance_event_frame, body.image_path, body.bbox)
        if png_bytes is None:
            raise HTTPException(status_code=422, detail="Não foi possível melhorar o frame")
        return Response(content=png_bytes, media_type="image/png")

    application.include_router(router)
    return application


app = create_app()
