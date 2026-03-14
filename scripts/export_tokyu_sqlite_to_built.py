from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.geo import haversine_km

DEFAULT_DB = REPO_ROOT / "data" / "tokyu_full.sqlite"
DEFAULT_BUILT_ROOT = REPO_ROOT / "data" / "built"
SEED_ROOT = REPO_ROOT / "data" / "seed" / "tokyu"


def _load_module(module_name: str, relative_path: str) -> Any:
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _read_seed_definition(dataset_id: str, depot_ids: list[str]) -> dict[str, Any]:
    path = SEED_ROOT / "datasets" / f"{dataset_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "dataset_id": dataset_id,
        "included_depots": [depot_id.replace("tokyu:depot:", "") for depot_id in depot_ids],
        "included_routes": "ALL",
    }


def _canonicalize_depot_ids(depot_ids: list[str]) -> list[str]:
    resolved: list[str] = []
    for depot_id in depot_ids:
        value = str(depot_id or "").strip()
        if not value:
            continue
        canonical = value if value.startswith("tokyu:depot:") else f"tokyu:depot:{value}"
        if canonical not in resolved:
            resolved.append(canonical)
    return resolved


def _resolve_depot_scope(dataset_id: str, depot_ids: list[str]) -> tuple[list[str], dict[str, Any]]:
    definition = _read_seed_definition(dataset_id, depot_ids)
    explicit_scope = _canonicalize_depot_ids(depot_ids)
    if explicit_scope:
        return explicit_scope, definition
    definition_scope = _canonicalize_depot_ids(list(definition.get("included_depots") or []))
    return definition_scope, definition


def _compute_distance_km(row: pd.Series) -> float:
    values = [
        row.get("origin_lat"),
        row.get("origin_lon"),
        row.get("destination_lat"),
        row.get("destination_lon"),
    ]
    if any(pd.isna(value) for value in values):
        return 0.0
    return round(
        haversine_km(
            float(row["origin_lat"]),
            float(row["origin_lon"]),
            float(row["destination_lat"]),
            float(row["destination_lon"]),
        ),
        4,
    )


def _canonical_service_id(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"平日", "weekday", "WEEKDAY"}:
        return "WEEKDAY"
    if text in {"土曜", "saturday", "SAT"}:
        return "SAT"
    if text in {"日曜", "休日", "日曜・休日", "日祝", "SUN_HOL", "holiday"}:
        return "SUN_HOL"
    return text or "WEEKDAY"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _depot_filter_clause(column_name: str, depot_ids: list[str]) -> tuple[str, list[Any]]:
    if not depot_ids:
        return "", []
    placeholders = ",".join("?" for _ in depot_ids)
    return f"WHERE {column_name} IN ({placeholders})", list(depot_ids)


def _route_detail_map(
    conn: sqlite3.Connection,
    depot_ids: list[str],
) -> dict[str, dict[str, Any]]:
    route_pattern_columns = _table_columns(conn, "route_patterns")
    if not {"pattern_id", "route_family", "depot_id"}.issubset(route_pattern_columns):
        return {}

    where_sql, params = _depot_filter_clause("depot_id", depot_ids)
    patterns = pd.read_sql_query(
        f"""
        SELECT pattern_id, route_family, title_ja, direction, depot_id, origin_stop_id, dest_stop_id, stop_count
        FROM route_patterns
        {where_sql}
        ORDER BY route_family, stop_count DESC, pattern_id
        """,
        conn,
        params=params,
    )
    if patterns.empty:
        return {}

    stop_name_by_id: dict[str, str] = {}
    if _table_exists(conn, "stops"):
        stop_rows = pd.read_sql_query(
            "SELECT stop_id, title_ja FROM stops",
            conn,
        )
        stop_name_by_id = {
            str(row["stop_id"]): str(row["title_ja"] or row["stop_id"])
            for _, row in stop_rows.iterrows()
        }

    pattern_stops_by_pattern_id: dict[str, list[str]] = {}
    if {"pattern_id", "seq", "stop_id"}.issubset(_table_columns(conn, "pattern_stops")):
        pattern_ids = [str(item) for item in patterns["pattern_id"].tolist()]
        if pattern_ids:
            placeholders = ",".join("?" for _ in pattern_ids)
            pattern_stops = pd.read_sql_query(
                f"""
                SELECT pattern_id, seq, stop_id
                FROM pattern_stops
                WHERE pattern_id IN ({placeholders})
                ORDER BY pattern_id, seq
                """,
                conn,
                params=pattern_ids,
            )
            for pattern_id, group in pattern_stops.groupby("pattern_id"):
                pattern_stops_by_pattern_id[str(pattern_id)] = [
                    str(stop_id)
                    for stop_id in group["stop_id"].tolist()
                    if str(stop_id).strip()
                ]

    details: dict[str, dict[str, Any]] = {}
    for _, row in patterns.iterrows():
        route_family = str(row["route_family"] or "").strip()
        if not route_family or route_family in details:
            continue
        origin_stop_id = str(row.get("origin_stop_id") or "").strip()
        dest_stop_id = str(row.get("dest_stop_id") or "").strip()
        pattern_id = str(row["pattern_id"] or "")
        details[route_family] = {
            "startStop": stop_name_by_id.get(origin_stop_id, origin_stop_id),
            "endStop": stop_name_by_id.get(dest_stop_id, dest_stop_id),
            "canonicalDirection": str(row.get("direction") or "").strip() or None,
            "routeVariantType": "main",
            "stopSequence": list(pattern_stops_by_pattern_id.get(pattern_id) or []),
        }
    return details


