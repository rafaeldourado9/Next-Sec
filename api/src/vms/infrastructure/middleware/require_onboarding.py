"""Middleware: bloqueia tenant que ainda não completou onboarding (escolha de plano).

Se o tenant tem `onboarding_complete=False`, retorna 403 para todas as rotas
exceto:
- /auth/* (login, refresh token)
- /billing/plans (listar planos disponíveis)
- /billing/activate (escolher plano)
- /health (health check)
- /docs, /redoc, /openapi.json (documentação)
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from vms.iam.models import TenantModel

logger = logging.getLogger(__name__)

# Rotas que NÃO exigem onboarding completo
EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/token",
    "/api/v1/auth/refresh",
    "/api/v1/billing/activate",
    "/api/v1/billing/status",
    "/api/v1/lgpd/status",
}


class RequireOnboardingMiddleware(BaseHTTPMiddleware):
    """Bloqueia requests de tenants que não escolheram plano."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path

        # Rotas isentas
        if any(path.startswith(ep) for ep in EXEMPT_PATHS):
            return await call_next(request)

        # Webhooks externos não exigem onboarding
        if path.startswith("/webhooks") or path in ("/hik_pro_connect", "/intelbras_events", "/camera_events"):
            return await call_next(request)

        # Verificar se usuário está autenticado (tem Authorization header)
        auth = request.headers.get("Authorization")
        if not auth:
            return await call_next(request)  # Vai falhar no auth middleware depois

        # Extrair tenant_id do token (já decodificado pelo auth middleware)
        # O auth middleware seta request.state.claims
        claims = getattr(request.state, "claims", None)
        if not claims:
            return await call_next(request)  # Auth ainda não processou

        tenant_id = getattr(claims, "tenant_id", None)
        if not tenant_id:
            return await call_next(request)

        # Verificar onboarding
        from vms.infrastructure.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            stmt = select(TenantModel.onboarding_complete).where(TenantModel.id == tenant_id)
            onboarded = await session.scalar(stmt)

            if onboarded is False:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "error": "onboarding_required",
                        "message": "Escolha um plano para ativar sua conta.",
                        "redirect": "/onboarding",
                    },
                )

        return await call_next(request)
