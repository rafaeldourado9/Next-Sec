"""Plugin de Cerca Virtual — detecta quando objetos CRUZAM o perímetro de uma ROI.

Diferente do modelo antigo de "presença na zona", este plugin rastreia objetos
frame-a-frame e emite eventos SOMENTE quando o centroide da bbox cruza a borda
do polígono (transição fora→dentro ou dentro→fora).

Eventos emitidos:
- analytics.intrusion.crossed : objeto cruzou a cerca
"""
from __future__ import annotations

import logging
import time

import numpy as np

from analytics.core.plugin_base import AnalyticsResult, FrameMetadata, ROIConfig
from analytics.core.yolo_base import YOLOPlugin

logger = logging.getLogger(__name__)


def _centroid(bbox: list[float]) -> tuple[float, float]:
    """Centroide de uma bbox [x1, y1, x2, y2]."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Ray-casting para verificar se ponto está dentro do polígono normalizado."""
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


def _iou(a: list[float], b: list[float]) -> float:
    """IoU entre duas bboxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class IntrusionDetectionPlugin(YOLOPlugin):
    """
    Cerca Virtual — detecta cruzamento de perímetro.

    Lógica:
    1. Rastreia cada detecção frame-a-frame via IoU + proximidade
    2. Guarda estado anterior (dentro/fora do polígono) para cada track
    3. Emite evento apenas na transição de estado (crossing)
    4. Cooldown por track para evitar spam
    """

    name = "intrusion"
    version = "2.0.0"
    roi_type = "intrusion"

    def __init__(self) -> None:
        super().__init__()
        # Tracks ativos: {track_id: {"centroid": (x,y), "in_roi": bool, "last_seen": float, "bbox": [...]}}
        self._tracks: dict[int, dict] = {}
        self._next_track_id = 0
        # Cooldown por track após crossing: {track_id: timestamp}
        self._cross_cooldowns: dict[int, float] = {}
        self._cooldown_seconds: float = 5.0
        # TTL para expirar tracks inativos
        self._track_ttl: float = 2.0  # segundos

    async def process_frame(
        self,
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        all_classes: set[int] = set()
        for roi in rois:
            classes = roi.config.get("classes", [0])
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

        # Expirar tracks antigos
        expired = [
            tid for tid, t in self._tracks.items()
            if now - t["last_seen"] > self._track_ttl
        ]
        for tid in expired:
            self._tracks.pop(tid, None)
            self._cross_cooldowns.pop(tid, None)

        # Atualizar tracks com novas detecções
        matched: set[int] = set()
        for det in detections:
            cx, cy = _centroid(det["bbox"])
            best_tid = None
            best_score = -1.0
            for tid, track in self._tracks.items():
                if tid in matched:
                    continue
                # Score = IoU * 0.7 + inverso_distancia * 0.3
                iou = _iou(det["bbox"], track["bbox"])
                dist = ((cx - track["centroid"][0]) ** 2 + (cy - track["centroid"][1]) ** 2) ** 0.5
                dist_score = max(0, 1.0 - dist * 5.0)  # normalizado, ~0.2px = limite
                score = iou * 0.7 + dist_score * 0.3
                if score > best_score and score > 0.3:
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

        # Verificar transições de estado para cada ROI
        for roi in rois:
            roi_classes = set(roi.config.get("classes", [0]))
            roi_conf = roi.config.get("min_confidence", 0.5)

            for tid, track in self._tracks.items():
                det = track.get("detection")
                if not det or det["class_id"] not in roi_classes or det["confidence"] < roi_conf:
                    continue

                # Verificar se está dentro do polígono desta ROI
                in_roi = _point_in_polygon(track["centroid"], roi.polygon_points)
                prev_in = track.get(f"in_roi_{roi.id}")

                # Salvar estado atual
                track[f"in_roi_{roi.id}"] = in_roi

                if prev_in is None:
                    # Primeira vez que vemos este track com esta ROI
                    continue

                if prev_in != in_roi:
                    # Transição! Cruzou a cerca
                    direction = "enter" if in_roi else "exit"

                    # Verificar cooldown
                    last_cross = self._cross_cooldowns.get(tid, 0)
                    if now - last_cross >= self._cooldown_seconds:
                        self._cross_cooldowns[tid] = now
                        results.append(self._make_result(
                            roi, det, metadata, direction, now
                        ))

        return results

    def _make_result(
        self,
        roi: ROIConfig,
        detection: dict,
        metadata: FrameMetadata,
        direction: str,
        now: float,
    ) -> AnalyticsResult:
        return AnalyticsResult(
            plugin=self.name,
            camera_id=metadata.camera_id,
            tenant_id=metadata.tenant_id,
            roi_id=roi.id,
            event_type="analytics.intrusion.crossed",
            payload={
                "roi_id": roi.id,
                "roi_name": roi.name,
                "direction": direction,  # "enter" ou "exit"
                "class": detection["class_name"],
                "confidence": round(detection["confidence"], 2),
                "bbox": detection["bbox"],
            },
            occurred_at=metadata.timestamp,
            confidence=detection["confidence"],
        )
