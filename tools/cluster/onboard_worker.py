"""Controller-side onboarding of one new SSH worker (after onboard_worker_machine.ps1 ran on it).

Steps: verify identity over key-based SSH, copy the verified uv bootstrap, run
install_worker_environment.ps1, and register the PC DISABLED (enabled=false, gurobi=false).
It never issues or copies a Gurobi license, never enables assignment, and never starts a solver.
Usage: .venv/Scripts/python.exe tools/cluster/onboard_worker.py <tailscale_ip> <ssh_user> [--no-register]
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import ClusterConfig, Worker, read_config, write_config  # noqa: E402

DEPLOY = ROOT / "output" / "cluster-deployment"
SSH = "C:/Windows/System32/OpenSSH/ssh.exe"
SCP = "C:/Windows/System32/OpenSSH/scp.exe"
FLAGS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
PROBE = r"""$ErrorActionPreference='SilentlyContinue'
[pscustomobject]@{computer=$env:COMPUTERNAME;user=$env:USERNAME;
 ram_gib=[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1);
 free_c_gib=[math]::Round((Get-PSDrive C).Free/1GB,1);
 venv=(Test-Path 'C:\mc-worker\venv\Scripts\python.exe')} | ConvertTo-Json -Compress"""


def remote(target: str, script: str, timeout: int = 900) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = [SSH, *FLAGS, target, "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded]
    return subprocess.run(command, capture_output=True, timeout=timeout, encoding="utf-8", errors="replace")


def copy(target: str, source: Path, destination: str) -> None:
    result = subprocess.run([SCP, "-B", *FLAGS, str(source), f"{target}:{destination}"], capture_output=True, timeout=600)
    if result.returncode:
        raise SystemExit(f"scp failed for {source.name}: {result.stderr.decode(errors='replace')[-300:]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ip")
    parser.add_argument("user")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()
    target = f"{args.user}@{args.ip}"

    probe = remote(target, PROBE, 60)
    if probe.returncode:
        raise SystemExit("SSH key login failed (run onboard_worker_machine.ps1 on the PC first): " + probe.stderr[-300:])
    info = json.loads(probe.stdout.strip().splitlines()[-1])
    if info["user"].lower() != args.user.lower():
        raise SystemExit(f"Unexpected user {info['user']}")
    name = info["computer"]
    print(json.dumps({"phase": "IDENTIFIED", **info}), flush=True)

    sha = (DEPLOY / "bootstrap.sha256").read_text().strip()
    if not info["venv"]:
        remote(target, "New-Item -ItemType Directory -Force C:/mc-worker | Out-Null", 60)
        copy(target, DEPLOY / "bootstrap.zip", "C:/mc-worker/bootstrap.zip")
        copy(target, ROOT / "tools" / "cluster" / "install_worker_environment.ps1", "C:/mc-worker/install_environment.ps1")
        # uv prints progress on stderr, so judge success by exit code and the ready marker.
        result = remote(target, f"& C:/mc-worker/install_environment.ps1 -ExpectedComputer '{name}' -ArchiveSha256 '{sha}'")
        if result.returncode or "MC_ENVIRONMENT_READY" not in result.stdout:
            raise SystemExit("Environment install did not report MC_ENVIRONMENT_READY: " + (result.stdout + result.stderr)[-500:])
        print(json.dumps({"phase": "ENVIRONMENT_READY", "runtime": result.stdout.strip().splitlines()[-2]}), flush=True)
    else:
        print(json.dumps({"phase": "ENVIRONMENT_ALREADY_PRESENT"}), flush=True)

    if args.no_register:
        return
    config = read_config()
    worker_id = name.lower().replace("_", "-")
    if any(w.id == worker_id or w.tailscale_ip == args.ip for w in config.workers):
        print(json.dumps({"phase": "ALREADY_REGISTERED", "id": worker_id}))
        return
    config.workers.append(Worker(
        id=worker_id, name=name, transport="ssh", host=args.ip, ssh_user=args.user, tailscale_ip=args.ip,
        python="C:/mc-worker/venv/Scripts/python.exe", repo="C:/mc-worker/repo", workspace="C:/mc-worker/jobs",
        gurobi=False, enabled=False, ram_gb=info["ram_gib"]))
    ClusterConfig.model_validate(config.model_dump())
    write_config(config)
    print(json.dumps({"phase": "REGISTERED_DISABLED", "id": worker_id, "ram_gb": info["ram_gib"]}))


if __name__ == "__main__":
    main()
