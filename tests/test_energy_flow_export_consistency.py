from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from src.data_schema import Charger, ProblemData, Site, Task, Vehicle
from src.milp_model import MILPResult
from src.model_sets import ModelSets
from src.optimization.accounting import build_accounting_artifacts
from src.optimization.common.problem import AssignmentPlan
from src.optimization.common.problem import ChargingSlot
from src.optimization.common.problem import OptimizationMode
from src.optimization.common.problem import OptimizationScenario
from src.optimization.common.problem import ProblemDepot
from src.optimization.common.problem import ProblemTrip
from src.optimization.common.problem import ProblemVehicle
from src.optimization.common.problem import CanonicalOptimizationProblem
from src.optimization.common.problem import OptimizationEngineResult
from src.optimization.common.problem import DepotEnergyAsset
from src.parameter_builder import DerivedParams
from src.result_exporter import (
    _build_kpi_summary_json,
    export_depot_energy_flows,
    export_graph_exports_phase1,
)
from src.simulator import SimulationResult


def _sample_context() -> tuple[ProblemData, ModelSets, DerivedParams, MILPResult, SimulationResult]:
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot="dep-1",
                battery_capacity=100.0,
                soc_init=50.0,
                soc_min=10.0,
                soc_max=100.0,
            )
        ],
        tasks=[
            Task(
                task_id="trip-1",
                start_time_idx=0,
                end_time_idx=1,
                origin="dep-1",
                destination="stop-1",
                distance_km=10.0,
                energy_required_kwh_bev=6.0,
                route_id="R1",
                route_family_code="R1",
                direction="outbound",
                route_variant_type="main_outbound",
            )
        ],
        chargers=[Charger(charger_id="chg-1", site_id="dep-1", power_max_kw=50.0)],
        sites=[Site(site_id="dep-1", site_type="depot", grid_import_limit_kw=100.0, contract_demand_limit_kw=100.0)],
        num_periods=2,
        delta_t_hour=0.5,
        planning_horizon_hours=1.0,
        enable_demand_charge=True,
        enable_pv=True,
    )

    ms = ModelSets(
        K_BEV=["veh-1"],
        K_ICE=[],
        K_ALL=["veh-1"],
        R=["trip-1"],
        R_BEV_ELIGIBLE=["trip-1"],
        R_ICE_ELIGIBLE=["trip-1"],
        T=[0, 1],
        I_DEPOT=["dep-1"],
        I_CHARGE=["dep-1"],
        I_ROUTE=[],
        I_ALL=["dep-1"],
        C=["chg-1"],
        C_at_site={"dep-1": ["chg-1"]},
        K_COMPAT_charger={"chg-1": ["veh-1"]},
        vehicle_task_feasible={"veh-1": {"trip-1"}},
        vehicle_charger_feasible={"veh-1": {"chg-1"}},
    )

    dp = DerivedParams()
    dp.vehicle_lut = {"veh-1": data.vehicles[0]}
    dp.task_lut = {"trip-1": data.tasks[0]}
    dp.charger_lut = {"chg-1": data.chargers[0]}
    dp.site_lut = {"dep-1": data.sites[0]}
    dp.pv_gen_kw = {"dep-1": {0: 20.0, 1: 0.0}}
    dp.grid_price = {"dep-1": {0: 20.0, 1: 20.0}}
    dp.base_load_kw = {"dep-1": {0: 0.0, 1: 0.0}}
    dp.grid_co2_factor = {"dep-1": {0: 0.0, 1: 0.0}}
    dp.deadhead_distance_km = {"trip-1": {"trip-1": 0.0}}

    milp = MILPResult(status="OPTIMAL")
    milp.assignment = {"veh-1": ["trip-1"]}
    milp.soc_series = {"veh-1": [50.0, 55.0, 52.0]}
    milp.charge_power_kw = {"veh-1": {"chg-1": [10.0, 0.0]}}
    milp.grid_import_kw = {("dep-1", 0): 6.0, ("dep-1", 1): 0.0}
    milp.pv_used_kw = {("dep-1", 0): 4.0, ("dep-1", 1): 0.0}
    milp.grid_to_bus_kwh_by_slot = {("dep-1", 0): 2.0}
    milp.pv_to_bus_kwh_by_slot = {("dep-1", 0): 2.0}
    milp.bess_to_bus_kwh_by_slot = {("dep-1", 0): 1.0}
    milp.grid_to_bess_kwh_by_slot = {("dep-1", 0): 1.0}
    milp.pv_to_bess_kwh_by_slot = {("dep-1", 0): 1.0}
    milp.pv_curtailed_kwh_by_slot = {("dep-1", 0): 7.0}
    milp.bess_soc_kwh_by_slot = {("dep-1", 0): 4.0}
    milp.obj_breakdown = {"total_cost": 0.0}
    milp.peak_demand_kw = {"dep-1": 5.0}
    milp.vehicle_provenance_is_exact = False

    sim = SimulationResult(
        total_operating_cost=0.0,
        total_energy_cost=0.0,
        total_demand_charge=0.0,
        total_fuel_cost=0.0,
        total_degradation_cost=0.0,
        total_co2_kg=0.0,
        served_task_ratio=1.0,
        unserved_tasks=[],
        total_grid_kwh=3.0,
        total_grid_export_kwh=0.0,
        provisional_grid_kwh=0.0,
        charged_grid_kwh=3.0,
        total_pv_kwh=0.0,
        pv_self_consumption_ratio=0.0,
        peak_demand_kw=5.0,
        charger_utilization={"chg-1": 0.5},
        vehicle_utilization={"veh-1": 1.0},
        soc_min_kwh=50.0,
        soc_violations=[],
    )

    return data, ms, dp, milp, sim


