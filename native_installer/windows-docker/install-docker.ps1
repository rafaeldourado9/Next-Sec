#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Instala o Next Sec Edge (Nivel 1 - Docker dedicado) como stack Docker Compose
    que sobe sozinha a cada boot, + tunel WireGuard.
.DESCRIPTION
    Roda a partir da pasta baixada no dashboard admin (onboarding de cliente ->
    "Baixar pacote completo"). Espera encontrar, no mesmo diretorio deste script:
      - docker-compose.edge.yml
      - .env.edge             (VMS_API_URL/VMS_API_KEY ja preenchidos)
      - nextsec.conf          (config do tunel WireGuard)

    Pre-requisito: Docker Desktop ja instalado (nao instalamos silenciosamente --
    exige reboot pra habilitar WSL2 em algumas maquinas, risco grande demais pra
    fazer sem supervisao humana. Ver docs/DEPLOY_EDGE.md).

    Auto-start apos reboot: Docker Desktop e um app grafico, nao roda headless
    sem sessao logada. A solucao (escolhida deliberadamente, ver docs/DEPLOY_EDGE.md
    secao de auto-start) e: login automatico do Windows (opcional, com aviso)
    + Docker Desktop "iniciar ao logar" + uma Scheduled Task "At log on" que
    espera o daemon subir e roda 'docker compose up -d'.
#>

$ErrorActionPreference = "Stop"

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = "$env:ProgramData\NextSecEdge"
$logDir     = "$installDir\logs"
$tunnelName = "nextsec-edge"

Write-Host "Instalando Next Sec Edge (Nivel 1 - Docker dedicado) em $installDir..."

New-Item -ItemType Directory -Force -Path $installDir, $logDir | Out-Null

$requiredFiles = @("docker-compose.edge.yml", ".env.edge", "nextsec.conf")
foreach ($f in $requiredFiles) {
    if (-not (Test-Path "$scriptDir\$f")) {
        throw "Arquivo obrigatorio nao encontrado: $f (esperado em $scriptDir -- baixe o pacote completo do painel admin)"
    }
}

# --- Docker Desktop (pre-requisito, nao instalamos automaticamente) --------
$dockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
if (-not (Test-Path $dockerExe)) {
    throw "Docker Desktop nao encontrado em '$dockerExe'. Instale em https://www.docker.com/products/docker-desktop/ antes de continuar (exige reboot pra habilitar WSL2 -- por isso este instalador nao faz isso sozinho)."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop instalado mas o comando 'docker' nao esta no PATH -- abra o Docker Desktop manualmente pelo menos uma vez e rode este instalador de novo."
}

# --- Tunel WireGuard --------------------------------------------------------
$wgExe = "C:\Program Files\WireGuard\wireguard.exe"
if (-not (Test-Path $wgExe)) {
    throw "WireGuard for Windows nao encontrado em '$wgExe'. Instale em https://www.wireguard.com/install/ antes de continuar."
}

$existingTunnel = Get-Service "WireGuardTunnel`$$tunnelName" -ErrorAction SilentlyContinue
if ($existingTunnel) {
    Write-Host "Tunel ja registrado -- removendo versao anterior antes de reinstalar..."
    & $wgExe /uninstalltunnelservice $tunnelName
    Start-Sleep -Seconds 2
}

Write-Host "Registrando tunel WireGuard..."
Copy-Item "$scriptDir\nextsec.conf" "$installDir\$tunnelName.conf" -Force
& $wgExe /installtunnelservice "$installDir\$tunnelName.conf"
Start-Sleep -Seconds 2

# --- Arquivos da stack -------------------------------------------------------
Copy-Item "$scriptDir\docker-compose.edge.yml" "$installDir\docker-compose.edge.yml" -Force
Copy-Item "$scriptDir\.env.edge" "$installDir\.env.edge" -Force

