"""Rotas HTTP do bounded context de câmeras e agents."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

logger = logging.getLogger(__name__)

# Futures de comandos agent->API pendentes de resposta, chaveados por
# request_id. Processo único (deploy tier micro, um container `api` só) —
# um dict em memória de processo é suficiente, não precisa de Redis/pubsub
# pra correlacionar a resposta (usa Redis só pra levar o comando até o
# agent, que é quem já está inscrito nesse canal via WS).
_pending_agent_requests: dict[str, asyncio.Future] = {}


async def _send_agent_command(agent_id: str, command: dict, timeout: float = 8.0) -> dict | None:
    """Publica um comando pro agent via o mesmo canal Redis do config push e
    aguarda a resposta correlacionada (request_id) vinda pelo WS. Usado para
    operações que só fazem sentido rodando dentro da LAN do cliente (probe/
    discover ONVIF) — a API na nuvem nunca alcança um IP de rede local
    atrás de CGNAT, então quem executa é o agent, que já está lá."""
    import uuid
    from vms.infrastructure.config import get_settings
    import redis.asyncio as aioredis

    request_id = str(uuid.uuid4())
    command = {**command, "request_id": request_id}

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _pending_agent_requests[request_id] = future
    try:
        settings = get_settings()
        redis_client = aioredis.from_url(settings.redis_url)
        try:
            await redis_client.publish(f"agent:{agent_id}:config", json.dumps(command))
        finally:
            await redis_client.aclose()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        _pending_agent_requests.pop(request_id, None)
from sqlalchemy.ext.asyncio import AsyncSession

from vms.cameras.repository import AgentRepository, AgentTunnelRepository, CameraRepository
from vms.cameras.schemas import (
    AgentConfigResponse,
    AgentResponse,
    AgentTunnelInternal,
    CameraConfigItem,
    CameraResponse,
    CreateAgentRequest,
    CreateAgentResponse,
    UpdateAgentRequest,
    CreateCameraRequest,
    DiscoverOnvifRequest,
    DiscoverOnvifResponse,
    DiscoveredCamera,
    HeartbeatRequest,
    OnvifProbeRequest,
    OnvifProbeResponse,
    RtmpConfigResponse,
    StreamUrlsResponse,
    UpdateCameraRequest,
)
from vms.cameras.ptz.router import router as ptz_router
from vms.cameras.service import AgentService, CameraService
from vms.cameras.wireguard_client import WireGuardHubClient
from vms.shared.api.dependencies import ApiKeyHeader, CurrentUser, DbSession, GestorUser
from vms.infrastructure.config import get_settings
from vms.infrastructure.middleware.audit_action import audit_action
from vms.iam.repository import ApiKeyRepository
from vms.iam.service import ApiKeyService

router = APIRouter()
router.include_router(ptz_router)


# ─── Factories ────────────────────────────────────────────────────────────────


def _camera_svc(db: AsyncSession) -> CameraService:
    """Constrói CameraService com repositório."""
    return CameraService(CameraRepository(db))


def _agent_svc(db: AsyncSession) -> AgentService:
    """Constrói AgentService com dependências, incluindo túnel WireGuard."""
    return AgentService(
        AgentRepository(db),
        CameraRepository(db),
        ApiKeyService(ApiKeyRepository(db)),
        AgentTunnelRepository(db),
        WireGuardHubClient(),
    )


def _verify_wg_control_token(request: Request) -> None:
    """Autenticação do hub WireGuard pro reconcile-on-boot — segredo
    compartilhado (`WG_CONTROL_TOKEN`), não JWT de usuário nem API key de
    agent (esse endpoint não pertence a nenhum tenant específico)."""
    import hmac

    auth = request.headers.get("Authorization", "")
    expected = f"ApiKey {get_settings().wg_control_token}"
    if not hmac.compare_digest(auth, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de controle inválido")


# ─── Câmeras ──────────────────────────────────────────────────────────────────


@router.get(
    "/cameras",
    response_model=list[CameraResponse],
    summary="Listar câmeras",
    tags=["cameras"],
)
async def list_cameras(
    claims: CurrentUser,
    db: DbSession,
    is_online: bool | None = None,
) -> list[CameraResponse]:
    """Lista câmeras do tenant autenticado."""
    svc = _camera_svc(db)
    cameras = await svc.list_cameras(claims.tenant_id, is_online=is_online)
    return [CameraResponse.model_validate(c) for c in cameras]


@router.post(
    "/cameras",
    response_model=CameraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar câmera",
    tags=["cameras"],
)
@audit_action("camera.created", resource_type="camera", name_param="body.name")
async def create_camera(
    body: CreateCameraRequest,
    claims: GestorUser,
    db: DbSession,
) -> CameraResponse:
    """Cria câmera (rtsp_pull, rtmp_push ou onvif) e registra path no MediaMTX."""
    svc = _camera_svc(db)
    camera = await svc.create_camera(
        tenant_id=claims.tenant_id,
        name=body.name,
        manufacturer=body.manufacturer,
        location=body.location,
        address=body.address,
        latitude=body.latitude,
        longitude=body.longitude,
        ia_enabled=body.ia_enabled,
        retention_days=body.retention_days,
        recording_enabled=body.recording_enabled,
        stream_quality=body.stream_quality,
        stream_protocol=body.stream_protocol,
        rtsp_url=body.rtsp_url,
        agent_id=body.agent_id,
        onvif_url=body.onvif_url,
        onvif_username=body.onvif_username,
        onvif_password=body.onvif_password,
        camera_type=body.camera_type,
    )
    return CameraResponse.model_validate(camera)


@router.get(
    "/cameras/{camera_id}",
    response_model=CameraResponse,
    summary="Buscar câmera",
    tags=["cameras"],
)
async def get_camera(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> CameraResponse:
    """Retorna câmera pelo ID."""
    svc = _camera_svc(db)
    camera = await svc.get_camera(camera_id, claims.tenant_id)
    return CameraResponse.model_validate(camera)


@router.patch(
    "/cameras/{camera_id}",
    response_model=CameraResponse,
    summary="Atualizar câmera",
    tags=["cameras"],
)
@audit_action("camera.updated", resource_type="camera", id_param="camera_id")
async def update_camera(
    camera_id: str,
    body: UpdateCameraRequest,
    claims: GestorUser,
    db: DbSession,
) -> CameraResponse:
    """Atualiza campos da câmera."""
    svc = _camera_svc(db)
    camera = await svc.update_camera(
        camera_id=camera_id,
        tenant_id=claims.tenant_id,
        name=body.name,
        rtsp_url=body.rtsp_url,
        onvif_url=body.onvif_url,
        onvif_username=body.onvif_username,
        onvif_password=body.onvif_password,
        manufacturer=body.manufacturer,
        location=body.location,
        address=body.address,
        latitude=body.latitude,
        longitude=body.longitude,
        ia_enabled=body.ia_enabled,
        retention_days=body.retention_days,
        recording_enabled=body.recording_enabled,
        stream_quality=body.stream_quality,
        agent_id=body.agent_id,
        is_active=body.is_active,
    )
    return CameraResponse.model_validate(camera)


@router.delete(
    "/cameras/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover câmera",
    tags=["cameras"],
)
@audit_action("camera.deleted", resource_type="camera", id_param="camera_id")
async def delete_camera(
    camera_id: str,
    claims: GestorUser,
    db: DbSession,
) -> None:
    """Remove câmera e seu path no MediaMTX (best-effort)."""
    svc = _camera_svc(db)
    await svc.delete_camera(camera_id, claims.tenant_id)


@router.get(
    "/cameras/{camera_id}/stream-urls",
    response_model=StreamUrlsResponse,
    summary="URLs de streaming",
    tags=["cameras"],
)
async def get_stream_urls(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
    request: Request,
) -> StreamUrlsResponse:
    """Retorna URLs HLS/WebRTC assinadas para um viewer."""
    from vms.iam.service import AuthService
    from vms.iam.repository import ApiKeyRepository as IamRepo
    from vms.shared.exceptions import NotFoundError

    try:
        # Gera viewer token via AuthService
        auth_svc = AuthService(user_repo=None, api_key_repo=IamRepo(db))  # type: ignore[arg-type]
        viewer_token = await auth_svc.issue_viewer_token(
            tenant_id=claims.tenant_id, camera_id=camera_id
        )

        svc = _camera_svc(db)
        # Usa o host da requisição para construir URLs corretas
        mediamtx_host = request.headers.get("X-MediaMTX-Host", request.url.hostname or "localhost")
        urls = await svc.get_stream_urls(camera_id, claims.tenant_id, viewer_token, mediamtx_host)
        return StreamUrlsResponse(
            hls_url=urls.hls_url,
            webrtc_url=urls.webrtc_url,
            rtsp_url=urls.rtsp_url,
            token=urls.token,
            expires_at=urls.expires_at,
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Câmera não encontrada",
        )
    except Exception as exc:
        logger.error("Erro ao gerar stream URLs: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Serviço de streaming temporariamente indisponível: {str(exc)}",
        )


@router.get(
    "/cameras/{camera_id}/rtmp-config",
    response_model=RtmpConfigResponse,
    summary="Configuração RTMP da câmera",
    tags=["cameras"],
)
async def get_rtmp_config(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
    request: Request,
) -> RtmpConfigResponse:
    """Retorna URL RTMP e stream key para câmeras com stream_protocol=rtmp_push."""
    from vms.shared.exceptions import NotFoundError

    svc = _camera_svc(db)
    camera = await svc.get_camera(camera_id, claims.tenant_id)

    if camera.stream_protocol != "rtmp_push" or not camera.rtmp_stream_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Câmera não está configurada como RTMP push",
        )

    from vms.infrastructure.config import get_settings

    settings = get_settings()
    # URL pública no formato padrão do mercado: {base}/live/{stream_key}.stream
    rtmp_url = f"{settings.rtmp_public_url}/live/{camera.rtmp_stream_key}.stream"
    return RtmpConfigResponse(rtmp_url=rtmp_url, stream_key=camera.rtmp_stream_key)


@router.get(
    "/cameras/{camera_id}/snapshot",
    summary="Snapshot da câmera",
    tags=["cameras"],
)
async def get_snapshot(
    camera_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> dict:
    """Retorna URL de snapshot da câmera (ONVIF) ou frame via ffmpeg."""
    from vms.cameras.snapshot import get_snapshot_url

    svc = _camera_svc(db)
    camera = await svc.get_camera(camera_id, claims.tenant_id)
    url = await get_snapshot_url(camera)
    return {"snapshot_url": url}


@router.get(
    "/cameras/{camera_id}/thumbnail",
    summary="Thumbnail da câmera (imagem JPEG)",
    tags=["cameras"],
    include_in_schema=False,
)
async def get_thumbnail(
    camera_id: str,
    db: DbSession,
    token: str | None = Query(default=None),
) -> Response:
    """
    Captura um frame do stream e retorna como imagem JPEG.

    Aceita token via query param (?token=...) para uso em <img src>.
    Usa ffmpeg para extrair frame do HLS/RTSP. Resultado cacheado por 30s.
    """
    from fastapi.responses import Response as FastResponse
    from vms.cameras.thumbnail import capture_thumbnail
    from vms.infrastructure.security import decode_token
    from jose import JWTError

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token obrigatório")
    try:
        payload = decode_token(token)
        tenant_id: str = payload["tenant_id"]
    except (JWTError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    svc = _camera_svc(db)
    camera = await svc.get_camera(camera_id, tenant_id)
    jpeg_bytes = await capture_thumbnail(camera)
    if not jpeg_bytes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail indisponível")
    return FastResponse(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=30",
        },
    )


@router.post(
    "/cameras/onvif-probe",
    response_model=OnvifProbeResponse,
    summary="Probe ONVIF",
    tags=["cameras"],
)
async def onvif_probe(
    body: OnvifProbeRequest,
    claims: CurrentUser,
    db: DbSession,
) -> OnvifProbeResponse:
    """Faz probe ONVIF e retorna capacidades da câmera.

    Se `agent_id` for informado, o probe roda no agent (dentro da LAN do
    cliente) — a API na nuvem nunca alcança um IP de rede local atrás de
    CGNAT (ver docs/ESTUDO_TECNICO_NEXT_SEC.md, seção 4)."""
    if body.agent_id:
        result_data = await _send_agent_command(body.agent_id, {
            "type": "onvif_probe_request",
            "onvif_url": body.onvif_url,
            "username": body.username,
            "password": body.password,
        })
        if result_data is None:
            return OnvifProbeResponse(reachable=False, error="Agent não respondeu (offline ou timeout)")
        return OnvifProbeResponse(
            reachable=result_data.get("reachable", False),
            manufacturer=result_data.get("manufacturer"),
            model=result_data.get("model"),
            rtsp_url=result_data.get("rtsp_url"),
            snapshot_url=result_data.get("snapshot_url"),
            error=result_data.get("error"),
        )

    svc = _camera_svc(db)
    result = await svc.onvif_probe(body.onvif_url, body.username, body.password)
    return OnvifProbeResponse(
        reachable=result.reachable,
        manufacturer=result.manufacturer,
        model=result.model,
        rtsp_url=result.rtsp_url,
        snapshot_url=result.snapshot_url,
        error=result.error,
    )


@router.post(
    "/cameras/discover",
    response_model=DiscoverOnvifResponse,
    summary="Descobrir câmeras ONVIF na rede",
    tags=["cameras"],
)
async def discover_cameras(
    body: DiscoverOnvifRequest,
    claims: CurrentUser,
    db: DbSession,
) -> DiscoverOnvifResponse:
    """WS-Discovery de câmeras ONVIF na rede local.

    Se `agent_id` for informado, o discovery roda no agent (dentro da LAN
    do cliente) — broadcast multicast não atravessa a internet, só faz
    sentido rodar de dentro da rede onde as câmeras estão."""
    start = time.monotonic()

    if body.agent_id:
        result_data = await _send_agent_command(
            body.agent_id,
            {"type": "onvif_discover_request", "timeout_seconds": body.timeout_seconds},
            timeout=body.timeout_seconds + 5.0,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        raw = (result_data or {}).get("cameras", [])
        cameras = [DiscoveredCamera(onvif_url=c["onvif_url"], ip=c["ip"]) for c in raw]
        return DiscoverOnvifResponse(cameras=cameras, duration_ms=duration_ms)

    from vms.cameras.onvif_client import OnvifClient

    raw = await OnvifClient.discover(timeout_seconds=body.timeout_seconds)
    duration_ms = int((time.monotonic() - start) * 1000)
    cameras = [DiscoveredCamera(onvif_url=c["onvif_url"], ip=c["ip"]) for c in raw]
    return DiscoverOnvifResponse(cameras=cameras, duration_ms=duration_ms)


# ─── Agents ───────────────────────────────────────────────────────────────────


@router.get(
    "/agents",
    response_model=list[AgentResponse],
    summary="Listar agents",
    tags=["agents"],
)
async def list_agents(
    claims: CurrentUser,
    db: DbSession,
) -> list[AgentResponse]:
    """Lista agents do tenant autenticado."""
    svc = _agent_svc(db)
    agents = await svc.list_agents(claims.tenant_id)
    return [AgentResponse.model_validate(a) for a in agents]


@router.post(
    "/agents",
    response_model=CreateAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar agent",
    tags=["agents"],
)
async def create_agent(
    body: CreateAgentRequest,
    claims: CurrentUser,
    db: DbSession,
) -> CreateAgentResponse:
    """Cria agent, emite API key e provisiona túnel WireGuard (tudo exibido
    uma única vez — a chave privada do túnel nunca é persistida)."""
    svc = _agent_svc(db)
    bundle = await svc.create_agent_with_tunnel(claims.tenant_id, body.name)
    # Commit explícito ANTES de montar a resposta — o peer no hub WireGuard
    # é um efeito colateral externo, não transacional com o Postgres. Um bug
    # na serialização da resposta (já aconteceu — ver is_active esquecido)
    # não pode fazer o rollback da sessão desfazer o agent/tunnel enquanto o
    # peer real já existe no hub, gerando um peer órfão sem registro no banco.
    await db.commit()
    agent = bundle.agent
    return CreateAgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        last_heartbeat_at=agent.last_heartbeat_at,
        version=agent.version,
        streams_running=agent.streams_running,
        streams_failed=agent.streams_failed,
        is_active=agent.is_active,
        created_at=agent.created_at,
        api_key=bundle.api_key,
        wg_private_key=bundle.wg_private_key,
        wg_public_key_hub=bundle.wg_public_key_hub,
        wg_endpoint=bundle.wg_endpoint,
        wg_tunnel_ip=bundle.wg_tunnel_ip,
        wg_allowed_ips=bundle.wg_allowed_ips,
    )


@router.get(
    "/agents/internal/tunnels",
    response_model=list[AgentTunnelInternal],
    summary="[interno] Lista de túneis ativos — reconcile do hub WireGuard",
    include_in_schema=False,
)
async def list_internal_tunnels(
    request: Request,
    db: DbSession,
) -> list[AgentTunnelInternal]:
    """Consumido só pelo container do hub WireGuard no boot, pra reconciliar
    seu wg0 (que sobe sem peer nenhum) contra o Postgres (fonte de verdade).
    Autenticado por segredo compartilhado, não por tenant/JWT — a lista
    cruza todos os tenants de propósito."""
    _verify_wg_control_token(request)
    svc = _agent_svc(db)
    tunnels = await svc.list_active_tunnels()
    return [AgentTunnelInternal(public_key=t.public_key, tunnel_ip=f"{t.tunnel_ip}/32") for t in tunnels]


@router.get(
    "/agents/me/config",
    response_model=AgentConfigResponse,
    summary="Configuração do agent autenticado",
    tags=["agents"],
)
async def get_agent_config(
    api_key: ApiKeyHeader,
    db: DbSession,
) -> AgentConfigResponse:
    """Retorna configuração de câmeras para o agent autenticado via API key."""
    from vms.iam.service import AuthService
    from vms.iam.repository import ApiKeyRepository as IamApiKeyRepo

    auth_svc = AuthService(
        user_repo=None,  # type: ignore[arg-type]
        api_key_repo=IamApiKeyRepo(db),
    )
    key_entity = await auth_svc.authenticate_api_key(api_key)
    svc = _agent_svc(db)
    agent, configs = await svc.get_agent_config(key_entity.owner_id, key_entity.tenant_id)
    return AgentConfigResponse(
        agent_id=agent.id,
        cameras=[
            CameraConfigItem(
                id=c.id,
                name=c.name,
                rtsp_url=c.rtsp_url,
                rtmp_push_url=c.rtmp_push_url,
                enabled=c.enabled,
            )
            for c in configs
        ],
    )


@router.post(
    "/agents/me/heartbeat",
    response_model=AgentResponse,
    summary="Heartbeat do agent autenticado",
    tags=["agents"],
)
async def agent_heartbeat(
    body: HeartbeatRequest,
    api_key: ApiKeyHeader,
    db: DbSession,
) -> AgentResponse:
    """Registra heartbeat do agent e atualiza status para online."""
    from vms.iam.service import AuthService
    from vms.iam.repository import ApiKeyRepository as IamApiKeyRepo

    auth_svc = AuthService(
        user_repo=None,  # type: ignore[arg-type]
        api_key_repo=IamApiKeyRepo(db),
    )
    key_entity = await auth_svc.authenticate_api_key(api_key)
    svc = _agent_svc(db)
    agent = await svc.register_heartbeat(
        agent_id=key_entity.owner_id,
        tenant_id=key_entity.tenant_id,
        version=body.version,
        streams_running=body.streams_running,
        streams_failed=body.streams_failed,
    )
    return AgentResponse.model_validate(agent)


@router.get(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    summary="Buscar agent",
    tags=["agents"],
)
async def get_agent(
    agent_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> AgentResponse:
    """Retorna agent pelo ID."""
    svc = _agent_svc(db)
    agent = await svc.get_agent(agent_id, claims.tenant_id)
    return AgentResponse.model_validate(agent)


@router.put(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    summary="Atualizar agent",
    tags=["agents"],
)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    claims: CurrentUser,
    db: DbSession,
) -> AgentResponse:
    """Atualiza nome e/ou status ativo do agent."""
    svc = _agent_svc(db)
    agent = await svc.update_agent(
        agent_id, claims.tenant_id, name=body.name, is_active=body.is_active
    )
    return AgentResponse.model_validate(agent)


@router.delete(
    "/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover agent",
    tags=["agents"],
)
async def delete_agent(
    agent_id: str,
    claims: CurrentUser,
    db: DbSession,
) -> None:
    """Remove agent e revoga sua API key."""
    svc = _agent_svc(db)
    await svc.delete_agent(agent_id, claims.tenant_id)


@router.websocket("/agents/me/ws")
async def agent_ws(
    websocket: WebSocket,
    api_key: str = Query(..., alias="api_key"),
    db: DbSession = None,  # type: ignore[assignment]
) -> None:
    """
    WebSocket persistente para config push imediato ao agent.

    Agent autentica com ?api_key=<key> na query string.
    Recebe mensagens: config_updated, camera_added, camera_removed, restart_stream.
    """
    from vms.infrastructure.database import get_session_factory
    from vms.infrastructure.config import get_settings
    import redis.asyncio as aioredis

    await websocket.accept()

    # Autentica API key
    try:
        factory = get_session_factory()
        async with factory() as session:
            from vms.iam.service import AuthService
            from vms.iam.repository import ApiKeyRepository as IamApiKeyRepo

            auth_svc = AuthService(
                user_repo=None,  # type: ignore[arg-type]
                api_key_repo=IamApiKeyRepo(session),
            )
            key_entity = await auth_svc.authenticate_api_key(api_key)
            agent_id = key_entity.owner_id
            tenant_id = key_entity.tenant_id
    except Exception:
        await websocket.close(code=4001, reason="API key inválida")
        return

    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url)
    channel = f"agent:{agent_id}:config"

    async with redis_client.pubsub() as pubsub:
        await pubsub.subscribe(channel)
        logger.info("Agent %s conectado via WebSocket (tenant=%s)", agent_id, tenant_id)

        async def _receive_ws() -> None:
            """Aguarda desconexão do client e roteia respostas de comando
            (onvif_probe_response/onvif_discover_response) pro future
            pendente correspondente — ver _send_agent_command."""
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    request_id = data.get("request_id")
                    future = _pending_agent_requests.get(request_id) if request_id else None
                    if future is not None and not future.done():
                        future.set_result(data)
            except WebSocketDisconnect:
                pass

        receive_task = asyncio.create_task(_receive_ws())

        try:
            while True:
                # Bug real achado testando um agente de verdade contra a VPS
                # (2026-08-02): sem `timeout=` aqui, `get_message` usa o
                # default de redis-py (0.0 = não-bloqueante) e retorna quase
                # instantâneo — o `asyncio.wait_for(..., timeout=30.0)` de
                # fora nunca chegava a esperar de verdade, e o loop girava
                # sem pausa nenhuma: 100% de um core por agente conectado.
                # Sob essa carga o scheduler do asyncio ficava injusto o
                # bastante pra atrasar o ping/pong do próprio WebSocket, e a
                # conexão caía em intervalos variáveis (visto em produção:
                # 6.9s, 35s, 436s — sem padrão fixo, como seria um timeout
                # explícito). Mesmo padrão já usado em `sse/router.py`:
                # passar `timeout=` direto pro `get_message` faz o redis-py
                # bloquear de verdade (via BRPOP interno), sem busy loop.
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message and message["type"] == "message":
                    # Bug real, causa-raiz das desconexões "aleatórias"
                    # observadas antes deste achado: este client Redis não
                    # usa `decode_responses=True`, então `message["data"]`
                    # vem em bytes — e `WebSocket.send_text` exige `str`.
                    # Toda publicação no canal (config push OU comando,
                    # como o onvif_probe_request usado no teste com câmera
                    # real) derrubava a conexão inteira aqui, silenciosamente
                    # do ponto de vista do agent (que nunca via nada chegar).
                    # Mesmo padrão de decode já usado em `sse/router.py`.
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(data)
                if receive_task.done():
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("Agent WS erro: %s", exc)
        finally:
            receive_task.cancel()
            await pubsub.unsubscribe(channel)
            await redis_client.aclose()
            logger.info("Agent %s desconectado do WebSocket", agent_id)
