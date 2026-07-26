"""Tarefas ARQ para câmeras — watchdog de status online."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from vms.cameras.mediamtx import MediaMTXClient
from vms.cameras.models import CameraModel
from vms.infrastructure.database import get_session_factory

logger = logging.getLogger(__name__)

OFFLINE_GRACE_SECONDS = 90


async def task_camera_watchdog(ctx: dict) -> None:
    """Reconcilia is_online com o estado real do MediaMTX.

    Webhooks runOnReady/runOnNotReady do MediaMTX usam `curl -s` e engolem
    erros silenciosamente — quando a API está reiniciando ou o DNS hesita,
    o estado fica dessincronizado. Esse watchdog é a fonte da verdade.

    Regra:
    - path no MediaMTX com `ready=true` → DB is_online=True, last_seen_at=now
    - path no MediaMTX com `ready=false` por > OFFLINE_GRACE_SECONDS → is_online=False
    - path ausente → is_online=False
    """
    client = MediaMTXClient()
    paths = await client.list_paths()

    by_name: dict[str, dict] = {p.get("name", ""): p for p in paths if p.get("name")}

    factory = get_session_factory()
    async with factory() as session:
        cameras = (await session.scalars(select(CameraModel).where(CameraModel.is_active.is_(True)))).all()

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=OFFLINE_GRACE_SECONDS)
        online_ids: list[str] = []
        offline_ids: list[str] = []

        for cam in cameras:
            if cam.rtmp_stream_key:
                mediamtx_path = f"live/{cam.rtmp_stream_key}"
                source_url = ""
            else:
                mediamtx_path = f"tenant-{cam.tenant_id}/cam-{cam.id}"
                source_url = cam.rtsp_url or ""
            entry = by_name.get(mediamtx_path)

            if entry is None and source_url:
                # Path ausente após restart do MediaMTX — re-provisiona
                try:
                    await client.add_path(mediamtx_path, source_url=source_url)
                    logger.info("Re-provisionado path MediaMTX: %s", mediamtx_path)
                except Exception:
                    logger.warning("Falha ao re-provisionar %s", mediamtx_path, exc_info=True)

            ready = bool(entry and entry.get("ready"))

            if ready:
                online_ids.append(cam.id)
            else:
                # Stale path: ready=false e câmera marcada online há tempo → derruba
                last_seen = cam.last_seen_at
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                if cam.is_online and (last_seen is None or last_seen < cutoff):
                    offline_ids.append(cam.id)

        if online_ids:
            await session.execute(
                update(CameraModel)
                .where(CameraModel.id.in_(online_ids))
                .values(is_online=True, last_seen_at=now)
            )
        if offline_ids:
            await session.execute(
                update(CameraModel)
                .where(CameraModel.id.in_(offline_ids))
                .values(is_online=False)
            )

        if online_ids or offline_ids:
            await session.commit()
            logger.info(
                "Watchdog câmeras: %d online, %d → offline",
                len(online_ids), len(offline_ids),
            )
