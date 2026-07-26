"""Normalizador genérico para payloads ALPR já normalizados."""
from __future__ import annotations

from datetime import datetime

from vms.events.domain import AlprDetection
from vms.events.normalizers.base import registry


class GenericNormalizer:
    """
    Normaliza payload ALPR pré-normalizado para AlprDetection.

    Formato esperado:
    {
        "plate": "ABC1D23",
        "confidence": 0.95,
        "timestamp": "2026-03-30T12:34:56Z"
    }
    """

    manufacturer: str = "generic"

    def can_handle(self, raw: dict) -> bool:
        """Retorna True se o payload contiver a chave 'plate' não vazia."""
        plate = raw.get("plate")
        return isinstance(plate, str) and bool(plate.strip())

    def normalize(
        self, raw: dict, camera_id: str, tenant_id: str
    ) -> AlprDetection | None:
        """Extrai placa, confiança e timestamp do payload genérico."""
        plate = str(raw["plate"]).upper().strip()
        if not plate:
            return None
        confidence = float(raw.get("confidence", 0.0))
        timestamp = _parse_generic_datetime(raw.get("timestamp", ""))
        image_b64 = raw.get("image_b64")
        bbox = raw.get("bbox")

        return AlprDetection(
            camera_id=camera_id,
            tenant_id=tenant_id,
            plate=plate,
            confidence=confidence,
            manufacturer=self.manufacturer,
            timestamp=timestamp,
            raw_payload=raw,
            image_b64=image_b64,
            bbox=bbox,
        )


def _parse_generic_datetime(value: str) -> datetime:
    """Converte string ISO 8601 (com ou sem 'Z') para datetime."""
    clean = value.rstrip("Z").replace("T", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(clean, fmt)
        except (ValueError, TypeError):
            continue
    return datetime.utcnow()


# Auto-registra ao importar
registry.register(GenericNormalizer())
