from __future__ import annotations

from pathlib import Path

import pandas as pd

from bff.errors import AppErrorCode
from bff.services.run_preparation import _build_prepared_scope_audit
from bff.services.run_preparation import _build_run_preparation
from bff.services.run_preparation import (
    _enrich_trip_distances_from_stop_sequences,
)


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


def test_prepared_scope_audit_uses_runtime_distance_fallback_and_keeps_strict_infeasible_signal() -> None:
    audit = _build_prepared_scope_audit(_prepared_payload(vehicle_count=1))

    assert audit["trip_distance_audit"]["zero_or_missing_count"] == 0
    assert audit["route_distance_audit"]["zero_or_missing_count"] == 0
    assert "trip_distance_zero_or_missing" not in audit["warning_codes"]
    assert "route_distance_zero_or_missing" not in audit["warning_codes"]
    assert audit["distance_join_diagnosis"]["classified_issue"] == "none"
    assert (
        audit["distance_join_diagnosis"]["route_distance_source_summary"]["route_distance_source_count"]
        > 0
    )
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
    compatibility = audit["vehicle_trip_compatibility_audit"]
    assert audit["formal_vehicle_trip_compatibility_ready"] is True
    assert compatibility["source_counts"] == {
        "trip_explicit_allowed_vehicle_types": 2
    }
    assert compatibility["allowed_trip_count_by_powertrain"] == {"BEV": 2}
    assert compatibility["explicit_all_selected_powertrains_assumption"] is True
    assert compatibility["matrix_rows"][0]["allowed_vehicle_ids"] == [
        "veh-1",
        "veh-2",
    ]
    assert compatibility["solver_powertrain_projection_exact"] is True
    assert len(compatibility["compatibility_matrix_sha256"]) == 64


def test_prepared_scope_audit_certifies_turnaround_buffer_sensitivity() -> None:
    payload = _prepared_payload(vehicle_count=2)
    payload["simulation_config"]["default_turnaround_min"] = 0
    payload["trips"] = [
        {
            "trip_id": "trip-1",
            "route_id": "route-a",
            "origin": "A",
            "destination": "B",
            "departure": "08:00",
            "arrival": "09:00",
            "distance_km": 12.0,
            "runtime_min": 60.0,
            "allowed_vehicle_types": ["BEV"],
        },
        {
            "trip_id": "trip-2",
            "route_id": "route-a",
            "origin": "B",
            "destination": "C",
            "departure": "09:05",
            "arrival": "10:00",
            "distance_km": 12.0,
            "runtime_min": 55.0,
            "allowed_vehicle_types": ["BEV"],
        },
    ]

    audit = _build_prepared_scope_audit(payload)

    sensitivity = audit["turnaround_buffer_sensitivity_audit"]
    assert sensitivity["schema_version"] == "turnaround_buffer_sensitivity_audit_v1"
    assert sensitivity["levels_minutes"] == [5, 10, 15]
    assert sensitivity["route_band_mode"] == "off"
    assert sensitivity["semantics"] == (
        "base_turnaround_plus_operational_buffer_before_deadhead"
    )
    assert [row["turnaround_buffer_min"] for row in sensitivity["rows"]] == [
        5,
        10,
        15,
    ]
    assert [row["dispatch_feasible_pair_count"] for row in sensitivity["rows"]] == [
        1,
        0,
        0,
    ]
    assert [row["relaxed_vehicle_lower_bound"] for row in sensitivity["rows"]] == [
        1,
        2,
        2,
    ]
    assert sensitivity["monotonic_checks"] == {
        "dispatch_feasible_pair_count_nonincreasing": True,
        "interval_feasible_pair_count_constant": True,
        "relaxed_vehicle_lower_bound_nondecreasing": True,
    }
    assert len(sensitivity["non_turnaround_control_sha256"]) == 64
    assert sensitivity["status"] == "VALID"
    assert sensitivity["transition_graph_evaluated_all_levels"] is True
    assert audit["formal_turnaround_sensitivity_ready"] is True
    assert "turnaround_buffer_sensitivity_invalid" not in audit["warning_codes"]


def test_prepared_scope_audit_fails_closed_when_transition_rebuild_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.optimization.common.builder.ProblemBuilder.build_from_scenario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic rebuild failure")
        ),
    )

    audit = _build_prepared_scope_audit(_prepared_payload(vehicle_count=2))

    assert audit["formal_transition_network_ready"] is False
    assert audit["route_band_off_transition_audit_checked"] is False
    assert audit["formal_turnaround_sensitivity_ready"] is False
    assert "prepared_scope_audit_failed" in audit["warning_codes"]
    assert "route_band_off_transition_audit_invalid" in audit["warning_codes"]
    assert "turnaround_buffer_sensitivity_invalid" in audit["warning_codes"]


def test_prepared_scope_audit_does_not_certify_buffer_sensitivity_without_trips() -> None:
    payload = _prepared_payload(vehicle_count=2)
    payload["trips"] = []

    audit = _build_prepared_scope_audit(payload)

    sensitivity = audit["turnaround_buffer_sensitivity_audit"]
    assert sensitivity["transition_graph_evaluated_all_levels"] is False
    assert sensitivity["status"] == "INVALID"
    assert audit["formal_turnaround_sensitivity_ready"] is False
    assert "turnaround_buffer_sensitivity_invalid" in audit["warning_codes"]


