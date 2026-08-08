from dataclasses import replace
from types import SimpleNamespace

import pytest

import src.optimization.engine as optimization_engine_module
from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
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
from src.optimization.common.seed_fingerprint import (
    phase4_seed_plan_fingerprint,
)
from src.optimization.engine import (
    OptimizationEngine,
    _phase4_seed_composition_search_limits,
    _phase4_seed_inventory_span_truncated,
    actual_cost_objective_reconciles,
)
from src.gurobi_runtime import ensure_gurobi
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    _actual_bess_terminal_soc_deviation_by_depot,
)
from test_post_return_soc_target import _dispatch_context


def test_phase4_seed_composition_search_scales_with_selected_fleet() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=60,
        requested_candidate_limit=1,
        requested_radius=0,
    )

    assert candidate_limit == 61
    assert radius == 60


def test_phase4_seed_composition_search_preserves_small_scope_floor() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=2,
        requested_candidate_limit=1,
        requested_radius=0,
    )

    assert candidate_limit == 21
    assert radius == 10


def test_phase4_seed_composition_search_caps_oversized_scope() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=100,
        requested_candidate_limit=500,
        requested_radius=500,
    )

    assert candidate_limit == 100
    assert radius == 100
    assert _phase4_seed_inventory_span_truncated(99) is False
    assert _phase4_seed_inventory_span_truncated(100) is True


def _same_slot_back_to_back_problem(
    vehicle_type: str,
) -> CanonicalOptimizationProblem:
    """Build two feasible trips that share one coarse energy slot.

    The first trip plus the canonical ten-minute turnaround ends exactly when
    the second trip departs.  Both trips intersect the 07:00--08:00 energy
    slot, but they never overlap in physical time.
    """
    dispatch_context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="trip-0703",
                route_id="route-a-b",
                origin="DEPOT",
                destination="B",
                departure_time="07:03",
                arrival_time="07:47",
                distance_km=5.0,
                allowed_vehicle_types=(vehicle_type,),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
                operator_id="tokyu",
            ),
            Trip(
                trip_id="trip-0757",
                route_id="route-b-depot",
                origin="B",
                destination="DEPOT",
                departure_time="07:57",
                arrival_time="08:48",
                distance_km=5.0,
                allowed_vehicle_types=(vehicle_type,),
                origin_stop_id="B",
                destination_stop_id="DEPOT",
                operator_id="tokyu",
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            vehicle_type: VehicleProfile(
                vehicle_type=vehicle_type,
                battery_capacity_kwh=(
                    100.0 if vehicle_type == "BEV" else None
                ),
                energy_consumption_kwh_per_km=(
                    1.0 if vehicle_type == "BEV" else None
                ),
                fuel_tank_capacity_l=(
                    100.0 if vehicle_type == "ICE" else None
                ),
                fuel_consumption_l_per_km=(
                    0.1 if vehicle_type == "ICE" else None
                ),
            )
        },
        default_turnaround_min=10,
    )
    return ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id="same-slot-back-to-back",
        vehicle_counts={vehicle_type: 1},
        chargers=(
            (ChargerDefinition("chg-1", "DEPOT", 60.0),)
            if vehicle_type == "BEV"
            else ()
        ),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=30.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )


