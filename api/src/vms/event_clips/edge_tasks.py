"""Task ARQ do worker de edge (Nível 1 — ver ADR-017 §1 e ADR-018 §4). Gera o
MP4 localmente (ffmpeg, hardware do cliente) e envia pra VPS central. É o único
lugar do Nível 1 onde ffmpeg roda de verdade — a carga que causou o incidente
de produção (load average 151/171, ver ADR-015/016) fica inteiramente fora da
VPS compartilhada para esses eventos.

**Clipe com movimento (ADR-018 §4).** Até aqui o "clipe" era o JPEG do evento
esticado em vídeo — não havia outra opção, porque nada guardava vídeo contínuo
acessível na hora de montá-lo. Com a gravação contínua morando na máquina do
cliente, o edge agora recorta vídeo de verdade da própria gravação, com
`seconds_before` de contexto antes do evento, e só cai no freeze-frame quando
não há gravação cobrindo aquele instante (câmera com gravação desligada ou
evento fora da janela de retenção local).

Fila de retry: **não** duplica nem importa a fila SQLite do `analytics`
(`analytics/core/outbox.py`, S6-02) — usa o retry nativo do próprio ARQ
(`arq.Retry`, com `defer` calculado como o mesmo backoff exponencial 5s→5min
da ADR-017 §2) em vez disso. Razão: `api/` e `analytics/` são dois
processos/imagens Docker diferentes sem pacote compartilhado hoje; ARQ já
resolve exatamente o problema de "reenfileirar com backoff até dar certo"
para jobs, então reaproveitá-lo aqui evita tanto duplicar ~80 linhas de
SQLite quanto criar um pacote novo só para isso neste sprint (reavaliar se
um terceiro consumidor do outbox aparecer).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

import httpx
from arq import Retry

from vms.event_clips.ffmpeg import cut_clip_from_recording, render_freeze_frame_clip

logger = logging.getLogger(__name__)

_DEFAULT_CLIP_DURATION_SECONDS = 15
_DEFAULT_SECONDS_BEFORE = 5
_DEFAULT_MAX_HEIGHT = 480
_INITIAL_BACKOFF_SECONDS = 5
_MAX_BACKOFF_SECONDS = 300

# Margem antes de tentar recortar da gravação. O MediaMTX escreve o segmento
# fmp4 em partes (`recordPartDuration: 1s`), então o trecho POSTERIOR ao evento
# ainda não está em disco no instante em que o evento é confirmado — recortar
# na hora produziria um clipe truncado no melhor caso. Espera a janela do clipe
# passar, mais uma folga para a última parte ser descarregada.
_SEGMENT_FLUSH_MARGIN_SECONDS = 3


def _backoff_seconds(job_try: int) -> int:
    """Mesmo backoff exponencial (5s, 10s, 20s... teto 5min) da fila SQLite
    do analytics (ver ADR-017 §2) — aqui expresso via `job_try` do ARQ."""
    return min(_INITIAL_BACKOFF_SECONDS * (2 ** max(job_try - 1, 0)), _MAX_BACKOFF_SECONDS)


async def _build_clip(
    ctx: dict,
    snapshot_local_path: str,
    duration_seconds: int,
    mediamtx_path: str | None,
    occurred_at_iso: str | None,
) -> str | None:
    """Vídeo real da gravação local quando possível; freeze-frame quando não.

    Devolve `None` só se as duas estratégias falharem — nesse caso o evento
    fica sem clipe, que é o comportamento best-effort já documentado (o evento
    em si e a foto já subiram).
    """
    recordings_dir = ctx.get("recordings_dir") or os.environ.get("RECORDINGS_PATH", "/recordings")

    if mediamtx_path and occurred_at_iso:
        try:
            occurred_at = datetime.fromisoformat(occurred_at_iso)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)

            elapsed = (datetime.now(UTC) - occurred_at).total_seconds()
            still_missing = duration_seconds + _SEGMENT_FLUSH_MARGIN_SECONDS - elapsed
            if still_missing > 0:
                await asyncio.sleep(min(still_missing, duration_seconds + _SEGMENT_FLUSH_MARGIN_SECONDS))

            clip = await cut_clip_from_recording(
                recordings_dir=recordings_dir,
                mediamtx_path=mediamtx_path,
                occurred_at=occurred_at,
                duration_seconds=duration_seconds,
                seconds_before=int(ctx.get("clip_seconds_before", _DEFAULT_SECONDS_BEFORE)),
                max_height=int(ctx.get("clip_max_height", _DEFAULT_MAX_HEIGHT)),
            )
            if clip:
                return clip
        except Exception:
            logger.exception("Falha ao recortar clipe da gravação — caindo no freeze-frame")

    if not os.path.isfile(snapshot_local_path):
        logger.warning("Sem gravação e sem snapshot local (%s) — evento fica sem clipe", snapshot_local_path)
        return None

    try:
        return await render_freeze_frame_clip(snapshot_local_path, duration_seconds)
    except Exception:
        logger.exception("Falha ao renderizar clipe freeze-frame (ffmpeg)")
        return None


async def task_render_and_upload_edge_clip(
    ctx: dict,
    event_id: str,
    snapshot_local_path: str,
    duration_seconds: int = _DEFAULT_CLIP_DURATION_SECONDS,
    mediamtx_path: str | None = None,
    occurred_at_iso: str | None = None,
) -> None:
    """Monta o MP4 e envia via PUT à VPS central.

    `snapshot_local_path` é um caminho absoluto no disco LOCAL (mesmo volume
    `/snapshots` do container `analytics` do compose de edge) — nunca um path
    relativo da VPS central, que não teria esse arquivo. `mediamtx_path` e
    `occurred_at_iso` são opcionais para compatibilidade com jobs já
    enfileirados antes desta mudança; sem eles, o comportamento é o anterior
    (freeze-frame).

    Erros de renderização (ffmpeg) não são reenfileirados — best-effort, igual
    ao comportamento já documentado em `task_dispatch_event_notifications`: o
    evento em si já foi confirmado na VPS, só o clipe ficaria ausente. Erros
    de rede/5xx no PUT levantam `arq.Retry` (backoff exponencial via
    `ctx['job_try']`) — o próprio ARQ reagenda o job.
    """
    vms_api_url = ctx.get("vms_api_url") or os.environ.get("VMS_API_URL", "http://localhost:8000")
    vms_api_key = ctx.get("vms_api_key") or os.environ.get("VMS_API_KEY", "dev-analytics-key")

    local_mp4 = await _build_clip(
        ctx, snapshot_local_path, duration_seconds, mediamtx_path, occurred_at_iso
    )
    if local_mp4 is None:
        return

    client: httpx.AsyncClient | None = ctx.get("http_client")
    owns_client = client is None
    clip_url = f"{vms_api_url.rstrip('/')}/api/v1/edge/events/{event_id}/clip"
    try:
        if owns_client:
            client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        try:
            with open(local_mp4, "rb") as fh:
                files = {"clip_file": (os.path.basename(local_mp4), fh.read(), "video/mp4")}
            resp = await client.put(
                clip_url,
                files=files,
                headers={"Authorization": f"ApiKey {vms_api_key}"},
            )
            resp.raise_for_status()
            logger.info("Clipe de edge enviado com sucesso: evento=%s", event_id)
        finally:
            if owns_client:
                await client.aclose()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 413:
            # Cota de storage do cliente estourada (ADR-018 §4). Reenfileirar
            # não ajuda: só um admin aumentando a cota ou a retenção liberando
            # espaço muda a resposta, e insistir gastaria banda do cliente
            # para receber o mesmo 413.
            logger.error(
                "Cota de storage de clipes excedida — evento %s fica sem clipe (evento e foto "
                "subiram normalmente)", event_id,
            )
            return
        if 400 <= exc.response.status_code < 500:
            logger.error(
                "VPS rejeitou o clipe de edge (erro do próprio conteúdo, não reenfileirado): "
                "evento=%s status=%s",
                event_id, exc.response.status_code,
            )
            return
        logger.warning(
            "VPS retornou %s para o clipe de edge — reenfileirando: evento=%s",
            exc.response.status_code, event_id,
        )
        raise Retry(defer=_backoff_seconds(ctx.get("job_try", 1))) from exc
    except httpx.HTTPError as exc:
        logger.warning("Falha de rede ao enviar clipe de edge — reenfileirando: evento=%s", event_id)
        raise Retry(defer=_backoff_seconds(ctx.get("job_try", 1))) from exc
    finally:
        if os.path.exists(local_mp4):
            os.remove(local_mp4)
