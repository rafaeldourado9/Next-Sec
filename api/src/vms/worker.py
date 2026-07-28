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
from vms.event_clips.tasks import task_cleanup_old_clips
from vms.recordings.tasks import task_prune_recording_windows
from vms.notifications.tasks import task_dispatch_event_notifications, task_dispatch_notification
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

    # Registra todos os models no metadata do SQLAlchemy antes de qualquer
    # query — o processo do worker só importa (transitivamente) os módulos
    # que as tasks registradas em `functions` precisam, então tabelas como
    # `tenants` nunca ficavam conhecidas e qualquer FK que apontasse pra elas
    # quebrava com NoReferencedTableError (achado: task_dispatch_event_
    # notifications falhava ao salvar notification_logs porque o mapper não
    # conseguia resolver a FK notification_logs.tenant_id -> tenants.id).
    # Mesma lista mantida em migrations/env.py, mais os models que essa task
    # usa e não estavam lá (contacts, event_clips).
    from vms.iam.models import TenantModel, UserModel, ApiKeyModel  # noqa: F401
    from vms.cameras.models import CameraModel, AgentModel  # noqa: F401
    from vms.events.models import VmsEventModel  # noqa: F401
    from vms.analytics.models import AnalyticsROI, PluginInstallation, AnalyticsEvent  # noqa: F401
    from vms.notifications.models import NotificationRuleModel, NotificationLogModel  # noqa: F401
    from vms.lgpd.models import RetentionPolicyModel, ConsentRecordModel  # noqa: F401
    from vms.audit.models import AuditLogModel  # noqa: F401
    from vms.billing.models import LicenseKeyModel  # noqa: F401
    from vms.contacts.models import ContactModel  # noqa: F401
    from vms.event_clips.models import EventClipModel  # noqa: F401
    from vms.recordings.models import RecordingWindowModel  # noqa: F401

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

    NOTA: o fluxo evento→clipe→storage→notificação (ver plugins/router.py)
    é enfileirado aqui via `task_dispatch_event_notifications` — rodava
    síncrono dentro de POST /plugins/events antes, e uma regra de
    notificação lenta/quebrada (retries de WhatsApp) atrasava o evento
    aparecer em tempo real pro usuário mesmo o registro já estando pronto.
    """

    functions = [
        task_dispatch_notification,
        task_dispatch_event_notifications,
        task_camera_watchdog,
        task_ensure_audit_partitions,
        task_cleanup_old_clips,
        task_prune_recording_windows,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs = [
        arq.cron(task_camera_watchdog, second={0, 30}),
        arq.cron(task_ensure_audit_partitions, day=1, hour=0, minute=1),
        arq.cron(task_cleanup_old_clips, hour=3, minute=30),
        arq.cron(task_prune_recording_windows, hour=3, minute=45),
    ]
    # Antes 50: numa VPS de 2 vCPU compartilhada, isso deixava rodar até 50
    # jobs concorrentes (cada `task_dispatch_event_notifications` pode disparar
    # ffmpeg pra gerar o clipe) contra um pool de só 10 conexões de banco —
    # sob rajada de eventos, o ffmpeg fica CPU-starved e mais lento, prendendo
    # sessões por mais tempo, o que derrubou a VPS de novo mesmo depois do
    # fix de c3efe4d (ver ADR-015, addendum). 10 alinha com o tamanho real do
    # pool de conexões do worker.
    max_jobs = 10
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
