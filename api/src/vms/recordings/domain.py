"""Entidade de domínio de recordings — janela contígua de gravação."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Gap máximo entre o fim de uma janela e o início do próximo segmento pra
# ainda considerar "contíguo" — recordSegmentDuration é 15min, então um gap
# de até 2x isso ainda é razoável tolerar (ex.: um segmento perdido, retry
# de reconexão RTSP) sem abrir uma janela nova por causa de um hiccup normal.
_GAP_TOLERANCE = timedelta(minutes=30)


@dataclass
class RecordingWindow:
    """Sessão contígua de gravação de uma câmera (não é 1 linha por segmento)."""

    id: str
    tenant_id: str
    camera_id: str
    started_at: datetime
    ended_at: datetime | None = None
    segment_count: int = 1

    def is_contiguous_with(self, segment_started_at: datetime) -> bool:
        """True se um segmento iniciado em `segment_started_at` ainda estende esta janela."""
        reference = self.ended_at or self.started_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=segment_started_at.tzinfo)
        return segment_started_at <= reference + _GAP_TOLERANCE
