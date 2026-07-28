# -*- mode: python ; coding: utf-8 -*-
"""Build alternativo (NÃO USADO pelo instalador atual) do .exe registrado
nativamente via pywin32/SCM.

ATENÇÃO — achado em produção (2026-07-28): `install.ps1` usa NSSM pra
registrar o serviço (`nssm install NextSecAgent next-sec-agent.exe`), NÃO
`agent_service.py install`/SCM nativo — o NSSM invoca o exe como processo
de console comum (sem args), e um exe construído a partir DESTE spec (que
embrulha `win32serviceutil.ServiceFramework`/`HandleCommandLine`) não
reconhece essa invocação como "start pelo SCM" e cai no fallback de
imprimir a mensagem de uso e sair — serviço entra em crash-loop e o NSSM
acaba marcando como "Paused". `agent.err.log`/`agent.out.log` ficam vazios
(o processo nem chega a rodar `SvcDoRun`); o sintoma real fica só em
`C:\ProgramData\NextSecAgent\logs\service.log`.

O build correto pro instalador atual (NSSM) é
`edge_agent/packaging/agent.spec` (console puro, `console=True`,
entry point `packaging/run_agent.py` → `agent.main.main()` direto, sem
nenhuma dependência de framework de serviço). Esse spec aqui
(`agent_service.spec` + `agent_service.py`) só faria sentido se um dia o
instalador for trocado pra registrar o serviço nativamente via SCM em vez
de NSSM — não é o caso hoje. Não usar pra gerar o `.exe` de produção.
"""
from pathlib import Path

this_dir = Path(SPECPATH)
edge_agent_root = this_dir.parent.parent / "edge_agent"

a = Analysis(
    [str(this_dir / "agent_service.py")],
    pathex=[str(edge_agent_root / "src"), str(this_dir)],
    binaries=[],
    datas=[],
    hiddenimports=["win32timezone", "win32serviceutil", "win32service", "win32event", "servicemanager"],
    excludes=["torch", "ultralytics", "cv2", "numpy", "matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="next-sec-agent",
    console=True,
    onefile=True,
)
