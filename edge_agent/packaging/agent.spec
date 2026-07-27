# -*- mode: python ; coding: utf-8 -*-
"""Build do executável nativo do edge_agent (onefile) — usado pelos
instaladores Windows e Linux (`native_installer/`).

Deliberadamente NÃO inclui ultralytics/opencv/numpy/torch — já removidos de
pyproject.toml (nunca usados em código real, ver `agent/hardware.py`, que já
trata `import torch` como opcional). ffmpeg também NÃO é embutido no exe
(infla o binário e complica build cross-platform) — os instaladores baixam/
empacotam um binário estático à parte e apontam `FFMPEG_PATH` pra ele.
"""
import sys
from pathlib import Path

project_root = Path(SPECPATH).parent

# pywin32 só existe (e só é necessário) no build Windows — incluir esses
# hiddenimports num build Linux faria o PyInstaller falhar procurando
# módulos que não existem lá.
hiddenimports = []
if sys.platform == "win32":
    hiddenimports = ["win32timezone", "win32serviceutil", "win32service", "win32event", "servicemanager"]

a = Analysis(
    [str(project_root / "packaging" / "run_agent.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
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
