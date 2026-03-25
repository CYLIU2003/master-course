from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from bff.services.route_family import RawRoute, extract_route_family_code
from bff.services.service_ids import canonical_service_id
from src.tokyu_bus_data import route_trip_counts_by_day_type, tokyu_bus_data_ready


def _dataset_id(scenario: Dict[str, Any]) -> str:
    meta = dict(scenario.get("meta") or {})
    overlay = dict(scenario.get("scenario_overlay") or {})
    feed_context = dict(scenario.get("feed_context") or scenario.get("feedContext") or {})
    return str(
        scenario.get("datasetId")
        or scenario.get("dataset_id")
        or meta.get("datasetId")
        or overlay.get("dataset_id")
        or overlay.get("datasetId")
        or feed_context.get("datasetId")
        or "tokyu_full"
    ).strip() or "tokyu_full"


def _normalize_counts(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    return {
        canonical_service_id(key): int(value or 0)
        for key, value in raw.items()
    }


def audit_route_catalog_consistency(
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    routes = [
        dict(item)
        for item in list(scenario.get("routes") or [])
        if isinstance(item, dict)
    ]
    route_ids = [
        str(item.get("id") or "").strip()
        for item in routes
        if str(item.get("id") or "").strip()
    ]
    dataset_id = _dataset_id(scenario)
    actual_counts_by_route: Dict[str, Dict[str, int]] = {}
    actual_counts_source = "unavailable"
    if route_ids and tokyu_bus_data_ready(dataset_id):
        actual_counts_by_route = route_trip_counts_by_day_type(
            dataset_id=dataset_id,
            route_ids=route_ids,
            depot_ids=None,
        )
        actual_counts_source = "tokyu_bus_data"

    issues: List[Dict[str, Any]] = []
    same_code_families: Dict[tuple[str, str], set[str]] = defaultdict(set)

    for route in routes:
        route_id = str(route.get("id") or "").strip()
        if not route_id:
            continue
        route_code = str(route.get("routeCode") or "").strip()
        depot_id = str(route.get("depotId") or "").strip() or "__unassigned__"
        stored_family_code = str(route.get("routeFamilyCode") or "").strip()
        expected_family_code = extract_route_family_code(RawRoute.from_dict(route))

        if route_code:
            same_code_families[(depot_id, route_code)].add(
                stored_family_code or expected_family_code
            )

        if not stored_family_code:
            issues.append(
                {
                    "kind": "missing_family_code",
                    "routeId": route_id,
                    "routeCode": route_code,
                    "depotId": depot_id,
                    "expectedRouteFamilyCode": expected_family_code,
                }
            )
        elif expected_family_code and stored_family_code != expected_family_code:
            issues.append(
                {
                    "kind": "family_code_mismatch",
                    "routeId": route_id,
                    "routeCode": route_code,
                    "depotId": depot_id,
                    "storedRouteFamilyCode": stored_family_code,
                    "expectedRouteFamilyCode": expected_family_code,
                }
            )

        if actual_counts_by_route:
            stored_counts = _normalize_counts(route.get("tripCountsByDayType"))
            actual_counts = _normalize_counts(actual_counts_by_route.get(route_id) or {})
            if stored_counts != actual_counts:
                issues.append(
                    {
                        "kind": "trip_count_mismatch",
                        "routeId": route_id,
                        "routeCode": route_code,
                        "depotId": depot_id,
                        "storedTripCountsByDayType": stored_counts,
                        "actualTripCountsByDayType": actual_counts,
                    }
                )

    for (depot_id, route_code), family_codes in sorted(same_code_families.items()):
        normalized = sorted(code for code in family_codes if code)
        if len(normalized) <= 1:
            continue
        issues.append(
            {
                "kind": "same_code_split_across_families",
                "depotId": depot_id,
                "routeCode": route_code,
                "routeFamilyCodes": normalized,
            }
        )

    family_issue_count = sum(
        1
        for item in issues
        if item.get("kind")
        in {
            "missing_family_code",
            "family_code_mismatch",
            "same_code_split_across_families",
        }
    )
    trip_count_mismatch_count = sum(
        1 for item in issues if item.get("kind") == "trip_count_mismatch"
    )

    return {
        "checkedRouteCount": len(route_ids),
        "actualCountsSource": actual_counts_source,
        "issueCount": len(issues),
        "familyIssueCount": family_issue_count,
        "tripCountMismatchCount": trip_count_mismatch_count,
        "issues": issues[:50],
    }

