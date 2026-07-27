"""
Shared Inference Engine — 1 inferência YOLO → N plugins consomem.

Em vez de cada plugin rodar sua própria inferência (desperdício de GPU),
este mecanismo executa YOLO uma vez com a união de todas as classes
necessárias e distribui os resultados para os plugins interessados.

Plugins que compartilham o mesmo modelo (ex: object.pt para intrusion,
people_count, vehicle_count) se beneficiam diretamente.

Uso:
    engine = SharedInferenceEngine("/models/object.pt", imgsz=640)
    # União de classes: person(0), car(2), motorcycle(3), bus(5), truck(7)
    detections = engine.predict(frame, classes={0, 2, 3, 5, 7}, conf=0.3)

    # Cada plugin filtra as detecções que lhe interessam:
    intrusion_detections   = engine.filter_by_class(detections, {0})
    people_count_detections = engine.filter_by_class(detections, {0})
    vehicle_count_detections = engine.filter_by_class(detections, {2, 3, 5, 7})
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_INFERENCE_LONG_EDGE = 640  # pixels — YOLOv8 treina em 640; não há ganho em passar mais


def _downscale_if_needed(frame: np.ndarray) -> np.ndarray:
    """Reduz o frame para que o maior lado seja ≤ _INFERENCE_LONG_EDGE.

    Preserva aspect ratio. Se o frame já couber, retorna sem copiar.
    Economiza RAM e CPU de pré-processamento do YOLO (sem perda de precisão,
    pois o modelo treina em 640×640 e faz resize interno de qualquer forma).
    """
    h, w = frame.shape[:2]
    if max(h, w) <= _INFERENCE_LONG_EDGE:
        return frame
    scale = _INFERENCE_LONG_EDGE / max(h, w)
    return cv2.resize(
        frame,
        (int(w * scale), int(h * scale)),
        interpolation=cv2.INTER_LINEAR,
    )


# Classes COCO relevantes para plugins de câmeras de segurança
COCO_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    4: "airplane",
    5: "bus",
    6: "train",
    7: "truck",
    8: "boat",
    # ... (classes 9-79 omitidas, não relevantes para vigilância)
}

# Classes por plugin (para shared inference)
PLUGIN_CLASSES: dict[str, set[int]] = {
    "intrusion": {0},  # person
    "people_count": {0},  # person
    "vehicle_count": {2, 3, 5, 7},  # car, motorcycle, bus, truck
    "lpr": {2, 3, 5, 7},  # vehicles para crop + OCR
    "biker_detection": {0, 1},  # person + bicycle
    "person_detection": {0},  # person
    "vehicle_detection": {2, 3, 5, 7},  # car, motorcycle, bus, truck
    "speed": {2, 3, 5, 7},  # car, motorcycle, bus, truck — estimativa de velocidade
    "horse_cart": set(),  # classes custom — não usa shared
    "fire_smoke": set(),  # modelo próprio — não usa shared
    "ppe_detection": set(),  # modelo próprio — não usa shared
    "motion": set(),  # MOG2 — não usa YOLO
}


class SharedInferenceEngine:
    """
    Engine de inferência compartilhada.

    Carrega um modelo YOLO uma vez e executa predições para múltiplos plugins.
    """

    def __init__(
        self,
        model_path: str,
        imgsz: int = 640,
        name: str = "shared",
    ) -> None:
        """
        Inicializa engine compartilhada.

        Args:
            model_path: Caminho do modelo YOLO (.pt)
            imgsz: Tamanho da imagem para inferência
            name: Nome identificador (ex: "object.pt")
        """
        from ultralytics import YOLO

        self._model = YOLO(model_path)
        self._imgsz = imgsz
        self._name = name
        logger.info(
            "SharedInferenceEngine criado: %s (%s, imgsz=%d)",
            name,
            model_path,
            imgsz,
        )

    def predict(
        self,
        frame: np.ndarray,
        classes: set[int] | None = None,
        conf: float = 0.30,
    ) -> list[dict[str, Any]]:
        """
        Executa inferência YOLO no frame.

        Args:
            frame: Frame BGR do OpenCV (qualquer resolução)
            classes: Conjunto de classes COCO para filtrar (None = todas)
            conf: Confiança mínima (0.0-1.0)

        Returns:
            Lista de detecções com keys:
            - class_id: int (COCO class ID)
            - class_name: str
            - confidence: float
            - bbox: [x1, y1, x2, y2] normalizado [0.0, 1.0]
        """
        frame = _downscale_if_needed(frame)

        results = self._model.predict(
            frame,
            imgsz=self._imgsz,
            conf=conf,
            classes=list(classes) if classes else None,
            verbose=False,
        )

        detections: list[dict[str, Any]] = []
        if results and results[0].boxes is not None:
            h, w = frame.shape[:2]  # dimensões do frame já reduzido (normalizadas corretamente)
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                detections.append(
                    {
                        "class_id": int(box.cls[0]),
                        "class_name": results[0].names[int(box.cls[0])],
                        "confidence": float(box.conf[0]),
                        "bbox": [
                            float(x1 / w),
                            float(y1 / h),
                            float(x2 / w),
                            float(y2 / h),
                        ],
                    }
                )

        return detections

    def predict_batch(
        self,
        frames: list[np.ndarray],
        classes: set[int] | None = None,
        conf: float = 0.30,
    ) -> list[list[dict[str, Any]]]:
        """Batch inference: N frames em uma chamada ao modelo.

        Amortiza o overhead fixo do YOLO (carregamento de contexto GPU, sync)
        pelo número de câmeras no batch. Usa _downscale_if_needed em cada frame.
        Retorna uma lista de detecções por frame, na mesma ordem dos frames.
        """
        prepared = [_downscale_if_needed(f) for f in frames]
        results = self._model.predict(
            prepared,
            imgsz=self._imgsz,
            conf=conf,
            classes=list(classes) if classes else None,
            verbose=False,
        )
        output: list[list[dict[str, Any]]] = []
        for frame, result in zip(prepared, results):
            h, w = frame.shape[:2]
            detections: list[dict[str, Any]] = []
            if result.boxes is not None:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    detections.append(
                        {
                            "class_id": int(box.cls[0]),
                            "class_name": result.names[int(box.cls[0])],
                            "confidence": float(box.conf[0]),
                            "bbox": [
                                float(x1 / w),
                                float(y1 / h),
                                float(x2 / w),
                                float(y2 / h),
                            ],
                        }
                    )
            output.append(detections)
        return output

    @staticmethod
    def filter_by_class(
        detections: list[dict[str, Any]],
        classes: set[int],
    ) -> list[dict[str, Any]]:
        """Filtra detecções por conjunto de classes."""
        return [d for d in detections if d["class_id"] in classes]

    @staticmethod
    def centroid(bbox: list[float]) -> tuple[float, float]:
        """Retorna centroide (cx, cy) normalizado."""
        return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    @staticmethod
    def point_in_polygon(
        point: tuple[float, float],
        polygon: list[list[float]],
    ) -> bool:
        """Ray-casting para verificar se ponto está dentro do polígono."""
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

    @staticmethod
    def filter_in_roi(
        detections: list[dict[str, Any]],
        polygon: list[list[float]],
    ) -> list[dict[str, Any]]:
        """Filtra detecções cujo centroide está dentro do polígono."""
        return [
            d
            for d in detections
            if SharedInferenceEngine.point_in_polygon(
                SharedInferenceEngine.centroid(d["bbox"]),
                polygon,
            )
        ]

    @property
    def name(self) -> str:
        return self._name
