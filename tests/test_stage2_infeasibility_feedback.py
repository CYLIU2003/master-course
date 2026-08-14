from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
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
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


@pytest.mark.parametrize("vehicle_type", ("BEV", "bev", "PHEV", "FCEV"))
def test_stage2_soc_diagnostics_include_electric_powertrains(
    vehicle_type: str,
) -> None:
    assert GurobiMILPAdapter._uses_electric_soc_diagnostics(vehicle_type)


@pytest.mark.parametrize("vehicle_type", ("ICE", "DIESEL", "HEV", "", None))
def test_stage2_soc_diagnostics_exclude_fuel_powertrains(
    vehicle_type: str | None,
) -> None:
    assert not GurobiMILPAdapter._uses_electric_soc_diagnostics(vehicle_type)


def test_vehicle_local_iis_uses_exact_vehicle_assignment_pattern_cut() -> None:
    scope = GurobiMILPAdapter._classify_stage2_iis_assignment_cut_scope(
        iis_constraint_names=(
            "soc_initial__bev-1",
            "charge_availability__bev-1__slot_7__trip_active",
            "departure_soc__bev-1__trip-42",
            "terminal_soc__bev-1__return_to_initial_upper",
        ),
        iis_variable_bound_names=(),
        assigned_vehicle_ids=("bev-1", "bev-2"),
    )

    assert scope == {
        "cut_type": "vehicle_local_exact_assignment_pattern_no_good_cut",
        "cut_scope": "vehicle_local_exact_assignment_pattern",
        "vehicle_ids": ("bev-1",),
        "reason": "iis_contains_only_vehicle_local_constraints",
    }


def test_vehicle_local_piecewise_iis_and_soc_bound_stay_local() -> None:
    scope = GurobiMILPAdapter._classify_stage2_iis_assignment_cut_scope(
        iis_constraint_names=(
            "soc_initial__bev-1",
            "stage2_charge_band_select__bev-1__slot_7",
            "stage2_charge_taper_power_upper__bev-1__slot_7",
            "terminal_soc__bev-1__target",
        ),
        iis_variable_bound_names=("soc_bev-1_7",),
        assigned_vehicle_ids=("bev-1", "bev-2"),
    )

    assert scope == {
        "cut_type": "vehicle_local_exact_assignment_pattern_no_good_cut",
        "cut_scope": "vehicle_local_exact_assignment_pattern",
        "vehicle_ids": ("bev-1",),
        "reason": "iis_contains_only_vehicle_local_constraints_and_bounds",
    }


@pytest.mark.parametrize(
    ("constraint_names", "variable_bound_names", "expected_reason"),
    (
        (
            ("soc_initial__bev-1", "charger_ports__charger-1__slot_7"),
            (),
            "iis_contains_shared_or_unknown_constraints",
        ),
        (
            ("soc_initial__bev-1", "terminal_soc__bev-1__target"),
            ("shared_grid_import_7",),
            "iis_contains_shared_or_unknown_variable_bounds",
        ),
        ((), (), "iis_constraint_list_empty"),
    ),
)
def test_shared_or_bound_iis_keeps_conservative_full_assignment_cut(
    constraint_names: tuple[str, ...],
    variable_bound_names: tuple[str, ...],
    expected_reason: str,
) -> None:
    scope = GurobiMILPAdapter._classify_stage2_iis_assignment_cut_scope(
        iis_constraint_names=constraint_names,
        iis_variable_bound_names=variable_bound_names,
        assigned_vehicle_ids=("bev-1", "bev-2"),
    )

    assert scope["cut_type"] == "full_assignment_no_good_cut"
    assert scope["cut_scope"] == "full_assignment"
    assert scope["vehicle_ids"] == ()
    assert scope["reason"] == expected_reason


