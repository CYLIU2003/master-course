"""SQLite state transitions, durable queue and reservations after disconnects."""
from __future__ import annotations

import json
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import RESERVED


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_has_slot(db, worker_id: str, slots: int, *, cpu_threads: int = 0, cpu_count: int | None = None) -> bool:
    active = [json.loads(row[1]) for row in db.execute("SELECT state,manifest FROM jobs WHERE worker_id=?", (worker_id,)) if row[0] in RESERVED]
    count = len(active)
    reserved_threads = sum((m.get("resource_requirements") or {}).get("cpu_threads") or (cpu_count if m.get("requires_gurobi") else 1) or 1 for m in active)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_resources'").fetchone():
        count += db.execute("SELECT count(*) FROM local_resources WHERE worker_id=? AND state='ACTIVE'", (worker_id,)).fetchone()[0]
        reserved_threads += db.execute("SELECT COALESCE(sum(cpu_threads),0) FROM local_resources WHERE worker_id=? AND state='ACTIVE'", (worker_id,)).fetchone()[0]
    return count < slots and (not cpu_threads or (cpu_count is not None and reserved_threads + cpu_threads <= cpu_count))


class ControllerLock:
    """One scheduler per database across processes, released by the OS on exit."""
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.file = (root / "controller.lock").open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError("Another cluster controller owns this database; use one BFF process") from exc

    def close(self):
        self.file.close()


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "cluster.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, worker_id TEXT,
                    manifest TEXT NOT NULL, error TEXT, result TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL,
                    state TEXT NOT NULL, message TEXT, at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery (
                    job_id TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
                    next_at REAL NOT NULL DEFAULT 0
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, manifest: dict) -> dict:
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES (?, 'QUEUED', NULL, ?, NULL, NULL, ?, ?)",
                       (manifest["id"], json.dumps(manifest), now(), now()))
            db.execute("INSERT INTO events(job_id,state,at) VALUES (?, 'QUEUED', ?)", (manifest["id"], now()))
        return self.get(manifest["id"])

    def rows(self) -> list[dict]:
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at")]

    @staticmethod
    def decode(row) -> dict:
        value = dict(row)
        value["manifest"] = json.loads(value["manifest"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def get(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            value = self.decode(row)
            value["events"] = [dict(item) for item in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY seq", (job_id,))]
            return value

    def transition(self, job_id: str, state: str, *, expected: set[str], worker_id: str | None = None,
                   error: str | None = None, result: dict | None = None) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] not in expected:
                return False
            db.execute("UPDATE jobs SET state=?, worker_id=COALESCE(?,worker_id), error=?, result=COALESCE(?,result), updated_at=? WHERE id=?",
                       (state, worker_id, error, json.dumps(result) if result is not None else None, now(), job_id))
            db.execute("INSERT INTO events(job_id,state,message,at) VALUES (?,?,?,?)", (job_id, state, error, now()))
            return True

    def recover(self):
        for row in self.rows():
            if row["state"] in RESERVED - {"LOST"}:
                self.transition(row["id"], "LOST", expected=RESERVED,
                                error="Controller restarted; reservation retained until reconciliation")

    def reserve_worker(self, job_id: str, worker_id: str, slots: int, *, cpu_threads: int = 0, cpu_count: int | None = None) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not worker_has_slot(db, worker_id, slots, cpu_threads=cpu_threads, cpu_count=cpu_count):
                return False
            changed = db.execute("UPDATE jobs SET state='STAGING',worker_id=?,updated_at=? WHERE id=? AND state='QUEUED'",
                                 (worker_id, now(), job_id))
            if changed.rowcount != 1:
                return False
            db.execute("INSERT INTO events(job_id,state,at) VALUES (?, 'STAGING', ?)", (job_id, now()))
            return True

    def recovery_due(self, job_id: str, at: float) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT next_at FROM recovery WHERE job_id=?", (job_id,)).fetchone()
            return row is None or row[0] <= at

    def defer_recovery(self, job_id: str, at: float):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT failures FROM recovery WHERE job_id=?", (job_id,)).fetchone()
            count = (previous[0] if previous else 0) + 1
            delay = min(120, 30 * 2 ** min(count - 1, 2))
            db.execute("INSERT OR REPLACE INTO recovery VALUES (?, ?, ?)", (job_id, count, at + delay))
