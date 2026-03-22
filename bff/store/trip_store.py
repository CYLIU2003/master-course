from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, List, Optional, cast

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover - optional dependency
    pa = None
    pq = None


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


def parquet_available() -> bool:
    return pa is not None and pq is not None


def save_parquet_rows(path: Path, rows: List[Any]) -> None:
    if not parquet_available():
        save_json(path, rows)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pa_module = cast(Any, pa)
    pq_module = cast(Any, pq)
    table = pa_module.table(
        {
            "row_index": list(range(len(rows))),
            "payload_json": [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows],
        }
    )
    metadata = {
        b"schema_version": b"1",
        b"payload_format": b"json_row_envelope",
    }
    pq_module.write_table(table.replace_schema_metadata(metadata), path)


def count_parquet_rows(path: Path) -> int:
    if not path.exists():
        return 0
    if not parquet_available():
        payload = load_json(path, [])
        return len(payload) if isinstance(payload, list) else 0
    pq_module = cast(Any, pq)
    parquet_file = pq_module.ParquetFile(path)
    return int(parquet_file.metadata.num_rows or 0)


def page_parquet_rows(path: Path, *, offset: int = 0, limit: Optional[int] = None) -> List[Any]:
    if not path.exists():
        return []
    if not parquet_available():
        payload = load_json(path, [])
        if not isinstance(payload, list):
            return []
        items = payload[offset:] if limit is None else payload[offset : offset + limit]
        return [item for item in items]

    pq_module = cast(Any, pq)
    parquet_file = pq_module.ParquetFile(path)
    target_end = None if limit is None else offset + limit
    current_index = 0
    results: List[Any] = []
    for batch in parquet_file.iter_batches(columns=["payload_json"], batch_size=1024):
        batch_size = batch.num_rows
        batch_start = current_index
        batch_end = current_index + batch_size
        current_index = batch_end
        if batch_end <= offset:
            continue
        start_in_batch = max(offset - batch_start, 0)
        end_in_batch = batch_size if target_end is None else min(target_end - batch_start, batch_size)
        payloads = batch.column(0).to_pylist()[start_in_batch:end_in_batch]
        results.extend(json.loads(str(payload)) for payload in payloads)
        if target_end is not None and limit is not None and len(results) >= limit:
            break
    return results


def load_parquet_rows(path: Path) -> List[Any]:
    return page_parquet_rows(path, offset=0, limit=None)


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
    # Exclude __vN duplicate trips produced by GTFS reconciliation
    conditions = ["(json_extract(payload_json, '$.trip_id') IS NULL OR json_extract(payload_json, '$.trip_id') NOT GLOB '*__v[0-9]*')"]
    params: list[Any] = []
    if service_id:
        conditions.append("service_id = ?")
        params.append(service_id)
    sql = "SELECT payload_json FROM timetable_rows WHERE " + " AND ".join(conditions)
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
    # Exclude __vN duplicate trips produced by GTFS reconciliation
    conditions = ["(json_extract(payload_json, '$.trip_id') IS NULL OR json_extract(payload_json, '$.trip_id') NOT GLOB '*__v[0-9]*')"]
    params: list[Any] = []
    if service_id:
        conditions.append("service_id = ?")
        params.append(service_id)
    sql = "SELECT COUNT(*) AS n FROM timetable_rows WHERE " + " AND ".join(conditions)
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        row = conn.execute(sql, params).fetchone()
    return int(row["n"] or 0)


def summarize_timetable_routes(db_path: Path) -> List[dict[str, Any]]:
    if not db_path.exists():
        return []
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT route_id, service_id, COUNT(*) AS trip_count
            FROM timetable_rows
            WHERE (json_extract(payload_json, '$.trip_id') IS NULL
                   OR json_extract(payload_json, '$.trip_id') NOT GLOB '*__v[0-9]*')
            GROUP BY route_id, service_id
            ORDER BY route_id ASC, service_id ASC
            """
        ).fetchall()
    summaries: List[dict[str, Any]] = []
    for row in rows:
        route_id = str(row["route_id"] or "").strip()
        if not route_id:
            continue
        summaries.append(
            {
                "route_id": route_id,
                "service_id": str(row["service_id"] or "WEEKDAY"),
                "trip_count": int(row["trip_count"] or 0),
            }
        )
    return summaries


def summarize_timetable_routes_from_row_artifacts(db_path: Path) -> List[dict[str, Any]]:
    if not db_path.exists():
        return []

    summaries: List[dict[str, Any]] = []
    with closing(_connect(db_path)) as conn:
        _ensure_schema(conn)
        try:
            rows = conn.execute(
                """
                SELECT
                    json_extract(payload_json, '$.route_id') AS route_id,
                    COALESCE(json_extract(payload_json, '$.service_id'), 'WEEKDAY') AS service_id,
                    COUNT(*) AS trip_count
                FROM row_artifacts
                WHERE name = 'timetable_rows'
                  AND (json_extract(payload_json, '$.trip_id') IS NULL
                       OR json_extract(payload_json, '$.trip_id') NOT GLOB '*__v[0-9]*')
                GROUP BY route_id, service_id
                ORDER BY route_id ASC, service_id ASC
                """
            ).fetchall()
            for row in rows:
                route_id = str(row["route_id"] or "").strip()
                if not route_id:
                    continue
                summaries.append(
                    {
                        "route_id": route_id,
                        "service_id": str(row["service_id"] or "WEEKDAY"),
                        "trip_count": int(row["trip_count"] or 0),
                    }
                )
            return summaries
        except sqlite3.OperationalError:
            pass

    rows = load_rows(db_path, "timetable_rows")
    grouped: dict[tuple[str, str], int] = {}
    for item in rows:
        route_id = str((item or {}).get("route_id") or "").strip()
        if not route_id:
            continue
        trip_id = str((item or {}).get("trip_id") or "")
        if trip_id and "__v" in trip_id and any(c.isdigit() for c in trip_id.split("__v")[-1][:1]):
            continue  # Skip __vN GTFS reconciliation duplicates
        service_id = str((item or {}).get("service_id") or "WEEKDAY")
        key = (route_id, service_id)
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {
            "route_id": route_id,
            "service_id": service_id,
            "trip_count": count,
        }
        for (route_id, service_id), count in sorted(grouped.items())
    ]


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
