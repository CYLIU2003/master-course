from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from bff.services.optimization_run.rolling_chain import (
    DAY_AHEAD_EXPLORATORY_PROFILE,
    DEFAULT_FRONTEND_RUN_PROFILE,
    _calendar_audit,
    execute_frontend_rolling_chain,
    frontend_rolling_is_required,
    persist_frontend_day_ahead_rolling_contract,
)
from scripts import run_hourly_charging_reoptimization as hourly_runner
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemVehicle,
)


def _problem(*, service_date: str = "2025-08-05") -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            horizon_start="00:00",
            horizon_end="02:00",
            horizon_duration_min=120,
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=0.8,
                battery_capacity_kwh=100.0,
                reserve_soc=0.2,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=18.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=22.0),
        ),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(1.0, 2.0),
            )
        },
        metadata={
            "service_date": service_date,
            "bev_terminal_soc_policy": "return_to_initial",
        },
    )


def test_normal_frontend_profile_forces_hourly_rolling() -> None:
    assert frontend_rolling_is_required(DEFAULT_FRONTEND_RUN_PROFILE) is True
    assert frontend_rolling_is_required(DAY_AHEAD_EXPLORATORY_PROFILE) is False


def test_frontend_day_ahead_contract_pins_exact_problem_and_result(
    tmp_path: Path,
) -> None:
    problem = _problem()
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text('{"prepared_input_id":"prepared-1"}', encoding="utf-8")
    (tmp_path / "canonical_solver_result.json").write_text(
        '{"feasible":true}', encoding="utf-8"
    )
    (tmp_path / "summary.json").write_text(
        '{"scenario_id":"scenario-1"}', encoding="utf-8"
    )

    audit = persist_frontend_day_ahead_rolling_contract(
        run_dir=tmp_path,
        scenario={"simulation_config": {"service_date": "2025-08-05"}},
        problem=problem,
        prepared_input_path=prepared_path,
        scenario_id="scenario-1",
        prepared_input_id="prepared-1",
        service_id="WEEKDAY",
        git_state={
            "git_sha": "abc123",
            "git_dirty": False,
            "git_state_available": True,
        },
    )

    assert audit["scenario_id"] == "scenario-1"
    assert audit["prepared_input_id"] == "prepared-1"
    assert audit["calendar_validation_status"] == "OK"
    assert audit["bev_terminal_soc_policy"] == "return_to_initial"
    assert len(audit["trip_input_hash"]) == 64
    assert len(audit["vehicle_input_hash"]) == 64
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_state"] == "complete"
    assert "canonical_solver_result.json" in manifest["artifacts"]
    assert "effective_pv_profiles.json" in manifest["artifacts"]


def test_weekday_on_sunday_requires_exact_counterfactual_waiver() -> None:
    rejected = _calendar_audit(
        service_date="2025-08-10",
        service_id="WEEKDAY",
        problem_metadata={},
    )
    accepted = _calendar_audit(
        service_date="2025-08-10",
        service_id="WEEKDAY",
        problem_metadata={
            "weather_comparison_contract": {
                "comparison_type": "fixed_weekday_timetable_pv_counterfactual",
                "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
            }
        },
    )

    assert rejected["calendar_validation_status"] == "ERROR"
    assert accepted["calendar_validation_status"] == "WAIVED_BY_EXPERIMENT_POLICY"
    assert accepted["waiver"] == {
        "scope": "weekday_timetable_on_sunday_for_pv_only_counterfactual",
        "reason": (
            "Fixed weekday timetable; only PV profile differs. "
            "Not actual Sunday operation."
        ),
    }


def test_dirty_provenance_blocks_acceptance_without_faking_execution_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "input_audit.json").write_text(
        '{"git_dirty":true}', encoding="utf-8"
    )
    chain_checks = {
        "full_energy_horizon_requested": True,
        "all_steps_feasible": True,
        "expected_step_count_observed": True,
        "executed_day_accounting_eligible": True,
        "day_ahead_git_clean": False,
        "rolling_runner_git_clean": False,
        "day_ahead_and_rolling_git_sha_match": True,
        "day_ahead_assignment_hash_constant": True,
        "gurobi_available": True,
        "no_chain_runtime_error": True,
    }

    def fake_run(request) -> int:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "rolling_chain_summary.json").write_text(
            json.dumps(
                {
                    "chain_accepted": False,
                    "acceptance_checks": chain_checks,
                    "rejection_reasons": [
                        "day_ahead_git_clean",
                        "rolling_runner_git_clean",
                    ],
                }
            ),
            encoding="utf-8",
        )
        return 2

    with mock.patch.object(hourly_runner, "run_rolling_chain", side_effect=fake_run):
        result = execute_frontend_rolling_chain(
            run_dir=tmp_path,
            problem=_problem(),
            scenario_id="scenario-1",
            prepared_input_id="prepared-1",
            service_id="WEEKDAY",
            depot_id="dep-1",
            execution_minutes=60,
            time_limit_sec=1,
            mip_gap=0.1,
            random_seed=42,
            gurobi_threads=1,
        )

    assert result.status == "executed_not_accepted"
    assert result.chain_accepted is False
    assert result.technical_failure_reasons == ()


def test_infeasible_rolling_step_is_a_technical_job_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "input_audit.json").write_text(
        '{"git_dirty":false}', encoding="utf-8"
    )
    checks = {
        "full_energy_horizon_requested": True,
        "all_steps_feasible": False,
        "expected_step_count_observed": False,
        "executed_day_accounting_eligible": False,
        "day_ahead_git_clean": True,
        "rolling_runner_git_clean": True,
        "day_ahead_and_rolling_git_sha_match": True,
        "day_ahead_assignment_hash_constant": True,
        "gurobi_available": True,
        "no_chain_runtime_error": True,
    }

    def fake_run(request) -> int:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "rolling_chain_summary.json").write_text(
            json.dumps(
                {
                    "chain_accepted": False,
                    "acceptance_checks": checks,
                    "rejection_reasons": ["step_infeasible"],
                }
            ),
            encoding="utf-8",
        )
        return 2

    with mock.patch.object(hourly_runner, "run_rolling_chain", side_effect=fake_run):
        result = execute_frontend_rolling_chain(
            run_dir=tmp_path,
            problem=_problem(),
            scenario_id="scenario-1",
            prepared_input_id="prepared-1",
            service_id="WEEKDAY",
            depot_id="dep-1",
            execution_minutes=60,
            time_limit_sec=1,
            mip_gap=0.1,
            random_seed=42,
            gurobi_threads=1,
        )

    assert set(result.technical_failure_reasons) == {
        "all_steps_feasible",
        "expected_step_count_observed",
        "executed_day_accounting_eligible",
    }
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_state"] == "rolling_execution_failed"
