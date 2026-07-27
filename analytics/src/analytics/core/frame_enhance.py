"""Melhoria de frame sob demanda ("Analisar Evento").

Não roda em todo evento — só quando o usuário pede, a partir do snapshot já
salvo (ver `analytics/router.py::get_event_snapshot` no lado da API). Recorta
ao redor do bbox da detecção (se houver) antes de escalar — aplicar
melhoria no frame inteiro desperdiça a maior parte do processamento em fundo
irrelevante.

Dois caminhos, escolhidos automaticamente:
- GFPGAN, se o recorte tem um rosto reconhecível — restaura e reconstrói
  detalhe de rosto borrado/comprimido de câmera real (bem melhor que upscale
  genérico pro caso de uso principal: identificar quem é a pessoa).
- EDSR (mesma API cv2.dnn_superres já usada no projeto), quando não há
  rosto — upscale geral melhor que o FSRCNN anterior, sem dependência nova.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import cv2
import numpy as np

from analytics.core.config import get_settings

logger = logging.getLogger(__name__)

_SNAPSHOTS_ROOT = Path("/snapshots")

_edsr = None      # cv2.dnn_superres.DnnSuperResImpl — lazy singleton
_gfpganer = None  # gfpgan.GFPGANer — lazy singleton
_MAX_CROP_SIDE = 400  # limite antes do upscale — evita rodar em recortes gigantes


def _shim_basicsr_torchvision_compat() -> None:
    """basicsr (dependência do gfpgan) importa
    `torchvision.transforms.functional_tensor`, removido em torchvision
    >=0.17 (a função que ele usa de lá, `rgb_to_grayscale`, migrou pra
    `torchvision.transforms.functional`). Sem isso `import gfpgan` quebra
    com ImportError na hora — incompatibilidade conhecida e ampla da
    comunidade (basicsr não é atualizado há tempo), não específica deste
    projeto. Cria o módulo que falta só com a função que o basicsr
    realmente usa, antes do primeiro import de gfpgan/basicsr.
    """
    if "torchvision.transforms.functional_tensor" in sys.modules:
        return
    try:
        import torchvision.transforms.functional_tensor  # noqa: F401
        return  # torchvision antigo o suficiente — módulo já existe
    except ImportError:
        pass
    import torchvision.transforms.functional as _F

    shim = types.ModuleType("torchvision.transforms.functional_tensor")
    shim.rgb_to_grayscale = _F.rgb_to_grayscale
    sys.modules["torchvision.transforms.functional_tensor"] = shim


def _get_edsr():
    global _edsr
    if _edsr is not None:
        return _edsr if _edsr is not False else None
    settings = get_settings()
    try:
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(settings.edsr_model_path)
        sr.setModel("edsr", settings.superres_scale)
        _edsr = sr
        logger.info("frame_enhance: EDSR (x%d) carregado", settings.superres_scale)
    except Exception:
        logger.exception("frame_enhance: falha ao carregar EDSR")
        _edsr = False
    return _edsr if _edsr is not False else None


def _get_gfpganer():
    global _gfpganer
    if _gfpganer is not None:
        return _gfpganer if _gfpganer is not False else None
    settings = get_settings()
    try:
        _shim_basicsr_torchvision_compat()
        from gfpgan import GFPGANer

        _gfpganer = GFPGANer(
            model_path=settings.gfpgan_model_path,
            upscale=settings.superres_scale,
            arch="clean",
            channel_multiplier=2,
            bg_upsampler=None,
        )
        logger.info("frame_enhance: GFPGAN carregado")
    except Exception:
        logger.exception("frame_enhance: falha ao carregar GFPGAN")
        _gfpganer = False
    return _gfpganer if _gfpganer is not False else None


def _crop_with_padding(
    image: np.ndarray, bbox: list[float], padding_pct: float = 0.4
) -> np.ndarray:
    """Recorta a imagem ao redor de um bbox normalizado (0-1), com padding."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    box_w, box_h = (x2 - x1), (y2 - y1)
    pad_x, pad_y = box_w * padding_pct, box_h * padding_pct

    px1 = max(0.0, x1 - pad_x)
    py1 = max(0.0, y1 - pad_y)
    px2 = min(1.0, x2 + pad_x)
    py2 = min(1.0, y2 + pad_y)

    left, top = int(px1 * w), int(py1 * h)
    right, bottom = int(px2 * w), int(py2 * h)
    if right <= left or bottom <= top:
        return image
    return image[top:bottom, left:right]


def _encode_png(image: np.ndarray) -> bytes | None:
    """PNG (lossless) — não JPEG. A imagem já passou por reconstrução de
    detalhe (GFPGAN/EDSR); codificar isso em JPEG reintroduz artefato de
    compressão bem em cima do que acabou de ser reconstruído, antes da
    imagem nem chegar na tela do usuário. É um recorte pequeno — não há
    motivo real pra aceitar perda aqui.
    """
    ok, buf = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        return None
    return buf.tobytes()


def enhance_event_frame(image_path: str, bbox: list[float] | None = None) -> bytes | None:
    """Lê o snapshot do evento, recorta ao redor do bbox (se houver) e melhora.

    Tenta GFPGAN primeiro (só usa o resultado se achou um rosto de verdade
    no recorte); sem rosto, cai pro EDSR. Retorna os bytes do PNG resultante,
    ou None se o snapshot não existir ou nenhum modelo puder ser carregado.
    """
    full_path = _SNAPSHOTS_ROOT / image_path.lstrip("/")
    data = cv2.imread(str(full_path))
    if data is None:
        logger.warning("frame_enhance: snapshot não encontrado: %s", full_path)
        return None

    region = _crop_with_padding(data, bbox) if bbox and len(bbox) == 4 else data

    # Recortes maiores que o limite são reduzidos antes de melhorar — tanto
    # GFPGAN quanto EDSR ficam mais lentos (sem ganho real) em entradas
    # grandes; o objetivo aqui é sempre um recorte pequeno, não o frame todo.
    h, w = region.shape[:2]
    if max(h, w) > _MAX_CROP_SIDE:
        scale = _MAX_CROP_SIDE / max(h, w)
        region = cv2.resize(region, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gfpganer = _get_gfpganer()
    if gfpganer is not None:
        try:
            # only_center_face=True: o recorte já é centrado na pessoa do
            # evento (padding em torno do bbox da detecção) — restaura o
            # rosto principal, não um rosto de fundo que tenha entrado na
            # margem de padding.
            _, restored_faces, _ = gfpganer.enhance(
                region, has_aligned=False, only_center_face=True, paste_back=True,
            )
            if restored_faces:
                # restored_faces[i] é o rosto alinhado 512x512 já restaurado
                # — usar esse, não o paste-back de volta no tamanho
                # original, que devolveria o rosto pequeno de novo.
                return _encode_png(restored_faces[0])
        except Exception:
            logger.exception("frame_enhance: falha ao rodar GFPGAN, tentando EDSR")

    edsr = _get_edsr()
    if edsr is None:
        return None
    try:
        enhanced = edsr.upsample(region)
    except Exception:
        logger.exception("frame_enhance: falha ao rodar EDSR")
        return None
    return _encode_png(enhanced)
