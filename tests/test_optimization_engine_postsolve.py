from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    OptimizationScenario,
    OptimizationObjectiveWeights,
    ProblemDepot,
)
from src.optimization.engine import OptimizationEngine, _derive_depot_energy_source_split, _repair_bess_terminal_soc


class _FakeMILPOptimizer:
    def __init__(self, result: OptimizationEngineResult) -> None:
        self._result = result

    def solve(self, problem, config) -> OptimizationEngineResult:  # noqa: ANN001
        return self._result


def test_postsolve_bess_terminal_soc_repair_shifts_late_discharge_to_grid() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-bess", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                bess_enabled=True,
                bess_energy_kwh=100.0,
                bess_power_kw=100.0,
                bess_initial_soc_kwh=50.0,
                bess_soc_min_kwh=0.0,
                bess_soc_max_kwh=100.0,
                bess_discharge_efficiency=1.0,
                bess_terminal_soc_min_kwh=30.0,
            )
        },
    )
    plan = AssignmentPlan(
        bess_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0, 1: 30.0}},
    )

    repaired = _repair_bess_terminal_soc(problem, plan)

    assert repaired.bess_to_bus_kwh_by_depot_slot["dep-1"][0] == 10.0
    assert repaired.bess_to_bus_kwh_by_depot_slot["dep-1"].get(1, 0.0) == 10.0
    assert repaired.grid_to_bus_kwh_by_depot_slot["dep-1"][1] == 20.0
    assert repaired.bess_soc_kwh_by_depot_slot["dep-1"][1] == 30.0
    assert repaired.metadata["bess_terminal_soc_violation_kwh"] == 0.0
    assert repaired.metadata["bess_terminal_soc_repair_shifted_to_grid_kwh"] == 20.0
    assert repaired.metadata["bess_terminal_soc_target_kwh_by_depot"] == {}
    assert repaired.metadata["bess_terminal_soc_deviation_kwh_by_depot"] == {}


def test_explicit_phase3_contract_preserves_solver_plan_without_postsolve_repair() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-phase3-no-repair", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0),
        ),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                bess_enabled=True,
                bess_energy_kwh=100.0,
                bess_power_kw=100.0,
                bess_initial_soc_kwh=50.0,
                bess_soc_min_kwh=0.0,
                bess_soc_max_kwh=100.0,
                bess_discharge_efficiency=1.0,
                bess_terminal_soc_min_kwh=30.0,
            )
        },
    )
    plan = AssignmentPlan(
        bess_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0, 1: 30.0}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={},
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage"),
    )

    assert result.plan.bess_to_bus_kwh_by_depot_slot == {"dep-1": {0: 10.0, 1: 30.0}}
    assert result.solver_metadata["postsolve_repair_allowed"] is False
    assert result.solver_metadata["postsolve_soc_repair_applied"] is False


def test_two_stage_accounting_total_is_not_labelled_as_solver_cost_optimal() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-two-stage-objective", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "thesis_mode": True,
            "objective_actual_cost_mode": True,
            "solver_objective_matches_accounting_total": False,
        },
    )
    breakdown = CostEvaluator().evaluate(
        problem,
        AssignmentPlan(
            metadata={"solver_objective_matches_accounting_total": False}
        ),
    )

    assert breakdown.objective_value == breakdown.total_cost
    assert breakdown.objective_is_actual_cost is False


