"""SQLite job store and per-person token file. Tokens are stored only as SHA-256 digests."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED", "LOST", "REJECTED"}
ACTIVE = {"STAGING", "RUNNING", "COLLECTING"}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Tokens:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def _read(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))["tokens"] if self.path.exists() else []

    def _write(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps({"tokens": rows}, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, name: str, admin: bool = False) -> str:
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("name must be letters, digits, - or _")
        with self.lock:
            rows = self._read()
            if any(r["name"] == name and not r["revoked"] for r in rows):
                raise ValueError("an active token with this name exists; revoke it first")
            token = "lab_" + secrets.token_urlsafe(32)
            rows.append({"name": name, "sha256": hashlib.sha256(token.encode()).hexdigest(), "admin": admin,
                         "created_at": now(), "revoked": False})
            self._write(rows)
        return token

    def revoke(self, name: str) -> int:
        with self.lock:
            rows = self._read()
            hit = [r for r in rows if r["name"] == name and not r["revoked"]]
            for row in hit:
                row["revoked"] = True
            self._write(rows)
        return len(hit)

    def list(self) -> list[dict]:
        return [{k: r[k] for k in ("name", "admin", "created_at", "revoked")} for r in self._read()]

    def authenticate(self, token: str | None) -> dict | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        found = None
        for row in self._read():  # no early exit: constant work per request
            if hmac.compare_digest(row["sha256"], digest) and not row["revoked"]:
                found = row
        return {"name": found["name"], "admin": found["admin"]} if found else None


class JobStore:
    COLUMNS = ("id", "owner", "name", "state", "message", "created_at", "updated_at", "entry", "args", "ram_gb",
               "threads", "time_limit_min", "machine", "idempotency_key", "bundle_path", "result_path",
               "exit_code", "started_at", "finished_at", "cancel_requested", "bundle_bytes")

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.lock, self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT, state TEXT NOT NULL,"
                       " message TEXT, created_at TEXT, updated_at TEXT, entry TEXT, args TEXT, ram_gb REAL, threads INTEGER,"
                       " time_limit_min INTEGER, machine TEXT, idempotency_key TEXT, bundle_path TEXT, result_path TEXT,"
                       " exit_code INTEGER, started_at TEXT, finished_at TEXT, cancel_requested INTEGER DEFAULT 0,"
                       " bundle_bytes INTEGER, seq INTEGER)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idem ON jobs(owner, idempotency_key) WHERE idempotency_key IS NOT NULL")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create(self, **fields) -> dict:
        job_id = fields.pop("id", None) or uuid.uuid4().hex[:12]
        with self.lock, self.connect() as db:
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM jobs").fetchone()[0]
            row = {"id": job_id, "state": "QUEUED", "created_at": now(), "updated_at": now(), "cancel_requested": 0, **fields}
            if isinstance(row.get("args"), (list, dict)):
                row["args"] = json.dumps(row["args"])
            names = list(row) + ["seq"]
            db.execute(f"INSERT INTO jobs ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
                       [row[k] for k in row] + [seq])
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._decode(row)

    @staticmethod
    def _decode(row) -> dict:
        data = {k: row[k] for k in JobStore.COLUMNS}
        data["args"] = json.loads(data["args"]) if data["args"] else []
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    def rows(self, *, owner: str | None = None, states: set[str] | None = None) -> list[dict]:
        query, params, clauses = "SELECT * FROM jobs", [], []
        if owner is not None:
            clauses.append("owner = ?")
            params.append(owner)
        if states:
            clauses.append(f"state IN ({','.join('?' * len(states))})")
            params += sorted(states)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connect() as db:
            return [self._decode(r) for r in db.execute(query + " ORDER BY seq", params)]

    def find_idempotent(self, owner: str, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE owner = ? AND idempotency_key = ?", (owner, key)).fetchone()
        return self._decode(row) if row else None

    def update(self, job_id: str, *, expected: set[str] | None = None, **fields) -> bool:
        fields["updated_at"] = now()
        sets = ",".join(f"{k} = ?" for k in fields)
        clause, extra = "", []
        if expected:
            clause = f" AND state IN ({','.join('?' * len(expected))})"
            extra = sorted(expected)
        with self.lock, self.connect() as db:
            cursor = db.execute(f"UPDATE jobs SET {sets} WHERE id = ?{clause}",
                                [int(v) if isinstance(v, bool) else v for v in fields.values()] + [job_id] + extra)
            return cursor.rowcount == 1
