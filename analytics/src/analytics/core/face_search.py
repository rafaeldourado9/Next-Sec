"""Busca facial sob demanda — compara um rosto de referência contra snapshots
de eventos já existentes (ver `.genesis/architecture/reuse-plan.md`).

Substituiu o antigo plugin `face_recognition` contínuo (frame a frame): agora
o usuário cadastra um rosto na watchlist e dispara uma busca pontual contra os
eventos já capturados por outros plugins (ex: `intrusion`), em vez de rodar
InsightFace em todo frame de toda câmera o tempo todo.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import cv2
import httpx
import numpy as np

from analytics.plugins.face_recognition.matching import cosine_similarity

logger = logging.getLogger(__name__)

_SNAPSHOTS_ROOT = Path("/snapshots")

_app = None  # insightface.app.FaceAnalysis — carregado sob demanda (lazy singleton)


def _get_face_app():
    """Carrega o InsightFace (buffalo_s) uma única vez, sob demanda.

    Diferente do plugin antigo, não é mais carregado no startup do serviço —
    só quando a primeira busca é disparada. Fica em memória depois disso.
    """
    global _app
    if _app is not None:
        return _app
    try:
        from insightface.app import FaceAnalysis

        _app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=-1, det_size=(320, 320))
        logger.info("face_search: InsightFace (buffalo_s) carregado")
    except Exception:
        logger.exception("face_search: falha ao carregar InsightFace")
        _app = False  # marca como "falhou" pra não tentar recarregar a cada busca
    return _app if _app is not False else None


async def _embedding_from_url(url: str) -> np.ndarray | None:
    """Baixa uma imagem por URL (ex: presigned MinIO) e extrai o embedding do rosto."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return _embedding_from_bytes(resp.content)
    except Exception:
        logger.exception("face_search: falha ao baixar imagem de referência")
        return None


def _embedding_from_path(relative_path: str) -> np.ndarray | None:
    """Lê um snapshot do volume compartilhado `/snapshots` e extrai o embedding."""
    full_path = _SNAPSHOTS_ROOT / relative_path.lstrip("/")
    try:
        data = full_path.read_bytes()
    except OSError:
        logger.warning("face_search: snapshot não encontrado: %s", full_path)
        return None
    return _embedding_from_bytes(data)


def _embedding_from_bytes(data: bytes) -> np.ndarray | None:
    app = _get_face_app()
    if app is None:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return None
    faces = app.get(image)
    if not faces:
        return None
    # Maior rosto do frame — heurística simples pra imagem com múltiplas pessoas
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return best.normed_embedding


async def search_faces(
    reference_image_url: str,
    candidates: list[dict],
    threshold: float = 0.5,
) -> list[dict]:
    """Compara o rosto de referência contra os snapshots dos eventos candidatos.

    `candidates`: lista de {"event_id": str, "image_path": str} (caminho
    relativo a /snapshots, já lido localmente — sem round-trip de rede).
    Retorna os matches acima do threshold, ordenados por similaridade desc.
    """
    reference_embedding = await _embedding_from_url(reference_image_url)
    if reference_embedding is None:
        return []

    matches: list[dict] = []
    for candidate in candidates:
        # InsightFace é CPU-bound — roda em thread separada pra não travar o
        # event loop (que também processa a captura contínua das câmeras
        # nesse mesmo processo) durante uma busca com muitos candidatos.
        embedding = await asyncio.to_thread(_embedding_from_path, candidate["image_path"])
        if embedding is None:
            continue
        similarity = cosine_similarity(reference_embedding, embedding)
        if similarity >= threshold:
            matches.append({"event_id": candidate["event_id"], "similarity": round(similarity, 3)})

    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches
