#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Remove o Next Sec Edge (Nivel 1 - Docker dedicado): stack, Scheduled Task,
    tunel WireGuard e (se configurado) login automatico do Windows.
#>

$ErrorActionPreference = "Continue"  # segue removendo o que der, mesmo se uma etapa falhar

$installDir = "$env:ProgramData\NextSecEdge"
$wgExe      = "C:\Program Files\WireGuard\wireguard.exe"
$tunnelName = "nextsec-edge"
$taskName   = "NextSecEdgeAutoStart"

Write-Host "Removendo Next Sec Edge (Nivel 1)..."

if (Test-Path "$installDir\docker-compose.edge.yml") {
    Write-Host "Derrubando a stack..."
    Push-Location $installDir
    docker compose -f docker-compose.edge.yml --env-file .env.edge down
    Pop-Location
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "Removendo Scheduled Task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ((Test-Path $wgExe) -and (Get-Service "WireGuardTunnel`$$tunnelName" -ErrorAction SilentlyContinue)) {
    Write-Host "Removendo tunel WireGuard..."
    & $wgExe /uninstalltunnelservice $tunnelName
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if ((Get-ItemProperty -Path $runKey -ErrorAction SilentlyContinue)."Docker Desktop") {
    Write-Host "Removendo entrada de auto-start do Docker Desktop..."
    Remove-ItemProperty -Path $runKey -Name "Docker Desktop" -ErrorAction SilentlyContinue
}

$winlogonKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
if ((Get-ItemProperty -Path $winlogonKey -ErrorAction SilentlyContinue).AutoAdminLogon -eq "1") {
    $revertAnswer = Read-Host "Login automatico do Windows foi configurado por este instalador. Reverter agora? (s/N)"
    if ($revertAnswer -match '^[sS]') {
        Set-ItemProperty -Path $winlogonKey -Name "AutoAdminLogon" -Value "0"
        Remove-ItemProperty -Path $winlogonKey -Name "DefaultPassword" -ErrorAction SilentlyContinue
        Write-Host "Login automatico revertido."
    }
}

if (Test-Path $installDir) {
    Write-Host "Removendo arquivos em $installDir..."
    Remove-Item -Recurse -Force $installDir -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Desinstalacao concluida." -ForegroundColor Green
