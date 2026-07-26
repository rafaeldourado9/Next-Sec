"""Base para plugins baseados em YOLO — infraestrutura compartilhada."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from analytics.core.plugin_base import AnalyticsPlugin

logger = logging.getLogger(__name__)


class YOLOPlugin(AnalyticsPlugin):
    """
    Base para plugins que usam YOLOv8 como backbone de detecção.

    Carrega o modelo YOLO uma vez e oferece helpers para:
    - Inferência com confiança configurável
    - Verificação se centroide está dentro de polígono
    - Filtragem por classes COCO
    """

    _model: Any = None

    async def initialize(self, config: dict) -> None:
        """Carrega modelo YOLO a partir do caminho configurado."""
        from ultralytics import YOLO

        model_path = config.get("model_path", "yolov8n.pt")
        imgsz = config.get("imgsz", 640)
        self._model = YOLO(model_path)
        self._imgsz = imgsz
        logger.info("Plugin %s: modelo carregado de %s (imgsz=%d)", self.name, model_path, imgsz)

    def detect(
        self,
        frame: np.ndarray,
        conf: float = 0.3,
        classes: list[int] | None = None,
    ) -> list[dict]:
        """
        Executa inferência YOLO no frame.

        Retorna lista de detecções com keys: class_id, class_name, confidence, bbox.
        bbox é normalizado [x1, y1, x2, y2] relativo ao frame.
        """
        if self._model is None:
            return []

        results = self._model.predict(
            frame,
            imgsz=self._imgsz,
            conf=conf,
            classes=classes,
            verbose=False,
        )

        detections = []
        if results and results[0].boxes is not None:
            h, w = frame.shape[:2]
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                detections.append({
                    "class_id": int(box.cls[0]),
                    "class_name": results[0].names[int(box.cls[0])],
                    "confidence": float(box.conf[0]),
                    "bbox": [
                        float(x1 / w),
                        float(y1 / h),
                        float(x2 / w),
                        float(y2 / h),
                    ],
                })
        return detections

    @staticmethod
    def centroid(bbox: list[float]) -> tuple[float, float]:
        """Retorna centroide (cx, cy) normalizado de uma bbox [x1, y1, x2, y2]."""
        return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    @staticmethod
    def point_in_polygon(
        point: tuple[float, float],
        polygon: list[list[float]],
    ) -> bool:
        """
        Ray-casting para verificar se ponto está dentro do polígono.

        Coordenadas normalizadas [0.0, 1.0].
        """
        x, y = point
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def filter_in_roi(
        self,
        detections: list[dict],
        polygon: list[list[float]],
    ) -> list[dict]:
        """Filtra detecções cujo centroide está dentro do polígono da ROI."""
        return [
            d for d in detections
            if self.point_in_polygon(self.centroid(d["bbox"]), polygon)
        ]

    async def shutdown(self) -> None:
        """Libera modelo da memória."""
        self._model = None