def _export_stops_artifact(
    conn: sqlite3.Connection,
    built_dir: Path,
    depot_ids: list[str],
) -> None:
    if not _table_exists(conn, "stops"):
        return
    stop_columns = _table_columns(conn, "stops")

    stop_ids: set[str] = set()
    if {"pattern_id", "seq", "stop_id"}.issubset(_table_columns(conn, "pattern_stops")) and {
        "pattern_id",
        "depot_id",
    }.issubset(_table_columns(conn, "route_patterns")):
        where_sql, params = _depot_filter_clause("rp.depot_id", depot_ids)
        pattern_stop_rows = pd.read_sql_query(
            f"""
            SELECT DISTINCT ps.stop_id
            FROM pattern_stops ps
            JOIN route_patterns rp ON ps.pattern_id = rp.pattern_id
            {where_sql}
            """,
            conn,
            params=params,
        )
        stop_ids.update(str(item) for item in pattern_stop_rows["stop_id"].tolist())
    if {"origin_stop_id", "dest_stop_id", "pattern_id"}.issubset(_table_columns(conn, "timetable_trips")):
        tt_where = ""
        tt_params: list[Any] = []
        if depot_ids and {"pattern_id", "depot_id"}.issubset(_table_columns(conn, "route_patterns")):
            placeholders = ",".join("?" for _ in depot_ids)
            tt_where = f"WHERE rp.depot_id IN ({placeholders})"
            tt_params = list(depot_ids)
            trip_stop_rows = pd.read_sql_query(
                f"""
                SELECT DISTINCT t.origin_stop_id AS stop_id
                FROM timetable_trips t
                JOIN route_patterns rp ON t.pattern_id = rp.pattern_id
                {tt_where}
                UNION
                SELECT DISTINCT t.dest_stop_id AS stop_id
                FROM timetable_trips t
                JOIN route_patterns rp ON t.pattern_id = rp.pattern_id
                {tt_where}
                """,
                conn,
                params=tt_params + tt_params,
            )
        else:
            trip_stop_rows = pd.read_sql_query(
                """
                SELECT DISTINCT origin_stop_id AS stop_id FROM timetable_trips
                UNION
                SELECT DISTINCT dest_stop_id AS stop_id FROM timetable_trips
                """,
                conn,
            )
        stop_ids.update(str(item) for item in trip_stop_rows["stop_id"].tolist())

    if not stop_ids:
        return

    placeholders = ",".join("?" for _ in stop_ids)
    kana_expr = "coalesce(title_kana, '')" if "title_kana" in stop_columns else "''"
    pole_expr = "coalesce(platform_num, '')" if "platform_num" in stop_columns else "''"
    operator_expr = "coalesce(operator_id, 'tokyu')" if "operator_id" in stop_columns else "'tokyu'"
    stops_df = pd.read_sql_query(
        f"""
        SELECT
            stop_id AS id,
            stop_id AS code,
            coalesce(title_ja, stop_id) AS name,
            {kana_expr} AS kana,
            lat,
            lon,
            {pole_expr} AS poleNumber,
            {operator_expr} AS operatorId,
            'sqlite_export' AS source
        FROM stops
        WHERE stop_id IN ({placeholders})
        ORDER BY stop_id
        """,
        conn,
        params=list(stop_ids),
    )
    if not stops_df.empty:
        stops_df.to_parquet(built_dir / "stops.parquet", index=False)


