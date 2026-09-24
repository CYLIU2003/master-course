"""Auditable trip-specific geographic distances from a frozen SQLite catalog.

These are adjacent-stop chord lengths, never certified road distances. Missing
stops cannot be replaced with route-wide endpoints or a default distance.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import sqlite3
from typing import Any, Sequence

from src.geo import haversine_km

DISTANCE_SOURCE = "trip_stop_sequence_polyline_haversine"


def trip_path_distance(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Validate every source stop before calculating a geographic proxy."""
    if len(rows) < 2:
        raise ValueError("TRIP_PATH_INCOMPLETE: fewer than two stops")
    ordered = sorted(rows, key=lambda row: int(row["seq"]))
    sequences = [int(row["seq"]) for row in ordered]
    if sequences != list(range(sequences[0], sequences[0] + len(rows))):
        raise ValueError("TRIP_PATH_SEQUENCE_INVALID: duplicate or missing sequence")
    points = []
    for row in ordered:
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"TRIP_COORDINATE_MISSING: {row.get('stop_id')}") from exc
        if not row.get("stop_id") or not (math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"TRIP_COORDINATE_INVALID: {row.get('stop_id')}")
        points.append((str(row["stop_id"]), lat, lon))
    # Keep the established Prepare radius so DB export and missing-distance
    # materialization agree without changing existing research assumptions.
    distance = round(sum(haversine_km(a[1], a[2], b[1], b[2], radius_km=6371.0)
                         for a, b in zip(points, points[1:])), 6)
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("TRIP_DISTANCE_NONPOSITIVE")
    return {
        "distance_km": distance,
        "distance_source": DISTANCE_SOURCE,
        "distance_stop_count": len(points),
        "distance_segment_count": len(points) - 1,
        "distance_path_sha256": hashlib.sha256(json.dumps(
            points, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest(),
    }


def load_trip_paths(connection: sqlite3.Connection, trip_ids: Sequence[str]) -> dict[str, list[dict]]:
    """Batch source reads to avoid one query per trip and SQLite bind limits."""
    result: dict[str, list[dict]] = defaultdict(list)
    unique = sorted(set(trip_ids))
    for start in range(0, len(unique), 400):
        batch = unique[start:start + 400]
        marks = ",".join("?" for _ in batch)
        cursor = connection.execute(f"""
            SELECT ts.trip_id, ts.seq, ts.stop_id, s.lat, s.lon,
                   ts.departure_hhmm, ts.arrival_hhmm
            FROM trip_stops ts LEFT JOIN stops s ON s.stop_id = ts.stop_id
            WHERE ts.trip_id IN ({marks}) ORDER BY ts.trip_id, ts.seq
        """, batch)
        names = [column[0] for column in cursor.description]
        for values in cursor:
            row = dict(zip(names, values))
            result[row["trip_id"]].append(row)
    return dict(result)


def validate_catalog_trip_path(trip: dict, path: Sequence[dict]) -> dict:
    """Keep short turns and loops; reject disagreement with the trip itself."""
    trip_id = str(trip.get("trip_id") or "")
    try:
        evidence = trip_path_distance(path)
        ordered = sorted(path, key=lambda row: int(row["seq"]))
        origin = trip.get("origin_stop_id", trip.get("origin"))
        destination = trip.get("dest_stop_id", trip.get("destination"))
        if origin != ordered[0]["stop_id"] or destination != ordered[-1]["stop_id"]:
            raise ValueError("TRIP_ENDPOINT_MISMATCH: source trip and stop sequence disagree")
        if trip.get("stop_count") is not None and int(trip["stop_count"]) != len(path):
            raise ValueError("TRIP_STOP_COUNT_MISMATCH")
        return evidence
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"{trip_id}: {exc}") from exc
