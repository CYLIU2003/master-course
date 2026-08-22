from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from bff.routers import optimization
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    DutyLeg,
    Trip,
    VehicleDuty,
)
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationEngineResult,
    OptimizationMode,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.engine import OptimizationEngine
from src.optimization.common.result import ResultSerializer


def _dispatch_trip() -> Trip:
    return Trip(
        trip_id="t1",
        route_id="route-1",
        origin="Depot Bay",
        destination="Terminal Bay",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-depot",
        destination_stop_id="stop-terminal",
        route_family_code="R1",
        direction="outbound",
        route_variant_type="main_outbound",
    )


def _problem_and_result() -> tuple[CanonicalOptimizationProblem, OptimizationEngineResult, dict]:
    dispatch_trip = _dispatch_trip()
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            timestep_min=30,
            horizon_start="08:00",
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-04-05",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={},
        ),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="route-1",
                origin="Depot Bay",
                destination="Terminal Bay",
                departure_min=480,
                arrival_min=510,
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=6.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep1",
                initial_soc=200.0,
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep1", name="Depot 1", import_limit_kw=15.0),),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        depot_energy_assets={
            "dep1": DepotEnergyAsset(
                depot_id="dep1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(2.0, 1.0),
            )
        },
        metadata={"service_date": "2026-04-05"},
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=dispatch_trip, deadhead_from_prev_min=0),),
            ),
        ),
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=1,
                charger_id="chg-1",
                charge_kw=20.0,
                charging_depot_id="dep1",
            ),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep1": {0: 1.0}},
        pv_to_bus_kwh_by_depot_slot={"dep1": {0: 0.5}},
        pv_to_bess_kwh_by_depot_slot={"dep1": {1: 0.2}},
        vehicle_soc_kwh_by_vehicle_slot={"veh-1": {0: 200.0, 1: 194.0}},
        served_trip_ids=("t1",),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.ALNS,
        solver_status="feasible",
        objective_value=123.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"energy_cost": 10.0, "total_cost": 123.0},
        solver_metadata={"objective_mode": "total_cost", "solve_time_sec": 1.5},
    )
    scenario = {
        "simulation_config": {"enable_vehicle_diagram_output": False},
        "trips": [
            {
                "trip_id": "t1",
                "route_id": "route-1",
                "routeFamilyCode": "R1",
                "origin": "Depot Bay",
                "destination": "Terminal Bay",
                "departure": "08:00",
                "arrival": "08:30",
            }
        ],
    }
    return problem, result, scenario


def test_result_serializer_restores_complete_persisted_plan_without_reoptimization() -> None:
    problem, result, _scenario = _problem_and_result()

    serialized = ResultSerializer.serialize_plan(result.plan)
    restored = ResultSerializer.deserialize_plan(problem, serialized)

    assert ResultSerializer.serialize_plan(restored) == serialized
    assert restored.charging_slots == result.plan.charging_slots
    assert restored.grid_to_bus_kwh_by_depot_slot == result.plan.grid_to_bus_kwh_by_depot_slot
    assert restored.pv_to_bus_kwh_by_depot_slot == result.plan.pv_to_bus_kwh_by_depot_slot
    assert restored.vehicle_soc_kwh_by_vehicle_slot == result.plan.vehicle_soc_kwh_by_vehicle_slot
    assert restored.metadata == result.plan.metadata


