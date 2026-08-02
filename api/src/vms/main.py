"""Ponto de entrada da aplicação VMS API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from vms.infrastructure.config import get_settings
from vms.infrastructure.database import close_db, create_engine, init_db
from vms.infrastructure.exceptions import register_exception_handlers
from vms.infrastructure.logging import setup_logging
from vms.infrastructure.messaging import connect_event_bus, disconnect_event_bus
from vms.shared.api.rate_limit import limiter

logger = logging.getLogger(__name__)


async def _provision_mediamtx_paths() -> None:
    """Recria todos os paths de câmeras no MediaMTX após restart."""
    import asyncio
    from sqlalchemy import select
    from vms.cameras.domain import StreamProtocol
    from vms.cameras.mediamtx import MediaMTXClient
    from vms.cameras.models import CameraModel
    from vms.infrastructure.database import get_session_factory

    # Health check: espera MediaMTX estar pronto (max 30s)
    mt_client = MediaMTXClient()
    max_retries = 6
    retry_delay = 5  # 5 segundos entre tentativas

    for attempt in range(1, max_retries + 1):
        try:
            # Testa conexão com MediaMTX
            is_ready = await mt_client.health_check()
            if is_ready:
                logger.info("MediaMTX está pronto após %d tentativas", attempt)
                break
        except Exception:
            logger.warning("MediaMTX não respondendo, tentativa %d/%d", attempt, max_retries)

        if attempt < max_retries:
            logger.info("Aguardando %ds antes da próxima tentativa...", retry_delay)
            await asyncio.sleep(retry_delay)
    else:
        logger.error(
            "MediaMTX não ficou pronto após %d tentativas. Provisionamento cancelado.", max_retries
        )
        return

    try:
        factory = get_session_factory()
        async with factory() as session:
            # `agent_id.is_(None)`: câmera de agent é tratada no edge
            # (ADR-019 §1) — a VPS não puxa nem serve o stream dela, então
            # não há path a provisionar aqui. Sem este filtro, todo boot da
            # API recriava o path com source de LAN e reiniciava o loop de
            # `i/o timeout` no MediaMTX central.
            result = await session.execute(
                select(CameraModel).where(
                    CameraModel.is_active.is_(True),
                    CameraModel.agent_id.is_(None),
                )
            )
            cameras = result.scalars().all()

        if not cameras:
            logger.info("Nenhuma câmera ativa para provisionar")
            return

        provisioned = 0
        failed = 0

        for cam in cameras:
            try:
                # Determina source URL para pull automático
                source_url = ""
                if cam.stream_protocol in ("rtsp_pull", "onvif") and cam.rtsp_url:
                    source_url = cam.rtsp_url

                # Para RTMP_PUSH, criar path sem source (aceitar publisher)
                # Path usa stream_key para URL limpa: live/{stream_key}
                if cam.stream_protocol == "rtmp_push" and cam.rtmp_stream_key:
                    mediamtx_path = f"live/{cam.rtmp_stream_key}"
                else:
                    mediamtx_path = f"tenant-{cam.tenant_id}/cam-{cam.id}"

                # force=True: esse loop roda só uma vez no boot da API — seu
                # propósito é reconciliar o MediaMTX com o estado real do
                # banco (inclusive depois de um restart do MediaMTX, quando
                # a fonte RTSP real reconecta rápido e o path já aparece
                # "ready" antes deste loop rodar, o que faria o early-return
                # de add_path pular a config de gravação silenciosamente).
                ok = await mt_client.add_path(
                    mediamtx_path,
                    source_url=source_url,
                    recording_enabled=getattr(cam, "recording_enabled", False),
                    retention_days=cam.retention_days,
                    force=True,
                )
                if ok:
                    provisioned += 1
                    logger.debug("Path provisionado: %s", mediamtx_path)
                else:
                    failed += 1
                    logger.warning("Falha ao provisionar path: %s", mediamtx_path)
            except Exception as exc:
                failed += 1
                logger.error("Erro ao provisionar câmera %s: %s", cam.id, exc)

        logger.info(
            "MediaMTX provisionamento concluído: %d sucesso, %d falhas (total: %d câmeras)",
            provisioned,
            failed,
            len(cameras),
        )
    except Exception as exc:
        logger.error("Falha catastrófica ao provisionar paths do MediaMTX: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Inicializa e finaliza recursos da aplicação."""
    settings = get_settings()

    # Logging estruturado
    setup_logging()

    # Banco de dados
    engine = create_engine(settings.database_url)
    init_db(engine)
    logger.info("Banco de dados inicializado")

    # Redis
    redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
        max_connections=20,  # evita crescimento ilimitado por processo
        socket_keepalive=True,
        retry_on_timeout=True,
    )
    app.state.redis = redis_client

    # Pool Redis dedicado ao SSE — pubsub mantém a conexão presa pela vida
    # inteira da stream, então SSE nunca pode competir pelo mesmo pool usado
    # por login/refresh/publish (achado: reconexões de SSE saturavam o pool
    # de 20 conexões do redis_client principal, o que derrubava até rotas
    # sem relação nenhuma com SSE, como /auth/refresh e /auth/login).
    sse_redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
        max_connections=25,
        socket_keepalive=True,
        retry_on_timeout=True,
    )
    app.state.sse_redis = sse_redis_client
    # ARQ pool para enfileiramento de tasks (conexões separadas do app Redis)
    from arq import create_pool
    from arq.connections import RedisSettings as ArqRedisSettings

    app.state.arq_redis = await create_pool(
        ArqRedisSettings.from_dsn(settings.redis_url),
    )
    logger.info("Redis conectado")

    # Event Bus (Domain Events via Redis pub/sub)
    try:
        await connect_event_bus()
        from vms.infrastructure.messaging import event_registry
        from vms.infrastructure.messaging.event_handlers import (
            register_all_events,
            subscribe_all_handlers,
        )

        register_all_events(event_registry)
        await subscribe_all_handlers(
            app.state.event_bus if hasattr(app.state, "event_bus") else None
        )
    except Exception as exc:
        logger.warning("Event bus indisponível no startup: %s", exc)

    # MediaMTX — provisionar paths de todas as câmeras
    await _provision_mediamtx_paths()

    yield

    # Shutdown
    await redis_client.aclose()
    await sse_redis_client.aclose()
    await app.state.arq_redis.aclose()
    await disconnect_event_bus()
    await close_db()
    logger.info("Recursos encerrados")


