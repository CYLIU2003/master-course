"""Persistent operator controls and time-bounded observations, separate from jobs."""
from __future__ import annotations

from .resource_policy import machine_memory_budget

import json
import time
from datetime import datetime, timezone

from .contracts import Worker, canonical, digest, comparable_runtime
from .store import JobStore, now

PROBE_TTL_SECONDS = 90
NETWORK_TTL_SECONDS = 20
JOB_ROLES = frozenset({"both", "gurobi_only", "alns_only", "diagnostic_only"})


def job_role_allows(role: str, manifest: dict) -> bool:
    """The operator's role limits optimization placement, including pinned jobs."""
    kind = manifest.get("kind")
    if kind in {"diagnostic", "license_test"}:
        return True
    if kind != "optimization":
        return False
    if manifest.get("requires_gurobi"):
        return role in {"both", "gurobi_only"}
    return role in {"both", "alns_only"}


def fresh(timestamp: str | None, maximum_age: float) -> bool:
    if not timestamp:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()
        return 0 <= age <= maximum_age
    except (ValueError, TypeError):
        return False


class WorkerRegistry:
    def __init__(self, store: JobStore, workers: list[Worker]):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY, config_hash TEXT NOT NULL, mode TEXT,
                observation TEXT NOT NULL, updated_at TEXT NOT NULL,
                job_role TEXT)""")
            if "job_role" not in {column[1] for column in db.execute("PRAGMA table_info(workers)")}:
                db.execute("ALTER TABLE workers ADD COLUMN job_role TEXT")
        for worker in workers:
            self.ensure(worker)
            # Persist history, but never reuse readiness across a controller restart.
            self.update(worker.id, {"session_verified": False, "probing": False})

    def ensure(self, worker: Worker):
        fingerprint = digest(canonical(worker.model_dump()))
        with self.store.connect() as db:
            db.execute("""INSERT INTO workers (id, config_hash, mode, observation, updated_at)
                VALUES (?, ?, NULL, '{}', ?)
                ON CONFLICT(id) DO UPDATE SET config_hash=excluded.config_hash,
                observation=CASE WHEN workers.config_hash=excluded.config_hash
                    THEN workers.observation ELSE '{}' END""", (worker.id, fingerprint, now()))
            if not worker.gurobi:
                db.execute("UPDATE workers SET job_role='alns_only' WHERE id=? AND job_role IN ('both', 'gurobi_only')",
                           (worker.id,))

    def get(self, worker_id: str) -> dict:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
        if row is None:
            raise KeyError(worker_id)
        return {**dict(row), "observation": json.loads(row["observation"])}

    def update(self, worker_id: str, values: dict):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT observation FROM workers WHERE id=?", (worker_id,)).fetchone()
            if row is None:
                raise KeyError(worker_id)
            observation = {**json.loads(row[0]), **values}
            db.execute("UPDATE workers SET observation=?, updated_at=? WHERE id=?", (json.dumps(observation), now(), worker_id))

    def quarantine_transport_failure(self, worker_id: str, error_code: str, error: str) -> None:
        """Invalidate stale readiness immediately after an SSH operation fails."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT observation FROM workers WHERE id=?", (worker_id,)).fetchone()
            if row is None:
                raise KeyError(worker_id)
            observation = json.loads(row[0])
            failures = int(observation.get("probe_failures", 0) or 0) + 1
            failed_at = time.time()
            observation.update({
                "session_verified": False,
                "ssh_ready": False,
                "probing": False,
                "transport_failure_at": failed_at,
                "probe_error": error,
                "probe_error_code": error_code,
                "probe_failures": failures,
                "next_probe_at": failed_at + min(120, 30 * 2 ** min(failures - 1, 2)),
            })
            db.execute("UPDATE workers SET observation=?, updated_at=? WHERE id=?",
                       (json.dumps(observation), now(), worker_id))

    def record_probe_result(self, worker_id: str, values: dict, started_at: float) -> bool:
        """Ignore a probe that started before a newer runtime SSH failure."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT observation FROM workers WHERE id=?", (worker_id,)).fetchone()
            if row is None:
                raise KeyError(worker_id)
            observation = json.loads(row[0])
            latest_failure = float(observation.get("transport_failure_at", 0) or 0)
            if latest_failure > started_at:
                # This older in-flight probe must not make the worker schedulable again.
                observation["probing"] = False
                db.execute("UPDATE workers SET observation=?, updated_at=? WHERE id=?",
                           (json.dumps(observation), now(), worker_id))
                return False
            failures = int(observation.get("probe_failures", 0) or 0) + 1 if values.get("probe_error") else 0
            observation.update(values)
            observation["probe_failures"] = failures
            observation["next_probe_at"] = time.time() + min(120, 30 * 2 ** min(max(failures - 1, 0), 2))
            db.execute("UPDATE workers SET observation=?, updated_at=? WHERE id=?",
                       (json.dumps(observation), now(), worker_id))
            return True

    def set_mode(self, worker_id: str, mode: str):
        if mode not in {"active", "disabled", "draining"}:
            raise ValueError("Invalid worker mode")
        with self.store.connect() as db:
            db.execute("UPDATE workers SET mode=?, updated_at=? WHERE id=?", (mode, now(), worker_id))

    def job_role(self, worker: Worker) -> str:
        return self.get(worker.id)["job_role"] or ("both" if worker.gurobi else "alns_only")

    def set_job_role(self, worker_id: str, role: str):
        if role not in JOB_ROLES:
            raise ValueError("Invalid worker job role")
        with self.store.connect() as db:
            db.execute("UPDATE workers SET job_role=?, updated_at=? WHERE id=?", (role, now(), worker_id))

    def view(self, worker: Worker, jobs: list[dict], controller: dict) -> dict:
        row = self.get(worker.id)
        observation = row["observation"]
        mode = row["mode"] or ("active" if worker.enabled else "disabled")
        job_role = row["job_role"] or ("both" if worker.gurobi else "alns_only")
        capability = observation.get("capability") or {}
        recent = observation.get("session_verified", False) and fresh(observation.get("last_probe_at"), PROBE_TTL_SECONDS)
        online = observation.get("tailscale_online") if fresh(observation.get("network_checked_at"), NETWORK_TTL_SECONDS) else None
        network_ok = not worker.tailscale_ip or online is True
        ssh_ready = worker.transport == "local" or (recent and observation.get("ssh_ready", False))
        reasons = []
        if not worker.identity_verified:
            reasons.append("登録端末の本人確認が未完了です")
        if not network_ok:
            reasons.append("Tailscaleがオフライン" if online is False else "Tailscale状態を確認できません")
        if not recent:
            reasons.append("計算環境の確認待ち、または確認期限切れ")
        if not ssh_ready:
            reasons.append("SSH接続未確認")
        if not capability:
            reasons.append("Worker runnerを確認できません")
        elif (capability.get("git") != controller.get("git")
              or capability.get("source_digest") != controller.get("source_digest")
              or comparable_runtime(capability.get("runtime_versions"), requires_gurobi=False)
              != comparable_runtime(controller.get("runtime_versions"), requires_gurobi=False)):
            reasons.append("親機とコードまたはPython依存環境が一致しません")
        if capability.get("disk_free_gb") is None or capability["disk_free_gb"] < worker.minimum_disk_free_gb:
            reasons.append("作業領域の空き容量が不足、または未確認")
        runner_ready = not reasons
        if controller.get("git", {}).get("dirty", True):
            reasons.append("最適化には親機と子機のclean commitが必要です")
        cpu_ready = not reasons
        if capability.get("runtime_versions") != controller.get("runtime_versions"):
            reasons.append("Gurobi依存環境のバージョンが一致しません")
        if not worker.gurobi or not capability.get("gurobi_version"):
            reasons.append("Gurobiのインストールと利用枠の設定が必要です")
        from .resource_policy import gurobi_ram_eligible
        if not gurobi_ram_eligible(capability):
            reasons.append("Gurobiは搭載RAM 32GB以上が必要です（不足または未確認）")
        ready = not reasons
        active = [job for job in jobs if job["worker_id"] == worker.id and job["state"] in {"STAGING", "RUNNING", "COLLECTING", "LOST"}]
        state = "READY" if ready else "SSH_READY" if ssh_ready and recent else "TAILSCALE_ONLINE" if online is True else "OFFLINE" if online is False else "UNKNOWN"
        if worker.tailscale_ip and online is False:
            state = "OFFLINE"
        if active:
            state = "BUSY"
        if mode != "active":
            state = "DISABLED" if mode == "disabled" else "DRAINING"
        return {"id": worker.id, "name": worker.name, "host": worker.host, "ssh_user": worker.ssh_user,
                "tailscale_ip": worker.tailscale_ip, "transport": worker.transport,
                "enabled": mode != "disabled", "mode": mode, "job_role": job_role,
                "status": state, "slots": worker.slots,
                "reserved": len(active), "active_jobs": [{"id": job["id"], "state": job["state"]} for job in active],
                "gurobi": worker.gurobi, "ram_gb": worker.ram_gb,
                "reserved_system_ram_gb": worker.reserved_system_ram_gb,
                "machine_memory_budget_gib": machine_memory_budget(capability),
                "tailscale_online": online, "ssh_ready": bool(ssh_ready and recent),
                "environment_ready": runner_ready, "can_run_optimization": ready and mode == "active",
                "can_run_no_gurobi": cpu_ready and mode == "active",
                "can_run_diagnostic": runner_ready and mode == "active", "readiness_reasons": reasons,
                "last_seen_at": observation.get("last_seen_at"), "network_checked_at": observation.get("network_checked_at"),
                "last_probe_at": observation.get("last_probe_at"), "probing": observation.get("probing", False),
                "next_probe_at": observation.get("next_probe_at"),
                "last_error": observation.get("probe_error") or observation.get("network_error"),
                "probe_error_code": observation.get("probe_error_code"),
                "capability": capability, "metrics_stale": not recent,
                "identity_verified": worker.identity_verified,
                "last_allocation": observation.get("last_allocation"),
                "completed_jobs": sum(job["state"] == "COMPLETED" and job["worker_id"] == worker.id for job in jobs),
                "failed_jobs": sum(job["state"] in {"FAILED", "BLOCKED"} and job["worker_id"] == worker.id for job in jobs)}