def _late_final_slot_problem() -> CanonicalOptimizationProblem:
    """Build one BEV trip spanning the final two hourly SOC slots."""

    dispatch_context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="late-final-trip",
                route_id="late-route",
                origin="Depot",
                destination="Terminal",
                departure_time="22:50",
                arrival_time="23:14",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
                operator_id="tokyu",
            )
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "Depot"): DeadheadRule("DEPOT", "Depot", 0),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 4),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        location_aliases={"Depot": ("DEPOT",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id="late-final-slot-integrated",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="00:00",
        operation_end_time="23:59",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                # Make the active final slot uniquely cheapest.  A missing
                # C12 row would deterministically attract illegal charging.
                grid_buy_yen_per_kwh=(0.0 if slot_index == 23 else 10.0),
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    # Keep enough headroom to charge the late trip's energy before departure;
    # the actual-cost contract changes the terminal policy to return-to-initial.
    return replace(
        problem,
        vehicles=tuple(
            replace(vehicle, initial_soc=80.0)
            for vehicle in problem.vehicles
        ),
    )


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
    assert result.solver_metadata["assignment_energy_coupling_mode"] == (
        "phase4_integrated_slot_energy_recourse"
    )
    assert result.solver_metadata["solve_time_sec"] is not None
    terminal_targets = result.solver_metadata[
        "vehicle_terminal_soc_target_kwh_by_vehicle"
    ]
    terminal_values = result.solver_metadata[
        "vehicle_terminal_soc_kwh_by_vehicle"
    ]
    terminal_contract = result.plan.metadata[
        "bev_terminal_soc_numeric_acceptance_contract"
    ]
    accepted_deviation_kwh = (
        terminal_contract["scientific_tolerance_kwh"]
        + terminal_contract["numeric_comparison_margin_kwh"]
    )

    assert result.solver_metadata["bev_terminal_soc_balance_satisfied"] is True
    assert terminal_targets
    assert terminal_values.keys() == terminal_targets.keys()
    assert result.plan.metadata["bev_terminal_soc_balance_satisfied"] is True
    for vehicle_id, target_kwh in terminal_targets.items():
        assert terminal_values[vehicle_id] == pytest.approx(
            target_kwh,
            abs=accepted_deviation_kwh,
        )


def test_phase4_degradation_uses_canonical_throughput_price() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-degradation-throughput",
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
        battery_degradation_price_jpy_per_kwh=2.5,
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
    charged_kwh = sum(
        slot.charge_kw * problem.scenario.timestep_min / 60.0
        for slot in result.plan.charging_slots
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.cost_breakdown["degradation_cost"] == pytest.approx(
        charged_kwh * 2.5
    )
    assert result.solver_metadata[
        "solver_objective_matches_accounting_total"
    ] is True


def test_phase4_final_slot_trip_has_one_energy_debit_and_no_trip_charge() -> None:
    problem = _late_final_slot_problem()

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
    assert result.solver_metadata["bev_terminal_soc_balance_satisfied"] is True
    assert all(
        slot.slot_index != 23
        for slot in result.plan.charging_slots
    )
    assert not any(
        "charging occurs during active trip slot 23" in reason
        or "exceeds return-to-initial" in reason
        for reason in result.infeasibility_reasons
    )
    terminal_values = result.solver_metadata[
        "vehicle_terminal_soc_kwh_by_vehicle"
    ]
    terminal_targets = result.solver_metadata[
        "vehicle_terminal_soc_target_kwh_by_vehicle"
    ]
    assert terminal_values.keys() == terminal_targets.keys()
    for vehicle_id, target_kwh in terminal_targets.items():
        assert terminal_values[vehicle_id] == pytest.approx(
            target_kwh,
            abs=1.0e-6,
        )


def test_bess_terminal_deviation_uses_physical_soc_trace() -> None:
    deviations = _actual_bess_terminal_soc_deviation_by_depot(
        bess_soc_end_kwh_by_depot_slot={
            "DEPOT": {0: 49.0, 23: 50.0},
        },
        bess_terminal_soc_target_kwh_by_depot={"DEPOT": 50.0},
    )

    assert deviations == {"DEPOT": 0.0}


def test_bess_terminal_deviation_fails_without_physical_soc_trace() -> None:
    with pytest.raises(
        RuntimeError,
        match="BESS terminal target has no solved end-of-slot SOC trace",
    ):
        _actual_bess_terminal_soc_deviation_by_depot(
            bess_soc_end_kwh_by_depot_slot={},
            bess_terminal_soc_target_kwh_by_depot={"DEPOT": 50.0},
        )


@pytest.mark.parametrize("vehicle_type", ["BEV", "ICE"])
def test_phase4_allows_back_to_back_trips_inside_one_energy_slot(
    vehicle_type: str,
) -> None:
    problem = _same_slot_back_to_back_problem(vehicle_type)
    first_trip, second_trip = problem.trips

    assert first_trip.arrival_min + problem.dispatch_context.default_turnaround_min == (
        second_trip.departure_min
    )
    assert GurobiMILPAdapter()._slot_index(
        problem, first_trip.departure_min
    ) == GurobiMILPAdapter()._slot_index(
        problem, second_trip.departure_min
    )

    outcome, plan = GurobiMILPAdapter().solve(
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
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent, outcome.solver_status
    assert set(plan.served_trip_ids) == {"trip-0703", "trip-0757"}
    assert plan.unserved_trip_ids == ()


def _phase4_seed_problem(
    scenario_id: str = "actual-cost-verified-phase3-seed",
) -> CanonicalOptimizationProblem:
    dispatch_context = _dispatch_context()
    dispatch_context = replace(
        dispatch_context,
        trips=tuple(
            replace(trip, operator_id="tokyu")
            for trip in dispatch_context.trips
        ),
    )
    problem = ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id=scenario_id,
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
    return replace(
        problem,
        depot_energy_assets={
            "DEPOT": DepotEnergyAsset(
                depot_id="DEPOT",
                bess_enabled=True,
                bess_energy_kwh=200.0,
                bess_power_kw=60.0,
                bess_initial_soc_kwh=100.0,
                bess_soc_min_kwh=20.0,
                bess_soc_max_kwh=180.0,
                bess_terminal_soc_min_kwh=20.0,
            )
        },
        metadata={
            **dict(problem.metadata or {}),
            "research_fleet_validation": {"status": "OK"},
            "service_calendar_validation": {"status": "OK"},
        },
    )


def test_phase4_uses_verified_same_problem_phase3_plan_as_complete_mip_start() -> None:
    problem = _phase4_seed_problem()
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is True
    assert result.solver_metadata["warm_start_source"] == (
        "verified_phase3_two_stage_phase4_mip_start"
    )
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "accepted"
    ] is True
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_stage1_stage2_candidate_limit"
    ] == 21
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_stage1_composition_search_radius"
    ] == 10
    composition_certificate = result.solver_metadata[
        "stage1_used_powertrain_composition_search"
    ]
    assert composition_certificate["enabled"] is True
    assert composition_certificate["radius_requested"] == 10
    assert result.solver_metadata[
        "stage1_used_powertrain_composition_search_accepted"
    ] is True
    assert len(
        result.solver_metadata["phase4_phase3_seed_audit"][
            "seed_plan_fingerprint"
        ]
    ) == 64
    audit = result.plan.metadata["integrated_warm_start_audit"]
    assert audit["applied"] is True
    assert audit["same_canonical_problem"] is True
    assert audit["complete_assignment_binary_start"] is True
    assert audit["complete_charger_binary_start"] is True
    assert audit["complete_vehicle_soc_start"] is True
    assert audit["complete_bess_soc_start"] is True
    assert audit["complete_bess_mode_binary_start"] is True
    assert audit["bess_mode_binary_start_count"] > 0
    assert audit["physical_energy_trace_start"] is True
    assert audit["dispatch_fixed_recourse_requested"] is True
    assert audit["integrated_dispatch_fixed_recourse_feasible"] is True
    assert audit["integrated_feasible_start_applied"] is True
    assert audit["complete_integrated_solution_start"] is True
    assert audit["integrated_solution_start_count"] > 0
    assert len(audit["integrated_solution_start_fingerprint"]) == 64
    assert audit["dispatch_fixed_recourse_runtime_sec"] >= 0.0
    assert result.solver_metadata["first_feasible_sec"] == 0.0
    assert result.solver_metadata["integrated_mip_focus"] == 1
    assert result.solver_metadata["integrated_heuristics"] == pytest.approx(
        0.5
    )
    assert result.solver_metadata["integrated_symmetry"] == -1
    assert result.solver_metadata["integrated_search_profile"][
        "phase_count_executed"
    ] == 1
    assert result.solver_metadata["integrated_search_profile"]["phases"][0][
        "phase"
    ] == "uninterrupted_incumbent_and_bound_search"
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_runtime_sec"
    ] > 0.0
    assert result.solver_metadata[
        "actual_cost_objective_numeric_reconciliation_passed"
    ] is True
    assert result.solver_metadata["research_run_accepted"] is True
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_declared_seed_handoff_satisfied"
    ] is True
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_no_hidden_bev_directed_seed"
    ] is True


