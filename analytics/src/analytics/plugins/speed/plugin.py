"""Plugin de Velocidade — estima a velocidade real (km/h) de veículos que
atravessam uma zona calibrada.

Diferente de um radar de verdade (que usa Doppler/laser), isso é estimativa
por vídeo: converte deslocamento em pixels entre a entrada e a saída da zona
em distância real, usando uma calibração de 2 pontos com distância conhecida
(ex: "essas duas marcas no chão distam 10 metros"). Funciona bem quando o
veículo atravessa a zona numa profundidade/direção razoavelmente constante
em relação à câmera — não é uma homografia completa, então câmeras com
perspectiva muito acentuada dentro da própria zona vão ter erro maior.

Eventos emitidos:
- analytics.speed.measured : veículo atravessou a zona calibrada, velocidade
  estimada anexada ao payload.
"""
from __future__ import annotations

import logging
import time

import numpy as np

from analytics.core.plugin_base import AnalyticsResult, FrameMetadata, ROIConfig
from analytics.core.yolo_base import YOLOPlugin

logger = logging.getLogger(__name__)

# Filtros de plausibilidade — descarta medições que são quase certamente
# ruído de tracking (troca de track ID, jitter de detecção) em vez de
# deslocamento real do veículo.
_MIN_DISPLACEMENT_NORM = 0.03  # ~3% da diagonal do frame, mínimo pra não ser jitter
_MAX_PLAUSIBLE_KMH = 180.0


