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
from typing import Any, Dict, List, Set, Tuple

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


def build_stop_distance_matrix(
    canonical_dir: Path,
    out_dir: Path,
    *,
    terminal_only: bool = True,
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

    # Determine which stops to include
    if terminal_only:
        target_ids: Set[str] = set()
        for r in routes:
            for key in ("origin_stop_id", "destination_stop_id"):
                sid = r.get(key, "")
                if sid:
                    target_ids.add(sid)
        target_ids = target_ids & set(stop_coords.keys())
    else:
        target_ids = set(stop_coords.keys())

    if not target_ids:
        warnings.append("No geolocated terminal stops — skipping distance matrix")
        return {"pair_count": 0, "warnings": warnings}

    # Compute pairwise distances
    sorted_ids = sorted(target_ids)
    pairs: List[Dict[str, Any]] = []
    for i, sid_a in enumerate(sorted_ids):
        lat_a, lon_a = stop_coords[sid_a]
        for sid_b in sorted_ids[i + 1 :]:
            lat_b, lon_b = stop_coords[sid_b]
            dist = _haversine_km(lat_a, lon_a, lat_b, lon_b)
            pairs.append(
                {
                    "stop_a": sid_a,
                    "stop_b": sid_b,
                    "distance_km": round(dist, 3),
                    "method": "haversine",
                }
            )

    out_path = out_dir / "stop_distances.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d stop distance pairs", len(pairs))
    return {"pair_count": len(pairs), "warnings": warnings}
