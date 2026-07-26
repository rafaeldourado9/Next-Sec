"""Captura de thumbnail de câmera via ffmpeg — retorna JPEG bytes."""
from __future__ import annotations

import asyncio
import logging

from vms.cameras.domain import Camera, StreamProtocol
from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 8  # segundos máximos para captura de frame
_CACHE: dict[str, bytes] = {}  # cache em memória simples (processo único)
_CACHE_TTL: dict[str, float] = {}


async def capture_thumbnail(camera: Camera) -> bytes | None:
    """
    Captura frame da câmera e retorna bytes JPEG.

    Estratégia por protocolo:
    - RTMP push: tenta HLS interno (stream ativo no MediaMTX)
    - RTSP pull / ONVIF: tenta RTSP direto, depois HLS
    - Retorna None se câmera offline ou stream indisponível
    """
    import time

    cache_key = camera.id
    now = time.monotonic()

    # Cache de 30s para não sobrecarregar ffmpeg
    if cache_key in _CACHE and now - _CACHE_TTL.get(cache_key, 0) < 30:
        return _CACHE[cache_key]

    settings = get_settings()
    path = camera.mediamtx_path

    # Tenta HLS do MediaMTX primeiro (mais confiável, não requer RTSP direto)
    hls_url = f"{settings.mediamtx_hls_url}/{path}/index.m3u8"
    frame = await _ffmpeg_grab_frame(hls_url)

    # Para RTSP pull/ONVIF, tenta RTSP direto se HLS falhou
    if not frame and camera.rtsp_url and camera.stream_protocol in (
        StreamProtocol.RTSP_PULL, StreamProtocol.ONVIF
    ):
        frame = await _ffmpeg_grab_frame(camera.rtsp_url, use_tcp=True)

    if frame:
        _CACHE[cache_key] = frame
        _CACHE_TTL[cache_key] = now

    return frame


async def _ffmpeg_grab_frame(url: str, use_tcp: bool = False) -> bytes | None:
    """
    Executa ffmpeg para capturar 1 frame da URL dada.

    Retorna bytes JPEG ou None em caso de erro.
    """
    cmd = ["ffmpeg", "-y"]
    if use_tcp:
        cmd += ["-rtsp_transport", "tcp"]
    cmd += [
        "-i", url,
        "-vframes", "1",
        "-vf", "scale=640:-1",     # redimensiona para largura 640 mantendo proporção
        "-q:v", "5",               # qualidade JPEG (2=melhor, 31=pior) — 5 é bom equilíbrio
        "-f", "image2",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        if proc.returncode == 0 and stdout:
            return stdout
    except (asyncio.TimeoutError, OSError) as exc:
        logger.debug("Falha ao capturar thumbnail de %s: %s", url, exc)

    return None
