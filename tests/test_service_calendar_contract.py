from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization import OptimizationConfig, ProblemBuilder
from src.optimization.common.service_calendar import (
    validate_service_calendar_contract,
)


def _weekday_row() -> dict[str, str]:
    return {
        "trip_id": "odpt.BusTimetable:Example.Weekday.0800",
        "route_id": "route-1",
        "origin": "depot",
        "destination": "terminal",
        "departure": "08:00",
        "arrival": "08:30",
    }


def test_research_calendar_rejects_sunday_with_weekday_timetable() -> None:
    with pytest.raises(
        ValueError,
        match="service_date_timetable_day_type_mismatch",
    ):
        validate_service_calendar_contract(
            service_date_text="2025-08-10",
            timetable_rows=[_weekday_row()],
            scenario_metadata={
                "simulation_config": {
                    "service_date": "2025-08-10",
                }
            },
            strict=True,
        )


def test_explicit_fixed_weekday_pv_counterfactual_waives_only_sunday_mismatch() -> None:
    result = validate_service_calendar_contract(
        service_date_text="2025-08-10",
        timetable_rows=[_weekday_row()],
        scenario_metadata={
            "simulation_config": {
                "service_date": "2025-08-10",
                "allow_fixed_weekday_timetable_pv_counterfactual": True,
                "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
            }
        },
        strict=True,
    )

    assert result["status"] == "WAIVED_BY_EXPERIMENT_POLICY"
    assert result["calendar_validation_status"] == "WAIVED_BY_EXPERIMENT_POLICY"
    assert result["waiver"]["scope"] == (
        "weekday_timetable_on_sunday_for_pv_only_counterfactual"
    )


def test_fixed_weekday_pv_counterfactual_does_not_waive_a_saturday() -> None:
    with pytest.raises(ValueError, match="service_date_timetable_day_type_mismatch"):
        validate_service_calendar_contract(
            service_date_text="2025-08-09",
            timetable_rows=[_weekday_row()],
            scenario_metadata={
                "simulation_config": {
                    "service_date": "2025-08-09",
                    "allow_fixed_weekday_timetable_pv_counterfactual": True,
                    "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
                }
            },
            strict=True,
        )


def test_counterfactual_keeps_service_date_and_separate_weather_date() -> None:
    result = validate_service_calendar_contract(
        service_date_text="2025-08-05",
        timetable_rows=[_weekday_row()],
        scenario_metadata={
            "simulation_config": {
                "service_date": "2025-08-05",
                "weather_observation_date": "2025-08-10",
                "weather_profile_source": "solcast-curve-sha256",
                "comparison_type": "counterfactual_weather_profile",
            }
        },
        strict=True,
    )

    assert result["status"] == "OK"
    assert result["comparison_type"] == "counterfactual_weather_profile"
    assert result["service_date"] == "2025-08-05"
    assert result["weather_observation_date"] == "2025-08-10"
    assert result["service_date_forecast_claim"] is False


def test_combined_weekend_calendar_token_accepts_saturday_service() -> None:
    row = dict(_weekday_row())
    row["trip_id"] = "odpt.BusTimetable:Example.SaturdayHoliday.0800"

    result = validate_service_calendar_contract(
        service_date_text="2025-08-09",
        timetable_rows=[row],
        scenario_metadata={
            "simulation_config": {
                "service_date": "2025-08-09",
            }
        },
        strict=True,
    )

    assert result["status"] == "OK"
    assert result["expected_service_day_type"] == "saturday"
    assert result["observed_timetable_day_types"] == ["weekend_or_holiday"]


def test_declared_weekday_holiday_accepts_holiday_service() -> None:
    row = dict(_weekday_row())
    row["trip_id"] = "odpt.BusTimetable:Example.Holiday.0800"

    result = validate_service_calendar_contract(
        service_date_text="2025-08-11",
        timetable_rows=[row],
        scenario_metadata={
            "simulation_config": {
                "service_date": "2025-08-11",
                "holiday_dates": ["2025-08-11"],
            }
        },
        strict=True,
    )

    assert result["status"] == "OK"
    assert result["service_date_weekday"] == "Monday"
    assert result["service_date_declared_holiday"] is True


def test_builder_persists_verified_service_calendar_contract() -> None:
    trip = Trip(
        trip_id=_weekday_row()["trip_id"],
        route_id="route-1",
        origin="depot",
        destination="terminal",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[trip],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_consumption_l_per_km=0.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="calendar-contract",
        scenario_metadata={
            "simulation_config": {
                "service_date": "2025-08-05",
            },
            "timetable_rows": [_weekday_row()],
        },
        config=OptimizationConfig(research_run=True),
        vehicle_counts={"ICE": 1},
    )

    validation = problem.metadata["service_calendar_validation"]
    assert validation["status"] == "OK"
    assert validation["expected_service_day_type"] == "weekday"
    assert validation["observed_timetable_day_types"] == ["weekday"]


def test_research_builder_rejects_declared_fleet_inventory_mismatch() -> None:
    trip = Trip(
        trip_id=_weekday_row()["trip_id"],
        route_id="route-1",
        origin="depot",
        destination="terminal",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[trip],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_consumption_l_per_km=0.2,
            )
        },
    )

    with pytest.raises(
        ValueError,
        match=r"ICE:expected=26,actual=25",
    ):
        ProblemBuilder().build_from_dispatch(
            context,
            scenario_id="fleet-contract",
            scenario_metadata={
                "simulation_config": {
                    "service_date": "2025-08-05",
                    "research_vehicle_inventory": {
                        "BEV": 35,
                        "ICE": 26,
                    },
                },
                "timetable_rows": [_weekday_row()],
            },
            config=OptimizationConfig(research_run=True),
            vehicle_counts={"BEV": 35, "ICE": 25},
        )
