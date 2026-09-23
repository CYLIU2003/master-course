"""Bounded background probes; a missing Tailscale CLI is UNKNOWN, not OFFLINE."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .contracts import Worker, git_state, source_digest, runtime_versions
from .store import now
from .transport import invoke, probe_ssh
from .worker_registry import WorkerRegistry, fresh

log = logging.getLogger(__name__)


def classify_probe_error(error: BaseException) -> str:
    if getattr(error, "error_code", None):
        return str(error.error_code)
    message = str(error).lower()
    if "host key" in message or "identification has changed" in message:
        return "SSH_HOST_KEY_MISMATCH"
    if "permission denied" in message or "authentication" in message or "publickey" in message:
        return "SSH_AUTHENTICATION_FAILED"
    if isinstance(error, subprocess.TimeoutExpired) or "timed out" in message:
        return "SSH_TIMEOUT"
    if "connection refused" in message or "no route to host" in message:
        return "SSH_PORT_UNREACHABLE"
    if any(marker in message for marker in ("connection reset", "network is unreachable", "broken pipe",
                                             "connection closed", "connection aborted", "could not resolve hostname")):
        return "SSH_CONNECTION_UNAVAILABLE"
    return "WORKER_PROBE_FAILED"


def parse_tailscale_status(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("BackendState") != "Running":
        raise ValueError("Tailscale status unavailable or incompatible")
    peers = payload.get("Peer")
    if peers is None:
        peers = {}
    if not isinstance(peers, dict):
        raise ValueError("Tailscale Peer format is incompatible")
    result = {}
    for peer in peers.values():
        if not isinstance(peer, dict):
            raise ValueError("Tailscale peer entry is incompatible")
        addresses = peer.get("TailscaleIPs") or []
        if not isinstance(addresses, list) or any(not isinstance(ip, str) for ip in addresses):
            raise ValueError("Tailscale address format is incompatible")
        if peer.get("LastSeen") is not None and not isinstance(peer["LastSeen"], str):
            raise ValueError("Tailscale last-seen format is incompatible")
        observation = {**peer, "Online": peer.get("Online") if isinstance(peer.get("Online"), bool) else None}
        for address in addresses:
            result[address] = observation
    return result


def tailscale_payload() -> dict:
    executable = shutil.which("tailscale")
    if not executable:
        candidate = Path("C:/Program Files/Tailscale/tailscale.exe")
        executable = str(candidate) if candidate.is_file() else "tailscale"
    result = subprocess.run([executable, "status", "--json"], capture_output=True, timeout=4)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-500:] or "Tailscale status failed")
    payload = json.loads(result.stdout)
    parse_tailscale_status(payload)
    return payload


def tailscale_status() -> dict:
    return parse_tailscale_status(tailscale_payload())


def local_tailnet_identity() -> dict:
    payload = tailscale_payload()
    identity = payload.get("Self")
    if not isinstance(identity, dict) or not identity.get("TailscaleIPs"):
        raise ValueError("Cannot verify the controller Tailnet identity for seed import")
    return identity


class WorkerMonitor:
    def __init__(self, registry: WorkerRegistry, workers: list[Worker]):
        self.registry, self.workers = registry, workers
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        self.inflight = set()
        self.controller = {}
        self.controller_checked = 0.0

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.loop, daemon=True, name="worker-monitor")
            self.thread.start()

    def refresh_network(self):
        remote = [worker for worker in self.workers if worker.tailscale_ip]
        if not remote:
            return
        error, peers = None, {}
        try:
            peers = tailscale_status()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
        checked = now()
        for worker in remote:
            peer = peers.get(worker.tailscale_ip)
            last_seen = (peer or {}).get("LastSeen")
            if last_seen and last_seen.startswith("0001-"):
                last_seen = None
            online = peer.get("Online") if peer is not None and not error else None
            self.registry.update(worker.id, {"tailscale_online": online, "network_checked_at": checked,
                "last_seen_at": checked if online is True else last_seen,
                "network_error": error or ("端末がこのTailnetの一覧にありません" if peer is None else None)})

    def refresh_controller(self):
        # Recompute independently of /workers polling. No expensive source walk per API request.
        if time.monotonic() - self.controller_checked > 30 or not self.controller:
            self.controller = {"git": git_state(), "source_digest": source_digest(), "runtime_versions": runtime_versions()}
            self.controller_checked = time.monotonic()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.refresh_controller()
                self.refresh_network()
                for worker in self.workers:
                    record = self.registry.get(worker.id)
                    observed = record["observation"]
                    if not worker.monitoring_enabled:
                        continue
                    if worker.tailscale_ip and observed.get("tailscale_online") is not True:
                        continue
                    if not fresh(observed.get("last_probe_at"), 30) and time.time() >= observed.get("next_probe_at", 0):
                        self.request_probe(worker)
            except Exception:
                log.exception("Worker monitoring failed")
            self.stop_event.wait(5)

    def request_probe(self, worker: Worker) -> bool:
        with self.lock:
            if worker.id in self.inflight or len(self.inflight) >= 3:
                return False
            self.inflight.add(worker.id)
        self.registry.update(worker.id, {"probing": True})
        threading.Thread(target=self.probe, args=(worker,), daemon=True, name=f"probe-{worker.id}").start()
        return True

    def probe(self, worker: Worker):
        started_at = time.time()
        ssh_ready = worker.transport == "local"
        capability, error, error_code = None, None, None
        try:
            if not ssh_ready:
                probe_ssh(worker)
                ssh_ready = True
            capability = invoke(worker, {"operation": "probe"}, self.registry.store.root / "worker-probes" / worker.id, timeout=20)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
            error_code = classify_probe_error(exc)
        finally:
            try:
                self.registry.record_probe_result(worker.id, {"last_probe_at": now(), "ssh_ready": ssh_ready,
                    "session_verified": True, "capability": capability, "probe_error": error, "probing": False,
                    "probe_error_code": error_code}, started_at)
            finally:
                with self.lock:
                    self.inflight.discard(worker.id)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
