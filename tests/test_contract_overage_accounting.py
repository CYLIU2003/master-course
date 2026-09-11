from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.run_hourly_charging_reoptimization import _build_executed_day_accounting
from src.dispatch.models import DispatchContext, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    ChargerDefinition,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationEngineResult,
    OptimizationMode,
    OptimizationScenario,
    ProblemDepot,
    ProblemVehicle,
)
from src.optimization.rolling.pv_execution import execute_pv_prefix


def _scenario(*, penalty: object = "missing", enable: object = "missing") -> dict:
    simulation_config = {
        "default_turnaround_min": 10,
        "objective_mode": "total_cost",
        "cost_component_flags": {},
    }
    if penalty != "missing":
        simulation_config["contract_overage_penalty_yen_per_kwh"] = penalty
    if enable != "missing":
        simulation_config["enable_contract_overage_penalty"] = enable
    return {
        "meta": {"updatedAt": "2026-03-31T00:00:00Z"},
        "simulation_config": simulation_config,
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {
                "diesel_price_per_l": 145.0,
                "grid_flat_price_per_kwh": 30.0,
            },
            "charging_constraints": {},
        },
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "ice-1",
                "depotId": "dep-1",
                "type": "ICE",
                "acquisitionCost": 30000000.0,
                "residualValueYen": 6000000.0,
                "lifetimeYear": 12,
                "operationDaysPerYear": 365,
                "fuelConsumptionLPerKm": 0.4,
                "fuelTankL": 280.0,
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["ICE"],
            }
        ],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


@pytest.mark.parametrize(
    ("metadata", "expected_penalty"),
    [
        ({"enable_contract_overage_penalty": True}, 500.0),
        (
            {
                "enable_contract_overage_penalty": True,
                "contract_overage_penalty_yen_per_kwh": None,
            },
            500.0,
        ),
        (
            {
                "enable_contract_overage_penalty": True,
                "contract_overage_penalty_yen_per_kwh": 0.0,
            },
            0.0,
        ),
        (
            {
                "enable_contract_overage_penalty": True,
                "contract_overage_penalty_yen_per_kwh": 20.0,
            },
            20.0,
        ),
        (
            {
                "enable_contract_overage_penalty": False,
                "contract_overage_penalty_yen_per_kwh": 500.0,
            },
            0.0,
        ),
        (
            {
                "enable_contract_overage_penalty": True,
                "contract_overage_penalty_yen_per_kwh": 500.0,
                "cost_component_flags": {"contract_overage_penalty": False},
            },
            0.0,
        ),
    ],
)
def test_contract_overage_cost_policy_matrix(
    metadata: dict[str, object], expected_penalty: float
) -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="contract-cost", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=30.0),),
        metadata=metadata,
    )
    plan = AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"DEPOT": {0: 11.0}},
        contract_over_limit_kwh_by_depot_slot={"DEPOT": {0: 1.0}},
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.contract_over_limit_kwh == pytest.approx(1.0)
    assert breakdown.contract_overage_cost == pytest.approx(expected_penalty)


@pytest.mark.parametrize(
    ("penalty", "expected"), [("missing", 500.0), (None, 500.0), (0.0, 0.0), (20.0, 20.0)]
)
def test_problem_builder_persists_a_finite_contract_overage_penalty(
    penalty: object, expected: float
) -> None:
    scenario = _scenario(penalty=penalty)
    problem = ProblemBuilder().build_from_scenario(
        scenario, depot_id="dep-1", service_id="WEEKDAY"
    )

    persisted = problem.metadata["contract_overage_penalty_yen_per_kwh"]
    assert isinstance(persisted, (int, float))
    assert persisted == pytest.approx(expected)


def _execution_case() -> tuple[
    CanonicalOptimizationProblem,
    CanonicalOptimizationProblem,
    AssignmentPlan,
    OptimizationEngineResult,
]:
    context = DispatchContext(
        service_date="2026-01-01",
        trips=[],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        daily_return_depot_id="DEPOT",
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="executed-contract-cost",
            planning_days=1,
            timestep_min=60,
            horizon_end="02:00",
        ),
        dispatch_context=context,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=50.0,
                battery_capacity_kwh=100.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="DEPOT", name="DEPOT", import_limit_kw=10.0),),
        chargers=(ChargerDefinition("charger", "DEPOT", 20.0),),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=30.0)
            for index in range(2)
        ),
        depot_energy_assets={
            "DEPOT": DepotEnergyAsset(
                depot_id="DEPOT",
                pv_enabled=True,
                # The forecast supplies one kWh of PV in each target slot.
                # Actual PV is zero, so the replay adds one kWh of grid import
                # and creates a one-kWh contract overage in each slot.
                pv_generation_kwh_by_slot=(1.0, 1.0),
            )
        },
        metadata={
            "enable_contract_overage_penalty": True,
            "contract_overage_penalty_yen_per_kwh": 500.0,
        },
    )
    plan = AssignmentPlan(
        charging_slots=tuple(
            # The third command is look-ahead and must not enter the day ledger.
            ChargingSlot(
                "bev-1", slot, "charger", charge_kw=11.0, charging_depot_id="DEPOT"
            )
            for slot in range(3)
        ),
        grid_to_bus_kwh_by_depot_slot={"DEPOT": {0: 10.0, 1: 10.0, 2: 10.0}},
        pv_to_bus_kwh_by_depot_slot={"DEPOT": {0: 1.0, 1: 1.0, 2: 1.0}},
        metadata={"source_provenance_exact": True},
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        solver_metadata={"bev_terminal_soc_balance_satisfied": True},
    )
    return problem, problem, plan, result


