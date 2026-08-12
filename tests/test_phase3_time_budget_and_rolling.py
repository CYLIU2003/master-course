from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import run_hourly_charging_reoptimization as hourly_runner
from src.dispatch.models import DutyLeg, Trip, VehicleDuty
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
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
    _pv_generation_kwh_at_slot,
    _remaining_posted_transition_fraction,
    _resolved_stage_time_limit_sec,
    _stage2_slot_indices,
    _bev_terminal_acceptance_reason,
    _bev_terminal_balance_satisfied,
    bev_terminal_numeric_acceptance_contract,
)
from src.optimization.rolling.day_ahead_hourly import build_next_execution_state


def _duties_assignment_result(*, trip_ids: tuple[str, ...]) -> OptimizationEngineResult:
    """A minimal infeasible/faked result used only for assignment-hash tests."""

    plan = AssignmentPlan(
        duties=(_duty_with_trips(trip_ids),),
        served_trip_ids=trip_ids,
        metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
    )
    return OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
    )


def _duty_with_trips(trip_ids: tuple[str, ...]) -> VehicleDuty:
    """Build a canonical VehicleDuty from synthetic trip IDs for hash tests."""

    legs = tuple(
        DutyLeg(
            trip=Trip(
                trip_id=str(trip_id),
                route_id="r-1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="09:00",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
            ),
            deadhead_from_prev_min=0,
        )
        for trip_id in trip_ids
    )
    return VehicleDuty(duty_id="duty-1", vehicle_type="BEV", legs=legs)


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="rolling",
            horizon_start="05:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
    )


def test_phase3_default_time_budget_preserves_historical_half_split() -> None:
    config = OptimizationConfig(
        time_limit_sec=1500,
        phase="phase3_two_stage",
    )

    assert _resolved_stage_time_limit_sec(config, stage=1) == 750
    assert _resolved_stage_time_limit_sec(config, stage=2) == 750


def test_explicit_stage_time_budget_avoids_unused_stage2_reservation() -> None:
    config = OptimizationConfig(
        time_limit_sec=150,
        stage1_time_limit_sec=120,
        stage2_time_limit_sec=30,
        phase="phase3_two_stage",
    )

    assert _resolved_stage_time_limit_sec(config, stage=1) == 120
    assert _resolved_stage_time_limit_sec(config, stage=2) == 30


def test_charging_only_receives_full_time_budget_by_default() -> None:
    config = OptimizationConfig(
        time_limit_sec=60,
        phase="phase1_charging_only",
    )

    assert _resolved_stage_time_limit_sec(config, stage=2) == 60


def test_remaining_day_slots_start_at_current_service_hour() -> None:
    problem = _problem()
    config = OptimizationConfig(
        rolling_current_min=8 * 60,
        rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
    )

    assert _stage2_slot_indices(problem, config, range(24)) == tuple(range(3, 24))


def test_rolling_keeps_whole_deadhead_event_that_finishes_after_boundary() -> None:
    assert _remaining_posted_transition_fraction(
        event_end_min=7 * 60 + 3,
        rolling_start_abs_min=7 * 60,
    ) == 1.0


def test_rolling_drops_deadhead_event_already_finished_at_boundary() -> None:
    assert _remaining_posted_transition_fraction(
        event_end_min=7 * 60,
        rolling_start_abs_min=7 * 60,
    ) == 0.0


def test_rolling_pv_uses_absolute_slot_not_subset_position() -> None:
    asset = DepotEnergyAsset(
        depot_id="dep-1",
        pv_enabled=True,
        pv_generation_kwh_by_slot=tuple(float(index) for index in range(24)),
    )

    assert _pv_generation_kwh_at_slot(asset, 7) == 7.0