def test_bff_canonical_export_counts_each_ice_movement_once(
    tmp_path: Path,
) -> None:
    """Exercise the production BFF canonical-export/accounting call chain."""

    dispatch_trips = (
        Trip(
            trip_id="ice-t1",
            route_id="route-1",
            origin="stop-a",
            destination="stop-b",
            departure_time="08:00",
            arrival_time="08:30",
            distance_km=5.0,
            allowed_vehicle_types=("ICE",),
        ),
        Trip(
            trip_id="ice-t2",
            route_id="route-1",
            origin="stop-c",
            destination="stop-d",
            departure_time="09:30",
            arrival_time="10:00",
            distance_km=7.0,
            allowed_vehicle_types=("ICE",),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="movement-e2e",
            timestep_min=30,
            horizon_start="00:00",
            objective_mode="total_cost",
            diesel_price_yen_per_l=100.0,
            ice_co2_kg_per_l=2.58,
        ),
        dispatch_context=DispatchContext(
            service_date="2026-07-27",
            trips=list(dispatch_trips),
            turnaround_rules={},
            deadhead_rules={
                ("stop-d", "dep1"): DeadheadRule(
                    from_stop="stop-d",
                    to_stop="dep1",
                    travel_time_min=30,
                )
            },
            vehicle_profiles={},
        ),
        trips=(
            ProblemTrip(
                trip_id="ice-t1",
                route_id="route-1",
                origin="stop-a",
                destination="stop-b",
                departure_min=480,
                arrival_min=510,
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
                fuel_l_by_vehicle_type={"ICE": 0.7},
            ),
            ProblemTrip(
                trip_id="ice-t2",
                route_id="route-1",
                origin="stop-c",
                destination="stop-d",
                departure_min=570,
                arrival_min=600,
                distance_km=7.0,
                allowed_vehicle_types=("ICE",),
                fuel_l_by_vehicle_type={"ICE": 0.9},
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=0.2,
                co2_emission_kg_per_l=2.58,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot_id="dep1",
                fuel_consumption_l_per_km=0.2,
            ),
        ),
        depots=(
            ProblemDepot(depot_id="dep1", name="Depot 1", import_limit_kw=100.0),
        ),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=20.0)
            for index in range(48)
        ),
        metadata={
            "service_date": "2026-07-27",
            "deadhead_speed_kmh": 18.0,
        },
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="ice-duty-1",
                vehicle_type="ICE",
                legs=(
                    DutyLeg(
                        trip=dispatch_trips[0],
                        deadhead_from_prev_min=10,
                    ),
                    DutyLeg(
                        trip=dispatch_trips[1],
                        deadhead_from_prev_min=20,
                    ),
                ),
            ),
        ),
        served_trip_ids=("ice-t1", "ice-t2"),
        metadata={"duty_vehicle_map": {"ice-duty-1": "ice-1"}},
    )
    expected_fuel_l = 0.7 + 0.9 + (3.0 + 6.0 + 9.0) * 0.2
    result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="feasible",
        objective_value=expected_fuel_l * 100.0,
        plan=plan,
        feasible=True,
        cost_breakdown={
            "fuel_cost": expected_fuel_l * 100.0,
            "ice_co2_kg": expected_fuel_l * 2.58,
            "total_co2_kg": expected_fuel_l * 2.58,
            "total_cost": expected_fuel_l * 100.0,
        },
        solver_metadata={
            "objective_mode": "total_cost",
            "objective_is_actual_cost": True,
            "research_run": False,
        },
    )
    scenario = {
        "operator_id": "operator-1",
        "simulation_config": {
            "enable_vehicle_diagram_output": False,
            "service_date": "2026-07-27",
        },
        "scenario_overlay": {
            "cost_coefficients": {
                "diesel_price_per_l": 100.0,
            }
        },
        "trips": [
            {
                "trip_id": trip.trip_id,
                "route_id": trip.route_id,
                "origin": trip.origin,
                "destination": trip.destination,
                "departure": trip.departure_time,
                "arrival": trip.arrival_time,
            }
            for trip in dispatch_trips
        ],
    }

    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="movement-e2e",
        output_dir=str(tmp_path),
    )

    with (tmp_path / "graph" / "movement_event_ledger.json").open(
        encoding="utf-8"
    ) as handle:
        movement_rows = json.load(handle)
    assert [row["event_type"] for row in movement_rows] == [
        "startup",
        "connection",
        "terminal_return",
    ]
    assert sum(row["distance_km"] for row in movement_rows) == pytest.approx(
        18.0
    )
    assert sum(row["ice_fuel_liter"] for row in movement_rows) == pytest.approx(
        3.6
    )

    with (tmp_path / "graph" / "vehicle_slot_ledger.json").open(
        encoding="utf-8"
    ) as handle:
        slot_rows = json.load(handle)
    assert sum(row["ice_fuel_liter"] for row in slot_rows) == pytest.approx(
        expected_fuel_l
    )
    assert sum(row["ice_co2_kg"] for row in slot_rows) == pytest.approx(
        expected_fuel_l * 2.58
    )
    referenced_event_ids = {
        event_id
        for row in slot_rows
        for event_id in str(row.get("source_event_ids") or "").split(";")
        if event_id
    }
    assert {
        row["event_id"] for row in movement_rows
    }.issubset(referenced_event_ids)
    with (tmp_path / "graph" / "trip_assignment.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        trip_rows = list(csv.DictReader(handle))
    assert all(float(row["deadhead_after_km"]) == 0.0 for row in trip_rows)
    with (tmp_path / "graph" / "data_flow_validation.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        validation_by_name = {
            row["check_name"]: row for row in csv.DictReader(handle)
        }
    for check_name in (
        "solver_fuel_cost_matches_physical_fuel_ledger",
        "solver_ice_co2_matches_physical_fuel_ledger",
    ):
        assert validation_by_name[check_name]["status"] == "OK"
    assert artifacts["accounting_summary"]["fuel_cost_jpy"] == pytest.approx(
        expected_fuel_l * 100.0
    )
    assert artifacts["accounting_summary"]["movement_event_count"] == 3
    assert artifacts["accounting_summary"][
        "movement_ice_fuel_liter"
    ] == pytest.approx(3.6)
    assert artifacts["accounting_summary"]["movement_event_id_unique"] is True


def test_normalize_postsolve_plan_preserves_pre_postsolve_source_flow_context() -> None:
    engine = OptimizationEngine()
    problem = SimpleNamespace(
        scenario=SimpleNamespace(timestep_min=30),
        metadata={},
        vehicles=(),
        chargers=(),
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=0,
                charger_id="grid:dep1",
                charge_kw=10.0,
                charging_depot_id="dep1",
            ),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep1": {0: 1.0}},
        pv_to_bus_kwh_by_depot_slot={"dep1": {0: 0.5}},
        metadata={},
    )

    with (
        mock.patch.object(engine, "_reassign_vehicle_fragments", return_value=plan),
        mock.patch("src.optimization.engine.apply_opportunistic_topup", side_effect=lambda _problem, current_plan: current_plan),
    ):
        normalized_plan, *_rest = engine._normalize_postsolve_plan(problem, plan)

    snapshot = normalized_plan.metadata["canonical_source_flow_context"]
    assert snapshot["source_provenance_exact"] is True
    assert snapshot["grid_to_bus_kwh_by_depot_slot"] == {"dep1": {0: 1.0}}
    assert snapshot["pv_to_bus_kwh_by_depot_slot"] == {"dep1": {0: 0.5}}
    assert snapshot["charging_slot_signatures"] == (("veh-1", 0, "grid:dep1", "dep1"),)


def test_canonical_charging_output_payload_uses_preserved_source_flow_context() -> None:
    problem, result, _scenario = _problem_and_result()
    preserved_context = {
        "grid_to_bus_kwh_by_depot_slot": {"dep1": {0: 1.0}},
        "pv_to_bus_kwh_by_depot_slot": {"dep1": {0: 0.5}},
        "bess_to_bus_kwh_by_depot_slot": {},
        "pv_to_bess_kwh_by_depot_slot": {},
        "grid_to_bess_kwh_by_depot_slot": {},
        "pv_curtail_kwh_by_depot_slot": {},
        "bess_soc_kwh_by_depot_slot": {},
        "contract_over_limit_kwh_by_depot_slot": {},
        "source_provenance_exact": True,
        "charging_slot_signatures": (("veh-1", 0, "grid:dep1", "dep1"),),
    }
    plan = replace(
        result.plan,
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=0,
                charger_id="grid:dep1",
                charge_kw=20.0,
                charging_depot_id="dep1",
            ),
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=1,
                charger_id="chg-topup",
                charge_kw=10.0,
                charging_depot_id="dep1",
            ),
        ),
        grid_to_bus_kwh_by_depot_slot={},
        pv_to_bus_kwh_by_depot_slot={},
        bess_to_bus_kwh_by_depot_slot={},
        pv_to_bess_kwh_by_depot_slot={},
        grid_to_bess_kwh_by_depot_slot={},
        pv_curtail_kwh_by_depot_slot={},
        bess_soc_kwh_by_depot_slot={},
        contract_over_limit_kwh_by_depot_slot={},
        metadata={
            **dict(result.plan.metadata or {}),
            "canonical_source_flow_context": preserved_context,
        },
    )
    result = replace(result, plan=plan)

    payload = optimization._canonical_charging_output_payload(problem, result)

    assert payload["summary"]["totals"]["grid_to_bus_kwh"] == 6.0
    assert payload["summary"]["totals"]["pv_to_bus_kwh"] == 0.5
    assert payload["summary"]["source_provenance_exact"] is False


