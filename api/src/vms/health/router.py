"""Endpoint de health check — sem autenticação."""
from __future__ import annotations

import logging

import aio_pika
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import func, select, text

from vms.infrastructure.config import get_settings
from vms.infrastructure.database import get_session_factory

logger = logging.getLogger(__name__)
router = APIRouter()

_VERSION = "1.0.0"


async def _check_db() -> str:
    """Verifica conectividade com o banco de dados."""
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.warning("Health check DB falhou: %s", exc)
        return f"error: {exc}"


async def _check_redis() -> str:
    """Verifica conectividade com o Redis."""
    try:
        settings = get_settings()
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception as exc:
        logger.warning("Health check Redis falhou: %s", exc)
        return f"error: {exc}"


async def _check_mediamtx() -> str:
    """Verifica conectividade com a API do MediaMTX."""
    try:
        settings = get_settings()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.mediamtx_api_url}/v3/config/global/get")
        return "ok" if resp.status_code == 200 else "degraded"
    except Exception as exc:
        logger.warning("Health check MediaMTX falhou: %s", exc)
        return "degraded"


async def _check_rabbitmq() -> str:
    """Verifica conectividade com o RabbitMQ."""
    try:
        settings = get_settings()
        connection = await aio_pika.connect(settings.rabbitmq_url, timeout=2)
        await connection.close()
        return "ok"
    except Exception as exc:
        logger.warning("Health check RabbitMQ falhou: %s", exc)
        return f"error: {exc}"


async def _camera_counts() -> tuple[int, int]:
    """Retorna (cameras_online, cameras_total) do banco."""
    try:
        from vms.cameras.models import CameraModel

        factory = get_session_factory()
        async with factory() as session:
            total = await session.scalar(select(func.count(CameraModel.id))) or 0
            online = await session.scalar(
                select(func.count(CameraModel.id)).where(CameraModel.is_online.is_(True))
            ) or 0
        return online, total
    except Exception as exc:
        logger.warning("Camera counts falhou: %s", exc)
        return 0, 0


async def _check_analytics() -> str:
    """Verifica se o Analytics Service está respondendo."""
    try:
        settings = get_settings()
        # Analytics service roda em porta separada (normalmente 9001)
        analytics_url = getattr(settings, "analytics_url", "http://analytics:9001/health")
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(analytics_url)
        return "ok" if resp.status_code == 200 else "degraded"
    except Exception as exc:
        logger.warning("Health check Analytics falhou: %s", exc)
        return "degraded"


@router.get("/health", summary="Health check", tags=["health"])
async def health_check() -> dict:
    """
    Verifica saúde de todos os serviços dependentes.

    Retorna status agregado sem lançar exceção — degraded se algum serviço falhar.
    Não requer autenticação.
    """
    db_status = await _check_db()
    redis_status = await _check_redis()
    rabbitmq_status = await _check_rabbitmq()
    mediamtx_status = await _check_mediamtx()
    analytics_status = await _check_analytics()

    cameras_online, cameras_total = await _camera_counts()

    all_ok = all(
        s == "ok" for s in (db_status, redis_status, rabbitmq_status, mediamtx_status, analytics_status)
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "services": {
            "db": db_status,
            "redis": redis_status,
            "rabbitmq": rabbitmq_status,
            "mediamtx": mediamtx_status,
            "analytics": analytics_status,
        },
        "cameras_online": cameras_online,
        "cameras_total": cameras_total,
        "version": _VERSION,
    }


@router.get("/system/server-address", summary="Endereço público do servidor", tags=["health"])
async def server_address() -> dict:
    """
    Retorna a URL do túnel Cloudflare ativo (se disponível).

    A URL é escrita pelo container cloudflared em /tunnel/url quando um
    quick tunnel é estabelecido. Retorna null se o túnel não estiver ativo.
    Não requer autenticação.
    """
    tunnel_url: str | None = None
    try:
        from pathlib import Path
        p = Path("/tunnel/url")
        if p.exists():
            tunnel_url = p.read_text().strip() or None
    except Exception as exc:
        logger.debug("Leitura de /tunnel/url falhou: %s", exc)
    return {"tunnel_url": tunnel_url}


@router.get("/metrics", summary="Métricas básicas", tags=["health"])
async def metrics() -> dict:
    """
    Contadores básicos para monitoramento.

    Consulta DB para contagens rápidas. Sem autenticação para scraping.
    """
    try:
        from sqlalchemy import func, select
        from vms.cameras.models import CameraModel
        from vms.events.models import VmsEventModel
        from vms.iam.models import TenantModel, UserModel

        factory = get_session_factory()
        async with factory() as session:
            tenants = await session.scalar(select(func.count(TenantModel.id)))
            users = await session.scalar(select(func.count(UserModel.id)))
            cameras = await session.scalar(select(func.count(CameraModel.id)))
            cameras_online = await session.scalar(
                select(func.count(CameraModel.id)).where(CameraModel.is_online.is_(True))
            )
            events_total = await session.scalar(select(func.count(VmsEventModel.id)))

        return {
            "tenants": tenants or 0,
            "users": users or 0,
            "cameras_total": cameras or 0,
            "cameras_online": cameras_online or 0,
            "events_total": events_total or 0,
            "version": _VERSION,
        }
    except Exception as exc:
        logger.warning("Metrics falhou: %s", exc)
        return {"error": str(exc), "version": _VERSION}
