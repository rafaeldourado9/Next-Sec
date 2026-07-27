"""Plugin de reconhecimento facial — com verificação LGPD.

LGPD Compliance (Art. 11):
- O gate de consentimento é aplicado inteiramente pela API, no endpoint
  `GET /plugins/watchlist` (ver ADR-014): se o tenant não tem
  `facial_recognition_enabled=True`, a API retorna uma watchlist VAZIA.
  Uma watchlist vazia significa "nada para comparar" — o plugin não faz
  nenhuma inferência de embedding nesse caso. Isso substitui o mecanismo
  antigo de `enable_for_tenant`/`disable_for_tenant` (nunca era chamado por
  ninguém — gate morto, ver .genesis/architecture/reuse-plan.md).

Modelo: InsightFace `buffalo_s`, CPU-only (ver ADR-014).
"""
from __future__ import annotations

import logging
import time

import numpy as np

from analytics.core.plugin_base import AnalyticsPlugin, AnalyticsResult, FrameMetadata, ROIConfig
from analytics.plugins.face_recognition.matching import best_match

logger = logging.getLogger(__name__)

_DEFAULT_SIMILARITY_THRESHOLD = 0.5
_WATCHLIST_CACHE_TTL_SECONDS = 60.0


class FaceRecognitionPlugin(AnalyticsPlugin):
    """Detecta e reconhece rostos em frames de vídeo dentro de zonas `face_recognition`."""

    name = "face_recognition"
    version = "2.0.0"
    roi_type = "face_recognition"

    def __init__(self) -> None:
        self._app = None  # insightface.app.FaceAnalysis — None se falhou ao carregar
        self._client = None  # VMSClient próprio deste plugin (watchlist não é uma ROI)
        self._watchlist_cache: dict[str, tuple[float, list[tuple[str, np.ndarray]]]] = {}
        self._similarity_threshold = _DEFAULT_SIMILARITY_THRESHOLD

    async def initialize(self, config: dict) -> None:
        """Carrega o modelo InsightFace e inicializa o cliente HTTP da watchlist."""
        self._similarity_threshold = config.get(
            "similarity_threshold", _DEFAULT_SIMILARITY_THRESHOLD
        )

        from analytics.core.vms_client import VMSClient
        self._client = VMSClient()
        await self._client.start()

        try:
            from insightface.app import FaceAnalysis

            self._app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
            self._app.prepare(ctx_id=-1, det_size=(320, 320))
            logger.info("FaceRecognitionPlugin: InsightFace (buffalo_s) carregado")
        except Exception:
            # Não derruba o serviço — plugin fica inativo (process_frame sempre
            # retorna []) se o modelo não puder ser baixado/carregado. Ver
            # ADR-014, "Consequências negativas".
            logger.exception(
                "FaceRecognitionPlugin: falha ao carregar InsightFace — plugin ficará inativo"
            )
            self._app = None

    async def _get_watchlist(self, tenant_id: str) -> list[tuple[str, np.ndarray]]:
        """Retorna embeddings da watchlist do tenant, com cache local de 60s.

        Lista vazia (tenant sem consentimento OU watchlist vazia) é o próprio
        gate de LGPD — nenhuma inferência de embedding roda nesse caso.
        """
        now = time.monotonic()
        cached = self._watchlist_cache.get(tenant_id)
        if cached and now - cached[0] < _WATCHLIST_CACHE_TTL_SECONDS:
            return cached[1]

        entries = await self._client.list_watchlist() if self._client else []
        embeddings: list[tuple[str, np.ndarray]] = []
        for entry in entries:
            embedding = await self._compute_reference_embedding(entry.get("image_url"))
            if embedding is not None:
                embeddings.append((entry["id"], embedding))

        self._watchlist_cache[tenant_id] = (now, embeddings)
        return embeddings

    async def _compute_reference_embedding(self, image_url: str | None) -> np.ndarray | None:
        """Baixa a imagem de referência da watchlist e computa seu embedding."""
        if not image_url or self._app is None:
            return None
        try:
            import cv2
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()

            arr = np.frombuffer(resp.content, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("Imagem de referência da watchlist inválida/corrompida")
                return None

            faces = self._app.get(image)
            if not faces:
                logger.warning("Nenhum rosto detectado na imagem de referência da watchlist")
                return None
            return faces[0].normed_embedding
        except Exception:
            logger.exception("Falha ao computar embedding de referência da watchlist")
            return None

    async def process_frame(
        self,
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        """Processa frame para reconhecimento facial dentro das zonas configuradas."""
        if self._app is None:
            return []

        face_rois = [r for r in rois if r.ia_type == self.roi_type]
        if not face_rois:
            return []

        watchlist = await self._get_watchlist(metadata.tenant_id)
        if not watchlist:
            # Sem watchlist (tenant sem consentimento, ou watchlist vazia) —
            # não há com o que comparar. Este é o gate de LGPD efetivo.
            return []

        try:
            faces = self._app.get(frame)
        except Exception:
            logger.exception("Falha ao detectar rostos no frame (câmera %s)", metadata.camera_id)
            return []

        frame_h, frame_w = frame.shape[:2]
        results: list[AnalyticsResult] = []
        for face in faces:
            match = best_match(face.normed_embedding, watchlist, self._similarity_threshold)
            if match is None:
                continue
            profile_id, similarity = match
            # face.bbox vem em pixels (x1,y1,x2,y2) — normaliza pra 0.0-1.0,
            # mesmo formato usado pelo plugin de intrusão, pra que o overlay
            # vermelho desenhado no WhatsApp (tasks.py::_draw_bbox_overlay)
            # também funcione pra eventos de reconhecimento facial.
            x1, y1, x2, y2 = face.bbox.tolist()
            bbox = [
                max(0.0, x1 / frame_w),
                max(0.0, y1 / frame_h),
                min(1.0, x2 / frame_w),
                min(1.0, y2 / frame_h),
            ]
            results.append(
                AnalyticsResult(
                    plugin=self.name,
                    camera_id=metadata.camera_id,
                    tenant_id=metadata.tenant_id,
                    event_type="analytics.face.recognized",
                    payload={
                        "face_profile_id": profile_id,
                        "similarity": round(similarity, 3),
                        "bbox": bbox,
                    },
                    occurred_at=metadata.timestamp,
                    confidence=similarity,
                )
            )
        return results

    async def process_shared_frame(
        self,
        detections: list[dict],
        frame: np.ndarray,
        metadata: FrameMetadata,
        rois: list[ROIConfig],
    ) -> list[AnalyticsResult]:
        """Reconhecimento facial não reaproveita detecções do SharedInferenceEngine

        (modelo YOLO genérico detecta pessoas, não landmarks faciais) — sempre
        roda sua própria detecção via `process_frame`.
        """
        return await self.process_frame(frame, metadata, rois)

    async def shutdown(self) -> None:
        """Libera recursos do modelo facial e do cliente HTTP."""
        if self._client:
            await self._client.close()
        self._watchlist_cache.clear()
        logger.info("FaceRecognitionPlugin encerrado")
