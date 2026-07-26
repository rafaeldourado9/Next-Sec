"""Carregamento de configuração local de zonas para os plugins.

Zonas são configuradas por deploy, não pelo VMS. Cada câmera pode ter
uma lista de zonas (polígonos) usadas pelos plugins de detecção.

Fontes suportadas (em ordem de prioridade):
  1. Arquivo zones.yaml no diretório de trabalho
  2. Variável de ambiente PLUGIN_ZONES_JSON (JSON serializado)

Formato esperado (YAML ou JSON):
  <camera_id>:
    - id: "zona-1"
      name: "Entrada principal"
      ia_type: "intrusion"
      polygon_points: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
      config: {}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from analytics.core.plugin_base import ROIConfig

logger = logging.getLogger(__name__)

_ZONES_FILE = Path("zones.yaml")
_ZONES_ENV_VAR = "PLUGIN_ZONES_JSON"


def load_zones_config() -> dict[str, list[ROIConfig]]:
    """
    Carrega configuração de zonas para os plugins.

    Retorna dict mapeando camera_id → lista de ROIConfig.
    Se nenhuma configuração encontrada, retorna dict vazio
    (plugins processam sem restrição de zona).
    """
    # Tenta arquivo YAML primeiro
    if _ZONES_FILE.exists():
        try:
            return _load_from_yaml(_ZONES_FILE)
        except Exception:
            logger.exception("Erro ao ler %s — ignorando", _ZONES_FILE)

    # Tenta variável de ambiente
    env_value = os.environ.get(_ZONES_ENV_VAR)
    if env_value:
        try:
            return _parse_zones_dict(json.loads(env_value))
        except Exception:
            logger.exception("Erro ao parsear %s — ignorando", _ZONES_ENV_VAR)

    logger.info(
        "Nenhuma configuração de zonas encontrada — plugins rodam sem restrição de zona"
    )
    return {}


def _load_from_yaml(path: Path) -> dict[str, list[ROIConfig]]:
    """Carrega zonas de arquivo YAML."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML não instalado — %s ignorado", path)
        return {}

    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return _parse_zones_dict(data)


def _parse_zones_dict(data: dict) -> dict[str, list[ROIConfig]]:
    """Converte dict bruto em {camera_id: [ROIConfig]}."""
    result: dict[str, list[ROIConfig]] = {}
    for camera_id, zone_list in data.items():
        if not isinstance(zone_list, list):
            continue
        rois: list[ROIConfig] = []
        for z in zone_list:
            try:
                rois.append(
                    ROIConfig(
                        id=str(z.get("id", f"{camera_id}-zone")),
                        name=str(z.get("name", "zona")),
                        ia_type=str(z.get("ia_type", "intrusion")),
                        polygon_points=z.get("polygon_points", []),
                        config=z.get("config", {}),
                    )
                )
            except Exception:
                logger.warning("Zona inválida em câmera %s: %s", camera_id, z)
        result[camera_id] = rois
    return result
