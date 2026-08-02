@echo off
REM Auto-eleva via UAC e chama install-licensed.ps1 (instalador unico por
REM licenca -- ver ADR-018). Mesmo padrao de INSTALAR.bat, que continua
REM existindo para o caminho anterior (pacote por cliente com WireGuard).
setlocal

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Solicitando permissao de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-licensed.ps1"

echo.
pause
