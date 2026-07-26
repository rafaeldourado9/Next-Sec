"""Cache TTL em memória para ROIs — evita query ao banco a cada frame do analytics."""
from __future__ import annotations

from datetime import datetime, timedelta

_TTL = timedelta(seconds=60)

# { "tenant_id:camera_id_or_*" -> (cached_at, data) }
_cache: dict[str, tuple[datetime, list[dict]]] = {}


def _key(tenant_id: str, camera_id: str | None) -> str:
    return f"{tenant_id}:{camera_id or '*'}"


def get(tenant_id: str, camera_id: str | None) -> list[dict] | None:
    entry = _cache.get(_key(tenant_id, camera_id))
    if entry and datetime.utcnow() - entry[0] < _TTL:
        return entry[1]
    return None


def set(tenant_id: str, camera_id: str | None, data: list[dict]) -> None:  # noqa: A001
    _cache[_key(tenant_id, camera_id)] = (datetime.utcnow(), data)


def invalidate(tenant_id: str, camera_id: str | None = None) -> None:
    """Chame ao criar, atualizar ou deletar uma ROI."""
    _cache.pop(_key(tenant_id, camera_id), None)
    if camera_id:
        # Invalida também a entrada sem filtro de câmera do mesmo tenant
        _cache.pop(_key(tenant_id, None), None)
