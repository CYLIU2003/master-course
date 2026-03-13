"""
src.tokyubus_gtfs.features.deadhead_candidates — Deadhead candidate builder.

Pre-computes potential deadhead movements between route terminals.
These feed into dispatch feasibility and optimisation as candidate
non-revenue movements.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ..constants import DEFAULT_DEADHEAD_SPEED_KMH

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


def build_deadhead_candidates(
    canonical_dir: Path,
    out_dir: Path,
    *,
    max_distance_km: float = 30.0,
    speed_kmh: float = DEFAULT_DEADHEAD_SPEED_KMH,
) -> Dict[str, Any]:
    """
    Build deadhead candidate movements between route terminals.

    For each ordered pair of terminals (from_stop, to_stop), estimate
    the deadhead distance and time using haversine + road factor.

    Output: ``deadhead_candidates.jsonl`` in *out_dir*.

    Parameters
    ----------
    canonical_dir
        Directory with canonical JSONL (stops.jsonl, routes.jsonl).
    out_dir
        Feature output directory.
    max_distance_km
        Maximum haversine distance to consider.
    speed_kmh
        Assumed average deadhead speed for time estimation.

    Returns
    -------
    dict
        Summary with candidate count and warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stops = _read_jsonl(canonical_dir / "stops.jsonl")
    routes = _read_jsonl(canonical_dir / "routes.jsonl")
    warnings: List[str] = []

    if not stops:
        warnings.append("No stops found — skipping deadhead candidate build")
        return {"candidate_count": 0, "warnings": warnings}

    # Stop coordinate lookup
    stop_coords: Dict[str, Tuple[float, float]] = {}
    for s in stops:
        sid = s.get("stop_id", "")
        lat, lon = s.get("lat"), s.get("lon")
        if sid and lat is not None and lon is not None:
            stop_coords[sid] = (float(lat), float(lon))

    # Collect terminal stops
    terminal_ids: Set[str] = set()
    for r in routes:
        for key in ("origin_stop_id", "destination_stop_id"):
            sid = r.get(key, "")
            if sid and sid in stop_coords:
                terminal_ids.add(sid)

    if not terminal_ids:
        warnings.append("No geolocated terminals — skipping deadhead candidates")
        return {"candidate_count": 0, "warnings": warnings}

    # Road factor: haversine underestimates actual road distance
    ROAD_FACTOR = 1.3

    sorted_ids = sorted(terminal_ids)
    candidates: List[Dict[str, Any]] = []

    for from_id in sorted_ids:
        lat_a, lon_a = stop_coords[from_id]
        for to_id in sorted_ids:
            if from_id == to_id:
                continue
            lat_b, lon_b = stop_coords[to_id]
            haversine = _haversine_km(lat_a, lon_a, lat_b, lon_b)
            if haversine > max_distance_km:
                continue

            road_km = round(haversine * ROAD_FACTOR, 2)
            time_min = round((road_km / speed_kmh) * 60, 1) if speed_kmh > 0 else 0.0

            candidates.append(
                {
                    "from_stop_id": from_id,
                    "to_stop_id": to_id,
                    "haversine_km": round(haversine, 3),
                    "estimated_road_km": road_km,
                    "estimated_time_min": time_min,
                    "speed_kmh": speed_kmh,
                    "method": "haversine_x1.3",
                }
            )

    out_path = out_dir / "deadhead_candidates.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d deadhead candidates", len(candidates))
    return {"candidate_count": len(candidates), "warnings": warnings}
