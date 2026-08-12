from __future__ import annotations

from dataclasses import replace

import pytest

from bff.services.optimization_run.thesis_ablation import (
    CSV_COLUMNS,
    ablation_candidate_csv_rows,
    build_day_ahead_ablation_candidates,
)
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    DutyLeg,
    Trip,
    VehicleDuty,
    VehicleProfile,
)
from src.optimization import (
    AssignmentPlan,
    ChargerDefinition,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.baselines.immediate_charge import (
    apply_arrival_immediate_charging,
    build_m0_rule_baseline,
    build_m2_simple_charge_baseline,
)


def _single_bev_problem(*, with_charger: bool = True):
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="round-trip",
                route_id="route",
                origin="DEPOT",
                destination="DEPOT",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="DEPOT",
                destination_stop_id="DEPOT",
                operator_id="tokyu",
            )
        ],
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
    chargers = (
        (
            ChargerDefinition(
                charger_id="charger-1",
                depot_id="DEPOT",
                power_kw=50.0,
            ),
        )
        if with_charger
        else ()
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="immediate-charge",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 1},
        chargers=chargers,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=index,
                grid_buy_yen_per_kwh=30.0,
            )
            for index in range(6)
        ),
        scenario_vehicles=(
            {
                "id": "BEV_001",
                "type": "BEV",
                "depotId": "DEPOT",
                "batteryKwh": 100.0,
                "energyConsumption": 1.0,
                "chargePowerKw": 50.0,
                "initialSoc": 0.8,
                "minSoc": 0.2,
                "enabled": True,
            },
        ),
        canonical_depot_id="DEPOT",
        timestep_min=30,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="10:00",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        bev_terminal_soc_policy="return_to_initial",
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        charging_power_model="constant_power_v0",
        enable_driver_cost=False,
        enable_vehicle_cost=False,
        enable_other_cost=False,
        service_coverage_mode="strict",
    )
    assert problem.baseline_plan is not None
    depot_id, asset = next(iter(problem.depot_energy_assets.items()))
    problem = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                pv_enabled=True,
                pv_generation_kwh_by_slot=(25.0,) + (0.0,) * 47,
                available_pv_surplus_kwh_by_slot=(25.0,) + (0.0,) * 47,
            )
        },
    )
    return replace(problem, baseline_plan=problem.baseline_plan)


def _fragmented_depot_reset_problem():
    first = Trip(
        trip_id="outbound",
        route_id="route",
        origin="DEPOT",
        destination="A",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="DEPOT",
        destination_stop_id="A",
        operator_id="tokyu",
    )
    second = Trip(
        trip_id="inbound",
        route_id="route",
        origin="B",
        destination="DEPOT",
        departure_time="10:00",
        arrival_time="10:30",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="B",
        destination_stop_id="DEPOT",
        operator_id="tokyu",
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[first, second],
        turnaround_rules={},
        deadhead_rules={
            ("A", "DEPOT"): DeadheadRule("A", "DEPOT", 10),
            ("DEPOT", "B"): DeadheadRule("DEPOT", "B", 10),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        default_turnaround_min=10,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="fragmented-immediate-charge",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("charger-1", "DEPOT", 50.0),),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=30.0)
            for index in range(10)
        ),
        scenario_vehicles=(
            {
                "id": "BEV_001",
                "type": "BEV",
                "depotId": "DEPOT",
                "batteryKwh": 100.0,
                "energyConsumption": 1.0,
                "chargePowerKw": 50.0,
                "initialSoc": 0.8,
                "minSoc": 0.2,
                "enabled": True,
            },
        ),
        canonical_depot_id="DEPOT",
        timestep_min=30,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="12:00",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        bev_terminal_soc_policy="return_to_initial",
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        charging_power_model="constant_power_v0",
        enable_driver_cost=False,
        enable_vehicle_cost=False,
        enable_other_cost=False,
        service_coverage_mode="strict",
    )
    vehicle_id = str(problem.vehicles[0].vehicle_id)
    first_duty = VehicleDuty(
        duty_id="fragment-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=first),),
    )
    second_duty = VehicleDuty(
        duty_id="fragment-2",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=second),),
    )
    baseline = AssignmentPlan(
        duties=(first_duty, second_duty),
        served_trip_ids=("outbound", "inbound"),
        metadata={
            "duty_vehicle_map": {
                "fragment-1": vehicle_id,
                "fragment-2": vehicle_id,
            },
            "optimization_structure": "assignment_only",
        },
    )
    return replace(problem, baseline_plan=baseline)


