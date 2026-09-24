param(
    [Parameter(Mandatory=$true)][string]$Operation,
    [ValidateSet('check','controller','status','run','collect','watch')][string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
try {
    $operationPath = (Resolve-Path -LiteralPath $Operation).Path
    $definition = Get-Content -LiteralPath $operationPath -Raw | ConvertFrom-Json
    $settings = Get-Content -LiteralPath $definition.settings -Raw | ConvertFrom-Json
    $entry = Join-Path $PSScriptRoot 'weekly_operator.py'
    & $settings.python -X utf8 $entry $Action --operation $operationPath
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}
