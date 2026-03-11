from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scalar_artifacts (
            name TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS row_artifacts (
            name TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (name, row_index)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_row_artifacts_name ON row_artifacts(name, row_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS timetable_rows (
            row_index INTEGER PRIMARY KEY,
            service_id TEXT,
            route_id TEXT,
            departure TEXT,
            arrival TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timetable_rows_service ON timetable_rows(service_id, row_index)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timetable_rows_route ON timetable_rows(route_id, row_index)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_arcs (
            row_index INTEGER PRIMARY KEY,
            reason_code TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_arcs_reason ON graph_arcs(reason_code, row_index)"
    )
    conn.commit()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def save_scalar(db_path: Path, name: str, value: Any) -> None:
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM scalar_artifacts WHERE name = ?", (name,))
        conn.execute(
            "INSERT INTO scalar_artifacts(name, payload_json) VALUES (?, ?)",
            (name, json.dumps(value, ensure_ascii=False, separators=(",", ":"))),
        )
        conn.commit()


def load_scalar(db_path: Path, name: str, default: Any = None) -> Any:
    if not db_path.exists():
        return default
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT payload_json FROM scalar_artifacts WHERE name = ?",
            (name,),
        ).fetchone()
    if row is None:
        return default
    return json.loads(str(row["payload_json"]))


def save_rows(db_path: Path, name: str, rows: List[Any]) -> None:
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM row_artifacts WHERE name = ?", (name,))
        conn.executemany(
            "INSERT INTO row_artifacts(name, row_index, payload_json) VALUES (?, ?, ?)",
            [
                (
                    name,
                    index,
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                )
                for index, row in enumerate(rows)
            ],
        )
        conn.commit()


def load_rows(db_path: Path, name: str) -> List[Any]:
    if not db_path.exists():
        return []
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT payload_json FROM row_artifacts WHERE name = ? ORDER BY row_index ASC",
            (name,),
        ).fetchall()
    return [json.loads(str(row["payload_json"])) for row in rows]


def page_rows(db_path: Path, name: str, *, offset: int = 0, limit: Optional[int] = None) -> List[Any]:
    if not db_path.exists():
        return []
    sql = "SELECT payload_json FROM row_artifacts WHERE name = ? ORDER BY row_index ASC"
    params: list[Any] = [name]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(str(row["payload_json"])) for row in rows]


def count_rows(db_path: Path, name: str) -> int:
    if not db_path.exists():
        return 0
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM row_artifacts WHERE name = ?",
            (name,),
        ).fetchone()
    return int(row["n"] or 0)


def save_timetable_rows(db_path: Path, rows: List[Any]) -> None:
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM timetable_rows")
        conn.executemany(
            "INSERT INTO timetable_rows(row_index, service_id, route_id, departure, arrival, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    index,
                    str((row or {}).get("service_id") or "WEEKDAY"),
                    str((row or {}).get("route_id") or ""),
                    (row or {}).get("departure"),
                    (row or {}).get("arrival"),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                )
                for index, row in enumerate(rows)
            ],
        )
        conn.commit()


def page_timetable_rows(
    db_path: Path,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
    service_id: Optional[str] = None,
) -> List[Any]:
    if not db_path.exists():
        return []
    sql = "SELECT payload_json FROM timetable_rows"
    params: list[Any] = []
    if service_id:
        sql += " WHERE service_id = ?"
        params.append(service_id)
    sql += " ORDER BY row_index ASC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(str(row["payload_json"])) for row in rows]


def count_timetable_rows(db_path: Path, *, service_id: Optional[str] = None) -> int:
    if not db_path.exists():
        return 0
    sql = "SELECT COUNT(*) AS n FROM timetable_rows"
    params: list[Any] = []
    if service_id:
        sql += " WHERE service_id = ?"
        params.append(service_id)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        row = conn.execute(sql, params).fetchone()
    return int(row["n"] or 0)


def save_graph_arcs(db_path: Path, rows: List[Any]) -> None:
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM graph_arcs")
        conn.executemany(
            "INSERT INTO graph_arcs(row_index, reason_code, payload_json) VALUES (?, ?, ?)",
            [
                (
                    index,
                    str((row or {}).get("reason_code") or ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                )
                for index, row in enumerate(rows)
            ],
        )
        conn.commit()


def load_graph_arcs(db_path: Path) -> List[Any]:
    return page_graph_arcs(db_path, offset=0, limit=None)


def page_graph_arcs(
    db_path: Path,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
    reason_code: Optional[str] = None,
) -> List[Any]:
    if not db_path.exists():
        return []
    sql = "SELECT payload_json FROM graph_arcs"
    params: list[Any] = []
    if reason_code:
        sql += " WHERE reason_code = ?"
        params.append(reason_code)
    sql += " ORDER BY row_index ASC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(str(row["payload_json"])) for row in rows]


def count_graph_arcs(db_path: Path, *, reason_code: Optional[str] = None) -> int:
    if not db_path.exists():
        return 0
    sql = "SELECT COUNT(*) AS n FROM graph_arcs"
    params: list[Any] = []
    if reason_code:
        sql += " WHERE reason_code = ?"
        params.append(reason_code)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        row = conn.execute(sql, params).fetchone()
    return int(row["n"] or 0)