def _centroid(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _meters_per_norm_unit(roi: ROIConfig) -> float | None:
    """Deriva a escala (metros por unidade normalizada 0-1) da calibração da
    ROI. Retorna None se a ROI não tiver calibração configurada."""
    a = roi.config.get("calib_point_a")
    b = roi.config.get("calib_point_b")
    dist_m = roi.config.get("calib_distance_m")
    if not a or not b or not dist_m:
        return None
    pixel_dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    if pixel_dist <= 0:
        return None
    return float(dist_m) / pixel_dist


class SpeedEstimationPlugin(YOLOPlugin):
    """
    Velocidade estimada — mede o tempo/deslocamento de um veículo entre a
    entrada e a saída de uma zona calibrada.

    Lógica:
    1. Rastreia detecções de veículo frame-a-frame (mesmo esquema de
       IoU+proximidade do plugin `intrusion` — câmera roda a poucos fps,
       então favorece proximidade sobre sobreposição de bbox).
    2. Ao entrar na zona, guarda posição+timestamp de entrada.
    3. Ao sair da zona, calcula distância percorrida (via calibração) e
       tempo decorrido → velocidade em km/h, emite um evento por passagem.
    """

    name = "speed"
    version = "1.0.0"
    roi_type = "speed"

    def __init__(self) -> None:
        super().__init__()
        self._tracks: dict[int, dict] = {}
        self._next_track_id = 0
        self._track_ttl: float = 2.0

    async def process_frame(
        self,
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        all_classes: set[int] = set()
        for roi in rois:
            classes = roi.config.get("classes", [2, 3, 5, 7])
            all_classes.update(classes)
        min_conf = min(
            (roi.config.get("min_confidence", 0.5) for roi in rois),
            default=0.5,
        )
        detections = self.detect(frame, conf=min_conf, classes=list(all_classes))
        return self._process_detections(detections, rois, metadata)

    async def process_shared_frame(
        self,
        detections: list[dict],
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        return self._process_detections(detections, rois, metadata)

    def _process_detections(
        self,
        detections: list[dict],
        rois: list[ROIConfig],
        metadata: FrameMetadata,
    ) -> list[AnalyticsResult]:
        results: list[AnalyticsResult] = []
        now = time.monotonic()

        expired = [
            tid for tid, t in self._tracks.items()
            if now - t["last_seen"] > self._track_ttl
        ]
        for tid in expired:
            self._tracks.pop(tid, None)

        matched: set[int] = set()
        for det in detections:
            cx, cy = _centroid(det["bbox"])
            best_tid = None
            best_score = -1.0
            for tid, track in self._tracks.items():
                if tid in matched:
                    continue
                iou = _iou(det["bbox"], track["bbox"])
                dist = ((cx - track["centroid"][0]) ** 2 + (cy - track["centroid"][1]) ** 2) ** 0.5
                dist_score = max(0, 1.0 - dist * 2.5)
                score = iou * 0.3 + dist_score * 0.7
                if score > best_score and score > 0.15:
                    best_score = score
                    best_tid = tid

            if best_tid is not None:
                self._tracks[best_tid].update({
                    "centroid": (cx, cy),
                    "bbox": det["bbox"],
                    "last_seen": now,
                    "detection": det,
                })
                matched.add(best_tid)
            else:
                tid = self._next_track_id
                self._next_track_id += 1
                self._tracks[tid] = {
                    "centroid": (cx, cy),
                    "bbox": det["bbox"],
                    "last_seen": now,
                    "detection": det,
                }

        for roi in rois:
            scale = _meters_per_norm_unit(roi)
            if scale is None:
                continue  # ROI sem calibração — plugin não faz nada nela

            roi_classes = set(roi.config.get("classes", [2, 3, 5, 7]))
            roi_conf = roi.config.get("min_confidence", 0.5)

            for tid, track in self._tracks.items():
                det = track.get("detection")
                if not det or det["class_id"] not in roi_classes or det["confidence"] < roi_conf:
                    continue

                state_key = f"speed_state_{roi.id}"
                in_roi = _point_in_polygon(track["centroid"], roi.polygon_points)
                state = track.get(state_key)

                if in_roi and state is None:
                    # Entrou na zona agora — marca ponto de partida.
                    track[state_key] = {
                        "entry_pos": track["centroid"],
                        "entry_ts": metadata.timestamp,
                        "last_pos": track["centroid"],
                        "last_ts": metadata.timestamp,
                    }
                elif in_roi and state is not None:
                    # Ainda dentro — atualiza último ponto conhecido (usado
                    # se o track expirar sem sair "oficialmente" da zona).
                    state["last_pos"] = track["centroid"]
                    state["last_ts"] = metadata.timestamp
                elif not in_roi and state is not None:
                    # Saiu da zona — calcula velocidade entrada->saída.
                    result = self._try_measure_speed(roi, det, metadata, state, scale)
                    if result is not None:
                        results.append(result)
                    track[state_key] = None

        return results

    def _try_measure_speed(
        self,
        roi: ROIConfig,
        detection: dict,
        metadata: FrameMetadata,
        state: dict,
        meters_per_norm: float,
    ) -> AnalyticsResult | None:
        entry_pos = state["entry_pos"]
        exit_pos = state["last_pos"]
        pixel_dist = ((exit_pos[0] - entry_pos[0]) ** 2 + (exit_pos[1] - entry_pos[1]) ** 2) ** 0.5
        if pixel_dist < _MIN_DISPLACEMENT_NORM:
            return None  # deslocamento pequeno demais — provável jitter, não movimento real

        elapsed_s = (state["last_ts"] - state["entry_ts"]).total_seconds()
        if elapsed_s <= 0:
            return None

        distance_m = pixel_dist * meters_per_norm
        speed_kmh = (distance_m / elapsed_s) * 3.6

        if speed_kmh > _MAX_PLAUSIBLE_KMH:
            logger.warning(
                "speed: descartando medição implausível (%.1f km/h) — roi=%s classe=%s",
                speed_kmh, roi.id, detection.get("class_name"),
            )
            return None

        return AnalyticsResult(
            plugin=self.name,
            camera_id=metadata.camera_id,
            tenant_id=metadata.tenant_id,
            roi_id=roi.id,
            event_type="analytics.speed.measured",
            payload={
                "roi_id": roi.id,
                "roi_name": roi.name,
                "class": detection["class_name"],
                "confidence": round(detection["confidence"], 2),
                "bbox": detection["bbox"],
                "speed_kmh": round(speed_kmh, 1),
                "elapsed_s": round(elapsed_s, 2),
            },
            occurred_at=metadata.timestamp,
            confidence=detection["confidence"],
        )
