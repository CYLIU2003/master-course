"""Fixed runner command over local subprocess or verified OpenSSH."""
from __future__ import annotations

import base64
import json
import shlex
import subprocess
import time
from pathlib import Path

from .contracts import Worker, canonical


class SSHTransportError(RuntimeError):
    """A failed SSH operation whose result may be uncertain to the caller."""

    def __init__(self, operation: str, error_code: str, attempts: int):
        self.operation = operation
        self.error_code = error_code
        self.attempts = attempts
        super().__init__(f"{error_code}: SSH {operation} failed after {attempts} attempt(s)")


def _classify_ssh_failure(stderr: str, *, timed_out: bool = False) -> tuple[str, bool]:
    """Return a stable failure code and whether one identical retry is safe."""
    message = stderr.lower()
    if timed_out or "timed out" in message or "operation timed out" in message:
        return "SSH_TIMEOUT", True
    if "host key verification failed" in message or "remote host identification has changed" in message:
        return "SSH_HOST_KEY_MISMATCH", False
    if "permission denied" in message or "no supported authentication methods" in message:
        return "SSH_AUTHENTICATION_FAILED", False
    transient_markers = (
        "connection reset", "connection refused", "no route to host", "network is unreachable",
        "broken pipe", "connection closed", "connection aborted", "could not resolve hostname",
        "cannot assign requested address", "destination host unreachable",
    )
    if any(marker in message for marker in transient_markers):
        return "SSH_CONNECTION_UNAVAILABLE", True
    return "SSH_HANDSHAKE_FAILED", False


def ssh_command(worker: Worker, remote: str) -> list[str]:
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=4",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-p", str(worker.ssh_port)]
    if worker.ssh_user:
        args += ["-l", worker.ssh_user]
    return [*args, worker.host, remote]


def probe_ssh(worker: Worker):
    command = ssh_command(worker, "echo MC_WORKER_OK")
    for attempt, timeout in enumerate((10, 20)):
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
        except OSError as exc:
            raise SSHTransportError("probe", "SSH_CLIENT_UNAVAILABLE", attempt + 1) from exc
        except subprocess.TimeoutExpired as exc:
            error_code, retryable = _classify_ssh_failure("", timed_out=True)
            if retryable and attempt == 0:
                continue
            raise SSHTransportError("probe", error_code, attempt + 1) from exc
        if result.returncode == 0 and result.stdout.strip() == b"MC_WORKER_OK":
            return
        error = result.stderr.decode("utf-8", errors="replace")[-1200:]
        error_code, retryable = _classify_ssh_failure(error)
        if attempt == 0 and retryable:
            continue
        raise SSHTransportError("probe", error_code, attempt + 1)


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
    payload = canonical(request)
    operation = str(request.get("operation") or "unknown")
    # Stream transport output to disk; long optimizations must not hold a pipe full of solver logs.
    # An SSH retry repeats the exact same id and bytes. Runner operations are attempt-scoped;
    # never synthesize a replacement job identity when the remote outcome is uncertain.
    max_attempts = 2 if worker.transport == "ssh" else 1
    for attempt in range(1, max_attempts + 1):
        attempt_stdout = directory / f"transport.stdout.attempt-{attempt}"
        attempt_stderr = directory / f"transport.stderr.attempt-{attempt}"
        timed_out = False
        with attempt_stdout.open("wb") as stdout, attempt_stderr.open("wb") as stderr:
            try:
                process = subprocess.Popen(command(worker), cwd=worker.repo if worker.transport == "local" else None,
                                           stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
            except OSError as exc:
                if worker.transport == "ssh":
                    raise SSHTransportError(operation, "SSH_CLIENT_UNAVAILABLE", attempt) from exc
                raise
            try:
                process.communicate(payload, timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()

        error_text = attempt_stderr.read_text(encoding="utf-8", errors="replace")[-2000:]
        if timed_out:
            if worker.transport == "ssh":
                error_code, retryable = _classify_ssh_failure(error_text, timed_out=True)
                if retryable and attempt < max_attempts:
                    time.sleep(0.5)
                    continue
                attempt_stderr.replace(directory / "transport.stderr")
                raise SSHTransportError(operation, error_code, attempt)
            raise subprocess.TimeoutExpired(command(worker), timeout)
        if process.returncode == 0:
            attempt_stdout.replace(directory / "transport.stdout")
            attempt_stderr.replace(directory / "transport.stderr")
            break
        if worker.transport == "ssh" and process.returncode == 255:
            error_code, retryable = _classify_ssh_failure(error_text)
            if retryable and attempt < max_attempts:
                time.sleep(0.5)
                continue
            attempt_stderr.replace(directory / "transport.stderr")
            raise SSHTransportError(operation, error_code, attempt)
        attempt_stderr.replace(directory / "transport.stderr")
        raise RuntimeError(f"Worker transport exited {process.returncode}: {error_text}")
    if request.get("operation") == "archive":
        return {"archive_path": str(directory / "transport.stdout")}
    return json.loads((directory / "transport.stdout").read_text(encoding="utf-8"))
