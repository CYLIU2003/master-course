from typing import Any, Dict, List, Optional
import math

def calculate_assignment_scores(
    routes: List[Dict[str, Any]],
    depots: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Suggests the best depot for each route based on a score-based algorithm.
    """
    suggestions = []
    
    # Pre-process depots for faster matching
    depot_list = []
    for d in depots:
        depot_id = d.get("id")
        if not depot_id:
            continue
        name = d.get("name", "")
        # Remove "営業所" to get the core name for better matching if needed
        core_name = name.replace("営業所", "").replace("車庫", "")
        depot_list.append({
            "id": depot_id,
            "name": name,
            "core_name": core_name,
            "operatorId": d.get("operatorId"),
        })

    for route in routes:
        route_id = route.get("id")
        if not route_id:
            continue
            
        start_stop = route.get("startStop", "") or ""
        end_stop = route.get("endStop", "") or ""
        route_family_label = route.get("routeFamilyLabel", "") or ""
        route_name = route.get("name", "") or ""
        route_operator = route.get("operatorId")
        
        best_depot_id = None
        best_score = -1
        best_reasons = []

        scores_for_route = []

        for depot in depot_list:
            score = 0
            reasons = []

            # 3 pts: Depot adjacent to route origin/destination
            # For simplicity, we check if the depot name or core name is in the terminal stops
            if (
                depot["name"] in start_stop or depot["core_name"] in start_stop or
                depot["name"] in end_stop or depot["core_name"] in end_stop
            ):
                score += 3
                reasons.append("Terminal stop matches depot name (3pt)")

            # 2 pts: Depot linked to route family via sidecar map (simulated by name match)
            if (
                depot["name"] in route_family_label or depot["core_name"] in route_family_label or
                depot["name"] in route_name or depot["core_name"] in route_name
            ):
                score += 2
                reasons.append("Route name relates to depot (2pt)")

            # 1 pt: Operator match
            if depot["operatorId"] and route_operator and depot["operatorId"] == route_operator:
                score += 1
                reasons.append("Operator matches (1pt)")
            elif not depot["operatorId"] and not route_operator:
                score += 1
                reasons.append("Same scenario bounds (1pt)")

            if score > 0:
                scores_for_route.append({
                    "depotId": depot["id"],
                    "depotName": depot["name"],
                    "score": score,
                    "reasons": reasons
                })
                if score > best_score:
                    best_score = score
                    best_depot_id = depot["id"]
                    best_reasons = reasons

        suggestions.append({
            "routeId": route_id,
            "routeCode": route.get("routeCode") or route.get("routeFamilyCode"),
            "routeName": route_name,
            "suggestedDepotId": best_depot_id,
            "score": best_score,
            "reasons": best_reasons,
            "candidates": sorted(scores_for_route, key=lambda x: x["score"], reverse=True)
        })

    return suggestions
