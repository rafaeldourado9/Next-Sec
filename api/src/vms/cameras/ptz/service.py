"""Casos de uso PTZ — pan/tilt/zoom via ONVIF."""
from __future__ import annotations

import httpx

from vms.cameras.domain import Camera, StreamProtocol
from vms.cameras.ptz.client import PtzClient
from vms.cameras.ptz.domain import PtzCommand, PtzPreset
from vms.cameras.repository import CameraRepositoryPort
from vms.shared.exceptions import BusinessRuleViolation, NotFoundError


class PtzService:
    """Casos de uso PTZ para câmeras ONVIF."""

    def __init__(self, camera_repo: CameraRepositoryPort) -> None:
        self._cameras = camera_repo

    async def list_presets(self, camera_id: str, tenant_id: str) -> list[PtzPreset]:
        """Lista presets PTZ salvos na câmera."""
        camera = await self._load_onvif_camera(camera_id, tenant_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ptz_url, profile_token = await self._get_ptz_context(camera, client)
            return await PtzClient.get_presets(
                ptz_url, profile_token,
                camera.onvif_username or "", camera.onvif_password or "",
                client,
            )

    async def goto_preset(
        self, camera_id: str, tenant_id: str, preset_token: str, speed: float = 0.5
    ) -> None:
        """Move câmera para preset salvo."""
        camera = await self._load_onvif_camera(camera_id, tenant_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ptz_url, profile_token = await self._get_ptz_context(camera, client)
            await PtzClient.goto_preset(
                ptz_url, profile_token, preset_token, speed,
                camera.onvif_username or "", camera.onvif_password or "",
                client,
            )

    async def move(self, camera_id: str, tenant_id: str, command: PtzCommand) -> None:
        """Inicia movimento contínuo PTZ."""
        camera = await self._load_onvif_camera(camera_id, tenant_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ptz_url, profile_token = await self._get_ptz_context(camera, client)
            await PtzClient.continuous_move(
                ptz_url, profile_token, command,
                camera.onvif_username or "", camera.onvif_password or "",
                client,
            )

    async def stop(self, camera_id: str, tenant_id: str) -> None:
        """Para movimento PTZ em curso."""
        camera = await self._load_onvif_camera(camera_id, tenant_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ptz_url, profile_token = await self._get_ptz_context(camera, client)
            await PtzClient.stop(
                ptz_url, profile_token,
                camera.onvif_username or "", camera.onvif_password or "",
                client,
            )

    async def save_preset(
        self, camera_id: str, tenant_id: str, name: str
    ) -> PtzPreset:
        """Salva posição atual da câmera como preset nomeado."""
        camera = await self._load_onvif_camera(camera_id, tenant_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            ptz_url, profile_token = await self._get_ptz_context(camera, client)
            token = await PtzClient.set_preset(
                ptz_url, profile_token, name,
                camera.onvif_username or "", camera.onvif_password or "",
                client,
            )
        return PtzPreset(token=token, name=name)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    async def _load_onvif_camera(self, camera_id: str, tenant_id: str) -> Camera:
        """Carrega câmera e valida que é ONVIF com credenciais."""
        camera = await self._cameras.get_by_id(camera_id, tenant_id)
        if not camera:
            raise NotFoundError("Câmera", camera_id)
        if camera.stream_protocol != StreamProtocol.ONVIF or not camera.onvif_url:
            raise BusinessRuleViolation("PTZ requer câmera configurada com protocolo ONVIF")
        return camera

    async def _get_ptz_context(
        self, camera: Camera, client: httpx.AsyncClient
    ) -> tuple[str, str]:
        """Retorna (ptz_url, profile_token) para a câmera."""
        username = camera.onvif_username or ""
        password = camera.onvif_password or ""
        ptz_url, profile_token = await _fetch_ptz_context(
            camera.onvif_url,  # type: ignore[arg-type]
            username, password, client,
        )
        return ptz_url, profile_token


async def _fetch_ptz_context(
    onvif_url: str,
    username: str,
    password: str,
    client: httpx.AsyncClient,
) -> tuple[str, str]:
    """Obtém PTZ URL e profile token concorrentemente."""
    import asyncio
    ptz_url, profile_token = await asyncio.gather(
        PtzClient.get_ptz_url(onvif_url, username, password, client),
        PtzClient.get_profile_token(onvif_url, username, password, client),
    )
    return ptz_url, profile_token