def test_normalize_postsolve_plan_keeps_feasible_exact_milp_source_trace() -> None:
    problem, result, _scenario = _problem_and_result()
    plan = replace(
        result.plan,
        metadata={**dict(result.plan.metadata or {}), "source": "milp_gurobi"},
    )
    engine = OptimizationEngine()

    with (
        mock.patch.object(engine._feasibility, "evaluate", return_value=SimpleNamespace(feasible=True)),
        mock.patch.object(engine, "_reassign_vehicle_fragments") as reassign,
        mock.patch("src.optimization.engine.apply_opportunistic_topup") as topup,
    ):
        normalized_plan, assignment_rebuilt, charging_recomputed, soc_repaired, topup_applied = engine._normalize_postsolve_plan(
            problem,
            plan,
            mode=OptimizationMode.MILP,
            solver_metadata={"supports_exact_milp": True},
        )

    reassign.assert_not_called()
    topup.assert_not_called()
    assert assignment_rebuilt is False
    assert charging_recomputed is False
    assert soc_repaired is False
    assert topup_applied is False
    assert normalized_plan.metadata["source_provenance_exact"] is True
    assert normalized_plan.metadata["derived_source_split"] is False
    assert normalized_plan.metadata["canonical_source_flow_context"]["source_provenance_exact"] is True


def test_normalize_postsolve_plan_noops_when_repair_disabled() -> None:
    problem, result, _scenario = _problem_and_result()
    engine = OptimizationEngine()

    with (
        mock.patch.object(engine, "_reassign_vehicle_fragments") as reassign,
        mock.patch("src.optimization.engine.apply_opportunistic_topup") as topup,
    ):
        normalized_plan, assignment_rebuilt, charging_recomputed, soc_repaired, topup_applied = engine._normalize_postsolve_plan(
            problem,
            result.plan,
            mode=OptimizationMode.MILP,
            solver_metadata={"supports_exact_milp": True},
            allow_postsolve_repair=False,
        )

    reassign.assert_not_called()
    topup.assert_not_called()
    assert normalized_plan.duties == result.plan.duties
    assert assignment_rebuilt is False
    assert charging_recomputed is False
    assert soc_repaired is False
    assert topup_applied is False
    assert normalized_plan.metadata["postsolve_repair_allowed"] is False


def test_vehicle_charging_source_timeseries_uses_vehicle_provenance_flag() -> None:
    problem, result, _scenario = _problem_and_result()
    plan = replace(
        result.plan,
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=0,
                charger_id="grid:dep1",
                charge_kw=12.0,
                charging_depot_id="dep1",
            ),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep1": {0: 6.0}},
        pv_to_bus_kwh_by_depot_slot={},
        metadata={
            **dict(result.plan.metadata or {}),
            "vehicle_source_provenance_exact": True,
        },
    )
    result = replace(result, plan=plan)

    rows = optimization._research_vehicle_charging_source_timeseries_rows(
        problem=problem,
        engine_result=result,
        base_date=date(2026, 4, 5),
    )

    charged_rows = [row for row in rows if row["time"] == "08:00"]
    assert charged_rows
    assert charged_rows[0]["source_provenance_exact"] is True
    assert charged_rows[0]["depot_source_provenance_exact"] is True
    assert "exact MILP" in charged_rows[0]["vehicle_source_split_note"]


def test_normalize_postsolve_plan_derives_pv_bess_source_split_without_milp_flow() -> None:
    problem, result, _scenario = _problem_and_result()
    asset = replace(
        problem.depot_energy_assets["dep1"],
        pv_generation_kwh_by_slot=(10.0, 0.0),
        bess_enabled=True,
        bess_energy_kwh=10.0,
        bess_power_kw=10.0,
        bess_initial_soc_kwh=0.0,
        bess_soc_min_kwh=0.0,
        bess_soc_max_kwh=10.0,
        bess_charge_efficiency=1.0,
        bess_discharge_efficiency=1.0,
    )
    problem = replace(
        problem,
        scenario=replace(problem.scenario, timestep_min=60),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        depot_energy_assets={"dep1": asset},
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=1,
                charger_id="grid:dep1",
                charge_kw=6.0,
                charging_depot_id="dep1",
            ),
        ),
        metadata=dict(result.plan.metadata or {}),
    )
    engine = OptimizationEngine()

    with (
        mock.patch.object(engine, "_reassign_vehicle_fragments", return_value=plan),
        mock.patch("src.optimization.engine.apply_opportunistic_topup", side_effect=lambda _problem, current_plan: current_plan),
    ):
        normalized_plan, *_rest = engine._normalize_postsolve_plan(problem, plan)

    assert normalized_plan.pv_to_bess_kwh_by_depot_slot == {"dep1": {0: 10.0}}
    assert normalized_plan.bess_to_bus_kwh_by_depot_slot == {"dep1": {1: 6.0}}
    assert normalized_plan.grid_to_bus_kwh_by_depot_slot == {}
    assert normalized_plan.metadata["derived_source_split"] is True
    assert normalized_plan.metadata["canonical_source_flow_context"]["source_provenance_exact"] is False


def test_canonical_charging_output_reports_warning_only_contract_overage_when_penalty_zero() -> None:
    problem, result, _scenario = _problem_and_result()
    plan = AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep1": {0: 10.0}},
        served_trip_ids=("t1",),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )
    result = replace(
        result,
        plan=plan,
        cost_breakdown={"contract_overage_cost": 0.0},
        solver_metadata={
            **dict(result.solver_metadata or {}),
            "enable_contract_overage_penalty": True,
            "contract_overage_penalty_yen_per_kwh": 0.0,
        },
    )

    payload = optimization._canonical_charging_output_payload(problem, result)
    totals = payload["summary"]["totals"]

    assert totals["contract_limit_exceeded"] is True
    assert totals["contract_overage_policy"] == "warning_only"
    assert totals["contract_overage_cost_jpy"] == 0.0
    assert "warning_only" in totals["contract_overage_warning"]


