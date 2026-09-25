"""Durable admission shared by local processes and remote cluster attempts.

An unresolved owner never expires. Only verified completion starts token-tail
cooldown; elapsed heartbeat time is not proof that a remote process stopped.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .store import JobStore, now, worker_has_slot


class LicenseBroker:
    def __init__(self, store: JobStore, *, total: int, external: int):
        if not 0 <= external <= total <= 2:
            raise ValueError("Managed WLS capacity must be between zero and two")
        self.store, self.total, self.external = store, total, external
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS license_reservations (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, owner_kind TEXT NOT NULL,
                owner_identity TEXT, release_after REAL, updated_at TEXT NOT NULL
            )""")

    def acquire(self, reservation_id: str, *, owner_kind: str, owner_identity: str = "",
                worker_id: str | None = None, worker_slots: int = 1,
                cpu_threads: int = 0, cpu_count: int | None = None) -> bool:
        if owner_kind not in {"local", "remote"}:
            raise ValueError("Invalid license owner kind")
        authority = os.environ.get("MC_GUROBI_AUTHORITY_FILE")
        if authority:
            from .license_authority import has_authority
            if not has_authority(Path(authority), self.store.root):
                return False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            at = time.time()
            # Never infer that an ACTIVE/RECONCILING owner died from elapsed time.
            db.execute("UPDATE license_reservations SET state='RELEASED' WHERE state='RELEASING' AND release_after<=?", (at,))
            existing = db.execute("SELECT state FROM license_reservations WHERE id=?", (reservation_id,)).fetchone()
            if existing:
                return False  # A duplicate process cannot reuse another process's grant.
            leases = list(db.execute("SELECT id FROM license_reservations WHERE state!='RELEASED'"))
            known = {r[0] for r in db.execute("SELECT id FROM license_reservations")}
            legacy = 0
            for job in db.execute("SELECT id,state,manifest,result,updated_at FROM jobs"):
                manifest = json.loads(job["manifest"])
                if job["id"] in known or not manifest.get("requires_gurobi"):
                    continue
                result = json.loads(job["result"]) if job["result"] else {}
                if result.get("cluster_admission") == "FENCED_BEFORE_LAUNCH":
                    continue
                tail = float(manifest.get("gurobi_token_cooldown_seconds") or 0)
                cooling = (job["state"] in {"COMPLETED", "FAILED", "BLOCKED"}
                           and at - datetime.fromisoformat(job["updated_at"]).timestamp() < tail)
                if job["state"] in {"STAGING", "RUNNING", "COLLECTING", "LOST"} or cooling:
                    legacy += 1
            if self.external + legacy + len(leases) >= self.total:
                return False
            if worker_id is not None:
                if not worker_has_slot(db, worker_id, worker_slots, cpu_threads=cpu_threads, cpu_count=cpu_count):
                    return False
                changed = db.execute("UPDATE jobs SET state='STAGING',worker_id=?,updated_at=? WHERE id=? AND state='QUEUED'",
                                     (worker_id, now(), reservation_id))
                if changed.rowcount != 1:
                    return False
                db.execute("INSERT INTO events(job_id,state,at) VALUES (?, 'STAGING', ?)", (reservation_id, now()))
            db.execute("INSERT INTO license_reservations VALUES (?, 'ACTIVE', ?, ?, NULL, ?)",
                       (reservation_id, owner_kind, owner_identity, now()))
            return True

    def finish(self, reservation_id: str, *, cooldown_seconds: float):
        if cooldown_seconds < 0:
            raise ValueError("Invalid cooldown")
        with self.store.connect() as db:
            # Repeated receipts cannot shorten or restart a token tail.
            db.execute("""UPDATE license_reservations SET state='RELEASING',release_after=?,updated_at=?
                          WHERE id=? AND state IN ('ACTIVE','RECONCILING')""",
                       (time.time() + cooldown_seconds, now(), reservation_id))

    def mark_uncertain(self, reservation_id: str):
        with self.store.connect() as db:
            db.execute("UPDATE license_reservations SET state='RECONCILING',updated_at=? WHERE id=? AND state='ACTIVE'",
                       (now(), reservation_id))

    def snapshot(self) -> list[dict]:
        with self.store.connect() as db:
            # Owner process identity is never exposed to the browser.
            return [dict(row) for row in db.execute(
                "SELECT id,state,release_after,updated_at FROM license_reservations ORDER BY updated_at")]

    def reconcile_local_owners(self):
        """Only same-host owners are checked with local PID creation identity."""
        from .runner import process_identity
        with self.store.connect() as db:
            rows = list(db.execute("SELECT id,owner_identity FROM license_reservations WHERE owner_kind='local' AND state IN ('ACTIVE','RECONCILING')"))
        for row in rows:
            raw = row["owner_identity"] or ""
            pid, separator, birth = raw.partition(":")
            if not separator or not pid.isdigit() or birth in {"", "unknown", "None"}:
                self.mark_uncertain(row["id"])
                continue
            current = process_identity(int(pid))
            if current is None or (current != "unknown" and current != birth):
                self.finish(row["id"], cooldown_seconds=330)
