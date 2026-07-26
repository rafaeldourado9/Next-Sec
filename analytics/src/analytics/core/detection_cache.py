"""
Detection-Based KV Cache — Cache inteligente baseado em detecções.

Ao invés de comparar frames por pixels (SSIM/hash), que causaria perda
de detecções de intrusos parados, este cache usa o **resultado da
inferência YOLO** como chave de decisão.

Lógica:
1. Se frame TEM detecções → SEMPRE processar (não perder intrusos!)
2. Se frame NÃO tem detecções e o anterior também não tinha → SKIP
3. Se frame NÃO tem detecções mas o anterior tinha → processar (transição)

Isto resolve o edge case "intruso parado != empty" do roadmap:
- Intruso detectado → processado e tracked
- Intruso sai → evento "cleared" emitido
- Frames vazios consecutivos → ignorados (economia de GPU)

Uso:
    cache = DetectionCache(ttl_seconds=30)
    if cache.should_process(camera_id, detections):
        # Rodar plugins e emitir eventos
        ...
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CameraState:
    """Estado de detecção para uma câmera."""

    last_detections_count: int = 0
    last_processed_at: float = 0.0
    empty_frame_count: int = 0
    total_frames_seen: int = 0
    total_frames_processed: int = 0


class DetectionCache:
    """
    Cache baseado em detecções para otimizar processamento de frames.

    Decisão de processamento:
    - HAS detections → True (sempre processar)
    - NO detections, last was EMPTY → False (skip: cena vazia consecutiva)
    - NO detections, last was NOT EMPTY → True (transição: possível saída de intruso)

    TTL: frames vazios consecutivos acima de `max_empty_frames` resetam
    o cache para a câmera (libera memória).
    """

    def __init__(
        self,
        max_empty_frames: int = 30,
        ttl_seconds: float = 60.0,
    ) -> None:
        """
        Inicializa cache de detecções.

        Args:
            max_empty_frames: Máximo de frames vazios consecutivos antes de reset
            ttl_seconds: TTL para limpeza de estados antigos
        """
        self._cache: dict[str, CameraState] = {}
        self._max_empty_frames = max_empty_frames
        self._ttl_seconds = ttl_seconds

    def should_process(
        self,
        camera_id: str,
        detections: list[dict],
    ) -> bool:
        """
        Decide se o frame deve ser processado baseado em detecções.

        Args:
            camera_id: ID da câmera
            detections: Lista de detecções do frame atual (vazia = sem detecções)

        Returns:
            True se o frame deve ser processado pelos plugins
        """
        state = self._get_state(camera_id)
        state.total_frames_seen += 1
        now = time.monotonic()

        has_detections = len(detections) > 0

        # Regra 1: SEMPRE processar se há detecções
        if has_detections:
            state.empty_frame_count = 0
            state.last_detections_count = len(detections)
            state.last_processed_at = now
            state.total_frames_processed += 1
            return True

        # Regra 2: Frame vazio após frame com detecções → processar (transição)
        if state.last_detections_count > 0:
            state.empty_frame_count = 1
            state.last_detections_count = 0
            state.last_processed_at = now
            state.total_frames_processed += 1
            logger.debug(
                "Camera %s: transição detecção→vazio (possível saída de intruso)",
                camera_id,
            )
            return True

        # Regra 3: Frame vazio após frame vazio → SKIP
        state.empty_frame_count += 1

        # Reset se muitos frames vazios consecutivos (libera memória)
        if state.empty_frame_count >= self._max_empty_frames:
            self._reset_state(camera_id)
            logger.debug(
                "Camera %s: reset após %d frames vazios consecutivos",
                camera_id,
                state.empty_frame_count,
            )
            return False

        return False

    def get_hit_rate(self) -> dict:
        """
        Retorna estatísticas de hit rate do cache.

        Útil para monitoramento e debugging.
        """
        total_seen = sum(s.total_frames_seen for s in self._cache.values())
        total_processed = sum(s.total_frames_processed for s in self._cache.values())
        total_skipped = total_seen - total_processed

        return {
            "total_frames_seen": total_seen,
            "total_frames_processed": total_processed,
            "total_frames_skipped": total_skipped,
            "hit_rate_pct": (
                round((total_skipped / total_seen) * 100, 1) if total_seen > 0 else 0.0
            ),
            "active_cameras": len(self._cache),
        }

    def clear_expired(self) -> int:
        """
        Remove estados expirados do cache.

        Returns:
            Número de estados removidos
        """
        now = time.monotonic()
        expired = [
            cam_id
            for cam_id, state in self._cache.items()
            if now - state.last_processed_at > self._ttl_seconds
        ]
        for cam_id in expired:
            del self._cache[cam_id]
        return len(expired)

    def _get_state(self, camera_id: str) -> CameraState:
        """Retorna ou cria estado para a câmera."""
        if camera_id not in self._cache:
            self._cache[camera_id] = CameraState()
        return self._cache[camera_id]

    def _reset_state(self, camera_id: str) -> None:
        """Reseta estado da câmera (após muitos frames vazios)."""
        if camera_id in self._cache:
            del self._cache[camera_id]

    def reset_all(self) -> None:
        """Limpa todo o cache."""
        self._cache.clear()
