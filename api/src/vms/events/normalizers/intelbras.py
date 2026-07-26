"""Normalizador de payload ALPR para câmeras Intelbras."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime

from vms.events.domain import AlprDetection
from vms.events.normalizers.base import registry

logger = logging.getLogger(__name__)

# Strings que aparecem no JPEG Dahua ITC mas NÃO são placas
_ITSCAM_NON_PLATE_STRINGS = frozenset({
    "Desconhecido", "Car come in", "Car go out", "ANPR", "DHAV3a",
    "JFIF", "Unknown", "Unkonwn",  # typo comum no firmware Dahua
})


def _extract_itscam_plate(raw_bytes: bytes) -> str | None:
    """
    Extrai placa do JPEG Dahua ITC / Intelbras ITSCAM.

    O JPEG tem uma seção APP2 proprietária com estrutura:
      ... ANPR ... Car come in ... Car go out ... <PLACA> ... DHAV3a ...

    A placa aparece como string ASCII após o bloco ANPR+Car labels.
    Se a câmera não detectou placa, o campo contém "Desconhecido".
    """
    anpr_pos = raw_bytes.find(b'ANPR')
    if anpr_pos < 0:
        return None

    # A placa está entre ANPR+200 e ANPR+2500 (depois dos labels Car come in / Car go out)
    search_zone = raw_bytes[anpr_pos + 200: anpr_pos + 2500]
    strings = re.findall(rb'[\x20-\x7E]{4,}', search_zone)

    for s in strings:
        text = s.decode("ascii", errors="ignore").strip()
        if len(set(text)) <= 2:  # strings triviais como "....", "0000"
            continue
        if text in _ITSCAM_NON_PLATE_STRINGS:
            if text == "Desconhecido" or text.startswith("Unknown"):
                logger.debug("ITSCAM: placa não detectada no frame (%s)", text)
                return None  # Nenhuma placa no frame — evento irrelevante
            continue
        # Encontrou a placa
        logger.debug("ITSCAM: placa extraída do JPEG: %s", text)
        return text.upper()

    return None


class IntelbrasNormalizer:
    """
    Normaliza payloads ANPR/LPR da Intelbras para AlprDetection.

    Suporta múltiplos formatos conforme o modelo:

    Formato 1 — ITSCAM 450/460 (campos em português):
        {"placa": "ABC1234", "confianca": 0.92, "timestamp": "2026-04-11T10:58:07"}

    Formato 2 — Modelos novos (campos em inglês):
        {"plate": "ABC1234", "confidence": 92, "timestamp": "2026-04-11T10:58:07", "channel": 1}

    Formato 3 — DVR/NVR Intelbras (lista de eventos):
        {
            "ChannelID": 1,
            "DateTime": "2026-04-11T10:58:07",
            "Events": [{"EventType": "AnprEvent", "LicensePlate": "ABC1234", "Confidence": 92}]
        }

    Formato 4 — ITSCAM ANPR via /NotificationInfo/TollgateInfo (Dahua ITC firmware):
        {"Picture": {"NormalPic": {"Content": "<base64 JPEG com placa embutida>"}}}
    """

    manufacturer: str = "intelbras"

    def can_handle(self, raw: dict) -> bool:
        """Detecta payload Intelbras com leitura de placa."""
        # Formato 4: ITSCAM /NotificationInfo/TollgateInfo — Picture com Plate e/ou NormalPic
        pic = raw.get("Picture")
        if isinstance(pic, dict) and ("Plate" in pic or "NormalPic" in pic):
            return True
        # Formato 1: campo 'placa' (PT)
        if "placa" in raw:
            return True
        # Formato 2: campo 'plate' APENAS se também tiver 'confianca' ou 'Events' (para não conflitar com generic)
        if "plate" in raw and ("confianca" in raw or "Events" in raw):
            return True
        # Formato 3: DVR/NVR com lista Events contendo AnprEvent
        events = raw.get("Events", [])
        if isinstance(events, list) and events:
            first = events[0] if isinstance(events[0], dict) else {}
            if "LicensePlate" in first or "Plate" in first or first.get("EventType") == "AnprEvent":
                return True
        return False

    def normalize(
        self, raw: dict, camera_id: str, tenant_id: str
    ) -> AlprDetection | None:
        """Extrai placa e confiança do payload Intelbras."""
        plate = ""
        confidence = 0.0
        timestamp = datetime.utcnow()
        image_b64 = None

        # Formato 4: ITSCAM /NotificationInfo/TollgateInfo
        pic = raw.get("Picture")
        if isinstance(pic, dict) and ("Plate" in pic or "NormalPic" in pic):
            plate_info = pic.get("Plate", {}) if isinstance(pic.get("Plate"), dict) else {}
            snap_info = pic.get("SnapInfo", {}) if isinstance(pic.get("SnapInfo"), dict) else {}
            normal_pic = pic.get("NormalPic", {}) if isinstance(pic.get("NormalPic"), dict) else {}

            # Placa via JSON estruturado (mais confiável que extração JPEG)
            plate = str(plate_info.get("PlateNumber") or "").upper().strip()

            # Fallback: extrai placa do JPEG se o campo JSON estiver vazio
            content = normal_pic.get("Content", "")
            if content:
                image_b64 = content
                if not plate:
                    try:
                        raw_bytes = base64.b64decode(content)
                        plate = _extract_itscam_plate(raw_bytes) or ""
                    except Exception as exc:
                        logger.debug("Erro ao extrair placa do JPEG ITSCAM: %s", exc)

            logger.info("ITSCAM frame | plate=%r pic_name=%s", plate, normal_pic.get("PicName", ""))

            if not plate:
                return None  # Frame sem placa detectada — ignorar

            confidence = _norm_confidence(plate_info.get("Confidence", 0))

            # Timestamp do SnapInfo (mais preciso que o JPEG)
            snap_time = snap_info.get("AccurateTime") or snap_info.get("SnapTime") or ""
            if snap_time:
                timestamp = _parse_intelbras_datetime(snap_time)

            # Extrai metadados de veículo de Picture.Plate antes de descartar o Picture
            # (o JPEG em NormalPic.Content é grande demais para salvar no DB)
            vehicle_meta: dict = {}
            _vehicle_field_map = [
                ("VehicleColor", "vehicle_color"),
                ("VehicleType",  "vehicle_type"),
                ("VehicleBrand", "vehicle_brand"),
                ("VehicleModel", "vehicle_model"),
                ("Speed",        "vehicle_speed"),
                ("Direction",    "direction"),
                ("Color",        "plate_color"),
            ]
            for src, dst in _vehicle_field_map:
                val = plate_info.get(src)
                if val not in (None, "", 0):
                    vehicle_meta[dst] = val

            return AlprDetection(
                camera_id=camera_id,
                tenant_id=tenant_id,
                plate=plate,
                confidence=confidence,
                manufacturer=self.manufacturer,
                timestamp=timestamp,
                raw_payload={
                    **{k: v for k, v in raw.items() if k != "Picture"},
                    **vehicle_meta,
                },
                image_b64=image_b64,
            )

        # Formato 3: DVR/NVR com Events[]
        events = raw.get("Events", [])
        if isinstance(events, list) and events:
            ev = events[0] if isinstance(events[0], dict) else {}
            plate = str(ev.get("LicensePlate") or ev.get("Plate") or "").upper().strip()
            if not plate:
                logger.debug("Intelbras normalizer: placa vazia, ignorando evento")
                return None
            confidence = _norm_confidence(ev.get("Confidence", 0))
            timestamp = _parse_intelbras_datetime(raw.get("DateTime", ""))

        # Formato 1 (PT) e Formato 2 (EN)
        if not plate:
            plate = str(raw.get("placa") or raw.get("plate") or "").upper().strip()
            confidence = _norm_confidence(raw.get("confianca") or raw.get("confidence") or 0)
            timestamp = _parse_intelbras_datetime(
                raw.get("timestamp") or raw.get("dateTime") or ""
            )
            image_b64 = raw.get("imagem") or raw.get("image")

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


def _norm_confidence(raw_value: object) -> float:
    """
    Normaliza confiança para o intervalo [0.0, 1.0].

    Câmeras Intelbras/Dahua podem enviar:
    - 0.92   → já normalizado (0–1)
    - 92     → percentual (0–100)
    - 118    → escala proprietária (0–127 em alguns firmwares) — clampeia em 1.0

    Regra: se o valor for > 1, divide por 100. Depois clampeia em [0.0, 1.0].
    """
    try:
        v = float(raw_value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0.0
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def _parse_intelbras_datetime(value: str) -> datetime:
    """Converte string de data Intelbras para datetime."""
    if not value:
        return datetime.utcnow()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(value[:19], fmt[:len(value[:19])])
        except (ValueError, TypeError):
            continue
    return datetime.utcnow()


# Auto-registra ao importar
registry.register(IntelbrasNormalizer())