# --- Docker Desktop "iniciar ao logar" (best-effort) -------------------------
# Em vez de tentar editar o settings.json interno do Docker Desktop (formato
# muda entre versoes -- achado durante o levantamento pra este instalador),
# usamos o mecanismo padrao e estavel do proprio Windows: uma entrada em
# HKCU\...\Run. Se o Docker Desktop ja tiver criado a dele (usuario ja
# habilitou manualmente "Start Docker Desktop when you sign in"), nao mexe.
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$existingRun = (Get-ItemProperty -Path $runKey -ErrorAction SilentlyContinue)."Docker Desktop"
if (-not $existingRun) {
    Write-Host "Configurando Docker Desktop para iniciar ao logar..."
    Set-ItemProperty -Path $runKey -Name "Docker Desktop" -Value "`"$dockerExe`""
} else {
    Write-Host "Docker Desktop ja esta configurado para iniciar ao logar."
}

# --- Login automatico do Windows (opcional) ----------------------------------
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host " ATENCAO: login automatico do Windows" -ForegroundColor Yellow
Write-Host " Docker Desktop so roda com uma sessao de usuario logada -- sem login" -ForegroundColor Yellow
Write-Host " automatico, a stack NAO sobe sozinha depois de um desligar/ligar real" -ForegroundColor Yellow
Write-Host " (so depois que alguem logar manualmente)." -ForegroundColor Yellow
Write-Host " Habilitar login automatico grava a senha da conta em texto plano no" -ForegroundColor Yellow
Write-Host " registro do Windows e permite que QUALQUER PESSOA com acesso fisico" -ForegroundColor Yellow
Write-Host " a esta maquina entre no Windows sem senha nenhuma." -ForegroundColor Yellow
Write-Host " So faca isso se esta maquina for dedicada a este agent, sem outro uso." -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Yellow
$autoLogonAnswer = Read-Host "Configurar login automatico agora? (s/N)"

if ($autoLogonAnswer -match '^[sS]') {
    $winlogonKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    $autoLogonUser = Read-Host "Nome de usuario Windows para login automatico (padrao: $env:USERNAME)"
    if (-not $autoLogonUser) { $autoLogonUser = $env:USERNAME }
    $autoLogonSecurePw = Read-Host "Senha da conta '$autoLogonUser'" -AsSecureString
    $autoLogonPw = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($autoLogonSecurePw)
    )

    Set-ItemProperty -Path $winlogonKey -Name "AutoAdminLogon" -Value "1"
    Set-ItemProperty -Path $winlogonKey -Name "DefaultUserName" -Value $autoLogonUser
    Set-ItemProperty -Path $winlogonKey -Name "DefaultDomainName" -Value $env:COMPUTERNAME
    Set-ItemProperty -Path $winlogonKey -Name "DefaultPassword" -Value $autoLogonPw

    Write-Host "Login automatico configurado para '$autoLogonUser'." -ForegroundColor Green
} else {
    Write-Host "Login automatico NAO configurado -- a stack so sobe sozinha depois que alguem logar manualmente nesta maquina."
}

# --- Script de auto-start (rodado pela Scheduled Task a cada logon) ---------
$autostartScript = @'
$ErrorActionPreference = "Continue"
$installDir = "$env:ProgramData\NextSecEdge"
$logFile = "$installDir\logs\autostart.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -Append -FilePath $logFile
}

Log "Aguardando o Docker Desktop subir..."
$deadline = (Get-Date).AddMinutes(5)
$dockerReady = $false
while ((Get-Date) -lt $deadline) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
    Start-Sleep -Seconds 5
}

if (-not $dockerReady) {
    Log "Docker nao respondeu apos 5 minutos -- desistindo desta tentativa."
    exit 1
}

Log "Docker pronto -- subindo a stack..."
Set-Location $installDir
docker compose -f docker-compose.edge.yml --env-file .env.edge up -d *>> $logFile
Log "Comando 'up -d' concluido (ver log acima para detalhes/erros)."
'@
Set-Content -Path "$installDir\autostart.ps1" -Value $autostartScript -Encoding UTF8

# --- Scheduled Task: roda o autostart a cada logon do usuario atual ---------
$taskName = "NextSecEdgeAutoStart"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$installDir\autostart.ps1`""
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null

Write-Host "Scheduled Task '$taskName' registrada (dispara a cada logon de '$env:USERNAME')."

# --- Sobe a stack agora, sem esperar o proximo boot -------------------------
Write-Host "Subindo a stack agora..."
Set-Location $installDir
docker compose -f docker-compose.edge.yml --env-file .env.edge up -d --build

Write-Host ""
Write-Host "Instalacao concluida." -ForegroundColor Green
Write-Host "  Tunel:           WireGuardTunnel`$$tunnelName"
Write-Host "  Scheduled Task:  $taskName"
Write-Host "  Stack:           docker compose -f `"$installDir\docker-compose.edge.yml`" ps"
Write-Host ""
Write-Host "Verifique com: docker compose -f `"$installDir\docker-compose.edge.yml`" ps"
Write-Host "Logs de auto-start em: $installDir\logs\autostart.log"
