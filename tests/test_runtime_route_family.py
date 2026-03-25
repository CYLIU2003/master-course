from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache

from bff.services.runtime_route_family import reclassify_routes_for_runtime
from src.research_dataset_loader import build_dataset_bootstrap
from src.tokyu_bus_data import route_trip_counts_by_day_type


@lru_cache(maxsize=1)
def _bootstrap_payload() -> dict:
    return build_dataset_bootstrap(
        "tokyu_full",
        scenario_id="test-runtime-route-family",
        random_seed=42,
    )


@lru_cache(maxsize=1)
def _reclassified_routes() -> list[dict]:
    payload = _bootstrap_payload()
    return reclassify_routes_for_runtime([dict(route) for route in payload["routes"]])


def test_runtime_reclassification_fixes_east98_depot_variants() -> None:
    routes = {
        str(route.get("id") or ""): route
        for route in _reclassified_routes()
    }
    expected_variants = {
        "odpt-route-8c7870a5bfdc": "depot_in",
        "odpt-route-fade5cdd5cc4": "depot_out",
        "odpt-route-48bf66658361": "main_outbound",
        "odpt-route-a4ab4b504c68": "main_outbound",
        "odpt-route-664ad72aef6f": "main_outbound",
        "odpt-route-0bff36ddf27d": "main_outbound",
        "odpt-route-090e495ea6ea": "main_inbound",
        "odpt-route-560ec0d7e114": "depot_in",
        "odpt-route-9ac3c35ceae4": "depot_out",
        "odpt-route-a5ffc3f38842": "depot_in",
        "odpt-route-3f3f02ba90f2": "depot_out",
    }
    expected_trip_counts = {
        "odpt-route-8c7870a5bfdc": 17,
        "odpt-route-fade5cdd5cc4": 42,
        "odpt-route-48bf66658361": 53,
        "odpt-route-a4ab4b504c68": 1,
        "odpt-route-664ad72aef6f": 5,
        "odpt-route-0bff36ddf27d": 3,
        "odpt-route-090e495ea6ea": 30,
        "odpt-route-560ec0d7e114": 6,
        "odpt-route-9ac3c35ceae4": 6,
        "odpt-route-a5ffc3f38842": 29,
        "odpt-route-3f3f02ba90f2": 4,
    }

    for route_id, expected_variant in expected_variants.items():
        route = routes[route_id]
        assert route["routeFamilyCode"] == "東98"
        assert route["routeVariantType"] == expected_variant
        assert int(route["tripCount"]) == expected_trip_counts[route_id]


def test_runtime_reclassification_splits_generic_service_families_and_removes_unknowns() -> None:
    routes = _reclassified_routes()
    generic_codes = {"高速", "空港", "直行", "急行", "出入庫"}

    assert all(route.get("routeVariantType") != "unknown" for route in routes)

    grouped_family_codes: dict[str, set[str]] = defaultdict(set)
    for route in routes:
        route_code = str(route.get("routeCode") or "")
        if route_code in generic_codes:
            family_code = str(route.get("routeFamilyCode") or "")
            grouped_family_codes[route_code].add(family_code)
            assert family_code != route_code
            assert family_code.startswith(f"{route_code}:")

    assert len(grouped_family_codes["高速"]) >= 5
    assert len(grouped_family_codes["空港"]) >= 10
    assert len(grouped_family_codes["直行"]) == 5
    assert len(grouped_family_codes["急行"]) == 2
    assert len(grouped_family_codes["出入庫"]) == 4

    depot_move_variants = Counter(
        route.get("routeVariantType")
        for route in routes
        if route.get("routeCode") == "出入庫"
    )
    assert depot_move_variants == Counter({"depot_in": 4, "depot_out": 3})


def test_bootstrap_route_trip_counts_match_trip_rows_for_all_routes() -> None:
    payload = _bootstrap_payload()
    route_ids = [
        str(route.get("id") or "").strip()
        for route in payload["routes"]
        if str(route.get("id") or "").strip()
    ]
    aggregated = route_trip_counts_by_day_type(
        dataset_id="tokyu_full",
        route_ids=route_ids,
        depot_ids=None,
    )

    mismatches: list[tuple[str, dict[str, int], dict[str, int], int, int]] = []
    for route in payload["routes"]:
        route_id = str(route.get("id") or "").strip()
        expected_counts = {
            str(service_id): int(count)
            for service_id, count in aggregated.get(route_id, {}).items()
            if int(count) > 0
        }
        actual_counts = {
            str(service_id): int(count)
            for service_id, count in dict(route.get("tripCountsByDayType") or {}).items()
            if int(count) > 0
        }
        expected_total = sum(expected_counts.values())
        actual_total = int(route.get("tripCountTotal") or route.get("tripCount") or 0)
        if actual_counts != expected_counts or actual_total != expected_total:
            mismatches.append(
                (route_id, actual_counts, expected_counts, actual_total, expected_total)
            )

    assert mismatches == []


def test_runtime_reclassification_applies_official_override_tags() -> None:
    routes = {
        str(route.get("id") or ""): route
        for route in _reclassified_routes()
    }

    assert routes["odpt-route-5d426a74c8ab"]["routeVariantType"] == "main_outbound"
    assert routes["odpt-route-ba3e0318d63c"]["routeVariantType"] == "main_inbound"
    assert routes["odpt-route-f26d4c5a5213"]["routeVariantType"] == "short_turn"
    assert routes["odpt-route-31f20134f727"]["routeVariantType"] == "branch"

    assert routes["odpt-route-c799354eac2c"]["routeVariantType"] == "main_outbound"
    assert routes["odpt-route-b152081a6404"]["routeVariantType"] == "main_inbound"
    assert routes["odpt-route-cb75217aefe4"]["routeVariantType"] == "branch"

    assert routes["odpt-route-48bf66658361"]["routeVariantType"] == "main_outbound"
    assert routes["odpt-route-090e495ea6ea"]["routeVariantType"] == "main_inbound"
    assert routes["odpt-route-fade5cdd5cc4"]["routeVariantType"] == "depot_out"
    assert routes["odpt-route-a5ffc3f38842"]["routeVariantType"] == "depot_in"

    assert routes["odpt-route-48bf66658361"]["classificationSource"] == "official_manual_override"
    assert routes["odpt-route-5d426a74c8ab"]["classificationSource"] == "official_manual_override"
    assert routes["odpt-route-c799354eac2c"]["classificationSource"] == "official_manual_override"


def test_runtime_reclassification_preserves_user_manual_override_over_official() -> None:
    seed = {
        "id": "route-manual-shibu41",
        "name": "渋41 manual",
        "routeCode": "渋41",
        "routeFamilyCode": "渋41",
        "routeLabel": "渋41 (渋谷駅 -> 大井町駅)",
        "startStop": "渋谷駅",
        "endStop": "大井町駅",
        "tripCount": 10,
        "routeVariantTypeManual": "branch",
        "canonicalDirectionManual": "inbound",
        "classificationSource": "user_manual_override",
        "manualClassificationLocked": True,
    }

    [route] = reclassify_routes_for_runtime([seed])

    assert route["routeVariantType"] == "branch"
    assert route["canonicalDirection"] == "inbound"
    assert route["classificationSource"] == "user_manual_override"
