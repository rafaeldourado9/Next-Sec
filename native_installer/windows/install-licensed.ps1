#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Instala o Next Sec Edge Agent como servico Windows, ativando por licenca.
.DESCRIPTION
    Instalador UNICO -- identico para todos os clientes, sem nenhum segredo
    embutido (ver ADR-018). O cliente digita a chave de licenca e o proprio
    agent troca ela por credenciais junto a VPS.

    Difere de install.ps1 (o caminho anterior) em tres pontos:
      - NAO exige nextsec.conf nem WireGuard: todo o trafego edge->VPS e HTTPS
        para o dominio publico, e o unico fluxo VPS->edge ja ia por WebSocket.
      - NAO exige config.env com AGENT_ID/AGENT_API_KEY: a identidade nasce da
        ativacao, vinculada a esta maquina.
      - Ativa ANTES de registrar o servico, e aborta mostrando o erro ao
        cliente. Ativar depois esconderia "licenca ja usada em outra maquina"
        num log de servico que ninguem vai abrir -- o cliente veria uma
        instalacao "concluida" que simplesmente nao funciona.

    Espera encontrar, no mesmo diretorio deste script:
      - next-sec-agent.exe   (executavel do agent, PyInstaller, modo console)
      - nssm.exe             (wrapper de servico -- ver nota em install.ps1)
      - ffmpeg.exe           (opcional -- se ausente, tenta usar o PATH)

.PARAMETER LicenseKey
    Chave no formato XXXX-XXXXX-XXXXX-XXXXX-XXXXX. Se omitida, e pedida
    interativamente.
