@echo off
REM Next Sec Edge — Nivel 1 (Docker dedicado) -- desinstalador com auto-elevacao.
net session >nul 2>&1
if %errorLevel% == 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-docker.ps1"
    pause
) else (
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
)
