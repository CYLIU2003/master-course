from __future__ import annotations

from pathlib import Path

import pandas as pd

from bff.errors import AppErrorCode
from bff.services.run_preparation import _build_prepared_scope_audit
from bff.services.run_preparation import _build_run_preparation


def _prepared_payload(*, vehicle_count: int = 1) -> dict:
    vehicles = [
        {
            "id": f"veh-{idx + 1}",
            "depotId": "dep1",
            "type": "BEV",
            "batteryKwh": 320.0,
            "energyConsumption": 1.2,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "chargePowerKw": 90.0,
            "initialSoc": 0.8,
            "enabled": True,
        }
        for idx in range(vehicle_count)
    ]
    return {
        "prepared_input_id": "prepared-test",
        "scenario_id": "scenario-1",
        "service_ids": ["WEEKDAY"],
        "primary_depot_id": "dep1",
        "planning_days": 1,
        "scope": {
            "primary_depot_id": "dep1",
            "service_ids": ["WEEKDAY"],
        },
        "dispatch_scope": {
            "depotSelection": {"mode": "include", "depotIds": ["dep1"], "primaryDepotId": "dep1"},
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {"includeShortTurn": True, "includeDepotMoves": True, "includeDeadhead": True},
            "depotId": "dep1",
            "serviceId": "WEEKDAY",
        },
        "scenario_overlay": {"solver_config": {"objective_mode": "total_cost"}},
        "simulation_config": {
            "service_coverage_mode": "strict",
            "allow_partial_service": False,
            "planning_days": 1,
            "start_time": "05:00",
            "end_time": "23:00",
            "initial_soc": 0.8,
            "soc_min": 0.2,
            "soc_max": 0.9,
        },
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [{"id": "route-a", "distanceKm": 0.0}],
        "vehicles": vehicles,
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90.0}],
        "trips": [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "09:00",
                "distance_km": 0.0,
                "runtime_min": 60.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "trip-2",
                "route_id": "route-a",
                "origin": "C",
                "destination": "D",
                "departure": "08:30",
                "arrival": "09:30",
                "distance_km": 0.0,
                "runtime_min": 60.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        "stop_time_sequences": [],
        "stops": [],
    }


def test_prepared_scope_audit_flags_zero_distance_and_strict_infeasible_scope() -> None:
    audit = _build_prepared_scope_audit(_prepared_payload(vehicle_count=1))

    assert audit["trip_distance_audit"]["zero_or_missing_count"] == 2
    assert audit["route_distance_audit"]["zero_or_missing_count"] == 1
    assert "trip_distance_zero_or_missing" in audit["warning_codes"]
    assert audit["strict_coverage_precheck"]["checked"] is True
    assert audit["strict_coverage_precheck"]["infeasible"] is True
    assert audit["strict_coverage_precheck"]["relaxed_vehicle_lower_bound"] == 2
    assert "strict_coverage_precheck_infeasible" in audit["warning_codes"]
    assert any("strict coverage needs at least 2 vehicles" in warning for warning in audit["warnings"])


def test_prepared_scope_audit_relaxes_warning_when_vehicle_lower_bound_is_met() -> None:
    audit = _build_prepared_scope_audit(_prepared_payload(vehicle_count=2))

    assert audit["strict_coverage_precheck"]["checked"] is True
    assert audit["strict_coverage_precheck"]["infeasible"] is False
    assert audit["strict_coverage_precheck"]["relaxed_vehicle_lower_bound"] == 2


def test_run_preparation_fails_hard_when_all_scope_distances_are_missing(monkeypatch) -> None:
    scenario = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {"solver_config": {"fixed_route_band_mode": False}},
        "simulation_config": {
            "planning_days": 1,
            "service_dates": ["2025-08-05"],
            "service_date": "2025-08-05",
        },
        "dispatch_scope": {
            "serviceId": "WEEKDAY",
            "depotId": "dep1",
            "routeSelection": {"includeRouteIds": ["route-a"]},
        },
    }
    scope = type(
        "Scope",
        (),
        {
            "depot_ids": ["dep1"],
            "route_ids": ["route-a"],
            "service_ids": ["WEEKDAY"],
            "service_date": "2025-08-05",
            "route_selectors": ["route-a"],
        },
    )()
    trips_df = pd.DataFrame(
        [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "09:00",
                "distance_km": 0.0,
                "service_id": "WEEKDAY",
            }
        ]
    )
    route_df = pd.DataFrame([{"id": "route-a", "distanceKm": 0.0}])

    monkeypatch.setattr(
        "bff.services.run_preparation._load_scope_frames",
        lambda *args, **kwargs: (trips_df, pd.DataFrame(), "built_parquet"),
    )
    monkeypatch.setattr("bff.services.run_preparation._load_optional_stops", lambda *args, **kwargs: [])
    monkeypatch.setattr("bff.services.run_preparation._load_stop_sequences", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "bff.services.run_preparation.audit_route_catalog_consistency",
        lambda *_args, **_kwargs: {"checkedRouteCount": 0},
    )

    result = _build_run_preparation(
        scenario,
        Path("C:/tmp"),
        Path("C:/tmp"),
        route_df,
        "scenario-hash",
        scope=scope,
        scope_payload={
            "scenario_id": "scenario-1",
            "dataset_id": "tokyu_core",
            "dataset_version": "v1",
            "operator_id": "tokyu",
            "selected_depot_ids": ["dep1"],
            "selected_route_ids": ["route-a"],
            "route_selectors": ["route-a"],
            "service_ids": ["WEEKDAY"],
            "service_date": "2025-08-05",
            "service_dates": ["2025-08-05"],
            "day_type": "WEEKDAY",
            "planning_days": 1,
            "trip_type_flags": {},
            "swap_flags": {},
            "fixed_route_band_mode": False,
            "allow_partial_service": False,
        },
        scope_hash="scope-hash",
    )

    assert result.is_valid is False
    assert result.error_code == AppErrorCode.PREPARE_DISTANCE_JOIN_BROKEN
    assert result.error is not None
    assert result.solver_input_path is None
    assert result.scope_summary["prepared_scope_audit"]["distance_join_broken"] is True
