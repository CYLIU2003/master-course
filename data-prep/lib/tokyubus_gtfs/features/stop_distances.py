"""
src.tokyubus_gtfs.features.stop_distances — Stop distance matrix builder.

Pre-computes pairwise geodesic distances between terminal stops for
deadhead estimation and depot-to-route assignment.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two GPS coordinates in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pair_key(stop_a: str, stop_b: str) -> Tuple[str, str]:
    return (stop_a, stop_b) if stop_a <= stop_b else (stop_b, stop_a)


def _estimate_adjacent_distance_km(
    stop_a: str,
    stop_b: str,
    stop_coords: Dict[str, Tuple[float, float]],
    delta_m: Optional[float] = None,
) -> Tuple[float, str]:
    if delta_m is not None and delta_m > 0.0:
        return (delta_m / 1000.0, "route_stops_delta")
    coords_a = stop_coords.get(stop_a)
    coords_b = stop_coords.get(stop_b)
    if coords_a and coords_b:
        return (_haversine_km(coords_a[0], coords_a[1], coords_b[0], coords_b[1]), "adjacent_haversine")
    return (0.0, "unknown")


def build_stop_distance_matrix(
    canonical_dir: Path,
    out_dir: Path,
    *,
    terminal_only: bool = True,
    min_distance_km: float = 0.03,
) -> Dict[str, Any]:
    """
    Build a pairwise distance matrix for terminal stops.

    Parameters
    ----------
    canonical_dir
        Directory with canonical JSONL (stops.jsonl, routes.jsonl).
    out_dir
        Feature output directory.
    terminal_only
        If True, only compute distances between route terminals.
        If False, compute for ALL stops (can be very large).

    Returns
    -------
    dict
        Summary with pair count and warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stops = _read_jsonl(canonical_dir / "stops.jsonl")
    routes = _read_jsonl(canonical_dir / "routes.jsonl")
    route_stops = _read_jsonl(canonical_dir / "route_stops.jsonl")
    stop_times = _read_jsonl(canonical_dir / "stop_times.jsonl")
    warnings: List[str] = []

    if not stops:
        warnings.append("No stops found — skipping distance matrix build")
        return {"pair_count": 0, "warnings": warnings}

    # Build stop coordinate lookup
    stop_coords: Dict[str, Tuple[float, float]] = {}
    for s in stops:
        sid = s.get("stop_id", "")
        lat, lon = s.get("lat"), s.get("lon")
        if sid and lat is not None and lon is not None:
            stop_coords[sid] = (float(lat), float(lon))

    # Determine target terminals for optional filtering
    terminal_ids: Set[str] = set()
    if terminal_only:
        for r in routes:
            for key in ("origin_stop_id", "destination_stop_id"):
                sid = r.get(key, "")
                if sid:
                    terminal_ids.add(sid)

    candidate_pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}

    route_stops_by_pattern: Dict[str, List[Dict[str, Any]]] = {}
    for row in route_stops:
        pattern_id = str(row.get("pattern_id") or "")
        if pattern_id:
            route_stops_by_pattern.setdefault(pattern_id, []).append(row)

    for pattern_id, rows in route_stops_by_pattern.items():
        ordered = sorted(rows, key=lambda item: int(item.get("stop_sequence") or 0))
        for idx in range(1, len(ordered)):
            prev_row = ordered[idx - 1]
            curr_row = ordered[idx]
            stop_a = str(prev_row.get("stop_id") or "")
            stop_b = str(curr_row.get("stop_id") or "")
            if not stop_a or not stop_b or stop_a == stop_b:
                continue
            prev_m = _safe_float(prev_row.get("distance_from_start_m"))
            curr_m = _safe_float(curr_row.get("distance_from_start_m"))
            delta_m = (curr_m - prev_m) if prev_m is not None and curr_m is not None else None
            dist_km, method = _estimate_adjacent_distance_km(stop_a, stop_b, stop_coords, delta_m)
            if dist_km < min_distance_km:
                continue
            key = _pair_key(stop_a, stop_b)
            current = candidate_pairs.get(key)
            if current is None or dist_km < float(current.get("distance_km") or 0.0):
                candidate_pairs[key] = {
                    "stop_a": key[0],
                    "stop_b": key[1],
                    "distance_km": round(dist_km, 3),
                    "method": method,
                    "source": f"route_stops:{pattern_id}",
                }

    stop_times_by_trip: Dict[str, List[Dict[str, Any]]] = {}
    for row in stop_times:
        trip_id = str(row.get("trip_id") or "")
        if trip_id:
            stop_times_by_trip.setdefault(trip_id, []).append(row)

    for trip_id, rows in stop_times_by_trip.items():
        ordered = sorted(rows, key=lambda item: int(item.get("stop_sequence") or 0))
        for idx in range(1, len(ordered)):
            stop_a = str(ordered[idx - 1].get("stop_id") or "")
            stop_b = str(ordered[idx].get("stop_id") or "")
            if not stop_a or not stop_b or stop_a == stop_b:
                continue
            dist_km, method = _estimate_adjacent_distance_km(stop_a, stop_b, stop_coords)
            if dist_km < min_distance_km:
                continue
            key = _pair_key(stop_a, stop_b)
            current = candidate_pairs.get(key)
            if current is None or dist_km < float(current.get("distance_km") or 0.0):
                candidate_pairs[key] = {
                    "stop_a": key[0],
                    "stop_b": key[1],
                    "distance_km": round(dist_km, 3),
                    "method": method,
                    "source": f"stop_times:{trip_id}",
                }

    pairs = sorted(candidate_pairs.values(), key=lambda item: (item["stop_a"], item["stop_b"]))
    if terminal_only and terminal_ids:
        pairs = [
            row
            for row in pairs
            if row["stop_a"] in terminal_ids or row["stop_b"] in terminal_ids
        ]

    if not pairs:
        warnings.append("No positive adjacent stop distances were generated")

    out_path = out_dir / "stop_distances.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d stop distance pairs", len(pairs))
    return {"pair_count": len(pairs), "warnings": warnings}
