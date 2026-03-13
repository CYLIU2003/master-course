"""
bff/services/depot_assignment.py

Score-based depot auto-assignment service.

Scoring tiers (additive):
  3 pts  geographic  – route terminal stop ID set intersects depot stop ID set
  2 pts  sidecar_map – depot appears in the sidecar depot_candidate_map for this route family
  1 pt   operator    – depot.operatorId == route.operatorId
  0      none        – no match at any tier

Callers use compute_depot_route_scores() to get the full matrix, then
auto_assign_depots() to pick the best (or all qualifying) depot per route.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DepotAssignmentScore:
    depot_id: str
    route_id: str
    score: int  # 0-6 (additive across tiers)
    reasons: List[str] = field(default_factory=list)

    @property
    def tier(self) -> str:
        """Human-readable tier label for UI badge display."""
        if self.score >= 3:
            return "geographic"
        if self.score >= 2:
            return "sidecar_map"
        if self.score >= 1:
            return "operator_match"
        return "none"


def compute_depot_route_scores(
    depots: List[Dict[str, Any]],
    routes: List[Dict[str, Any]],
    sidecar_depot_candidate_map: Optional[Dict[str, List[str]]] = None,
) -> List[DepotAssignmentScore]:
    """Return a DepotAssignmentScore for every (depot, route) pair.

    Args:
        depots: list of depot dicts.
            Required keys: id (or depotId), operatorId.
            Optional key:  stopIds (list[str]) – stop IDs served by / adjacent to this depot.
        routes: list of route dicts.
            Required keys: id (or routeId), operatorId.
            Optional keys: routeFamilyId (or route_family_id),
                           stopIds (or stop_ids, list[str]).
        sidecar_depot_candidate_map: {route_family_id: [depot_id, ...]}
            Comes from GTFS sidecar / Layer-D feature data.
            Pass None or {} to skip the sidecar tier.

    Returns:
        List of DepotAssignmentScore (one per depot×route combination).
    """
    if sidecar_depot_candidate_map is None:
        sidecar_depot_candidate_map = {}

    results: List[DepotAssignmentScore] = []

    for depot in depots:
        depot_id = str(depot.get("id") or depot.get("depotId") or "").strip()
        if not depot_id:
            continue
        depot_operator = str(depot.get("operatorId") or "").strip()
        depot_stop_set: set[str] = {
            str(s) for s in (depot.get("stopIds") or depot.get("stop_ids") or []) if s
        }

        for route in routes:
            route_id = str(route.get("id") or route.get("routeId") or "").strip()
            if not route_id:
                continue
            route_operator = str(route.get("operatorId") or "").strip()
            family_id = str(
                route.get("routeFamilyId") or route.get("route_family_id") or ""
            ).strip()
            stop_ids: List[str] = [
                str(s)
                for s in (route.get("stopIds") or route.get("stop_ids") or [])
                if s
            ]
            # Only use terminal stops (first + last) to avoid over-matching
            route_endpoints: set[str] = set()
            if stop_ids:
                route_endpoints.add(stop_ids[0])
                route_endpoints.add(stop_ids[-1])

            score = 0
            reasons: List[str] = []

            # ── Tier 1: operator match (1 pt) ───────────────────────────
            if depot_operator and route_operator and depot_operator == route_operator:
                score += 1
                reasons.append("operator_match")

            # ── Tier 2: sidecar depot_candidate_map (2 pts) ─────────────
            sidecar_candidates = sidecar_depot_candidate_map.get(family_id, [])
            if depot_id in sidecar_candidates:
                score += 2
                reasons.append("sidecar_map")

            # ── Tier 3: geographic – terminal stop overlap (3 pts) ───────
            if (
                depot_stop_set
                and route_endpoints
                and (depot_stop_set & route_endpoints)
            ):
                score += 3
                reasons.append("geographic")

            results.append(
                DepotAssignmentScore(
                    depot_id=depot_id,
                    route_id=route_id,
                    score=score,
                    reasons=reasons,
                )
            )

    return results


def auto_assign_depots(
    depots: List[Dict[str, Any]],
    routes: List[Dict[str, Any]],
    sidecar_depot_candidate_map: Optional[Dict[str, List[str]]] = None,
    *,
    min_score: int = 1,
    allow_multi_depot: bool = False,
) -> Dict[str, List[str]]:
    """Return {route_id: [depot_id, ...]} for routes that meet *min_score*.

    Args:
        min_score: Minimum total score for a depot to be included in the result.
            0 = include all; 1 = operator match or better (default);
            2 = sidecar_map or better; 3 = geographic or better.
        allow_multi_depot: If True, all qualifying depots per route are returned
            (sorted by descending score). If False (default), only the single
            highest-scoring depot is returned per route.

    Returns:
        Dict mapping route_id → list of depot_ids (best first).
        Routes with no qualifying depot are omitted.
    """
    scores = compute_depot_route_scores(depots, routes, sidecar_depot_candidate_map)

    route_candidates: Dict[str, List[DepotAssignmentScore]] = defaultdict(list)
    for s in scores:
        if s.score >= min_score:
            route_candidates[s.route_id].append(s)

    result: Dict[str, List[str]] = {}
    for route_id, candidates in route_candidates.items():
        candidates.sort(key=lambda x: -x.score)
        if allow_multi_depot:
            result[route_id] = [c.depot_id for c in candidates]
        else:
            result[route_id] = [candidates[0].depot_id]

    return result


# ---------------------------------------------------------------------------
# Legacy helper (kept for backward compatibility with existing router calls)
# ---------------------------------------------------------------------------


def calculate_assignment_scores(
    routes: List[Dict[str, Any]],
    depots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Legacy name-based scorer — kept for backward compatibility.

    Scores routes against depots using string-name heuristics
    (terminal stop name ⊃ depot name, route label ⊃ depot name, operator match).
    New code should use ``compute_depot_route_scores()`` instead.
    """
    suggestions: List[Dict[str, Any]] = []

    depot_list = []
    for d in depots:
        depot_id = d.get("id")
        if not depot_id:
            continue
        name = d.get("name", "") or ""
        core_name = name.replace("営業所", "").replace("車庫", "")
        depot_list.append(
            {
                "id": depot_id,
                "name": name,
                "core_name": core_name,
                "operatorId": d.get("operatorId"),
            }
        )

    for route in routes:
        route_id = route.get("id")
        if not route_id:
            continue

        start_stop = route.get("startStop", "") or ""
        end_stop = route.get("endStop", "") or ""
        route_family_label = route.get("routeFamilyLabel", "") or ""
        route_name = route.get("name", "") or ""
        route_operator = route.get("operatorId")

        best_depot_id: Optional[str] = None
        best_score = -1
        best_reasons: List[str] = []
        scores_for_route: List[Dict[str, Any]] = []

        for depot in depot_list:
            score = 0
            reasons: List[str] = []

            # 3 pts: depot name in terminal stop strings
            if (
                depot["name"] in start_stop
                or depot["core_name"] in start_stop
                or depot["name"] in end_stop
                or depot["core_name"] in end_stop
            ):
                score += 3
                reasons.append("Terminal stop matches depot name (3pt)")

            # 2 pts: depot name in route family label / route name
            if (
                depot["name"] in route_family_label
                or depot["core_name"] in route_family_label
                or depot["name"] in route_name
                or depot["core_name"] in route_name
            ):
                score += 2
                reasons.append("Route name relates to depot (2pt)")

            # 1 pt: operator match
            if (
                depot["operatorId"]
                and route_operator
                and depot["operatorId"] == route_operator
            ):
                score += 1
                reasons.append("Operator matches (1pt)")
            elif not depot["operatorId"] and not route_operator:
                score += 1
                reasons.append("Same scenario bounds (1pt)")

            if score > 0:
                scores_for_route.append(
                    {
                        "depotId": depot["id"],
                        "depotName": depot["name"],
                        "score": score,
                        "reasons": reasons,
                    }
                )
                if score > best_score:
                    best_score = score
                    best_depot_id = depot["id"]
                    best_reasons = reasons

        suggestions.append(
            {
                "routeId": route_id,
                "routeCode": route.get("routeCode") or route.get("routeFamilyCode"),
                "routeName": route_name,
                "suggestedDepotId": best_depot_id,
                "score": best_score,
                "reasons": best_reasons,
                "candidates": sorted(
                    scores_for_route, key=lambda x: x["score"], reverse=True
                ),
            }
        )

    return suggestions
