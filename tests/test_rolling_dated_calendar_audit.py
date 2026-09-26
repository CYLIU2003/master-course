from copy import deepcopy

import pytest

from bff.services.optimization_run.rolling_chain import _calendar_audit


def validation():
    return {"schema_version": "service_calendar_validation_v2", "status": "OK",
            "calendar_policy": "fixed_version_date_specific_calendar", "errors": [],
            "unknown_timetable_row_count": 0, "service_dates": ["2025-02-03", "2025-02-04"],
            "days": [{"service_date": "2025-02-03"}, {"service_date": "2025-02-04"}],
            "timetable_rows_sha256": "a" * 64}


def test_verified_dated_calendar_does_not_compare_monday_to_legacy_sat_selector():
    result = _calendar_audit(service_date="2025-02-03", service_id="SAT",
                             problem_metadata={"service_calendar_validation": validation()})
    assert result["calendar_validation_status"] == "OK"
    assert result["service_id_scope"] == "per_date_not_single_service_id"
    assert result["requested_service_id"] == "SAT"


@pytest.mark.parametrize("field,value", [("status", "ERROR"), ("errors", ["bad row"]),
    ("unknown_timetable_row_count", 1), ("days", []), ("timetable_rows_sha256", ""),
    ("service_dates", ["2025-02-04"])])
def test_invalid_dated_evidence_cannot_fall_back_to_matching_weekday(field, value):
    payload = deepcopy(validation()); payload[field] = value
    result = _calendar_audit(service_date="2025-02-03", service_id="WEEKDAY",
                             problem_metadata={"service_calendar_validation": payload})
    assert result["calendar_validation_status"] == "ERROR"
