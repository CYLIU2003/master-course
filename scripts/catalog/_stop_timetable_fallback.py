from __future__ import annotations

import sqlite3
from collections.abc import Iterable


SYNTHETIC_STOP_TIMETABLE_NOTE = "synthetic_from_trip_stops"


def _pattern_ids_list(pattern_ids: Iterable[str] | None) -> list[str]:
    resolved: list[str] = []
    for pattern_id in pattern_ids or ():
        value = str(pattern_id or "").strip()
        if value and value not in resolved:
            resolved.append(value)
    return resolved


def delete_synthetic_stop_timetables(
    conn: sqlite3.Connection,
    *,
    pattern_ids: Iterable[str] | None = None,
) -> int:
    resolved_pattern_ids = _pattern_ids_list(pattern_ids)
    params: list[object] = [SYNTHETIC_STOP_TIMETABLE_NOTE]
    where = "WHERE note = ?"
    if resolved_pattern_ids:
        placeholders = ",".join("?" for _ in resolved_pattern_ids)
        where += f" AND pattern_id IN ({placeholders})"
        params.extend(resolved_pattern_ids)
    cur = conn.execute(f"DELETE FROM stop_timetables {where}", params)
    return int(cur.rowcount or 0)


def synthesize_missing_stop_timetables(
    conn: sqlite3.Connection,
    *,
    pattern_ids: Iterable[str] | None = None,
) -> dict[str, int]:
    resolved_pattern_ids = _pattern_ids_list(pattern_ids)
    scoped_params: list[object] = []
    pattern_filter = ""
    if resolved_pattern_ids:
        placeholders = ",".join("?" for _ in resolved_pattern_ids)
        pattern_filter = f" AND tt.pattern_id IN ({placeholders})"
        scoped_params.extend(resolved_pattern_ids)

    missing_patterns = [
        str(row[0])
        for row in conn.execute(
            f"""
            SELECT DISTINCT tt.pattern_id
            FROM timetable_trips tt
            WHERE tt.pattern_id IS NOT NULL
              AND tt.pattern_id <> ''
              {pattern_filter}
              AND NOT EXISTS (
                  SELECT 1
                  FROM stop_timetables st
                  WHERE st.pattern_id = tt.pattern_id
              )
            """,
            scoped_params,
        ).fetchall()
        if str(row[0] or "")
    ]
    if not missing_patterns:
        return {"patterns": 0, "entries": 0}

    delete_synthetic_stop_timetables(conn, pattern_ids=missing_patterns)

    placeholders = ",".join("?" for _ in missing_patterns)
    rows = conn.execute(
        f"""
        SELECT
            ts.stop_id,
            tt.pattern_id,
            tt.calendar_type,
            tt.direction,
            COALESCE(ts.departure_hhmm, ts.arrival_hhmm, '') AS departure_hhmm,
            COALESCE(ts.dep_min, ts.arr_min) AS dep_min
        FROM trip_stops ts
        JOIN timetable_trips tt ON tt.trip_id = ts.trip_id
        WHERE tt.pattern_id IN ({placeholders})
          AND ts.stop_id IS NOT NULL
          AND ts.stop_id <> ''
          AND COALESCE(ts.departure_hhmm, ts.arrival_hhmm, '') <> ''
        ORDER BY tt.pattern_id, tt.calendar_type, tt.direction, ts.stop_id, dep_min, departure_hhmm
        """,
        missing_patterns,
    ).fetchall()
    if not rows:
        return {"patterns": len(missing_patterns), "entries": 0}

    conn.executemany(
        """
        INSERT INTO stop_timetables
            (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(row[0] or ""),
                str(row[1] or ""),
                str(row[2] or ""),
                str(row[3] or ""),
                str(row[4] or ""),
                row[5],
                SYNTHETIC_STOP_TIMETABLE_NOTE,
            )
            for row in rows
        ],
    )
    return {"patterns": len(missing_patterns), "entries": len(rows)}
