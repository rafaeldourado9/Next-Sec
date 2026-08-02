"""Schemas Pydantic v2 para o bounded context de câmeras e agents."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from vms.cameras.domain import StreamProtocol, StreamQuality


class CreateCameraRequest(BaseModel):
    """Dados para criação de uma nova câmera."""

    name: str = Field(..., min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    ia_enabled: bool = False
    manufacturer: str = Field(default="generic")
    retention_days: int = Field(default=7)
    recording_enabled: bool = Field(
        default=False,
        description="Gravação contínua opt-in — ver incidente documentado em cameras/mediamtx.py antes de ligar em produção.",
    )
    stream_quality: str = StreamQuality.HIGH
    stream_protocol: str = StreamProtocol.RTSP_PULL
    camera_type: str = Field(default="internal", pattern=r"^(internal|external|lpr|facial)$")

    # rtsp_pull / onvif
    rtsp_url: str | None = Field(default=None, min_length=10, max_length=2000)
    agent_id: str | None = None

    # onvif
    onvif_url: str | None = Field(default=None, min_length=7, max_length=2000)
    onvif_username: str | None = Field(default=None, max_length=255)
    onvif_password: str | None = Field(default=None, max_length=500)

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        if v not in (5, 15, 30):
            raise ValueError("retention_days deve ser 5, 15 ou 30")
        return v

    @field_validator("rtsp_url", mode="before")
    @classmethod
    def sanitize_rtsp_url(cls, v: str | None) -> str | None:
        """Garante que rtsp_url é uma única URL válida, sem espaços ou quebras."""
        if v is None:
            return v
        # Pega apenas a primeira token não-vazio (evita colagem de múltiplas URLs)
        first = v.strip().split()[0] if v.strip() else v
        if not first.startswith(("rtsp://", "rtmp://", "http://", "https://")):
            raise ValueError(
                "rtsp_url deve ser uma URL válida iniciando com rtsp://, rtmp://, http:// ou https://"
            )
        return first

    @model_validator(mode="after")
    def _validate_protocol_fields(self) -> "CreateCameraRequest":
        if self.stream_protocol == StreamProtocol.RTSP_PULL:
            if not self.rtsp_url:
                raise ValueError("rtsp_url é obrigatório para stream_protocol=rtsp_pull")
        elif self.stream_protocol == StreamProtocol.ONVIF:
            if not self.onvif_url:
                raise ValueError("onvif_url é obrigatório para stream_protocol=onvif")
        # rtmp_push: nenhum campo adicional obrigatório — stream_key é gerado pelo serviço
        return self


class UpdateCameraRequest(BaseModel):
    """Dados para atualização parcial de uma câmera."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = None
    address: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    ia_enabled: bool | None = None
    stream_quality: str | None = None
    rtsp_url: str | None = Field(default=None, min_length=10, max_length=2000)

    @field_validator("rtsp_url", mode="before")
    @classmethod
    def sanitize_rtsp_url(cls, v: str | None) -> str | None:
        """Garante que rtsp_url é uma única URL válida."""
        if v is None:
            return v
        first = v.strip().split()[0] if v.strip() else v
        if not first.startswith(("rtsp://", "rtmp://", "http://", "https://")):
            raise ValueError(
                "rtsp_url deve ser uma URL válida iniciando com rtsp://, rtmp://, http:// ou https://"
            )
        return first

    onvif_url: str | None = Field(default=None, min_length=7, max_length=2000)
    onvif_username: str | None = Field(default=None, max_length=255)
    onvif_password: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = None
    retention_days: int | None = Field(default=None)
    recording_enabled: bool | None = None
    camera_type: str | None = Field(default=None, pattern=r"^(internal|external|lpr|facial)$")
    agent_id: str | None = None

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int | None) -> int | None:
        if v is not None and v not in (5, 15, 30):
            raise ValueError("retention_days deve ser 5, 15 ou 30")
        return v

    is_active: bool | None = None

    # ISAPI
    isapi_enabled: bool | None = None
    isapi_base_url: str | None = Field(default=None, max_length=2000)
    isapi_username: str | None = Field(default=None, max_length=255)
    isapi_password: str | None = Field(default=None, max_length=500)


class CameraResponse(BaseModel):
    """Resposta com dados completos de uma câmera."""

    model_config = {"from_attributes": True}

    id: str
    tenant_id: str
    name: str
    location: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    ia_enabled: bool
    stream_protocol: str
    rtsp_url: str | None
    rtmp_stream_key: str | None
    onvif_url: str | None
    onvif_username: str | None
    manufacturer: str
    retention_days: int
    recording_enabled: bool
    stream_quality: str
    is_active: bool
    is_online: bool
    ptz_supported: bool
    agent_id: str | None
    camera_type: str
    last_seen_at: datetime | None
    created_at: datetime

    # ISAPI
    isapi_enabled: bool
    isapi_base_url: str | None
    isapi_username: str | None
    serial_number: str | None
    firmware_version: str | None
    model_name: str | None
    isapi_capabilities: dict