def _feedback_problem(diagnostics_dir: str) -> CanonicalOptimizationProblem:
    """Build a case that exposes Stage 1's continuous charger relaxation.

    Two BEVs can fractionally share a 90 kW and a 50 kW charger in Stage 1,
    but the exact Stage 2 requires each active vehicle to select one physical
    charger.  The first two all-BEV assignments are therefore infeasible.  A
    more expensive ICE assignment remains feasible after the no-good cuts.
    """
    dispatch_trips = []
    problem_trips = []
    for index in range(2):
        trip_id = f"feedback-trip-{index + 1}"
        dispatch_trips.append(
            Trip(
                trip_id=trip_id,
                route_id="feedback-route",
                origin="DEPOT",
                destination="DEPOT",
                departure_time="06:00",
                arrival_time="07:00",
                distance_km=60.0,
                allowed_vehicle_types=("BEV", "ICE"),
                origin_stop_id="DEPOT",
                destination_stop_id="DEPOT",
            )
        )
        problem_trips.append(
            ProblemTrip(
                trip_id=trip_id,
                route_id="feedback-route",
                origin="DEPOT",
                destination="DEPOT",
                departure_min=6 * 60,
                arrival_min=7 * 60,
                distance_km=60.0,
                energy_kwh=60.0,
                allowed_vehicle_types=("BEV", "ICE"),
            )
        )

    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="stage2-feedback-regression",
            horizon_start="05:00",
            horizon_end="08:00",
            timestep_min=60,
            service_coverage_mode="strict",
            diesel_price_yen_per_l=1_000.0,
        ),
        dispatch_context=DispatchContext(
            service_date="2026-04-24",
            trips=dispatch_trips,
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=100.0,
                    energy_consumption_kwh_per_km=1.0,
                ),
                "ICE": VehicleProfile(
                    vehicle_type="ICE",
                    fuel_consumption_l_per_km=1.0,
                ),
            },
        ),
        trips=tuple(problem_trips),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-feedback-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=0.20,
                battery_capacity_kwh=100.0,
                reserve_soc=0.20,
                energy_consumption_kwh_per_km=1.0,
                charge_power_max_kw=90.0,
            ),
            ProblemVehicle(
                vehicle_id="bev-feedback-2",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=0.20,
                battery_capacity_kwh=100.0,
                reserve_soc=0.20,
                energy_consumption_kwh_per_km=1.0,
                charge_power_max_kw=90.0,
            ),
            ProblemVehicle(
                vehicle_id="ice-feedback-1",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
                fuel_consumption_l_per_km=1.0,
                fixed_use_cost_jpy=100_000.0,
            ),
            ProblemVehicle(
                vehicle_id="ice-feedback-2",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
                fuel_consumption_l_per_km=1.0,
                fixed_use_cost_jpy=100_000.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                charge_power_max_kw=90.0,
                reserve_soc=0.20,
                energy_consumption_kwh_per_km=1.0,
            ),
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=1.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="DEPOT",
                name="Feedback depot",
                charger_ids=("charger-90", "charger-50"),
                import_limit_kw=1_000.0,
            ),
        ),
        chargers=(
            ChargerDefinition(
                charger_id="charger-90",
                depot_id="DEPOT",
                power_kw=90.0,
                simultaneous_ports=1,
            ),
            ChargerDefinition(
                charger_id="charger-50",
                depot_id="DEPOT",
                power_kw=50.0,
                simultaneous_ports=1,
            ),
        ),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=1.0)
            for index in range(3)
        ),
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "final_soc_floor_percent": 20.0,
            "milp_max_successors_per_trip": None,
            "phase3_diagnostics_dir": diagnostics_dir,
            "stage2_feedback_max_iterations": 2,
        },
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_proven_stage2_infeasibility_returns_a_no_good_cut_to_stage1(
    tmp_path,
) -> None:
    """A real Stage 2 IIS must retry and publish only the feasible schedule."""
    problem = _feedback_problem(str(tmp_path / "diagnostics"))

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            gurobi_threads=1,
        ),
    )
    independent_report = FeasibilityChecker().evaluate(problem, result.plan)
    metadata = result.plan.metadata
    feedback_history = metadata["stage2_feedback_history"]
    assigned_vehicle_types = {
        duty.vehicle_type for duty in result.plan.duties
    }

    assert result.feasible, result.infeasibility_reasons
    assert independent_report.feasible, independent_report.errors
    assert metadata["stage2_solver_status"] == "optimal"
    assert metadata["stage2_feasible"] is True
    assert metadata["stage2_feedback_iteration"] == 2
    assert metadata["stage1_feasibility_no_good_cut_count"] == 2
    assert len(feedback_history) == 2
    assert all(entry["stage2_status"] == "infeasible" for entry in feedback_history)
    assert all(entry["iis_generated"] is True for entry in feedback_history)
    assert all(entry["cut_scope"] == "full_assignment" for entry in feedback_history)
    assert "BEV" in assigned_vehicle_types
    assert "ICE" in assigned_vehicle_types
    assert (tmp_path / "diagnostics" / "stage2_infeasible.ilp").is_file()
    assert (
        tmp_path
        / "diagnostics"
        / "stage2_feedback_attempt_1"
        / "stage2_infeasible.ilp"
    ).is_file()