def _export_stop_timetables_artifact(
    conn: sqlite3.Connection,
    built_dir: Path,
    depot_ids: list[str],
) -> None:
    required_route_pattern_cols = {"pattern_id", "route_family", "depot_id"}
    if not _table_exists(conn, "stop_timetables") or not required_route_pattern_cols.issubset(
        _table_columns(conn, "route_patterns")
    ):
        return

    where_sql = ""
    params: list[Any] = []
    if depot_ids:
        placeholders = ",".join("?" for _ in depot_ids)
        where_sql = f"WHERE rp.depot_id IN ({placeholders})"
        params = list(depot_ids)

    stop_tt_rows = pd.read_sql_query(
        f"""
        SELECT
            st.stop_id,
            st.pattern_id,
            st.calendar_type,
            st.direction,
            st.departure_hhmm,
            st.note,
            rp.route_family,
            rp.depot_id
        FROM stop_timetables st
        JOIN route_patterns rp ON st.pattern_id = rp.pattern_id
        {where_sql}
        ORDER BY st.stop_id, st.calendar_type, st.departure_hhmm, st.pattern_id
        """,
        conn,
        params=params,
    )
    if stop_tt_rows.empty:
        return

    stop_name_by_id: dict[str, str] = {}
    if _table_exists(conn, "stops"):
        stops_df = pd.read_sql_query("SELECT stop_id, title_ja FROM stops", conn)
        stop_name_by_id = {
            str(row["stop_id"]): str(row["title_ja"] or row["stop_id"])
            for _, row in stops_df.iterrows()
        }

    items: list[dict[str, Any]] = []
    for (stop_id, calendar_type), group in stop_tt_rows.groupby(["stop_id", "calendar_type"]):
        service_id = _canonical_service_id(calendar_type)
        rows = []
        for index, (_, entry) in enumerate(group.iterrows()):
            route_id = "tokyu:{depot}:{route_family}".format(
                depot=str(entry["depot_id"]).replace("tokyu:depot:", ""),
                route_family=str(entry["route_family"]),
            )
            rows.append(
                {
                    "index": index,
                    "arrival": None,
                    "departure": entry["departure_hhmm"],
                    "busroutePattern": route_id,
                    "busTimetable": None,
                    "destinationSign": str(entry["note"] or ""),
                }
            )
        items.append(
            {
                "id": f"{stop_id}::{service_id}",
                "stopId": stop_id,
                "stopName": stop_name_by_id.get(str(stop_id), str(stop_id)),
                "calendar": service_id,
                "service_id": service_id,
                "source": "sqlite_export",
                "items": rows,
            }
        )

    pd.DataFrame(items).to_parquet(built_dir / "stop_timetables.parquet", index=False)