def test_canonical_graph_exports_write_legacy_graph_files_even_when_diagrams_disabled(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()

    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )

    assert artifacts["enabled"] is True
    assert (tmp_path / "graph" / "vehicle_timeline.csv").exists()
    assert (tmp_path / "graph" / "soc_events.csv").exists()
    assert (tmp_path / "graph" / "depot_power_timeseries.csv").exists()
    assert (tmp_path / "graph" / "grid_import_timeseries.csv").exists()
    assert (tmp_path / "graph" / "pv_generation_timeseries.csv").exists()
    assert (tmp_path / "graph" / "energy_flow_timeseries.csv").exists()
    assert (tmp_path / "graph" / "bus_charging_total_timeseries.csv").exists()
    assert (tmp_path / "graph" / "vehicle_soc_timeseries.csv").exists()
    fuel_summary_path = tmp_path / "graph" / "fuel_summary.csv"
    fuel_canonical_path = tmp_path / "graph" / "fuel_canonical_ledger.csv"
    fuel_timeseries_path = tmp_path / "graph" / "fuel_timeseries.csv"
    assert fuel_summary_path.exists()
    assert fuel_canonical_path.exists()
    assert fuel_timeseries_path.exists()
    for fuel_path in (
        fuel_summary_path,
        fuel_canonical_path,
        fuel_timeseries_path,
    ):
        # This fixture is all-BEV. Empty fuel relations must retain their CSV
        # schema instead of becoming ambiguous zero-byte artifacts.
        assert fuel_path.stat().st_size > 0
        with fuel_path.open(encoding="utf-8", newline="") as handle:
            assert list(csv.DictReader(handle)) == []
    assert (tmp_path / "graph" / "trip_assignment.csv").exists()
    refuel_events_path = tmp_path / "graph" / "refuel_events.csv"
    assert refuel_events_path.exists()
    # The fixture has no ICE refueling.  A valid zero-event graph export still
    # needs a CSV header so the manifest-backed artifact audit can distinguish
    # it from a missing or truncated file.
    with refuel_events_path.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
    assert refuel_events_path.read_text(encoding="utf-8").strip() == (
        "vehicle_id,slot_index,time_hhmm,refuel_liters,location_id"
    )
    assert (tmp_path / "graph" / "cost_breakdown.json").exists()
    assert (tmp_path / "graph" / "canonical_cost_ledger.json").exists()
    assert (tmp_path / "graph" / "kpi_summary.json").exists()
    assert (tmp_path / "graph" / "charging_source_provenance.json").exists()
    assert (tmp_path / "graph" / "manifest.json").exists()
    assert artifacts["manifest_path"] == "graph/route_band_diagrams/manifest.json"
    route_band_manifest = json.loads((tmp_path / "graph" / "route_band_diagrams" / "manifest.json").read_text(encoding="utf-8"))
    assert route_band_manifest["entries"]
    assert route_band_manifest["diagram_count"] == len(route_band_manifest["entries"])
    assert (tmp_path / "graph" / "vehicle_operation_diagrams" / "manifest.json").exists()
    soc_rows = list(csv.DictReader((tmp_path / "graph" / "vehicle_soc_timeseries.csv").open(encoding="utf-8")))
    assert soc_rows[0]["time"] == "00:00"
    assert soc_rows[-1]["time"] == "23:30"
    assert len(soc_rows) == 48
    grid_rows = list(csv.DictReader((tmp_path / "graph" / "grid_import_timeseries.csv").open(encoding="utf-8")))
    assert grid_rows[0]["time"] == "00:00"
    assert grid_rows[-1]["time"] == "23:30"
    assert len(grid_rows) == 48
    source_precision = json.loads(
        (tmp_path / "graph" / "charging_source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert source_precision["site_depot_timestep"]["exact"] is True
    assert source_precision["vehicle_timestep"]["exact"] is False
    assert source_precision["vehicle_timestep"]["allocation_method"] == (
        "proportional_by_depot_timestep"
    )


def test_bess_soc_start_end_stay_within_configured_bounds_across_artifacts(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()
    asset = replace(
        problem.depot_energy_assets["dep1"],
        pv_generation_kwh_by_slot=(10.0, 0.0),
        bess_enabled=True,
        bess_energy_kwh=500.0,
        bess_power_kw=100.0,
        bess_initial_soc_kwh=390.0,
        bess_soc_min_kwh=100.0,
        bess_soc_max_kwh=400.0,
        bess_charge_efficiency=1.0,
        bess_discharge_efficiency=1.0,
        bess_terminal_soc_target_kwh=0.0,
    )
    problem = replace(
        problem,
        scenario=replace(problem.scenario, timestep_min=60, horizon_start="00:00"),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        depot_energy_assets={"dep1": asset},
    )
    plan = replace(
        result.plan,
        charging_slots=(),
        grid_to_bus_kwh_by_depot_slot={},
        pv_to_bus_kwh_by_depot_slot={},
        bess_to_bus_kwh_by_depot_slot={},
        pv_to_bess_kwh_by_depot_slot={"dep1": {0: 10.0}},
        grid_to_bess_kwh_by_depot_slot={},
        pv_curtail_kwh_by_depot_slot={},
        bess_soc_kwh_by_depot_slot={},
        metadata=dict(result.plan.metadata or {}),
    )
    result = replace(result, plan=plan)

    def assert_bess_bounds(rows: list[dict[str, str]]) -> None:
        assert rows
        for row in rows:
            for key in ("bess_soc_start_kwh", "bess_soc_end_kwh"):
                assert key in row
                value = float(row.get(key) or 0.0)
                assert 100.0 <= value <= 400.0

    charging_payload = optimization._canonical_charging_output_payload(problem, result)
    assert_bess_bounds(charging_payload["rows"])
    assert charging_payload["rows"][0]["bess_soc_start_kwh"] == 390.0
    assert charging_payload["rows"][0]["bess_soc_end_kwh"] == 400.0

    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )
    graph_dir = tmp_path / "graph"
    manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bess_soc_kwh_semantics"] == "slot_end"
    for filename in (
        "depot_power_timeseries.csv",
        "energy_flow_timeseries.csv",
        "bess_timeseries.csv",
        "energy_flow_ledger.csv",
    ):
        assert_bess_bounds(list(csv.DictReader((graph_dir / filename).open(encoding="utf-8"))))

    canonical_solver_result = ResultSerializer.serialize_result(result)
    run_dir = tmp_path / "run"
    optimization._persist_rich_run_outputs(
        run_dir=run_dir,
        scenario=scenario,
        optimization_result={
            "scenario_id": "scenario-1",
            "mode": "mode_alns_only",
            "solver_status": "feasible",
            "objective_mode": "total_cost",
            "objective_value": 123.0,
            "solve_time_seconds": 1.5,
            "summary": {"trip_count_served": 1, "trip_count_unserved": 0, "vehicle_count_used": 1},
            "cost_breakdown": {"total_cost": 123.0, "energy_cost": 10.0, "grid_to_bus_kwh": 0.0},
            "graph_artifacts": artifacts,
        },
        optimization_audit={},
        result_payload={"assignment": {"veh-1": ["t1"]}, "unserved_tasks": [], "obj_breakdown": {"energy_cost": 10.0}},
        sim_payload=None,
        canonical_solver_result=canonical_solver_result,
        graph_source_dir=graph_dir,
        charging_summary=charging_payload["summary"],
        charging_flow_payload=charging_payload,
    )
    assert_bess_bounds(list(csv.DictReader((run_dir / "depot_energy_flows.csv").open(encoding="utf-8"))))
    for filename in (
        "optimization_result.json",
        "optimization_audit.json",
        "summary.json",
        "run_manifest.json",
        "research_claim_scope.json",
    ):
        payload = json.loads((run_dir / filename).read_text(encoding="utf-8"))
        assert payload["diagnostic_only"] is True
        assert payload["research_submission_ready"] is False
        assert payload["teacher_release_status"] == "BLOCKED"
        assert payload["blocking_reason"] == "dirty_or_nonformal_run"


def test_rich_run_outputs_restore_charging_schedule_and_vehicle_timelines_json(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()
    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )
    canonical_solver_result = ResultSerializer.serialize_result(result)
    charging_payload = optimization._canonical_charging_output_payload(problem, result)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / optimization.RUN_INPUT_MANIFEST_FILE).write_text(
        json.dumps(
            {
                "schema_version": "frontend_run_input_provenance_v1",
                "prepared_input_id": "prepared-test",
                "prepared_source_sha256": "prepared-sha",
                "artifacts": {"scenario_input_snapshot.json": {"sha256": "x"}},
            }
        ),
        encoding="utf-8",
    )

    optimization._persist_rich_run_outputs(
        run_dir=run_dir,
        scenario=scenario,
        optimization_result={
            "scenario_id": "scenario-1",
            "mode": "mode_alns_only",
            "solver_status": "feasible",
            "objective_mode": "total_cost",
            "objective_value": 123.0,
            "solve_time_seconds": 1.5,
            "summary": {
                "trip_count_served": 1,
                "trip_count_unserved": 0,
                "vehicle_count_used": 1,
                "trip_count_by_type": {"BEV": 1},
            },
            "cost_breakdown": {
                "total_cost": 123.0,
                "energy_cost": 10.0,
                "fuel_cost": 4.0,
                "fuel_cost_provisional": 7.0,
                "fuel_cost_refueled": 2.0,
                "fuel_cost_provisional_leftover": 2.0,
                "grid_to_bus_kwh": 1.0,
                "grid_to_bess_kwh": 0.0,
            },
            "graph_artifacts": artifacts,
        },
        optimization_audit={},
        result_payload={"assignment": {"veh-1": ["t1"]}, "unserved_tasks": [], "obj_breakdown": {"energy_cost": 10.0}},
        sim_payload=None,
        canonical_solver_result=canonical_solver_result,
        graph_source_dir=tmp_path / "graph",
        charging_summary=charging_payload["summary"],
        charging_flow_payload=charging_payload,
    )

    assert (run_dir / "charging_schedule.csv").exists()
    assert (run_dir / "vehicle_timelines.json").exists()
    assert (run_dir / "charging_summary.json").exists()
    assert (run_dir / "charging_source_provenance.json").exists()
    assert (run_dir / "depot_energy_flows.csv").exists()
    assert (run_dir / "site_power_balance.csv").exists()
    assert (run_dir / "raw" / "optimization_result.json").exists()
    assert (run_dir / "raw" / "optimization_audit.json").exists()
    assert (run_dir / "raw" / "solver_result.json").exists()
    assert (run_dir / "raw" / "canonical_solver_result.json").exists()
    assert (run_dir / "raw" / "assignment.csv").exists()
    assert (run_dir / "raw" / "unserved_trips.csv").exists()
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["graph"]["manifest_path"] == "graph/manifest.json"
    assert run_manifest["run_input_provenance"]["status"] == "OK"
    root_source_precision = json.loads(
        (run_dir / "charging_source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_source_precision["site_depot_timestep"]["exact"] is True
    assert root_source_precision["vehicle_timestep"]["exact"] is False
    assert (
        run_manifest["run_input_provenance"]["prepared_input_id"]
        == "prepared-test"
    )
    assert run_manifest["graph"]["route_band_diagrams_manifest"] == "graph/route_band_diagrams/manifest.json"
    assert run_manifest["graph"]["route_band_diagram_count"] == artifacts["diagram_count"]
    charging_summary_json = json.loads((run_dir / "charging_summary.json").read_text(encoding="utf-8"))
    assert charging_summary_json["totals"]["grid_to_bus_kwh"] == 1.0
    assert charging_summary_json["totals"]["pv_to_bus_kwh"] == 0.5
    kpi_summary_json = json.loads((run_dir / "kpi_summary.json").read_text(encoding="utf-8"))
    assert kpi_summary_json["fuel_cost_jpy"] == 4.0
    assert kpi_summary_json["fuel_cost_final_jpy"] == 4.0
    assert kpi_summary_json["fuel_cost_provisional_jpy"] == 7.0
    assert kpi_summary_json["fuel_cost_refueled_jpy"] == 2.0
    assert kpi_summary_json["fuel_cost_provisional_leftover_jpy"] == 2.0


def test_rich_run_condition_tables_use_canonical_prices_and_import_limit(
    tmp_path: Path,
) -> None:
    problem, result, scenario = _problem_and_result()
    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )
    run_dir = tmp_path / "run"

    optimization._persist_rich_run_outputs(
        run_dir=run_dir,
        scenario={"simulation_config": {}},
        optimization_result={
            "scenario_id": "scenario-1",
            "mode": "mode_alns_only",
            "solver_status": "feasible",
            "objective_mode": "total_cost",
            "objective_value": 123.0,
            "solve_time_seconds": 1.5,
            "summary": {"trip_count_served": 1, "trip_count_unserved": 0},
            "cost_breakdown": {"total_cost": 123.0},
            "graph_artifacts": artifacts,
        },
        optimization_audit={},
        result_payload={"assignment": {}, "unserved_tasks": [], "obj_breakdown": {}},
        sim_payload=None,
        canonical_solver_result=None,
        canonical_problem=problem,
    )

    tou_rows = list(
        csv.DictReader(
            (run_dir / "simulation_conditions_tou_prices.csv").open(
                encoding="utf-8"
            )
        )
    )
    contract_rows = list(
        csv.DictReader(
            (run_dir / "simulation_conditions_contract_limits.csv").open(
                encoding="utf-8"
            )
        )
    )
    provenance = json.loads(
        (run_dir / "simulation_conditions_provenance.json").read_text(
            encoding="utf-8"
        )
    )

    assert [(row["site_id"], row["grid_energy_price_yen_per_kwh"]) for row in tou_rows] == [
        ("dep1", "20.0"),
        ("dep1", "20.0"),
    ]
    assert all(row["base_load_kw"] == "" for row in tou_rows)
    assert all(row["demand_charge_weight"] == "0.0" for row in tou_rows)
    assert contract_rows == [
        {
            "site_id": "dep1",
            "site_type": "depot",
            "contract_demand_limit_kw": "15.0",
            "grid_import_limit_kw": "15.0",
            "site_transformer_limit_kw": "",
        }
    ]
    assert provenance["source"] == "canonical_problem"
    assert provenance["contract_limit_source"] == (
        "canonical_problem.depots[].import_limit_kw"
    )


def test_canonical_condition_tables_preserve_explicit_base_load_without_inference() -> None:
    problem, _result, _scenario = _problem_and_result()
    problem = replace(
        problem,
        metadata={"base_load_kw_by_slot": {"0": 3.5, "1": 4.0}},
    )

    tables = optimization._canonical_simulation_condition_tables(problem)

    assert tables is not None
    tou_rows, _contract_rows, provenance = tables
    assert [row["base_load_kw"] for row in tou_rows] == [3.5, 4.0]
    assert all(row["demand_charge_weight"] == 0.0 for row in tou_rows)
    assert provenance["base_load_source"].endswith("blank_when_not_represented")


@pytest.mark.parametrize(
    ("rolling_status", "expected_generated"),
    (
        ("executed_and_accepted", True),
        ("not_executed", False),
    ),
)
def test_rich_run_outputs_finalize_reporting_after_top_level_files_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rolling_status: str,
    expected_generated: bool,
) -> None:
    problem, result, scenario = _problem_and_result()
    result = replace(
        result,
        cost_breakdown={
            "energy_cost": 10.0,
            "electricity_cost": 10.0,
            "vehicle_usage_cost": 113.0,
            "total_cost": 123.0,
        },
    )
    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )
    canonical_solver_result = ResultSerializer.serialize_result(result)
    charging_payload = optimization._canonical_charging_output_payload(problem, result)
    generated_for: list[Path] = []

    monkeypatch.setattr(
        optimization,
        "_rolling_execution_evidence",
        lambda **_kwargs: {
            "status": rolling_status,
            "rolling_execution_minutes": 60,
            "step_count": 24 if expected_generated else 0,
            "expected_step_count": 24,
            "chain_accepted": expected_generated,
        },
    )

    def _generate_bundle(run_dir: Path) -> dict:
        generated_for.append(run_dir)
        literature_dir = run_dir / "graph" / "literature_figures"
        literature_dir.mkdir(parents=True, exist_ok=True)
        (literature_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "literature_figure_bundle_v1",
                    "status": "READY",
                }
            ),
            encoding="utf-8",
        )
        return {
            "status": "READY",
            "schema_version": "literature_figure_bundle_v1",
            "figure_count": 5,
            "diagnostic_only": True,
        }

    monkeypatch.setattr(
        "bff.services.optimization_run.literature_figures."
        "generate_literature_figure_bundle",
        _generate_bundle,
    )

    reporting_result = optimization._persist_rich_run_outputs(
        run_dir=tmp_path,
        scenario=scenario,
        optimization_result={
            "scenario_id": "scenario-1",
            "mode": "mode_alns_only",
            "solver_status": "feasible",
            "objective_mode": "total_cost",
            "objective_value": 123.0,
            "solve_time_seconds": 1.5,
            "summary": {
                "trip_count_served": 1,
                "trip_count_unserved": 0,
                "vehicle_count_used": 1,
                "trip_count_by_type": {"BEV": 1},
            },
            "cost_breakdown": {
                "total_cost": 123.0,
                "energy_cost": 10.0,
                "electricity_cost": 6.0,
                "demand_charge": 0.0,
                "fuel_cost": 4.0,
                "co2_cost": 0.0,
                "total_co2_kg": 0.0,
                "grid_to_bus_kwh": 1.0,
                "grid_to_bess_kwh": 0.0,
            },
            "graph_artifacts": artifacts,
        },
        optimization_audit={"warnings": []},
        result_payload={
            "assignment": {"veh-1": ["t1"]},
            "unserved_tasks": [],
            "obj_breakdown": {"objective_value": 123.0, "energy_cost": 10.0},
        },
        sim_payload=None,
        canonical_solver_result=canonical_solver_result,
        graph_source_dir=tmp_path / "graph",
        charging_summary=charging_payload["summary"],
        charging_flow_payload=charging_payload,
        finalize_reporting=True,
    )

    assert reporting_result is not None
    assert reporting_result["status"] == "completed"
    assert (tmp_path / "cost_breakdown_detail.csv").exists()
    assert (tmp_path / "rebuild_reporting_log.json").exists()
    assert (tmp_path / "experiment_report.md").exists()
    persisted = json.loads((tmp_path / "optimization_result.json").read_text(encoding="utf-8"))
    assert persisted["graph_artifacts"]["reporting_finalizer"]["status"] == "completed"
    audit = json.loads((tmp_path / "optimization_audit.json").read_text(encoding="utf-8"))
    assert audit["experiment_report"]["status"] == "generated"
    assert audit["experiment_report"]["accounting_reconciled"] is True
    assert audit["experiment_report"]["run_json_path"] == "experiment_report.json"
    assert audit["experiment_report"]["run_md_path"] == "experiment_report.md"
    if expected_generated:
        assert generated_for == [tmp_path]
        assert persisted["literature_figure_bundle"] == {
            "status": "READY",
            "schema_version": "literature_figure_bundle_v1",
            "figure_count": 5,
            "diagnostic_only": True,
            "manifest": "graph/literature_figures/manifest.json",
        }
        run_manifest = json.loads(
            (tmp_path / "run_manifest.json").read_text(encoding="utf-8")
        )
        assert (
            "graph/literature_figures/manifest.json"
            in run_manifest["files"]
        )
    else:
        assert generated_for == []
        assert persisted["literature_figure_bundle"]["status"] == (
            "NOT_GENERATED"
        )


