"""Twelve synthetic one-day scenarios for deployment checks, not research.

Four BEV service trips, explicit deadheads, one spare ICE, and one charger are
fictional inputs. Months are independent: no annual SOC or accounting claim.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

from src.optimization.common.date_series import content_hash, materialize_dated_timetable


def scenario_for_month(year: int, month: int, *, route_id: str = "smoke-route") -> dict:
    day = date(year, month, 15)
    day += timedelta(days=(1 - day.weekday()) % 7)
    service_date = day.isoformat()
    templates = [{
        "trip_id": f"smoke-trip-{i+1}", "route_id": route_id,
        "operator_id": "synthetic_cluster", "service_id": "WEEKDAY",
        "origin": "SMOKE_A", "destination": "SMOKE_B",
        "origin_stop_id": "SMOKE_A", "destination_stop_id": "SMOKE_B",
        "departure": f"{8+i:02d}:00", "arrival": f"{8+i:02d}:30",
        "distance_km": 10.0, "distance_source": "declared_synthetic_fixture",
        "allowed_vehicle_types": ["BEV"],
    } for i in range(4)]
    rows, contract = materialize_dated_timetable(
        templates, service_dates=[service_date], holiday_dates=[],
        source_provenance={"data_kind": "synthetic_deployment_test", "research_eligible": False})
    profiles = [{"date": service_date, "slot_minutes": 30, "capacity_factor_by_slot": [0.0]*48}]
    contract["pv_capacity_factor_rows_sha256"] = content_hash(profiles)
    return {
        "meta": {"id": f"cluster-smoke-{year}-{month:02d}",
                 "name": f"DIAGNOSTIC {year}-{month:02d} {route_id} synthetic cluster smoke"},
        "scenario_overlay": {"dataset_id": "cluster_smoke", "dataset_version": "synthetic-v1",
                             "depot_ids": ["SMOKE_DEPOT"], "route_ids": [route_id],
                             "solver_config": {"mode": "phase3_two_stage", "objective_mode": "total_cost"}},
        "dispatch_scope": {"depotId": "SMOKE_DEPOT", "serviceId": "WEEKDAY",
                           "effectiveRouteIds": [route_id],
                           "routeSelection": {"includeRouteIds": [route_id]}},
        "simulation_config": {
            "solver_mode": "phase3_two_stage", "service_date": service_date,
            "service_dates": [service_date], "planning_days": 1, "day_type": "WEEKDAY",
            "multi_day_input_mode": "dated_timetable_and_pv_v1", "date_series_contract": contract,
            "start_time": "00:00", "end_time": "23:59", "timestep_min": 30,
            "operation_time_window_enabled": False,
            "default_turnaround_min": 10, "initial_soc_percent": 80,
            "allow_same_day_depot_cycles": False, "max_depot_cycles_per_vehicle_per_day": 1,
            "min_soc_percent": 20, "max_soc_percent": 90,
            "final_soc_floor_percent": 20, "final_soc_target_percent": 80,
            "bev_terminal_soc_policy": "return_to_initial", "charging_power_model": "constant_power_v0",
            "enable_vehicle_cost": False, "enable_driver_cost": False, "enable_other_cost": False,
            "service_coverage_mode": "strict", "milp_max_successors_per_trip": None,
            "generate_vehicle_operation_diagrams": True,
            "depot_energy_assets": [{"depot_id": "SMOKE_DEPOT", "pv_enabled": False,
                                     "bess_enabled": False, "pv_generation_kwh_by_slot": [0.0]*48,
                                     "pv_capacity_factor_by_date": profiles}],
        },
        "depots": [{"id": "SMOKE_DEPOT", "name": "Synthetic depot", "depotAreaM2": 1000}],
        "routes": [{"id": route_id, "name": f"Synthetic {route_id} loop", "depotId": "SMOKE_DEPOT",
                    "distanceKm": 10.0, "distance_km": 10.0, "operator_id": "synthetic_cluster"}],
        "stops": [{"id": stop, "stop_id": stop, "name": stop}
                  for stop in ("SMOKE_DEPOT", "SMOKE_A", "SMOKE_B")],
        "vehicles": [
            {"id": "SMOKE_BEV", "type": "BEV", "depotId": "SMOKE_DEPOT", "enabled": True,
             "batteryKwh": 200.0, "energyConsumption": 1.316, "chargePowerKw": 90,
             "initialSoc": 0.8, "minSoc": 0.2, "maxSoc": 0.9,
             "compatibleChargerIds": ["smoke-charger"]},
            {"id": "SMOKE_ICE", "type": "ICE", "depotId": "SMOKE_DEPOT", "enabled": True,
             "fuelTankL": 100, "initialFuelL": 90, "fuelReserveL": 10, "fuelConsumptionLPerKm": 1/4.52},
        ],
        "chargers": [{"id": "smoke-charger", "siteId": "SMOKE_DEPOT", "powerKw": 90,
                      "simultaneousPorts": 1, "enabled": True}],
        "energy_price_profiles": [{"site_id": "SMOKE_DEPOT", "values": [20.0]*48}],
        "timetable_rows": rows, "stop_timetables": [],
        "deadhead_rules": [{"from_stop": origin, "to_stop": destination, "travel_time_min": 10}
                           for origin in ("SMOKE_DEPOT", "SMOKE_A", "SMOKE_B")
                           for destination in ("SMOKE_DEPOT", "SMOKE_A", "SMOKE_B") if origin != destination],
        "turnaround_rules": [],
    }


def prepare_month(year: int, month: int, dataset: Path, output: Path):
    from bff.store import scenario_store
    from bff.services.run_preparation import get_or_build_run_preparation
    scenario = scenario_for_month(year, month)
    scenario_store._save(scenario)
    scenario_id = scenario["meta"]["id"]
    scenario_store.set_dispatch_scope(scenario_id, {"depotId": "SMOKE_DEPOT", "serviceId": "WEEKDAY"})
    persisted = scenario_store.get_scenario_document(scenario_id)
    prepared = get_or_build_run_preparation(persisted, dataset, output / "prepared_inputs", None)
    if not prepared.is_valid:
        raise ValueError(f"Month {month} Prepare failed: {prepared.error}")
    payload = json.loads(prepared.solver_input_path.read_bytes())
    if len(payload["trips"]) != 4 or any(row["operator_id"] != "synthetic_cluster" for row in payload["trips"]):
        raise ValueError("Prepare changed the synthetic timetable scope")
    return scenario_id, prepared
