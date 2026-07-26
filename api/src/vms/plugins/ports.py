"""
Ports do Bounded Context: Plugins.

Interfaces que o Plugins Context exporta para outros contexts usarem.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PluginCameraInfo:
    """DTO mínimo de câmera necessário para o Plugins Context."""
    id: str
    tenant_id: str
    name: str
    is_active: bool
    ia_enabled: bool


class PluginCameraPort(Protocol):
    """
    Porta para listar câmeras no Plugins Context.

    Plugins precisa listar câmeras ativas com analytics habilitado.

    Implementação real: CameraRepository do bounded context Cameras.
    """

    async def list_active_by_tenant(self, tenant_id: str) -> list[PluginCameraInfo]: ...
    async def get_by_id(self, camera_id: str, tenant_id: str) -> PluginCameraInfo | None: ...


class PluginAuthPort(Protocol):
    """
    Porta para autenticação no Plugins Context.

    Implementação real: AuthService do IAM Context.
    """

    async def authenticate_api_key(self, api_key: str) -> str | None:
        """Retorna owner_id se API key válida, None caso contrário."""
        ...


class PluginROIPort(Protocol):
    """
    Porta para buscar ROIs ativas no Plugins Context.

    Implementação real: AnalyticsROI do bounded context Analytics.
    """

    async def list_active_by_camera(self, camera_id: str) -> list[dict]: ...
