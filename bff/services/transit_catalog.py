from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bff.services.gtfs_import import (
    DEFAULT_GTFS_FEED_PATH,
    build_gtfs_route_timetables,
    build_gtfs_stop_timetables,
    gtfs_feed_signature,
    load_gtfs_core_bundle,
    resolve_gtfs_feed_path,
)
from bff.services.odpt_routes import (
    DEFAULT_OPERATOR,
    build_routes_from_operational,
    fetch_operational_dataset,
)
from bff.services.odpt_stop_timetables import build_stop_timetables_from_normalized
from bff.services.odpt_stops import build_stops_from_normalized
from bff.services.odpt_timetable import (
    build_timetable_rows_from_operational,
    normalize_timetable_row_indexes,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DB_PATH_DEFAULT = _REPO_ROOT / "outputs" / "transit_catalog.sqlite"
_ODPT_SAVED_SNAPSHOT_DIR_DEFAULT = _REPO_ROOT / "data" / "odpt" / "tokyu"

_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
    "calendar_entries",
    "calendar_date_entries",
)
_ODPT_REQUIRED_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
)
_GTFS_REQUIRED_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
    "calendar_entries",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _catalog_db_path() -> Path:
    configured = os.environ.get("TRANSIT_CATALOG_DB_PATH")
    if configured:
        return _resolve_repo_path(configured)
    return _CATALOG_DB_PATH_DEFAULT


