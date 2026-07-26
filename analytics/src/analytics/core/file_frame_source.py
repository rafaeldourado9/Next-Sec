"""
FileFrameSource — Extração de frames de arquivos de vídeo gravados.

Similar ao FrameSource (RTSP) mas para arquivos fMP4/MP4 locais.
Usado pelo Batch Pipeline para processar gravações offline.

Uso:
    source = FileFrameSource("/recordings/tenant-1/cam-abc/2026/04/12/10-00-00.mp4", fps=1)
    if source.open():
        while True:
            frame, timestamp = source.read()
            if frame is None:
                break
            # Processar frame com timestamp original do vídeo
    source.close()
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FileFrameSource:
    """
    Extrai frames de um arquivo de vídeo gravado.

    Suporta controle de FPS para sample inteligente:
    - Vídeo original: 30 FPS
    - Sample 1 FPS: lê 1 frame a cada 30 frames
    - Mantém timestamp original de cada frame lido
    """

    def __init__(
        self,
        file_path: str,
        fps: int = 1,
    ) -> None:
        """
        Inicializa leitor de arquivo de vídeo.

        Args:
            file_path: Caminho absoluto do arquivo de vídeo (fMP4/MP4)
            fps: Frames por segundo para sample (1 = 1 frame/segundo)
        """
        self._file_path = file_path
        self._target_fps = fps
        self._cap: cv2.VideoCapture | None = None
        self._original_fps: float = 0
        self._frame_skip: int = 0
        self._frame_index: int = 0
        self._start_time: datetime | None = None
        self._total_frames: int = 0
        self._opened = False

    def open(self) -> bool:
        """
        Abre o arquivo de vídeo.

        Returns:
            True se abriu com sucesso, False caso contrário
        """
        self._cap = cv2.VideoCapture(self._file_path)
        if not self._cap.isOpened():
            logger.error("Não foi possível abrir arquivo de vídeo: %s", self._file_path)
            return False

        self._original_fps = self._cap.get(cv2.CAP_PROP_FPS)
        if self._original_fps <= 0:
            self._original_fps = 25  # fallback padrão

        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._frame_skip = max(1, int(self._original_fps / self._target_fps))
        self._frame_index = 0
        self._opened = True

        # Calcula timestamp de início baseado no tempo de criação do arquivo
        # (aproximação — o timestamp exato vem do path do arquivo)
        self._start_time = datetime.now(timezone.utc)

        logger.debug(
            "FileFrameSource aberto: %s (%.1f FPS original, sample %d → 1 frame, total %d frames)",
            self._file_path,
            self._original_fps,
            self._frame_skip,
            self._total_frames,
        )
        return True

    def read(self) -> tuple[np.ndarray | None, datetime]:
        """
        Lê próximo frame no intervalo de sample.

        Returns:
            Tuple (frame, timestamp_original):
            - frame: np.ndarray BGR ou None se fim do arquivo
            - timestamp_original: timestamp calculado do frame no vídeo
        """
        if not self._cap or not self._opened:
            return None, datetime.now(timezone.utc)

        # Avança frames até o próximo sample
        while True:
            ret, frame = self._cap.read()
            if not ret:
                # Fim do arquivo
                self._opened = False
                return None, datetime.now(timezone.utc)

            if self._frame_index % self._frame_skip == 0:
                # Calcula timestamp original deste frame
                timestamp = self._calculate_frame_timestamp(self._frame_index)
                return frame, timestamp

            self._frame_index += 1

    def _calculate_frame_timestamp(self, frame_index: int) -> datetime:
        """
        Calcula timestamp aproximado de um frame no vídeo.

        Usa o índice do frame e FPS original para calcular o offset
        desde o início do vídeo.
        """
        if self._start_time is None:
            return datetime.now(timezone.utc)

        offset_seconds = frame_index / self._original_fps
        return self._start_time + timedelta(seconds=offset_seconds)

    def close(self) -> None:
        """Libera recursos do leitor de vídeo."""
        if self._cap:
            self._cap.release()
            self._cap = None
            self._opened = False
            logger.debug("FileFrameSource fechado: %s", self._file_path)

    @property
    def is_opened(self) -> bool:
        """Verifica se o arquivo está aberto e pronto para leitura."""
        return self._opened

    @property
    def total_frames(self) -> int:
        """Total de frames no arquivo (antes do sample)."""
        return self._total_frames

    @property
    def duration_seconds(self) -> float:
        """Duração total do vídeo em segundos."""
        if self._original_fps <= 0:
            return 0
        return self._total_frames / self._original_fps

    @property
    def frames_to_read(self) -> int:
        """Quantos frames serão lidos após o sample."""
        if self._frame_skip <= 0:
            return 0
        return self._total_frames // self._frame_skip

    def __enter__(self) -> FileFrameSource:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
