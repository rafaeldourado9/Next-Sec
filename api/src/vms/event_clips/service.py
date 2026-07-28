"""Application service de event_clips — geração e upload do clipe do evento.

LIMITAÇÃO CONHECIDA (v1, ver reuse-plan.md): o Next Sec ainda não tem um
ring-buffer de vídeo contínuo (nem no edge agent, nem no serviço de analytics
— confirmado, não existe no código reaproveitado). Por isso, o "clipe" desta
primeira versão é o frame único do evento (já capturado pelo plugin) esticado
em um vídeo de `duration_seconds` via ffmpeg — uma prova visual real, mas sem
movimento. Um ring-buffer de frames de fato é a melhoria natural de uma
próxima sprint, não deste MVP.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vms.event_clips.domain import ClipStatus, EventClip
from vms.event_clips.repository import EventClipRepository, EventClipRepositoryPort
from vms.events.images import SNAPSHOTS_DIR
from vms.infrastructure.database import get_session_factory
from vms.infrastructure.storage_provider import StorageProvider, build_storage_provider
from vms.shared.exceptions import NotFoundError

logger = logging.getLogger(__name__)


class EventClipService:
    """Casos de uso de geração e consulta do clipe de um evento."""

    def __init__(
        self,
        clip_repo: EventClipRepositoryPort,
        session: AsyncSession,
        storage: StorageProvider | None = None,
    ) -> None:
        self._clips = clip_repo
        self._session = session
        self._storage = storage or build_storage_provider()

    async def get_clip(self, vms_event_id: str) -> EventClip:
        """Retorna o clipe de um evento. Lança NotFoundError se ainda não existir."""
        clip = await self._clips.get_by_event(vms_event_id)
        if not clip:
            raise NotFoundError("EventClip", vms_event_id)
        return clip

    async def generate_and_upload(
        self, vms_event_id: str, tenant_id: str, image_path: str | None
    ) -> EventClip:
        """Gera o clipe a partir do snapshot do evento e envia ao storage provider.

        Idempotente: se já existe um clipe para este evento, retorna o existente
        em vez de gerar de novo (evita duplicar upload em caso de retry).

        Usa sessões de banco curtas e independentes da `self._session` injetada
        (commitadas/fechadas logo após cada leitura/escrita), em vez de manter
        uma única transação aberta do início ao fim: o ffmpeg + upload pro
        storage são a parte lenta e não devem segurar uma conexão do pool
        (só 10 no worker) presa em "idle in transaction" por toda a duração —
        foi exatamente isso que já causou vazamento de pool/memória uma vez
        (ver ADR-015, addendum) num ponto próximo (notifications), sob rajada
        de eventos.
        """
        existing = await self._clips.get_by_event(vms_event_id)
        if existing:
            return existing

        clip = await self._clips.create(
            EventClip(id=str(uuid.uuid4()), vms_event_id=vms_event_id)
        )
        await self._session.commit()

        if not image_path:
            return await self._update_status_isolated(
                clip.id, ClipStatus.FAILED,
                error_message="Evento sem snapshot — nada para gerar",
            )

        snapshot_file = SNAPSHOTS_DIR / image_path
        if not snapshot_file.is_file():
            return await self._update_status_isolated(
                clip.id, ClipStatus.FAILED,
                error_message=f"Snapshot não encontrado em disco: {image_path}",
            )

        clip = await self._update_status_isolated(clip.id, ClipStatus.STAGED)

        try:
            local_mp4 = await self._render_freeze_frame_clip(
                str(snapshot_file), duration_seconds=clip.duration_seconds
            )
            try:
                key = f"{tenant_id}/{clip.id}.mp4"
                url = await self._storage.upload(local_mp4, key, content_type="video/mp4")
            finally:
                os.remove(local_mp4)

            return await self._update_status_isolated(
                clip.id, ClipStatus.UPLOADED, storage_ref=key, storage_url=url
            )
        except Exception as exc:
            logger.exception("Falha ao gerar/enviar clipe do evento %s", vms_event_id)
            return await self._update_status_isolated(
                clip.id, ClipStatus.FAILED, error_message=str(exc)[:1000]
            )

    async def _update_status_isolated(
        self, clip_id: str, status: ClipStatus, **fields: object
    ) -> EventClip:
        """Atualiza o status do clipe numa sessão própria, curta, commitada e
        fechada na hora — não usa `self._session`/`self._clips` de propósito,
        pra não reter a conexão do chamador (`task_dispatch_event_notifications`)
        presa durante o ffmpeg/upload que roda entre as chamadas."""
        factory = get_session_factory()
        async with factory() as session:
            repo = EventClipRepository(session)
            clip = await repo.update_status(clip_id, status, **fields)
            await session.commit()
            return clip

    async def _render_freeze_frame_clip(self, image_path: str, duration_seconds: int) -> str:
        """Gera um MP4 de `duration_seconds` a partir de uma imagem única, via ffmpeg."""
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
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            os.remove(output_path)
            raise RuntimeError(f"ffmpeg falhou (código {proc.returncode}): {stderr.decode()[-500:]}")
        return output_path


def build_event_clip_service(session: AsyncSession) -> EventClipService:
    """Factory que constrói EventClipService com implementações concretas."""
    return EventClipService(clip_repo=EventClipRepository(session), session=session)
