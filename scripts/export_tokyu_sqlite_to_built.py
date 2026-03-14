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


def export_sqlite_to_built(
    db_path: Path,
    dataset_id: str,
    built_root: Path,
    depot_ids: list[str],
) -> Path:
    manifest_writer = _load_module("manifest_writer", "data-prep/lib/manifest_writer.py")
    producer_version = _load_module("producer_version", "data-prep/lib/producer_version.py")

    built_dir = built_root / dataset_id
    built_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    route_where = ""
    params: list[Any] = []
    if depot_ids:
        placeholders = ",".join("?" for _ in depot_ids)
        route_where = f"WHERE route_families.depot_id IN ({placeholders})"
        params.extend(depot_ids)

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
    routes_df.to_parquet(built_dir / "routes.parquet", index=False)

    trip_where = "WHERE t.pattern_id = rp.pattern_id"
    trip_params: list[Any] = []
    if depot_ids:
        placeholders = ",".join("?" for _ in depot_ids)
        trip_where += f" AND rp.depot_id IN ({placeholders})"
        trip_params.extend(depot_ids)

    trips_df = pd.read_sql_query(
        f"""
        SELECT
            t.trip_id,
            'tokyu:' || replace(rp.depot_id, 'tokyu:depot:', '') || ':' || t.route_family AS route_id,
            t.calendar_type AS service_id,
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
    trips_df["distance_km"] = trips_df.apply(_compute_distance_km, axis=1)
    trips_df["allowed_vehicle_types"] = trips_df["allowed_vehicle_types"].apply(json.loads)
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
    conn.close()

    definition = _read_seed_definition(dataset_id, depot_ids)
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


if __name__ == "__main__":
    main()