.PARAMETER ApiUrl
    URL da VPS (ex.: https://app.seudominio.com).
.EXAMPLE
    .\install-licensed.ps1 -LicenseKey ABCD-12345-67890-ABCDE-FGHIJ -ApiUrl https://app.exemplo.com
#>

param(
    [string]$LicenseKey = "",
    [string]$ApiUrl = ""
)

$ErrorActionPreference = "Stop"

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = "$env:ProgramData\NextSecAgent"
$logDir     = "$installDir\logs"

Write-Host "Instalando Next Sec Edge Agent em $installDir..."

New-Item -ItemType Directory -Force -Path $installDir, $logDir | Out-Null

foreach ($f in @("next-sec-agent.exe", "nssm.exe")) {
    if (-not (Test-Path "$scriptDir\$f")) {
        throw "Arquivo obrigatorio nao encontrado: $f (esperado em $scriptDir)"
    }
}

# --- Dados da ativacao --------------------------------------------------------
if (-not $ApiUrl) {
    $ApiUrl = Read-Host "Endereco do servidor (ex.: https://app.seudominio.com)"
}
if (-not $ApiUrl) { throw "Endereco do servidor e obrigatorio." }

if (-not $LicenseKey) {
    $LicenseKey = Read-Host "Chave de licenca (XXXX-XXXXX-XXXXX-XXXXX-XXXXX)"
}
if (-not $LicenseKey) { throw "Chave de licenca e obrigatoria." }

# --- Para/remove instalacao anterior ANTES de copiar arquivos -----------------
# Precisa vir antes do Copy-Item: se o servico antigo ainda estiver rodando,
# ele mantem next-sec-agent.exe aberto e o Copy-Item falha com
# "being used by another process".
$existingAgentSvc = Get-Service "NextSecAgent" -ErrorAction SilentlyContinue
if ($existingAgentSvc) {
    Write-Host "Servico do agent ja existe -- parando antes de sobrescrever arquivos..."
    $nssmExisting = "$installDir\nssm.exe"
    # nssm escreve em stderr mesmo em operacoes normais -- ver nota detalhada
    # em install.ps1 sobre NativeCommandError + $ErrorActionPreference=Stop.
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if (Test-Path $nssmExisting) {
        & $nssmExisting stop NextSecAgent
        Start-Sleep -Seconds 2
        & $nssmExisting remove NextSecAgent confirm
    } else {
        Stop-Service NextSecAgent -Force
        Start-Sleep -Seconds 2
        sc.exe delete NextSecAgent | Out-Null
    }
    $ErrorActionPreference = $prevPref
    Start-Sleep -Seconds 1
}

Copy-Item "$scriptDir\next-sec-agent.exe" "$installDir\next-sec-agent.exe" -Force
Copy-Item "$scriptDir\nssm.exe" "$installDir\nssm.exe" -Force
if (Test-Path "$scriptDir\ffmpeg.exe") {
    Copy-Item "$scriptDir\ffmpeg.exe" "$installDir\ffmpeg.exe" -Force
}

$agentExe = "$installDir\next-sec-agent.exe"
$nssm     = "$installDir\nssm.exe"

# --- Ativacao (sincrona, ANTES de registrar o servico) ------------------------
# Codigos de saida do subcomando `activate` (ver edge_agent/src/agent/cli.py):
#   0 = ativado (ou ja estava)   1 = falha definitiva   2 = vale tentar de novo
Write-Host ""
Write-Host "Ativando esta instalacao..."
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $agentExe activate $LicenseKey --api-url $ApiUrl --hostname $env:COMPUTERNAME
$activationExit = $LASTEXITCODE
$ErrorActionPreference = $prevPref

if ($activationExit -eq 2) {
    Write-Host ""
    Write-Host "Nao foi possivel falar com o servidor agora." -ForegroundColor Yellow
    $again = Read-Host "Tentar novamente? (S/n)"
    if ($again -notmatch '^[nN]') {
        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $agentExe activate $LicenseKey --api-url $ApiUrl --hostname $env:COMPUTERNAME
        $activationExit = $LASTEXITCODE
        $ErrorActionPreference = $prevPref
    }
}

if ($activationExit -ne 0) {
    Write-Host ""
    Write-Host "Instalacao interrompida: a licenca nao pode ser ativada nesta maquina." -ForegroundColor Red
    Write-Host "Nenhum servico foi registrado. Corrija o problema acima e rode este instalador de novo."
    exit 1
}

# --- Servico do agent (via NSSM) ----------------------------------------------
Write-Host ""
Write-Host "Registrando servico do agent..."
& $nssm install NextSecAgent $agentExe
& $nssm set NextSecAgent AppDirectory $installDir
& $nssm set NextSecAgent DisplayName "Next Sec Edge Agent"
& $nssm set NextSecAgent Description "Captura, analisa e envia eventos para o sistema Next Sec. Gravacao continua permanece nesta maquina."
& $nssm set NextSecAgent Start SERVICE_AUTO_START
& $nssm set NextSecAgent AppStdout "$logDir\agent.out.log"
& $nssm set NextSecAgent AppStderr "$logDir\agent.err.log"
& $nssm set NextSecAgent AppRotateFiles 1
& $nssm set NextSecAgent AppRotateBytes 10485760

# Recuperacao automatica: um servico que morre por um erro transitorio (disco
# ocupado, rede caindo no boot) precisa voltar sozinho -- ninguem monitora o
# mini-PC de uma loja.
& $nssm set NextSecAgent AppExit Default Restart
& $nssm set NextSecAgent AppRestartDelay 10000

# O agent le a identidade de agent.json (gravado pela ativacao acima), nao do
# ambiente -- por isso nao ha AGENT_ID/AGENT_API_KEY aqui. So o ffmpeg
# empacotado precisa ser apontado, ja que nao ha garantia de PATH configurado.
if (Test-Path "$installDir\ffmpeg.exe") {
    & $nssm set NextSecAgent AppEnvironmentExtra "FFMPEG_PATH=$installDir\ffmpeg.exe"
}

& $nssm start NextSecAgent

Write-Host ""
Write-Host "Instalacao concluida." -ForegroundColor Green
Write-Host "  Servico:      NextSecAgent"
Write-Host "  Credenciais:  $installDir\agent.json (acesso restrito)"
Write-Host "  Logs:         $logDir\agent.out.log / agent.err.log"
Write-Host ""
Write-Host "Estado da ativacao:  `"$agentExe`" status"
Write-Host "ID desta maquina:    `"$agentExe`" fingerprint   (peca ao suporte se precisar desvincular)"
