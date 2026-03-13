"""
src.tokyubus_gtfs.features.depot — Depot candidate feature builder.

Identifies potential depot locations from terminal stops and stop metadata.
Placeholder for future multi-depot optimization.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

_log = logging.getLogger(__name__)

# Japanese keywords commonly associated with bus depots/garages
_DEPOT_KEYWORDS = ("営業所", "車庫", "操車場", "車庫前", "出入庫")


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


def _has_depot_keyword(name: str) -> bool:
    return any(kw in name for kw in _DEPOT_KEYWORDS)


def build_depot_candidates(
    canonical_dir: Path,
    out_dir: Path,
) -> Dict[str, Any]:
    """
    Identify depot candidate stops from canonical data.

    Heuristics:
      1. Stops whose names contain depot keywords
      2. Stops that are terminals of multiple routes
      3. (Future) Stops with known charger infrastructure

    Output: ``depot_candidates.jsonl`` in *out_dir*.

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
        warnings.append("No stops found — skipping depot candidate build")
        return {"candidate_count": 0, "warnings": warnings}

    # Count how many routes terminate at each stop
    terminal_counts: Dict[str, int] = {}
    for r in routes:
        for sid in (r.get("origin_stop_id"), r.get("destination_stop_id")):
            if sid:
                terminal_counts[sid] = terminal_counts.get(sid, 0) + 1

    stop_map = {s.get("stop_id"): s for s in stops}
    candidates: List[Dict[str, Any]] = []

    for stop_id, count in terminal_counts.items():
        s = stop_map.get(stop_id, {})
        name = s.get("stop_name", "")
        has_keyword = _has_depot_keyword(name)

        # Only flag if keyword match OR high terminal count
        if has_keyword or count >= 3:
            score = 0.0
            reasons: List[str] = []
            if has_keyword:
                score += 0.5
                reasons.append("depot_keyword_match")
            if count >= 5:
                score += 0.3
                reasons.append(f"terminal_of_{count}_routes")
            elif count >= 3:
                score += 0.15
                reasons.append(f"terminal_of_{count}_routes")

            candidates.append(
                {
                    "stop_id": stop_id,
                    "stop_name": name,
                    "lat": s.get("lat"),
                    "lon": s.get("lon"),
                    "terminal_route_count": count,
                    "depot_score": round(min(score, 1.0), 2),
                    "reasons": reasons,
                }
            )

    # Sort by score descending
    candidates.sort(key=lambda c: c["depot_score"], reverse=True)

    out_path = out_dir / "depot_candidates.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False, separators=(",", ":")) + "\n")

    candidate_by_stop = {str(candidate.get("stop_id") or ""): candidate for candidate in candidates}
    route_candidate_map: List[Dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        if not route_id:
            continue
        route_candidates: List[Dict[str, Any]] = []
        for role, stop_key in (("origin", "origin_stop_id"), ("destination", "destination_stop_id")):
            stop_id = str(route.get(stop_key) or "")
            candidate = candidate_by_stop.get(stop_id)
            if not candidate:
                continue
            route_candidates.append(
                {
                    "match_role": role,
                    "stop_id": stop_id,
                    "stop_name": candidate.get("stop_name"),
                    "depot_score": candidate.get("depot_score"),
                    "reasons": candidate.get("reasons") or [],
                }
            )
        route_candidate_map.append(
            {
                "route_id": route_id,
                "route_code": route.get("route_code", ""),
                "route_name": route.get("route_name", ""),
                "route_family_code": route.get("route_family_code", route.get("route_code", "")),
                "origin_stop_id": route.get("origin_stop_id", ""),
                "destination_stop_id": route.get("destination_stop_id", ""),
                "depot_candidates": route_candidates,
            }
        )

    map_path = out_dir / "depot_candidate_map.json"
    with map_path.open("w", encoding="utf-8") as f:
        json.dump(route_candidate_map, f, ensure_ascii=False, indent=2)

    _log.info("Identified %d depot candidates", len(candidates))
    return {
        "candidate_count": len(candidates),
        "mapped_route_count": len(route_candidate_map),
        "warnings": warnings,
    }
