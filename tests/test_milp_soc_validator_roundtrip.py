from __future__ import annotations

import pytest

from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    VehicleProfile,
)
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.milp.engine import MILPOptimizer


def _soc_roundtrip_problem() -> CanonicalOptimizationProblem:
    dispatch_trip = Trip(
        trip_id="startup-trip",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="A",
        destination_stop_id="B",
    )
    context = DispatchContext(
        service_date="2026-04-24",
        trips=[dispatch_trip],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 30),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 60),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="soc-roundtrip",
            horizon_start="00:00",
            horizon_end="00:00",
            timestep_min=60,
            service_coverage_mode="strict",
        ),
        dispatch_context=context,
        trips=(
            ProblemTrip(
                trip_id="startup-trip",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=8 * 60,
                arrival_min=9 * 60,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=80.0,
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
                charge_power_max_kw=60.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                charge_power_max_kw=60.0,
                reserve_soc=20.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="DEPOT",
                name="Depot",
                charger_ids=("chg-1",),
                import_limit_kw=100.0,
            ),
        ),
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=10.0)
            for index in range(24)
        ),
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "final_soc_floor_percent": 20.0,
            "deadhead_speed_kmh": 18.0,
            "milp_max_successors_per_trip": None,
        },
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_gurobi_plan_with_startup_deadhead_roundtrips_through_validator() -> None:
    problem = _soc_roundtrip_problem()
    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            gurobi_threads=1,
        ),
    )
    independent_report = FeasibilityChecker().evaluate(problem, result.plan)

    assert result.plan.duties
    assert result.plan.duties[0].legs[0].deadhead_from_prev_min == 30
    assert result.feasible, result.infeasibility_reasons
    assert independent_report.feasible, independent_report.errors
    assert result.solver_metadata["stage2_has_feasible_incumbent"] is True
    assert result.solver_metadata[
        "stage1_gurobi_feasibility_tol"
    ] == pytest.approx(1.0e-6)
    assert result.solver_metadata[
        "stage2_gurobi_feasibility_tol"
    ] == pytest.approx(1.0e-9)
    assert result.solver_metadata[
        "stage2_gurobi_integrality_tol"
    ] == pytest.approx(1.0e-9)
    assert "maximum_constraint_violation" in result.solver_metadata[
        "stage1_numeric_diagnostics"
    ]
    assert "maximum_constraint_violation" in result.solver_metadata[
        "stage2_numeric_diagnostics"
    ]