def test_charging_summary_reports_electricity_cost_not_propulsion_aggregate() -> None:
    problem, result, _scenario = _problem_and_result()
    result = replace(
        result,
        cost_breakdown={
            "energy_cost": 100.0,
            "electricity_cost": 12.0,
            "fuel_cost": 88.0,
            "total_cost": 100.0,
        },
    )

    payload = optimization._canonical_charging_output_payload(problem, result)

    assert payload["summary"]["totals"]["electricity_cost_jpy"] == 12.0


def test_canonical_kpi_summary_reports_fuel_provisional_and_final_costs() -> None:
    problem, result, scenario = _problem_and_result()
    result = replace(
        result,
        cost_breakdown={
            "total_cost": 200.0,
            "energy_cost": 150.0,
            "electricity_cost": 50.0,
            "pv_marginal_charge_cost_yen_per_kwh": 4.25,
            "pv_self_consumption_cost_jpy": 2.0,
            "fuel_cost": 100.0,
            "fuel_cost_provisional": 160.0,
            "fuel_cost_refueled": 40.0,
            "fuel_cost_provisional_leftover": 60.0,
        },
    )

    payload = optimization._canonical_kpi_summary_json(
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        soc_rows=[],
    )

    assert payload["electricity_cost_jpy"] == 50.0
    assert payload["fuel_cost_jpy"] == 100.0
    assert payload["fuel_cost_final_jpy"] == 100.0
    assert payload["fuel_cost_provisional_jpy"] == 160.0
    assert payload["fuel_cost_refueled_jpy"] == 40.0
    assert payload["fuel_cost_provisional_leftover_jpy"] == 60.0
    assert payload["objective_value_jpy"] == 123.0
    assert payload["objective_is_actual_cost"] is False
    assert payload["supports_exact_milp"] is False
    assert payload["pv_self_consumption_cost_jpy"] == 2.0
    assert payload["pv_marginal_charge_cost_yen_per_kwh"] == 4.25


