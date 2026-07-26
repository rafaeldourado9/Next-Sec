"""
GPU Check — Verificação de utilização GPU para batch processing.

Usado pelo Batch Pipeline para decidir se deve processar segmentos
ou adiar para evitar sobrecarga da GPU.

Uso:
    if await should_process_batch():
        # GPU livre o suficiente — processar segmento
        await process_segment(...)
    else:
        # GPU ocupada — requeue ou aguardar
        raise GPUBusyError()
"""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Threshold de utilização GPU para batch (0.0-1.0)
GPU_BATCH_THRESHOLD = 0.60  # 60%


async def get_gpu_utilization() -> float | None:
    """
    Retorna utilização atual da GPU via nvidia-smi.

    Returns:
        Utilização como float 0.0-100.0, ou None se GPU indisponível
    """
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        logger.debug("nvidia-smi não encontrado — GPU indisponível")
        return None

    try:
        result = await asyncio.create_subprocess_exec(
            nvidia_smi,
            "--query-gpu=utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            logger.debug("nvidia-smi falhou: %s", stderr.decode().strip())
            return None

        utilization = float(stdout.decode().strip())
        return utilization

    except (subprocess.SubprocessError, ValueError, FileNotFoundError) as exc:
        logger.debug("Erro ao consultar GPU: %s", exc)
        return None


async def should_process_batch() -> bool:
    """
    Verifica se GPU está livre o suficiente para batch processing.

    Returns:
        True se GPU disponível e utilização < 60%
        True se GPU indisponível (fallback: processar em CPU)
    """
    utilization = await get_gpu_utilization()

    if utilization is None:
        # GPU indisponível — fallback para CPU
        logger.debug("GPU indisponível — batch processará em CPU")
        return True

    should = utilization < (GPU_BATCH_THRESHOLD * 100)
    if not should:
        logger.info(
            "GPU ocupada (%.1f%%) — batch processing adiado",
            utilization,
        )
    return should


async def get_gpu_memory_info() -> dict | None:
    """
    Retorna informações de memória GPU.

    Returns:
        Dict com 'total_mb', 'used_mb', 'free_mb' ou None
    """
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None

    try:
        result = await asyncio.create_subprocess_exec(
            nvidia_smi,
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            return None

        parts = stdout.decode().strip().split(",")
        return {
            "total_mb": int(parts[0].strip()),
            "used_mb": int(parts[1].strip()),
            "free_mb": int(parts[2].strip()),
        }

    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


import asyncio
