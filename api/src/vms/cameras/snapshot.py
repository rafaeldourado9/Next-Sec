"""Captura de snapshot de câmera — ffmpeg frame capturado inline."""
from __future__ import annotations

import logging

from vms.cameras.domain import Camera, StreamProtocol

logger = logging.getLogger(__name__)


async def get_snapshot_url(camera: Camera) -> str | None:
    """
    Captura um frame da câmera e retorna como data URL (data:image/jpeg;base64,...).

    Estratégia:
    1. Tenta HLS interno do MediaMTX (funciona para qualquer câmera com stream ativo)
    2. Para RTSP pull / ONVIF: fallback para RTSP direto
    3. Retorna None se ffmpeg não conseguir capturar frame
    """
    if camera.stream_protocol == StreamProtocol.ONVIF and camera.onvif_url:
        try:
            from vms.cameras.onvif_client import OnvifClient

            probe = await OnvifClient.probe(
                camera.onvif_url,
                camera.onvif_username or "",
                camera.onvif_password or "",
            )
            if probe.snapshot_url:
                return probe.snapshot_url
        except Exception as exc:
            logger.debug("Falha ao obter snapshot ONVIF da camera=%s: %s", camera.id, exc)

    if camera.rtsp_url and camera.stream_protocol in (StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF):
        return f"/api/v1/cameras/{camera.id}/thumbnail?path={camera.mediamtx_path}"

    logger.debug("get_snapshot_url: sem URL para camera=%s protocol=%s", camera.id, camera.stream_protocol)
    return None