def test_kpi_pv_uses_depot_generation_not_sim_zero() -> None:
    data, ms, dp, milp, sim = _sample_context()
    kpi = _build_kpi_summary_json(data, ms, dp, milp, sim, "scenario-1")

    assert kpi["pv_generation_total_kwh"] == pytest.approx(10.0)
    assert kpi["pv_to_bus_total_kwh"] == pytest.approx(2.0)
    assert kpi["pv_to_bess_total_kwh"] == pytest.approx(1.0)
    assert kpi["pv_curtail_total_kwh"] == pytest.approx(7.0)
    assert kpi["pv_utilization_ratio"] == pytest.approx(0.3)


def test_export_depot_energy_flows_contains_pv_generation_and_pv_to_bus(tmp_path: Path) -> None:
    data, ms, dp, milp, _sim = _sample_context()
    run_dir = tmp_path / "2025-08-05" / "run_0001"
    run_dir.mkdir(parents=True, exist_ok=True)

    export_depot_energy_flows(run_dir, data, ms, dp, milp)

    rows = list(csv.DictReader((run_dir / "depot_energy_flows.csv").open(encoding="utf-8")))
    assert rows
    assert float(rows[0]["pv_generation_kwh"]) == pytest.approx(10.0)
    assert float(rows[0]["pv_to_bus_kwh"]) == pytest.approx(2.0)
    assert (run_dir / "energy_flow_ledger.csv").exists()


def test_export_supports_tuple_key_milp_flows(tmp_path: Path) -> None:
    data, ms, dp, milp, _sim = _sample_context()
    run_dir = tmp_path / "2025-08-05" / "run_0002"
    run_dir.mkdir(parents=True, exist_ok=True)

    milp.grid_import_kw = {("dep-1", 0): 6.0, ("dep-1", 1): 0.0}
    milp.pv_used_kw = {("dep-1", 0): 4.0, ("dep-1", 1): 0.0}

    export_depot_energy_flows(run_dir, data, ms, dp, milp)

    rows = list(csv.DictReader((run_dir / "energy_flow_ledger.csv").open(encoding="utf-8")))
    assert rows
    assert float(rows[0]["grid_import_kw_reported"]) == pytest.approx(6.0)
    assert float(rows[0]["grid_import_balance_error_kw"]) == pytest.approx(0.0)


