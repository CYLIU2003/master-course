"""
src.tokyubus_gtfs.features.energy — Energy estimation feature builder.

Placeholder for segment-level and trip-level energy consumption estimates.
This will be populated with BEV / ICE energy models when the optimization
layer is connected.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

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


def build_energy_features(
    canonical_dir: Path,
    out_dir: Path,
    *,
    default_kwh_per_km: float = 1.2,
    default_l_per_km: float = 0.35,
) -> Dict[str, Any]:
    """
    Build basic energy estimation features for each trip.

    Uses simple distance-based estimation as a baseline.
    Will be replaced by segment-level models incorporating grade,
    traffic, HVAC load, and passenger load.

    Output: ``energy_estimates.jsonl`` in *out_dir*.

    Returns
    -------
    dict
        Summary with count and warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    trips = _read_jsonl(canonical_dir / "trips.jsonl")
    warnings: List[str] = []

    if not trips:
        warnings.append("No trips found — skipping energy feature build")
        return {"estimate_count": 0, "warnings": warnings}

    estimates: List[Dict[str, Any]] = []
    for t in trips:
        dist = t.get("distance_km", 0.0)
        est = {
            "trip_id": t.get("trip_id"),
            "route_id": t.get("route_id"),
            "distance_km": dist,
            "bev_kwh_estimate": round(dist * default_kwh_per_km, 2),
            "ice_l_estimate": round(dist * default_l_per_km, 3),
            "estimation_method": "distance_linear",
            "confidence": 0.3,  # low — simple linear model
        }
        estimates.append(est)

    out_path = out_dir / "energy_estimates.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for e in estimates:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d energy estimates", len(estimates))
    return {"estimate_count": len(estimates), "warnings": warnings}
