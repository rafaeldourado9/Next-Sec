@echo off
REM Auto-eleva via UAC e chama install-licensed.ps1 (instalador unico por
REM licenca -- ver ADR-018). Mesmo padrao de INSTALAR.bat, que continua
REM existindo para o caminho anterior (pacote por cliente com WireGuard).
setlocal

REM UTF-8 no console: as mensagens do agent (e os motivos de falha de
REM ativacao) tem acento, e o codepage padrao do Windows brasileiro as
REM deixaria ilegiveis justamente para quem precisa le-las.
chcp 65001 >nul 2>&1

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Solicitando permissao de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-licensed.ps1"

echo.
pause
