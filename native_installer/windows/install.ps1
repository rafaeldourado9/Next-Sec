#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Instala o Next Sec Edge Agent + tunel WireGuard como servicos Windows.
.DESCRIPTION
    Roda a partir da pasta baixada no dashboard ("Criar Agent" -> Download).
    Espera encontrar, no mesmo diretorio deste script:
      - next-sec-agent.exe   (executavel do agent, PyInstaller, modo console)
      - nssm.exe             (wrapper de servico -- registra o agent como
                               servico Windows de verdade; ver nota abaixo)
      - nextsec.conf         (config do tunel WireGuard, baixado do dashboard)
      - config.env           (variaveis do agent, baixado do dashboard)
      - ffmpeg.exe           (opcional -- se ausente, tenta usar o PATH)

    NOTA: usa NSSM em vez de registrar o servico via pywin32/win32serviceutil
    diretamente -- um executavel pywin32 congelado pelo PyInstaller nao
    conversa direito com o Service Control Manager (falha ao iniciar sem
    mensagem de erro util). NSSM e um wrapper de servico dedicado e maduro,
    especificamente feito pra isso -- o agent roda como processo de console
    comum, sem nenhuma dependencia de framework de servico embutida nele.
#>

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = "$env:ProgramData\NextSecAgent"
$wgDir = "$installDir\wireguard"
$logDir = "$installDir\logs"

Write-Host "Instalando Next Sec Edge Agent em $installDir..."

New-Item -ItemType Directory -Force -Path $installDir, $wgDir, $logDir | Out-Null

$requiredFiles = @("next-sec-agent.exe", "nssm.exe", "nextsec.conf", "config.env")
foreach ($f in $requiredFiles) {
    if (-not (Test-Path "$scriptDir\$f")) {
        throw "Arquivo obrigatorio nao encontrado: $f (esperado em $scriptDir -- baixe o pacote completo do dashboard)"
    }
}

Copy-Item "$scriptDir\next-sec-agent.exe" "$installDir\next-sec-agent.exe" -Force
Copy-Item "$scriptDir\nssm.exe" "$installDir\nssm.exe" -Force
Copy-Item "$scriptDir\config.env" "$installDir\config.env" -Force
Copy-Item "$scriptDir\nextsec.conf" "$wgDir\nextsec.conf" -Force
if (Test-Path "$scriptDir\ffmpeg.exe") {
    Copy-Item "$scriptDir\ffmpeg.exe" "$installDir\ffmpeg.exe" -Force
}

$nssm = "$installDir\nssm.exe"

# --- Tunel WireGuard ---------------------------------------------------------
$wgExe = "C:\Program Files\WireGuard\wireguard.exe"
if (-not (Test-Path $wgExe)) {
    throw "WireGuard for Windows nao encontrado em '$wgExe'. Instale em https://www.wireguard.com/install/ antes de continuar."
}

$existingTunnel = Get-Service "WireGuardTunnel`$nextsec" -ErrorAction SilentlyContinue
if ($existingTunnel) {
    Write-Host "Tunel ja registrado -- removendo versao anterior antes de reinstalar..."
    & $wgExe /uninstalltunnelservice nextsec
    Start-Sleep -Seconds 2
}

Write-Host "Registrando tunel WireGuard..."
& $wgExe /installtunnelservice "$wgDir\nextsec.conf"
Start-Sleep -Seconds 2

# --- Servico do agent (via NSSM) ----------------------------------------------
$existingAgent = Get-Service "NextSecAgent" -ErrorAction SilentlyContinue
if ($existingAgent) {
    Write-Host "Servico do agent ja existe -- removendo versao anterior antes de reinstalar..."
    # nssm escreve em stderr mesmo em operacoes normais (ex: "service not
    # started" ao tentar parar um servico que nunca rodou) -- redirecionar
    # stderr faz o PowerShell embrulhar isso num NativeCommandError e, com
    # $ErrorActionPreference=Stop, aborta o script por um aviso inofensivo.
    # Sem redirecionar, e so texto no console, nao interrompe nada.
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $nssm stop NextSecAgent
    Start-Sleep -Seconds 2
    & $nssm remove NextSecAgent confirm
    $ErrorActionPreference = $prevPref
}

Write-Host "Registrando servico do agent..."
& $nssm install NextSecAgent "$installDir\next-sec-agent.exe"
& $nssm set NextSecAgent AppDirectory $installDir
& $nssm set NextSecAgent DisplayName "Next Sec Edge Agent"
& $nssm set NextSecAgent Description "Captura RTSP e envia para o sistema Next Sec via RTMP, atraves do tunel WireGuard (servico WireGuardTunnel`$nextsec)."
& $nssm set NextSecAgent Start SERVICE_AUTO_START
& $nssm set NextSecAgent AppStdout "$logDir\agent.out.log"
& $nssm set NextSecAgent AppStderr "$logDir\agent.err.log"
& $nssm set NextSecAgent AppRotateFiles 1
& $nssm set NextSecAgent AppRotateBytes 10485760

# Variaveis do agent -- lidas de config.env e passadas direto pro processo
# via NSSM (AppEnvironmentExtra), sem depender do ambiente de MAQUINA do
# Windows (que so seria visto por um processo novo depois de reboot).
$envPairs = @()
Get-Content "$installDir\config.env" | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') {
        $envPairs += "$($matches[1].Trim())=$($matches[2].Trim())"
    }
}
if (Test-Path "$installDir\ffmpeg.exe") {
    $envPairs += "FFMPEG_PATH=$installDir\ffmpeg.exe"
}
if ($envPairs.Count -gt 0) {
    & $nssm set NextSecAgent AppEnvironmentExtra @envPairs
}

& $nssm start NextSecAgent

Write-Host ""
Write-Host "Instalacao concluida." -ForegroundColor Green
Write-Host "  Tunel:  WireGuardTunnel`$nextsec"
Write-Host "  Agent:  NextSecAgent"
Write-Host ""
Write-Host "Verifique com: Get-Service NextSecAgent, 'WireGuardTunnel*'"
Write-Host "Logs em: $logDir\agent.out.log / agent.err.log"
