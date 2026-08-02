"""Renderização de clipe via ffmpeg — funções puras, sem dependência de sessão
de banco nem de `EventClipService`.

Extraída de `EventClipService._render_freeze_frame_clip` (Sprint 4) para ser
reaproveitada também pela task do worker de edge (`vms.event_clips.
edge_tasks`, ver ADR-017 §1) — o mesmo ffmpeg que a VPS central roda hoje
(quando `edge_generates_clip=False`) passa a rodar também no hardware do
cliente (Nível 1), sem duplicar a lógica de invocação do processo.

Duas estratégias, nesta ordem de preferência (ADR-018 §4):

- `cut_clip_from_recording` — recorta vídeo **de verdade** da gravação
  contínua local, com movimento. Só é possível no edge, e só depois da ADR-018:
  é justamente porque a gravação contínua passou a ficar na máquina do cliente
  que existe um arquivo para recortar. Antes disso, o único material disponível
  na hora de montar o clipe era o JPEG do evento.
- `render_freeze_frame_clip` — fallback: o frame único esticado em vídeo.
  Continua sendo o caminho de setups Nível 3 (VPS faz tudo, sem gravação local)
  e de câmeras com gravação desligada.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# `recordPath: /recordings/%path/%Y-%m-%d_%H-%M-%S-%f` (infra/mediamtx/mediamtx.yml)
_SEGMENT_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-(\d+)")


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


def find_segment_for(recordings_dir: str, mediamtx_path: str, moment: datetime) -> tuple[str, float] | None:
    """Acha o segmento da gravação contínua que contém `moment`.

    Retorna `(caminho_do_segmento, offset_em_segundos_dentro_dele)` ou `None` se
    não houver gravação cobrindo aquele instante (câmera com gravação
    desligada, segmento já expirado pela retenção local, ou evento anterior ao
    início da gravação).

    O nome do arquivo é a única fonte do horário de início do segmento — é o
    que `recordPath` do MediaMTX grava. Comparações são feitas em horário
    **local** porque é assim que o MediaMTX formata `%Y-%m-%d_%H-%M-%S`, e o
    relógio do mini-PC do cliente é o mesmo para os dois lados.
    """
    segments_dir = Path(recordings_dir) / mediamtx_path
    if not segments_dir.is_dir():
        return None

    target = moment.astimezone() if moment.tzinfo else moment.replace(tzinfo=UTC).astimezone()
    best: tuple[str, float] | None = None
    best_start: datetime | None = None

    for entry in segments_dir.iterdir():
        match = _SEGMENT_NAME_RE.match(entry.name)
        if not match or not entry.is_file():
            continue
        try:
            start = datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S").astimezone()
        except ValueError:
            continue
        if start > target:
            continue
        # O último segmento que começou antes do evento é o que o contém — os
        # segmentos do MediaMTX são contíguos por construção.
        if best_start is None or start > best_start:
            best_start = start
            best = (str(entry), (target - start).total_seconds())

    return best


async def cut_clip_from_recording(
    recordings_dir: str,
    mediamtx_path: str,
    occurred_at: datetime,
    duration_seconds: int,
    seconds_before: int = 5,
    max_height: int = 480,
) -> str | None:
    """Recorta um clipe real da gravação contínua local, reencodado para a VPS.

    Retorna o path do MP4 temporário, ou `None` quando não há gravação cobrindo
    o evento — o chamador cai no freeze-frame nesse caso.

    `seconds_before` puxa o corte para antes do instante do evento: um alerta
    de intrusão em que o vídeo começa com a pessoa já dentro da cena é bem
    menos útil do que um que mostra a aproximação.

    O reencode para `max_height` não é cosmético — é o que faz o clipe caber no
    orçamento de storage da VPS (ADR-018 §4: ~500 KB a 480 p contra ~3,7 MB a
    720 p). Ele roda aqui, no hardware do cliente, que é exatamente o ponto:
    a VPS nunca toca em ffmpeg para eventos de edge.
    """
    found = find_segment_for(recordings_dir, mediamtx_path, occurred_at)
    if found is None:
        logger.info(
            "Sem gravação contínua cobrindo o evento (path=%s momento=%s) — usando freeze-frame",
            mediamtx_path, occurred_at,
        )
        return None

    segment_path, offset = found
    # Um evento nos primeiros segundos de um segmento não tem `seconds_before`
    # para trás; corta do início em vez de falhar (o clipe sai mais curto).
    start_at = max(0.0, offset - seconds_before)

    fd, output_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y",
        # `-ss` antes do `-i`: seek rápido por keyframe. Depois do `-i` seria
        # exato ao frame, mas decodificaria o segmento inteiro até o ponto —
        # num mini-PC, com segmento de 15 min, isso é a diferença entre
        # instantâneo e inviável.
        "-ss", f"{start_at:.3f}",
        "-i", segment_path,
        "-t", str(duration_seconds),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-an",  # sem áudio: dobra o custo de banda sem ajudar na triagem
        "-vf", f"scale=-2:'min({max_height},ih)'",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]

    def _run_ffmpeg() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    result = await asyncio.to_thread(_run_ffmpeg)
    if result.returncode != 0 or os.path.getsize(output_path) == 0:
        os.remove(output_path)
        logger.warning(
            "Falha ao recortar clipe da gravação (%s @ %.1fs): %s",
            segment_path, start_at, result.stderr.decode()[-300:],
        )
        return None

    return output_path
