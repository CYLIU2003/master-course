"""Reserve the controller PC for ordinary BFF jobs as well as cluster jobs."""
from __future__ import annotations

import os

from .contracts import Worker
from .store import JobStore, now, worker_has_slot


class LocalResources:
    def __init__(self, store: JobStore):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS local_resources (
                id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, pid INTEGER NOT NULL,
                identity TEXT, state TEXT NOT NULL, cpu_threads INTEGER NOT NULL,
                updated_at TEXT NOT NULL)""")

    def reconcile(self):
        from .runner import process_identity
        with self.store.connect() as db:
            rows = list(db.execute("SELECT id,pid,identity FROM local_resources WHERE state='ACTIVE'"))
        for row in rows:
            current = process_identity(row["pid"])
            if current is None or (current != "unknown" and row["identity"] not in {None, "unknown"} and current != row["identity"]):
                self.release(row["id"])

    def acquire(self, job_id: str, worker: Worker, cpu_threads: int) -> bool:
        from .runner import process_identity
        cores = os.cpu_count()
        requested = cpu_threads or cores or 1
        if cores is not None and requested > cores:
            raise ValueError("Requested solver threads exceed this PC; select another worker")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not worker_has_slot(db, worker.id, worker.slots, cpu_threads=requested, cpu_count=cores):
                return False
            db.execute("INSERT INTO local_resources VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)",
                       (job_id, worker.id, os.getpid(), process_identity(os.getpid()), requested, now()))
            return True

    def release(self, job_id: str):
        with self.store.connect() as db:
            db.execute("UPDATE local_resources SET state='RELEASED',updated_at=? WHERE id=?", (now(), job_id))

    def rows(self) -> list[dict]:
        with self.store.connect() as db:
            return [{"id": r["id"], "worker_id": r["worker_id"], "state": "RUNNING",
                     "manifest": {"kind": "local_execution", "requires_gurobi": False, "minimum_ram_gb": 0,
                                  "resource_requirements": {"cpu_threads": r["cpu_threads"]}},
                     "result": None} for r in db.execute("SELECT * FROM local_resources WHERE state='ACTIVE'")]
