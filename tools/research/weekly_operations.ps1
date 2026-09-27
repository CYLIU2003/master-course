param(
    [Parameter(Mandatory=$true)][string]$Operation,
    [ValidateSet('check','controller','status','run','collect','watch')][string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
try {
    $operationPath = (Resolve-Path -LiteralPath $Operation).Path
    $definition = Get-Content -LiteralPath $operationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $settingsPath = [string]$definition.settings
    if (-not [System.IO.Path]::IsPathRooted($settingsPath)) {
        $settingsPath = Join-Path (Split-Path -Parent $operationPath) $settingsPath
    }
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [System.IO.Path]::IsPathRooted([string]$settings.python)) {
        throw 'Controller setting python must be an absolute path.'
    }
    if (-not (Test-Path -LiteralPath $settings.python -PathType Leaf)) {
        throw "Configured Python is missing: $($settings.python). Restore the declared environment; do not choose a different solver runtime."
    }
    $entry = Join-Path $PSScriptRoot 'weekly_operator.py'
    & $settings.python -X utf8 $entry $Action --operation $operationPath
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("OPERATOR_ERROR: " + $_.Exception.Message)
    exit 2
}