def test_canonical_graph_exports_enable_route_band_diagrams_when_fixed_mode_is_on(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()
    problem = replace(
        problem,
        metadata={**dict(problem.metadata or {}), "fixed_route_band_mode": True},
    )
    scenario = {
        **scenario,
        "simulation_config": {
            **dict(scenario.get("simulation_config") or {}),
            "enable_vehicle_diagram_output": False,
            "fixed_route_band_mode": True,
        },
    }

    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )

    assert artifacts["enabled"] is True
    assert (tmp_path / "graph" / "route_band_diagrams" / "manifest.json").exists()


def test_canonical_graph_exports_research_timeseries_files(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()

    optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )

    graph_dir = tmp_path / "graph"
    for filename in (
        "co2_timeseries.csv",
        "cost_timeseries.csv",
        "contract_limit_timeseries.csv",
        "bess_timeseries.csv",
        "vehicle_charging_source_timeseries.csv",
        "fuel_timeseries.csv",
    ):
        assert (graph_dir / filename).exists()

    with (graph_dir / "contract_limit_timeseries.csv").open("r", encoding="utf-8", newline="") as handle:
        contract_rows = list(csv.DictReader(handle))
    assert len(contract_rows) == 48
    assert "grid_import_for_contract_kw" in contract_rows[0]
    assert "bess_to_bus_excluded_from_contract_kwh" in contract_rows[0]

    with (graph_dir / "vehicle_charging_source_timeseries.csv").open("r", encoding="utf-8", newline="") as handle:
        vehicle_source_rows = list(csv.DictReader(handle))
    assert len(vehicle_source_rows) == 48
    assert abs(sum(float(row["grid_to_vehicle_kwh"]) for row in vehicle_source_rows) - 10.0) < 1.0e-9

    with (graph_dir / "pv_generation_timeseries.csv").open("r", encoding="utf-8", newline="") as handle:
        pv_rows = list(csv.DictReader(handle))
    with (graph_dir / "energy_flow_ledger.csv").open("r", encoding="utf-8", newline="") as handle:
        ledger_rows = list(csv.DictReader(handle))
    with (graph_dir / "cost_timeseries.csv").open("r", encoding="utf-8", newline="") as handle:
        cost_rows = list(csv.DictReader(handle))
    kpi_summary = json.loads((graph_dir / "kpi_summary.json").read_text(encoding="utf-8"))
    pv_timeseries_total = sum(float(row["pv_generation_slot_kwh"]) for row in pv_rows)
    ledger_total = sum(float(row["pv_generation_kwh"]) for row in ledger_rows)
    ledger_grid_cost = sum(float(row["grid_purchase_cost_jpy"]) for row in ledger_rows)
    cost_timeseries_grid_cost = sum(float(row["grid_purchase_cost_jpy"]) for row in cost_rows)
    assert pv_timeseries_total == 3.0
    assert ledger_total == pv_timeseries_total
    assert cost_timeseries_grid_cost > 0.0
    assert abs(ledger_grid_cost - cost_timeseries_grid_cost) < 1.0e-9
    assert kpi_summary["pv_generation_kwh"] == pv_timeseries_total

    with (graph_dir / "data_flow_validation.csv").open("r", encoding="utf-8", newline="") as handle:
        validation_rows = {row["check_name"]: row for row in csv.DictReader(handle)}
    assert validation_rows["pv_generation_matches_pv_timeseries"]["status"] == "OK"
    assert validation_rows["kpi_pv_generation_matches_energy_flow_ledger"]["status"] == "OK"


