"""Recuperação de stream morto: backoff sem desistir + captura de stderr.

Dois bugs reais achados testando uma câmera Wi-Fi doméstica de verdade
(2026-08-02): a conexão RTSP caiu (`-10054`/`WSAECONNRESET`, instabilidade
de rede comum em câmera doméstica) e (1) o agent desistia de vez depois de
`_MAX_RESTART_ATTEMPTS` (5) tentativas com delay fixo — nenhum cliente real
deveria precisar reiniciar o serviço inteiro porque o Wi-Fi da câmera
piscou — e (2) o `stderr` do ffmpeg, que continha a mensagem de erro real,
era capturado (`stderr=PIPE`) mas nunca lido nem logado — só descobri o
`-10054` reproduzindo o comando manualmente fora do agent.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from agent.stream_manager import (
    StreamManager,
    StreamProcess,
    _INITIAL_RESTART_DELAY_SECONDS,
    _MAX_RESTART_DELAY_SECONDS,
)

pytestmark = pytest.mark.asyncio


class _FakeProcess:
    """Só o suficiente pra simular um processo morto: sem I/O real."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self.pid = 12345


class TestBackoffNeverGivesUpPermanently:
    """A regressão exata: mais tentativas que o antigo `_MAX_RESTART_ATTEMPTS`
    (5) precisam continuar agendando retry, não travar pra sempre."""

    async def test_schedules_a_retry_after_death_instead_of_giving_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vps:1935")
        sp = StreamProcess(camera_id="cam-1", rtsp_url="rtsp://x", rtmp_url="rtmp://x")
        sp.process = _FakeProcess(returncode=1)
        sp._running = True  # noqa: SLF001 — estava rodando, acabou de morrer
        manager._streams[sp.camera_id] = sp  # noqa: SLF001

        t0 = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: t0)
        await manager.restart_dead_streams()

        assert sp._running is False  # noqa: SLF001
        assert sp.next_retry_at == pytest.approx(t0 + _INITIAL_RESTART_DELAY_SECONDS)

    async def test_survives_far_more_failures_than_the_old_hard_cap_of_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O bug antigo desistia definitivamente na 6ª tentativa. Simula 20
        ciclos de morte-e-retentativa e confere que o manager continua
        agendando a próxima — nunca marca a câmera como definitivamente
        perdida."""
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vps:1935")
        sp = StreamProcess(camera_id="cam-1", rtsp_url="rtsp://x", rtmp_url="rtmp://x")
        sp.process = _FakeProcess(returncode=1)
        sp._running = True  # noqa: SLF001
        manager._streams[sp.camera_id] = sp  # noqa: SLF001

        clock = {"t": 1000.0}
        monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

        # `_launch` tentaria rodar ffmpeg de verdade; aqui só interessa que
        # o AGENDAMENTO continue acontecendo. O fake imita a câmera que
        # falha em TODA reconexão: "religa" (como o `_launch` real faria,
        # marcando `_running=True`) mas o processo resultante já nasce
        # morto — a próxima chamada de `restart_dead_streams` detecta essa
        # morte e agenda outra tentativa. Por isso cada ciclo completo
        # (morre → agenda → religa → morre de novo) consome DUAS chamadas.
        async def _fake_launch(stream_process: StreamProcess) -> None:
            stream_process.process = _FakeProcess(returncode=1)
            stream_process._running = True  # noqa: SLF001

        monkeypatch.setattr(manager, "_launch", _fake_launch)

        for _ in range(40):
            clock["t"] += _MAX_RESTART_DELAY_SECONDS + 1  # sempre pula o backoff
            await manager.restart_dead_streams()

        # 40 chamadas (~20 ciclos completos) muito além de qualquer cap
        # antigo de 5 tentativas, e o manager ainda tem uma próxima
        # tentativa agendada — nunca desistiu.
        assert sp.restart_count >= 10
        assert sp.next_retry_at > clock["t"] - _MAX_RESTART_DELAY_SECONDS

    async def test_delay_grows_but_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vps:1935")
        sp = StreamProcess(camera_id="cam-1", rtsp_url="rtsp://x", rtmp_url="rtmp://x")
        sp.restart_count = 10  # bem além do ponto onde o teto já foi atingido
        sp.process = _FakeProcess(returncode=1)
        sp._running = True  # noqa: SLF001
        manager._streams[sp.camera_id] = sp  # noqa: SLF001

        t0 = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: t0)
        await manager.restart_dead_streams()

        assert sp.next_retry_at == pytest.approx(t0 + _MAX_RESTART_DELAY_SECONDS)

    async def test_does_not_retry_before_the_backoff_elapses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vps:1935")
        sp = StreamProcess(camera_id="cam-1", rtsp_url="rtsp://x", rtmp_url="rtmp://x")
        sp.process = _FakeProcess(returncode=1)
        sp._running = False  # noqa: SLF001 — já processado, aguardando o backoff
        sp.next_retry_at = 2000.0
        manager._streams[sp.camera_id] = sp  # noqa: SLF001

        launched = []

        async def _fake_launch(stream_process: StreamProcess) -> None:
            launched.append(stream_process.camera_id)

        monkeypatch.setattr(manager, "_launch", _fake_launch)
        monkeypatch.setattr(time, "monotonic", lambda: 1500.0)  # antes da hora

        await manager.restart_dead_streams()

        assert launched == []

    async def test_still_running_processes_are_left_alone(self) -> None:
        """Health check não pode mexer num processo que ainda está vivo."""
        manager = StreamManager(mediamtx_rtmp_base="rtmp://vps:1935")
        sp = StreamProcess(camera_id="cam-1", rtsp_url="rtsp://x", rtmp_url="rtmp://x")
        sp.process = _FakeProcess(returncode=None)  # ainda rodando
        sp._running = True  # noqa: SLF001
        manager._streams["cam-1"] = sp  # noqa: SLF001

        await manager.restart_dead_streams()

        assert sp._running is True  # noqa: SLF001
        assert sp.restart_count == 0


class TestStderrCapture:
    """Sem isto, a mensagem de erro real do ffmpeg nunca aparecia em lugar
    nenhum — só foi possível descobrir o `-10054` reproduzindo o comando
    manualmente fora do agent."""

    async def test_drains_real_process_stderr_into_the_tail(self) -> None:
        """ffmpeg de verdade, com uma URL RTSP inválida — falha rápido e
        previsível, com uma mensagem de erro real no stderr."""
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "warning", "-rtsp_transport", "tcp",
            "-i", "rtsp://127.0.0.1:1/nonexistent", "-t", "1", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        sp = StreamProcess(camera_id="cam-1", rtsp_url="x", rtmp_url="x")
        sp.process = process

        await StreamManager._drain_stderr(sp)  # noqa: SLF001
        await process.wait()

        tail = sp._stderr_tail.decode("utf-8", errors="replace")  # noqa: SLF001
        assert tail.strip() != ""
        # Porta 1 recusa conexão imediatamente — ffmpeg real relata isso.
        assert "connection" in tail.lower() or "refused" in tail.lower()

    async def test_tail_is_bounded_and_keeps_the_most_recent_bytes(self) -> None:
        """`_STDERR_TAIL_BYTES` existe pra não acumular memória sem limite
        se o processo rodar (e escrever) por muito tempo antes de morrer."""
        marker = "END-OF-OUTPUT-MARKER"
        script = (
            "import sys\n"
            "for i in range(20000):\n"
            "    sys.stderr.write('x')\n"
            f"sys.stderr.write('{marker}')\n"
        )
        process = await asyncio.create_subprocess_exec(
            "python3", "-c", script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        sp = StreamProcess(camera_id="cam-1", rtsp_url="x", rtmp_url="x")
        sp.process = process

        await StreamManager._drain_stderr(sp)  # noqa: SLF001
        await process.wait()

        assert len(sp._stderr_tail) <= 4096  # noqa: SLF001
        # O final (o que importa pra diagnosticar um erro) sobrevive ao corte.
        assert sp._stderr_tail.decode().endswith(marker)  # noqa: SLF001