def test_hourly_cli_contract_rejects_different_trip_input() -> None:
    problem = _problem()
    audit = {
        "scenario_id": "rolling",
        "prepared_input_id": "prep-1",
        "service_date": "2025-08-05",
        "trip_input_hash": "different-trip-input",
        "vehicle_input_hash": hourly_runner._vehicle_input_hash(problem),
    }

    with pytest.raises(ValueError, match="trip_input_hash"):
        hourly_runner._validate_day_ahead_input_contract(
            problem,
            audit,
            scenario_id="rolling",
            prepared_input_id="prep-1",
            service_date="2025-08-05",
            service_id="WEEKDAY",
        )


def test_hourly_cli_contract_rejects_changed_bev_terminal_policy() -> None:
    problem = _problem()
    problem.metadata["bev_terminal_soc_policy"] = "return_to_initial"
    audit = {
        "scenario_id": "rolling",
        "prepared_input_id": "prep-1",
        "service_date": "2025-08-05",
        "trip_input_hash": hourly_runner._trip_input_hash(problem),
        "vehicle_input_hash": hourly_runner._vehicle_input_hash(problem),
        "bev_terminal_soc_policy": "minimum_only",
    }

    with pytest.raises(ValueError, match="bev_terminal_soc_policy"):
        hourly_runner._validate_day_ahead_input_contract(
            problem,
            audit,
            scenario_id="rolling",
            prepared_input_id="prep-1",
            service_date="2025-08-05",
            service_id="WEEKDAY",
        )


def test_hourly_chain_loads_hash_verified_effective_day_ahead_pv(tmp_path) -> None:
    profile = {
        "schema_version": "effective_pv_profiles_v1",
        "forecast_by_depot": {"dep-1": [0.0, 1.25]},
    }
    profile_path = tmp_path / "effective_pv_profiles.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    audit = {
        "effective_pv_profiles_artifact": profile_path.name,
        "effective_pv_profiles_sha256": hashlib.sha256(
            profile_path.read_bytes()
        ).hexdigest(),
    }

    loaded, actual_sha256 = hourly_runner._load_day_ahead_effective_pv_profiles(
        day_ahead_output_dir=tmp_path,
        input_audit=audit,
    )

    assert loaded == profile
    assert actual_sha256 == audit["effective_pv_profiles_sha256"]


def test_hourly_chain_rejects_tampered_effective_day_ahead_pv(tmp_path) -> None:
    profile_path = tmp_path / "effective_pv_profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "effective_pv_profiles_v1",
                "forecast_by_depot": {"dep-1": [0.0, 1.25]},
            }
        ),
        encoding="utf-8",
    )
    audit = {
        "effective_pv_profiles_artifact": profile_path.name,
        "effective_pv_profiles_sha256": "not-the-file-hash",
    }

    with pytest.raises(ValueError, match="does not match"):
        hourly_runner._load_day_ahead_effective_pv_profiles(
            day_ahead_output_dir=tmp_path,
            input_audit=audit,
        )


def _hourly_result_problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="rolling-state",
            horizon_start="05:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="ev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=120.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, demand_charge_weight=1.0),
            EnergyPriceSlot(slot_index=1, demand_charge_weight=0.0),
        ),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                bess_enabled=True,
                bess_energy_kwh=100.0,
                bess_initial_soc_kwh=50.0,
                bess_soc_min_kwh=20.0,
                bess_soc_max_kwh=90.0,
                bess_terminal_soc_policy="return_to_initial",
            )
        },
    )


