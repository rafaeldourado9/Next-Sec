"""Utilitários para salvar imagens de eventos em disco."""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path(os.environ.get("SNAPSHOTS_PATH", "/snapshots"))


def save_event_image(
    tenant_id: str,
    event_id: str,
    image_b64: str | None,
    occurred_at: datetime,
) -> str | None:
    """Salva imagem base64 em disco e retorna o caminho relativo.

    Retorna None se não houver imagem ou se falhar ao salvar.
    """
    if not image_b64:
        return None

    try:
        # Limpa prefixo data:image/...;base64,
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]

        image_bytes = base64.b64decode(image_b64)
        if len(image_bytes) == 0:
            return None

        # Estrutura: /snapshots/events/{tenant_id}/{YYYY}/{MM}/{DD}/{event_id}.jpg
        date_path = occurred_at.strftime("%Y/%m/%d")
        dir_path = SNAPSHOTS_DIR / "events" / tenant_id / date_path
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{event_id}.jpg"
        file_path.write_bytes(image_bytes)

        # Retorna caminho relativo a partir de /snapshots
        rel_path = file_path.relative_to(SNAPSHOTS_DIR)
        return str(rel_path).replace("\\", "/")
    except Exception as exc:
        logger.warning("Falha ao salvar imagem do evento %s: %s", event_id, exc)
        return None