def test_arrival_immediate_rule_uses_pv_before_grid_and_is_physically_valid() -> None:
    problem = _single_bev_problem()

    result = apply_arrival_immediate_charging(
        problem,
        problem.baseline_plan,
        method_id="M0",
    )

    assert result.feasible is True
    assert result.errors == ()
    assert result.audit["pv_to_bus_kwh"] == pytest.approx(10.0 / 0.95)
    assert result.audit["grid_to_bus_kwh"] == pytest.approx(0.0)
    assert result.plan.metadata["thesis_ablation_method_id"] == "M0"
    assert result.plan.metadata["charging_dispatch_optimized"] is False
    assert result.plan.metadata["source_provenance_exact"] is True


def test_arrival_immediate_rule_uses_available_surplus_not_gross_pv() -> None:
    problem = _single_bev_problem()
    depot_id, asset = next(iter(problem.depot_energy_assets.items()))
    available = (5.0,) + (0.0,) * (
        len(asset.available_pv_surplus_kwh_by_slot) - 1
    )
    problem = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                pv_generation_kwh_by_slot=(25.0,) + (0.0,) * (
                    len(asset.pv_generation_kwh_by_slot) - 1
                ),
                available_pv_surplus_kwh_by_slot=available,
                pv_input_semantics="available_surplus_after_depot_load",
            )
        },
    )

    result = build_m0_rule_baseline(problem)

    assert result.feasible is True
    assert result.audit["pv_to_bus_kwh"] == pytest.approx(5.0)
    assert result.audit["grid_to_bus_kwh"] == pytest.approx(10.0 / 0.95 - 5.0)
    assert result.audit["pv_input_semantics"] == (
        "available_surplus_after_depot_load"
    )


def test_fragmented_assignment_materializes_reset_but_fails_closed_on_checker() -> None:
    problem = _fragmented_depot_reset_problem()

    result = build_m0_rule_baseline(problem)

    assert result.feasible is False
    assert any("[SOC_FRAGMENT]" in error for error in result.errors)
    assert any("[FRAGMENT]" in error for error in result.errors)
    assert any(slot.slot_index == 4 for slot in result.plan.charging_slots)
    assert result.plan.metadata["fragment_transition_policy"] == (
        "direct_when_feasible_else_explicit_home_depot_reset"
    )


def test_m0_and_m2_wrappers_enforce_dispatch_provenance() -> None:
    problem = _single_bev_problem()

    m0 = build_m0_rule_baseline(problem)
    with pytest.raises(ValueError, match="M2 requires an assignment"):
        build_m2_simple_charge_baseline(problem, problem.baseline_plan)
    optimized_assignment = replace(
        problem.baseline_plan,
        metadata={
            **dict(problem.baseline_plan.metadata),
            "optimization_structure": "assignment_only",
        },
    )
    m2 = build_m2_simple_charge_baseline(problem, optimized_assignment)

    assert m0.feasible is True
    assert m0.plan.metadata["thesis_ablation_method_id"] == "M0"
    assert m2.feasible is True
    assert m2.plan.metadata["thesis_ablation_method_id"] == "M2"


def test_arrival_immediate_rule_fails_closed_without_required_charger() -> None:
    problem = _single_bev_problem(with_charger=False)

    result = apply_arrival_immediate_charging(
        problem,
        problem.baseline_plan,
        method_id="M2",
    )

    assert result.feasible is False
    assert result.audit["charging_slot_row_count"] == 0
    assert any("terminal SOC below target" in error for error in result.errors)
    assert result.plan.metadata["thesis_ablation_method_id"] == "M2"


