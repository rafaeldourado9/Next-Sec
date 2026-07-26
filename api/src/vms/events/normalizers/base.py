"""Interface base para normalizadores de payload ALPR."""
from __future__ import annotations

from typing import Protocol

from vms.events.domain import AlprDetection


class NormalizerPort(Protocol):
    """Normaliza payload raw de fabricante para AlprDetection."""

    manufacturer: str

    def normalize(
        self, raw: dict, camera_id: str, tenant_id: str
    ) -> AlprDetection: ...

    def can_handle(self, raw: dict) -> bool: ...


class NormalizerRegistry:
    """Registro de normalizadores por fabricante."""

    def __init__(self) -> None:
        self._normalizers: dict[str, NormalizerPort] = {}

    def register(self, normalizer: NormalizerPort) -> None:
        """Registra normalizador pelo fabricante."""
        self._normalizers[normalizer.manufacturer] = normalizer

    def get(self, manufacturer: str) -> NormalizerPort | None:
        """Retorna normalizador pelo nome do fabricante ou None se não registrado."""
        return self._normalizers.get(manufacturer)

    def normalize(
        self,
        manufacturer: str,
        raw: dict,
        camera_id: str,
        tenant_id: str,
    ) -> AlprDetection:
        """
        Normaliza payload raw usando o normalizador do fabricante.

        Lança ValueError se fabricante não registrado.
        """
        normalizer = self.get(manufacturer)
        if not normalizer:
            raise ValueError(f"Fabricante não suportado: '{manufacturer}'")
        return normalizer.normalize(raw, camera_id, tenant_id)


# Registro global de normalizadores
registry = NormalizerRegistry()
