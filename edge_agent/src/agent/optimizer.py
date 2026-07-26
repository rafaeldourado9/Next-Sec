"""Resource Optimizer — gerencia KV cache, CPU/GPU allocation e dynamic FPS."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.hardware import HardwareInfo

logger = logging.getLogger(__name__)


@dataclass
class ModelCacheEntry:
    """Entrada no KV cache de modelos."""

    model_path: str
    model: Any  # YOLO model instance
    imgsz: int
    device: str  # "cuda", "cpu", "mps"
    last_used: float  # timestamp


class ResourceOptimizer:
    """
    Otimiza uso de recursos para inferência YOLO.

    Funcionalidades:
    - KV Cache: mantém modelos pré-carregados em RAM/VRAM
    - Auto-detect: escolhe melhor device (CUDA > MPS > CPU)
    - Dynamic FPS: ajusta FPS baseado em load atual
    - Worker pooling: pool de workers compartilhado
    """

    def __init__(self, hardware: HardwareInfo) -> None:
        self.hardware = hardware
        self._model_cache: dict[str, ModelCacheEntry] = {}
        self._max_cache_size = self._calculate_max_cache_size()
        self._current_load = 0.0  # 0.0 a 1.0
        self._target_fps = 1
        self._device = self._select_device()
        self._batch_size = self._calculate_batch_size()

        logger.info(
            "ResourceOptimizer inicializado: device=%s, cache=%d modelos, batch=%d",
            self._device,
            self._max_cache_size,
            self._batch_size,
        )

    def _select_device(self) -> str:
        """Seleciona melhor device disponível."""
        if self.hardware.accelerator == "cuda":
            return "cuda"
        elif self.hardware.accelerator == "mps":
            return "mps"
        elif self.hardware.accelerator == "rocm":
            return "cuda"  # ROCm usa API CUDA-compatible
        return "cpu"

    def _calculate_max_cache_size(self) -> int:
        """Calcula quantos modelos cabem em cache."""
        ram_gb = self.hardware.ram_gb
        if self.hardware.has_gpu:
            # VRAM limitada: 1-2 modelos grandes
            if self.hardware.gpu_vram_gb >= 8:
                return 4
            elif self.hardware.gpu_vram_gb >= 4:
                return 2
            return 1
        else:
            # CPU com mais RAM: mais modelos
            if ram_gb >= 32:
                return 6
            elif ram_gb >= 16:
                return 4
            return 2

    def _calculate_batch_size(self) -> int:
        """Calcula batch size ótimo para inferência."""
        if self._device == "cuda":
            if self.hardware.gpu_vram_gb >= 8:
                return 8
            elif self.hardware.gpu_vram_gb >= 4:
                return 4
            return 2
        elif self._device == "mps":
            return 4
        else:
            # CPU: depende de cores
            return min(4, max(1, self.hardware.cpu_cores // 4))

    def get_model_config(self, model_path: str) -> dict[str, Any]:
        """Retorna config ótima para carregar um modelo."""
        return {
            "device": self._device,
            "batch_size": self._batch_size,
            "half": self._device == "cuda",  # FP16 só em GPU
            "imgsz": 640,
            "conf": 0.30,
            "iou": 0.45,
            "max_det": 300,
        }

    def get_or_load_model(self, model_path: str, loader_fn) -> Any:
        """
        Obtém modelo do cache ou carrega.

        loader_fn: função que carrega o modelo (ex: YOLO(model_path))
        """
        import time

        # Já está em cache?
        if model_path in self._model_cache:
            entry = self._model_cache[model_path]
            entry.last_used = time.time()
            logger.debug("Modelo em cache: %s", model_path)
            return entry.model

        # Cache cheio? Evict LRU
        if len(self._model_cache) >= self._max_cache_size:
            self._evict_lru()

        # Carregar modelo
        logger.info("Carregando modelo: %s (device=%s)", model_path, self._device)
        model = loader_fn(model_path)

        # Colocar em cache
        self._model_cache[model_path] = ModelCacheEntry(
            model_path=model_path,
            model=model,
            imgsz=640,
            device=self._device,
            last_used=time.time(),
        )

        logger.info(
            "Modelo carregado em cache: %s (%d/%d slots)",
            model_path,
            len(self._model_cache),
            self._max_cache_size,
        )
        return model

    def _evict_lru(self) -> None:
        """Remove modelo menos recentemente usado."""
        if not self._model_cache:
            return

        oldest_path = min(
            self._model_cache.keys(),
            key=lambda k: self._model_cache[k].last_used,
        )
        logger.info("Evicting modelo do cache: %s", oldest_path)
        del self._model_cache[oldest_path]

    def update_load(self, current_load: float) -> None:
        """Atualiza load atual e ajusta FPS dinamicamente."""
        self._current_load = max(0.0, min(1.0, current_load))
        self._target_fps = self._calculate_target_fps()
        logger.debug("Load atualizado: %.1f%% → FPS alvo: %d", self._current_load * 100, self._target_fps)

    def _calculate_target_fps(self) -> int:
        """Calcula FPS alvo baseado em load."""
        if self._current_load < 0.3:
            return 5  # Low load: max FPS
        elif self._current_load < 0.6:
            return 3  # Medium load
        elif self._current_load < 0.8:
            return 2  # High load: reduzir
        else:
            return 1  # Very high load: mínimo

    @property
    def target_fps(self) -> int:
        """FPS alvo atual."""
        return self._target_fps

    @property
    def device(self) -> str:
        """Device selecionado."""
        return self._device

    @property
    def cache_stats(self) -> dict[str, Any]:
        """Estatísticas do cache."""
        return {
            "cached_models": len(self._model_cache),
            "max_cache_size": self._max_cache_size,
            "device": self._device,
            "batch_size": self._batch_size,
            "current_load": round(self._current_load * 100, 1),
            "target_fps": self._target_fps,
        }

    def clear_cache(self) -> None:
        """Limpa todo o cache de modelos."""
        self._model_cache.clear()
        logger.info("Cache de modelos limpo")
