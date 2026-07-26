"""Matching de embeddings faciais por similaridade de cosseno.

Função pura, sem dependência do InsightFace — testável isoladamente com
vetores sintéticos (ver ADR-014, seção "Gap de validação real").
"""
from __future__ import annotations

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similaridade de cosseno entre dois vetores, em [-1, 1].

    Retorna 0.0 se algum vetor tiver norma zero (evita divisão por zero).
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def best_match(
    embedding: np.ndarray,
    watchlist: list[tuple[str, np.ndarray]],
    threshold: float,
) -> tuple[str, float] | None:
    """Retorna (profile_id, similarity) do melhor match acima do threshold, ou None.

    `watchlist` é uma lista de (profile_id, embedding_de_referencia).
    """
    best_id: str | None = None
    best_sim = 0.0
    for profile_id, ref_embedding in watchlist:
        sim = cosine_similarity(embedding, ref_embedding)
        if sim > best_sim:
            best_id, best_sim = profile_id, sim

    if best_id is not None and best_sim >= threshold:
        return best_id, best_sim
    return None
