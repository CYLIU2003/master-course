from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

from bff.routers import optimization
from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty
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
)
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


def test_canonical_graph_exports_write_legacy_graph_files_even_when_diagrams_disabled(tmp_path: Path) -> None:
    problem, result, scenario = _problem_and_result()

    artifacts = optimization._persist_canonical_graph_exports(
        scenario=scenario,
        problem=problem,
        engine_result=result,
        scenario_id="scenario-1",
        output_dir=str(tmp_path),
    )

    assert artifacts["enabled"] is False
    assert (tmp_path / "graph" / "vehicle_timeline.csv").exists()
    assert (tmp_path / "graph" / "soc_events.csv").exists()
    assert (tmp_path / "graph" / "depot_power_timeseries_5min.csv").exists()
    assert (tmp_path / "graph" / "trip_assignment.csv").exists()
    assert (tmp_path / "graph" / "cost_breakdown.json").exists()
    assert (tmp_path / "graph" / "kpi_summary.json").exists()
    assert (tmp_path / "graph" / "manifest.json").exists()
    assert (tmp_path / "graph" / "vehicle_operation_diagrams" / "manifest.json").exists()


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
            "cost_breakdown": {"total_cost": 123.0, "energy_cost": 10.0, "grid_to_bus_kwh": 1.0, "grid_to_bess_kwh": 0.0},
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
    assert (run_dir / "depot_energy_flows.csv").exists()
    assert (run_dir / "site_power_balance.csv").exists()
    charging_summary_json = json.loads((run_dir / "charging_summary.json").read_text(encoding="utf-8"))
    assert charging_summary_json["totals"]["grid_to_bus_kwh"] == 1.0
    assert charging_summary_json["totals"]["pv_to_bus_kwh"] == 0.5


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

    depot_power_path = tmp_path / "graph" / "depot_power_timeseries_5min.csv"
    with depot_power_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    charged_rows = [row for row in rows if float(row["grid_to_bus_kwh"]) > 0.0]
    assert charged_rows
    assert float(charged_rows[0]["contract_limit_kw"]) == 15.0
    assert float(charged_rows[0]["contract_over_limit_kwh"]) > 0.0
    assert charged_rows[0]["contract_limit_exceeded"] == "True"
    assert charged_rows[0]["source_provenance_exact"] == "False"
