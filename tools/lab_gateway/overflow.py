"""Borrow idle thesis PCs for lab jobs when the lab pool is full.

The thesis controller stays in charge of its PCs. A PC is borrowed only when that controller reports it READY,
active, with no job and no reservation, and only beyond the idle PCs kept free for queued thesis jobs. The PC is
put into the controller's own "draining" mode (no new thesis jobs) before the lab job is staged, and set back to
"active" when the lab job ends. If a thesis job slipped in between the check and the drain, the claim is undone.
Claims are kept in overflow_claims.json so a gateway restart can resume or release them.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from .remote import Machine
from .store import now

DEFAULT_PYTHON = "C:/mc-worker/venv/Scripts/python.exe"


class ControllerError(RuntimeError):
    pass


def controller_http(base_url: str, method: str, path: str, timeout: float = 20) -> dict:
    request = urllib.request.Request(base_url.rstrip("/") + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ControllerError(f"thesis controller {method} {path} failed: {type(exc).__name__}") from exc


class ThesisOverflow:
    def __init__(self, data_dir: Path, *, base_url: str, max_minutes: int = 360, keep_idle: int = 2,
                 http=controller_http, machine_factory=Machine, cache_seconds: float = 20):
        self.path = data_dir / "overflow_claims.json"
        self.base_url, self.max_minutes, self.keep_idle = base_url, max_minutes, keep_idle
        self.http, self.machine_factory, self.cache_seconds = http, machine_factory, cache_seconds
        self.lock = threading.RLock()
        self._cache: tuple[float, list[dict]] | None = None

    # ---- claims file
    def claims(self) -> dict[str, dict]:
        with self.lock:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _save(self, claims: dict[str, dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(claims, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- controller view
    def eligible(self, job: dict) -> bool:
        return int(job["time_limit_min"]) <= self.max_minutes

    def candidates(self, exclude: set[str]) -> list[dict]:
        """Idle thesis PCs that may be borrowed, weakest first; the strongest idle ones stay free for the thesis queue."""
        if self._cache and time.monotonic() - self._cache[0] < self.cache_seconds:
            idle_sorted = self._cache[1]
        else:
            workers = self.http(self.base_url, "GET", "/api/cluster/workers")["workers"]
            queued = sum(1 for job in self.http(self.base_url, "GET", "/api/cluster/jobs") if job.get("state") == "QUEUED")
            idle = [w for w in workers if w.get("transport") == "ssh" and w.get("host") and w.get("mode") == "active"
                    and w.get("status") == "READY" and not w.get("active_jobs") and not w.get("reserved")]
            idle.sort(key=lambda w: w.get("machine_memory_budget_gib") or 0, reverse=True)
            idle_sorted = list(reversed(idle[min(queued, self.keep_idle):]))
            self._cache = (time.monotonic(), idle_sorted)
        claimed = self.claims()
        return [w for w in idle_sorted if w["id"] not in exclude and w["id"] not in claimed]

    def machine(self, view: dict):
        capability = view.get("capability") or {}
        worker = SimpleNamespace(id=view["id"], host=view["host"], ssh_user=view.get("ssh_user"), ssh_port=22,
                                 python=capability.get("python_executable") or DEFAULT_PYTHON)
        return self.machine_factory(worker)

    def machine_for(self, machine_id: str):
        claim = self.claims().get(machine_id)
        return self.machine(claim["view"]) if claim else None

    # ---- borrow / give back
    def claim(self, view: dict, job_id: str) -> bool:
        with self.lock:
            self.http(self.base_url, "POST", f"/api/cluster/workers/{view['id']}/drain")
            after = self.http(self.base_url, "GET", f"/api/cluster/workers/{view['id']}")
            if after.get("active_jobs") or after.get("reserved"):
                self.http(self.base_url, "POST", f"/api/cluster/workers/{view['id']}/enable")
                self._cache = None
                return False
            claims = self.claims()
            claims[view["id"]] = {"job_id": job_id, "claimed_at": now(),
                                  "view": {k: view.get(k) for k in ("id", "host", "ssh_user", "capability")}}
            self._save(claims)
            self._cache = None
            return True

    def release(self, machine_id: str) -> None:
        with self.lock:
            claims = self.claims()
            if machine_id not in claims:
                return
            try:
                current = self.http(self.base_url, "GET", f"/api/cluster/workers/{machine_id}")
                if current.get("mode") == "draining":  # still ours; never re-enable a PC someone disabled meanwhile
                    self.http(self.base_url, "POST", f"/api/cluster/workers/{machine_id}/enable")
            except ControllerError:
                return  # keep the claim so the next reconcile retries
            claims.pop(machine_id)
            self._save(claims)
            self._cache = None

    def reconcile(self, active_job_ids: set[str]) -> None:
        for machine_id, claim in self.claims().items():
            if claim["job_id"] not in active_job_ids:
                self.release(machine_id)