def test_prepared_scope_audit_blocks_implicit_all_powertrain_fallback() -> None:
    payload = _prepared_payload(vehicle_count=2)
    for trip in payload["trips"]:
        trip.pop("allowed_vehicle_types", None)

    audit = _build_prepared_scope_audit(payload)

    compatibility = audit["vehicle_trip_compatibility_audit"]
    assert audit["formal_vehicle_trip_compatibility_ready"] is False
    assert compatibility["implicit_fallback_trip_count"] == 2
    assert compatibility["source_counts"] == {
        "implicit_builder_all_powertrains_fallback": 2
    }
    assert (
        "vehicle_trip_compatibility_contract_incomplete"
        in audit["warning_codes"]
    )


def test_prepared_scope_audit_blocks_vehicle_level_permission_projection() -> None:
    payload = _prepared_payload(vehicle_count=2)
    for trip in payload["trips"]:
        trip.pop("allowed_vehicle_types", None)
    payload["vehicle_route_permissions"] = [
        {"routeId": "route-a", "vehicleId": "veh-1", "allowed": True},
        {"routeId": "route-a", "vehicleId": "veh-2", "allowed": False},
    ]

    audit = _build_prepared_scope_audit(payload)

    compatibility = audit["vehicle_trip_compatibility_audit"]
    assert compatibility["source_counts"] == {
        "explicit_vehicle_route_permissions": 2
    }
    assert compatibility["matrix_rows"][0]["allowed_vehicle_ids"] == ["veh-1"]
    assert compatibility["solver_powertrain_projection_exact"] is False
    assert compatibility["vehicle_level_restriction_trip_count"] == 2
    assert audit["formal_vehicle_trip_compatibility_ready"] is False


def test_trip_distance_uses_all_ordered_stop_coordinates() -> None:
    trips = [{"trip_id": "trip-1", "distance_km": 0.0}]
    stops = [
        {"id": "A", "lat": 35.0, "lon": 139.0},
        {"id": "B", "lat": 35.01, "lon": 139.01},
        {"id": "C", "lat": 35.0, "lon": 139.02},
    ]
    stop_sequences = [
        {"trip_id": "trip-1", "stop_id": "C", "sequence": 2},
        {"trip_id": "trip-1", "stop_id": "A", "sequence": 0},
        {"trip_id": "trip-1", "stop_id": "B", "sequence": 1},
    ]

    audit = _enrich_trip_distances_from_stop_sequences(
        trips,
        stops=stops,
        stop_sequences=stop_sequences,
    )

    assert trips[0]["distance_km"] > 0.0
    assert trips[0]["distance_source"] == (
        "trip_stop_sequence_polyline_haversine"
    )
    assert trips[0]["distance_stop_count"] == 3
    assert trips[0]["distance_segment_count"] == 2
    assert audit["source_counts"] == {
        "trip_stop_sequence_polyline_haversine": 1
    }
    assert audit["semantics"] == (
        "adjacent_stop_haversine_polyline_not_road_network_distance"
    )


def test_trip_distance_requires_complete_stop_coordinate_coverage() -> None:
    trips = [{"trip_id": "trip-1", "distance_km": 0.0}]
    stops = [
        {"id": "A", "lat": 35.0, "lon": 139.0},
        {"id": "C", "lat": 35.0, "lon": 139.02},
    ]
    stop_sequences = [
        {"trip_id": "trip-1", "stop_id": "A", "sequence": 0},
        {"trip_id": "trip-1", "stop_id": "B", "sequence": 1},
        {"trip_id": "trip-1", "stop_id": "C", "sequence": 2},
    ]

    audit = _enrich_trip_distances_from_stop_sequences(
        trips,
        stops=stops,
        stop_sequences=stop_sequences,
    )

    assert trips[0]["distance_km"] == 0.0
    assert "distance_source" not in trips[0]
    assert audit["source_counts"] == {"unresolved": 1}


def test_prepared_scope_audit_does_not_fail_when_route_band_block_samples_are_emitted() -> None:
    payload = _prepared_payload(vehicle_count=1)
    payload["scenario_overlay"] = {"solver_config": {"fixed_route_band_mode": True}}
    payload["routes"] = [
        {
            "id": "route-a",
            "routeCode": "A",
            "routeFamilyCode": "FAM-A",
            "direction": "outbound",
            "routeVariantType": "base",
            "distanceKm": 12.0,
        },
        {
            "id": "route-b",
            "routeCode": "B",
            "routeFamilyCode": "FAM-B",
            "direction": "outbound",
            "routeVariantType": "base",
            "distanceKm": 12.0,
        },
    ]
    payload["trips"] = [
        {
            "trip_id": "trip-1",
            "route_id": "route-a",
            "route_code": "A",
            "routeFamilyCode": "FAM-A",
            "direction": "outbound",
            "routeVariantType": "base",
            "origin": "A",
            "destination": "B",
            "departure": "08:00",
            "arrival": "09:00",
            "distance_km": 12.0,
            "runtime_min": 60.0,
            "allowed_vehicle_types": ["BEV"],
        },
        {
            "trip_id": "trip-2",
            "route_id": "route-b",
            "route_code": "B",
            "routeFamilyCode": "FAM-B",
            "direction": "outbound",
            "routeVariantType": "base",
            "origin": "B",
            "destination": "C",
            "departure": "09:30",
            "arrival": "10:00",
            "distance_km": 12.0,
            "runtime_min": 30.0,
            "allowed_vehicle_types": ["BEV"],
        },
    ]

    audit = _build_prepared_scope_audit(payload)

    assert "prepared_scope_audit_failed" not in audit["warning_codes"]
    assert audit["strict_coverage_precheck"]["checked"] is True
    assert "route_band_blocked" in audit["strict_coverage_precheck"]["blocked_transition_reason_counts"]
    assert "route_band_blocked" not in (
        audit["route_band_off_transition_audit"][
            "blocked_transition_reason_counts"
        ]
    )


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
            "day_type": "WEEKDAY",
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
