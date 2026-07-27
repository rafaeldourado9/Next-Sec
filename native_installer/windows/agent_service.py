"""Servico Windows do Next Sec Edge Agent.

Registrado via `agent_service.py install` (ou `next-sec-agent.exe --install-
service` uma vez congelado pelo PyInstaller). O tunel WireGuard e um servico
Windows A PARTE (`WireGuardTunnel$nextsec`, registrado direto pelo
`wireguard.exe /installtunnelservice` -- ver install.ps1), nao gerenciado
por este script.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import traceback
from datetime import datetime

_INSTALL_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "NextSecAgent")
_LOG_FILE = os.path.join(_INSTALL_DIR, "logs", "service.log")


def _log(message: str) -> None:
    """Log em arquivo (nao só no Event Log do Windows) -- um servico pywin32
    empacotado sem message-resource DLL registrada normalmente so mostra
    "a descricao para o evento X nao foi encontrada" no Visualizador de
    Eventos; um arquivo de texto simples e sempre legivel."""
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except OSError:
        pass


def _load_env_file(path: str) -> None:
    """Le config.env e popula os.environ diretamente.

    Necessario porque o Service Control Manager NAO recarrega seu proprio
    bloco de ambiente depois que uma variavel de maquina e adicionada via
    registro (install.ps1 usa `SetEnvironmentVariable(..., "Machine")`) --
    isso so valeria pra processos novos depois de um reboot, ja que
    services.exe mantem o ambiente cacheado desde o proprio boot. O
    instalador grava config.env em disco; carregamos direto daqui.
    """
    if not os.path.isfile(path):
        _log(f"AVISO: config.env nao encontrado em {path}")
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()
    _log(f"config.env carregado de {path}")


try:
    _load_env_file(os.path.join(_INSTALL_DIR, "config.env"))

    # Cobre execucao via `python agent_service.py` direto em dev -- uma vez
    # congelado pelo PyInstaller, `agent` ja vem embutido no proprio exe e
    # este insert e inofensivo (path simplesmente nao existe no ambiente
    # congelado).
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "edge_agent", "src")
    )

    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    from agent.main import main as run_agent
except Exception:
    _log("FALHA NO IMPORT/SETUP:\n" + traceback.format_exc())
    raise


class NextSecAgentService(win32serviceutil.ServiceFramework):
    """Wrapper de servico -- so orquestra start/stop; toda a logica real do
    agent (polling, heartbeat, RTSP/RTMP) e a mesma usada no Docker/Linux
    (`agent.main.EdgeAgent`), sem duplicacao."""

    _svc_name_ = "NextSecAgent"
    _svc_display_name_ = "Next Sec Edge Agent"
    _svc_description_ = (
        "Captura RTSP e envia para o sistema Next Sec via RTMP, atraves do "
        "tunel WireGuard (servico NextSecTunnel)."
    )

    def __init__(self, args: list[str]) -> None:
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        # O SCM entrega o stop request nesta thread -- DIFERENTE da thread
        # onde o event loop do agent roda. `asyncio.Event.set()` direto de
        # outra thread nao e seguro; `call_soon_threadsafe` e a forma
        # correta (ver docstring de `agent.main._main`/`ready_callback`).
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        win32event.SetEvent(self._stop_event)

    def SvcDoRun(self) -> None:
        _log("SvcDoRun iniciado")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        agent_thread = threading.Thread(target=self._run_agent, daemon=True)
        agent_thread.start()
        # SvcDoRun so pode retornar depois do stop -- e isso que mantem o
        # servico "rodando" aos olhos do SCM.
        win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)

    def _run_agent(self) -> None:
        def _ready(loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event) -> None:
            self._loop = loop
            self._shutdown_event = shutdown_event

        try:
            run_agent(_ready)
        except Exception:
            _log("FALHA FATAL NO LOOP DO AGENT:\n" + traceback.format_exc())
            servicemanager.LogErrorMsg("NextSecAgent: falha fatal no loop do agent -- ver logs\\service.log")


if __name__ == "__main__":
    try:
        win32serviceutil.HandleCommandLine(NextSecAgentService)
    except Exception:
        _log("FALHA NO HandleCommandLine:\n" + traceback.format_exc())
        raise
