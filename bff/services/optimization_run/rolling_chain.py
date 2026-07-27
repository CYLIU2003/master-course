"""Production orchestration for frontend day-ahead plus hourly rolling runs.

This module deliberately keeps the BFF boundary small.  It persists the exact
canonical problem/result contract produced by the frontend day-ahead solve and
then invokes the same in-process rolling service used by the strict research
CLI.  It never rebuilds timetable rows, duties, or vehicle assignments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.optimization.common.initial_soc_policy import (
    InitialSocPolicy,
    initial_soc_input_metadata,
)
from src.optimization.common.input_fingerprints import (
    INPUT_FINGERPRINT_SCHEMA,
    canonical_trip_input_hash,
    canonical_vehicle_input_hash,
)
from src.optimization.rolling.acceptance import rolling_chain_acceptance_audit


DEFAULT_FRONTEND_RUN_PROFILE = "day_ahead_and_hourly_rolling"
DAY_AHEAD_EXPLORATORY_PROFILE = "day_ahead_exploratory"
SUPPORTED_FRONTEND_RUN_PROFILES = frozenset(
    {DEFAULT_FRONTEND_RUN_PROFILE, DAY_AHEAD_EXPLORATORY_PROFILE}
)


class RollingChainExecutionError(RuntimeError):
    """A requested hourly chain failed to execute its physical control steps."""


@dataclass(frozen=True)
class FrontendRollingResult:
    """Persisted outcome of the production frontend rolling orchestration."""

    exit_code: int
    status: str
    chain_summary_path: str | None
    chain_accepted: bool
    acceptance_audit: Mapping[str, Any]
    technical_failure_reasons: tuple[str, ...]


def normalize_frontend_run_profile(value: Any) -> str:
    profile = str(value or DEFAULT_FRONTEND_RUN_PROFILE).strip()
    if profile not in SUPPORTED_FRONTEND_RUN_PROFILES:
        allowed = ", ".join(sorted(SUPPORTED_FRONTEND_RUN_PROFILES))
        raise ValueError(f"Unsupported run_profile {profile!r}; expected one of {allowed}")
    return profile


def frontend_rolling_is_required(run_profile: Any) -> bool:
    """Return the server-authoritative rolling policy for a frontend run."""

    return normalize_frontend_run_profile(run_profile) != DAY_AHEAD_EXPLORATORY_PROFILE


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _effective_pv_profiles(problem: Any) -> dict[str, Any]:
    forecast_by_depot = {
        str(depot_id): [
            float(value or 0.0)
            for value in tuple(asset.pv_generation_kwh_by_slot or ())
        ]
        for depot_id, asset in sorted(
            dict(problem.depot_energy_assets or {}).items()
        )
    }
    return {
        "schema_version": "effective_pv_profiles_v1",
        "semantics": (
            "Exact full-horizon kWh PV profiles supplied to the frontend "
            "day-ahead canonical problem. The production rolling chain must "
            "use this identical input."
        ),
        "forecast_by_depot": forecast_by_depot,
        "forecast_by_depot_hash": _canonical_hash(forecast_by_depot),
    }


def _calendar_audit(
    *,
    service_date: str,
    service_id: str,
    problem_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = date.fromisoformat(str(service_date)[:10])
    normalized_service_id = str(service_id or "").strip().upper()
    weekday = parsed.weekday()
    matches = (
        weekday <= 4
        if normalized_service_id == "WEEKDAY"
        else weekday == 5
        if normalized_service_id in {"SAT", "SATURDAY"}
        else weekday == 6
        if normalized_service_id in {"SUN_HOL", "SUN_HOLIDAY", "SUNDAY", "HOLIDAY"}
        else False
    )
    weather_contract = dict(
        problem_metadata.get("weather_comparison_contract") or {}
    )
    waiver_declared = bool(
        normalized_service_id == "WEEKDAY"
        and weekday == 6
        and weather_contract.get("comparison_type")
        == "fixed_weekday_timetable_pv_counterfactual"
        and weather_contract.get("calendar_policy")
        == "fixed_weekday_timetable_pv_counterfactual"
    )
    if matches:
        return {
            "calendar_policy": "service_date_matches_timetable",
            "calendar_validation_status": "OK",
            "service_date": parsed.isoformat(),
            "service_id": normalized_service_id,
        }
    if waiver_declared:
        return {
            "comparison_type": "fixed_weekday_timetable_pv_counterfactual",
            "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
            "calendar_validation_status": "WAIVED_BY_EXPERIMENT_POLICY",
            "waiver": {
                "scope": "weekday_timetable_on_sunday_for_pv_only_counterfactual",
                "reason": (
                    "Fixed weekday timetable; only PV profile differs. "
                    "Not actual Sunday operation."
                ),
            },
            "service_date": parsed.isoformat(),
            "service_id": normalized_service_id,
        }
    return {
        "calendar_policy": "service_date_must_match_timetable",
        "calendar_validation_status": "ERROR",
        "service_date": parsed.isoformat(),
        "service_id": normalized_service_id,
        "reason": "service_date_and_service_id_mismatch_without_declared_waiver",
    }


def _research_manifest(
    *,
    run_dir: Path,
    input_audit: Mapping[str, Any],
    run_state: str,
) -> dict[str, Any]:
    artifact_names = (
        "effective_scenario.json",
        "effective_pv_profiles.json",
        "input_audit.json",
        "canonical_solver_result.json",
        "summary.json",
        "rolling_hourly_chain/rolling_chain_summary.json",
        "rolling_hourly_chain/executed_day_accounting.json",
        "rolling_hourly_chain/day_ahead_vs_rolling_summary.json",
        "rolling_hourly_chain/hourly_energy_flow_chart.csv",
        "rolling_hourly_chain/charging_schedule.csv",
    )
    artifacts = {
        name: {
            "sha256": _file_sha256(run_dir / name),
            "size_bytes": (run_dir / name).stat().st_size,
        }
        for name in artifact_names
        if (run_dir / name).is_file()
    }
    return {
        "schema": "research_run_manifest_v1",
        "run_state": run_state,
        "declared_controls": {
            key: input_audit.get(key)
            for key in (
                "scenario_id",
                "prepared_input_id",
                "prepared_input_sha256",
                "service_date",
                "service_id",
                "timestep_min",
                "price_slot_count",
                "bev_terminal_soc_policy",
                "charger_configuration_hash",
                "depot_energy_assets_fixed_hash",
                "effective_pv_profiles_sha256",
                "vehicle_input_hash",
                "trip_input_hash",
                "git_sha",
                "git_dirty",
                "calendar_policy",
                "calendar_validation_status",
            )
        },
        "artifacts": artifacts,
    }


def persist_frontend_day_ahead_rolling_contract(
    *,
    run_dir: Path,
    scenario: Mapping[str, Any],
    problem: Any,
    prepared_input_path: Path,
    scenario_id: str,
    prepared_input_id: str,
    service_id: str,
    git_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the exact day-ahead input contract consumed by rolling.

    The caller must already have written ``canonical_solver_result.json`` and
    ``summary.json``.  Missing model semantics are rejected instead of inferred.
    """

    from scripts.run_hourly_charging_reoptimization import (
        _charger_configuration_hash,
        _depot_energy_assets_fixed_hash,
    )

    run_dir = Path(run_dir)
    result_path = run_dir / "canonical_solver_result.json"
    summary_path = run_dir / "summary.json"
    if not result_path.is_file() or not summary_path.is_file():
        raise ValueError(
            "Day-ahead rolling contract requires canonical_solver_result.json "
            "and summary.json from the completed frontend solve"
        )
    if not prepared_input_path.is_file():
        raise ValueError(f"Prepared input artifact is missing: {prepared_input_path}")

    metadata = dict(getattr(problem, "metadata", {}) or {})
    service_date = str(metadata.get("service_date") or "")[:10]
    if not service_date:
        raise ValueError("Canonical problem is missing service_date")
    terminal_policy = str(metadata.get("bev_terminal_soc_policy") or "").strip()
    if not terminal_policy:
        raise ValueError(
            "Canonical problem is missing bev_terminal_soc_policy; rolling "
            "must not infer the day-ahead terminal SOC meaning"
        )

    effective_scenario = dict(scenario)
    effective_scenario_path = run_dir / "effective_scenario.json"
    _write_json(effective_scenario_path, effective_scenario)
    effective_pv_path = run_dir / "effective_pv_profiles.json"
    _write_json(effective_pv_path, _effective_pv_profiles(problem))

    initial_soc = initial_soc_input_metadata(
        problem,
        policy=InitialSocPolicy.ACTUAL_VEHICLE_INVENTORY,
    )
    depot_energy_assets = {
        str(depot_id): {
            "pv_generation_hash": _canonical_hash(
                [
                    float(value or 0.0)
                    for value in tuple(asset.pv_generation_kwh_by_slot or ())
                ]
            )
        }
        for depot_id, asset in sorted(
            dict(problem.depot_energy_assets or {}).items()
        )
    }
    calendar_audit = _calendar_audit(
        service_date=service_date,
        service_id=service_id,
        problem_metadata=metadata,
    )
    input_audit = {
        "input_fingerprint_schema": INPUT_FINGERPRINT_SCHEMA,
        "effective_scenario_artifact": effective_scenario_path.name,
        "effective_scenario_sha256": _canonical_hash(effective_scenario),
        "effective_pv_profiles_artifact": effective_pv_path.name,
        "effective_pv_profiles_sha256": _file_sha256(effective_pv_path),
        "scenario_id": str(scenario_id),
        "prepared_input_id": str(prepared_input_id),
        "prepared_input_sha256": _file_sha256(prepared_input_path),
        "service_date": service_date,
        "service_id": str(service_id),
        "timestep_min": int(problem.scenario.timestep_min),
        "price_slot_count": len(problem.price_slots),
        "trip_input_hash": canonical_trip_input_hash(problem),
        "vehicle_input_hash": canonical_vehicle_input_hash(problem),
        "initial_soc_policy": initial_soc["initial_soc_policy"],
        "initial_soc_source": initial_soc["initial_soc_source"],
        "initial_soc_input_hash": initial_soc["initial_soc_input_hash"],
        "initial_soc_by_vehicle": initial_soc["initial_soc_by_vehicle"],
        "bev_terminal_soc_policy": terminal_policy,
        "terminal_soc_policy": {
            "bev_terminal_soc_policy": terminal_policy,
        },
        "charger_configuration_hash": _charger_configuration_hash(problem),
        "depot_energy_assets": depot_energy_assets,
        "depot_energy_assets_fixed_hash": _depot_energy_assets_fixed_hash(problem),
        "calendar_audit": calendar_audit,
        "calendar_policy": calendar_audit["calendar_policy"],
        "calendar_validation_status": calendar_audit[
            "calendar_validation_status"
        ],
        "git_sha": git_state.get("git_sha"),
        "git_dirty": git_state.get("git_dirty"),
        "git_state_available": bool(git_state.get("git_state_available", False)),
        "git_state_error": git_state.get("git_state_error"),
        "artifact_semantics": (
            "Exact in-memory canonical problem and result produced by the "
            "frontend day-ahead solve; no timetable or assignment rebuild."
        ),
    }
    _write_json(run_dir / "input_audit.json", input_audit)
    _write_json(
        run_dir / "manifest.json",
        _research_manifest(
            run_dir=run_dir,
            input_audit=input_audit,
            run_state="complete",
        ),
    )
    return input_audit