def test_vehicle_charge_source_allocation_matches_depot_totals(tmp_path: Path) -> None:
    data, ms, dp, milp, sim = _sample_context()
    run_dir = tmp_path / "2025-08-05" / "run_0003"
    run_dir.mkdir(parents=True, exist_ok=True)

    export_depot_energy_flows(run_dir, data, ms, dp, milp)
    export_graph_exports_phase1(run_dir, data, ms, dp, milp, sim, "scenario-1")

    source_rows = list(csv.DictReader((run_dir / "graph" / "vehicle_charge_energy_sources.csv").open(encoding="utf-8")))
    ledger_rows = list(csv.DictReader((run_dir / "depot_energy_flows.csv").open(encoding="utf-8")))
    kpi_summary = json.loads((run_dir / "graph" / "kpi_summary.json").read_text(encoding="utf-8"))
    assert source_rows
    assert float(source_rows[0]["grid_to_vehicle_kwh"]) == pytest.approx(2.0)
    assert float(source_rows[0]["pv_to_vehicle_kwh"]) == pytest.approx(2.0)
    assert float(source_rows[0]["bess_to_vehicle_kwh"]) == pytest.approx(1.0)
    assert float(source_rows[0]["source_balance_error_kwh"]) == pytest.approx(0.0)
    assert sum(float(row["grid_to_vehicle_kwh"]) for row in source_rows) == pytest.approx(sum(float(row["grid_to_bus_kwh"]) for row in ledger_rows))
    assert sum(float(row["pv_to_vehicle_kwh"]) for row in source_rows) == pytest.approx(sum(float(row["pv_to_bus_kwh"]) for row in ledger_rows))
    assert sum(float(row["bess_to_vehicle_kwh"]) for row in source_rows) == pytest.approx(sum(float(row["bess_to_bus_kwh"]) for row in ledger_rows))
    assert kpi_summary["pv_generation_total_kwh"] == pytest.approx(10.0)


def test_vehicle_soc_timeseries_is_written(tmp_path: Path) -> None:
    data, ms, dp, milp, sim = _sample_context()
    run_dir = tmp_path / "2025-08-05" / "run_0004"
    run_dir.mkdir(parents=True, exist_ok=True)

    export_graph_exports_phase1(run_dir, data, ms, dp, milp, sim, "scenario-1")

    rows = list(csv.DictReader((run_dir / "graph" / "vehicle_soc_timeseries.csv").open(encoding="utf-8")))
    assert len(rows) == 3
    assert rows[0]["is_initial"] == "True"
    assert rows[-1]["is_terminal"] == "True"


def test_vehicle_slot_ledger_does_not_duplicate_trip_distance() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            timestep_min=30,
            objective_mode="total_cost",
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-1",
                route_id="route-1",
                origin="dep-1",
                destination="stop-1",
                departure_min=480,
                arrival_min=490,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=6.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot 1", import_limit_kw=100.0),),
        price_slots=(),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(0.0, 0.0),
            )
        },
        metadata={"service_date": "2025-08-05"},
    )
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="scenario-1",
        run_id="run-1",
        service_date=date(2025, 8, 5),
        weather_date=date(2025, 8, 5),
        operator_id="tokyu",
        trip_assignment_rows=[
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "route_series_code": "route-1",
                "served_flag": True,
                "assigned_vehicle_id": "veh-1",
                "assigned_vehicle_type": "BEV",
                "actual_departure": "2025-08-05T08:00:00",
                "actual_arrival": "2025-08-05T08:10:00",
                "distance_km": 10.0,
                "energy_used_kwh": 6.0,
                "deadhead_before_km": 0.0,
                "deadhead_after_km": 0.0,
            }
        ],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[],
        energy_flow_rows=[],
        metadata={"objective_value": 0.0, "available_vehicle_count": 1},
    )

    total_service_km = sum(row.service_km for row in artifacts.vehicle_slot_ledger)
    assert total_service_km == pytest.approx(10.0)
