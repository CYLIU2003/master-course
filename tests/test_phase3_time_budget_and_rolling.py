from __future__ import annotations

import pytest

from scripts import run_hourly_charging_reoptimization as hourly_runner
from src.dispatch.models import VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    OptimizationScenario,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import (
    ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
    _pv_generation_kwh_at_slot,
    _resolved_stage_time_limit_sec,
    _stage2_slot_indices,
)
from src.optimization.rolling.day_ahead_hourly import build_next_execution_state


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
            )
        },
    )


def _hourly_result(*, include_next_vehicle_soc: bool = True) -> OptimizationEngineResult:
    vehicle_soc = {0: 100.0}
    if include_next_vehicle_soc:
        vehicle_soc[1] = 90.0
    plan = AssignmentPlan(
        duties=(VehicleDuty(duty_id="duty-1", vehicle_type="BEV", legs=()),),
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
    assert state.to_dict()["state_semantics"]["vehicle_soc"] == "start_of_next_slot"


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
