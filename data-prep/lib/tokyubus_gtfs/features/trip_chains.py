"""
src.tokyubus_gtfs.features.trip_chains — Trip chain / block builder.

Pre-computes candidate trip chains (consecutive trip pairs that a single
vehicle could operate) based on time/location feasibility.

This is Layer D's equivalent of the dispatch connection graph, but stored
as a feature table rather than computed on-the-fly.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..constants import DEFAULT_DEADHEAD_SPEED_KMH, DEFAULT_TURNAROUND_SEC

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
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_stop_distance_lookup(feature_dir: Path) -> Dict[Tuple[str, str], float]:
    lookup: Dict[Tuple[str, str], float] = {}
    for row in _read_jsonl(feature_dir / "stop_distances.jsonl"):
        stop_a = str(row.get("stop_a") or "")
        stop_b = str(row.get("stop_b") or "")
        distance_km = _safe_float(row.get("distance_km"))
        if not stop_a or not stop_b or distance_km is None or distance_km <= 0.0:
            continue
        lookup[(stop_a, stop_b)] = distance_km
        lookup[(stop_b, stop_a)] = distance_km
    return lookup


def _build_stop_coord_lookup(canonical_dir: Path) -> Dict[str, Tuple[float, float]]:
    lookup: Dict[str, Tuple[float, float]] = {}
    for row in _read_jsonl(canonical_dir / "stops.jsonl"):
        stop_id = str(row.get("stop_id") or "")
        lat = _safe_float(row.get("lat"))
        lon = _safe_float(row.get("lon"))
        if stop_id and lat is not None and lon is not None:
            lookup[stop_id] = (lat, lon)
    return lookup


def _estimate_deadhead_distance_km(
    from_stop: str,
    to_stop: str,
    stop_distance_lookup: Dict[Tuple[str, str], float],
    stop_coords: Dict[str, Tuple[float, float]],
) -> Tuple[float, str]:
    if not from_stop or not to_stop:
        return (0.0, "none")
    lookup_distance = stop_distance_lookup.get((from_stop, to_stop))
    if lookup_distance is not None and lookup_distance > 0.0:
        return (lookup_distance, "stop_distance_lookup")
    coords_from = stop_coords.get(from_stop)
    coords_to = stop_coords.get(to_stop)
    if coords_from and coords_to:
        dist = _haversine_km(coords_from[0], coords_from[1], coords_to[0], coords_to[1])
        if dist > 0.0:
            return (dist, "haversine_fallback")
    return (0.0, "none")


def build_trip_chains(
    canonical_dir: Path,
    out_dir: Path,
    *,
    turnaround_sec: int = DEFAULT_TURNAROUND_SEC,
    deadhead_speed_kmh: float = DEFAULT_DEADHEAD_SPEED_KMH,
    max_wait_min: float = 120.0,
) -> Dict[str, Any]:
    """
    Build candidate trip chain features from canonical trips.

    For each pair of trips (i, j) within the same service day:
      - Check if trip_j departs after trip_i arrives + turnaround
      - Check if the wait time is within the threshold
      - Estimate deadhead time/distance if terminals differ

    Output: ``trip_chains.jsonl`` in *out_dir*.

    Parameters
    ----------
    canonical_dir
        Directory with canonical JSONL (trips.jsonl).
    out_dir
        Feature output directory (data/tokyubus/features/).
    turnaround_sec
        Minimum turnaround time at terminal.
    deadhead_speed_kmh
        Assumed average speed for deadhead estimation.
    max_wait_min
        Maximum allowed gap between consecutive trips.

    Returns
    -------
    dict
        Summary with chain count and warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    trips = _read_jsonl(canonical_dir / "trips.jsonl")
    stop_distance_lookup = _build_stop_distance_lookup(out_dir)
    stop_coords = _build_stop_coord_lookup(canonical_dir)
    warnings: List[str] = []

    if not trips:
        warnings.append("No trips found — skipping trip chain build")
        return {"chain_count": 0, "warnings": warnings}

    # Group by service_id
    by_service: Dict[str, List[Dict[str, Any]]] = {}
    for t in trips:
        sid = t.get("service_id", "WEEKDAY")
        by_service.setdefault(sid, []).append(t)

    chains: List[Dict[str, Any]] = []
    turnaround_min = turnaround_sec / 60.0

    for sid, svc_trips in by_service.items():
        # Sort by departure time
        sorted_trips = sorted(svc_trips, key=lambda t: t.get("departure_seconds") or 0)

        for i, t_i in enumerate(sorted_trips):
            arr_i = t_i.get("arrival_seconds")
            if arr_i is None:
                continue
            dest_i = t_i.get("destination_stop_id", "")

            for j in range(i + 1, len(sorted_trips)):
                t_j = sorted_trips[j]
                dep_j = t_j.get("departure_seconds")
                if dep_j is None:
                    continue

                # Time gap
                gap_sec = dep_j - arr_i
                gap_min = gap_sec / 60.0
                if gap_min < turnaround_min:
                    continue  # too tight
                if gap_min > max_wait_min:
                    break  # sorted, so no further j will be feasible

                origin_j = t_j.get("origin_stop_id", "")
                needs_deadhead = dest_i != origin_j
                deadhead_distance_km = 0.0
                deadhead_time_min = 0.0
                deadhead_method = "none"
                if needs_deadhead:
                    deadhead_distance_km, deadhead_method = _estimate_deadhead_distance_km(
                        str(dest_i),
                        str(origin_j),
                        stop_distance_lookup,
                        stop_coords,
                    )
                    if deadhead_distance_km > 0.0 and deadhead_speed_kmh > 0.0:
                        deadhead_time_min = (deadhead_distance_km / deadhead_speed_kmh) * 60.0

                if gap_min < (turnaround_min + deadhead_time_min):
                    continue

                chain = {
                    "service_id": sid,
                    "trip_i_id": t_i.get("trip_id"),
                    "trip_j_id": t_j.get("trip_id"),
                    "trip_i_route": t_i.get("route_id"),
                    "trip_j_route": t_j.get("route_id"),
                    "gap_min": round(gap_min, 1),
                    "needs_deadhead": needs_deadhead,
                    "deadhead_distance_km": round(deadhead_distance_km, 3),
                    "deadhead_time_min": round(deadhead_time_min, 1),
                    "deadhead_method": deadhead_method,
                    "dest_i": dest_i,
                    "origin_j": origin_j,
                    "feasible": True,
                }
                chains.append(chain)

    # Write canonical JSONL and compatibility JSON array.
    out_path = out_dir / "trip_chains.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for c in chains:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")
    compatibility_path = out_dir / "trip_chains.json"
    compatibility_path.write_text(
        json.dumps(chains, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _log.info("Built %d candidate trip chains", len(chains))
    return {"chain_count": len(chains), "warnings": warnings}
