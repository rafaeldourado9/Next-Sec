"""
Ports do Bounded Context: Cameras.

Interfaces que o Cameras Context exporta para outros contexts usarem.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class CameraStatusInfo:
    """DTO mínimo de câmera para atualização de status."""
    id: str
    tenant_id: str
    is_online: bool


class CameraStatusPort(Protocol):
    """
    Porta para atualizar status online/offline de câmeras.

    O Events Context precisa marcar câmeras como online/offline
    quando recebe webhooks do MediaMTX.

    Implementação real: CameraRepository do bounded context Cameras.
    """

    async def mark_online(self, camera_id: str, tenant_id: str) -> None: ...
    async def mark_offline(self, camera_id: str, tenant_id: str) -> None: ...
    async def get_by_id(self, camera_id: str, tenant_id: str) -> CameraStatusInfo | None: ...
    async def get_by_stream_key(self, stream_key: str) -> CameraStatusInfo | None: ...
    async def list_active_with_retention(self, tenant_id: str) -> list[dict]: ...