def test_research_phase3_accepts_feasibility_but_not_a_global_cost_claim() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-research-gate", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={"research_fleet_validation": {"status": "OK"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=AssignmentPlan(
            metadata={
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
                "stage1_energy_envelope_constraint_count": 35,
                "stage1_energy_envelope_semantics": (
                    "optimistic_vehicle_local_necessary_condition"
                ),
                "stage1_time_indexed_soc_relaxation_constraint_count": 123,
                "stage1_time_indexed_soc_relaxation_semantics": (
                    "location_aware_cumulative_soc_with_single_vehicle_slot_"
                    "charge_cap_necessary_condition"
                ),
                "stage1_energy_cost_proxy_configuration": {
                    "enabled": True,
                    "charge_efficiency": 0.95,
                },
                "stage1_energy_cost_proxy_weather_input": {
                    "pv_available_kwh_by_depot": {"depot": 100.0}
                },
                "stage1_energy_cost_proxy_result": {
                    "grid_to_bus_kwh": 10.0
                },
            }
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
            solver_metadata={
                "supports_exact_milp": True,
                "supports_two_stage_milp": True,
                "requested_phase_token": "phase3_two_stage",
                "requested_phase": "phase3_two_stage",
                "resolved_phase": "phase3_two_stage",
                "executed_phase": "phase3_two_stage",
            },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.solver_status == "optimal"
    assert result.solver_metadata["research_run"] is True
    assert result.solver_metadata["research_run_accepted"] is True
    assert result.solver_metadata["research_feasibility_eligible"] is True
    assert result.solver_metadata["research_cost_kpi_eligible"] is False
    assert result.solver_metadata["single_continuous_vehicle_duty"] is True
    assert result.solver_metadata["stage1_energy_envelope_constraint_count"] == 35
    assert result.solver_metadata["stage1_energy_envelope_semantics"] == (
        "optimistic_vehicle_local_necessary_condition"
    )
    assert result.solver_metadata[
        "stage1_time_indexed_soc_relaxation_constraint_count"
    ] == 123
    assert result.solver_metadata["stage1_time_indexed_soc_relaxation_semantics"] == (
        "location_aware_cumulative_soc_with_single_vehicle_slot_"
        "charge_cap_necessary_condition"
    )
    assert result.solver_metadata["stage1_energy_cost_proxy_configuration"] == {
        "enabled": True,
        "charge_efficiency": 0.95,
    }
    assert result.solver_metadata["stage1_energy_cost_proxy_weather_input"] == {
        "pv_available_kwh_by_depot": {"depot": 100.0}
    }
    assert result.solver_metadata["stage1_energy_cost_proxy_result"] == {
        "grid_to_bus_kwh": 10.0
    }
    assert "objective_is_actual_cost" not in result.solver_metadata["research_acceptance_checks"]


def test_research_run_rejects_undeclared_vehicle_inventory_contract() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-undeclared-fleet",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=AssignmentPlan(
            metadata={
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
            }
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={
            "supports_exact_milp": True,
            "supports_two_stage_milp": True,
            "requested_phase_token": "phase3_two_stage",
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
        },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.solver_metadata["research_run_accepted"] is False
    assert (
        result.solver_metadata["research_acceptance_checks"][
            "research_vehicle_inventory_contract"
        ]
        is False
    )


def test_research_phase3_publishes_accounting_cost_only_when_ev_energy_is_restored() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-balanced-cost",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "research_fleet_validation": {"status": "OK"},
        },
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=AssignmentPlan(
            metadata={
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
                "bev_terminal_soc_policy": "return_to_initial",
                "bev_terminal_soc_balance_satisfied": True,
            }
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={
            "supports_exact_milp": True,
            "supports_two_stage_milp": True,
            "source_provenance_exact": True,
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_balance_satisfied": True,
            "requested_phase_token": "phase3_two_stage",
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
        },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.solver_metadata["research_run_accepted"] is True
    assert result.solver_metadata["research_accounting_cost_eligible"] is True
    assert result.solver_metadata["research_cost_kpi_eligible"] is True
    assert result.solver_metadata["research_cost_optimality_eligible"] is False
    assert result.solver_metadata["research_cost_acceptance_checks"] == {
        "research_run_accepted": True,
        "full_operational_validation": True,
        "source_provenance_exact": True,
        "bev_terminal_policy_return_to_initial": True,
        "bev_terminal_soc_balance_satisfied": True,
        "ev_energy_inventory_balanced": True,
    }
    assert any(
        "global total-cost optimality is not established" in warning
        for warning in result.warnings
    )


def test_balanced_phase1_warning_identifies_assignment_scope_not_energy_gap() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-balanced-phase1",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "research_fleet_validation": {"status": "OK"},
        },
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=AssignmentPlan(
            metadata={
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
                "bev_terminal_soc_policy": "return_to_initial",
                "bev_terminal_soc_balance_satisfied": True,
            }
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={
            "supports_exact_milp": True,
            "charging_dispatch_evaluated": True,
            "soc_constraints_evaluated": True,
            "source_provenance_exact": True,
            "bev_terminal_soc_policy": "return_to_initial",
            "bev_terminal_soc_balance_satisfied": True,
            "requested_phase_token": "phase1_charging_only",
            "requested_phase": "phase1_charging_only",
            "resolved_phase": "phase1_charging_only",
            "executed_phase": "phase1_charging_only",
        },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase1_charging_only",
            research_run=True,
        ),
    )

    assert result.solver_metadata["research_run_accepted"] is True
    assert result.solver_metadata["research_cost_kpi_eligible"] is False
    assert any(
        "accounting trace is balanced" in warning
        and "global assignment" in warning
        for warning in result.warnings
    )
    assert not any(
        "terminal energy inventory" in warning for warning in result.warnings
    )


