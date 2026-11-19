"""OpenSSH/scp access to one lab PC. Fixed commands only; no user-supplied text reaches a shell."""
from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

REMOTE_ROOT = "C:/mc-lab/jobs"
RUN_SCRIPT = Path(__file__).with_name("run_job.py")
JOB_ID = re.compile(r"[0-9a-f]{12}")
WINDOWS_OPENSSH = Path("C:/Windows/System32/OpenSSH")


class RemoteError(RuntimeError):
    pass


def _binary(name: str) -> str:
    # Git for Windows' ssh cannot read a BOM-prefixed ~/.ssh/config; the Windows client can.
    candidate = WINDOWS_OPENSSH / f"{name}.exe"
    return str(candidate) if candidate.exists() else name


def _encoded(script: str) -> str:
    return "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(script.encode("utf-16le")).decode("ascii")


def run_process(command: list[str], *, timeout: float, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, timeout=timeout, cwd=cwd)


class Machine:
    """One PC from the lab pool. `runner` is injectable so the dispatcher can be tested without SSH."""

    def __init__(self, worker, *, runner=run_process):
        self.id = worker.id
        self.host, self.user, self.port, self.python = worker.host, worker.ssh_user, worker.ssh_port, worker.python
        self.runner = runner

    def _options(self) -> list[str]:
        return ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]

    def _target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def ssh(self, script: str, *, timeout: float = 60) -> str:
        command = [_binary("ssh"), "-T", *self._options(), "-p", str(self.port), self._target(), _encoded(script)]
        try:
            result = self.runner(command, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RemoteError(f"ssh to {self.id} failed: {type(exc).__name__}") from exc
        if result.returncode != 0:
            tail = result.stderr.decode("utf-8", "replace")[-300:]
            raise RemoteError(f"ssh to {self.id} exited {result.returncode}: {tail}")
        return result.stdout.decode("utf-8", "replace")

    def scp(self, *, local: Path, remote: str, upload: bool, timeout: float = 600) -> None:
        peer = f"{self._target()}:{remote}"
        endpoints = [local.name, peer] if upload else [peer, local.name]
        command = [_binary("scp"), "-q", *self._options(), "-P", str(self.port), *endpoints]
        try:
            result = self.runner(command, timeout=timeout, cwd=str(local.parent))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RemoteError(f"scp with {self.id} failed: {type(exc).__name__}") from exc
        if result.returncode != 0:
            raise RemoteError(f"scp with {self.id} exited {result.returncode}: {result.stderr.decode('utf-8', 'replace')[-300:]}")

    @staticmethod
    def job_dir(job_id: str) -> str:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("invalid job id")
        return f"{REMOTE_ROOT}/{job_id}"

    def probe(self) -> dict:
        script = ("$os = Get-CimInstance Win32_OperatingSystem; $cs = Get-CimInstance Win32_ComputerSystem; "
                  "$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
                  "@{total_gb=[math]::Round($cs.TotalPhysicalMemory/1GB,2); free_gb=[math]::Round($os.FreePhysicalMemory/1MB,2); "
                  "cpu_load=[double]$cpu; cpus=[int]$cs.NumberOfLogicalProcessors; "
                  "disk_free_gb=[math]::Round((Get-PSDrive C).Free/1GB,1); "
                  f"python_ok=(Test-Path '{self.python}')}} | ConvertTo-Json -Compress")
        lines = [line for line in self.ssh(script, timeout=45).splitlines() if line.strip().startswith("{")]
        if not lines:
            raise RemoteError(f"probe of {self.id} returned no data")
        return json.loads(lines[-1])

    def stage(self, job_id: str, bundle: Path, job: dict) -> None:
        directory = self.job_dir(job_id)
        self.ssh(f"New-Item -ItemType Directory -Force -Path '{directory}/work' | Out-Null", timeout=30)
        self.scp(local=bundle, remote=f"{directory}/bundle.zip", upload=True)
        with tempfile.TemporaryDirectory() as temporary:
            spec = Path(temporary) / "job.json"
            spec.write_text(json.dumps({**job, "job_id": job_id, "python": self.python}), encoding="ascii")
            self.scp(local=spec, remote=f"{directory}/job.json", upload=True)
        self.scp(local=RUN_SCRIPT, remote=f"{directory}/run_job.py", upload=True)
        # run_job.py --detach breaks away from sshd's kill-on-close Job Object, like the thesis cluster runner.
        self.ssh("$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; "
                 f"[IO.Compression.ZipFile]::ExtractToDirectory('{directory}/bundle.zip','{directory}/work'); "
                 f"& '{self.python}' '{directory}/run_job.py' '{directory}' --detach; if ($LASTEXITCODE -ne 0) {{ throw 'launcher failed' }}",
                 timeout=90)

    def status(self, job_id: str) -> dict | None:
        directory = self.job_dir(job_id)
        text = self.ssh(f"if (Test-Path '{directory}/status.json') {{ Get-Content -Raw '{directory}/status.json' }}", timeout=30).strip()
        return json.loads(text) if text.startswith("{") else None

    def fetch_result(self, job_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.scp(local=destination, remote=f"{self.job_dir(job_id)}/result.zip", upload=False)

    def kill(self, pid: int) -> None:
        self.ssh(f"& taskkill.exe /T /F /PID {int(pid)} | Out-Null; exit 0", timeout=30)

    def cleanup(self, job_id: str) -> None:
        self.ssh(f"Remove-Item -LiteralPath '{self.job_dir(job_id)}' -Recurse -Force -ErrorAction SilentlyContinue; exit 0", timeout=60)
