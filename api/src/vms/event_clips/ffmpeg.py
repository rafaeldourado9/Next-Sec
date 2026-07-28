"""Renderização de clipe (freeze-frame) via ffmpeg — função pura, sem
dependência de sessão de banco nem de `EventClipService`.

Extraída de `EventClipService._render_freeze_frame_clip` (Sprint 4) para ser
reaproveitada também pela task do worker de edge (`vms.event_clips.
edge_tasks`, ver ADR-017 §1) — o mesmo ffmpeg que a VPS central roda hoje
(quando `edge_generates_clip=False`) passa a rodar também no hardware do
cliente (Nível 1), sem duplicar a lógica de invocação do processo.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile


async def render_freeze_frame_clip(image_path: str, duration_seconds: int) -> str:
    """Gera um MP4 de `duration_seconds` a partir de uma imagem única, via ffmpeg.

    LIMITAÇÃO CONHECIDA (v1, ver `event_clips/service.py`): sem ring-buffer de
    vídeo contínuo — o "clipe" é o frame único do evento esticado num vídeo,
    uma prova visual real, mas sem movimento.

    Roda o ffmpeg síncrono (`subprocess.run`) numa thread (`asyncio.to_thread`)
    em vez de `asyncio.create_subprocess_exec` — achado no Sprint 6 (S6-04):
    o child watcher de subprocess do asyncio pode ficar preso quando o
    processo é recriado várias vezes ao longo do mesmo processo Python com
    múltiplos event loops (ex.: um loop novo por teste no pytest-asyncio),
    fazendo o `communicate()` nunca retornar mesmo com o ffmpeg já tendo
    saído. `subprocess.run` numa thread usa `waitpid` direto, sem depender
    de nenhum estado do event loop — mais simples e mais robusto pro mesmo
    resultado.

    Retorna o path do arquivo MP4 temporário gerado — o chamador é responsável
    por removê-lo depois de usar (upload/envio).
    """
    fd, output_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-c:v", "libx264",
        "-t", str(duration_seconds),
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        output_path,
    ]

    def _run_ffmpeg() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    result = await asyncio.to_thread(_run_ffmpeg)
    if result.returncode != 0:
        os.remove(output_path)
        raise RuntimeError(
            f"ffmpeg falhou (código {result.returncode}): {result.stderr.decode()[-500:]}"
        )
    return output_path
