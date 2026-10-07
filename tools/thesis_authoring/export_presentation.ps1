param(
    [Parameter(Mandatory=$true)][string]$Pptx,
    [Parameter(Mandatory=$true)][string]$Pdf,
    [Parameter(Mandatory=$true)][string]$Images
)
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $Pptx).Path
$pdfPath = [IO.Path]::GetFullPath($Pdf)
$imagePath = [IO.Path]::GetFullPath($Images)
if ((Test-Path -LiteralPath $pdfPath) -or (Test-Path -LiteralPath $imagePath)) {
    throw 'Use new PDF and image destinations; existing user files are never overwritten.'
}
$before = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
$presentation = $null
$powerPoint = New-Object -ComObject PowerPoint.Application
try {
    $presentation = $powerPoint.Presentations.Open($sourcePath, -1, 0, 0)
    New-Item -ItemType Directory -Path $imagePath | Out-Null
    # 32 = PDF. The source is read-only and only this presentation is closed.
    $presentation.SaveAs($pdfPath, 32)
    for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
        $presentation.Slides.Item($i).Export((Join-Path $imagePath "slide-$i.png"), 'PNG', 1280, 720)
    }
    @{ slides = $presentation.Slides.Count; pdf = $pdfPath; images = $imagePath } | ConvertTo-Json
} finally {
    if ($null -ne $presentation) { $presentation.Close() }
    # Do not Quit: a researcher may already have PowerPoint documents open.
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint)
}
if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne $before) {
    throw 'Source PPTX changed during read-only export.'
}
