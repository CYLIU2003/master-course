param(
    [ValidateSet('menu','check','controller','status','run','collect','watch')]
    [string]$Action = 'menu',
    [int]$OperationIndex = 0
)
$ErrorActionPreference = 'Stop'
try {
    $registry = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'registry.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($registry.schema_version -ne 1) { throw 'Unsupported operator registry version.' }
    $entries = @($registry.operations)
    if ($entries.Count -eq 0) { throw 'No operations registered.' }
    for ($index = 0; $index -lt $entries.Count; $index++) {
        $entry = $entries[$index]
        Write-Host ("{0}: {1} / {2} weeks / SHA {3}" -f ($index + 1), $entry.campaign, @($entry.weeks).Count, $entry.git_sha)
    }
    if ($OperationIndex -eq 0) {
        $selection = Read-Host 'Operation number (Q to exit)'
        if ($selection -eq 'Q') { exit 0 }
        if (-not [int]::TryParse($selection, [ref]$OperationIndex)) { throw 'Enter an operation number.' }
    }
    if ($OperationIndex -lt 1 -or $OperationIndex -gt $entries.Count) { throw 'Operation number is out of range.' }
    $selected = $entries[$OperationIndex - 1]
    if ($Action -ne 'menu') {
        & $registry.wrapper -Operation $selected.path -Action $Action
        exit $LASTEXITCODE
    }
    while ($true) {
        Write-Host ''
        Write-Host '1 status  2 check  3 controller  4 run/resume  5 collect  6 watch'
        Write-Host '7 browser  8 guide  9 results folder  Q exit'
        Write-Host 'Ctrl+C stops this operator, not remote workers. Closing the controller stops new scheduling.'
        $choice = Read-Host 'Action'
        if ($choice -eq 'Q') { exit 0 }
        if ($choice -eq '7') { Start-Process $selected.url; continue }
        if ($choice -eq '8') { Invoke-Item -LiteralPath $registry.guide; continue }
        if ($choice -eq '9') { Invoke-Item -LiteralPath $selected.campaign; continue }
        $actions = @{ '1'='status'; '2'='check'; '3'='controller'; '4'='run'; '5'='collect'; '6'='watch' }
        if (-not $actions.ContainsKey($choice)) { Write-Host 'Choose 1-9 or Q.'; continue }
        & $registry.wrapper -Operation $selected.path -Action $actions[$choice]
        Write-Host "Operator exit code: $LASTEXITCODE (0=operation succeeded, 3=incomplete, 2=error)"
    }
} catch {
    [Console]::Error.WriteLine('OPERATOR_ERROR: ' + $_.Exception.Message)
    exit 2
}