def test_phase4_formal_gate_rejects_failed_declared_seed(monkeypatch) -> None:
    problem = _phase4_seed_problem("actual-cost-rejected-formal-seed")
    monkeypatch.setattr(
        optimization_engine_module,
        "phase4_seed_plan_fingerprint",
        lambda _plan: "",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "accepted"
    ] is False
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_declared_seed_handoff_satisfied"
    ] is False
    assert result.solver_metadata["research_run_accepted"] is False


def test_integrated_seed_recourse_preflight_restores_bounds_and_exports_iis() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("phase4_seed_recourse_negative_contract")
    model.Params.OutputFlag = 0
    dispatch = model.addVar(vtype=GRB.BINARY, name="dispatch_seed")
    model.addConstr(dispatch == 0.0, name="integrated_only_conflict")
    model.setObjective(0.0, GRB.MINIMIZE)
    model.update()
    dispatch.Start = 1.0

    audit = GurobiMILPAdapter._certify_integrated_dispatch_fixed_recourse(
        model,
        config=OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            phase4_integrated_seed_recourse_preflight_enabled=True,
            phase4_integrated_seed_recourse_time_limit_sec=10,
        ),
        GRB=GRB,
        integrated_warm_start_audit={"applied": True},
        dispatch_variable_maps=(("assignment", {"vehicle-a|trip-a": dispatch}),),
    )

    assert audit["dispatch_fixed_recourse_status"] == "infeasible"
    assert audit["integrated_dispatch_fixed_recourse_feasible"] is False
    assert audit["dispatch_fixed_recourse_iis_generated"] is True
    assert audit["dispatch_fixed_recourse_model_variable_count"] == 1
    assert audit["dispatch_fixed_recourse_model_constraint_count"] == 1
    assert audit["dispatch_fixed_recourse_iis_constraint_count"] >= 1
    assert audit["dispatch_fixed_recourse_iis_variable_bound_count"] >= 1
    assert len(audit["dispatch_fixed_recourse_iis_fingerprint"]) == 64
    assert audit[
        "dispatch_fixed_recourse_iis_variable_bound_semantic_sample"
    ] == ["LB:assignment[vehicle-a|trip-a]"]
    semantic_constraints = audit[
        "dispatch_fixed_recourse_iis_constraint_semantic_sample"
    ]
    assert len(semantic_constraints) == 1
    assert semantic_constraints[0]["constraint_name"] == (
        "integrated_only_conflict"
    )
    assert semantic_constraints[0]["terms"] == [
        {
            "coefficient": 1.0,
            "variable": "assignment[vehicle-a|trip-a]",
            "raw_variable_name": "dispatch_seed",
        }
    ]
    assert dispatch.LB == 0.0
    assert dispatch.UB == 1.0


