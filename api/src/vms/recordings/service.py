"""Application service de recordings — índice de cobertura + playback URL assinado.

NÃO é dono dos arquivos gravados — o MediaMTX grava e apaga sozinho
(record/recordDeleteAfter, configurado por `cameras/mediamtx.py`). Este
serviço só mantém `recording_windows` (índice leve de "quais intervalos têm
gravação", pra timeline) e monta a URL assinada de playback que o frontend
usa contra o `/mediamtx-playback/` do MediaMTX (via nginx auth_request).
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from vms.infrastructure.security import create_playback_token
from vms.recordings.domain import RecordingWindow
from vms.recordings.repository import RecordingWindowRepositoryPort

logger_name = __name__

# Formato do recordPath em mediamtx.yml: %Y-%m-%d_%H-%M-%S-%f
_SEGMENT_FILENAME_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6})"
)


def parse_segment_start(segment_path: str) -> datetime | None:
    """Extrai o timestamp de início do segmento a partir do nome do arquivo.

    MediaMTX não manda um campo de timestamp separado no webhook — só o
    caminho do arquivo, que já embute o horário de início (recordPath usa
    %Y-%m-%d_%H-%M-%S-%f).
    """
    match = _SEGMENT_FILENAME_RE.search(segment_path)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("ts"), "%Y-%m-%d_%H-%M-%S-%f").replace(tzinfo=UTC)
    except ValueError:
        return None


class RecordingService:
    """Casos de uso do bounded context de recordings."""

    def __init__(self, window_repo: RecordingWindowRepositoryPort) -> None:
        self._windows = window_repo

    async def record_segment_complete(
        self, camera_id: str, tenant_id: str, segment_path: str
    ) -> None:
        """Estende a janela de cobertura aberta, ou abre uma nova se houve gap."""
        segment_started_at = parse_segment_start(segment_path)
        if segment_started_at is None:
            return

        now = datetime.now(UTC)
        open_window = await self._windows.get_open_window(camera_id)

        if open_window and open_window.is_contiguous_with(segment_started_at):
            await self._windows.extend(
                open_window.id, ended_at=now, segment_count=open_window.segment_count + 1
            )
            return

        await self._windows.create(
            RecordingWindow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                camera_id=camera_id,
                started_at=segment_started_at,
                ended_at=now,
                segment_count=1,
            )
        )

    async def get_available_ranges(
        self, camera_id: str, tenant_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        """Intervalos com gravação disponível, pra sombrear a timeline no frontend."""
        windows = await self._windows.list_in_range(camera_id, tenant_id, start, end)
        return [
            {
                "start": w.started_at.isoformat(),
                "end": (w.ended_at or datetime.now(UTC)).isoformat(),
            }
            for w in windows
        ]

    def build_playback_url(
        self, camera_id: str, tenant_id: str, start: datetime, end: datetime
    ) -> dict:
        """Monta a URL assinada de playback (via /mediamtx-playback/, atrás do
        auth_request do nginx) pro intervalo pedido."""
        start_iso = start.isoformat()
        end_iso = end.isoformat()
        token = create_playback_token(tenant_id, camera_id, start_iso, end_iso)
        mediamtx_path = f"tenant-{tenant_id}/cam-{camera_id}"
        playback_url = (
            f"/mediamtx-playback/get?path={mediamtx_path}"
            f"&start={start_iso}&end={end_iso}&token={token}"
        )
        return {"playback_url": playback_url, "token": token}


def build_recording_service(window_repo: RecordingWindowRepositoryPort) -> RecordingService:
    """Factory que constrói RecordingService com implementações concretas."""
    return RecordingService(window_repo)