def _hourly_result(
    *,
    include_next_vehicle_soc: bool = True,
    active_charge_session: bool = True,
) -> OptimizationEngineResult:
    vehicle_soc = {0: 100.0}
    if include_next_vehicle_soc:
        vehicle_soc[1] = 90.0
    plan = AssignmentPlan(
        duties=(VehicleDuty(duty_id="duty-1", vehicle_type="BEV", legs=()),),
        charging_slots=(
            (
                ChargingSlot(
                    vehicle_id="ev-1",
                    slot_index=0,
                    charger_id="charger-1",
                    charge_kw=10.0,
                ),
                ChargingSlot(
                    vehicle_id="ev-1",
                    slot_index=1,
                    charger_id="charger-1",
                    charge_kw=10.0,
                ),
            )
            if active_charge_session
            else (
                ChargingSlot(
                    vehicle_id="ev-1",
                    slot_index=0,
                    charger_id="charger-1",
                    charge_kw=10.0,
                ),
            )
        ),
        grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {0: 5.0}},
        bess_soc_kwh_by_depot_slot={"dep-1": {0: 48.0}},
        vehicle_soc_kwh_by_vehicle_slot={"ev-1": vehicle_soc},
        metadata={
            "duty_vehicle_map": {"duty-1": "ev-1"},
            "rolling_start_slot_index": 0,
        },
    )
    return OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=0.0,
        plan=plan,
        feasible=True,
    )


def test_hourly_state_handoff_uses_boundary_soc_and_executed_grid_peak() -> None:
    state = build_next_execution_state(
        _hourly_result_problem(),
        _hourly_result(),
        current_min=5 * 60,
        execution_minutes=60,
        prior_on_peak_kw_by_depot={"dep-1": 12.0},
        prior_off_peak_kw_by_depot={"dep-1": 3.0},
    )

    assert state.current_min == 6 * 60
    assert state.actual_vehicle_soc_kwh == {"ev-1": 90.0}
    assert state.actual_bess_soc_kwh == {"dep-1": 48.0}
    assert state.observed_on_peak_kw_by_depot == {"dep-1": 15.0}
    assert state.observed_off_peak_kw_by_depot == {"dep-1": 3.0}
    assert state.active_charge_session_vehicle_ids == ("ev-1",)
    assert state.to_dict()["state_semantics"]["vehicle_soc"] == "start_of_next_slot"
    assert state.to_dict()["active_charge_session_vehicle_ids"] == ["ev-1"]


def test_hourly_state_handoff_does_not_invent_inactive_charge_session() -> None:
    state = build_next_execution_state(
        _hourly_result_problem(),
        _hourly_result(active_charge_session=False),
        current_min=5 * 60,
        execution_minutes=60,
    )

    assert state.active_charge_session_vehicle_ids == ()


@pytest.mark.parametrize(
    ("initial_session_active", "expected_charge_kw"),
    ((False, 75.0), (True, 82.5)),
)
def test_piecewise_charge_setup_is_not_reapplied_to_rolling_continuation(
    initial_session_active: bool,
    expected_charge_kw: float,
) -> None:
    gp = pytest.importorskip("gurobipy")
    try:
        model = gp.Model("rolling_charge_session_boundary")
    except gp.GurobiError as exc:  # pragma: no cover - license-dependent CI
        pytest.skip(f"Gurobi model creation unavailable: {exc}")
    model.Params.OutputFlag = 0
    charge_on = model.addVar(vtype=gp.GRB.BINARY, name="charge_on")
    charge_power = model.addVar(lb=0.0, ub=90.0, name="charge_power")
    soc = model.addVar(lb=0.0, ub=300.0, name="soc")
    model.addConstr(charge_on == 1)
    model.addConstr(soc == 150.0)
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="rolling-session-boundary",
            horizon_start="00:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "charging_power_model": "piecewise_soc_taper_v1",
            "charge_setup_minutes": 5,
            "charge_teardown_minutes": 5,
            "minimum_charge_session_minutes": 15,
        },
    )

    GurobiMILPAdapter()._add_piecewise_charge_power_constraints(
        model=model,
        gp=gp,
        GRB=gp.GRB,
        problem=problem,
        vehicle_id="ev-1",
        slot_indices=(6,),
        soc_var={("ev-1", 6): soc},
        charge_power_var={("ev-1", 6): charge_power},
        charge_on_var={("ev-1", 6): charge_on},
        capacity_kwh=300.0,
        charge_max_kw=90.0,
        timestep_h=1.0,
        session_start_var=None,
        name_prefix="rolling_boundary",
        initial_session_active=initial_session_active,
    )
    model.setObjective(charge_power, gp.GRB.MAXIMIZE)
    model.optimize()

    assert model.Status == gp.GRB.OPTIMAL
    assert charge_power.X == pytest.approx(expected_charge_kw, abs=1.0e-6)


