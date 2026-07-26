"""Cache TTL em memória para a watchlist facial — mesmo padrão do roi_cache.py."""
from __future__ import annotations

from datetime import datetime, timedelta

_TTL = timedelta(seconds=60)

_cache: dict[str, tuple[datetime, list[dict]]] = {}


def get(tenant_id: str) -> list[dict] | None:
    entry = _cache.get(tenant_id)
    if entry and datetime.utcnow() - entry[0] < _TTL:
        return entry[1]
    return None


def set(tenant_id: str, data: list[dict]) -> None:  # noqa: A001
    _cache[tenant_id] = (datetime.utcnow(), data)


def invalidate(tenant_id: str) -> None:
    """Chame ao cadastrar, remover ou alterar o gate de LGPD de um tenant."""
    _cache.pop(tenant_id, None)
