"""Stable submission identity survives HTTP retries and controller restarts."""
from __future__ import annotations

import uuid

from .contracts import canonical, digest, segment
from .store import JobStore


def claim_submission(store: JobStore, key: str, payload: dict) -> str:
    segment(key)
    fingerprint = digest(canonical(payload))
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS submissions (key TEXT PRIMARY KEY, digest TEXT NOT NULL, job_id TEXT UNIQUE NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT digest,job_id FROM submissions WHERE key=?", (key,)).fetchone()
        if row:
            if row["digest"] != fingerprint:
                raise ValueError("IDEMPOTENCY_CONFLICT: submission key has different inputs")
            return row["job_id"]
        job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "master-course-cluster:" + key))
        db.execute("INSERT INTO submissions VALUES (?, ?, ?)", (key, fingerprint, job_id))
        return job_id
