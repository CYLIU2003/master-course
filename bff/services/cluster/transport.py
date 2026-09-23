"""Fixed runner command over local subprocess or verified OpenSSH."""
from __future__ import annotations

import base64
import json
import shlex
import subprocess
from pathlib import Path

from .contracts import Worker, canonical


def ssh_command(worker: Worker, remote: str) -> list[str]:
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=4",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-p", str(worker.ssh_port)]
    if worker.ssh_user:
        args += ["-l", worker.ssh_user]
    return [*args, worker.host, remote]


def probe_ssh(worker: Worker):
    result = subprocess.run(ssh_command(worker, "echo MC_WORKER_OK"), capture_output=True, timeout=10)
    if result.returncode or result.stdout.strip() != b"MC_WORKER_OK":
        error = result.stderr.decode("utf-8", errors="replace")[-1200:]
        raise RuntimeError(error or "SSH did not return the worker marker")


def command(worker: Worker) -> list[str]:
    args = [worker.python, "-m", "bff.services.cluster.runner", "--workspace", worker.workspace]
    if worker.gurobi_license_file:
        args += ["--license-file", worker.gurobi_license_file]
    if worker.transport == "local":
        return args
    if worker.shell == "powershell":
        def quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"
        script = "$ErrorActionPreference='Stop'; Set-Location -LiteralPath " + quote(worker.repo)
        script += "; & " + " ".join(quote(arg) for arg in args) + "; exit $LASTEXITCODE"
        remote = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(script.encode("utf-16le")).decode("ascii")
    else:
        remote = "cd " + shlex.quote(worker.repo) + " && exec " + shlex.join(args)
    return ssh_command(worker, remote)


def invoke(worker: Worker, request: dict, directory: Path, *, timeout: float | None = None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    # Stream transport output to disk; long optimizations must not hold a pipe full of solver logs.
    with (directory / "transport.stdout").open("wb") as stdout, (directory / "transport.stderr").open("wb") as stderr:
        process = subprocess.Popen(command(worker), cwd=worker.repo if worker.transport == "local" else None,
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        try:
            process.communicate(canonical(request), timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
    if process.returncode:
        detail = (directory / "transport.stderr").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"Worker transport exited {process.returncode}: {detail}")
    if request.get("operation") == "archive":
        return {"archive_path": str(directory / "transport.stdout")}
    return json.loads((directory / "transport.stdout").read_text(encoding="utf-8"))
