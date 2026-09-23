"""Validate private seed inventories without resetting previously verified nodes."""
from __future__ import annotations

import ipaddress
import socket
from pydantic import BaseModel, ConfigDict, Field

from .contracts import ClusterConfig, Worker


class SeedWorker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    transport: str
    host: str | None = None
    ssh_user: str | None = None
    ssh_port: int = Field(default=22, ge=1, le=65535)
    monitoring_enabled: bool = True
    accepting_jobs: bool = False
    max_concurrent_jobs: int = Field(default=1, ge=1, le=16)
    tailscale_node_id: str | None = None
    ssh_host_key_fingerprint: str | None = None
    identity_verification: str = "unverified"
    workspace: str | None = None
    python_executable: str | None = None
    capabilities_verification: str | None = None


class SeedInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    implementation_status: str = ""
    source: str = ""
    privacy: str = ""
    license_policy: dict = Field(default_factory=dict)
    local_worker: SeedWorker
    workers: list[SeedWorker]


def merge_private_seed(payload: dict, existing: ClusterConfig, *, self_node_id: str | None = None,
                       self_name: str | None = None, self_addresses: set[str] | None = None) -> ClusterConfig:
    seed = SeedInventory.model_validate(payload)
    if seed.schema_version != "cluster-worker-seed-proposal-v1":
        raise ValueError("Unsupported private seed schema")
    entries = [seed.local_worker, *seed.workers]
    if seed.local_worker.transport != "local" or any(w.transport != "ssh" for w in seed.workers):
        raise ValueError("Exactly one local worker and SSH remote workers are required")
    ids, addresses, nodes = set(), set(), set()
    names = {name.casefold() for name in (self_name or socket.gethostname(), seed.local_worker.name)}
    proposed = []
    for entry in entries:
        if entry.id in ids:
            raise ValueError("Duplicate worker ID")
        ids.add(entry.id)
        if entry.transport == "ssh":
            address = ipaddress.ip_address(entry.host or "")
            if address.version != 4 or address not in ipaddress.ip_network("100.64.0.0/10"):
                raise ValueError("Remote seed address must belong to the Tailnet IPv4 range")
            if str(address) in addresses or str(address) in (self_addresses or set()) or entry.name.casefold() in names:
                raise ValueError("Duplicate remote or local machine identity")
            addresses.add(str(address))
        if entry.tailscale_node_id:
            if entry.tailscale_node_id in nodes or (entry.transport == "ssh" and entry.tailscale_node_id == self_node_id):
                raise ValueError("Duplicate local/remote Tailnet node identity")
            nodes.add(entry.tailscale_node_id)
        proposed.append(Worker(id=entry.id, name=entry.name, transport=entry.transport,
            host=entry.host, tailscale_ip=entry.host if entry.transport == "ssh" else None,
            ssh_user=entry.ssh_user, ssh_port=entry.ssh_port, enabled=False,
            monitoring_enabled=entry.monitoring_enabled, slots=1, gurobi=False, identity_verified=False,
            tailscale_node_id=entry.tailscale_node_id, ssh_host_key_fingerprint=entry.ssh_host_key_fingerprint,
            workspace=entry.workspace or "", python=entry.python_executable or "",
            reserved_system_ram_gb=2 if entry.transport == "local" else 1,
            require_ac_power=True))
    result = list(existing.workers)
    current = {worker.id: worker for worker in existing.workers}
    for incoming in proposed:
        previous = current.get(incoming.id)
        if previous:
            # Host aliases are administrator-owned; compare the registered Tailnet address.
            if ((previous.tailscale_ip or previous.host) != (incoming.tailscale_ip or incoming.host)
                    or previous.ssh_user != incoming.ssh_user or previous.name != incoming.name) and incoming.transport != "local":
                raise ValueError("Existing identity differs; refusing to overwrite a registered worker")
            continue
        result.append(incoming)
    return ClusterConfig(global_gurobi_slots=existing.global_gurobi_slots,
                         external_gurobi_slots=existing.external_gurobi_slots, workers=result)