def test_hourly_state_handoff_rejects_missing_next_vehicle_soc() -> None:
    with pytest.raises(ValueError, match="missing the SOC boundary"):
        build_next_execution_state(
            _hourly_result_problem(),
            _hourly_result(include_next_vehicle_soc=False),
            current_min=5 * 60,
            execution_minutes=60,
        )


def test_hourly_pv_forecast_update_replaces_full_profile_with_audit_hash() -> None:
    problem, audit = hourly_runner._apply_pv_forecast_update(
        _hourly_result_problem(),
        {"forecast_by_depot": {"dep-1": [4.0, 6.0]}},
    )

    assert problem.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot == (
        4.0,
        6.0,
    )
    assert audit["pv_generation_kwh_by_depot"] == {"dep-1": 10.0}
    assert len(audit["profile_hash"]) == 64


def test_hourly_pv_forecast_update_rejects_short_profile() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        hourly_runner._apply_pv_forecast_update(
            _hourly_result_problem(),
            {"forecast_by_depot": {"dep-1": [4.0]}},
        )


def test_hourly_pv_forecast_update_rejects_non_finite_energy() -> None:
    with pytest.raises(ValueError, match="finite, non-negative"):
        hourly_runner._apply_pv_forecast_update(
            _hourly_result_problem(),
            {"forecast_by_depot": {"dep-1": [4.0, float("nan")]}},
        )


def test_executed_day_accounting_stitches_each_slot_once() -> None:
    problem = _hourly_result_problem()
    day_ahead_plan = AssignmentPlan()
    first = SimpleNamespace(
        feasible=True,
        solver_metadata={"bev_terminal_soc_balance_satisfied": True},
        plan=AssignmentPlan(
            grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0, 1: 999.0}},
            bess_soc_kwh_by_depot_slot={"dep-1": {0: 49.0, 1: 999.0}},
            vehicle_soc_kwh_by_vehicle_slot={"ev-1": {0: 100.0, 1: 90.0}},
        ),
    )
    second = SimpleNamespace(
        feasible=True,
        solver_metadata={"bev_terminal_soc_balance_satisfied": True},
        plan=AssignmentPlan(
            grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 20.0}},
            bess_soc_kwh_by_depot_slot={"dep-1": {1: 50.0}},
            vehicle_soc_kwh_by_vehicle_slot={"ev-1": {1: 90.0, 2: 100.0}},
        ),
    )

    accounting = hourly_runner._build_executed_day_accounting(
        problem,
        day_ahead_plan,
        [(problem, first, 0, 1), (problem, second, 1, 2)],
    )

    assert accounting["eligible"] is True
    assert accounting["missing_slots"] == []
    assert accounting["duplicate_slots"] == []
    assert accounting["cost_breakdown"]["grid_import_kwh"] == pytest.approx(30.0)
    assert accounting["bev_terminal_energy_balanced"] is True
    assert accounting["bess_terminal_energy_balanced"] is True
    assert accounting["bess_terminal_soc_by_depot"]["dep-1"] == {
        "policy": "return_to_initial",
        "initial_soc_kwh": 50.0,
        "target_soc_kwh": 50.0,
        "terminal_soc_kwh": 50.0,
        "absolute_deviation_kwh": 0.0,
        "balanced": True,
    }


