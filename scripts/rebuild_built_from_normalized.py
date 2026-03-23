"""
scripts/rebuild_built_from_normalized.py
=========================================
Rebuilds data/built/tokyu_full/*.parquet from two authoritative sources:
  1. data/catalog-fast/normalized/routes.jsonl   (rich ODPT route metadata, 764 routes)
  2. data/tokyu_gtfs.sqlite                       (full GTFS trip timetable, 33k trips)

Why:
  - routes.jsonl has 41 fields (routeVariantType, routeFamilyCode, depotId, tripCount, etc.)
    but trips.jsonl only has 1000 sample trips.
  - tokyu_gtfs.sqlite has 33,354 trips with real timetable data.
  - The built routes.parquet was only 7 columns and trips.parquet was a 1000-trip sample.

Strategy:
  - routes.parquet  → rebuilt from routes.jsonl (all 41 fields preserved)
  - trips.parquet   → rebuilt by joining GTFS trips to ODPT route variants
  - timetables.parquet → subset of trips.parquet columns

Trip-to-Route mapping:
  - Primary key: parse `odptPatternId` from the preserved ODPT-style `trip_id`
    and map it to normalized `routes.jsonl.odptPatternId`.
  - Fallback: `(routeFamilyCode, depotId, first_stop_id, last_stop_id)` when
    the trip ID does not carry an ODPT pattern.
  - Never replicate one physical trip to every route in the same family.

Usage:
    python scripts/rebuild_built_from_normalized.py
    python scripts/rebuild_built_from_normalized.py --db data/tokyu_gtfs.sqlite
    python scripts/rebuild_built_from_normalized.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_ROUTES_JSONL = _REPO_ROOT / "data" / "catalog-fast" / "normalized" / "routes.jsonl"
DEFAULT_GTFS_DB = _REPO_ROOT / "data" / "tokyu_gtfs.sqlite"
DEFAULT_BUILT_DIR = _REPO_ROOT / "data" / "built" / "tokyu_full"


def log(msg: str) -> None:
    import datetime
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _canonical_service_id(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"平日", "weekday", "WEEKDAY", "Weekday"}:
        return "WEEKDAY"
    if text in {"土曜", "saturday", "SAT", "Saturday"}:
        return "SAT"
    if text in {"日曜", "休日", "日曜・休日", "日祝", "SUN_HOL", "holiday", "Sunday", "Holiday"}:
        return "SUN_HOL"
    return text or "WEEKDAY"


def _short_depot_id(depot_id: str) -> str:
    """'tokyu:depot:meguro' → 'meguro'"""
    if not depot_id:
        return ""
    return depot_id.replace("tokyu:depot:", "").strip()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 4)


def load_normalized_routes(path: Path) -> list[dict]:
    """Read routes.jsonl → list of dicts."""
    routes = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if text:
                routes.append(json.loads(text))
    log(f"Loaded {len(routes)} routes from {path.name}")
    return routes


def build_odpt_route_lookup(routes: list[dict]) -> dict[tuple[str, str, str, str], list[str]]:
    """Build mapping: (routeFamilyCode, depotId_short, first_stop_id, last_stop_id) → [route_id]."""
    lookup: dict[tuple, list[str]] = {}
    for r in routes:
        fam = str(r.get("routeFamilyCode") or r.get("routeCode") or "").strip()
        depot = str(r.get("depotId") or r.get("depot_id") or "").strip()
        rid = str(r.get("id") or "").strip()
        stop_sequence = [
            str(item).strip()
            for item in list(r.get("stopSequence") or [])
            if str(item).strip()
        ]
        if not fam or not rid or not stop_sequence:
            continue
        key = (fam, depot, stop_sequence[0], stop_sequence[-1])
        lookup.setdefault(key, []).append(rid)
    return lookup


def build_pattern_lookup(routes: list[dict]) -> dict[str, str]:
    """Build mapping: odptPatternId → route_id."""
    lookup: dict[str, str] = {}
    for route in routes:
        pattern_id = str(route.get("odptPatternId") or "").strip()
        route_id = str(route.get("id") or "").strip()
        if pattern_id and route_id and pattern_id not in lookup:
            lookup[pattern_id] = route_id
    return lookup


def build_route_family_lookup_no_depot(routes: list[dict]) -> dict[str, list[str]]:
    """Build mapping: routeFamilyCode → [odpt-route-id, ...] for routes WITHOUT depotId."""
    lookup: dict[str, list[str]] = {}
    for r in routes:
        if r.get("depotId") or r.get("depot_id"):
            continue
        fam = str(r.get("routeFamilyCode") or r.get("routeCode") or "").strip()
        rid = str(r.get("id") or "").strip()
        if fam and rid:
            lookup.setdefault(fam, []).append(rid)
    return lookup


def load_gtfs_trips(db_path: Path) -> pd.DataFrame:
    """Load full timetable from tokyu_gtfs.sqlite."""
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query(
        """
        SELECT
            tt.trip_id,
            tt.pattern_id,
            tt.route_family,
            tt.calendar_type,
            tt.direction,
            tt.departure_hhmm  AS departure,
            tt.arrival_hhmm    AS arrival,
            tt.origin_stop_id  AS origin_id,
            tt.dest_stop_id    AS dest_id,
            rp.depot_id,
            os.title_ja        AS origin_name,
            os.lat             AS origin_lat,
            os.lon             AS origin_lon,
            ds.title_ja        AS dest_name,
            ds.lat             AS dest_lat,
            ds.lon             AS dest_lon
        FROM timetable_trips tt
        JOIN route_patterns rp ON tt.pattern_id = rp.pattern_id
        LEFT JOIN stops os ON tt.origin_stop_id = os.stop_id
        LEFT JOIN stops ds ON tt.dest_stop_id = ds.stop_id
        ORDER BY tt.dep_min, tt.trip_id
        """,
        conn,
    )
    conn.close()
    log(f"Loaded {len(df)} trips from {db_path.name}")
    return df


def _extract_odpt_pattern_id_from_trip_id(trip_id: Any) -> str | None:
    text = str(trip_id or "").strip()
    parts = text.split(".")
    if len(parts) < 4:
        return None
    if parts[0] != "odpt" or parts[1] != "BusTimetable:TokyuBus":
        return None
    return f"odpt.BusroutePattern:TokyuBus.{parts[2]}.{parts[3]}"


def build_trips_parquet(
    gtfs_trips: pd.DataFrame,
    pattern_lookup: dict[str, str],
    odpt_lookup: dict[tuple, list[str]],
    no_depot_lookup: dict[str, list[str]],
) -> pd.DataFrame:
    """
    Map GTFS trips to ODPT route IDs and produce trips DataFrame.
    Each GTFS trip must resolve to exactly one route variant.
    """
    records = []
    skipped = 0
    matched_by_pattern = 0
    matched_by_signature = 0
    matched_by_family = 0
    ambiguous_fallback = 0

    for _, row in gtfs_trips.iterrows():
        route_family = str(row["route_family"] or "").strip()
        depot_id_full = str(row["depot_id"] or "").strip()
        depot_id_short = _short_depot_id(depot_id_full)
        base_trip_id = str(row["trip_id"] or "").strip()

        matched_route_ids: list[str] = []
        odpt_pattern_id = _extract_odpt_pattern_id_from_trip_id(base_trip_id)
        if odpt_pattern_id:
            matched_route_id = pattern_lookup.get(odpt_pattern_id)
            if matched_route_id:
                matched_route_ids = [matched_route_id]
                matched_by_pattern += 1

        if not matched_route_ids and depot_id_short:
            signature_ids = odpt_lookup.get(
                (
                    route_family,
                    depot_id_short,
                    str(row["origin_id"] or "").strip(),
                    str(row["dest_id"] or "").strip(),
                ),
                [],
            )
            if len(signature_ids) == 1:
                matched_route_ids = list(signature_ids)
                matched_by_signature += 1
            elif len(signature_ids) > 1:
                ambiguous_fallback += 1

        if not matched_route_ids:
            no_depot_ids = no_depot_lookup.get(route_family, [])
            if len(no_depot_ids) == 1:
                matched_route_ids = list(no_depot_ids)
                matched_by_family += 1
            elif len(no_depot_ids) > 1:
                ambiguous_fallback += 1

        if not matched_route_ids:
            skipped += 1
            continue

        service_id = _canonical_service_id(row["calendar_type"])
        departure = str(row["departure"] or "").strip()
        arrival = str(row["arrival"] or "").strip()

        # Compute distance
        distance_km = 0.0
        try:
            if all(
                v is not None and not pd.isna(v)
                for v in [row["origin_lat"], row["origin_lon"], row["dest_lat"], row["dest_lon"]]
            ):
                distance_km = _haversine_km(
                    float(row["origin_lat"]), float(row["origin_lon"]),
                    float(row["dest_lat"]), float(row["dest_lon"]),
                )
        except Exception:
            pass

        direction = str(row["direction"] or "unknown").strip()
        origin_name = str(row["origin_name"] or row["origin_id"] or "").strip()
        dest_name = str(row["dest_name"] or row["dest_id"] or "").strip()
        origin_lat = float(row["origin_lat"]) if row["origin_lat"] is not None and not pd.isna(row["origin_lat"]) else None
        origin_lon = float(row["origin_lon"]) if row["origin_lon"] is not None and not pd.isna(row["origin_lon"]) else None
        dest_lat = float(row["dest_lat"]) if row["dest_lat"] is not None and not pd.isna(row["dest_lat"]) else None
        dest_lon = float(row["dest_lon"]) if row["dest_lon"] is not None and not pd.isna(row["dest_lon"]) else None

        records.append({
            "trip_id": base_trip_id,
            "route_id": matched_route_ids[0],
            "service_id": service_id,
            "departure": departure,
            "arrival": arrival,
            "origin": origin_name,
            "destination": dest_name,
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "destination_lat": dest_lat,
            "destination_lon": dest_lon,
            "distance_km": distance_km,
            "direction": direction,
            "allowed_vehicle_types": ["BEV", "ICE"],
            "source": "gtfs",
        })

    log(
        "Built %s trip records (%s skipped, pattern=%s, signature=%s, family=%s, ambiguous=%s)"
        % (
            len(records),
            skipped,
            matched_by_pattern,
            matched_by_signature,
            matched_by_family,
            ambiguous_fallback,
        )
    )
    if not records:
        raise RuntimeError("No trips could be mapped to ODPT routes — check route family name matching")
    return pd.DataFrame(records)


def build_routes_parquet(routes: list[dict], trip_counts: dict[str, int]) -> pd.DataFrame:
    """Build enriched routes DataFrame from normalized JSONL data."""
    rows = []
    for r in routes:
        route_id = str(r.get("id") or "").strip()
        if not route_id:
            continue
        stop_seq = r.get("stopSequence") or []
        if isinstance(stop_seq, str):
            try:
                stop_seq = json.loads(stop_seq)
            except Exception:
                stop_seq = []
        rows.append({
            # Core fields
            "id": route_id,
            "name": r.get("name") or r.get("routeLabel") or r.get("routeCode") or route_id,
            "routeCode": r.get("routeCode") or "",
            "routeLabel": r.get("routeLabel") or r.get("name") or "",
            "source": r.get("source") or "odpt",
            "depotId": r.get("depotId") or r.get("depot_id") or "",
            "depotName": r.get("depotName") or r.get("depot_name") or "",
            "stopSequence": list(stop_seq),
            # Rich metadata (previously missing from 7-column parquet)
            "startStop": r.get("startStop") or "",
            "endStop": r.get("endStop") or "",
            "distanceKm": float(r.get("distanceKm") or 0.0),
            "durationMin": int(r.get("durationMin") or 0),
            "color": r.get("color") or "",
            "enabled": bool(r.get("enabled", True)),
            "routeFamilyCode": r.get("routeFamilyCode") or r.get("routeCode") or "",
            "routeFamilyLabel": r.get("routeFamilyLabel") or r.get("routeLabel") or "",
            "routeVariantType": r.get("routeVariantType") or "main",
            "routeVariantId": r.get("routeVariantId") or r.get("route_variant_id") or "",
            "canonicalDirection": r.get("canonicalDirection") or r.get("canonical_direction") or "",
            "routeSeriesCode": r.get("routeSeriesCode") or "",
            "routeSeriesPrefix": r.get("routeSeriesPrefix") or "",
            "routeSeriesNumber": int(r.get("routeSeriesNumber") or 0),
            "isPrimaryVariant": bool(r.get("isPrimaryVariant", False)),
            "classificationConfidence": float(r.get("classificationConfidence") or 1.0),
            "classificationSource": r.get("classificationSource") or "",
            "odptPatternId": r.get("odptPatternId") or "",
            "odptBusrouteId": r.get("odptBusrouteId") or "",
            "operator_id": r.get("operator_id") or "tokyu",
            # Trip count (from built trips data)
            "tripCount": int(trip_counts.get(route_id) or 0),
        })
    log(f"Built {len(rows)} route records")
    return pd.DataFrame(rows)


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rebuild_manifest(built_dir: Path, dataset_version: str) -> None:
    """Write v1-schema manifest.json with artifact hashes."""
    manifest_path = built_dir / "manifest.json"
    artifact_names = [
        "routes.parquet",
        "trips.parquet",
        "timetables.parquet",
        "stops.parquet",
        "stop_timetables.parquet",
    ]
    artifact_hashes: dict[str, str] = {}
    for name in artifact_names:
        p = built_dir / name
        if p.exists():
            artifact_hashes[name] = _sha256_file(p)
    manifest = {
        "schema_version": "v1",
        "dataset_id": built_dir.name,
        "dataset_version": dataset_version,
        "producer_version": "rebuild_from_normalized",
        "min_runtime_version": "0.1.0",
        "artifact_hashes": artifact_hashes,
        "source": "rebuild_from_normalized",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  Wrote manifest ({len(artifact_hashes)} artifact hashes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--routes-jsonl", default=str(DEFAULT_ROUTES_JSONL), help="Path to normalized/routes.jsonl")
    parser.add_argument("--db", default=str(DEFAULT_GTFS_DB), help="Path to tokyu_gtfs.sqlite")
    parser.add_argument("--built-dir", default=str(DEFAULT_BUILT_DIR), help="Output directory for parquet files")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without writing files")
    args = parser.parse_args()

    routes_path = Path(args.routes_jsonl)
    db_path = Path(args.db)
    built_dir = Path(args.built_dir)

    if not routes_path.exists():
        print(f"ERROR: routes.jsonl not found at {routes_path}")
        sys.exit(1)
    if not db_path.exists():
        print(f"ERROR: GTFS database not found at {db_path}")
        sys.exit(1)

    log("=== Rebuilding built parquet files ===")
    log(f"  Routes source : {routes_path}")
    log(f"  Trips source  : {db_path}")
    log(f"  Output dir    : {built_dir}")

    # Step 1: Load normalized routes
    routes = load_normalized_routes(routes_path)

    # Step 2: Build lookup tables
    pattern_lookup = build_pattern_lookup(routes)
    odpt_lookup = build_odpt_route_lookup(routes)
    no_depot_lookup = build_route_family_lookup_no_depot(routes)
    log(f"  odptPatternId routes: {len(pattern_lookup)}")
    log(f"  (family,depot,terminals) pairs with routes: {len(odpt_lookup)}")
    log(f"  Route families with no-depot routes: {len(no_depot_lookup)}")

    # Step 3: Load GTFS trips
    gtfs_trips = load_gtfs_trips(db_path)

    # Step 4: Map GTFS trips → ODPT route IDs
    trips_df = build_trips_parquet(gtfs_trips, pattern_lookup, odpt_lookup, no_depot_lookup)

    # Step 5: Compute trip counts per route_id
    trip_counts: dict[str, int] = (
        trips_df.groupby("route_id").size().to_dict()
        if not trips_df.empty
        else {}
    )
    routes_with_trips = sum(1 for c in trip_counts.values() if c > 0)
    log(f"  Routes with trips: {routes_with_trips} / {len(routes)}")

    # Step 6: Build enriched routes DataFrame
    routes_df = build_routes_parquet(routes, trip_counts)

    # Step 7: Build timetables (subset of trips)
    timetables_cols = [
        "trip_id", "route_id", "service_id",
        "origin", "origin_lat", "origin_lon",
        "destination", "destination_lat", "destination_lon",
        "departure", "arrival", "distance_km",
        "allowed_vehicle_types", "source",
    ]
    timetables_df = trips_df[[c for c in timetables_cols if c in trips_df.columns]].copy()

    # Step 8: Build trips (subset without lat/lon for backward compat)
    trips_export_cols = [
        "trip_id", "route_id", "service_id", "departure", "arrival",
        "origin", "destination", "distance_km", "direction",
        "allowed_vehicle_types", "source",
    ]
    trips_export_df = trips_df[[c for c in trips_export_cols if c in trips_df.columns]].copy()

    log(f"  routes_df: {len(routes_df)} rows, {len(routes_df.columns)} columns")
    log(f"  trips_df: {len(trips_export_df)} rows, {len(trips_export_df.columns)} columns")
    log(f"  timetables_df: {len(timetables_df)} rows")

    if args.dry_run:
        log("DRY RUN - no files written.")
        print("\nSample routes:")
        for _, row in routes_df.head(3).iterrows():
            print(f"  {row['id']}: {row['routeCode']} depot={row['depotId']} tripCount={row['tripCount']}")
        print("\nSample trips:")
        for _, row in trips_export_df.head(3).iterrows():
            print(f"  {row['trip_id']}: route={row['route_id']} svc={row['service_id']} dep={row['departure']}")

        # Stats by depot
        depot_stats = routes_df.groupby("depotId").agg(
            route_count=("id", "count"),
            trips=("tripCount", "sum"),
        ).reset_index()
        print("\nDepot stats:")
        for _, row in depot_stats.iterrows():
            print(f"  {row['depotId'] or '(no depot)'}: {row['route_count']} routes, {int(row['trips'])} trips")
        return

    # Write parquet files
    built_dir.mkdir(parents=True, exist_ok=True)
    routes_out = built_dir / "routes.parquet"
    trips_out = built_dir / "trips.parquet"
    timetables_out = built_dir / "timetables.parquet"

    routes_df.to_parquet(routes_out, index=False)
    log(f"  Wrote {routes_out}")
    trips_export_df.to_parquet(trips_out, index=False)
    log(f"  Wrote {trips_out}")
    timetables_df.to_parquet(timetables_out, index=False)
    log(f"  Wrote {timetables_out}")

    from datetime import date
    rebuild_manifest(built_dir, date.today().isoformat())

    log("=== Done ===")
    print(f"\nSummary:")
    print(f"  routes.parquet   : {len(routes_df)} routes, {len(routes_df.columns)} columns")
    print(f"  trips.parquet    : {len(trips_export_df)} trips")
    print(f"  timetables.parquet: {len(timetables_df)} rows")
    print(f"  Routes with trips: {routes_with_trips}")
    print(f"  Routes without depotId: {sum(1 for r in routes if not r.get('depotId'))}")

    # Per-depot stats
    print("\nDepot summary:")
    depot_stats = routes_df.groupby("depotId").agg(
        route_count=("id", "count"),
        trips=("tripCount", "sum"),
    ).reset_index().sort_values("trips", ascending=False)
    for _, row in depot_stats.iterrows():
        label = row["depotId"] or "(no depot)"
        print(f"  {label:25s}: {row['route_count']:3d} routes, {int(row['trips']):6d} trips")


if __name__ == "__main__":
    main()