def test_research_rejection_preserves_a_real_feasible_incumbent_status() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-pruned-network",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="time_limit",
        objective_value=0.0,
        plan=AssignmentPlan(
            metadata={
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
            }
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={
            "supports_exact_milp": False,
            "supports_two_stage_milp": True,
            "has_feasible_incumbent": True,
            "requested_phase_token": "phase3_two_stage",
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
        },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.feasible is True
    assert result.solver_status == "time_limit"
    assert result.solver_metadata["research_run_accepted"] is False
    assert result.solver_metadata["research_cost_kpi_eligible"] is False
    assert result.solver_metadata["result_class"] == "feasible_research_ineligible"
    assert result.solver_metadata["termination_reason"] == (
        "feasible_incumbent_research_acceptance_failed"
    )


def test_research_phase3_rejects_disconnected_vehicle_fragments() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-fragment-gate",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=AssignmentPlan(
            duties=(
                VehicleDuty(duty_id="duty-1", vehicle_type="BEV", legs=()),
                VehicleDuty(duty_id="duty-2", vehicle_type="BEV", legs=()),
            ),
            metadata={
                "duty_vehicle_map": {"duty-1": "bev-1", "duty-2": "bev-1"},
                "source_provenance_exact": True,
                "vehicle_source_provenance_exact": True,
            },
        ),
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={
            "supports_exact_milp": True,
            "supports_two_stage_milp": True,
            "requested_phase_token": "phase3_two_stage",
            "requested_phase": "phase3_two_stage",
            "resolved_phase": "phase3_two_stage",
            "executed_phase": "phase3_two_stage",
        },
    )
    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.feasible is False
    assert result.solver_status == "NO_VALID_INCUMBENT"
    assert result.solver_metadata["research_run_accepted"] is False
    assert result.solver_metadata["research_feasibility_eligible"] is False
    assert result.solver_metadata["single_continuous_vehicle_duty"] is False


def test_research_contract_disables_the_non_accounting_return_leg_bonus() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-research-objective", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        objective_weights=OptimizationObjectiveWeights(return_leg_bonus=3.0),
    )

    contracted_problem, contracted_config = OptimizationEngine._apply_phase_contract(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, research_run=True),
    )

    assert contracted_config.allow_postsolve_repair is False
    assert contracted_problem.objective_weights.return_leg_bonus == 0.0
    assert contracted_problem.metadata["return_leg_bonus_disabled_for_research"] is True


def test_research_contract_forces_strict_coverage() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s-research-strict",
            timestep_min=60,
            service_coverage_mode="penalized",
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )

    contracted_problem, _ = OptimizationEngine._apply_phase_contract(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, research_run=True),
    )

    assert contracted_problem.scenario.service_coverage_mode == "strict"
    assert contracted_problem.metadata["research_forced_strict_coverage"] is True


def test_research_contract_rejects_an_unrecognized_phase_without_reenabling_repair() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-research-unknown-phase", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )

    _, contracted_config = OptimizationEngine._apply_phase_contract(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="unknown_phase",
            research_run=True,
            allow_postsolve_repair=True,
        ),
    )

    assert contracted_config.allow_postsolve_repair is False


def test_postsolve_bess_soc_repair_respects_configured_max_buffer() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-bess-max", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                bess_enabled=True,
                bess_energy_kwh=500.0,
                bess_power_kw=500.0,
                bess_initial_soc_kwh=390.0,
                bess_soc_min_kwh=100.0,
                bess_soc_max_kwh=400.0,
                bess_charge_efficiency=1.0,
                bess_discharge_efficiency=1.0,
                pv_generation_kwh_by_slot=(50.0,),
            )
        },
    )
    plan = AssignmentPlan(
        pv_to_bess_kwh_by_depot_slot={"dep-1": {0: 50.0}},
        pv_curtail_kwh_by_depot_slot={"dep-1": {0: 0.0}},
    )

    repaired = _repair_bess_terminal_soc(problem, plan)

    assert repaired.pv_to_bess_kwh_by_depot_slot["dep-1"][0] == 10.0
    assert repaired.pv_curtail_kwh_by_depot_slot["dep-1"][0] == 40.0
    assert repaired.bess_soc_kwh_by_depot_slot["dep-1"][0] == 400.0
    assert repaired.metadata["bess_soc_end_kwh_by_depot_slot"]["dep-1"][0] == 400.0
    assert repaired.metadata["bess_soc_boundary_adjusted_kwh"] == 40.0