def create_app() -> FastAPI:
    """Factory da aplicação FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title="VMS API",
        description="Video Management System — Multi-tenant",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # GZip — comprime respostas de listagem > 1 KB (−60% bandwidth em eventos/recordings)
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)

    # CORS
    origins = (
        ["*"]
        if not settings.is_production
        else settings.cors_origins.split(",")
        if settings.cors_origins
        else ["https://app.vms.io"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Correlation ID — request tracking e structured logging
    from vms.infrastructure.middleware.correlation_id import CorrelationIdMiddleware

    app.add_middleware(CorrelationIdMiddleware)

    # Require onboarding — bloqueia tenant sem licença ativada
    from vms.infrastructure.middleware.require_onboarding import RequireOnboardingMiddleware

    app.add_middleware(RequireOnboardingMiddleware)

    # Handlers de exceção de domínio
    register_exception_handlers(app)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Handler genérico para erros não tratados
    @app.exception_handler(Exception)
    async def handle_unhandled(_req: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erro não tratado: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error", "message": "Erro interno do servidor"},
        )

    _include_routers(app)
    return app


def _include_routers(app: FastAPI) -> None:
    """Registra todos os routers no app."""
    from vms.health.router import router as health_router
    from vms.iam.router import router as iam_router
    from vms.cameras.router import router as cameras_router
    from vms.cameras.isapi_router import router as isapi_router
    from vms.events.router import router as events_router
    from vms.recordings.router import router as recordings_router
    from vms.notifications.router import router as notifications_router
    from vms.sse.router import router as sse_router
    from vms.plugins.router import router as plugins_router
    from vms.webhooks_public.router import router as public_webhooks_router
    from vms.analytics.router import router as analytics_router
    from vms.audit.router import router as audit_router
    from vms.reports.router import router as reports_router
    from vms.lgpd.router import router as lgpd_router
    from vms.contacts.router import router as contacts_router
    from vms.watchlist.router import router as watchlist_router
    from vms.billing.router import router as billing_router
    from vms.whatsapp.router import router as whatsapp_router
    from vms.edge.router import router as edge_router

    # Health
    app.include_router(health_router, prefix="/api/v1")

    # Autenticação e gestão de usuários
    app.include_router(iam_router, prefix="/api/v1")

    # Recursos principais
    app.include_router(cameras_router, prefix="/api/v1")
    app.include_router(isapi_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(recordings_router, prefix="/api/v1")

    # Webhooks públicos (câmeras POSTam diretamente, sem auth)
    # Prefixo /webhooks → nginx location /webhooks/ já roteia para a API
    app.include_router(public_webhooks_router, prefix="/webhooks")

    # SSE
    app.include_router(sse_router, prefix="/api/v1")

    # Notificações
    app.include_router(notifications_router, prefix="/api/v1")

    # Contrato público de plugins externos
    app.include_router(plugins_router, prefix="/api/v1")

    # Edge — ativação por licença e ingestão em lote (ADR-018)
    app.include_router(edge_router, prefix="/api/v1")

    # Analytics — catálogo e eventos
    app.include_router(analytics_router, prefix="/api/v1")

    # Audit — audit trail
    app.include_router(audit_router, prefix="/api/v1")

    # Reports — relatórios assíncronos
    app.include_router(reports_router, prefix="/api/v1")

    # LGPD — compliance e proteção de dados
    app.include_router(lgpd_router, prefix="/api/v1")

    # Contatos — telefones que recebem alertas (Next Sec)
    app.include_router(contacts_router, prefix="/api/v1")

    # Watchlist — reconhecimento facial (Next Sec)
    app.include_router(watchlist_router, prefix="/api/v1")

    # Billing — licenciamento mínimo (status/ativação), exigido pelo LicenseGate
    app.include_router(billing_router, prefix="/api/v1")

    # WhatsApp — proxy de conexão com o Arcanum (QR/status), ver ADR-009
    app.include_router(whatsapp_router, prefix="/api/v1")

    # Admin Panel — franqueado (somente role admin)
    from vms.admin.router import router as admin_router
    app.include_router(admin_router, prefix="/api/v1")


app = create_app()
