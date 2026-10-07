param([Parameter(Mandatory=$true)][string]$BuildRoot,[Parameter(Mandatory=$true)][string]$OutputRoot)
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
if((Test-Path -LiteralPath $BuildRoot) -or (Test-Path -LiteralPath $OutputRoot)){throw 'Use new build and output destinations'}
$runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies'
$node=Join-Path $runtime 'node/bin/node.exe';$python=Join-Path $runtime 'python/python.exe'
$src=Join-Path $PSScriptRoot 'reproduction'
& $python (Join-Path $src 'prepare_weather.py') $BuildRoot $OutputRoot
if($LASTEXITCODE -ne 0){throw 'Frozen weather verification failed'}
& $node (Join-Path $src 'build_appendix.mjs') $BuildRoot
if($LASTEXITCODE -ne 0){throw 'Native table export failed'}
& (Join-Path $src 'append_native.ps1') -BuildRoot $BuildRoot
if(-not $?){throw 'Native append failed'}
& $python (Join-Path $src 'sync_chart_caches.py') $BuildRoot
if($LASTEXITCODE -ne 0){throw 'Chart cache reconciliation failed'}
& $node (Join-Path $src 'finalize.mjs') $BuildRoot $OutputRoot
if($LASTEXITCODE -ne 0){throw 'Presentation finalization failed'}
& (Join-Path $src 'render.ps1') -Pptx (Join-Path $src 'source_base.pptx') -RenderDir (Join-Path $BuildRoot 'render_source') -ExpectedSlides 44
& (Join-Path $src 'render.ps1') -Pptx (Join-Path $OutputRoot 'research_progress_20261006_daily_weather.pptx') -RenderDir (Join-Path $BuildRoot 'render') -Pdf (Join-Path $OutputRoot 'research_progress_20261006_daily_weather.pdf')
& $python (Join-Path $src 'verify_delivery.py') $BuildRoot $OutputRoot
if($LASTEXITCODE -ne 0){throw 'Coverage, evidence retention, or native display verification failed'}
Write-Output '84 daily records, 12 editable tables, PPTX and PDF rebuilt without AI or a new optimization run.'
