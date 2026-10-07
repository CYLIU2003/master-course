param(
    [string]$OutputDirectory,
    [string]$BuildDirectory
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root "output/presentation_rebuild_$stamp/product" }
if (-not $BuildDirectory) { $BuildDirectory = Join-Path $root "output/presentation_rebuild_$stamp/work" }
$output = [IO.Path]::GetFullPath($OutputDirectory)
$build = [IO.Path]::GetFullPath($BuildDirectory)
$runtime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
$python = [IO.Path]::GetFullPath((Join-Path $runtime 'python/python.exe'))
$node = [IO.Path]::GetFullPath((Join-Path $runtime 'node/bin/node.exe'))
$pptx = Join-Path $output 'research_progress_20261005_teacher_ready.pptx'
$pdf = Join-Path $output 'research_progress_20261005_teacher_ready.pdf'
$images = Join-Path $build 'render'
if ((Test-Path -LiteralPath $build) -or (Test-Path -LiteralPath $pptx) -or (Test-Path -LiteralPath $pdf)) {
    throw 'Choose new build and product paths. Existing presentations are never overwritten.'
}
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $node)) {
    throw 'The bundled Python/Node runtime is missing; see README.md prerequisites.'
}
$runtime = Split-Path (Split-Path $python -Parent) -Parent
$env:RUNTIME_NODE_MODULES = Join-Path $runtime 'node/node_modules'
$scripts = Join-Path $PSScriptRoot 'reproduction'
New-Item -ItemType Directory -Path $output -Force | Out-Null
function Check-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed with exit code $LASTEXITCODE. Keep the build directory for diagnosis." }
}
Write-Output '1/7 Verify the frozen evidence and preserve the source deck'
& $python (Join-Path $scripts 'prepare_revision.py') $build
Check-Exit 'Evidence preparation'
Write-Output '2/7 Build five editable native slides'
& $node (Join-Path $scripts 'build_slides.mjs') $build
Check-Exit 'Native slide construction'
Write-Output '3/7 Merge, order and add date axes with PowerPoint'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts 'merge_render.ps1') -Build $build
Check-Exit 'PowerPoint merge'
Write-Output '4/7 Reconcile chart caches with the preserved workbooks'
& $python (Join-Path $scripts 'align_chart_cache.py') $build
Check-Exit 'Chart cache reconciliation'
Write-Output '5/7 Check native objects, notes and teacher comments'
& $python (Join-Path $scripts 'inspect_revision.py') $build
Check-Exit 'Presentation inspection'
Write-Output '6/7 Validate and finalize the new PPTX'
& $node (Join-Path $scripts 'finalize.mjs') $build $pptx
Check-Exit 'Presentation finalization'
Write-Output '7/7 Export the PDF and all native slide images'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools/thesis_authoring/export_presentation.ps1') -Pptx $pptx -Pdf $pdf -Images $images
Check-Exit 'Native export'
& $python (Join-Path $scripts 'inspect_revision.py') $build $pptx
Check-Exit 'Final presentation inspection'
Write-Output "PPTX: $pptx"
Write-Output "PDF: $pdf"
Write-Output "Verification and images: $build"
