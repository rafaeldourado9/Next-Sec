"""Interfaces base para plugins de analytics."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class ROIConfig:
    """Configuração de região de interesse para o plugin."""

    id: str
    name: str
    ia_type: str
    polygon_points: list[list[float]]  # normalizado 0.0–1.0
    config: dict = field(default_factory=dict)


@dataclass
class FrameMetadata:
    """Metadados do frame sendo processado."""

    camera_id: str
    tenant_id: str
    timestamp: datetime
    stream_url: str


@dataclass
class AnalyticsResult:
    """Resultado de análise de um plugin."""

    plugin: str
    camera_id: str
    tenant_id: str
    event_type: str
    payload: dict
    occurred_at: datetime
    confidence: float | None = None
    roi_id: str | None = None  # preenchido quando plugin usa zonas locais


class AnalyticsPlugin(ABC):
    """Base para todos os plugins de analytics."""

    name: str
    version: str
    roi_type: str

    async def initialize(self, config: dict) -> None:
        """Carrega modelos, aloca recursos. Chamado uma vez no startup."""

    @abstractmethod
    async def process_frame(
        self,
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        """Processa um frame e retorna lista de resultados."""

    async def process_shared_frame(
        self,
        detections: list[dict],
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        """
        Processa frame com detecções pré-computadas do SharedInferenceEngine.

        Plugins que compartilham modelo (ex: object.pt) sobrescrevem este
        método em vez de process_frame. Recebe as detecções já filtradas
        para as classes relevantes ao plugin.

        Args:
            detections: Lista de detecções pré-filtradas por classe
            frame: Frame original (para crop/OCR se necessário)
            metadata: Metadados do frame
            rois: Regiões de interesse configuradas para esta câmera

        Returns:
            Lista de AnalyticsResult gerados
        """
        return []

    async def shutdown(self) -> None:
        """Libera recursos. Chamado no shutdown do serviço."""
