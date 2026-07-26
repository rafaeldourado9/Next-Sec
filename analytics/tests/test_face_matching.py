"""Testes de vms.analytics.plugins.face_recognition.matching — puros, sem InsightFace.

Ver ADR-014 ("Gap de validação real") — valida a lógica de similaridade/threshold
com vetores sintéticos, já que baixar e rodar o modelo real exige rede e uma
imagem de rosto de teste (deixado para o Sprint 5, deploy piloto).
"""
from __future__ import annotations

import numpy as np

from analytics.plugins.face_recognition.matching import best_match, cosine_similarity


def test_identical_vectors_have_similarity_one() -> None:
    v = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(v, v) == 1.0


def test_orthogonal_vectors_have_similarity_zero() -> None:
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == 0.0


def test_opposite_vectors_have_similarity_negative_one() -> None:
    a = np.array([1.0, 0.0])
    b = np.array([-1.0, 0.0])
    assert cosine_similarity(a, b) == -1.0


def test_zero_vector_returns_zero_not_nan() -> None:
    a = np.array([0.0, 0.0])
    b = np.array([1.0, 1.0])
    assert cosine_similarity(a, b) == 0.0


def test_best_match_returns_closest_above_threshold() -> None:
    query = np.array([1.0, 0.0, 0.0])
    watchlist = [
        ("profile-far", np.array([0.0, 1.0, 0.0])),
        ("profile-close", np.array([0.9, 0.1, 0.0])),
    ]
    result = best_match(query, watchlist, threshold=0.5)
    assert result is not None
    profile_id, similarity = result
    assert profile_id == "profile-close"
    assert similarity > 0.9


def test_best_match_returns_none_below_threshold() -> None:
    query = np.array([1.0, 0.0, 0.0])
    watchlist = [("profile-far", np.array([0.0, 1.0, 0.0]))]
    assert best_match(query, watchlist, threshold=0.5) is None


def test_best_match_empty_watchlist_returns_none() -> None:
    query = np.array([1.0, 0.0, 0.0])
    assert best_match(query, [], threshold=0.5) is None
