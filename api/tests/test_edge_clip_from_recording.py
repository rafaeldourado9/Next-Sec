"""Recorte do clipe de 15 s a partir da gravação contínua local (ADR-018 §4).

Roda **ffmpeg de verdade** — gera um vídeo sintético fazendo o papel do
segmento que o MediaMTX grava (`recordPath: /recordings/%path/%Y-%m-%d_%H-%M-%S-%f`)
e confere que o recorte sai com duração, resolução e conteúdo reais. Mockar o
ffmpeg aqui não testaria nada do que importa: a parte arriscada é exatamente a
aritmética de offset dentro do segmento e a flag de escala.

Contexto de por que isso passou a existir: até a ADR-018 o "clipe" era o JPEG
do evento esticado em vídeo (`render_freeze_frame_clip`) — não havia
alternativa, porque nada guardava vídeo contínuo acessível na hora de montá-lo.
Com a gravação contínua morando na máquina do cliente, passa a haver arquivo
pra recortar.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from vms.event_clips.ffmpeg import cut_clip_from_recording, find_segment_for

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe não disponíveis neste ambiente",
)

_SEGMENT_START = datetime(2026, 8, 1, 14, 30, 0)


def _make_segment(dirpath, name: str, seconds: int = 60, height: int = 720) -> str:
    """Vídeo sintético fazendo o papel de um segmento gravado pelo MediaMTX."""
    path = str(dirpath / name)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"testsrc=duration={seconds}:size={height * 16 // 9}x{height}:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10", path,
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return path


def _probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        check=True, capture_output=True,
    )
    return json.loads(out.stdout)


class TestFindSegment:
    def test_finds_the_segment_containing_the_moment(self, tmp_path) -> None:
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        (cam_dir / "2026-08-01_14-00-00-000000.mp4").touch()
        (cam_dir / "2026-08-01_14-30-00-000000.mp4").touch()
        (cam_dir / "2026-08-01_15-00-00-000000.mp4").touch()

        found = find_segment_for(
            str(tmp_path), "tenant-a/cam-1",
            _SEGMENT_START.astimezone() + timedelta(minutes=7),
        )

        assert found is not None
        segment, offset = found
        assert segment.endswith("2026-08-01_14-30-00-000000.mp4")
        assert offset == pytest.approx(7 * 60, abs=1)

    def test_returns_none_when_the_moment_precedes_every_segment(self, tmp_path) -> None:
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        (cam_dir / "2026-08-01_14-30-00-000000.mp4").touch()

        found = find_segment_for(
            str(tmp_path), "tenant-a/cam-1", _SEGMENT_START.astimezone() - timedelta(hours=1)
        )
        assert found is None

    def test_returns_none_when_the_camera_has_no_recording(self, tmp_path) -> None:
        """Câmera com gravação desligada — o chamador cai no freeze-frame."""
        assert find_segment_for(str(tmp_path), "tenant-a/sem-gravacao", datetime.now(UTC)) is None

    def test_ignores_files_that_are_not_segments(self, tmp_path) -> None:
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        (cam_dir / "leia-me.txt").touch()
        (cam_dir / ".DS_Store").touch()

        assert find_segment_for(str(tmp_path), "tenant-a/cam-1", datetime.now(UTC)) is None


class TestCutClipFromRecording:
    async def test_cuts_a_real_clip_with_the_requested_duration(self, tmp_path) -> None:
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        _make_segment(cam_dir, "2026-08-01_14-30-00-000000.mp4", seconds=60)

        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/cam-1",
            occurred_at=_SEGMENT_START.astimezone() + timedelta(seconds=30),
            duration_seconds=15,
        )

        assert clip is not None
        try:
            info = _probe(clip)
            assert float(info["format"]["duration"]) == pytest.approx(15, abs=1.5)
            # Vídeo de verdade, não um frame parado: mais de um keyframe/frames
            # suficientes pra haver movimento.
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            assert int(video["nb_frames"]) > 30
        finally:
            os.remove(clip)

    async def test_downscales_to_the_storage_budget(self, tmp_path) -> None:
        """O reencode pra 480p é o que faz o clipe caber no orçamento da VPS
        (~500 KB contra ~3,7 MB a 720p — ADR-018 §4)."""
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        _make_segment(cam_dir, "2026-08-01_14-30-00-000000.mp4", seconds=40, height=720)

        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/cam-1",
            occurred_at=_SEGMENT_START.astimezone() + timedelta(seconds=20),
            duration_seconds=10,
            max_height=480,
        )

        assert clip is not None
        try:
            video = next(s for s in _probe(clip)["streams"] if s["codec_type"] == "video")
            assert int(video["height"]) == 480
        finally:
            os.remove(clip)

    async def test_does_not_upscale_a_camera_below_the_limit(self, tmp_path) -> None:
        """Subir a resolução de uma câmera de 360p pra 480p só inventaria bytes."""
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        _make_segment(cam_dir, "2026-08-01_14-30-00-000000.mp4", seconds=30, height=360)

        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/cam-1",
            occurred_at=_SEGMENT_START.astimezone() + timedelta(seconds=15),
            duration_seconds=5,
            max_height=480,
        )

        assert clip is not None
        try:
            video = next(s for s in _probe(clip)["streams"] if s["codec_type"] == "video")
            assert int(video["height"]) == 360
        finally:
            os.remove(clip)

    async def test_event_near_the_segment_start_does_not_fail(self, tmp_path) -> None:
        """`seconds_before` não cabe: corta do início em vez de errar — o clipe
        sai mais curto, o que é muito melhor que ficar sem clipe."""
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        _make_segment(cam_dir, "2026-08-01_14-30-00-000000.mp4", seconds=30)

        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/cam-1",
            occurred_at=_SEGMENT_START.astimezone() + timedelta(seconds=1),
            duration_seconds=10,
            seconds_before=5,
        )

        assert clip is not None
        try:
            assert os.path.getsize(clip) > 0
        finally:
            os.remove(clip)

    async def test_returns_none_without_recording_so_caller_can_fall_back(
        self, tmp_path
    ) -> None:
        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/inexistente",
            occurred_at=datetime.now(UTC),
            duration_seconds=15,
        )
        assert clip is None

    async def test_corrupt_segment_returns_none_instead_of_raising(self, tmp_path) -> None:
        """Segmento truncado por queda de energia no meio da gravação é
        plausível num mini-PC de cliente — não pode derrubar a task."""
        cam_dir = tmp_path / "tenant-a" / "cam-1"
        cam_dir.mkdir(parents=True)
        (cam_dir / "2026-08-01_14-30-00-000000.mp4").write_bytes(b"nao sou um mp4")

        clip = await cut_clip_from_recording(
            recordings_dir=str(tmp_path),
            mediamtx_path="tenant-a/cam-1",
            occurred_at=_SEGMENT_START.astimezone() + timedelta(seconds=5),
            duration_seconds=10,
        )
        assert clip is None
