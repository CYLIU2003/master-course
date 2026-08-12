from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization import (
    ChargerDefinition,
    CostEvaluator,
    EnergyPriceSlot,
    FeasibilityChecker,
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.common.cost_components import default_cost_component_flags
from src.optimization.validation.small_electric_oracle import (
    SmallElectricOracleInfeasibleError,
    solve_small_exact_electric_oracle,
)


BEV_KWH_PER_KM = 1.316
ICE_L_PER_KM = 1.0 / 4.52
DIESEL_JPY_PER_L = 150.0
CHARGE_EFFICIENCY = 0.95


def _accounting_only_cost_flags() -> dict[str, bool]:
    flags = {key: False for key in default_cost_component_flags()}
    flags.update(
        {
            "electricity_cost": True,
            "fuel_cost": True,
        }
    )
    return flags


def _mixed_break_even_problem(*, grid_price_jpy_per_kwh: float):
    trips = [
        Trip(
            trip_id=f"trip-{index + 1}",
            route_id="route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time=f"{8 + index:02d}:00",
            arrival_time=f"{8 + index:02d}:30",
            distance_km=10.0,
            allowed_vehicle_types=("BEV", "ICE"),
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
            operator_id="tokyu",
        )
        for index in range(4)
    ]
    context = DispatchContext(
        service_date="2025-08-05",
        trips=trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=BEV_KWH_PER_KM,
            ),
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=100.0,
                fuel_consumption_l_per_km=ICE_L_PER_KM,
            ),
        },
        default_turnaround_min=10,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id=f"electric-oracle-{grid_price_jpy_per_kwh:g}",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 1, "ICE": 1},
        chargers=(ChargerDefinition("charger-1", "DEPOT", 90.0),),
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=index,
                grid_buy_yen_per_kwh=grid_price_jpy_per_kwh,
            )
            for index in range(12)
        ),
        scenario_vehicles=(
            {
                "id": "BEV_001",
                "type": "BEV",
                "depotId": "DEPOT",
                "batteryKwh": 100.0,
                "energyConsumption": BEV_KWH_PER_KM,
                "chargePowerKw": 90.0,
                "initialSoc": 0.8,
                "minSoc": 0.2,
                "enabled": True,
            },
            {
                "id": "ICE_001",
                "type": "ICE",
                "depotId": "DEPOT",
                "fuelTankL": 100.0,
                "fuelConsumptionLPerKm": ICE_L_PER_KM,
                "initialFuelL": 100.0,
                "fuelReserveL": 10.0,
                "enabled": True,
            },
        ),
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        diesel_price_yen_per_l=DIESEL_JPY_PER_L,
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        bev_terminal_soc_policy="return_to_initial",
        charging_power_model="constant_power_v0",
        charge_setup_minutes=0,
        charge_teardown_minutes=0,
        minimum_charge_session_minutes=0,
        canonical_depot_id="DEPOT",
        timestep_min=30,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="13:00",
        enable_contract_overage_penalty=False,
        enable_vehicle_cost=False,
        enable_driver_cost=False,
        enable_other_cost=False,
        cost_component_flags=_accounting_only_cost_flags(),
        milp_max_successors_per_trip=None,
        service_coverage_mode="strict",
    )
    return replace(problem, baseline_plan=None)