def test_executed_day_accounting_rejects_bess_terminal_soc_difference() -> None:
    problem = _hourly_result_problem()
    result = SimpleNamespace(
        feasible=True,
        solver_metadata={"bev_terminal_soc_balance_satisfied": True},
        plan=AssignmentPlan(
            bess_soc_kwh_by_depot_slot={"dep-1": {0: 49.0, 1: 49.0}},
            vehicle_soc_kwh_by_vehicle_slot={
                "ev-1": {0: 100.0, 1: 100.0, 2: 100.0}
            },
        ),
    )

    accounting = hourly_runner._build_executed_day_accounting(
        problem,
        AssignmentPlan(),
        [(problem, result, 0, 2)],
    )

    assert accounting["eligible"] is False
    assert accounting["bess_terminal_energy_balanced"] is False
    assert accounting["rejection_reasons"] == [
        "bess_terminal_energy_not_balanced"
    ]
    assert accounting["bess_terminal_soc_by_depot"]["dep-1"][
        "absolute_deviation_kwh"
    ] == pytest.approx(1.0)


def test_executed_day_accounting_rejects_missing_slot() -> None:
    problem = _hourly_result_problem()
    result = SimpleNamespace(
        feasible=True,
        solver_metadata={"bev_terminal_soc_balance_satisfied": True},
        plan=AssignmentPlan(
            grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0}},
            vehicle_soc_kwh_by_vehicle_slot={"ev-1": {0: 100.0, 1: 90.0}},
        ),
    )

    accounting = hourly_runner._build_executed_day_accounting(
        problem,
        AssignmentPlan(),
        [(problem, result, 0, 1)],
    )

    assert accounting["eligible"] is False
    assert accounting["reason"] == "executed_slot_coverage_incomplete"
    assert accounting["missing_slots"] == [1]
    assert accounting["cost_breakdown"] is None


def test_day_ahead_assignment_hash_is_constant_for_same_plan() -> None:
    plan = AssignmentPlan(
        duties=(_duty_with_trips(("t1", "t2")),),
        served_trip_ids=("t1", "t2"),
        metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
    )

    first = hourly_runner._day_ahead_assignment_hash(plan)
    second = hourly_runner._day_ahead_assignment_hash(plan)

    assert first == second
    assert len(first) == 64


def test_day_ahead_assignment_hash_detects_changed_duties() -> None:
    base = AssignmentPlan(
        duties=(_duty_with_trips(("t1", "t2")),),
        served_trip_ids=("t1", "t2"),
        metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
    )
    changed = AssignmentPlan(
        duties=(_duty_with_trips(("t1", "t2", "t3")),),
        served_trip_ids=("t1", "t2", "t3"),
        metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
    )

    assert hourly_runner._day_ahead_assignment_hash(base) != (
        hourly_runner._day_ahead_assignment_hash(changed)
    )


def test_assert_duties_unchanged_matches_hash_for_same_assignment() -> None:
    day_ahead_hash = hourly_runner._day_ahead_assignment_hash(
        AssignmentPlan(
            duties=(_duty_with_trips(("t1", "t2")),),
            served_trip_ids=("t1", "t2"),
            metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
        )
    )
    result = _duties_assignment_result(trip_ids=("t1", "t2"))

    audit = hourly_runner._assert_duties_unchanged(day_ahead_hash, result)

    assert audit["matched"] is True
    assert audit["fixed_assignment_check"] == "matched"


def test_assert_duties_unchanged_flags_a_re_dispatched_plan() -> None:
    day_ahead_hash = hourly_runner._day_ahead_assignment_hash(
        AssignmentPlan(
            duties=(_duty_with_trips(("t1", "t2")),),
            served_trip_ids=("t1", "t2"),
            metadata={"duty_vehicle_map": {"duty-1": "ev-1"}},
        )
    )
    result = _duties_assignment_result(trip_ids=("t1", "t2", "t3"))

    audit = hourly_runner._assert_duties_unchanged(day_ahead_hash, result)

    assert audit["matched"] is False
    assert audit["fixed_assignment_check"] == "changed"


