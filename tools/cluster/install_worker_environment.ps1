param(
    [Parameter(Mandatory=$true)][string]$ExpectedComputer,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ArchiveSha256
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:COMPUTERNAME -ne $ExpectedComputer) { throw 'Worker identity mismatch' }
$root = 'C:\mc-worker'
$archive = Join-Path $root 'bootstrap.zip'
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $ArchiveSha256) { throw 'Bootstrap SHA256 mismatch' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (-not (Test-Path -LiteralPath "$root\bootstrap\uv.exe")) {
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, "$root\bootstrap")
}
$env:UV_PYTHON_INSTALL_DIR = "$root\python"
$env:UV_CACHE_DIR = "$root\uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "$root\venv"
$env:UV_NO_PROGRESS = '1'
$env:UV_NO_MODIFY_PATH = '1'
& "$root\bootstrap\uv.exe" sync --project "$root\bootstrap\environment" --locked --managed-python
if ($LASTEXITCODE -ne 0) { throw "uv sync failed: $LASTEXITCODE" }
# Keep private Git discovery within this venv. No machine/user PATH is modified.
$startup = "import os`nfrom pathlib import Path`n_root=Path(__file__).resolve().parents[3]`nos.environ['PATH']=str(_root/'bootstrap/git/bin')+os.pathsep+os.environ.get('PATH','')`nos.environ.setdefault('OMP_NUM_THREADS','1')`nos.environ.setdefault('OPENBLAS_NUM_THREADS','1')`n"
[IO.File]::WriteAllText("$root\venv\Lib\site-packages\sitecustomize.py", $startup, [Text.UTF8Encoding]::new($false))
& "$root\venv\Scripts\python.exe" -c "import json,platform,subprocess; from importlib.metadata import version; print(json.dumps({'python':platform.python_version(),'gurobi':version('gurobipy'),'git':subprocess.check_output(['git','--version'],text=True).strip()}))"
if ($LASTEXITCODE -ne 0) { throw 'Worker runtime verification failed' }
Write-Output 'MC_ENVIRONMENT_READY'