def _odpt_saved_snapshot_dir(operator: str) -> Optional[Path]:
    configured = os.environ.get("ODPT_SNAPSHOT_DIR")
    if configured:
        return _resolve_repo_path(configured)
    if operator == DEFAULT_OPERATOR:
        return _ODPT_SAVED_SNAPSHOT_DIR_DEFAULT
    return None


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    db_path = _catalog_db_path()
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_snapshots (
            snapshot_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            dataset_ref TEXT NOT NULL,
            signature TEXT,
            generated_at TEXT,
            refreshed_at TEXT NOT NULL,
            meta_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog_entities (
            snapshot_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_key, entity_type, entity_id),
            FOREIGN KEY (snapshot_key) REFERENCES catalog_snapshots(snapshot_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_entities_lookup
            ON catalog_entities(snapshot_key, entity_type, sort_key);

        CREATE TABLE IF NOT EXISTS catalog_route_payloads (
            snapshot_key TEXT NOT NULL,
            route_id TEXT NOT NULL,
            route_code TEXT NOT NULL,
            route_label TEXT NOT NULL,
            trip_count INTEGER NOT NULL DEFAULT 0,
            first_departure TEXT,
            last_arrival TEXT,
            services_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_key, route_id),
            FOREIGN KEY (snapshot_key) REFERENCES catalog_snapshots(snapshot_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_route_payloads_lookup
            ON catalog_route_payloads(snapshot_key, route_code, route_label);
        """
    )
    conn.commit()


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _deserialize(value: str | bytes | bytearray | None) -> Any:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    return json.loads(value)


def _read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        return None
    return payload


def _file_signature(paths: Iterable[Path]) -> str:
    signature: List[tuple[str, int, int]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        stat = path.stat()
        signature.append((path.name, stat.st_mtime_ns, stat.st_size))
    return _serialize(signature)


def _normalize_snapshot_key(source: str, dataset_ref: str) -> str:
    return f"{source}::{dataset_ref}"


def _entity_id(entity_type: str, item: Dict[str, Any], index: int) -> str:
    if entity_type in {"stops", "routes", "stop_timetables"}:
        candidate = item.get("id")
        if candidate:
            return str(candidate)
    if entity_type == "timetable_rows":
        candidate = item.get("trip_id")
        if candidate:
            return str(candidate)
        return "|".join(
            [
                str(item.get("route_id") or ""),
                str(item.get("service_id") or ""),
                str(item.get("direction") or ""),
                str(item.get("trip_index") or index),
                str(item.get("departure") or ""),
                str(item.get("arrival") or ""),
            ]
        )
    if entity_type == "calendar_entries":
        candidate = item.get("service_id")
        if candidate:
            return str(candidate)
    if entity_type == "calendar_date_entries":
        return "|".join(
            [
                str(item.get("date") or ""),
                str(item.get("service_id") or ""),
                str(item.get("exception_type") or ""),
            ]
        )
    return f"{entity_type}:{index}"


def _sort_key(entity_type: str, item: Dict[str, Any], index: int) -> str:
    if entity_type == "stops":
        return str(item.get("name") or item.get("id") or index)
    if entity_type == "routes":
        return str(
            item.get("routeCode")
            or item.get("route_code")
            or item.get("name")
            or item.get("id")
            or index
        )
    if entity_type == "timetable_rows":
        return "|".join(
            [
                str(item.get("service_id") or ""),
                str(item.get("route_id") or ""),
                str(item.get("direction") or ""),
                str(item.get("departure") or ""),
                str(item.get("arrival") or ""),
                str(item.get("trip_id") or index),
            ]
        )
    if entity_type == "stop_timetables":
        return "|".join(
            [
                str(item.get("stopName") or ""),
                str(item.get("service_id") or ""),
                str(item.get("id") or index),
            ]
        )
    if entity_type == "calendar_entries":
        return str(item.get("service_id") or index)
    if entity_type == "calendar_date_entries":
        return "|".join(
            [
                str(item.get("date") or ""),
                str(item.get("service_id") or ""),
                str(item.get("exception_type") or ""),
            ]
        )
    return f"{index:08d}"


def _route_payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "route_id": str(payload.get("route_id") or ""),
        "route_code": str(payload.get("route_code") or payload.get("route_id") or ""),
        "route_label": str(payload.get("route_label") or payload.get("route_code") or ""),
        "trip_count": int(payload.get("trip_count") or 0),
        "first_departure": payload.get("first_departure"),
        "last_arrival": payload.get("last_arrival"),
        "services": list(payload.get("services") or []),
    }


def _canonicalize_odpt_route_payloads(
    payloads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in payloads:
        route_id = str(payload.get("busroute_id") or payload.get("route_id") or "")
        if not route_id:
            continue
        items.append(
            {
                "route_id": route_id,
                "route_code": str(payload.get("route_code") or route_id),
                "route_label": str(payload.get("route_label") or payload.get("route_code") or route_id),
                "trip_count": int(payload.get("trip_count") or 0),
                "first_departure": payload.get("first_departure"),
                "last_arrival": payload.get("last_arrival"),
                "patterns": list(payload.get("patterns") or []),
                "services": list(payload.get("services") or []),
                "trips": list(payload.get("trips") or []),
                "source": "odpt",
            }
        )
    return items


def _replace_snapshot(
    *,
    snapshot_key: str,
    source: str,
    dataset_ref: str,
    signature: str,
    meta: Dict[str, Any],
    entities: Dict[str, List[Dict[str, Any]]],
    route_payloads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM catalog_entities WHERE snapshot_key = ?", (snapshot_key,))
        conn.execute(
            "DELETE FROM catalog_route_payloads WHERE snapshot_key = ?", (snapshot_key,)
        )
        conn.execute(
            """
            INSERT INTO catalog_snapshots (
                snapshot_key,
                source,
                dataset_ref,
                signature,
                generated_at,
                refreshed_at,
                meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_key) DO UPDATE SET
                source = excluded.source,
                dataset_ref = excluded.dataset_ref,
                signature = excluded.signature,
                generated_at = excluded.generated_at,
                refreshed_at = excluded.refreshed_at,
                meta_json = excluded.meta_json
            """,
            (
                snapshot_key,
                source,
                dataset_ref,
                signature,
                meta.get("generatedAt"),
                meta.get("refreshedAt") or _now_iso(),
                _serialize(meta),
            ),
        )

        for entity_type, items in entities.items():
            deduped: Dict[str, tuple[str, str, str, str, str]] = {}
            for index, item in enumerate(items):
                entity_id = _entity_id(entity_type, item, index)
                deduped[entity_id] = (
                    snapshot_key,
                    entity_type,
                    entity_id,
                    _sort_key(entity_type, item, index),
                    _serialize(item),
                )
            rows = list(deduped.values())
            conn.executemany(
                """
                INSERT INTO catalog_entities (
                    snapshot_key,
                    entity_type,
                    entity_id,
                    sort_key,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

        route_rows = []
        for payload in route_payloads:
            summary = _route_payload_summary(payload)
            route_rows.append(
                (
                    snapshot_key,
                    summary["route_id"],
                    summary["route_code"],
                    summary["route_label"],
                    summary["trip_count"],
                    summary.get("first_departure"),
                    summary.get("last_arrival"),
                    _serialize(summary.get("services") or []),
                    _serialize(payload),
                )
            )
        conn.executemany(
            """
            INSERT INTO catalog_route_payloads (
                snapshot_key,
                route_id,
                route_code,
                route_label,
                trip_count,
                first_departure,
                last_arrival,
                services_json,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            route_rows,
        )
        conn.commit()
    return get_snapshot(snapshot_key) or {}


def _load_entities(snapshot_key: str, entity_type: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM catalog_entities
            WHERE snapshot_key = ? AND entity_type = ?
            ORDER BY sort_key ASC, entity_id ASC
            """,
            (snapshot_key, entity_type),
        ).fetchall()
    return [dict(_deserialize(row["payload_json"]) or {}) for row in rows]


def _has_snapshot_payload(snapshot_key: str, required_entity_types: Iterable[str]) -> bool:
    with _connect() as conn:
        _ensure_schema(conn)
        for entity_type in required_entity_types:
            count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM catalog_entities
                WHERE snapshot_key = ? AND entity_type = ?
                """,
                (snapshot_key, entity_type),
            ).fetchone()["n"]
            if int(count or 0) == 0:
                return False
        route_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM catalog_route_payloads
            WHERE snapshot_key = ?
            """,
            (snapshot_key,),
        ).fetchone()["n"]
    return int(route_count or 0) > 0


def list_snapshots() -> List[Dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT snapshot_key, source, dataset_ref, signature, generated_at, refreshed_at, meta_json
            FROM catalog_snapshots
            ORDER BY refreshed_at DESC, snapshot_key ASC
            """
        ).fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        meta = dict(_deserialize(row["meta_json"]) or {})
        items.append(
            {
                "snapshotKey": row["snapshot_key"],
                "source": row["source"],
                "datasetRef": row["dataset_ref"],
                "signature": row["signature"],
                "generatedAt": row["generated_at"],
                "refreshedAt": row["refreshed_at"],
                "meta": meta,
            }
        )
    return items


def get_snapshot(snapshot_key: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT snapshot_key, source, dataset_ref, signature, generated_at, refreshed_at, meta_json
            FROM catalog_snapshots
            WHERE snapshot_key = ?
            """,
            (snapshot_key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "snapshotKey": row["snapshot_key"],
        "source": row["source"],
        "datasetRef": row["dataset_ref"],
        "signature": row["signature"],
        "generatedAt": row["generated_at"],
        "refreshedAt": row["refreshed_at"],
        "meta": dict(_deserialize(row["meta_json"]) or {}),
    }


def load_snapshot_bundle(snapshot_key: str) -> Dict[str, Any]:
    snapshot = get_snapshot(snapshot_key)
    if snapshot is None:
        raise KeyError(snapshot_key)
    return {
        "snapshot": snapshot,
        "meta": dict(snapshot.get("meta") or {}),
        "stops": _load_entities(snapshot_key, "stops"),
        "routes": _load_entities(snapshot_key, "routes"),
        "timetable_rows": _load_entities(snapshot_key, "timetable_rows"),
        "stop_timetables": _load_entities(snapshot_key, "stop_timetables"),
        "calendar_entries": _load_entities(snapshot_key, "calendar_entries"),
        "calendar_date_entries": _load_entities(snapshot_key, "calendar_date_entries"),
    }


def list_route_payload_summaries(snapshot_key: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT route_id, route_code, route_label, trip_count, first_departure, last_arrival, services_json
            FROM catalog_route_payloads
            WHERE snapshot_key = ?
            ORDER BY route_code ASC, route_label ASC, route_id ASC
            """,
            (snapshot_key,),
        ).fetchall()

    return [
        {
            "route_id": row["route_id"],
            "route_code": row["route_code"],
            "route_label": row["route_label"],
            "trip_count": int(row["trip_count"] or 0),
            "first_departure": row["first_departure"],
            "last_arrival": row["last_arrival"],
            "services": list(_deserialize(row["services_json"]) or []),
        }
        for row in rows
    ]


def get_route_payload(snapshot_key: str, route_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM catalog_route_payloads
            WHERE snapshot_key = ? AND route_id = ?
            """,
            (snapshot_key, route_id),
        ).fetchone()
    if row is None:
        return None
    return dict(_deserialize(row["payload_json"]) or {})


def _odpt_snapshot_key(operator: str) -> str:
    return _normalize_snapshot_key("odpt", operator)


def _gtfs_dataset_ref(feed_path: str | Path) -> str:
    feed_root = resolve_gtfs_feed_path(feed_path)
    try:
        return str(feed_root.relative_to(_REPO_ROOT))
    except ValueError:
        return str(feed_root)


def _gtfs_snapshot_key(feed_path: str | Path) -> str:
    return _normalize_snapshot_key("gtfs", _gtfs_dataset_ref(feed_path))


def _load_saved_odpt_snapshot(operator: str) -> Optional[Dict[str, Any]]:
    snapshot_dir = _odpt_saved_snapshot_dir(operator)
    if snapshot_dir is None:
        return None

    operational_path = snapshot_dir / "operational_dataset.json"
    operational_dataset = _read_json_object(operational_path)
    if operational_dataset is None:
        return None

    route_payloads = operational_dataset.get("routeTimetables")
    route_timetables_path = snapshot_dir / "route_timetables_dataset.json"
    if not isinstance(route_payloads, list):
        route_timetable_dataset = _read_json_object(route_timetables_path)
        route_items = (
            route_timetable_dataset.get("items") if route_timetable_dataset else None
        )
        route_payloads = route_items if isinstance(route_items, list) else []

    return {
        "dataset": operational_dataset,
        "route_payloads": list(route_payloads or []),
        "signature": _file_signature([operational_path, route_timetables_path]),
        "snapshot_dir": str(snapshot_dir),
    }


def _store_odpt_snapshot(
    *,
    operator: str,
    dataset: Dict[str, Any],
    route_payloads: Iterable[Dict[str, Any]],
    signature: str,
    requested_dump: bool,
    effective_dump: bool,
    snapshot_source: str,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dataset_meta = dict(dataset.get("meta") or {})
    stops = build_stops_from_normalized(dataset)
    routes = build_routes_from_operational(dataset)
    timetable_rows = normalize_timetable_row_indexes(
        build_timetable_rows_from_operational(dataset)
    )
    stop_timetables = build_stop_timetables_from_normalized(dataset)
    canonical_route_payloads = _canonicalize_odpt_route_payloads(route_payloads)

    merged_meta = dict(extra_meta or {})
    extra_warnings = list(merged_meta.pop("warnings", []) or [])
    warnings = list(dict.fromkeys(list(dataset_meta.get("warnings") or []) + extra_warnings))

    meta = {
        "source": "odpt",
        "datasetRef": operator,
        "operator": operator,
        "dump": effective_dump,
        "requestedDump": requested_dump,
        "effectiveDump": effective_dump,
        "generatedAt": dataset_meta.get("generatedAt"),
        "refreshedAt": _now_iso(),
        "warnings": warnings,
        "cache": dict(dataset_meta.get("cache") or {}),
        "snapshotSource": snapshot_source,
        "counts": {
            "stops": len(stops),
            "routes": len(routes),
            "timetableRows": len(timetable_rows),
            "stopTimetables": len(stop_timetables),
            "routePayloads": len(canonical_route_payloads),
        },
    }
    meta.update(merged_meta)

    return _replace_snapshot(
        snapshot_key=_odpt_snapshot_key(operator),
        source="odpt",
        dataset_ref=operator,
        signature=signature,
        meta=meta,
        entities={
            "stops": stops,
            "routes": routes,
            "timetable_rows": timetable_rows,
            "stop_timetables": stop_timetables,
            "calendar_entries": [],
            "calendar_date_entries": [],
        },
        route_payloads=canonical_route_payloads,
    )


def bootstrap_odpt_snapshot_from_saved(
    *,
    operator: str = DEFAULT_OPERATOR,
) -> Optional[Dict[str, Any]]:
    saved = _load_saved_odpt_snapshot(operator)
    if saved is None:
        return None

    return _store_odpt_snapshot(
        operator=operator,
        dataset=dict(saved.get("dataset") or {}),
        route_payloads=list(saved.get("route_payloads") or []),
        signature=str(saved.get("signature") or operator),
        requested_dump=True,
        effective_dump=True,
        snapshot_source="saved-json",
        extra_meta={
            "snapshotDir": saved.get("snapshot_dir"),
            "warnings": [
                "Catalog bootstrapped from saved ODPT operational_dataset.json."
            ],
        },
    )


def refresh_odpt_snapshot(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
) -> Dict[str, Any]:
    effective_dump = True
    dataset = fetch_operational_dataset(
        operator=operator,
        dump=effective_dump,
        force_refresh=force_refresh,
        ttl_sec=ttl_sec,
        include_bus_timetables=True,
        include_stop_timetables=True,
    )
    signature = _serialize(
        {
            "operator": operator,
            "generatedAt": (dataset.get("meta") or {}).get("generatedAt"),
            "effectiveDump": effective_dump,
        }
    )
    warnings: List[str] = []
    if not dump:
        warnings.append(
            "Catalog refresh always uses dump=1 to keep a complete ODPT snapshot."
        )

    return _store_odpt_snapshot(
        operator=operator,
        dataset=dataset,
        route_payloads=dataset.get("routeTimetables") or [],
        signature=signature,
        requested_dump=dump,
        effective_dump=effective_dump,
        snapshot_source="remote",
        extra_meta={"warnings": warnings},
    )


def get_or_refresh_odpt_snapshot(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
) -> Dict[str, Any]:
    snapshot_key = _odpt_snapshot_key(operator)
    snapshot = get_snapshot(snapshot_key)
    if (
        not force_refresh
        and snapshot is not None
        and _has_snapshot_payload(snapshot_key, _ODPT_REQUIRED_ENTITY_TYPES)
    ):
        bundle = load_snapshot_bundle(snapshot_key)
        bundle["meta"]["snapshotMode"] = "catalog"
        return bundle

    if not force_refresh:
        bootstrapped = bootstrap_odpt_snapshot_from_saved(operator=operator)
        if bootstrapped is not None:
            bundle = load_snapshot_bundle(bootstrapped["snapshotKey"])
            bundle["meta"]["snapshotMode"] = "saved-json"
            return bundle

    refreshed = refresh_odpt_snapshot(
        operator=operator,
        dump=dump,
        force_refresh=force_refresh,
        ttl_sec=ttl_sec,
    )
    bundle = load_snapshot_bundle(refreshed["snapshotKey"])
    bundle["meta"]["snapshotMode"] = "refreshed"
    return bundle


def refresh_gtfs_snapshot(
    *,
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
) -> Dict[str, Any]:
    dataset_ref = _gtfs_dataset_ref(feed_path)
    signature = _serialize(gtfs_feed_signature(feed_path))
    core = load_gtfs_core_bundle(feed_path)
    stop_bundle = build_gtfs_stop_timetables(feed_path)
    route_bundle = build_gtfs_route_timetables(feed_path)
    meta = {
        **dict(core.get("meta") or {}),
        "source": "gtfs",
        "datasetRef": dataset_ref,
        "signature": signature,
        "refreshedAt": _now_iso(),
        "counts": {
            "stops": len(list(core.get("stops") or [])),
            "routes": len(list(core.get("routes") or [])),
            "timetableRows": len(list(core.get("timetable_rows") or [])),
            "stopTimetables": len(list(stop_bundle.get("stop_timetables") or [])),
            "routePayloads": len(list(route_bundle.get("route_timetables") or [])),
        },
    }
    return _replace_snapshot(
        snapshot_key=_gtfs_snapshot_key(feed_path),
        source="gtfs",
        dataset_ref=dataset_ref,
        signature=signature,
        meta=meta,
        entities={
            "stops": list(core.get("stops") or []),
            "routes": list(core.get("routes") or []),
            "timetable_rows": list(core.get("timetable_rows") or []),
            "stop_timetables": list(stop_bundle.get("stop_timetables") or []),
            "calendar_entries": list(core.get("calendar_entries") or []),
            "calendar_date_entries": list(core.get("calendar_date_entries") or []),
        },
        route_payloads=list(route_bundle.get("route_timetables") or []),
    )


def get_or_refresh_gtfs_snapshot(
    *,
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
) -> Dict[str, Any]:
    snapshot_key = _gtfs_snapshot_key(feed_path)
    expected_signature = _serialize(gtfs_feed_signature(feed_path))
    snapshot = get_snapshot(snapshot_key)
    if (
        snapshot is not None
        and snapshot.get("signature") == expected_signature
        and _has_snapshot_payload(snapshot_key, _GTFS_REQUIRED_ENTITY_TYPES)
    ):
        bundle = load_snapshot_bundle(snapshot_key)
        bundle["meta"]["snapshotMode"] = "catalog"
        return bundle

    refreshed = refresh_gtfs_snapshot(feed_path=feed_path)
    bundle = load_snapshot_bundle(refreshed["snapshotKey"])
    bundle["meta"]["snapshotMode"] = "refreshed"
    return bundle
