#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Remove o Next Sec Edge Agent + tunel WireGuard (servicos e arquivos).
#>

$ErrorActionPreference = "Continue"  # segue removendo o que der, mesmo se uma etapa falhar

$installDir = "$env:ProgramData\NextSecAgent"
$wgExe = "C:\Program Files\WireGuard\wireguard.exe"
$nssm = "$installDir\nssm.exe"

Write-Host "Removendo Next Sec Edge Agent..."

if ((Test-Path $nssm) -and (Get-Service "NextSecAgent" -ErrorAction SilentlyContinue)) {
    Write-Host "Parando e removendo servico do agent..."
    # Sem redirecionar stderr -- nssm escreve avisos inofensivos la (ex:
    # servico ja parado) que o PowerShell mostraria em vermelho se
    # redirecionados, mesmo sem serem erros de verdade.
    & $nssm stop NextSecAgent
    Start-Sleep -Seconds 2
    & $nssm remove NextSecAgent confirm
}

if ((Test-Path $wgExe) -and (Get-Service "WireGuardTunnel`$nextsec" -ErrorAction SilentlyContinue)) {
    Write-Host "Removendo tunel WireGuard..."
    & $wgExe /uninstalltunnelservice nextsec
}

if (Test-Path $installDir) {
    Write-Host "Removendo arquivos em $installDir..."
    Remove-Item -Recurse -Force $installDir -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Desinstalacao concluida." -ForegroundColor Green
