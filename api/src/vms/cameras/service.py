"""Casos de uso do bounded context de câmeras e agents."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

from dataclasses import dataclass

from vms.cameras.domain import (
    Agent,
    AgentTunnel,
    Camera,
    CameraConfig,
    CameraManufacturer,
    OnvifProbeResult,
    StreamProtocol,
    StreamQuality,
    StreamUrls,
)
from vms.cameras.mediamtx import MediaMTXClient
from vms.cameras.repository import AgentRepositoryPort, AgentTunnelRepositoryPort, CameraRepositoryPort
from vms.cameras.wireguard_client import WireGuardHubClient
from vms.infrastructure.config import get_settings
from vms.infrastructure.security import generate_wg_keypair
from vms.shared.exceptions import NotFoundError, DuplicateError, BusinessRuleViolation, UnauthorizedError
from vms.iam.domain import ApiKeyOwnerType
from vms.iam.service import ApiKeyService


def _wg_subnet_prefix(subnet_cidr: str) -> str:
    """`"10.60.0.0/24"` -> `"10.60.0"` — os 3 primeiros octetos da subnet do
    túnel, usados pra montar o IP completo de cada agent (`{prefix}.{n}`)."""
    network_addr = subnet_cidr.split("/")[0]
    return ".".join(network_addr.split(".")[:3])


@dataclass
class AgentTunnelBundle:
    """Retorno de `create_agent_with_tunnel` — tudo que o agent precisa pra
    montar seu próprio `wg0.conf`. `wg_private_key` só existe aqui, nunca é
    persistida (mesmo contrato do `api_key` em texto puro)."""

    agent: Agent
    api_key: str
    wg_private_key: str
    wg_public_key_hub: str
    wg_endpoint: str
    wg_tunnel_ip: str
    wg_allowed_ips: str


class CameraService:
    """Casos de uso de gerenciamento de câmeras."""

    def __init__(
        self,
        camera_repo: CameraRepositoryPort,
        mediamtx: MediaMTXClient | None = None,
    ) -> None:
        self._cameras = camera_repo
        self._mediamtx = mediamtx or MediaMTXClient()

    async def create_camera(
        self,
        tenant_id: str,
        name: str,
        manufacturer: str = "generic",
        location: str | None = None,
        address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        ia_enabled: bool = False,
        retention_days: int = 7,
        recording_enabled: bool = False,
        stream_quality: StreamQuality = StreamQuality.HIGH,
        stream_protocol: StreamProtocol = StreamProtocol.RTSP_PULL,
        rtsp_url: str | None = None,
        agent_id: str | None = None,
        onvif_url: str | None = None,
        onvif_username: str | None = None,
        onvif_password: str | None = None,
        camera_type: str = "internal",
    ) -> Camera:
        """Cria câmera de acordo com o protocolo e registra no MediaMTX."""
        # Verifica unicidade apenas entre câmeras ativas
        existing_by_name = await self._cameras.get_by_name(name, tenant_id, only_active=True)
        if isinstance(existing_by_name, Camera):
            raise DuplicateError(f"Já existe uma câmera com o nome '{name}' neste tenant")

        if rtsp_url:
            existing_by_url = await self._cameras.get_by_rtsp_url(
                rtsp_url, tenant_id, only_active=True
            )
            if isinstance(existing_by_url, Camera):
                raise DuplicateError(
                    f"Já existe uma câmera com a URL RTSP '{rtsp_url[:50]}...' neste tenant"
                )

        rtmp_stream_key: str | None = None
        ptz_supported: bool = False

        if stream_protocol == StreamProtocol.RTMP_PUSH:
            rtmp_stream_key = Camera.generate_stream_key()
            agent_id = None  # rtmp_push não usa agent

        elif stream_protocol == StreamProtocol.ONVIF:
            if not onvif_url:
                raise DuplicateError("onvif_url é obrigatório para protocolo ONVIF")
            # Se rtsp_url não foi fornecida, tenta extrair via probe
            if not rtsp_url:
                from vms.cameras.onvif_client import OnvifClient
                from vms.cameras.ptz.client import PtzClient

                probe = await OnvifClient.probe(
                    onvif_url, onvif_username or "", onvif_password or ""
                )
                if not probe.reachable or not probe.rtsp_url:
                    # NOTA (Next Sec): antes disso, uma falha de probe aqui deixava a
                    # câmera ser criada mesmo assim, com rtsp_url vazio — o MediaMTX
                    # nunca recebia frame e a tela ficava presa em "Aguardando
                    # primeiro frame" sem nenhum erro visível (achado durante teste
                    # local com câmera real).
                    raise BusinessRuleViolation(
                        probe.error or "Não foi possível obter a URL RTSP via ONVIF",
                        details={"onvif_url": onvif_url},
                    )
                rtsp_url = probe.rtsp_url
                if probe.manufacturer and probe.manufacturer != "unknown":
                    manufacturer = probe.manufacturer.lower()
                ptz_supported = await PtzClient.check_ptz_supported(
                    onvif_url, onvif_username or "", onvif_password or ""
                )

        camera = Camera(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            manufacturer=manufacturer
            if manufacturer
            in (
                CameraManufacturer.HIKVISION,
                CameraManufacturer.INTELBRAS,
                CameraManufacturer.DAHUA,
                CameraManufacturer.GENERIC,
            )
            else CameraManufacturer.GENERIC,
            stream_protocol=stream_protocol,
            rtsp_url=rtsp_url,
            rtmp_stream_key=rtmp_stream_key,
            onvif_url=onvif_url,
            onvif_username=onvif_username,
            onvif_password=onvif_password,
            location=location,
            address=address,
            latitude=latitude,
            longitude=longitude,
            ia_enabled=ia_enabled,
            retention_days=retention_days,
            recording_enabled=recording_enabled,
            stream_quality=stream_quality,
            agent_id=agent_id,
            ptz_supported=ptz_supported,
            # ISAPI
            isapi_enabled=False,
            camera_type=camera_type,
        )
        saved = await self._cameras.create(camera)
        # Registra path no MediaMTX com source URL se houver RTSP
        source_url = (
            saved.rtsp_url
            if saved.stream_protocol in (StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF)
            else ""
        )
        await self._mediamtx.add_path(
            saved.mediamtx_path,
            source_url=source_url,
            recording_enabled=saved.recording_enabled,
            retention_days=saved.retention_days,
        )
        if saved.agent_id:
            await _notify_agent(saved.agent_id, "camera_added", {"camera_id": saved.id})
        return saved

    async def get_camera(self, camera_id: str, tenant_id: str) -> Camera:
        """Retorna câmera por ID. Lança NotFoundError se não encontrada."""
        camera = await self._cameras.get_by_id(camera_id, tenant_id)
        if not camera:
            raise NotFoundError("Câmera", camera_id)
        return camera

    async def list_cameras(self, tenant_id: str, is_online: bool | None = None) -> list[Camera]:
        """Lista câmeras do tenant, opcionalmente filtrando por status online."""
        return await self._cameras.list_by_tenant(tenant_id, is_online=is_online)

    async def update_camera(
        self,
        camera_id: str,
        tenant_id: str,
        name: str | None = None,
        rtsp_url: str | None = None,
        onvif_url: str | None = None,
        onvif_username: str | None = None,
        onvif_password: str | None = None,
        manufacturer: str | None = None,
        location: str | None = None,
        address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        ia_enabled: bool | None = None,
        retention_days: int | None = None,
        recording_enabled: bool | None = None,
        stream_quality: StreamQuality | None = None,
        agent_id: str | None = None,
        is_active: bool | None = None,
        # ISAPI
        isapi_enabled: bool | None = None,
        isapi_base_url: str | None = None,
        isapi_username: str | None = None,
        isapi_password: str | None = None,
    ) -> Camera:
        """Atualiza campos fornecidos da câmera."""
        camera = await self.get_camera(camera_id, tenant_id)
        # Reprovisiona o path no MediaMTX (edit/add mesmo se já ativo) só
        # quando um campo que afeta a config de gravação de fato muda — ver
        # MediaMTXClient.add_path(force=...). Reprovisionar sempre a cada
        # update seria inofensivo mas desnecessário; o importante é NUNCA
        # deixar de reprovisionar quando o usuário liga/desliga a gravação.
        recording_config_changed = (
            (retention_days is not None and retention_days != camera.retention_days)
            or (recording_enabled is not None and recording_enabled != camera.recording_enabled)
        )

        # Validações de unicidade se nome ou rtsp_url estão sendo alterados
        if name is not None and name != camera.name:
            existing_by_name = await self._cameras.get_by_name(name, tenant_id, only_active=False)
            if isinstance(existing_by_name, Camera):
                raise DuplicateError(f"Já existe uma câmera com o nome '{name}' neste tenant")
            camera.name = name

        if rtsp_url is not None and rtsp_url != camera.rtsp_url:
            existing_by_url = await self._cameras.get_by_rtsp_url(
                rtsp_url, tenant_id, only_active=False
            )
            if isinstance(existing_by_url, Camera):
                raise DuplicateError(
                    f"Já existe uma câmera com a URL RTSP '{rtsp_url[:50]}...' neste tenant"
                )
            camera.rtsp_url = rtsp_url

        if onvif_url is not None:
            camera.onvif_url = onvif_url
        if onvif_username is not None:
            camera.onvif_username = onvif_username
        if onvif_password is not None:
            camera.onvif_password = onvif_password
        if manufacturer is not None:
            camera.manufacturer = (
                manufacturer
                if manufacturer
                in (
                    CameraManufacturer.HIKVISION,
                    CameraManufacturer.INTELBRAS,
                    CameraManufacturer.DAHUA,
                    CameraManufacturer.GENERIC,
                )
                else CameraManufacturer.GENERIC
            )
        if location is not None:
            camera.location = location
        if address is not None:
            camera.address = address
        if latitude is not None:
            camera.latitude = latitude
        if longitude is not None:
            camera.longitude = longitude
        if ia_enabled is not None:
            camera.ia_enabled = ia_enabled
        if retention_days is not None:
            camera.retention_days = retention_days
        if recording_enabled is not None:
            camera.recording_enabled = recording_enabled
        if stream_quality is not None:
            camera.stream_quality = stream_quality
        if agent_id is not None:
            camera.agent_id = agent_id
        if is_active is not None:
            camera.is_active = is_active

        # ISAPI
        if isapi_enabled is not None:
            camera.isapi_enabled = isapi_enabled
        if isapi_base_url is not None:
            camera.isapi_base_url = isapi_base_url
        if isapi_username is not None:
            camera.isapi_username = isapi_username
        if isapi_password is not None:
            camera.isapi_password = isapi_password

        updated = await self._cameras.update(camera)

        # Re-provision MediaMTX path se RTSP URL mudou, ou se algo que afeta
        # a config de gravação mudou (force=True — ver docstring de add_path).
        if rtsp_url is not None or recording_config_changed:
            source_url = (
                updated.rtsp_url
                if updated.stream_protocol in (StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF)
                else ""
            )
            await self._mediamtx.add_path(
                updated.mediamtx_path,
                source_url=source_url,
                recording_enabled=updated.recording_enabled,
                retention_days=updated.retention_days,
                force=recording_config_changed,
            )

        if updated.agent_id:
            await _notify_agent(updated.agent_id, "config_updated", {"camera_id": updated.id})
        return updated

    async def delete_camera(self, camera_id: str, tenant_id: str) -> None:
        """Remove câmera. Best-effort: não falha se MediaMTX inacessível."""
        camera = await self.get_camera(camera_id, tenant_id)
        agent_id = camera.agent_id
        await self._mediamtx.remove_path(camera.mediamtx_path)
        await self._cameras.delete(camera_id, tenant_id)
        if agent_id:
            await _notify_agent(agent_id, "camera_removed", {"camera_id": camera_id})

    async def get_stream_urls(
        self, camera_id: str, tenant_id: str, viewer_token: str, mediamtx_host: str
    ) -> StreamUrls:
        """Gera URLs de streaming assinadas para um viewer."""
        camera = await self.get_camera(camera_id, tenant_id)
        settings = get_settings()
        path = camera.mediamtx_path

        # Log para debug
        logger.info(
            "Gerando stream URLs: camera=%s tenant=%s path=%s host=%s",
            camera_id,
            tenant_id,
            path,
            mediamtx_host,
        )

        return StreamUrls(
            hls_url=f"/hls/{path}/index.m3u8?token={viewer_token}",
            webrtc_url=f"/webrtc/{path}/whep?token={viewer_token}",
            rtsp_url=(
                f"/stream/rtsp/{path}?token={viewer_token}"
                if camera.stream_protocol != StreamProtocol.RTMP_PUSH
                else None
            ),
            token=viewer_token,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
        )

    async def onvif_probe(self, onvif_url: str, username: str, password: str) -> OnvifProbeResult:
        """Faz probe ONVIF e retorna capacidades da câmera."""
        from vms.cameras.onvif_client import OnvifClient

        return await OnvifClient.probe(onvif_url, username, password)


class AgentService:
    """Casos de uso de gerenciamento de agents."""

    def __init__(
        self,
        agent_repo: AgentRepositoryPort,
        camera_repo: CameraRepositoryPort,
        api_key_service: ApiKeyService,
        tunnel_repo: AgentTunnelRepositoryPort | None = None,
        wg_hub_client: WireGuardHubClient | None = None,
    ) -> None:
        self._agents = agent_repo
        self._cameras = camera_repo
        self._api_keys = api_key_service
        # Opcionais: endpoints que não mexem com túnel (get_agent_config,
        # heartbeat, etc.) não precisam construir esses dois toda vez.
        self._tunnels = tunnel_repo
        self._wg_hub = wg_hub_client

    async def create_agent(self, tenant_id: str, name: str) -> tuple[Agent, str]:
        """
        Cria agent e emite API key.

        Retorna (agent, api_key_plain). A chave deve ser exibida uma única vez.
        """
        agent = Agent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
        )
        saved = await self._agents.create(agent)
        api_key, plain = await self._api_keys.issue_api_key(
            tenant_id=tenant_id,
            owner_type=ApiKeyOwnerType.AGENT,
            owner_id=saved.id,
        )
        return saved, plain

    async def create_agent_with_tunnel(self, tenant_id: str, name: str) -> AgentTunnelBundle:
        """
        Cria agent, emite API key e provisiona o túnel WireGuard.

        Se qualquer passo do túnel falhar (ex.: hub inacessível), desfaz tudo
        — não deixa um agent "órfão" sem túnel, que pareceria criado mas
        nunca conseguiria se conectar.
        """
        assert self._tunnels is not None and self._wg_hub is not None, (
            "AgentService precisa de tunnel_repo/wg_hub_client pra create_agent_with_tunnel"
        )
        agent, plain_key = await self.create_agent(tenant_id, name)
        try:
            settings = get_settings()
            private_key, public_key = generate_wg_keypair()
            offset = await self._tunnels.next_ip_offset()
            subnet_prefix = _wg_subnet_prefix(settings.wg_subnet)
            tunnel_ip = f"{subnet_prefix}.{offset}"

            hub_info = await self._wg_hub.get_hub_info()

            await self._tunnels.create(AgentTunnel(
                id=str(uuid.uuid4()),
                agent_id=agent.id,
                public_key=public_key,
                tunnel_ip=tunnel_ip,
            ))
            await self._wg_hub.add_peer(public_key, tunnel_ip)
        except Exception:
            logger.exception(
                "Falha ao provisionar túnel WG pro agent %s — desfazendo criação", agent.id
            )
            await self._api_keys.revoke_api_keys_for_owner(
                ApiKeyOwnerType.AGENT, agent.id, tenant_id
            )
            await self._agents.delete(agent.id, tenant_id)
            raise

        return AgentTunnelBundle(
            agent=agent,
            api_key=plain_key,
            wg_private_key=private_key,
            wg_public_key_hub=hub_info["public_key"],
            wg_endpoint=hub_info.get("endpoint") or settings.wg_public_endpoint,
            wg_tunnel_ip=f"{tunnel_ip}/32",
            wg_allowed_ips=f"{subnet_prefix}.1/32",
        )

    async def get_agent(self, agent_id: str, tenant_id: str) -> Agent:
        """Retorna agent por ID. Lança NotFoundError se não encontrado."""
        agent = await self._agents.get_by_id(agent_id, tenant_id)
        if not agent:
            raise NotFoundError("Agent", agent_id)
        return agent

    async def list_agents(self, tenant_id: str) -> list[Agent]:
        """Lista todos os agents do tenant."""
        return await self._agents.list_by_tenant(tenant_id)

    async def update_agent(
        self,
        agent_id: str,
        tenant_id: str,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> Agent:
        """Atualiza nome e/ou status ativo de um agent."""
        agent = await self.get_agent(agent_id, tenant_id)
        if name is not None:
            agent.name = name
        if is_active is not None:
            agent.is_active = is_active
        return await self._agents.update(agent)

    async def get_agent_config(
        self, agent_id: str, tenant_id: str
    ) -> tuple[Agent, list[CameraConfig]]:
        """Retorna agent e lista de configurações de câmera para o agent (somente rtsp_pull)."""
        agent = await self.get_agent(agent_id, tenant_id)
        if not agent.is_active:
            raise UnauthorizedError("Agent desativado")
        cameras = await self._cameras.list_by_agent(agent_id, tenant_id)
        configs = [
            CameraConfig(
                id=cam.id,
                name=cam.name,
                rtsp_url=cam.rtsp_url or "",
                mediamtx_path=cam.mediamtx_path,
                enabled=cam.is_active,
            )
            for cam in cameras
            if cam.stream_protocol in (StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF)
            and cam.rtsp_url
        ]
        return agent, configs

    async def register_heartbeat(
        self,
        agent_id: str,
        tenant_id: str,
        version: str,
        streams_running: int,
        streams_failed: int,
    ) -> Agent:
        """Registra heartbeat do agent e atualiza status para online."""
        agent = await self.get_agent(agent_id, tenant_id)
        if not agent.is_active:
            raise UnauthorizedError("Agent desativado")
        agent.mark_online(version, streams_running, streams_failed)
        return await self._agents.update(agent)

    async def delete_agent(self, agent_id: str, tenant_id: str) -> None:
        """Remove agent definitivamente e revoga sua(s) API key(s) e túnel."""
        await self.get_agent(agent_id, tenant_id)  # 404 se não existir/outro tenant
        await self._api_keys.revoke_api_keys_for_owner(
            ApiKeyOwnerType.AGENT, agent_id, tenant_id
        )
        if self._tunnels is not None:
            try:
                tunnel = await self._tunnels.get_by_agent(agent_id)
                if tunnel:
                    if self._wg_hub is not None:
                        await self._wg_hub.remove_peer(tunnel.public_key)
                    await self._tunnels.delete(tunnel.id)
            except Exception:
                # Best-effort — não bloqueia a remoção do agent por causa de
                # um hub temporariamente inacessível (mesmo espírito do
                # cleanup de MediaMTX em CameraService.delete_camera).
                logger.warning("Falha ao revogar túnel WG do agent %s (não crítico)", agent_id)
        await self._agents.delete(agent_id, tenant_id)

    async def list_active_tunnels(self) -> list[AgentTunnel]:
        """Todos os túneis ativos, de qualquer tenant — usado pelo hub
        WireGuard pra reconciliar seu estado no boot (fonte de verdade é o
        Postgres, não o estado runtime do container do hub)."""
        assert self._tunnels is not None
        return await self._tunnels.list_active()


async def _notify_agent(agent_id: str, event: str, data: dict) -> None:
    """Publica evento no Redis channel do agent (best-effort, não falha)."""
    try:
        from vms.infrastructure.config import get_settings
        import redis.asyncio as aioredis

        settings = get_settings()
        client = aioredis.from_url(settings.redis_url)
        payload = json.dumps({"event": event, **data})
        await client.publish(f"agent:{agent_id}:config", payload)
        await client.aclose()
    except Exception as exc:
        logger.warning("Falha ao notificar agent %s: %s", agent_id, exc)
