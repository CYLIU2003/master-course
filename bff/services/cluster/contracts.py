"""Versioned, hash-bound worker protocol and administrator-owned configuration."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import platform
import ipaddress
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
RESERVED = {"STAGING", "RUNNING", "COLLECTING", "LOST"}


def segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value) or ".." in value:
        raise ValueError("Invalid identifier")
    return value


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_state(root: Path = ROOT) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8", timeout=30).strip()
    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def source_digest(root: Path = ROOT) -> str:
    """Bind diagnostic jobs to actual source, including uncommitted additions."""
    entries = {}
    for folder in ("bff", "src"):
        for path in sorted((root / folder).rglob("*.py")):
            entries[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return digest(canonical(entries))


def runtime_versions() -> dict:
    result = {"python": platform.python_version()}
    lock = ROOT / "tools" / "cluster" / "environment" / "uv.lock"
    result["uv_lock_sha256"] = digest(lock.read_bytes()) if lock.is_file() else None
    for package in ("gurobipy", "numpy", "pandas", "scipy", "pydantic"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def comparable_runtime(versions: dict | None, *, requires_gurobi: bool = True) -> dict:
    return {key: value for key, value in (versions or {}).items() if requires_gurobi or key != "gurobipy"}


class Worker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    transport: Literal["local", "ssh"] = "local"
    host: str | None = None  # OpenSSH config alias, never a browser-supplied command
    ssh_user: str | None = None
    ssh_port: int = Field(default=22, ge=1, le=65535)
    tailscale_ip: str | None = None
    minimum_disk_free_gb: float = Field(default=2, ge=0)
    gurobi_license_file: str | None = None  # Path only. Credentials never enter job bundles.
    gurobi_token_cooldown_seconds: int = Field(default=0, ge=0, le=7200)
    shell: Literal["powershell", "posix"] = "powershell"
    repo: str = str(ROOT)
    python: str = sys.executable
    workspace: str = str(ROOT / "output" / "cluster-worker")
    enabled: bool = True
    slots: int = Field(default=1, ge=1, le=16)
    gurobi: bool = False
    ram_gb: float = Field(default=0, ge=0)
    reserved_system_ram_gb: float = Field(default=4, ge=0, allow_inf_nan=False)
    maximum_cpu_load_percent: float = Field(default=90, gt=0, le=100)
    require_ac_power: bool = False
    monitoring_enabled: bool = True
    tailscale_node_id: str | None = None
    ssh_host_key_fingerprint: str | None = None
    identity_verified: bool = True  # Existing configured workers retain their prior verification path.

    @model_validator(mode="after")
    def validate_worker(self):
        segment(self.id)
        if self.transport == "ssh" and (not self.host or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.host)):
            raise ValueError("SSH requires a trusted OpenSSH config alias")
        if self.ssh_user and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.ssh_user):
            raise ValueError("Invalid SSH user")
        if self.tailscale_ip and ipaddress.ip_address(self.tailscale_ip) not in ipaddress.ip_network("100.64.0.0/10"):
            raise ValueError("tailscale_ip must be a Tailnet IPv4 address")
        return self


class ClusterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    global_gurobi_slots: int = Field(default=2, ge=0, le=2)
    external_gurobi_slots: int = Field(default=0, ge=0, le=64)
    workers: list[Worker] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_workers(self):
        if len({worker.id for worker in self.workers}) != len(self.workers):
            raise ValueError("Duplicate worker ID")
        for field in ("tailscale_ip", "tailscale_node_id"):
            values = [getattr(worker, field) for worker in self.workers if getattr(worker, field)]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate worker {field}")
        if self.external_gurobi_slots > self.global_gurobi_slots:
            raise ValueError("External Gurobi reservations exceed the total slots")
        return self


def config_path() -> Path:
    return Path(os.environ.get("MC_CLUSTER_CONFIG", ROOT / "config" / "cluster" / "workers.local.json"))


def read_config() -> ClusterConfig:
    path = config_path()
    if not path.exists():
        return ClusterConfig(workers=[Worker(id="local", name="このPC")])
    return ClusterConfig.model_validate_json(path.read_text(encoding="utf-8-sig"))


def write_config(config: ClusterConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical(config.model_dump()))
    temporary.replace(path)
