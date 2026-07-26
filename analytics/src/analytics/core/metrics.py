"""
Metrics Collector — Coleta e consolidação de métricas de performance.

Coleta:
- Tempo de inferência YOLO (ms)
- Número de detecções por frame
- Eventos emitidos por plugin e tipo
- Hit rate do detection cache

Uso:
    metrics = MetricsCollector()
    metrics.record_inference("cam-1", inference_ms=45.2, detections=3)
    metrics.record_event("intrusion", "analytics.intrusion.started")
    stats = metrics.get_stats()
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Coletor de métricas de performance do analytics."""

    def __init__(self, log_interval_seconds: float = 60.0) -> None:
        """
        Inicializa coletor de métricas.

        Args:
            log_interval_seconds: Intervalo para log consolidado
        """
        self._log_interval = log_interval_seconds
        self._inference_times: list[float] = []
        self._detection_counts: list[int] = []
        self._event_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._last_log_time = time.monotonic()
        self._total_frames = 0
        self._total_inferences = 0

    def record_inference(
        self,
        camera_id: str,
        inference_ms: float,
        detection_count: int,
    ) -> None:
        """
        Registra tempo de inferência YOLO.

        Args:
            camera_id: ID da câmera
            inference_ms: Tempo de inferência em milissegundos
            detection_count: Número de detecções no frame
        """
        self._inference_times.append(inference_ms)
        self._detection_counts.append(detection_count)
        self._total_frames += 1
        self._total_inferences += 1

        # Log consolidado periódico
        now = time.monotonic()
        if now - self._last_log_time >= self._log_interval:
            self._log_stats()
            self._last_log_time = now

    def record_event(self, plugin: str, event_type: str) -> None:
        """
        Registra evento emitido por plugin.

        Args:
            plugin: Nome do plugin
            event_type: Tipo do evento
        """
        self._event_counts[plugin][event_type] += 1

    def get_stats(self) -> dict:
        """
        Retorna estatísticas consolidadas.

        Returns:
            Dict com métricas atuais
        """
        avg_inference = (
            sum(self._inference_times) / len(self._inference_times)
            if self._inference_times
            else 0.0
        )
        max_inference = max(self._inference_times) if self._inference_times else 0.0
        avg_detections = (
            sum(self._detection_counts) / len(self._detection_counts)
            if self._detection_counts
            else 0.0
        )

        total_events = sum(
            sum(events.values())
            for events in self._event_counts.values()
        )

        return {
            "total_frames": self._total_frames,
            "total_inferences": self._total_inferences,
            "total_events": total_events,
            "avg_inference_ms": round(avg_inference, 1),
            "max_inference_ms": round(max_inference, 1),
            "avg_detections_per_frame": round(avg_detections, 1),
            "events_by_plugin": {
                plugin: dict(events)
                for plugin, events in self._event_counts.items()
            },
        }

    def _log_stats(self) -> None:
        """Loga estatísticas consolidadas."""
        stats = self.get_stats()
        logger.info(
            "Analytics Metrics | "
            "Frames=%d | Inferences=%d | Events=%d | "
            "AvgInference=%.1fms | MaxInference=%.1fms | "
            "AvgDetections=%.1f",
            stats["total_frames"],
            stats["total_inferences"],
            stats["total_events"],
            stats["avg_inference_ms"],
            stats["max_inference_ms"],
            stats["avg_detections_per_frame"],
        )

    def reset(self) -> None:
        """Limpa todas as métricas coletadas."""
        self._inference_times.clear()
        self._detection_counts.clear()
        self._event_counts.clear()
        self._total_frames = 0
        self._total_inferences = 0
