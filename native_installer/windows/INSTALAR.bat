@echo off
REM Next Sec Edge Agent -- instalador com auto-elevacao.
REM Duplo clique nisso: se nao estiver rodando como Administrador, relanca a
REM si mesmo pedindo elevacao (UAC) automaticamente, depois roda install.ps1.
net session >nul 2>&1
if %errorLevel% == 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
    pause
) else (
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
)
