param(
    [Parameter(Mandatory=$true)][string]$Settings,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
$settingsPath = [IO.Path]::GetFullPath($Settings)
$config = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$release = [IO.Path]::GetFullPath($config.release)
$python = [IO.Path]::GetFullPath($config.python)
$entry = Join-Path $release 'tools\cluster\serve_controller.py'
$port = [int]$config.port
if ($port -lt 1 -or $port -gt 65535) { throw 'Invalid controller port' }
$url = "http://127.0.0.1:$port/"
$listeners = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $ownerPid = $listeners[0].OwningProcess
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
    if (-not $owner -or $owner.CommandLine -notlike '*serve_controller.py*' -or
        $owner.CommandLine -notlike "*$settingsPath*") {
        throw "Port $port is owned by another process"
    }
} else {
    if (-not (Test-Path -LiteralPath $entry) -or -not (Test-Path -LiteralPath $python)) {
        throw 'Frozen controller files are missing'
    }
    & $python -X utf8 $entry --settings $settingsPath --check | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Frozen controller preflight failed' }
    $logDir = Join-Path ([IO.Path]::GetDirectoryName($settingsPath)) 'resident-monitor'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $arguments = @('-X', 'utf8', ('"' + $entry + '"'), '--settings', ('"' + $settingsPath + '"'))
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'controller.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'controller.stderr.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($process.HasExited) { throw "Controller exited with code $($process.ExitCode)" }
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Controller did not become ready in time' }
    @{ pid = $process.Id; settings = $settingsPath; url = $url; started_at = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir 'state.json') -Encoding UTF8
}
if ($OpenBrowser) { Start-Process ($url + '#cluster') }
Write-Output "MONITOR_READY $url"
