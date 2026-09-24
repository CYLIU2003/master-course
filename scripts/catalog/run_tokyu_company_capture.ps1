param(
    [Parameter(Mandatory = $true)][string]$Output,
    [ValidateRange(1, 8)][int]$Workers = 4,
    [ValidateRange(250, 60000)][int]$IntervalMs = 1000,
    [switch]$ProbePagination,
    [switch]$PromptSecondaryKey
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$goCommand = Get-Command go -ErrorAction SilentlyContinue
if ($goCommand) {
    $goExe = $goCommand.Source
} else {
    $goExe = Join-Path $env:USERPROFILE '.codex\toolchains\go1.26.8\go\bin\go.exe'
}
if (-not (Test-Path -LiteralPath $goExe)) {
    throw 'Go is required. Install a verified Go toolchain before manually refreshing ODPT.'
}

$priorKey = [Environment]::GetEnvironmentVariable('ODPT_CONSUMER_KEY', 'Process')
$priorSecondaryKey = [Environment]::GetEnvironmentVariable('ODPT_CONSUMER_KEY_SECONDARY', 'Process')
$secureKey = Read-Host -AsSecureString 'ODPT consumer key'
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$secureSecondaryKey = $null
$secondaryBstr = [IntPtr]::Zero
try {
    $env:ODPT_CONSUMER_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    Remove-Item Env:ODPT_CONSUMER_KEY_SECONDARY -ErrorAction SilentlyContinue
    if ($PromptSecondaryKey) {
        $secureSecondaryKey = Read-Host -AsSecureString 'Second ODPT consumer key'
        $secondaryBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecondaryKey)
        $env:ODPT_CONSUMER_KEY_SECONDARY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secondaryBstr)
    }
    Push-Location -LiteralPath $repoRoot
    try {
        $goArgs = @('run', 'scripts/catalog/capture_tokyu_company.go', '--output', $Output, '--workers', [string]$Workers, '--interval-ms', [string]$IntervalMs)
        if ($ProbePagination) { $goArgs += '--probe-pagination' }
        & $goExe @goArgs
        if ($LASTEXITCODE -ne 0) {
            throw "ODPT capture failed with exit code $LASTEXITCODE; the capture manifest was not frozen."
        }
    } finally {
        Pop-Location
    }
} finally {
    if ($null -eq $priorKey) {
        Remove-Item Env:ODPT_CONSUMER_KEY -ErrorAction SilentlyContinue
    } else {
        $env:ODPT_CONSUMER_KEY = $priorKey
    }
    if ($null -eq $priorSecondaryKey) {
        Remove-Item Env:ODPT_CONSUMER_KEY_SECONDARY -ErrorAction SilentlyContinue
    } else {
        $env:ODPT_CONSUMER_KEY_SECONDARY = $priorSecondaryKey
    }
    if ($secondaryBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secondaryBstr)
    }
    if ($null -ne $secureSecondaryKey) { $secureSecondaryKey.Dispose() }
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secureKey.Dispose()
}
