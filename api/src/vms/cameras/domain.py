"""
Entidades de domínio de câmeras e agents.

Bounded Context: Cameras

Responsabilidade:
    Gerenciar câmeras de segurança, agents de captura e configurações de stream.
    Controlar estado online/offline, protocolos de ingestão e analytics.

Atores:
    - Camera: entidade principal, aggregate root
    - Agent: agente local que captura RTSP e faz push RTMP
    - CameraConfig: DTO para configuração do agent
    - StreamUrls: DTO de resposta para viewers
    - OnvifProbeResult: resultado de probe ONVIF

Integrações:
    - Streaming Context: fornece mediamtx_path para sessões
    - Recordings Context: câmera gera segmentos de gravação
    - Analytics Context: câmera com plugins de IA ativos
    - Events Context: câmera gera eventos ALPR, motion, etc.

Regras de Negócio:
    1. Câmera RTMP_PUSH tem stream_key único e agente_id nulo
    2. Câmera RTSP_PULL/ONVIF tem agente_id e usa path tenant-X/cam-Y
    3. Câmera inativa não pode ficar online
    4. Transições de estado (online/offline) emitem Domain Events
    5. Analytics só pode ser habilitado em câmera ativa

Não faz:
    - Streaming ao vivo (responsabilidade do Streaming Context)
    - Gravação de segmentos (responsabilidade do Recordings Context)
    - Detecção de eventos IA (responsabilidade do Analytics Context)
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from vms.shared.kernel import (
    AggregateRoot,
    BusinessRuleViolation,
    CameraId,
    EntityId,
    TenantId,
)


# ─── Enums (Value Objects) ───────────────────────────────────────────────────


class StreamProtocol:
    """Protocolo de ingestão de vídeo da câmera."""

    RTSP_PULL = "rtsp_pull"  # Agent faz RTSP pull e RTMP push para o VMS
    RTMP_PUSH = "rtmp_push"  # Câmera envia RTMP diretamente para o MediaMTX
    ONVIF = "onvif"  # Câmera ONVIF — stream URL extraída via GetStreamUri


class CameraManufacturer:
    """Fabricantes de câmera suportados."""

    HIKVISION = "hikvision"
    INTELBRAS = "intelbras"
    DAHUA = "dahua"
    GENERIC = "generic"


class StreamQuality:
    """Qualidade de stream/gravação da câmera."""

    LOW = "low"  # 480p — menor consumo de banda
    MEDIUM = "medium"  # 720p — equilibrio
    HIGH = "high"  # 1080p — alta fidelidade
    SOURCE = "source"  # resolução original da câmera


class AgentStatus:
    """Estado do agent local."""

    PENDING = "pending"
    ONLINE = "online"
    OFFLINE = "offline"


# ─── Domain Events ────────────────────────────────────────────────────────────

from vms.shared.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class CameraCreated(DomainEvent):
    """Câmera foi criada no sistema."""

    camera_id: CameraId | None = None
    tenant_id: TenantId | None = None
    name: str = ""
    protocol: str = ""


@dataclass(frozen=True, kw_only=True)
class CameraActivated(DomainEvent):
    """Câmera ficou online (conectou ao MediaMTX/Agent)."""

    camera_id: CameraId | None = None
    tenant_id: TenantId | None = None


@dataclass(frozen=True, kw_only=True)
class CameraDeactivated(DomainEvent):
    """Câmera ficou offline (desconectou)."""

    camera_id: CameraId | None = None
    tenant_id: TenantId | None = None


@dataclass(frozen=True, kw_only=True)
class CameraAnalyticsEnableded(DomainEvent):
    """Analytics foi habilitado na câmera."""

    camera_id: CameraId | None = None
    tenant_id: TenantId | None = None


@dataclass(frozen=True, kw_only=True)
class CameraAnalyticsDisabled(DomainEvent):
    """Analytics foi desabilitado na câmera."""

    camera_id: CameraId | None = None
    tenant_id: TenantId | None = None


# ─── Entidades ────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """
    Agent local que captura streams RTSP e envia via RTMP.

    Aggregate Root do Agent Aggregate.
    Controla o estado de conexão e métricas de saúde do agent.
    """

    id: EntityId
    tenant_id: TenantId
    name: str
    status: str = AgentStatus.PENDING
    last_heartbeat_at: datetime | None = None
    version: str | None = None
    streams_running: int = 0
    streams_failed: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    def mark_online(
        self,
        version: str,
        streams_running: int,
        streams_failed: int,
    ) -> None:
        """
        Marca agent como online com dados do heartbeat.

        Transição de estado: qualquer estado → ONLINE.
        Atualiza métricas de saúde do agent.
        """
        self.status = AgentStatus.ONLINE
        self.last_heartbeat_at = datetime.now(timezone.utc)
        self.version = version
        self.streams_running = streams_running
        self.streams_failed = streams_failed

    def mark_offline(self) -> None:
        """
        Marca agent como offline.

        Transição de estado: qualquer estado → OFFLINE.
        Usado quando heartbeat expira ou conexão cai.
        """
        self.status = AgentStatus.OFFLINE

    @property
    def is_online(self) -> bool:
        """Verifica se agent está online."""
        return self.status == AgentStatus.ONLINE

    @property
    def health_pct(self) -> float:
        """
        Calcula porcentagem de saúde do agent.

        Retorna 100% se nenhum stream falhou.
        Retorna 0% se todos os streams falharam.
        """
        total = self.streams_running + self.streams_failed
        if total == 0:
            return 100.0
        return (self.streams_running / total) * 100


@dataclass
class Camera(AggregateRoot):
    """
    Câmera de segurança gerenciada pelo VMS.

    Aggregate Root do Camera Aggregate.
    Controla streaming, analytics, gravações e estado de conexão.

    Invariantes:
        1. Câmera inativa não pode ficar online
        2. Câmera RTMP_PUSH tem stream_key e agent_id nulo
        3. Câmera RTSP_PULL/ONVIF tem agent_id
        4. Analytics só pode ser habilitado em câmera ativa
    """

    id: CameraId
    tenant_id: TenantId
    name: str
    manufacturer: str = CameraManufacturer.GENERIC
    stream_protocol: str = StreamProtocol.RTSP_PULL
    rtsp_url: str | None = None
    rtmp_stream_key: str | None = None
    onvif_url: str | None = None
    onvif_username: str | None = None
    onvif_password: str | None = None
    location: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    ia_enabled: bool = False
    agent_id: EntityId | None = None
    retention_days: int = 7
    recording_enabled: bool = False
    stream_quality: str = StreamQuality.HIGH
    is_active: bool = True
    is_online: bool = False
    ptz_supported: bool = False
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ISAPI Integration (Hikvision)
    isapi_enabled: bool = False
    isapi_base_url: str | None = None
    isapi_username: str | None = None
    isapi_password: str | None = None  # Encrypted
    serial_number: str | None = None
    firmware_version: str | None = None
    model_name: str | None = None
    isapi_capabilities: dict = field(default_factory=dict)
    camera_type: str = "internal"  # internal | external | lpr | facial

    # ─── Factories ───────────────────────────────────────────────────────

    @classmethod
    def create_rtmp_push(
        cls,
        tenant_id: TenantId,
        name: str,
        manufacturer: str = CameraManufacturer.GENERIC,
        retention_days: int = 7,
        stream_quality: str = StreamQuality.HIGH,
    ) -> Camera:
        """
        Factory para câmera RTMP push.

        Câmeras RTMP push não têm agent — enviam stream diretamente ao MediaMTX.
        Stream key é gerado automaticamente.

        Uso:
            camera = Camera.create_rtmp_push(
                tenant_id=TenantId(...),
                name="Entrada Principal",
            )
        """
        return cls(
            id=CameraId.new(),
            tenant_id=tenant_id,
            name=name,
            manufacturer=manufacturer,
            stream_protocol=StreamProtocol.RTMP_PUSH,
            rtmp_stream_key=cls._generate_stream_key(),
            agent_id=None,
            retention_days=retention_days,
            stream_quality=stream_quality,
        )

    @classmethod
    def create_rtsp_pull(
        cls,
        tenant_id: TenantId,
        agent_id: EntityId,
        name: str,
        rtsp_url: str,
        manufacturer: str = CameraManufacturer.GENERIC,
        retention_days: int = 7,
        stream_quality: str = StreamQuality.HIGH,
    ) -> Camera:
        """
        Factory para câmera RTSP pull (via agent).

        Câmeras RTSP pull requerem um agent para capturar o stream.

        Uso:
            camera = Camera.create_rtsp_pull(
                tenant_id=TenantId(...),
                agent_id=agent.id,
                name="Portaria Norte",
                rtsp_url="rtsp://192.168.1.100:554/stream",
            )
        """
        return cls(
            id=CameraId.new(),
            tenant_id=tenant_id,
            name=name,
            manufacturer=manufacturer,
            stream_protocol=StreamProtocol.RTSP_PULL,
            rtsp_url=rtsp_url,
            agent_id=agent_id,
            retention_days=retention_days,
            stream_quality=stream_quality,
        )

    # ─── Transições de Estado ──────────────────────────────────────────────

    def activate(self) -> None:
        """
        Ativa a câmera.

        Transição: inativa → ativa.
        Se estava online, permanece online.
        """
        if self.is_active:
            return  # Já ativa — idempotente
        self.is_active = True
        self.record_event(CameraActivated(camera_id=self.id, tenant_id=self.tenant_id))

    def deactivate(self) -> None:
        """
        Desativa a câmera.

        Transição: ativa → inativa.
        Se estava online, vai para offline.
        Analytics é desabilitado automaticamente.
        """
        if not self.is_active:
            return  # Já inativa — idempotente
        self.is_active = False
        self.is_online = False
        self.ia_enabled = False
        self.record_event(CameraDeactivated(camera_id=self.id, tenant_id=self.tenant_id))

    def go_online(self) -> None:
        """
        Marca câmera como online (conectou).

        Transição: offline → online.
        Requer que câmera esteja ativa.

        Raises:
            BusinessRuleViolation: Se câmera está inativa.
        """
        if not self.is_active:
            raise BusinessRuleViolation(
                "Câmera inativa não pode ficar online",
                details={"camera_id": str(self.id)},
            )
        self.is_online = True
        self.last_seen_at = datetime.now(timezone.utc)
        self.record_event(CameraActivated(camera_id=self.id, tenant_id=self.tenant_id))

    def mark_online(self) -> None:
        """Alias legado para marcar câmera como online."""
        self.go_online()

    def go_offline(self) -> None:
        """
        Marca câmera como offline (desconectou).

        Transição: online → offline.
        Sempre permitido.
        """
        if not self.is_online:
            return  # Já offline — idempotente
        self.is_online = False
        self.record_event(CameraDeactivated(camera_id=self.id, tenant_id=self.tenant_id))

    def mark_offline(self) -> None:
        """Alias legado para marcar câmera como offline."""
        self.go_offline()

    def enable_analytics(self) -> None:
        """
        Habilita analytics (plugins de IA) na câmera.

        Requer que câmera esteja ativa.

        Raises:
            BusinessRuleViolation: Se câmera está inativa.
        """
        if not self.is_active:
            raise BusinessRuleViolation(
                "Câmera inativa não pode ter analytics",
                details={"camera_id": str(self.id)},
            )
        if self.ia_enabled:
            return  # Já habilitado — idempotente
        self.ia_enabled = True
        self.record_event(CameraAnalyticsEnableded(camera_id=self.id, tenant_id=self.tenant_id))

    def disable_analytics(self) -> None:
        """
        Desabilita analytics na câmera.

        Sempre permitido.
        """
        if not self.ia_enabled:
            return  # Já desabilitado — idempotente
        self.ia_enabled = False
        self.record_event(CameraAnalyticsDisabled(camera_id=self.id, tenant_id=self.tenant_id))

    # ─── Propriedades Calculadas ───────────────────────────────────────────

    @property
    def mediamtx_path(self) -> str:
        """
        Path do stream no MediaMTX.

        RTMP push: live/{stream_key} (URL limpa para integrador)
        RTSP/ONVIF: tenant-{tid}/cam-{cid} (isolamento por tenant)
        """
        if self.stream_protocol == StreamProtocol.RTMP_PUSH and self.rtmp_stream_key:
            return f"live/{self.rtmp_stream_key}"
        return f"tenant-{self.tenant_id}/cam-{self.id}"

    @property
    def has_location(self) -> bool:
        """Verifica se câmera tem coordenadas geográficas."""
        return self.latitude is not None and self.longitude is not None

    @property
    def is_rtmp_push(self) -> bool:
        """Verifica se câmera é do tipo RTMP push."""
        return self.stream_protocol == StreamProtocol.RTMP_PUSH

    @property
    def is_agent_based(self) -> bool:
        """Verifica se câmera requer agent (RTSP pull ou ONVIF)."""
        return self.stream_protocol in (StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF)

    # ─── Helpers ───────────────────────────────────────────────────────────

    def update_location(
        self,
        latitude: float | None,
        longitude: float | None,
        address: str | None = None,
    ) -> None:
        """
        Atualiza localização geográfica da câmera.

        Usado no mapa tático para posicionar pins.
        """
        if latitude is not None and not (-90 <= latitude <= 90):
            raise BusinessRuleViolation(f"Latitude inválida: {latitude} (deve ser entre -90 e 90)")
        if longitude is not None and not (-180 <= longitude <= 180):
            raise BusinessRuleViolation(
                f"Longitude inválida: {longitude} (deve ser entre -180 e 180)"
            )
        self.latitude = latitude
        self.longitude = longitude
        if address is not None:
            self.address = address

    def update_rtsp_credentials(
        self,
        rtsp_url: str | None,
        onvif_url: str | None = None,
        onvif_username: str | None = None,
        onvif_password: str | None = None,
    ) -> None:
        """
        Atualiza credenciais RTSP/ONVIF da câmera.

        Nota: onvif_password é armazenada encrypted at rest.
        """
        self.rtsp_url = rtsp_url
        if onvif_url is not None:
            self.onvif_url = onvif_url
        if onvif_username is not None:
            self.onvif_username = onvif_username
        if onvif_password is not None:
            self.onvif_password = onvif_password

    @staticmethod
    def generate_stream_key() -> str:
        """Gera stream key aleatório seguro para câmeras RTMP push."""
        return Camera._generate_stream_key()

    @staticmethod
    def _generate_stream_key() -> str:
        """Gera stream key aleatório seguro para câmeras RTMP push."""
        return secrets.token_urlsafe(32)


# ─── DTOs (não são entidades de domínio) ─────────────────────────────────────


@dataclass
class CameraConfig:
    """Configuração de uma câmera para o agent (apenas rtsp_pull)."""

    id: str
    name: str
    rtsp_url: str
    rtmp_push_url: str
    enabled: bool


@dataclass
class StreamUrls:
    """URLs de streaming assinadas para um viewer."""

    hls_url: str
    webrtc_url: str
    rtsp_url: str | None
    token: str
    expires_at: datetime


@dataclass
class OnvifProbeResult:
    """Resultado de probe ONVIF em uma câmera."""

    reachable: bool
    manufacturer: str | None = None
    model: str | None = None
    rtsp_url: str | None = None
    snapshot_url: str | None = None
    error: str | None = None
