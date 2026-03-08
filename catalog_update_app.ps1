$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "catalog_update_app.py"

if (Test-Path $venvPython) {
  & $venvPython $scriptPath @args
  exit $LASTEXITCODE
}

& python $scriptPath @args
exit $LASTEXITCODE
