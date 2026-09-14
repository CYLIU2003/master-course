param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\output\monthly_fair_weeks_20260914\script_observer\config.json')
)
$ErrorActionPreference = 'Stop'
$resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$settings = Get-Content -LiteralPath $resolvedConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$observerScript = Join-Path $settings.root 'scripts\watch_monthly_campaign.py'
$statePath = Join-Path $settings.output 'state.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $active = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.observer_pid)" -ErrorAction SilentlyContinue
    if ($active -and $active.CommandLine -like '*watch_monthly_campaign.py*') {
        Write-Output "Observer already running: PID $($active.ProcessId)"
        return
    }
}
& $settings.python -X utf8 $observerScript --config $resolvedConfig --check
if ($LASTEXITCODE -ne 0) { throw 'Observer deployment check failed; nothing started.' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$stdout = Join-Path $settings.output "observer_${stamp}.stdout.log"
$stderr = Join-Path $settings.output "observer_${stamp}.stderr.log"
$arguments = @('-X', 'utf8', ('"' + $observerScript + '"'), '--config', ('"' + $resolvedConfig + '"'))
$process = Start-Process -FilePath $settings.python -ArgumentList $arguments -WorkingDirectory $settings.root -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
[ordered]@{
    launcher_pid = $process.Id
    started_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    config = $resolvedConfig
    stdout = $stdout
    stderr = $stderr
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $settings.output 'launch.json') -Encoding UTF8
Write-Output "Observer started: launcher PID $($process.Id). See state.json for the actual Python PID."
