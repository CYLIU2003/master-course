param(
    [Parameter(Mandatory = $true)][string]$Campaign,
    [Parameter(Mandatory = $true)][string]$ControllerSettings,
    [string]$Python = 'C:\master-course\.venv\Scripts\python.exe',
    [string]$TaskName = 'MasterCourseCampaignProgress',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$campaignPath = (Get-Item -LiteralPath $Campaign -ErrorAction Stop).FullName
$settingsPath = (Get-Item -LiteralPath $ControllerSettings -ErrorAction Stop).FullName
$pythonPath = (Get-Item -LiteralPath $Python -ErrorAction Stop).FullName
$source = Join-Path $PSScriptRoot 'publish_campaign_progress.py'
if (-not (Test-Path -LiteralPath $source)) { throw 'Publisher source is missing' }
if (-not (Test-Path -LiteralPath (Join-Path $campaignPath 'binding.json'))) {
    throw 'Campaign binding is missing'
}
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$frontend = (Get-Item -LiteralPath $settings.frontend -ErrorAction Stop).FullName
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'index.html'))) {
    throw 'Controller frontend is missing'
}
$output = Join-Path $frontend 'campaign-progress.json'
$installDirectory = 'C:\master-course\output\cluster-deployment\progress-ui'
$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
$installed = Join-Path $installDirectory ('publisher-' + $sourceHash.Substring(0, 12) + '.py')
$eventLog = Join-Path $installDirectory 'publisher-events.log'
$arguments = ('"' + $installed + '" --campaign "' + $campaignPath + '" --output "' +
    $output + '" --watch --event-log "' + $eventLog + '"')

if ($CheckOnly) {
    [pscustomobject]@{
        check = 'VALID'; task = $TaskName; campaign = $campaignPath
        frontend = $frontend; source_sha256 = $sourceHash
    } | ConvertTo-Json
    return
}

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $installed)) {
    Copy-Item -LiteralPath $source -Destination $installed
}
if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
    throw 'Installed publisher hash differs from source'
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running' -and
    ($existing.Actions.Execute -ne $pythonPath -or $existing.Actions.Arguments -ne $arguments)) {
    throw 'The existing progress task is running with different inputs; stop it explicitly before rebinding'
}
if (-not $existing -or $existing.Actions.Execute -ne $pythonPath -or
    $existing.Actions.Arguments -ne $arguments) {
    $account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $installDirectory
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $taskSettings `
        -Description 'Read-only monthly campaign progress for the local research dashboard' `
        -Force | Out-Null
}
if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') {
    Start-ScheduledTask -TaskName $TaskName
}
Start-Sleep -Seconds 2
$state = (Get-ScheduledTask -TaskName $TaskName).State
if ($state -ne 'Running') { throw "Progress task did not remain running: $state" }
[pscustomobject]@{
    status = 'RUNNING'; task = $TaskName; campaign = $campaignPath
    frontend = $frontend; source_sha256 = $sourceHash; event_log = $eventLog
} | ConvertTo-Json
