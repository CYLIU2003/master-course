"""
src.tokyubus_gtfs.features.charging_windows — Charging window feature builder.

Identifies time windows at terminal stops where a vehicle could charge
between trips.  These windows feed into the optimisation layer's charger
scheduling constraints.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..constants import DEFAULT_TURNAROUND_SEC

_log = logging.getLogger(__name__)

# Minimum idle time (seconds) for a window to be considered chargeable
_MIN_CHARGE_WINDOW_SEC = 600  # 10 minutes


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


def build_charging_windows(
    canonical_dir: Path,
    out_dir: Path,
    *,
    min_window_sec: int = _MIN_CHARGE_WINDOW_SEC,
    turnaround_sec: int = DEFAULT_TURNAROUND_SEC,
) -> Dict[str, Any]:
    """
    Identify charging windows from trip chain gaps.

    A charging window exists when a vehicle dwells at a terminal stop
    for longer than ``turnaround_sec + min_window_sec``.

    Reads ``trip_chains.jsonl`` from the features directory and
    ``trips.jsonl`` from the canonical directory.

    Output: ``charging_windows.jsonl`` in *out_dir*.

    Returns
    -------
    dict
        Summary with window count and warnings.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    chains = _read_jsonl(out_dir / "trip_chains.jsonl")
    trips = _read_jsonl(canonical_dir / "trips.jsonl")
    warnings: List[str] = []

    if not chains:
        warnings.append("No trip chains found — skipping charging window build")
        return {"window_count": 0, "warnings": warnings}

    # Build trip lookup
    trip_map: Dict[str, Dict[str, Any]] = {
        t.get("trip_id", ""): t for t in trips if t.get("trip_id")
    }

    windows: List[Dict[str, Any]] = []
    threshold_min = (turnaround_sec + min_window_sec) / 60.0

    for chain in chains:
        gap_min = chain.get("gap_min", 0.0)
        if gap_min < threshold_min:
            continue
        if chain.get("needs_deadhead", False):
            continue  # Can't charge if vehicle must deadhead

        trip_i = trip_map.get(chain.get("trip_i_id", ""), {})
        trip_j = trip_map.get(chain.get("trip_j_id", ""), {})
        arr_sec = trip_i.get("arrival_seconds")
        dep_sec = trip_j.get("departure_seconds")
        if arr_sec is None or dep_sec is None:
            continue

        usable_sec = (dep_sec - arr_sec) - turnaround_sec
        if usable_sec < min_window_sec:
            continue

        window = {
            "service_id": chain.get("service_id", ""),
            "stop_id": chain.get("dest_i", ""),
            "trip_before_id": chain.get("trip_i_id"),
            "trip_after_id": chain.get("trip_j_id"),
            "arrival_seconds": arr_sec,
            "departure_seconds": dep_sec,
            "turnaround_sec": turnaround_sec,
            "usable_charging_sec": usable_sec,
            "usable_charging_min": round(usable_sec / 60.0, 1),
        }
        windows.append(window)

    out_path = out_dir / "charging_windows.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for w in windows:
            f.write(json.dumps(w, ensure_ascii=False, separators=(",", ":")) + "\n")

    _log.info("Built %d charging windows", len(windows))
    return {"window_count": len(windows), "warnings": warnings}
