"""Task ARQ do worker de edge (Nível 1, Docker dedicado no cliente — ver
ADR-017 §1). Gera o MP4 localmente (ffmpeg, hardware do cliente) a partir do
snapshot local e envia pro endpoint `PUT /plugins/events/{id}/clip` da VPS
central. É o único lugar do Nível 1 onde ffmpeg roda de verdade — a carga
que causou o incidente de produção (load average 151/171, ver ADR-015/016)
fica inteiramente fora da VPS compartilhada para esses eventos.

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

import logging
import os

import httpx
from arq import Retry

from vms.event_clips.ffmpeg import render_freeze_frame_clip

logger = logging.getLogger(__name__)

_DEFAULT_CLIP_DURATION_SECONDS = 8
_INITIAL_BACKOFF_SECONDS = 5
_MAX_BACKOFF_SECONDS = 300


def _backoff_seconds(job_try: int) -> int:
    """Mesmo backoff exponencial (5s, 10s, 20s... teto 5min) da fila SQLite
    do analytics (ver ADR-017 §2) — aqui expresso via `job_try` do ARQ."""
    return min(_INITIAL_BACKOFF_SECONDS * (2 ** max(job_try - 1, 0)), _MAX_BACKOFF_SECONDS)


async def task_render_and_upload_edge_clip(
    ctx: dict,
    event_id: str,
    snapshot_local_path: str,
    duration_seconds: int = _DEFAULT_CLIP_DURATION_SECONDS,
) -> None:
    """Renderiza o MP4 (freeze-frame do snapshot) e envia via PUT à VPS central.

    `snapshot_local_path` é um caminho absoluto no disco LOCAL (mesmo volume
    `/snapshots` do container `analytics` do compose de edge) — nunca um path
    relativo da VPS central, que não teria esse arquivo.

    Erros de renderização (ffmpeg) não são reenfileirados — best-effort, igual
    ao comportamento já documentado em `task_dispatch_event_notifications`: o
    evento em si já foi confirmado na VPS, só o clipe ficaria ausente. Erros
    de rede/5xx no PUT levantam `arq.Retry` (backoff exponencial via
    `ctx['job_try']`) — o próprio ARQ reagenda o job.
    """
    if not os.path.isfile(snapshot_local_path):
        logger.warning(
            "Snapshot local não encontrado para gerar clipe de edge: evento=%s path=%s",
            event_id, snapshot_local_path,
        )
        return

    vms_api_url = ctx.get("vms_api_url") or os.environ.get("VMS_API_URL", "http://localhost:8000")
    vms_api_key = ctx.get("vms_api_key") or os.environ.get("VMS_API_KEY", "dev-analytics-key")

    try:
        local_mp4 = await render_freeze_frame_clip(snapshot_local_path, duration_seconds)
    except Exception:
        logger.exception("Falha ao renderizar clipe de edge (ffmpeg) — evento %s", event_id)
        return

    client: httpx.AsyncClient | None = ctx.get("http_client")
    owns_client = client is None
    clip_url = f"{vms_api_url.rstrip('/')}/api/v1/plugins/events/{event_id}/clip"
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
