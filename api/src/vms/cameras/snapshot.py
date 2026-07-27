"""Captura de snapshot de câmera — ffmpeg frame capturado inline."""
from __future__ import annotations

import base64
import logging

from vms.cameras.domain import Camera, StreamProtocol

logger = logging.getLogger(__name__)


async def get_snapshot_url(camera: Camera) -> str | None:
    """
    Captura um frame da câmera e retorna como data URL (data:image/jpeg;base64,...).

    Estratégia:
    1. ONVIF com snapshot URI próprio da câmera — usa direto.
    2. Qualquer outro protocolo com stream ativo — captura via ffmpeg
       (`capture_thumbnail`, mesma captura usada pelo grid de thumbnails).
    3. Retorna None se nenhuma das duas conseguir um frame.

    NOTA (Next Sec): antes disso, o fallback pra RTSP/ONVIF devolvia um path
    de API (`/cameras/{id}/thumbnail?path=...`) em vez de uma data URL — o
    endpoint de thumbnail exige `?token=` (JWT), não `?path=`, então essa URL
    sempre dava 401 no frontend (achado durante teste local — "snapshot não
    funciona").
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

    from vms.cameras.thumbnail import capture_thumbnail

    jpeg_bytes = await capture_thumbnail(camera)
    if jpeg_bytes:
        encoded = base64.b64encode(jpeg_bytes).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    logger.debug("get_snapshot_url: sem frame disponível para camera=%s protocol=%s", camera.id, camera.stream_protocol)
    return None
