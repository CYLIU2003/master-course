from dataclasses import replace
from types import SimpleNamespace

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ChargerDefinition,
    OptimizationConfig,
    OptimizationMode,
    EnergyPriceSlot,
)
from src.optimization.common.builder import ProblemBuilder
from src.optimization.engine import (
    OptimizationEngine,
    actual_cost_objective_reconciles,
)
from test_post_return_soc_target import _dispatch_context


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="actual-cost-contract",
            objective_mode="total_cost",
            service_coverage_mode="strict",
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(),
        objective_weights=OptimizationObjectiveWeights(
            energy=2.0,
            fuel=3.0,
            demand=4.0,
            switch=5.0,
            degradation=6.0,
            return_leg_bonus=7.0,
        ),
        depot_energy_assets={
            "depot": DepotEnergyAsset(
                depot_id="depot",
                bess_enabled=True,
                bess_energy_kwh=6000.0,
                bess_power_kw=900.0,
                bess_initial_soc_kwh=3000.0,
                bess_soc_min_kwh=1200.0,
                bess_soc_max_kwh=4800.0,
                bess_terminal_soc_min_kwh=1200.0,
            )
        },
        metadata={
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "vehicle_usage_cost_semantics": "unclassified",
            "cost_component_flags": {},
        },
    )


def test_integrated_actual_cost_contract_removes_nonaccounting_terms() -> None:
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        _problem()
    )
    flags = aligned.metadata["cost_component_flags"]

    assert aligned.objective_weights.energy == 1.0
    assert aligned.objective_weights.fuel == 1.0
    assert aligned.objective_weights.demand == 1.0
    assert aligned.objective_weights.switch == 0.0
    assert aligned.objective_weights.degradation == 1.0
    assert aligned.objective_weights.return_leg_bonus == 0.0
    assert flags["grid_to_bus_priority_penalty"] is False
    assert flags["opportunistic_topup_deficit_penalty"] is False
    assert flags["battery_degradation_cost"] is True
    assert aligned.metadata["pv_curtail_penalty_yen_per_kwh"] == 0.0
    assert aligned.depot_energy_assets["depot"].bess_terminal_soc_target_kwh == 3000.0
    assert aligned.depot_energy_assets["depot"].bess_terminal_soc_policy == (
        "return_to_initial"
    )
    assert aligned.metadata[
        "research_economic_claim_blocked_by_vehicle_usage_cost_semantics"
    ] is True


def test_actual_cost_objective_reconciliation_fails_closed() -> None:
    assert actual_cost_objective_reconciles(
        raw_objective_jpy=100.0,
        accounting_total_jpy=100.0,
        structural_contract_passed=True,
        feasible=True,
        solution_unmodified=True,
    )


def test_provisional_vehicle_day_cost_remains_research_blocked() -> None:
    problem = _problem()
    problem = replace(
        problem,
        metadata={
            **dict(problem.metadata),
            "vehicle_usage_cost_semantics": "provisional_sensitivity",
        },
    )
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        problem
    )

    assert aligned.metadata["vehicle_usage_cost_semantics_classified"] is True
    assert aligned.metadata[
        "vehicle_usage_cost_semantics_research_eligible"
    ] is False
    assert aligned.metadata[
        "research_economic_claim_blocked_by_vehicle_usage_cost_semantics"
    ] is True
    assert not actual_cost_objective_reconciles(
        raw_objective_jpy=100.01,
        accounting_total_jpy=100.0,
        structural_contract_passed=True,
        feasible=True,
        solution_unmodified=True,
    )


def test_integrated_ev_utilization_keeps_cost_contract_without_cost_claim() -> None:
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        _problem(),
        objective_kind="minimum_ice_fuel_lexicographic",
    )

    assert aligned.metadata["integrated_actual_cost_contract_applied"] is True
    assert aligned.metadata["integrated_actual_cost_objective_requested"] is False
    assert aligned.metadata["integrated_primary_objective_kind"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert aligned.metadata["actual_cost_objective_structural_contract_passed"] is True


def test_phase4_solver_reconciles_integrated_actual_cost_on_full_day() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-solver",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata[
        "actual_cost_objective_numeric_reconciliation_passed"
    ] is True
    assert result.solver_metadata[
        "solver_objective_matches_accounting_total"
    ] is True
    assert result.cost_breakdown["objective_is_actual_cost"] is True


def test_phase4_ev_utilization_enforces_canonical_cost_cap() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="ev-utilization-cost-cap",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    baseline = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )
    cost_cap = float(baseline.cost_breakdown["total_cost"]) * 1.01

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_ev_utilization_mode=(
                "minimum_ice_fuel_lexicographic"
            ),
            integrated_actual_cost_upper_bound_jpy=cost_cap,
            integrated_actual_cost_upper_bound_delta_ratio=0.01,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.cost_breakdown["total_cost"] <= cost_cap + 1.0e-6
    assert result.cost_breakdown["objective_is_actual_cost"] is False
    assert result.solver_metadata["integrated_ev_utilization_mode"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert result.solver_metadata[
        "integrated_actual_cost_contract_applied"
    ] is True
    assert result.solver_metadata["integrated_primary_objective_kind"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert result.solver_metadata[
        "integrated_actual_cost_upper_bound_verified"
    ] is True
    assert result.solver_metadata["integrated_primary_ice_fuel_l"] >= 0.0
