param(
    [Parameter(Mandatory=$true)][string]$Operation,
    [string]$TaskName = 'MasterCourseControllerSupervisor',
    [switch]$CheckOnly,
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
$operationPath = (Resolve-Path -LiteralPath $Operation).Path
$definition = Get-Content -LiteralPath $operationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$settingsPath = [string]$definition.settings
if (-not [IO.Path]::IsPathRooted($settingsPath)) {
    $settingsPath = Join-Path (Split-Path -Parent $operationPath) $settingsPath
}
$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$python = (Get-Item -LiteralPath $settings.python).FullName
$source = Join-Path $PSScriptRoot 'controller_supervisor.py'
if (-not (Test-Path -LiteralPath (Join-Path $settings.queue 'cluster.sqlite3') -PathType Leaf)) {
    throw 'Existing queue is required. This installer does not create jobs or a queue.'
}
& $python -X utf8 $source status --operation $operationPath
if ($LASTEXITCODE -ne 0) { throw 'Supervisor settings validation failed.' }
$uiSource = Join-Path $PSScriptRoot 'supervisor_ui.py'
$arguments = '-X utf8 "' + $uiSource + '" --operation "' + $operationPath + '"'
$legacyArguments = '-X utf8 "' + $source + '" watch --operation "' + $operationPath + '"'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$upgrade = $existing -and $existing.Actions.Execute -eq $python -and $existing.Actions.Arguments -eq $legacyArguments
if ($upgrade -and $existing.State -eq 'Running') {
    throw 'Disable the legacy supervisor and wait for its task to exit before upgrading. Do not stop the running controller.'
}
if ($existing -and -not $upgrade -and ($existing.Actions.Execute -ne $python -or $existing.Actions.Arguments -ne $arguments)) {
    throw 'Task name is already bound to different settings. Choose another name; do not overwrite it.'
}
if ($CheckOnly) {
    [pscustomobject]@{status='VALID'; task=$TaskName; operation=$operationPath; start_requested=[bool]$Start} | ConvertTo-Json
    return
}
if (-not $existing -or $upgrade) {
    $account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory (Split-Path -Parent $source)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $taskSettings -Description 'Browser controls and bounded recovery for the same frozen controller.' -Force | Out-Null
}
if ($Start) {
    & $python -X utf8 $source enable --operation $operationPath
    if ($LASTEXITCODE -ne 0) { throw 'Supervisor is blocked; inspect its state before restarting.' }
    Start-ScheduledTask -TaskName $TaskName
}
[pscustomobject]@{status='REGISTERED'; task=$TaskName; state=(Get-ScheduledTask -TaskName $TaskName).State;
    operation=$operationPath; auto_start_before_logon=$false} | ConvertTo-Json