def test_canonical_graph_exports_fallback_grid_import_and_contract_exceedance(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()
    result = replace(
        result,
        plan=AssignmentPlan(
            duties=result.plan.duties,
            charging_slots=(
                ChargingSlot(
                    vehicle_id="veh-1",
                    slot_index=1,
                    charger_id="chg-1",
                    charge_kw=20.0,
                    charging_depot_id="dep1",
                ),
            ),
            served_trip_ids=("t1",),
            unserved_trip_ids=(),
            metadata={
                "duty_vehicle_map": {"veh-1": "veh-1"},
                "enable_contract_overage_penalty": True,
                "contract_overage_penalty_yen_per_kwh": 500.0,
            },
        ),
        cost_breakdown={
            "energy_cost": 10.0,
            "total_cost": 123.0,
            "contract_overage_cost": 1250.0,
        },
    )

    optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )

    depot_power_path = tmp_path / "graph" / "depot_power_timeseries.csv"
    with depot_power_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert "slot_minutes" in rows[0]
    assert "grid_to_bus_slot_kwh" in rows[0]
    assert "grid_to_bus_hourly_source_kwh" in rows[0]
    assert "contract_over_limit_slot_kwh" in rows[0]
    charged_rows = [row for row in rows if float(row["grid_to_bus_kwh"]) > 0.0]
    assert charged_rows
    assert sum(float(row["grid_to_bus_kwh"]) for row in rows) == 10.0
    assert sum(float(row["grid_to_bus_slot_kwh"]) for row in rows) == 10.0
    assert sum(float(row["pv_to_bus_kwh"]) for row in rows) == 0.0
    assert float(charged_rows[0]["contract_limit_kw"]) == 15.0
    assert float(charged_rows[0]["slot_minutes"]) == 30.0
    assert float(charged_rows[0]["grid_to_bus_hourly_source_kwh"]) == 10.0
    assert float(charged_rows[0]["contract_over_limit_kwh"]) > 0.0
    assert charged_rows[0]["contract_limit_exceeded"] == "True"
    assert charged_rows[0]["source_provenance_exact"] == "False"


