param([Parameter(Mandatory=$true)][string]$BuildRoot,[Parameter(Mandatory=$true)][string]$OutputRoot)
$ErrorActionPreference='Stop'
if((Test-Path -LiteralPath $BuildRoot) -or (Test-Path -LiteralPath $OutputRoot)){throw 'Use new build and output destinations'}
$runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies'
$node=Join-Path $runtime 'node/bin/node.exe';$python=Join-Path $runtime 'python/python.exe'
$src=Join-Path $PSScriptRoot 'reproduction'
New-Item -ItemType Directory -Path $BuildRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $src 'edits.json') -Destination (Join-Path $BuildRoot 'edits.json')
& $node (Join-Path $src 'build_edits.mjs') $BuildRoot
if($LASTEXITCODE -ne 0){throw 'Native element export failed'}
& $python (Join-Path $src 'merge_edits.py') $BuildRoot
if($LASTEXITCODE -ne 0){throw 'Source-preserving merge failed'}
& $node (Join-Path $src 'finalize.mjs') $BuildRoot $OutputRoot 'research_progress_20261006_explained_v2.pptx'
if($LASTEXITCODE -ne 0){throw 'Finalization failed'}
& (Join-Path $src 'render.ps1') -Pptx (Join-Path $OutputRoot 'research_progress_20261006_explained_v2.pptx') -RenderDir (Join-Path $BuildRoot 'render') -Pdf (Join-Path $OutputRoot 'research_progress_20261006_explained_v2.pdf')