def test_phase4_rejects_incomplete_bess_soc_seed_trace() -> None:
    engine = OptimizationEngine()
    problem = _phase4_seed_problem("actual-cost-incomplete-bess-seed")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        phase4_phase3_seed_enabled=True,
        phase4_phase3_seed_time_limit_sec=60,
        stage1_stage2_candidate_limit=1,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=True,
        allow_postsolve_repair=False,
    )
    seeded_problem = engine._with_verified_phase4_phase3_seed(
        problem,
        config,
    )
    assert seeded_problem.baseline_plan is not None
    baseline_metadata = dict(seeded_problem.baseline_plan.metadata or {})
    baseline_metadata.pop("bess_soc_start_kwh_by_depot_slot", None)
    incomplete_plan_without_updated_hash = replace(
        seeded_problem.baseline_plan,
        metadata=baseline_metadata,
    )
    incomplete_fingerprint = phase4_seed_plan_fingerprint(
        incomplete_plan_without_updated_hash
    )
    seed_audit = dict(
        baseline_metadata.get("phase4_phase3_seed_audit") or {}
    )
    seed_audit["seed_plan_fingerprint"] = incomplete_fingerprint
    baseline_metadata["phase4_phase3_seed_audit"] = seed_audit
    baseline_metadata[
        "phase4_seed_plan_fingerprint"
    ] = incomplete_fingerprint
    incomplete_plan = replace(
        incomplete_plan_without_updated_hash,
        metadata=baseline_metadata,
    )
    incomplete_problem = replace(
        seeded_problem,
        baseline_plan=incomplete_plan,
    )

    result = engine.solve(
        incomplete_problem,
        replace(config, phase4_phase3_seed_enabled=False),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "seed_bess_start_soc_trace_missing"


def test_phase4_rejects_seed_plan_changed_after_fingerprinting() -> None:
    engine = OptimizationEngine()
    problem = _phase4_seed_problem("actual-cost-tampered-seed")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        phase4_phase3_seed_enabled=True,
        phase4_phase3_seed_time_limit_sec=60,
        stage1_stage2_candidate_limit=1,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=True,
        allow_postsolve_repair=False,
    )
    seeded_problem = engine._with_verified_phase4_phase3_seed(
        problem,
        config,
    )
    assert seeded_problem.baseline_plan is not None
    tampered_plan = replace(
        seeded_problem.baseline_plan,
        vehicle_soc_kwh_by_vehicle_slot={},
    )

    result = engine.solve(
        replace(seeded_problem, baseline_plan=tampered_plan),
        replace(config, phase4_phase3_seed_enabled=False),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "seed_plan_fingerprint_mismatch"


def test_phase4_rejects_unverified_dispatch_baseline_as_integrated_mip_start() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-reject-unverified-seed",
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
    assert problem.baseline_plan is not None

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=False,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "baseline_is_not_verified_phase3_seed"


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