class StreamUrlsResponse(BaseModel):
    """URLs de streaming para um viewer."""

    hls_url: str
    webrtc_url: str
    rtsp_url: str | None
    token: str
    expires_at: datetime


class RtmpConfigResponse(BaseModel):
    """Configuração RTMP para câmeras push direto."""

    rtmp_url: str
    stream_key: str


class OnvifProbeRequest(BaseModel):
    """Dados para probe ONVIF de uma câmera."""

    onvif_url: str = Field(..., min_length=7, max_length=2000)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=500)
    agent_id: str | None = Field(
        default=None,
        description="Se informado, o probe roda no agent (dentro da LAN do "
        "cliente) em vez de direto da API — necessário sempre que a câmera "
        "está atrás de CGNAT/NAT, já que a API na nuvem não alcança IPs de "
        "rede local.",
    )


class OnvifProbeResponse(BaseModel):
    """Resultado do probe ONVIF."""

    reachable: bool
    manufacturer: str | None = None
    model: str | None = None
    rtsp_url: str | None = None
    snapshot_url: str | None = None
    error: str | None = None


class DiscoverOnvifRequest(BaseModel):
    """Parâmetros para WS-Discovery de câmeras ONVIF na rede."""

    subnet: str | None = Field(
        default=None,
        description="Subnet CIDR para busca (ex: 192.168.1.0/24). Sem este campo usa broadcast.",
    )
    timeout_seconds: int = Field(default=3, ge=1, le=10)
    agent_id: str | None = Field(
        default=None,
        description="Se informado, o discovery roda no agent (dentro da LAN "
        "do cliente) em vez de direto da API — mesma razão do OnvifProbeRequest.",
    )


class DiscoveredCamera(BaseModel):
    """Câmera descoberta via WS-Discovery."""

    onvif_url: str
    manufacturer: str | None = None
    model: str | None = None
    ip: str


class DiscoverOnvifResponse(BaseModel):
    """Resultado da descoberta de câmeras ONVIF."""

    cameras: list[DiscoveredCamera]
    duration_ms: int


class CreateAgentRequest(BaseModel):
    """Dados para criação de um novo agent."""

    name: str = Field(..., min_length=1, max_length=255)


class UpdateAgentRequest(BaseModel):
    """Payload para atualização parcial de agent."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class AgentResponse(BaseModel):
    """Resposta com dados de um agent."""

    model_config = {"from_attributes": True}

    id: str
    name: str
    status: str
    last_heartbeat_at: datetime | None
    version: str | None
    streams_running: int
    streams_failed: int
    is_active: bool
    created_at: datetime


class CreateAgentResponse(AgentResponse):
    """Resposta de criação de agent — inclui API key e bundle do túnel
    WireGuard em texto plano (única vez — a chave privada nunca é persistida,
    nem re-consultável depois desta resposta)."""

    api_key: str = Field(
        ..., description="API key em texto plano. Guarde — não será exibida novamente."
    )
    wg_private_key: str = Field(..., description="Chave privada WireGuard do agent — nunca persistida no servidor.")
    wg_public_key_hub: str = Field(..., description="Chave pública do hub (VPS).")
    wg_endpoint: str = Field(..., description="host:port público do hub pra o agent discar.")
    wg_tunnel_ip: str = Field(..., description="IP alocado pro agent dentro do túnel, ex: 10.60.0.5/32.")
    wg_allowed_ips: str = Field(
        ..., description="AllowedIPs do lado do agent — só o IP do hub (split-tunnel, não afeta o resto da rede do cliente).",
    )


class AgentTunnelInternal(BaseModel):
    """Item retornado por `GET /agents/internal/tunnels` — consumido só pelo
    hub WireGuard pra reconciliar seu estado no boot (auth via WG_CONTROL_TOKEN,
    não JWT de usuário)."""

    public_key: str
    tunnel_ip: str


class CameraConfigItem(BaseModel):
    """Item de configuração de câmera para o agent.

    `mediamtx_path` é só o caminho (ex.: `tenant-x/cam-y`) — era
    `rtmp_push_url` (URL RTMP completa, montada com o host INTERNO da VPS)
    até um bug real achado em produção: o agent prefixava a própria base
    RTMP por cima de uma URL que já vinha completa. Ver `CameraConfig` em
    `cameras/domain.py` para o relato completo."""

    id: str
    name: str
    rtsp_url: str
    mediamtx_path: str
    enabled: bool


class AgentConfigResponse(BaseModel):
    """Configuração completa do agent — retornada no endpoint /agents/me/config."""

    agent_id: str
    cameras: list[CameraConfigItem]


class HeartbeatRequest(BaseModel):
    """Dados de heartbeat enviados pelo agent."""

    version: str = Field(..., min_length=1, max_length=50)
    streams_running: int = Field(..., ge=0)
    streams_failed: int = Field(..., ge=0)
    uptime_seconds: int = Field(..., ge=0)
