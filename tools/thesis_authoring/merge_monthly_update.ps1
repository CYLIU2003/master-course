param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Update,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$PreviewDirectory
)
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$updatePath = (Resolve-Path -LiteralPath $Update).Path
$outputPath = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) { throw 'Use a new output file; never overwrite a user deck.' }
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($outputPath)) -Force | Out-Null
New-Item -ItemType Directory -Path $PreviewDirectory -Force | Out-Null
$previewPath = (Resolve-Path -LiteralPath $PreviewDirectory).Path
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
try {
    $deck = $app.Presentations.Open($sourcePath, -1, 0, 0)
    $oldCount = $deck.Slides.Count
    # Keep user-authored historical slides, but never present old numbers as current.
    for ($i=1; $i -le $oldCount; $i++) { $deck.Slides.Item($i).SlideShowTransition.Hidden = -1 }
    $inserted = $deck.Slides.InsertFromFile($updatePath, 0)
    if ($inserted -ne 6 -or $deck.Slides.Count -ne ($oldCount+6)) { throw 'Unexpected slide count' }
    $deck.SaveAs($outputPath, 24)
    for ($i=1; $i -le $inserted; $i++) {
        $deck.Slides.Item($i).Export((Join-Path $previewPath "slide-$i.png"), 'PNG', 1280, 720)
    }
    # PDF exports visible current pages only; retained historical pages stay in PPTX.
    $deck.SaveAs([IO.Path]::ChangeExtension($outputPath, '.pdf'), 32)
} finally {
    if ($null -ne $deck) { $deck.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck) }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $sourceHash) { throw 'Original presentation changed' }
@{source=$sourcePath;source_sha256=$sourceHash;output=$outputPath;updated_slides=6;historical_slides_hidden=$oldCount;solver_started=$false} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $previewPath 'merge-receipt.json') -Encoding utf8
Write-Output $outputPath
