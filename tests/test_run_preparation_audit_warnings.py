from __future__ import annotations

from bff.services.run_preparation import _route_catalog_audit_warnings


def test_route_catalog_audit_warnings_summarize_clean_audit() -> None:
    warnings = _route_catalog_audit_warnings(
        {
            "checkedRouteCount": 10,
            "issueCount": 0,
            "familyIssueCount": 0,
            "tripCountMismatchCount": 0,
            "actualCountsSource": "tokyu_bus_data",
        }
    )

    assert warnings == [
        "Route catalog audit passed: checked=10, family_issues=0, trip_count_mismatches=0, source=tokyu_bus_data"
    ]


def test_route_catalog_audit_warnings_include_sample_details() -> None:
    warnings = _route_catalog_audit_warnings(
        {
            "checkedRouteCount": 3,
            "issueCount": 2,
            "familyIssueCount": 1,
            "tripCountMismatchCount": 1,
            "actualCountsSource": "tokyu_bus_data",
            "issues": [
                {"kind": "family_code_mismatch", "routeCode": "東98"},
                {"kind": "trip_count_mismatch", "routeId": "route-b"},
            ],
        }
    )

    assert warnings[0].startswith("Route catalog audit found inconsistencies:")
    assert "family_code_mismatch (東98)" in warnings[1]
    assert "trip_count_mismatch (route-b)" in warnings[2]
