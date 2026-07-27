# -*- mode: python ; coding: utf-8 -*-
"""Build do executável de serviço Windows do Next Sec Edge Agent.

Diferente de `edge_agent/packaging/agent.spec` (console puro, usado no
Linux/debug local) — este parte de `agent_service.py`: o próprio .exe sabe
se registrar/iniciar/parar como serviço Windows via pywin32
(`win32serviceutil.HandleCommandLine`), e é o que o SCM de fato invoca
quando o serviço inicia no boot.
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