def test_postsolve_source_split_prefers_direct_pv_before_bess_discharge() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-pv-first", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0),),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(10.0,),
                bess_enabled=True,
                bess_energy_kwh=100.0,
                bess_power_kw=100.0,
                bess_initial_soc_kwh=60.0,
                bess_soc_min_kwh=0.0,
                bess_soc_max_kwh=100.0,
                bess_discharge_efficiency=1.0,
                bess_terminal_soc_target_kwh=50.0,
            )
        },
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="veh-1",
                slot_index=0,
                charger_id="grid:dep-1",
                charge_kw=15.0,
                charging_depot_id="dep-1",
            ),
        )
    )

    split = _derive_depot_energy_source_split(problem, plan)

    assert split.pv_to_bus_kwh_by_depot_slot["dep-1"][0] == 10.0
    assert split.bess_to_bus_kwh_by_depot_slot["dep-1"][0] == 5.0
    assert split.grid_to_bus_kwh_by_depot_slot.get("dep-1", {}).get(0, 0.0) == 0.0
    assert split.bess_soc_kwh_by_depot_slot["dep-1"][0] == 55.0
    assert split.metadata["bess_terminal_soc_target_kwh_by_depot"] == {"dep-1": 50.0}
    assert split.metadata["bess_terminal_soc_deviation_kwh_by_depot"] == {"dep-1": 5.0}


def test_optimization_engine_rebuilds_impossible_fragment_sequence() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:45",
        arrival_time="09:15",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_postsolve_rebuild",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=5),),
            ),
            VehicleDuty(
                duty_id="veh-1__frag2",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=10),),
            ),
        ),
        served_trip_ids=("t_a", "t_b"),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.feasible is False
    assert result.plan.served_trip_ids == ("t_a",)
    assert result.plan.unserved_trip_ids == ("t_b",)
    assert result.plan.duty_vehicle_map() == {"BEV_001": "BEV_001"}
    assert result.solver_metadata.get("postsolve_assignment_rebuilt") is True
    assert result.solver_metadata.get("postsolve_feasible") is False


def test_optimization_engine_merges_directly_connectable_same_band_fragments() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:50",
        arrival_time="09:20",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-c"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-c",
                travel_time_min=5,
            ),
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_postsolve_merge",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=5),),
            ),
            VehicleDuty(
                duty_id="veh-1__frag2",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=10),),
            ),
        ),
        served_trip_ids=("t_a", "t_b"),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
        cost_breakdown={"objective_value": 0.0, "total_cost": 0.0},
        solver_metadata={},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.feasible is True
    assert result.plan.served_trip_ids == ("t_a", "t_b")
    assert result.plan.unserved_trip_ids == ()
    assert len(result.plan.duties) == 1
    assert result.plan.duties[0].trip_ids == ["t_a", "t_b"]
    assert result.plan.duties[0].legs[1].deadhead_from_prev_min == 5


def test_optimization_engine_uses_truthful_baseline_guardrail_when_milp_candidate_is_worse() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Depot",
        destination="Stop A",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-depot",
        destination_stop_id="stop-a",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-a",
        origin="Stop A",
        destination="Depot",
        departure_time="08:40",
        arrival_time="09:10",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-depot",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_truthful_guardrail",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        canonical_depot_id="dep1",
    )
    weak_plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=0),),
            ),
        ),
        served_trip_ids=("t_a",),
        unserved_trip_ids=("t_b",),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )
    fake_result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=123.0,
        plan=weak_plan,
        feasible=True,
        cost_breakdown={"objective_value": 123.0, "total_cost": 123.0},
        solver_metadata={"supports_exact_milp": True},
    )

    engine = OptimizationEngine()
    engine._milp = _FakeMILPOptimizer(fake_result)

    result = engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=5, mip_gap=0.0),
    )

    assert result.solver_status == "baseline_fallback"
    assert result.plan.unserved_trip_ids == ()
    assert tuple(sorted(result.plan.served_trip_ids)) == ("t_a", "t_b")
    assert result.solver_metadata.get("truthful_baseline_guardrail_applied") is True
    assert result.solver_metadata.get("supports_exact_milp") is False
