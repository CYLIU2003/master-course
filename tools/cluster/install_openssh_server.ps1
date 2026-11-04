# Run ON the new worker in an elevated (administrator) PowerShell.
# Installs/starts OpenSSH Server only. It does not add keys, edit sshd_config,
# change firewall rules beyond the default OpenSSH rule, or touch Windows Update.
# Usage: powershell -ExecutionPolicy Bypass -File install_openssh_server.ps1
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an elevated PowerShell (Run as administrator).'
}
if (-not (Get-CimInstance Win32_Service -Filter "Name='sshd'")) {
    $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
    if (-not $cap) { throw 'OpenSSH.Server capability not found on this Windows build.' }
    Write-Host "Installing $($cap.Name) (needs internet / Windows Update) ..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd }
Start-Sleep -Seconds 2

$svc = Get-CimInstance Win32_Service -Filter "Name='sshd'"
$listen = @(Get-NetTCPConnection -State Listen -LocalPort 22 -ErrorAction SilentlyContinue).Count -gt 0
$fw = @(Get-NetFirewallRule -DisplayName '*OpenSSH*' -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }).Count
Write-Host ("sshd state={0} start={1} listen22={2} enabled_inbound_openssh_fw_rules={3}" -f $svc.State, $svc.StartMode, $listen, $fw)
if ($svc.State -ne 'Running' -or $svc.StartMode -ne 'Auto' -or -not $listen) { throw 'OpenSSH Server is not in the expected state.' }
Write-Host 'OK: OpenSSH Server is running. Keys have NOT been added yet.'