def test_contract_grid_import_columns_exclude_bess_to_bus() -> None:
    problem, result, _scenario = _problem_and_result()
    result = replace(
        result,
        plan=replace(
            result.plan,
            charging_slots=(),
            grid_to_bus_kwh_by_depot_slot={"dep1": {0: 100.0}},
            grid_to_bess_kwh_by_depot_slot={"dep1": {0: 20.0}},
            bess_to_bus_kwh_by_depot_slot={"dep1": {0: 80.0}},
            pv_to_bus_kwh_by_depot_slot={},
            pv_to_bess_kwh_by_depot_slot={},
        ),
    )

    rows = optimization._canonical_depot_power_rows_5min(
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        base_date=date(2026, 4, 5),
    )

    assert rows
    assert abs(sum(float(row["grid_import_for_contract_slot_kwh"]) for row in rows) - 120.0) < 1.0e-9
    assert abs(sum(float(row["bus_charge_from_bess_slot_kwh"]) for row in rows) - 80.0) < 1.0e-9
    first_row = rows[0]
    assert float(first_row["grid_import_for_contract_hourly_source_kwh"]) == 120.0
    assert float(first_row["bus_charge_from_bess_hourly_source_kwh"]) == 80.0


def test_solver_settings_payload_reports_gap_ratio_and_percent() -> None:
    payload = optimization._solver_settings_payload(
        time_limit_seconds_requested=300,
        mip_gap_requested=0.01,
        solver_metadata={
            "effective_limits": {"time_limit_sec": 300, "mip_gap": 0.01},
            "final_gap": 0.0025,
            "has_feasible_incumbent": True,
            "supports_exact_milp": True,
            "stage1_gurobi_feasibility_tol": 1.0e-6,
            "stage2_gurobi_feasibility_tol": 1.0e-9,
            "stage2_gurobi_integrality_tol": 1.0e-9,
            "stage1_numeric_diagnostics": {
                "maximum_constraint_violation": 5.0e-7,
            },
            "stage1_root_lp_diagnostic": {
                "enabled": True,
                "status": "time_limit",
                "time_limit_sec": 30.0,
                "solution_count": 0,
            },
            "fragment_pairwise_depot_reset_constraint_count": 0,
            "fragment_temporal_occupancy_constraint_count": 13,
            "fragment_pairwise_depot_reset_constraint_mode": (
                "lazy_integer_incumbent_separation"
            ),
            "fragment_transition_lazy_separator": {
                "enabled": True,
                "lazy_constraint_count": 3,
                "callback_error": None,
            },
            "overlap_clique_constraint_count": 5,
            "integrated_fragment_pairwise_constraint_count": 0,
            "integrated_fragment_pairwise_constraint_mode": (
                "lazy_integer_incumbent_separation"
            ),
            "integrated_fragment_transition_lazy_separator": {
                "enabled": True,
                "lazy_constraint_count": 7,
                "callback_error": None,
            },
            "integrated_fragment_occupancy_constraint_count": 24_600,
            "integrated_overlap_clique_constraint_count": 9_420,
            "bff_runtime_git_attestation": {
                "schema_version": "bff_runtime_git_attestation_v1",
                "runtime_git_sha": "abc123",
                "runtime_git_state_matches_current": True,
            },
        },
    )

    assert payload["time_limit_seconds_requested"] == 300
    assert payload["time_limit_seconds_effective"] == 300
    assert payload["mip_gap_requested_ratio"] == 0.01
    assert payload["mip_gap_requested_percent"] == 1.0
    assert payload["mip_gap_achieved_ratio"] == 0.0025
    assert payload["mip_gap_achieved_percent"] == 0.25
    assert payload["stage1_gurobi_feasibility_tol"] == pytest.approx(1.0e-6)
    assert payload["stage2_gurobi_feasibility_tol"] == pytest.approx(1.0e-9)
    assert payload["stage2_gurobi_integrality_tol"] == pytest.approx(1.0e-9)
    assert payload["stage1_numeric_diagnostics"][
        "maximum_constraint_violation"
    ] == pytest.approx(5.0e-7)
    assert payload["stage1_root_lp_diagnostic"] == {
        "enabled": True,
        "status": "time_limit",
        "time_limit_sec": 30.0,
        "solution_count": 0,
    }
    assert payload["fragment_pairwise_depot_reset_constraint_count"] == 0
    assert payload["fragment_temporal_occupancy_constraint_count"] == 13
    assert (
        payload["fragment_pairwise_depot_reset_constraint_mode"]
        == "lazy_integer_incumbent_separation"
    )
    assert payload["fragment_transition_lazy_separator"][
        "lazy_constraint_count"
    ] == 3
    assert payload["overlap_clique_constraint_count"] == 5
    assert payload["integrated_fragment_pairwise_constraint_count"] == 0
    assert (
        payload["integrated_fragment_pairwise_constraint_mode"]
        == "lazy_integer_incumbent_separation"
    )
    assert payload["integrated_fragment_transition_lazy_separator"][
        "lazy_constraint_count"
    ] == 7
    assert payload["integrated_fragment_occupancy_constraint_count"] == 24_600
    assert payload["integrated_overlap_clique_constraint_count"] == 9_420
    assert payload["bff_runtime_git_attestation"]["runtime_git_sha"] == (
        "abc123"
    )