def test_day_ahead_ablation_artifact_never_pretends_m1_was_solved() -> None:
    problem = _single_bev_problem()
    optimized_assignment = replace(
        problem.baseline_plan,
        metadata={
            **dict(problem.baseline_plan.metadata),
            "optimization_structure": "two_stage",
        },
    )

    payload = build_day_ahead_ablation_candidates(
        problem=problem,
        optimized_plan=optimized_assignment,
        optimized_solver_status="OPTIMAL",
    )
    rows = ablation_candidate_csv_rows(payload)
    by_method = {row["method_id"]: row for row in payload["methods"]}

    assert payload["status"] == "PARTIAL_CANDIDATE_SET"
    assert payload["primary_optimization_structure"] == "two_stage"
    assert payload["available_method_ids"] == ["M0", "M2"]
    assert payload["missing_method_ids"] == ["M1", "M3"]
    assert payload["complete_four_method_comparison_available"] is False
    assert payload["research_conclusion_eligible"] is False
    assert by_method["M1"]["construction_status"] == (
        "SEPARATE_PHASE1_RUN_REQUIRED"
    )
    assert by_method["M1"]["candidate_available"] is False
    assert by_method["M2"]["day_ahead_comparison_eligible"] is True
    assert by_method["M3"]["construction_status"] == (
        "SEPARATE_PHASE4_INTEGRATED_RUN_REQUIRED"
    )
    assert len(payload["payload_sha256"]) == 64
    assert [row["method_id"] for row in rows] == ["M0", "M1", "M2", "M3"]
    assert tuple(rows[0]) == CSV_COLUMNS


def test_ablation_primary_method_labels_follow_optimization_structure() -> None:
    problem = _single_bev_problem()
    integrated_plan = replace(
        problem.baseline_plan,
        metadata={
            **dict(problem.baseline_plan.metadata),
            "optimization_structure": "integrated",
        },
    )
    phase1_plan = replace(
        problem.baseline_plan,
        metadata={
            **dict(problem.baseline_plan.metadata),
            "optimization_structure": "charging_only",
        },
    )

    integrated = build_day_ahead_ablation_candidates(
        problem=problem,
        optimized_plan=integrated_plan,
        optimized_solver_status="OPTIMAL",
    )
    phase1 = build_day_ahead_ablation_candidates(
        problem=problem,
        optimized_plan=phase1_plan,
        optimized_solver_status="OPTIMAL",
    )
    integrated_methods = {
        row["method_id"]: row for row in integrated["methods"]
    }
    phase1_methods = {row["method_id"]: row for row in phase1["methods"]}

    assert integrated_methods["M3"]["candidate_available"] is True
    assert integrated_methods["M3"]["construction_status"] == (
        "PRIMARY_PHASE4_DAY_AHEAD_RESULT"
    )
    assert integrated_methods["M1"]["candidate_available"] is False
    assert phase1_methods["M1"]["candidate_available"] is True
    assert phase1_methods["M1"]["construction_status"] == (
        "PRIMARY_PHASE1_DAY_AHEAD_RESULT"
    )
    assert phase1_methods["M2"]["candidate_available"] is False
    assert phase1_methods["M3"]["candidate_available"] is False


def test_ablation_reconciles_structure_from_engine_metadata() -> None:
    problem = _single_bev_problem()
    plan_without_structure = replace(
        problem.baseline_plan,
        metadata={
            key: value
            for key, value in dict(problem.baseline_plan.metadata).items()
            if key != "optimization_structure"
        },
    )

    payload = build_day_ahead_ablation_candidates(
        problem=problem,
        optimized_plan=plan_without_structure,
        optimized_solver_status="OPTIMAL",
        primary_optimization_structure="integrated",
    )

    assert payload["primary_optimization_structure"] == "integrated"
    assert payload["primary_optimization_structure_source"] == (
        "engine_result.solver_metadata"
    )
    assert payload["available_method_ids"] == ["M0", "M2", "M3"]

    with pytest.raises(ValueError, match="optimization_structure mismatch"):
        build_day_ahead_ablation_candidates(
            problem=problem,
            optimized_plan=replace(
                plan_without_structure,
                metadata={"optimization_structure": "two_stage"},
            ),
            optimized_solver_status="OPTIMAL",
            primary_optimization_structure="integrated",
        )
