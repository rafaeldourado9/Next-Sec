"""Rotas SSE — Server-Sent Events via Redis pub/sub."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from jose import JWTError

from vms.infrastructure.security import decode_token

logger = logging.getLogger(__name__)
router = APIRouter()

_SSE_MAX_CONNECTIONS = 30
_sse_active = 0


def _get_claims_from_token(token: str) -> dict:
    """Valida JWT e retorna claims."""
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise JWTError("Tipo de token inválido")
        return payload
    except (JWTError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        ) from exc


@router.get(
    "/sse",
    summary="Server-Sent Events em tempo real",
    tags=["sse"],
)
async def sse_stream(
    request: Request,
    token: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """
    Stream SSE filtrado por tenant do usuário autenticado.

    Autenticação via query string: `?token=<jwt>`.
    Escuta canal Redis `sse:{tenant_id}` e envia eventos ao cliente.
    """
    global _sse_active
    if _sse_active >= _SSE_MAX_CONNECTIONS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Limite de conexões SSE atingido. Tente novamente mais tarde.",
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token obrigatório para SSE",
        )

    claims = _get_claims_from_token(token)
    tenant_id = claims["tenant_id"]

    async def event_generator():
        """Gera eventos SSE via Redis pub/sub."""
        global _sse_active
        _sse_active += 1
        redis = request.app.state.redis
        channel_name = f"sse:{tenant_id}"

        pubsub = redis.pubsub()
        await pubsub.subscribe(channel_name)
        logger.info("SSE conectado: tenant=%s (ativas=%d)", tenant_id, _sse_active)

        try:
            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                else:
                    # Heartbeat para manter conexão viva
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(15)
        except asyncio.CancelledError:
            pass
        finally:
            _sse_active -= 1
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()
            logger.info("SSE desconectado: tenant=%s (ativas=%d)", tenant_id, _sse_active)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def publish_sse_event(
    redis, tenant_id: str, event_type: str, payload: dict
) -> None:
    """Publica evento no canal SSE do tenant via Redis pub/sub."""
    message = json.dumps({"event": event_type, "data": payload})
    await redis.publish(f"sse:{tenant_id}", message)
