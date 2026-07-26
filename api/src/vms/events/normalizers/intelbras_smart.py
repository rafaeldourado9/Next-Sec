"""Normalizador de Smart Events Intelbras (FaceRec, PeopleCount, Intrusion, etc.)."""
from __future__ import annotations

import logging
from datetime import datetime

from vms.events.domain import AlprDetection
from vms.events.normalizers.base import NormalizerPort, registry

logger = logging.getLogger(__name__)

# Mapeamento de eventos Intelbras para tipos VMS
EVENT_TYPE_MAP = {
    # Segurança / Analytics
    "CrossLineDetection": "analytics.line_crossing",
    "IntrusionDetection": "analytics.intrusion",
    "AreaDetection": "analytics.intrusion",
    "FaceDetection": "analytics.face_detected",
    "FaceRecognition": "analytics.face_recognized",
    "PeopleCounting": "analytics.people_count",
    "VehicleCounting": "analytics.vehicle_count",
    # Camera status
    "VideoTampering": "camera.tampering",
    "VideoBlind": "camera.tampering",
    "VideoLoss": "camera.video_loss",
    "MotionDetection": "motion.detected",
    # Alarmes
    "IOAlarm": "alarm.io",
}


class IntelbrasSmartNormalizer(NormalizerPort):
    """
    Normaliza Smart Events de câmeras/DVRs Intelbras para VmsEvent.

    Suporta:
    - CrossLineDetection (cruzamento de linha)
    - IntrusionDetection / AreaDetection (invasão de área)
    - FaceRecognition (reconhecimento facial nativo)
    - PeopleCounting (contagem de pessoas nativa)
    - VehicleCounting (contagem de veículos nativa)
    - VideoTampering / VideoLoss (status da câmera)
    - MotionDetection (detecção de movimento)
    - IOAlarm (alarmes de E/S)
    """

    manufacturer = "intelbras_smart"

    def can_handle(self, raw: dict) -> bool:
        """Detecta se é um Smart Event Intelbras."""
        # Formato: {"event": "CrossLineDetection", ...}
        event_type = raw.get("event") or raw.get("eventType") or raw.get("EventType")
        if not event_type:
            return False

        # Ignora ALPR (já tem normalizador dedicado)
        if event_type.lower() in ("alpr", "anpr", "placa"):
            return False

        return event_type in EVENT_TYPE_MAP

    def normalize(self, raw: dict, camera_id: str, tenant_id: str) -> AlprDetection:
        """Normaliza Smart Event para AlprDetection (usado como evento genérico)."""
        event_type_raw = raw.get("event") or raw.get("eventType") or raw.get("EventType", "Unknown")
        event_type = EVENT_TYPE_MAP.get(event_type_raw, f"intelbras.{event_type_raw.lower()}")

        # Extrair timestamp
        timestamp = self._parse_timestamp(raw)

        # Montar payload estruturado
        payload = {
            "eventType": event_type_raw,
            "channel": raw.get("channel") or raw.get("channelID"),
        }

        # Adicionar dados específicos baseados no tipo de evento
        data = raw.get("data") or raw.get("Data") or {}
        if data:
            payload.update(data)

        # Campos soltos no payload principal
        for key in ["person_id", "person_name", "group_id", "similarity", "access_granted",
                    "enter", "exit", "current", "count", "license_plate"]:
            if key in raw:
                payload[key] = raw[key]

        # Imagem base64 se disponível
        image_b64 = raw.get("face_image") or raw.get("image") or raw.get("snapshot")

        return AlprDetection(
            camera_id=camera_id,
            tenant_id=tenant_id,
            plate="",  # Smart events não têm placa
            confidence=float(payload.get("similarity") or payload.get("confidence", 0)),
            manufacturer=self.manufacturer,
            timestamp=timestamp,
            raw_payload=raw,
            image_b64=image_b64,
        )

    @staticmethod
    def _parse_timestamp(raw: dict) -> datetime:
        """Extrai timestamp do payload."""
        ts = raw.get("timestamp") or raw.get("dateTime") or raw.get("DateTime") or raw.get("time")
        if ts:
            # Tenta múltiplos formatos
            ts_str = str(ts).replace("Z", "+00:00")
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    continue
        return datetime.utcnow()


# Auto-registrar
registry.register(IntelbrasSmartNormalizer())
