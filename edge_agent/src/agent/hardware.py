"""Hardware detection — detecta CPU, RAM e GPU disponíveis."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

AcceleratorType = Literal["cuda", "rocm", "mps", "cpu", "none"]


@dataclass
class HardwareInfo:
    """Informações de hardware detectadas."""

    cpu_cores: int
    cpu_model: str
    ram_gb: float
    has_gpu: bool
    gpu_name: str | None
    gpu_vram_gb: float
    accelerator: AcceleratorType


def detect_hardware() -> HardwareInfo:
    """Detecta hardware disponível na máquina do cliente."""
    import psutil

    # CPU e RAM
    cpu_cores = psutil.cpu_count(logical=True)
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)

    # Tentar detectar CPU model
    cpu_model = _get_cpu_model()

    # GPU detection
    gpu_info = _detect_gpu()

    info = HardwareInfo(
        cpu_cores=cpu_cores,
        cpu_model=cpu_model,
        ram_gb=ram_gb,
        has_gpu=gpu_info["has_gpu"],
        gpu_name=gpu_info["name"],
        gpu_vram_gb=gpu_info["vram_gb"],
        accelerator=gpu_info["accelerator"],
    )

    logger.info("Hardware detectado: %s", info)
    return info


def _get_cpu_model() -> str:
    """Tenta obter modelo do CPU."""
    import platform
    return platform.processor() or "Unknown"


def _detect_gpu() -> dict:
    """Detecta GPU e tipo de acelerador."""
    # Tentar NVIDIA primeiro
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            parts = lines[0].split(",")
            name = parts[0].strip()
            vram = float(parts[1].strip())
            return {
                "has_gpu": True,
                "name": name,
                "vram_gb": round(vram / 1024, 1),
                "accelerator": "cuda",
            }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Tentar ROCm (AMD)
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return {
                "has_gpu": True,
                "name": "AMD GPU (ROCm)",
                "vram_gb": 8.0,  # Default estimativa
                "accelerator": "rocm",
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Tentar MPS (Apple Silicon)
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return {
                "has_gpu": True,
                "name": "Apple Silicon (MPS)",
                "vram_gb": 8.0,  # Compartilhado com RAM
                "accelerator": "mps",
            }
    except ImportError:
        pass

    return {
        "has_gpu": False,
        "name": None,
        "vram_gb": 0.0,
        "accelerator": "cpu",
    }


def check_minimum_requirements(
    hardware: HardwareInfo,
    min_ram_gb: float = 4.0,
    require_gpu: bool = False,
) -> tuple[bool, list[str]]:
    """Verifica se hardware atende requisitos mínimos."""
    issues = []

    if hardware.ram_gb < min_ram_gb:
        issues.append(f"RAM insuficiente: {hardware.ram_gb} GB < {min_ram_gb} GB mínimo")

    if require_gpu and not hardware.has_gpu:
        issues.append("GPU requerida mas não detectada")

    return (len(issues) == 0, issues)