def _accounting_case(monkeypatch=None):
    problem, execution_problem, plan, result = _execution_case()
    actual_problem, executed, _audit = execute_pv_prefix(
        execution_problem,
        result,
        actual_pv_by_depot_slot={"DEPOT": {0: 0.0, 1: 0.0}},
        actual_bess_soc_kwh={},
        start_slot=0,
        stop_slot=2,
    )
    if monkeypatch is not None:
        original_evaluate = CostEvaluator.evaluate

        def zero_out_reported_fee(self, evaluated_problem, evaluated_plan):
            return replace(
                original_evaluate(self, evaluated_problem, evaluated_plan),
                contract_overage_cost=0.0,
            )

        monkeypatch.setattr(CostEvaluator, "evaluate", zero_out_reported_fee)
    accounting = _build_executed_day_accounting(
        problem, plan, [(actual_problem, executed, 0, 2)]
    )
    return actual_problem, executed, accounting


def test_executed_pv_prefix_accounts_only_target_slots_and_daily_ledger() -> None:
    actual_problem, executed, accounting = _accounting_case()

    breakdown = accounting["cost_breakdown"]
    assert accounting["eligible"] is True
    assert accounting["contract_overage_accounting"]["consistent"] is True
    assert accounting["contract_overage_accounting"]["executed_overage_kwh"] == pytest.approx(2.0)
    assert accounting["contract_overage_accounting"]["reported_overage_kwh"] == pytest.approx(2.0)
    assert breakdown["contract_overage_cost"] == pytest.approx(1000.0)
    assert breakdown["total_cost"] == pytest.approx(1660.0)

    forecast_breakdown = CostEvaluator().evaluate(actual_problem, _execution_case()[2])
    assert forecast_breakdown.contract_over_limit_kwh == pytest.approx(0.0)
    assert forecast_breakdown.contract_overage_cost == pytest.approx(0.0)

    # The executed result retains the look-ahead command for rolling state, so
    # ledger reconciliation uses the same target prefix that accounting uses.
    target_plan = replace(
        executed.plan,
        charging_slots=tuple(slot for slot in executed.plan.charging_slots if slot.slot_index < 2),
        grid_to_bus_kwh_by_depot_slot={
            depot: {slot: value for slot, value in values.items() if slot < 2}
            for depot, values in executed.plan.grid_to_bus_kwh_by_depot_slot.items()
        },
        pv_to_bus_kwh_by_depot_slot={
            depot: {slot: value for slot, value in values.items() if slot < 2}
            for depot, values in executed.plan.pv_to_bus_kwh_by_depot_slot.items()
        },
        contract_over_limit_kwh_by_depot_slot={
            depot: {slot: value for slot, value in values.items() if slot < 2}
            for depot, values in executed.plan.contract_over_limit_kwh_by_depot_slot.items()
        },
    )
    evaluator = CostEvaluator()
    ledger_breakdown = evaluator.evaluate(actual_problem, target_plan)
    _vehicle_ledger, daily_ledger = evaluator.build_plan_ledgers(
        actual_problem, target_plan, ledger_breakdown
    )
    assert sum(row.total_cost_jpy for row in daily_ledger) == pytest.approx(
        ledger_breakdown.total_cost
    )
    assert ledger_breakdown.contract_overage_cost == pytest.approx(1000.0)
    assert all(row.total_cost_jpy == pytest.approx(1660.0) for row in daily_ledger)


def test_executed_accounting_gate_rejects_positive_overage_with_zero_reported_fee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _actual_problem, _executed, accounting = _accounting_case(monkeypatch)

    audit = accounting["contract_overage_accounting"]
    assert audit["executed_overage_kwh"] == pytest.approx(2.0)
    assert audit["reported_cost_jpy"] == pytest.approx(0.0)
    assert audit["expected_cost_jpy"] == pytest.approx(1000.0)
    assert audit["consistent"] is False
    assert audit["cost_difference_jpy"] == pytest.approx(1000.0)
    assert accounting["eligible"] is False
    assert "contract_overage_accounting_mismatch" in accounting["rejection_reasons"]
