from __future__ import annotations

from bff.services.route_catalog_audit import audit_route_catalog_consistency


def _base_scenario() -> dict:
    return {
        "meta": {"id": "scenario-1", "datasetId": "tokyu_full"},
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "routes": [
            {
                "id": "route-a",
                "routeCode": "東９８",
                "routeFamilyCode": "東98",
                "depotId": "meguro",
                "tripCountsByDayType": {"WEEKDAY": 10, "SAT": 5},
            }
        ],
    }


def test_route_catalog_audit_reports_family_and_trip_count_mismatches(monkeypatch) -> None:
    monkeypatch.setattr(
        "bff.services.route_catalog_audit.tokyu_bus_data_ready",
        lambda dataset_id: dataset_id == "tokyu_full",
    )
    monkeypatch.setattr(
        "bff.services.route_catalog_audit.route_trip_counts_by_day_type",
        lambda **_kwargs: {"route-a": {"WEEKDAY": 11, "SAT": 5}},
    )

    scenario = _base_scenario()
    scenario["routes"][0]["routeFamilyCode"] = "別系統"

    audit = audit_route_catalog_consistency(scenario)

    assert audit["checkedRouteCount"] == 1
    assert audit["familyIssueCount"] == 1
    assert audit["tripCountMismatchCount"] == 1
    assert {item["kind"] for item in audit["issues"]} == {
        "family_code_mismatch",
        "trip_count_mismatch",
    }


def test_route_catalog_audit_passes_clean_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "bff.services.route_catalog_audit.tokyu_bus_data_ready",
        lambda dataset_id: dataset_id == "tokyu_full",
    )
    monkeypatch.setattr(
        "bff.services.route_catalog_audit.route_trip_counts_by_day_type",
        lambda **_kwargs: {"route-a": {"WEEKDAY": 10, "SAT": 5}},
    )

    audit = audit_route_catalog_consistency(_base_scenario())

    assert audit["issueCount"] == 0
    assert audit["familyIssueCount"] == 0
    assert audit["tripCountMismatchCount"] == 0