def _simultaneous_bev_problem(*, charger_ports: int):
    trips = [
        Trip(
            trip_id=f"parallel-{index + 1}",
            route_id="route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time="08:00",
            arrival_time="09:00",
            distance_km=40.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
            operator_id="tokyu",
        )
        for index in range(2)
    ]
    context = DispatchContext(
        service_date="2025-08-05",
        trips=trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        default_turnaround_min=10,
    )
    scenario_vehicles = tuple(
        {
            "id": f"BEV_{index + 1:03d}",
            "type": "BEV",
            "depotId": "DEPOT",
            "batteryKwh": 100.0,
            "energyConsumption": 1.0,
            "chargePowerKw": 20.0,
            "initialSoc": 0.5,
            "minSoc": 0.2,
            "enabled": True,
        }
        for index in range(2)
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id=f"electric-oracle-ports-{charger_ports}",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 2},
        chargers=(
            ChargerDefinition(
                "charger-1",
                "DEPOT",
                20.0,
                simultaneous_ports=charger_ports,
            ),
        ),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=30.0)
            for index in range(4)
        ),
        scenario_vehicles=scenario_vehicles,
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        initial_soc_percent=50.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=50.0,
        final_soc_target_tolerance_percent=0.0,
        bev_terminal_soc_policy="return_to_initial",
        charging_power_model="constant_power_v0",
        charge_setup_minutes=0,
        charge_teardown_minutes=0,
        minimum_charge_session_minutes=0,
        canonical_depot_id="DEPOT",
        timestep_min=60,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="11:00",
        enable_contract_overage_penalty=False,
        enable_vehicle_cost=False,
        enable_driver_cost=False,
        enable_other_cost=False,
        cost_component_flags=_accounting_only_cost_flags(),
        milp_max_successors_per_trip=None,
        service_coverage_mode="strict",
    )
    return replace(problem, baseline_plan=None)


def _integrated_result(problem):
    return OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=False,
            research_run=False,
            allow_postsolve_repair=False,
        ),
    )


def _assignment_by_trip(plan) -> dict[str, str]:
    return {
        trip_id: plan.vehicle_id_for_duty(duty.duty_id)
        for duty in plan.duties
        for trip_id in duty.trip_ids
    }


def test_grid_only_tariff_crosses_hand_calculated_break_even() -> None:
    distance_km = 4 * 10.0
    expected_break_even = (
        distance_km * ICE_L_PER_KM * DIESEL_JPY_PER_L
    ) / (distance_km * BEV_KWH_PER_KM / CHARGE_EFFICIENCY)
    assert expected_break_even == pytest.approx(23.9563439761)

    low_price = solve_small_exact_electric_oracle(
        _mixed_break_even_problem(grid_price_jpy_per_kwh=20.0)
    )
    high_price = solve_small_exact_electric_oracle(
        _mixed_break_even_problem(grid_price_jpy_per_kwh=30.0)
    )

    assert set(low_price.assignment_by_trip.values()) == {"BEV_001"}
    assert low_price.grid_import_kwh == pytest.approx(
        distance_km * BEV_KWH_PER_KM / CHARGE_EFFICIENCY
    )
    assert low_price.fuel_l == pytest.approx(0.0)
    assert set(high_price.assignment_by_trip.values()) == {"ICE_001"}
    assert high_price.grid_import_kwh == pytest.approx(0.0)
    assert high_price.fuel_l == pytest.approx(distance_km * ICE_L_PER_KM)

    certificate = low_price.to_metadata()
    assert certificate["assignment_enumeration_complete"] is True
    assert certificate["charging_subproblem_global_optimality"] == (
        "SCIPY_HIGHS_OPTIMAL"
    )
    assert "zero_pv_zero_bess" in certificate["scope"]


