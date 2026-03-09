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
from pathlib import Path
from typing import Any, Dict, List, Optional

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

                chain = {
                    "service_id": sid,
                    "trip_i_id": t_i.get("trip_id"),
                    "trip_j_id": t_j.get("trip_id"),
                    "trip_i_route": t_i.get("route_id"),
                    "trip_j_route": t_j.get("route_id"),
                    "gap_min": round(gap_min, 1),
                    "needs_deadhead": needs_deadhead,
                    "dest_i": dest_i,
                    "origin_j": origin_j,
                    "feasible": True,
                }
                chains.append(chain)

    # Write
    out_path = out_dir / "trip_chains.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for c in chains:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d candidate trip chains", len(chains))
    return {"chain_count": len(chains), "warnings": warnings}