def refresh_frontend_rolling_manifest(
    *, run_dir: Path, run_state: str
) -> None:
    input_audit_path = Path(run_dir) / "input_audit.json"
    if not input_audit_path.is_file():
        raise ValueError("Cannot refresh rolling manifest without input_audit.json")
    input_audit = json.loads(input_audit_path.read_text(encoding="utf-8"))
    _write_json(
        Path(run_dir) / "manifest.json",
        _research_manifest(
            run_dir=Path(run_dir),
            input_audit=input_audit,
            run_state=run_state,
        ),
    )


def execute_frontend_rolling_chain(
    *,
    run_dir: Path,
    problem: Any,
    scenario_id: str,
    prepared_input_id: str,
    service_id: str,
    depot_id: str,
    execution_minutes: int,
    time_limit_sec: int,
    mip_gap: float,
    random_seed: int,
    gurobi_threads: int | None,
) -> FrontendRollingResult:
    """Run and independently classify the production hourly chain."""

    from scripts.run_hourly_charging_reoptimization import (
        RollingChainRequest,
        run_rolling_chain,
    )

    if int(execution_minutes) != 60:
        raise ValueError(
            "The production frontend rolling interval is fixed at 60 minutes"
        )
    service_date = str(
        dict(getattr(problem, "metadata", {}) or {}).get("service_date") or ""
    )[:10]
    if not service_date:
        raise ValueError("Canonical problem is missing service_date")

    request = RollingChainRequest(
        scenario_id=str(scenario_id),
        prepared_input_id=str(prepared_input_id),
        expected_service_date=service_date,
        day_ahead_result_path=str(
            Path(run_dir) / "canonical_solver_result.json"
        ),
        output_dir=str(Path(run_dir) / "rolling_hourly_chain"),
        full_chain=True,
        execution_minutes=60,
        time_limit_sec=max(int(time_limit_sec), 1),
        mip_gap=float(mip_gap),
        random_seed=int(random_seed),
        gurobi_threads=gurobi_threads,
        depot_id=str(depot_id),
        service_id=str(service_id),
        day_ahead_problem=problem,
    )
    exit_code = run_rolling_chain(request)
    chain_summary_path = Path(request.output_dir) / "rolling_chain_summary.json"
    if not chain_summary_path.is_file():
        raise RollingChainExecutionError(
            "Rolling service returned without rolling_chain_summary.json"
        )
    chain_summary = json.loads(chain_summary_path.read_text(encoding="utf-8"))
    acceptance_audit = rolling_chain_acceptance_audit(chain_summary)
    checks = dict(acceptance_audit.get("acceptance_checks") or {})
    technical_check_names = (
        "full_energy_horizon_requested",
        "all_steps_feasible",
        "expected_step_count_observed",
        "executed_day_accounting_eligible",
        "day_ahead_and_rolling_git_sha_match",
        "day_ahead_assignment_hash_constant",
        "gurobi_available",
        "no_chain_runtime_error",
    )
    technical_failures = tuple(
        name for name in technical_check_names if checks.get(name) is not True
    )
    if technical_failures:
        _write_json(
            Path(request.output_dir) / "rolling_execution_failure.json",
            {
                "status": "failed",
                "reason": "rolling_execution_checks_failed",
                "technical_failure_reasons": list(technical_failures),
                "chain_summary_path": str(chain_summary_path),
                "exit_code": int(exit_code),
            },
        )
    refresh_frontend_rolling_manifest(
        run_dir=Path(run_dir),
        run_state=(
            "complete"
            if not technical_failures
            else "rolling_execution_failed"
        ),
    )
    return FrontendRollingResult(
        exit_code=int(exit_code),
        status=(
            "executed_and_accepted"
            if acceptance_audit.get("accepted") is True
            else "executed_not_accepted"
        ),
        chain_summary_path=str(chain_summary_path),
        chain_accepted=bool(acceptance_audit.get("accepted")),
        acceptance_audit=acceptance_audit,
        technical_failure_reasons=technical_failures,
    )
