"""Tarefa ARQ de poda do índice de cobertura de gravação (recording_windows).

Não apaga vídeo — isso é o MediaMTX via recordDeleteAfter (configurado por
câmera a partir de retention_days, ver cameras/mediamtx.py). Esta task só
mantém recording_windows do mesmo tamanho que o retention real de cada
câmera, pra timeline não mostrar cobertura "disponível" de um trecho que o
MediaMTX já apagou.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vms.cameras.models import CameraModel
from vms.infrastructure.database import get_session_factory
from vms.recordings.repository import RecordingWindowRepository

logger = logging.getLogger(__name__)


async def task_prune_recording_windows(ctx: dict) -> None:
    """Remove janelas de cobertura mais antigas que o retention_days de cada câmera."""
    factory = get_session_factory()
    async with factory() as session:
        cameras = (
            await session.scalars(
                select(CameraModel).where(CameraModel.recording_enabled.is_(True))
            )
        ).all()

        repo = RecordingWindowRepository(session)
        total_removed = 0
        for cam in cameras:
            try:
                cutoff = datetime.now(UTC) - timedelta(days=cam.retention_days)
                removed = await repo.delete_before(cam.id, cutoff)
                total_removed += removed
            except Exception:
                logger.exception("Falha ao podar recording_windows da câmera %s", cam.id)

        await session.commit()
        logger.info(
            "Poda de recording_windows: %d janelas removidas (%d câmeras com gravação)",
            total_removed, len(cameras),
        )
