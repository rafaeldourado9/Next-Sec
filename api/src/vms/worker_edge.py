"""Configuração do worker ARQ de edge (Nível 1 — Docker dedicado no cliente,
ver ADR-016/017). Módulo separado de `worker.py` (não uma terceira classe
lá dentro): o worker central importa e registra models de TODO o schema de
negócio (tenants, contacts, notification_rules, event_clips...) porque suas
tasks tocam o Postgres central — o worker de edge não tem Postgres local
nenhum (decisão da ADR-017 §2) e só roda UMA task (`task_render_and_upload_
edge_clip`, que é ffmpeg + HTTP puro, sem SQLAlchemy). Colocar isso dentro de
`worker.py` obrigaria decidir, a cada mudança naquele arquivo, se ela também
vale pro edge — nunca vale, já que os dois processos não compartilham banco.
Um módulo próprio deixa essa fronteira explícita.

Rodar via:
    python -m arq vms.worker_edge.EdgeWorkerSettings
"""
from __future__ import annotations

import logging

from arq.connections import RedisSettings

from vms.event_clips.edge_tasks import task_render_and_upload_edge_clip

logger = logging.getLogger(__name__)


def _edge_settings():
    """Lê `VMS_API_URL`/`VMS_API_KEY`/`REDIS_URL` diretamente do ambiente, sem
    depender de `vms.infrastructure.config.Settings` (que traz `database_url`
    e dezenas de outros campos que não fazem sentido pra um processo sem
    Postgres) — mantém o worker de edge desacoplado do schema de config do
    worker central."""
    import os

    class _EdgeEnv:
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        vms_api_url = os.environ.get("VMS_API_URL", "http://localhost:8000")
        vms_api_key = os.environ.get("VMS_API_KEY", "dev-analytics-key")

    return _EdgeEnv()


async def on_startup(ctx: dict) -> None:
    """Inicializa só o que a task de clipe precisa: um httpx.AsyncClient
    compartilhado (keep-alive entre jobs) e a URL/key da VPS central. Sem
    banco, sem registro de models — ver docstring do módulo (ADR-017 §2)."""
    import httpx

    settings = _edge_settings()
    ctx["vms_api_url"] = settings.vms_api_url
    ctx["vms_api_key"] = settings.vms_api_key
    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        headers={"User-Agent": "VMS-EdgeWorker/1.0"},
    )
    logger.info("Worker de edge: iniciado (VPS central=%s)", settings.vms_api_url)


async def on_shutdown(ctx: dict) -> None:
    """Fecha o httpx.AsyncClient compartilhado."""
    if "http_client" in ctx:
        await ctx["http_client"].aclose()
    logger.info("Worker de edge: recursos encerrados")


class EdgeWorkerSettings:
    """Worker ARQ do Nível 1 (Docker dedicado no cliente) — só a task de
    geração/envio de clipe (ver ADR-017 §1). NÃO inclui `task_dispatch_
    notification`, `task_dispatch_event_notifications`, `task_cleanup_old_
    clips` nem qualquer outra task do worker central — essas continuam
    exclusivas dele, e nunca devem tocar contacts/notification_rules/Arcanum
    a partir do edge (ver ADR-017 §3).

    Fila ARQ própria, sobre o Redis LOCAL do `docker-compose.edge.yml` (nunca
    o Redis da VPS central) — quem enfileira é o `analytics/` local, logo
    após um `ingest_event` confirmadamente aceito (ver `VMSClient.
    _enqueue_local_clip_task`).
    """

    functions = [task_render_and_upload_edge_clip]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(_edge_settings().redis_url)
    # Hardware de cliente possivelmente modesto (mini-PC/NUC) — bem menor que
    # o max_jobs=10 do worker central (que já tinha sido reduzido de 50,
    # ver ADR-015/016), e sem pool de conexão de banco pra dimensionar contra.
    max_jobs = 3
    job_timeout = 120