def test_gurobi_version_snapshot_records_available_flag_when_present() -> None:
    from src import gurobi_runtime

    snapshot = hourly_runner._gurobi_version_snapshot()

    assert snapshot["backend"] == "gurobi"
    assert isinstance(snapshot["available"], bool)
    if gurobi_runtime.is_gurobi_available():
        assert snapshot["available"] is True
        assert snapshot["version"] is not None


def test_terminal_numeric_contract_defaults_chain_legacy_tolerance_first() -> None:
    contract = bev_terminal_numeric_acceptance_contract(
        {
            "bev_terminal_soc_equality_tolerance_kwh": 2.5e-6,
            "stage2_gurobi_feasibility_tol": 1.0e-9,
        },
        gurobi_feasibility_tol=None,
    )

    assert contract["scientific_tolerance_kwh"] == pytest.approx(2.5e-6)
    assert contract["numeric_comparison_margin_kwh"] == pytest.approx(1.0e-9)
    assert contract["gurobi_feasibility_tol_kwh"] == pytest.approx(1.0e-9)
    assert contract["legacy_equality_tolerance_kwh"] == pytest.approx(2.5e-6)


def test_terminal_numeric_contract_explicit_scientific_wins() -> None:
    contract = bev_terminal_numeric_acceptance_contract(
        {
            "bev_terminal_soc_scientific_tolerance_kwh": 5.0e-6,
            "bev_terminal_soc_numeric_margin_kwh": 4.0e-7,
            "stage2_gurobi_feasibility_tol": 1.0e-9,
        },
        gurobi_feasibility_tol=None,
    )

    assert contract["scientific_tolerance_kwh"] == pytest.approx(5.0e-6)
    assert contract["numeric_comparison_margin_kwh"] == pytest.approx(4.0e-7)


def test_terminal_numeric_contract_rejects_negative_overrides() -> None:
    contract = bev_terminal_numeric_acceptance_contract(
        {
            "bev_terminal_soc_scientific_tolerance_kwh": -0.1,
            "bev_terminal_soc_numeric_margin_kwh": "not-a-number",
        },
        gurobi_feasibility_tol=1.0e-7,
    )

    assert contract["scientific_tolerance_kwh"] == pytest.approx(1.0e-6)
    assert contract["numeric_comparison_margin_kwh"] == pytest.approx(1.0e-7)
    assert contract["gurobi_feasibility_tol_kwh"] == pytest.approx(1.0e-7)


def test_terminal_acceptance_reason_accepts_numeric_margin_at_boundary() -> None:
    reason = _bev_terminal_acceptance_reason(
        target_by_vehicle={"ev-1": 300.0},
        shortfall_by_vehicle={"ev-1": 2.0e-7},
        surplus_by_vehicle={"ev-1": 0.0},
        scientific_tolerance_kwh=1.0e-7,
        numeric_margin_kwh=1.0e-6,
    )

    assert reason["category"] == "within_numeric_margin_of_scientific_tolerance"
    assert reason["judgement"] == "accepted"


@pytest.mark.parametrize(
    ("shortfall_kwh", "surplus_kwh", "expected_judgement"),
    [
        (1.0e-6, 0.0, "accepted"),
        (1.000001e-6, 0.0, "accepted"),
        (0.0, 1.000001e-6, "accepted"),
        (1.0011e-6, 0.0, "rejected"),
    ],
)
def test_terminal_acceptance_reason_respects_scientific_boundary(
    shortfall_kwh: float,
    surplus_kwh: float,
    expected_judgement: str,
) -> None:
    reason = _bev_terminal_acceptance_reason(
        target_by_vehicle={"ev-1": 300.0},
        shortfall_by_vehicle={"ev-1": shortfall_kwh},
        surplus_by_vehicle={"ev-1": surplus_kwh},
        scientific_tolerance_kwh=1.0e-6,
        numeric_margin_kwh=1.0e-9,
    )

    assert reason["judgement"] == expected_judgement


