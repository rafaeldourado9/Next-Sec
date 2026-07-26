"""
Value Objects Compartilhados — tipos fortes para conceitos de domínio.

Value Objects são imutáveis e definidos por seus atributos, não por identidade.
Use estes ao invés de strings/dicts soltos para ganhar type safety e validação.

Uso:
    coords = Coordinates(Decimal("-23.5505"), Decimal("-46.6333"))
    confidence = Confidence(0.95)
    time_range = TimeRange(start, end)

Regras:
- Todos são frozen=True (imutáveis)
- Validam no __post_init__
- Têm __str__ legível
- Métodos utilitários quando fazem sentido
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from vms.shared.kernel import ValueObject


# ─── Coordenadas Geográficas ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Coordinates(ValueObject):
    """
    Coordenadas geográficas de uma câmera.

    Valida limites válidos de latitude/longitude.

    Uso:
        coords = Coordinates(Decimal("-23.5505"), Decimal("-46.6333"))
        print(coords)  # "-23.5505, -46.6333"
    """
    latitude: Decimal
    longitude: Decimal

    def __post_init__(self) -> None:
        if not (-90 <= self.latitude <= 90):
            raise ValueError(f"Latitude inválida (deve ser -90 a 90): {self.latitude}")
        if not (-180 <= self.longitude <= 180):
            raise ValueError(f"Longitude inválida (deve ser -180 a 180): {self.longitude}")

    @classmethod
    def brazil_center(cls) -> Coordinates:
        """Centro aproximado do Brasil (para mapas sem câmeras com localização)."""
        return cls(Decimal("-14.2350"), Decimal("-51.9253"))

    def distance_to(self, other: Coordinates) -> float:
        """
        Calcula distância aproximada em km até outro ponto (Haversine simplificado).

        Uso:
            dist = coords.distance_to(other_coords)
        """
        import math

        lat1, lon1 = float(self.latitude), float(self.longitude)
        lat2, lon2 = float(other.latitude), float(other.longitude)

        # Conversão para radianos
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

        # Fórmula de Haversine
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return 6371 * c  # Raio da Terra em km

    def __str__(self) -> str:
        return f"{self.latitude:.4f}, {self.longitude:.4f}"


# ─── Endereço IP ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IpAddress(ValueObject):
    """
    Endereço IP validado.

    Suporta IPv4 e IPv6 (validação básica para IPv4).

    Uso:
        ip = IpAddress("192.168.1.100")
        ip.is_private  # True
    """
    value: str

    # Regex simples para IPv4
    _IPV4_RE: ClassVar = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

    def __post_init__(self) -> None:
        # Validação básica de IPv4
        if self._IPV4_RE.match(self.value):
            parts = self.value.split(".")
            for part in parts:
                if not (0 <= int(part) <= 255):
                    raise ValueError(f"Octeto IPv4 inválido: {part}")

    @property
    def is_private(self) -> bool:
        """
        Verifica se é IP privado (RFC 1918).

        Private ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
        """
        return (
            self.value.startswith("192.168.")
            or self.value.startswith("10.")
            or self.value.startswith("172.16.")
            or self.value.startswith("172.17.")
            or self.value.startswith("172.18.")
            or self.value.startswith("172.19.")
            or self.value.startswith("172.20.")
            or self.value.startswith("172.21.")
            or self.value.startswith("172.22.")
            or self.value.startswith("172.23.")
            or self.value.startswith("172.24.")
            or self.value.startswith("172.25.")
            or self.value.startswith("172.26.")
            or self.value.startswith("172.27.")
            or self.value.startswith("172.28.")
            or self.value.startswith("172.29.")
            or self.value.startswith("172.30.")
            or self.value.startswith("172.31.")
            or self.value == "127.0.0.1"
            or self.value == "localhost"
        )

    @property
    def is_localhost(self) -> bool:
        """Verifica se é localhost."""
        return self.value in ("127.0.0.1", "::1", "localhost")

    def __str__(self) -> str:
        return self.value


# ─── Intervalo de Tempo ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimeRange(ValueObject):
    """
    Intervalo de tempo com início e fim.

    Valida que end é posterior a start.

    Uso:
        range = TimeRange(start, end)
        range.contains(some_timestamp)  # True/False
        range.duration_seconds  # 3600.0
    """
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(
                f"end deve ser posterior a start: "
                f"start={self.start}, end={self.end}"
            )

    @property
    def duration_seconds(self) -> float:
        """Duração do intervalo em segundos."""
        return (self.end - self.start).total_seconds()

    @property
    def duration_minutes(self) -> float:
        """Duração do intervalo em minutos."""
        return self.duration_seconds / 60.0

    def contains(self, timestamp: datetime) -> bool:
        """Verifica se um timestamp está dentro deste intervalo."""
        return self.start <= timestamp <= self.end

    def overlaps(self, other: TimeRange) -> bool:
        """Verifica se este intervalo sobrepõe outro."""
        return self.start <= other.end and self.end >= other.start

    def merge(self, other: TimeRange) -> TimeRange:
        """
        Une dois intervalos sobrepostos em um só.

        Raises:
            ValueError: Se os intervalos não se sobrepõem.
        """
        if not self.overlaps(other):
            raise ValueError("Intervalos não se sobrepõem, não podem ser unidos")
        return TimeRange(
            start=min(self.start, other.start),
            end=max(self.end, other.end),
        )

    def __str__(self) -> str:
        return f"{self.start.isoformat()} → {self.end.isoformat()}"


# ─── Confiança de Detecção ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Confidence(ValueObject):
    """
    Confiança de detecção (0.0 a 1.0).

    Valida que o valor está no range correto.

    Uso:
        conf = Confidence(0.95)
        conf.is_high  # True
        float(conf)   # 0.95
    """
    value: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(f"Confiança deve estar entre 0 e 1: {self.value}")

    def __float__(self) -> float:
        return self.value

    @property
    def is_high(self) -> bool:
        """Confiança alta (≥ 0.8)."""
        return self.value >= 0.8

    @property
    def is_medium(self) -> bool:
        """Confiança média (0.5 a 0.8)."""
        return 0.5 <= self.value < 0.8

    @property
    def is_low(self) -> bool:
        """Confiança baixa (< 0.5)."""
        return self.value < 0.5

    def meets_threshold(self, threshold: float) -> bool:
        """Verifica se atinge um threshold mínimo."""
        return self.value >= threshold

    def __str__(self) -> str:
        return f"{self.value:.2%}"


# ─── Hash SHA-256 ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Sha256Hash(ValueObject):
    """
    Hash SHA-256 de arquivo (integridade de gravações).

    Valida que o hash tem 64 caracteres hexadecimais.

    Uso:
        file_hash = Sha256Hash("abc123...")
        str(file_hash)  # "abc123..."
    """
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 64:
            raise ValueError(
                f"Hash SHA-256 deve ter 64 caracteres hexadecimais, "
                f"recebido {len(self.value)} caracteres"
            )
        if not re.match(r"^[a-f0-9]{64}$", self.value):
            raise ValueError("Hash SHA-256 deve conter apenas caracteres hexadecimais")

    @classmethod
    def from_file(cls, file_path: str) -> Sha256Hash:
        """
        Calcula SHA-256 de arquivo (streaming, não carrega tudo em memória).

        Uso:
            file_hash = Sha256Hash.from_file("/path/to/recording.mp4")
        """
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return cls(h.hexdigest())

    @classmethod
    def from_bytes(cls, data: bytes) -> Sha256Hash:
        """Calcula SHA-256 de bytes em memória."""
        return cls(hashlib.sha256(data).hexdigest())

    def verify_file(self, file_path: str) -> bool:
        """
        Verifica se um arquivo corresponde a este hash.

        Uso:
            if not file_hash.verify_file("/path/to/file.mp4"):
                raise IntegrityError("Arquivo adulterado!")
        """
        current = Sha256Hash.from_file(file_path)
        return self.value == current.value

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Sha256Hash('{self.value[:16]}...')"
