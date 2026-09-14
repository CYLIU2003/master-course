$ErrorActionPreference = 'Stop'
$researchRoot = 'C:/master-course-worktrees/shibu21-23-monthly-search-20260915'
$controlRoot = 'C:/master-course'
$runtimeRoot = Join-Path $controlRoot 'output/monthly_search_20260915'
$pythonPath = Join-Path $controlRoot '.venv/Scripts/python.exe'
$expectedSha = '10a40c9faa00d0a4725ae0062d6dbaa223f82bfd'
if ((git -C $researchRoot rev-parse HEAD) -ne $expectedSha) { throw 'Wrong frozen SHA' }
if (git -C $researchRoot status --porcelain) { throw 'Frozen source is dirty' }
$campaignPath = Join-Path $researchRoot 'output/monthly_search_campaign_20260915'
if (Test-Path -LiteralPath $campaignPath) { throw 'Campaign exists; refusing restart/overwrite' }
if (Test-Path -LiteralPath (Join-Path $runtimeRoot 'budget_rerun_launch.json')) { throw 'Launch already recorded' }
$arguments = @('-X', 'utf8', '-u', 'scripts/benchmarks/run_exact_seasonal_campaign.py',
    '--config', 'config/shibu21_23_monthly_search_20260915.json',
    '--output', 'output/monthly_search_campaign_20260915')
$launcher = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $researchRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'campaign.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'campaign.stderr.log')
$solverProcess = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($launcher.Id)" | Where-Object { $_.Name -match '^python' -and $_.CommandLine -like '*run_exact_seasonal_campaign.py*' })
    if ($children.Count -eq 1) { $solverProcess = $children[0]; break }
    Start-Sleep -Milliseconds 500
}
if (-not $solverProcess) { throw "Cannot bind actual solver PID; inspect launcher $($launcher.Id) and logs" }
$started = $solverProcess.CreationDate.ToUniversalTime().ToString('o')
& $pythonPath -X utf8 (Join-Path $runtimeRoot 'configure_observer.py') --pid $solverProcess.ProcessId --started $started
if ($LASTEXITCODE -ne 0) { throw 'Observer configuration failed; solver may still be running, do not restart' }
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Test-Path -LiteralPath (Join-Path $campaignPath 'progress.json')) { break }
    Start-Sleep -Milliseconds 500
}
& (Join-Path $controlRoot 'scripts/start_monthly_campaign_observer.ps1') -ConfigPath (Join-Path $runtimeRoot 'script_observer/config.json')
Write-Output "Frozen campaign PID $($solverProcess.ProcessId); launcher PID $($launcher.Id); source $expectedSha"
