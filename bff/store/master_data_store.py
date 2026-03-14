from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # Scenario artifact writes use staging dirs on Windows; DELETE avoids stray
    # -wal/-shm handles that can block staging cleanup during atomic replace.
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            name TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def load_master_data(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with closing(_connect(path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT name, payload_json FROM collections ORDER BY name ASC"
        ).fetchall()
    payload: Dict[str, Any] = {}
    for row in rows:
        payload[str(row["name"])] = json.loads(str(row["payload_json"]))
    return payload


def save_master_data(path: Path, payload: Dict[str, Any]) -> None:
    with closing(_connect(path)) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM collections")
        now = _now_iso()
        conn.executemany(
            "INSERT INTO collections(name, payload_json, updated_at) VALUES (?, ?, ?)",
            [
                (
                    key,
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                    now,
                )
                for key, value in payload.items()
            ],
        )
        conn.commit()