def test_terminal_balance_gate_uses_the_same_science_plus_margin_limit() -> None:
    common = {
        "target_by_vehicle": {"ev-1": 300.0},
        "surplus_by_vehicle": {"ev-1": 0.0},
        "scientific_tolerance_kwh": 1.0e-6,
        "numeric_margin_kwh": 1.0e-9,
    }

    assert _bev_terminal_balance_satisfied(
        **common,
        shortfall_by_vehicle={"ev-1": 1.000001e-6},
    )
    assert not _bev_terminal_balance_satisfied(
        **common,
        shortfall_by_vehicle={"ev-1": 1.0011e-6},
    )


def test_charging_schedule_serialization_includes_energy_source() -> None:
    from src.optimization.common.problem import ChargingSlot
    from src.optimization.common.result import ResultSerializer

    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="ev-1",
                slot_index=1,
                charger_id="chgr-1",
                energy_source="grid",
                charge_kw=50.0,
                discharge_kw=0.0,
            ),
        ),
    )

    serialized = ResultSerializer.serialize_plan(plan)

    assert serialized["charging_schedule"][0]["energy_source"] == "grid"


def test_executed_charging_schedule_preserves_each_energy_source(tmp_path) -> None:
    from src.optimization.common.problem import ChargingSlot

    problem = _hourly_result_problem()
    result = SimpleNamespace(
        plan=AssignmentPlan(
            charging_slots=(
                ChargingSlot(
                    vehicle_id="ev-1",
                    slot_index=0,
                    charger_id="chgr-1",
                    energy_source="pv",
                    charge_kw=10.0,
                ),
                ChargingSlot(
                    vehicle_id="ev-1",
                    slot_index=0,
                    charger_id="chgr-1",
                    energy_source="grid",
                    charge_kw=20.0,
                ),
            )
        ),
        solver_metadata={
            "vehicle_source_provenance_exact": False,
            "vehicle_source_allocation_policy": "proportional_by_depot_timestep",
        },
    )
    path = tmp_path / "charging_schedule.csv"

    hourly_runner._write_executed_charging_schedule(
        path,
        problem=problem,
        executed_segments=[(problem, result, 0, 1)],
    )

    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3
    assert "energy_source" in rows[0]
    assert any(",grid," in row for row in rows[1:])
    assert any(",pv," in row for row in rows[1:])


def test_hourly_chart_uses_executed_prefix_not_remaining_objective(tmp_path) -> None:
    problem = _hourly_result_problem()
    result = SimpleNamespace(
        plan=AssignmentPlan(
            grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0, 1: 999.0}},
            vehicle_soc_kwh_by_vehicle_slot={"ev-1": {0: 100.0, 1: 90.0}},
            bess_soc_kwh_by_depot_slot={"dep-1": {0: 48.0}},
        ),
        solver_metadata={},
    )
    path = tmp_path / "hourly_energy_flow_chart.csv"

    hourly_runner._write_hourly_chart_csv(
        path,
        problem=problem,
        executed_segments=[(problem, result, 0, 1)],
    )

    values = path.read_text(encoding="utf-8")
    assert "999" not in values
    assert "financial_at_step_jpy" not in values
    assert "bev_soc_min_kwh" in values.splitlines()[0]


def test_day_ahead_rolling_start_contract_rejects_unaccepted_result(tmp_path) -> None:
    from scripts.run_research_phase3_frontend_weather import (
        _validate_day_ahead_rolling_start_contract,
    )

    (tmp_path / "solver_result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "input_audit.json").write_text("{}", encoding="utf-8")
    (tmp_path / "summary.json").write_text(
        '{"feasible": true, "research_run_accepted": false, '
        '"research_feasibility_eligible": true, "phase": "phase3_two_stage"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="day_ahead_research_acceptance_failed"):
        _validate_day_ahead_rolling_start_contract(tmp_path)