def export_sqlite_to_built(
    db_path: Path,
    dataset_id: str,
    built_root: Path,
    depot_ids: list[str],
) -> Path:
    manifest_writer = _load_module("manifest_writer", "data-prep/lib/manifest_writer.py")
    producer_version = _load_module("producer_version", "data-prep/lib/producer_version.py")
    resolved_depot_ids, definition = _resolve_depot_scope(dataset_id, depot_ids)

    built_dir = built_root / dataset_id
    built_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    route_detail_map = _route_detail_map(conn, resolved_depot_ids)
    route_where = ""
    params: list[Any] = []
    if resolved_depot_ids:
        placeholders = ",".join("?" for _ in resolved_depot_ids)
        route_where = f"WHERE route_families.depot_id IN ({placeholders})"
        params.extend(resolved_depot_ids)

    routes_df = pd.read_sql_query(
        f"""
        SELECT
            'tokyu:' || replace(route_families.depot_id, 'tokyu:depot:', '') || ':' || route_families.route_family AS id,
            route_families.route_family AS routeCode,
            route_families.route_family AS routeLabel,
            coalesce(route_families.title_ja, route_families.route_family) AS name,
            route_families.depot_id AS depotId,
            depot.lat AS depotLat,
            depot.lon AS depotLon,
            'sqlite_export' AS source
        FROM route_families
        LEFT JOIN depots depot ON route_families.depot_id = depot.depot_id
        {route_where}
        ORDER BY route_family
        """,
        conn,
        params=params,
    )
    if routes_df.empty:
        conn.close()
        depot_scope = ", ".join(resolved_depot_ids) if resolved_depot_ids else "ALL"
        raise RuntimeError(
            f"No route_families were found in '{db_path}' for depot scope '{depot_scope}'. "
            "The SQLite catalog is empty or the depot filter does not match any authoritative route-depot assignments."
        )
    routes_df["startStop"] = routes_df["routeCode"].map(
        lambda route_code: (route_detail_map.get(str(route_code)) or {}).get("startStop", "")
    )
    routes_df["endStop"] = routes_df["routeCode"].map(
        lambda route_code: (route_detail_map.get(str(route_code)) or {}).get("endStop", "")
    )
    routes_df["routeFamilyCode"] = routes_df["routeCode"]
    routes_df["routeFamilyLabel"] = routes_df["name"]
    routes_df["routeVariantType"] = routes_df["routeCode"].map(
        lambda route_code: (route_detail_map.get(str(route_code)) or {}).get("routeVariantType")
    )
    routes_df["canonicalDirection"] = routes_df["routeCode"].map(
        lambda route_code: (route_detail_map.get(str(route_code)) or {}).get("canonicalDirection")
    )
    routes_df["stopSequence"] = routes_df["routeCode"].map(
        lambda route_code: list((route_detail_map.get(str(route_code)) or {}).get("stopSequence") or [])
    )

    trip_where = "WHERE t.pattern_id = rp.pattern_id"
    trip_params: list[Any] = []
    if resolved_depot_ids:
        placeholders = ",".join("?" for _ in resolved_depot_ids)
        trip_where += f" AND rp.depot_id IN ({placeholders})"
        trip_params.extend(resolved_depot_ids)

    trips_df = pd.read_sql_query(
        f"""
        SELECT
            t.trip_id,
            'tokyu:' || replace(rp.depot_id, 'tokyu:depot:', '') || ':' || t.route_family AS route_id,
            t.calendar_type AS calendar_type,
            t.departure_hhmm AS departure,
            t.arrival_hhmm AS arrival,
            t.origin_stop_id AS origin,
            origin_stop.title_ja AS origin_name,
            origin_stop.lat AS origin_lat,
            origin_stop.lon AS origin_lon,
            t.dest_stop_id AS destination,
            dest_stop.title_ja AS destination_name,
            dest_stop.lat AS destination_lat,
            dest_stop.lon AS destination_lon,
            json('["BEV","ICE"]') AS allowed_vehicle_types,
            'sqlite_export' AS source
        FROM timetable_trips t
        JOIN route_patterns rp ON t.pattern_id = rp.pattern_id
        LEFT JOIN stops origin_stop ON t.origin_stop_id = origin_stop.stop_id
        LEFT JOIN stops dest_stop ON t.dest_stop_id = dest_stop.stop_id
        {trip_where}
        ORDER BY t.dep_min, t.trip_id
        """,
        conn,
        params=trip_params,
    )
    if trips_df.empty:
        conn.close()
        depot_scope = ", ".join(resolved_depot_ids) if resolved_depot_ids else "ALL"
        raise RuntimeError(
            f"No timetable_trips were found in '{db_path}' for depot scope '{depot_scope}'. "
            "Build the SQLite catalog successfully first; empty exports are rejected."
        )
    trips_df["distance_km"] = trips_df.apply(_compute_distance_km, axis=1)
    trips_df["allowed_vehicle_types"] = trips_df["allowed_vehicle_types"].apply(json.loads)
    trips_df["service_id"] = trips_df["calendar_type"].apply(_canonical_service_id)
    trips_df = trips_df.drop(columns=["calendar_type"])
    trip_counts = {
        str(route_id): int(count)
        for route_id, count in trips_df.groupby("route_id").size().items()
    }
    routes_df["tripCount"] = routes_df["id"].map(lambda route_id: int(trip_counts.get(str(route_id)) or 0))
    routes_df.to_parquet(built_dir / "routes.parquet", index=False)
    trips_df.to_parquet(built_dir / "trips.parquet", index=False)

    timetables_df = trips_df[
        [
            "trip_id",
            "route_id",
            "service_id",
            "origin",
            "origin_name",
            "origin_lat",
            "origin_lon",
            "destination",
            "destination_name",
            "destination_lat",
            "destination_lon",
            "departure",
            "arrival",
            "distance_km",
            "allowed_vehicle_types",
            "source",
        ]
    ].copy()
    timetables_df.to_parquet(built_dir / "timetables.parquet", index=False)

    _export_stops_artifact(conn, built_dir, resolved_depot_ids)
    _export_stop_timetables_artifact(conn, built_dir, resolved_depot_ids)
    conn.close()

    dataset_version = date.today().isoformat()
    manifest_writer.write_manifest(
        built_dir=built_dir,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        included_depots=list(definition.get("included_depots") or []),
        included_routes=definition.get("included_routes") or "ALL",
        seed_version_path=SEED_ROOT / "version.json",
        producer_version=producer_version.get_producer_version(),
        min_runtime_version=producer_version.get_min_runtime_version(),
        source="sqlite_export",
    )
    return built_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--depot-ids", default="")
    parser.add_argument("--built-root", default=str(DEFAULT_BUILT_ROOT))
    args = parser.parse_args()

    built_dir = export_sqlite_to_built(
        db_path=Path(args.db),
        dataset_id=args.dataset_id,
        built_root=Path(args.built_root),
        depot_ids=_split_csv(args.depot_ids),
    )
    print(f"built_dir={built_dir}")
    print(f"routes={built_dir / 'routes.parquet'}")
    print(f"trips={built_dir / 'trips.parquet'}")
    print(f"timetables={built_dir / 'timetables.parquet'}")
    if (built_dir / "stops.parquet").exists():
        print(f"stops={built_dir / 'stops.parquet'}")
    if (built_dir / "stop_timetables.parquet").exists():
        print(f"stop_timetables={built_dir / 'stop_timetables.parquet'}")


if __name__ == "__main__":
    main()
