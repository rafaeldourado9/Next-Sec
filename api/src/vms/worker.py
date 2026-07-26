"""Configuração dos workers ARQ.

Dois workers:
- WorkerSettings        → fila "arq:high": notificações, watchdog de câmera, audit
- LowPriorityWorkerSettings → fila "arq:low": reports PDF (pesados, sem urgência)

Para rodar os dois, adicione no docker-compose:
    worker-high:
        command: python -m arq vms.worker.WorkerSettings
    worker-low:
        command: python -m arq vms.worker.LowPriorityWorkerSettings

NOTA (Next Sec): a versão original (vms/) também tinha tasks de recordings
(segmentação/HLS/cleanup), billing (snapshot/invoice) e um pipeline de
detecção motion/person/vehicle sobre gravações (frame_extractor,
tasks_motion, tasks_dynamic) — todos dependentes de módulos não copiados
(`recordings`, `billing`) ou superados pelo serviço de analytics em tempo
real (`analytics/` na raiz do workspace, plugins intrusion/face_recognition).
Removidos daqui para não quebrar o import do worker — ver
.genesis/architecture/reuse-plan.md.
"""

from __future__ import annotations

import logging

import arq
from arq.connections import RedisSettings

from vms.infrastructure.config import get_settings
from vms.cameras.tasks import task_camera_watchdog
from vms.notifications.tasks import task_dispatch_notification
from vms.reports.tasks import task_auto_monthly_report, task_generate_report
from vms.audit.tasks import task_ensure_audit_partitions

logger = logging.getLogger(__name__)

_ARQ_HIGH = "arq:high"
_ARQ_LOW = "arq:low"


async def startup(ctx: dict) -> None:
    """Inicializa recursos compartilhados para o worker."""
    import httpx
    import redis.asyncio as aioredis
    from arq import create_pool
    from arq.connections import RedisSettings as ArqRedisSettings
    from vms.infrastructure.database import create_engine, init_db

    settings = get_settings()

    # Banco de dados — pool menor: worker é processo único com tasks async
    engine = create_engine(settings.database_url, for_worker=True)
    init_db(engine)
    ctx["db_engine"] = engine
    logger.info("Worker: banco de dados inicializado")

    # Redis para deduplicação ALPR e cache
    redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=False,
        max_connections=10,
        socket_keepalive=True,
        retry_on_timeout=True,
    )
    ctx["redis"] = redis_client
    logger.info("Worker: Redis conectado")

    # ARQ pool para enfileiramento de sub-tasks a partir de jobs do worker
    ctx["arq_redis"] = await create_pool(ArqRedisSettings.from_dsn(settings.redis_url))
    logger.info("Worker: ARQ redis pool criado")

    # httpx client compartilhado — reutiliza conexões TCP entre jobs (keep-alive)
    # Sem isso cada task_dispatch_notification abre e fecha uma conexão TCP nova.
    ctx["http_client"] = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
            keepalive_expiry=30,
        ),
        headers={"User-Agent": "VMS-Webhook/1.0"},
    )
    logger.info("Worker: httpx client inicializado")


async def shutdown(ctx: dict) -> None:
    """Fecha recursos do worker."""
    from vms.infrastructure.database import close_db

    if "http_client" in ctx:
        await ctx["http_client"].aclose()

    if "arq_redis" in ctx:
        await ctx["arq_redis"].aclose()

    if "redis" in ctx:
        await ctx["redis"].aclose()

    await close_db()
    logger.info("Worker: recursos encerrados")


class WorkerSettings:
    """Worker de alta prioridade: notificações, watchdog de câmera, audit.

    Usa a fila padrão do ARQ ("arq:queue") para não exigir _queue_name
    nos enqueue_job existentes.

    TODO (Next Sec, gap real — ver reuse-plan.md): adicionar aqui as tasks
    novas do fluxo evento→clipe→storage→notificação: upload do clipe ao
    MinIO (staging), upload ao StorageProvider (Google Drive) e o dispatch
    via ChannelAdapter (WhatsApp/Arcanum) quando destination_type='contact'.
    """

    functions = [
        task_dispatch_notification,
        task_camera_watchdog,
        task_ensure_audit_partitions,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs = [
        arq.cron(task_camera_watchdog, second={0, 30}),
        arq.cron(task_ensure_audit_partitions, day=1, hour=0, minute=1),
    ]
    max_jobs = 50
    job_timeout = 300


class LowPriorityWorkerSettings:
    """Worker de baixa prioridade: geração de relatórios PDF."""

    queue_name = _ARQ_LOW
    functions = [
        task_generate_report,
        task_auto_monthly_report,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs = [
        # Dia 1 de cada mês às 6h UTC
        arq.cron(task_auto_monthly_report, day=1, hour=6, minute=0),
    ]
    max_jobs = 3  # reports são pesados — limita paralelismo no nível do worker
    job_timeout = 600  # PDF de um mês de dados pode demorar
