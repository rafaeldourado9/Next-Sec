"""Normalizador de payload ALPR para câmeras Hikvision ANPR."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from vms.events.domain import AlprDetection
from vms.events.normalizers.base import registry

logger = logging.getLogger(__name__)


class HikvisionNormalizer:
    """
    Normaliza payload ANPR da Hikvision para AlprDetection.

    Aceita três formatos (todos convertidos para dict antes de chegar aqui):

    1. JSON direto:
       {"ANPR": {"licensePlate": "ABC1234", "confidence": 85}, "dateTime": "20260411105807"}

    2. XML convertido para dict (EventNotificationAlert):
       {"ANPR": {"licensePlate": "ABC1234", "confidence": "85"}, "dateTime": "2026-04-11T10:58:07+01:00"}

    3. Multipart com JSON (campo 'anpr_result') — já convertido pelo _parse_multipart.
    """

    manufacturer: str = "hikvision"

    def can_handle(self, raw: dict) -> bool:
        """Detecta payload Hikvision com evento ANPR."""
        # JSON/XML padrão
        if "ANPR" in raw:
            return True
        # Alguns modelos colocam a placa no nível raiz
        if "licensePlate" in raw:
            return True
        # XML com eventType=ANPR e placa aninhada
        if raw.get("eventType") == "ANPR" or raw.get("EventType") == "ANPR":
            return True
        return False

    def normalize(
        self, raw: dict, camera_id: str, tenant_id: str
    ) -> AlprDetection:
        """Extrai placa, confiança e timestamp do payload Hikvision."""
        anpr = raw.get("ANPR") or {}

        # Placa pode estar em ANPR.licensePlate ou no nível raiz
        plate = (
            anpr.get("licensePlate")
            or raw.get("licensePlate")
            or ""
        )
        plate = str(plate).upper().strip()
        if not plate:
            logger.debug("Hikvision normalizer: placa vazia, ignorando evento")
            return None

        # Confiança: normaliza para [0.0, 1.0] independente da escala enviada
        confidence_raw = (
            anpr.get("confidence")
            or anpr.get("confidenceLevel")
            or raw.get("confidence")
            or raw.get("confidenceLevel")
            or 0
        )
        try:
            v = float(confidence_raw)
            confidence = max(0.0, min(1.0, v / 100.0 if v > 1.0 else v))
        except (ValueError, TypeError):
            confidence = 0.0

        timestamp = _parse_hikvision_datetime(raw.get("dateTime") or anpr.get("dateTime") or "")
        image_b64 = raw.get("pictureBase64") or raw.get("picture")

        return AlprDetection(
            camera_id=camera_id,
            tenant_id=tenant_id,
            plate=plate,
            confidence=confidence,
            manufacturer=self.manufacturer,
            timestamp=timestamp,
            raw_payload=raw,
            image_b64=image_b64,
        )


# Regex para formato compacto YYYYMMDDHHmmss
_COMPACT_DT_RE = re.compile(r"^\d{14}$")
# Regex para ISO 8601 (com ou sem timezone)
_ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse_hikvision_datetime(value: str) -> datetime:
    """
    Converte string de data Hikvision para datetime.

    Suporta:
    - "20260411105807"            (YYYYMMDDHHmmss — formato antigo)
    - "2026-04-11T10:58:07+01:00" (ISO 8601 com timezone — XML)
    - "2026-04-11T10:58:07Z"      (ISO 8601 UTC — XML)
    - "2026-04-11T10:58:07"       (ISO 8601 sem timezone)
    """
    if not value:
        return datetime.utcnow()

    # Formato compacto: YYYYMMDDHHmmss
    if _COMPACT_DT_RE.match(value):
        try:
            return datetime.strptime(value, "%Y%m%d%H%M%S")
        except ValueError:
            pass

    # ISO 8601 — stripamos a parte de timezone e parseamos os primeiros 19 chars
    if _ISO_DT_RE.match(value):
        try:
            return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    return datetime.utcnow()


# Auto-registra ao importar
registry.register(HikvisionNormalizer())
