param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference='Stop'
$repoPath='C:/master-course'
$runtimePath='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies'
$pythonPath=Join-Path $runtimePath 'python/python.exe'
$nodePath=Join-Path $runtimePath 'node/bin/node.exe'
$destinationPath=[IO.Path]::GetFullPath($Destination)
if(Test-Path -LiteralPath $destinationPath){throw 'Use a new destination; existing results are preserved.'}
$rebuildStamp=(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[guid]::NewGuid().ToString('N').Substring(0,8)
$buildPath=Join-Path $repoPath ('output/teacher_revision_rebuild_'+$rebuildStamp)
New-Item -ItemType Directory -Path $buildPath | Out-Null
New-Item -ItemType Directory -Path $destinationPath | Out-Null

# LiteralPath does not expand wildcards. Enumerate only this packaged directory.
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'reproduction') -File | Copy-Item -Destination $buildPath
$previousOutput=$env:TEACHER_REVISION_OUTPUT
$env:TEACHER_REVISION_OUTPUT=$destinationPath
$app=$null; $deck=$null
try {
    & $pythonPath -X utf8 (Join-Path $buildPath 'analyze_comments.py')
    if($LASTEXITCODE -ne 0){throw 'Evidence analysis failed'}
    & $pythonPath -X utf8 (Join-Path $buildPath 'patch_and_merge.py')
    if($LASTEXITCODE -ne 0){throw 'Source-preserving text revision failed'}
    & $nodePath (Join-Path $buildPath 'build_supplement.mjs') $buildPath
    if($LASTEXITCODE -ne 0){throw 'Native evidence slide generation failed'}
    $app=New-Object -ComObject PowerPoint.Application
    $deck=$app.Presentations.Open((Join-Path $buildPath 'patched_only.pptx'),-1,0,0)
    $inserted=$deck.Slides.InsertFromFile((Join-Path $buildPath 'supplement_final/supplement_v2.pptx'),36)
    if($inserted -ne 3 -or $deck.Slides.Count -ne 39){throw 'Unexpected slide count'}
    $deck.SaveAs((Join-Path $buildPath 'native_merge_candidate_v2.pptx'),24)
    $deck.Close();$deck=$null
    & $pythonPath -X utf8 (Join-Path $buildPath 'align_chart_cache.py')
    if($LASTEXITCODE -ne 0){throw 'Chart/workbook alignment failed'}
    $pptxPath=Join-Path $destinationPath 'september_progress_20261002_v5_teacher_revised.pptx'
    & $nodePath (Join-Path $buildPath 'finalize.mjs') $buildPath $pptxPath
    if($LASTEXITCODE -ne 0){throw 'Final presentation validation failed'}
    & powershell -NoProfile -File (Join-Path $repoPath 'tools/thesis_authoring/export_presentation.ps1') -Pptx $pptxPath -Pdf (Join-Path $destinationPath 'september_progress_20261002_v5_teacher_revised.pdf') -Images (Join-Path $buildPath 'render')
    if($LASTEXITCODE -ne 0){throw 'Native PowerPoint render failed'}
    Write-Output ('Rebuilt without AI, solver, or data acquisition: '+$destinationPath)
    Write-Output ('Private build and checks: '+$buildPath)
} finally {
    $env:TEACHER_REVISION_OUTPUT=$previousOutput
    if($null -ne $deck){$deck.Close()}
    if($null -ne $app){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}

