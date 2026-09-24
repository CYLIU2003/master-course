param(
    [Parameter(Mandatory = $true)][string]$Output,
    [ValidateRange(1, 8)][int]$Workers = 2,
    [ValidateRange(250, 60000)][int]$IntervalMs = 1000,
    [string]$Python,
    [switch]$PromptSecondaryKey
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$pythonExe = $Python
if (-not $pythonExe) {
    $pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = (Get-Command python -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python interpreter not found: $pythonExe"
}

& (Join-Path $PSScriptRoot 'run_tokyu_company_capture.ps1') -Output $Output -Workers $Workers -IntervalMs $IntervalMs -PromptSecondaryKey:$PromptSecondaryKey
Push-Location -LiteralPath $repoRoot
try {
    & $pythonExe -m scripts.catalog.manual_tokyu_company_snapshot verify --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'Frozen ODPT source verification failed; database was not built.' }
    & $pythonExe -m scripts.catalog.manual_tokyu_company_snapshot build --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'Offline Tokyu catalog build failed; no formal scenario was changed.' }
} finally {
    Pop-Location
}
