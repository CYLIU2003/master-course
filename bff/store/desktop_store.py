"""Bounded read projections for the desktop UI; never changes research inputs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

import ijson

from bff.store import scenario_store, trip_store

MASTER_TABLES = frozenset({"routes", "depots", "vehicles", "stops", "chargers"})
ARTIFACT_TABLES = frozenset({"timetable_rows", "trips", "duties", "blocks"})
RESULT_PATHS = (
    "status",
    "solver_status",
    "feasible",
    "objective_value",
    "cost_breakdown",
    "mip_gap",
    "solution_validity",
    "result_class",
    "research_kpi_eligible",
    "prepared_input_id",
    "scenario_hash",
    "scope_hash",
    "final_accounting_source",
    "final_accounting_total_cost_jpy",
    "solver_metadata.research_git_provenance",
    "metadata.research_acceptance_status",
    "metadata.research_acceptance_checks",
    "metadata.physical_schedule_validation",
    "metadata.accounting_summary",
    "metadata.git_commit",
    "metadata.git_sha",
    "metadata.mip_gap",
    "metadata.fallback_used",
    "metadata.post_solve_repair_used",
    "metadata.rolling_hourly_chain_summary",
    "metadata.claim_scope",
)


def _context(scenario_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    # Reuse the scenario store's ref normalization (including moved workspaces).
    return scenario_store.get_desktop_context(scenario_id)


def _read_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


@lru_cache(maxsize=256)
def _metadata(path: str, modified_ns: int, size: int) -> dict[str, Any]:
    del modified_ns, size  # Cache identity includes atomic replacements.
    with open(path, "rb") as source:
        meta = next(ijson.items(source, "meta"), {})
    if (
        not isinstance(meta, dict)
        or not isinstance(meta.get("id"), str)
        or not isinstance(meta.get("name"), str)
    ):
        raise ValueError("Invalid scenario metadata")
    return {
        key: meta.get(key)
        for key in ("id", "name", "description", "status", "updatedAt", "operatorId")
    }


def scenario_page(query: str, offset: int, limit: int) -> dict[str, Any]:
    items, errors = [], []
    for path in scenario_store.scenario_metadata_paths():
        try:
            stat = path.stat()
            meta = _metadata(str(path), stat.st_mtime_ns, stat.st_size)
            if (
                meta.get("id")
                and query.casefold() in str(meta.get("name") or "").casefold()
            ):
                items.append(meta)
        except (OSError, ValueError, ijson.JSONError) as exc:
            errors.append(f"{path.stem}: {type(exc).__name__}")
    items.sort(
        key=lambda row: (str(row.get("updatedAt") or ""), str(row["id"])), reverse=True
    )
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "warnings": errors[:20],
    }


def collection(scenario_id: str, name: str) -> Any:
    meta, refs = _context(scenario_id)
    path = Path(refs["masterData"])
    if path.exists():
        with closing(_read_connection(path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM collections WHERE name = ?", (name,)
            ).fetchone()
        if row is not None:
            return json.loads(row[0])
    return meta.get(name)


def _indexed_timetable_page(
    path: Path, offset: int, limit: int, service_id: str | None
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with closing(_read_connection(path)) as conn:
        conn.execute("BEGIN")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'timetable_rows'"
            ).fetchone()
            is None
        ):
            return None
        visible = trip_store.TIMETABLE_VISIBLE_FILTER
        condition = visible + (" AND service_id = ?" if service_id else "")
        params = [service_id] if service_id else []
        total = conn.execute(
            "SELECT COUNT(*) FROM timetable_rows WHERE " + condition, params
        ).fetchone()[0]
        if (
            not total
            and conn.execute(
                "SELECT 1 FROM timetable_rows WHERE " + visible + " LIMIT 1"
            ).fetchone()
            is None
        ):
            return None
        rows = conn.execute(
            "SELECT payload_json FROM timetable_rows WHERE "
            + condition
            + " ORDER BY row_index LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return {
        "items": [json.loads(row[0]) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def table_page(
    scenario_id: str, name: str, offset: int, limit: int, service_id: str | None = None
) -> dict[str, Any]:
    meta, refs = _context(scenario_id)
    if name == "timetable_rows":
        indexed = _indexed_timetable_page(
            Path(refs["artifactStore"]), offset, limit, service_id
        )
        if indexed is not None:
            return indexed
        total = scenario_store.count_timetable_rows(scenario_id, service_id=service_id)
        items = scenario_store.page_timetable_rows(
            scenario_id, offset=offset, limit=limit, service_id=service_id
        )
    elif name in ARTIFACT_TABLES:
        total = scenario_store.count_field_rows(scenario_id, name)
        items = scenario_store.page_field_rows(
            scenario_id, name, offset=offset, limit=limit
        )
    elif name in MASTER_TABLES:
        path = Path(refs["masterData"])
        if path.exists():
            with closing(_read_connection(path)) as conn:
                total_row = conn.execute(
                    "SELECT json_array_length(payload_json) FROM collections WHERE name = ?",
                    (name,),
                ).fetchone()
                total = int(total_row[0] or 0) if total_row else 0
                rows = conn.execute(
                    "SELECT j.value FROM collections c, json_each(c.payload_json) j WHERE c.name = ? ORDER BY CAST(j.key AS INTEGER) LIMIT ? OFFSET ?",
                    (name, limit, offset),
                ).fetchall()
                items = [json.loads(row[0]) for row in rows]
        else:
            rows = meta.get(name) or []
            total, items = len(rows), rows[offset : offset + limit]
    else:
        raise ValueError("Unsupported desktop table")
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def _stream_projection(source: BinaryIO) -> dict[str, Any]:
    # Event projection skips large trajectories/allocations in constant parser memory.
    from ijson.common import ObjectBuilder

    result: dict[str, Any] = {}
    builder = None
    root = ""
    depth = 0
    projected_events = 0
    for prefix, event, value in ijson.parse(source, use_float=True):
        if builder is not None:
            projected_events += 1
            if projected_events > 10_000:
                raise ValueError(
                    "Result summary exceeds the desktop bound; inspect the saved result artifact"
                )
            builder.event(event, value)
            depth += int(event in {"start_map", "start_array"}) - int(
                event in {"end_map", "end_array"}
            )
            if depth == 0:
                result[root] = builder.value
                builder = None
        elif prefix in RESULT_PATHS:
            if event in {"start_map", "start_array"}:
                builder, root, depth = ObjectBuilder(), prefix, 1
                builder.event(event, value)
            elif event in {"string", "number", "boolean", "null"}:
                result[prefix] = value
    return result


def _json_projection(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return _stream_projection(source)


@lru_cache(maxsize=32)
def _cached_projection(
    path: str, modified_ns: int, size: int, sqlite: bool
) -> dict[str, Any] | None:
    del modified_ns, size
    if not sqlite:
        return _json_projection(Path(path))
    with closing(_read_connection(Path(path))) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scalar_artifacts'"
            ).fetchone()
            is None
        ):
            return None
        row = conn.execute(
            "SELECT rowid FROM scalar_artifacts WHERE name = 'optimization_result'"
        ).fetchone()
        if row is None:
            return None
        # TEXT blobs expose UTF-8 bytes too. No Python allocation of the full
        # solver JSON, and no repeated SQLite JSON extraction of large values.
        with conn.blobopen(
            "scalar_artifacts", "payload_json", row[0], readonly=True
        ) as source:
            return _stream_projection(source)


def result_summary(scenario_id: str) -> dict[str, Any]:
    _, refs = _context(scenario_id)
    path = Path(refs["artifactStore"])
    if path.exists():
        stat = path.stat()
        result = _cached_projection(str(path), stat.st_mtime_ns, stat.st_size, True)
        if result:
            return {
                "available": True,
                "source": "optimization_result",
                "values": result,
            }
    json_path = Path(refs["optimizationResult"])
    if json_path.exists():
        stat = json_path.stat()
        result = _cached_projection(
            str(json_path), stat.st_mtime_ns, stat.st_size, False
        )
        if result:
            return {
                "available": True,
                "source": "optimization_result",
                "values": result,
            }
    return {"available": False, "source": None, "values": {}}