@pytest.mark.parametrize("grid_price_jpy_per_kwh", [20.0, 30.0])
def test_oracle_plan_reconciles_with_canonical_physics_and_accounting(
    grid_price_jpy_per_kwh: float,
) -> None:
    problem = _mixed_break_even_problem(
        grid_price_jpy_per_kwh=grid_price_jpy_per_kwh
    )
    oracle = solve_small_exact_electric_oracle(problem)

    feasibility = FeasibilityChecker().evaluate(problem, oracle.plan)
    accounting = CostEvaluator().evaluate(problem, oracle.plan)

    assert feasibility.feasible is True, feasibility.errors
    assert accounting.electricity_cost == pytest.approx(
        oracle.electricity_cost_jpy, abs=1.0e-6
    )
    assert accounting.fuel_cost == pytest.approx(
        oracle.fuel_cost_jpy, abs=1.0e-6
    )
    assert accounting.total_cost == pytest.approx(
        oracle.canonical_operating_cost_jpy, abs=1.0e-6
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi is required")
@pytest.mark.parametrize("grid_price_jpy_per_kwh", [20.0, 30.0])
def test_integrated_milp_matches_independent_electric_oracle(
    grid_price_jpy_per_kwh: float,
) -> None:
    problem = _mixed_break_even_problem(
        grid_price_jpy_per_kwh=grid_price_jpy_per_kwh
    )
    oracle = solve_small_exact_electric_oracle(problem)
    result = _integrated_result(problem)

    assert result.feasible is True
    assert tuple(result.plan.unserved_trip_ids) == ()
    assert _assignment_by_trip(result.plan) == dict(oracle.assignment_by_trip)
    assert result.cost_breakdown["electricity_cost"] == pytest.approx(
        oracle.electricity_cost_jpy, abs=2.0e-6
    )
    assert result.cost_breakdown["fuel_cost"] == pytest.approx(
        oracle.fuel_cost_jpy, abs=1.0e-6
    )
    assert result.cost_breakdown["total_cost"] == pytest.approx(
        oracle.canonical_operating_cost_jpy, abs=2.0e-6
    )


def test_terminal_soc_requirement_makes_no_charger_case_infeasible() -> None:
    problem = _mixed_break_even_problem(grid_price_jpy_per_kwh=20.0)
    bev_only = replace(
        problem,
        trips=tuple(
            replace(trip, allowed_vehicle_types=("BEV",))
            for trip in problem.trips[:1]
        ),
        dispatch_context=replace(
            problem.dispatch_context,
            trips=list(problem.dispatch_context.trips[:1]),
        ),
        feasible_connections={},
        chargers=(),
    )

    with pytest.raises(SmallElectricOracleInfeasibleError) as exc_info:
        solve_small_exact_electric_oracle(bev_only)

    assert exc_info.value.enumerated_assignment_count == 1
    assert exc_info.value.dispatch_feasible_assignment_count == 1
    assert exc_info.value.energy_feasible_assignment_count == 0


def test_charger_port_shortage_is_detected_by_exact_oracle() -> None:
    with pytest.raises(SmallElectricOracleInfeasibleError) as exc_info:
        solve_small_exact_electric_oracle(
            _simultaneous_bev_problem(charger_ports=1)
        )
    assert exc_info.value.enumerated_assignment_count == 4
    assert exc_info.value.dispatch_feasible_assignment_count == 2
    assert exc_info.value.energy_feasible_assignment_count == 0
    assert exc_info.value.to_metadata()["status"] == "INFEASIBLE"

    feasible_problem = _simultaneous_bev_problem(charger_ports=2)
    feasible = solve_small_exact_electric_oracle(feasible_problem)
    report = FeasibilityChecker().evaluate(feasible_problem, feasible.plan)
    assert feasible.energy_feasible_assignment_count == 2
    assert feasible.used_vehicle_day_count == 2
    assert report.feasible is True, report.errors


def test_nonzero_pv_is_rejected_instead_of_approximated() -> None:
    problem = _mixed_break_even_problem(grid_price_jpy_per_kwh=20.0)
    depot_id, asset = next(iter(problem.depot_energy_assets.items()))
    nonzero_pv_problem = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                pv_enabled=True,
                pv_generation_kwh_by_slot=(1.0,)
                + (0.0,) * (len(problem.price_slots) - 1),
                available_pv_surplus_kwh_by_slot=(1.0,)
                + (0.0,) * (len(problem.price_slots) - 1),
            )
        },
    )

    with pytest.raises(ValueError, match="requires PV=0"):
        solve_small_exact_electric_oracle(nonzero_pv_problem)


def test_nonzero_bess_is_rejected_even_when_disabled() -> None:
    problem = _mixed_break_even_problem(grid_price_jpy_per_kwh=20.0)
    depot_id, asset = next(iter(problem.depot_energy_assets.items()))
    hidden_capacity_problem = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                bess_enabled=False,
                bess_energy_kwh=1.0,
                bess_soc_max_kwh=1.0,
            )
        },
    )

    with pytest.raises(ValueError, match="requires BESS=0"):
        solve_small_exact_electric_oracle(hidden_capacity_problem)
