"""Captura de frames RTSP via OpenCV."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_RECONNECT_INTERVAL = 3.0  # segundos entre tentativas de reconexão
_LOG_EVERY = 30            # logar warning a cada N falhas consecutivas

# Força RTSP sobre TCP no backend FFmpeg do OpenCV. Sem isso o FFmpeg tenta
# UDP por padrão — quando o analytics conectava via MediaMTX, o MediaMTX já
# forçava TCP nessa câmera especificamente (fix anterior desta sessão: UDP
# perdia pacote nela). Conectar direto via OpenCV perdia essa correção sem
# ninguém perceber, e é bem provável que seja a causa real da reconexão
# ficar tão frequente (a cada poucos segundos) depois da mudança pra conexão
# direta — precisa ser setado antes de qualquer cv2.VideoCapture(..., CAP_FFMPEG).
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class FrameSource:
    """
    Leitor de frames RTSP com controle de FPS, backoff e reconexão automática.

    Quando o stream fica offline, evita flood de logs e tenta reabrir a
    cada _RECONNECT_INTERVAL segundos sem travar o loop do orchestrator.
    """

    def __init__(self, stream_url: str, fps: int = 1) -> None:
        self._url = stream_url
        self._fps = fps
        self._cap: Any = None
        self._last_read: float = 0.0
        self._fail_count: int = 0
        self._last_reconnect: float = 0.0

    def open(self) -> bool:
        """Abre conexão RTSP. Retorna True se sucesso."""
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            logger.error("Falha ao abrir stream: %s", self._url)
            return False
        logger.info("Stream aberto: %s", self._url)
        self._fail_count = 0
        self._last_reconnect = time.monotonic()
        return True

    def read(self) -> np.ndarray | None:
        """
        Lê próximo frame respeitando o FPS configurado.

        Retorna None se não há frame disponível, se não passou tempo suficiente,
        ou se o stream está offline.  Reconnects automáticos a cada
        _RECONNECT_INTERVAL segundos quando o stream falha.
        """
        if self._cap is None:
            return None

        # Uma tentativa de reconexão que falha a abrir deixa _cap num estado
        # "fechado" — sem isto, a próxima chamada cairia direto no retorno
        # None abaixo pra sempre, sem nunca tentar de novo (achado em teste
        # local: câmera voltava a ficar disponível segundos depois, mas o
        # analytics já tinha parado de ler frames dela silenciosamente).
        if not self._cap.isOpened():
            self._try_reconnect()
            return None

        now = time.monotonic()
        interval = 1.0 / self._fps
        if now - self._last_read < interval:
            # Descarta frames para manter o FPS correto
            self._cap.grab()
            return None

        ret, frame = self._cap.read()
        if not ret:
            self._fail_count += 1

            # Log throttled: primeira falha e a cada _LOG_EVERY depois
            if self._fail_count == 1 or self._fail_count % _LOG_EVERY == 0:
                logger.warning(
                    "Falha ao ler frame de %s (tentativa %d)",
                    self._url,
                    self._fail_count,
                )

            self._try_reconnect()
            return None

        if self._fail_count > 0:
            logger.info("Stream recuperado após %d falha(s): %s", self._fail_count, self._url)
            self._fail_count = 0

        self._last_read = now
        return frame

    def _try_reconnect(self) -> None:
        """Tenta reabrir o stream, respeitando _RECONNECT_INTERVAL entre tentativas."""
        now = time.monotonic()
        if now - self._last_reconnect < _RECONNECT_INTERVAL:
            return

        self._last_reconnect = now
        logger.info("Reconectando a %s...", self._url)
        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if self._cap.isOpened():
            logger.info("Reconectado a %s após %d falhas", self._url, self._fail_count)
            self._fail_count = 0
        else:
            logger.warning("Reconexão falhou: %s", self._url)

    def close(self) -> None:
        """Fecha a conexão com o stream."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Stream fechado: %s", self._url)

    @property
    def is_open(self) -> bool:
        """Verifica se o stream está aberto."""
        return self._cap is not None and self._cap.isOpened()
