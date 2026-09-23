param([Parameter(Mandatory=$true)][string]$Settings)
$ErrorActionPreference = 'Stop'
$settingsPath = [IO.Path]::GetFullPath($Settings)
$scriptPath = Join-Path $PSScriptRoot 'start_resident_monitor.ps1'
if (-not (Test-Path -LiteralPath $settingsPath)) { throw 'Controller settings are missing' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" -Settings `"$settingsPath`" -OpenBrowser"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'MasterCourseClusterMonitor' -Action $action -Trigger $trigger `
    -Principal $principal -Description 'Loopback cluster monitor from a frozen release; no AI calls' -Force | Out-Null
& $scriptPath -Settings $settingsPath -OpenBrowser
