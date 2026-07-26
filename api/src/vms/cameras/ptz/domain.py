"""Entidades de domínio PTZ (Pan-Tilt-Zoom)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PtzCommand:
    """Comando de movimento PTZ contínuo."""

    pan: float = 0.0    # -1.0 a 1.0 (negativo = esquerda, positivo = direita)
    tilt: float = 0.0   # -1.0 a 1.0 (negativo = baixo, positivo = cima)
    zoom: float = 0.0   # -1.0 a 1.0 (negativo = zoom out, positivo = zoom in)
    speed: float = 0.5  # 0.0 a 1.0


@dataclass
class PtzPreset:
    """Preset de posição PTZ salvo na câmera."""

    token: str
    name: str | None = None


@dataclass
class PtzCapabilities:
    """Capacidades PTZ de uma câmera ONVIF."""

    ptz_url: str
    profile_token: str
    presets: list[PtzPreset] = field(default_factory=list)
