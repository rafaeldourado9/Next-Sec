"""Normalizador de Smart Events Hikvision (LineDetection, FieldDetection, VMD, etc.)."""
from __future__ import annotations

import logging
from datetime import datetime

from vms.events.domain import AlprDetection
from vms.events.normalizers.base import NormalizerPort, registry

logger = logging.getLogger(__name__)

# Mapeamento de eventos ISAPI para tipos VMS
EVENT_TYPE_MAP = {
    "LineDetection": "analytics.line_crossing",
    "FieldDetection": "analytics.intrusion",
    "VMD": "motion_detected",
    "Tampering": "camera.tampering",
    "ShockDetection": "camera.shock",
    "IOAlarm": "alarm.io",
    "FaceDetection": "analytics.face_detected",
    "ANPR": "alpr.detected",
}


class HikvisionSmartNormalizer(NormalizerPort):
    """
    Normaliza Smart Events da Hikvision para VmsEvent.

    Suporta:
    - LineDetection (cruzamento de linha virtual)
    - FieldDetection (invasão de área configurada)
    - VMD (detecção de movimento)
    - Tampering (vandalismo/lente coberta)
    - ShockDetection (vibração/impacto)
    - IOAlarm (alarme de entrada/saída)
    - FaceDetection (detecção facial)
    """

    manufacturer = "hikvision_smart"

    def can_handle(self, raw: dict) -> bool:
        """Detecta se é um Smart Event Hikvision."""
        event_type = raw.get("eventType") or raw.get("EventNotificationAlert", {}).get("eventType")
        return event_type in EVENT_TYPE_MAP and event_type != "ANPR"  # ANPR já tem normalizer dedicado

    def normalize(self, raw: dict, camera_id: str, tenant_id: str) -> AlprDetection:
        """Normaliza Smart Event para AlprDetection (usado como evento genérico)."""
        event_type_raw = raw.get("eventType") or raw.get("EventNotificationAlert", {}).get("eventType", "Unknown")
        event_type = EVENT_TYPE_MAP.get(event_type_raw, f"hikvision.{event_type_raw.lower()}")

        # Extrair timestamp
        timestamp = self._parse_timestamp(raw)

        # Montar payload estruturado
        payload = {
            "eventType": event_type_raw,
            "channelID": raw.get("channelID"),
            "ipAddress": raw.get("ipAddress"),
        }

        # Adicionar dados específicos do evento
        event_data = raw.get(event_type_raw) or raw.get("EventNotificationAlert", {}).get(event_type_raw)
        if event_data:
            payload.update(event_data)

        return AlprDetection(
            camera_id=camera_id,
            tenant_id=tenant_id,
            plate="",  # Smart events não têm placa
            confidence=0.0,
            manufacturer=self.manufacturer,
            timestamp=timestamp,
            raw_payload=raw,
            image_b64=None,
        )

    @staticmethod
    def _parse_timestamp(raw: dict) -> datetime:
        """Extrai timestamp do payload."""
        ts = raw.get("dateTime") or raw.get("EventNotificationAlert", {}).get("dateTime")
        if ts:
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y%m%dT%H%M%S"):
                try:
                    return datetime.strptime(ts.replace("Z", "+00:00"), fmt)
                except ValueError:
                    continue
        return datetime.utcnow()


# Auto-registrar
registry.register(HikvisionSmartNormalizer())
