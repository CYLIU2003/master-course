from __future__ import annotations

from bff.services.run_preparation import _build_prepared_scope_audit


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

    # ProblemBuilder fills in distances via duration-based estimation (departure/arrival
    # times are present), so effective zero count is 0 after builder pass.
    assert audit["trip_distance_audit"]["zero_or_missing_count"] == 0
    assert audit["trip_distance_audit"].get("builder_estimated") is True
    # Route distance warning also cleared when all trip distances are filled.
    assert audit["route_distance_audit"]["zero_or_missing_count"] == 0
    assert "trip_distance_zero_or_missing" not in audit["warning_codes"]
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
