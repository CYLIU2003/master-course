"""Production orchestration for frontend day-ahead plus hourly rolling runs.

This module deliberately keeps the BFF boundary small.  It persists the exact
canonical problem/result contract produced by the frontend day-ahead solve and
then invokes the same in-process rolling service used by the strict research
CLI.  It never rebuilds timetable rows, duties, or vehicle assignments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from bff.services.optimization_run.cost_breakdown import (
    canonical_cost_ledger_from_breakdown,
)
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
from src.optimization.validation.physical_event_schedule import (
    PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION,
    REQUIRED_ZERO_METRICS,
    validate_physical_event_schedule,
)


DEFAULT_FRONTEND_RUN_PROFILE = "day_ahead_and_hourly_rolling"
DAY_AHEAD_EXPLORATORY_PROFILE = "day_ahead_exploratory"
PHYSICAL_SCHEDULE_VALIDATION_ARTIFACT = "physical_schedule_validation.json"
COMPARISON_CASE_MANIFEST_ARTIFACT = "comparison_case_manifest.json"
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


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required rolling artifact is missing: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return dict(loaded)


def _zero_hard_validation_counts(metrics: Mapping[str, Any]) -> bool:
    """Fail closed when a required metric is absent, malformed, or nonzero."""

    for key in REQUIRED_ZERO_METRICS:
        if key not in metrics:
            return False
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(float(value)) or int(value) != 0:
            return False
    return True


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({str(key) for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _persist_physical_event_artifacts(
    *,
    run_dir: Path,
    event_validation: Mapping[str, Any],
) -> None:
    graph_dir = Path(run_dir) / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    events = [
        dict(item) for item in list(event_validation.get("events") or ())
    ]
    violations = [
        dict(item) for item in list(event_validation.get("violations") or ())
    ]
    _write_csv(graph_dir / "vehicle_event_timeline.csv", events)
    _write_csv(
        graph_dir / "charger_occupancy_timeline.csv",
        [item for item in events if item.get("event_type") == "charging"],
    )
    _write_csv(
        graph_dir / "vehicle_location_timeline.csv",
        [
            {
                "event_id": item.get("event_id"),
                "vehicle_id": item.get("vehicle_id"),
                "event_type": item.get("event_type"),
                "start_min": item.get("start_min"),
                "end_min": item.get("end_min"),
                "start_location": item.get("start_location"),
                "end_location": item.get("end_location"),
            }
            for item in events
        ],
    )
    _write_csv(graph_dir / "physical_schedule_violations.csv", violations)


def _physical_schedule_validation(
    *,
    run_dir: Path,
    optimization_result: Mapping[str, Any],
    chain: Mapping[str, Any],
    executed_day: Mapping[str, Any],
    event_validation: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently classify physical feasibility, not research acceptance."""

    canonical = _load_json_object(run_dir / "canonical_solver_result.json")
    solver_metadata = dict(
        canonical.get("solver_metadata")
        or optimization_result.get("solver_metadata")
        or {}
    )
    validity = dict(
        optimization_result.get("solution_validity")
        or canonical.get("solution_validity")
        or {}
    )
    solver_validation_metrics = dict(
        validity.get("validation_metrics")
        or solver_metadata.get("validation_metrics")
        or {}
    )
    validation_metrics = dict(event_validation.get("metrics") or {})
    trip_count_unserved = int(canonical.get("trip_count_unserved", 0) or 0)
    chain_audit = rolling_chain_acceptance_audit(chain)
    no_fallback_or_repair = not any(
        bool(solver_metadata.get(key))
        for key in (
            "fallback_applied",
            "postsolve_soc_repair_applied",
            "postsolve_charging_recomputed",
            "postsolve_modified_solution",
        )
    )
    checks = {
        "canonical_solver_feasible": canonical.get("feasible") is True,
        "all_trips_served": (
            trip_count_unserved == 0
            and not list(canonical.get("unserved_trip_ids") or ())
        ),
        "hard_validation_counts_zero": _zero_hard_validation_counts(
            validation_metrics
        ),
        "independent_event_schema_current": (
            event_validation.get("schema_version")
            == PHYSICAL_EVENT_VALIDATION_SCHEMA_VERSION
        ),
        "independent_event_schedule_accepted": (
            event_validation.get("accepted") is True
        ),
        "all_required_hard_validation_checks_passed": (
            solver_validation_metrics.get("all_required_validation_checks_passed")
            is True
        ),
        "no_fallback_or_postsolve_repair": no_fallback_or_repair,
        "rolling_chain_accepted": chain_audit.get("accepted") is True,
        "rolling_assignment_hash_constant": dict(
            chain.get("acceptance_checks") or {}
        ).get("day_ahead_assignment_hash_constant")
        is True,
        "day_ahead_and_rolling_git_sha_match": dict(
            chain.get("acceptance_checks") or {}
        ).get("day_ahead_and_rolling_git_sha_match")
        is True,
        "executed_day_accounting_eligible": executed_day.get("eligible") is True,
        "bev_terminal_energy_balanced": (
            executed_day.get("bev_terminal_energy_balanced") is True
        ),
        "bess_terminal_energy_balanced": (
            executed_day.get("bess_terminal_energy_balanced") is True
        ),
        "required_input_hashes_present": all(
            bool(str(chain.get(key) or "").strip())
            for key in (
                "trip_input_hash",
                "vehicle_input_hash",
                "scenario_fleet_contract_hash",
                "active_vehicle_id_hash",
                "vehicle_parameter_hash",
                "initial_state_hash",
                "initial_soc_input_hash",
                "charger_configuration_hash",
                "day_ahead_assignment_hash",
            )
        ),
    }
    failed_checks = sorted(
        name for name, passed in checks.items() if passed is not True
    )
    return {
        "schema_version": "physical_schedule_validation_v2",
        "accepted": not failed_checks,
        "status": "VALID" if not failed_checks else "INVALID",
        "checks": checks,
        "failed_checks": failed_checks,
        "validation_metrics": validation_metrics,
        "solver_validation_metrics": solver_validation_metrics,
        "independent_event_validation": {
            key: value
            for key, value in event_validation.items()
            if key not in {"events", "violations"}
        },
        "evidence": {
            "canonical_solver_result": "canonical_solver_result.json",
            "rolling_chain_summary": (
                "rolling_hourly_chain/rolling_chain_summary.json"
            ),
            "executed_day_accounting": (
                "rolling_hourly_chain/executed_day_accounting.json"
            ),
            "trip_input_hash": chain.get("trip_input_hash"),
            "vehicle_input_hash": chain.get("vehicle_input_hash"),
            "scenario_fleet_contract_hash": chain.get(
                "scenario_fleet_contract_hash"
            ),
            "active_vehicle_id_hash": chain.get(
                "active_vehicle_id_hash"
            ),
            "vehicle_parameter_hash": chain.get(
                "vehicle_parameter_hash"
            ),
            "initial_state_hash": chain.get("initial_state_hash"),
            "initial_soc_input_hash": chain.get("initial_soc_input_hash"),
            "charger_configuration_hash": chain.get(
                "charger_configuration_hash"
            ),
            "assignment_hash": chain.get("day_ahead_assignment_hash"),
            "day_ahead_git_sha": chain.get("day_ahead_git_sha"),
            "rolling_runner_git_sha": chain.get("rolling_runner_git_sha"),
            "vehicle_event_timeline": "graph/vehicle_event_timeline.csv",
            "charger_occupancy_timeline": (
                "graph/charger_occupancy_timeline.csv"
            ),
            "vehicle_location_timeline": (
                "graph/vehicle_location_timeline.csv"
            ),
            "physical_schedule_violations": (
                "graph/physical_schedule_violations.csv"
            ),
        },
        "semantics": (
            "This artifact proves physical schedule and executed rolling-chain "
            "validity only. Research acceptance, fleet-contract compliance, "
            "and global optimality are separate gates."
        ),
    }


def _price_slot_hash(problem: Any) -> str:
    return _canonical_hash(
        [
            {
                "slot_index": int(getattr(slot, "slot_index", 0) or 0),
                "grid_buy_yen_per_kwh": float(
                    getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0
                ),
                "grid_sell_yen_per_kwh": float(
                    getattr(slot, "grid_sell_yen_per_kwh", 0.0) or 0.0
                ),
                "demand_charge_weight": float(
                    getattr(slot, "demand_charge_weight", 0.0) or 0.0
                ),
                "co2_factor": float(
                    getattr(slot, "co2_factor", 0.0) or 0.0
                ),
            }
            for slot in tuple(getattr(problem, "price_slots", ()) or ())
        ]
    )


def _non_pv_depot_asset_hash(problem: Any) -> str:
    from scripts.run_research_phase3_frontend_weather import _asset_snapshot

    fixed = {
        depot_id: {
            key: value
            for key, value in dict(asset).items()
            if key
            not in {
                "pv_case_id",
                "pv_generation_kwh",
                "pv_generation_hash",
            }
        }
        for depot_id, asset in sorted(_asset_snapshot(problem).items())
    }
    return _canonical_hash(fixed)


def _comparison_case_manifest(
    *,
    scenario: Mapping[str, Any],
    problem: Any,
    input_audit: Mapping[str, Any],
    chain: Mapping[str, Any],
    physical_validation: Mapping[str, Any],
    executed_day: Mapping[str, Any],
    optimization_result: Mapping[str, Any],
) -> dict[str, Any]:
    simulation_config = dict(scenario.get("simulation_config") or {})
    comparison_type = str(
        simulation_config.get("comparison_type") or ""
    ).strip()
    comparison_requested = (
        comparison_type == "same_service_date_pv_counterfactual"
    )
    service_date = str(chain.get("service_date") or "")[:10]
    source_date = str(
        simulation_config.get("counterfactual_pv_source_date") or ""
    )[:10]
    explicit_role = str(
        simulation_config.get("comparison_role") or ""
    ).strip()
    comparison_role = explicit_role or (
        "baseline"
        if source_date and source_date == service_date
        else "pv_curve_counterfactual"
    )
    solver_settings = dict(
        optimization_result.get("solver_settings") or {}
    )
    control_payload = {
        "schema_version": "frontend_pv_control_contract_v1",
        "service_date": service_date,
        "service_id": input_audit.get("service_id"),
        "trip_input_hash": chain.get("trip_input_hash"),
        "vehicle_input_hash": chain.get("vehicle_input_hash"),
        "scenario_fleet_contract_hash": chain.get(
            "scenario_fleet_contract_hash"
        ),
        "active_vehicle_id_hash": chain.get("active_vehicle_id_hash"),
        "vehicle_parameter_hash": chain.get("vehicle_parameter_hash"),
        "initial_state_hash": chain.get("initial_state_hash"),
        "initial_soc_input_hash": chain.get("initial_soc_input_hash"),
        "charger_configuration_hash": chain.get(
            "charger_configuration_hash"
        ),
        "non_pv_depot_asset_hash": _non_pv_depot_asset_hash(problem),
        "price_slot_hash": _price_slot_hash(problem),
        "bev_terminal_soc_policy": chain.get("bev_terminal_soc_policy"),
        "bess_terminal_policy": chain.get("bess_terminal_policy"),
        "timestep_min": chain.get("timestep_min"),
        "energy_horizon_start_time": chain.get("energy_horizon_start_time"),
        "energy_horizon_end_time": chain.get("energy_horizon_end_time"),
        "energy_horizon_slot_count": chain.get("energy_horizon_slot_count"),
        "solver_backend": chain.get("solver_backend"),
        "solver_version": chain.get("solver_version"),
        "day_ahead_solver_controls": {
            "time_limit_seconds_effective": solver_settings.get(
                "time_limit_seconds_effective"
            ),
            "stage2_time_limit_seconds_effective": solver_settings.get(
                "stage2_time_limit_seconds_effective"
            ),
            "mip_gap_requested_ratio": solver_settings.get(
                "mip_gap_requested_ratio"
            ),
            "stage1_best_obj_stop_enabled": solver_settings.get(
                "stage1_best_obj_stop_enabled"
            ),
            "gurobi_threads": solver_settings.get("gurobi_threads"),
            "random_seed": dict(
                optimization_result.get("solver_metadata") or {}
            ).get("random_seed"),
        },
        "rolling_solver_controls": {
            "gurobi_threads": chain.get("gurobi_threads"),
            "mip_gap": chain.get("mip_gap"),
            "time_limit_sec": chain.get("time_limit_sec"),
            "random_seed": chain.get("random_seed"),
            "execution_minutes": chain.get("execution_minutes"),
        },
        "git_sha": chain.get("day_ahead_git_sha"),
        "weather_operation_policy_enabled": bool(
            simulation_config.get("enable_weather_operation_policy", False)
        ),
        "minimum_used_bev_count": int(
            dict(getattr(problem, "metadata", {}) or {}).get(
                "minimum_used_bev_count", 0
            )
            or 0
        ),
    }
    cost_breakdown = dict(executed_day.get("cost_breakdown") or {})
    return {
        "schema_version": "frontend_pv_comparison_case_v1",
        "comparison_requested": comparison_requested,
        "comparison_type": comparison_type or None,
        "comparison_role": comparison_role,
        # Every accepted frontend run receives a case-level control hash. This
        # allows an explicitly selected baseline run (which need not itself be
        # configured as a counterfactual) to be paired fail-closed later.
        "comparison_control_hash": _canonical_hash(control_payload),
        "comparison_control_payload": control_payload,
        "pv_profile_hash": chain.get("day_ahead_pv_forecast_hash"),
        "pv_source_date": source_date or None,
        "assignment_hash": chain.get("day_ahead_assignment_hash"),
        "physical_schedule_validated": physical_validation.get("accepted")
        is True,
        "rolling_chain_accepted": chain.get("chain_accepted") is True,
        "executed_day_accounting_eligible": executed_day.get("eligible") is True,
        "executed_total_cost_jpy": cost_breakdown.get("total_cost"),
        "pv_generated_kwh": cost_breakdown.get("pv_generated_kwh"),
        "grid_import_kwh": cost_breakdown.get("grid_import_kwh"),
        "semantics": (
            "A case-level comparison contract. A separate pair manifest must "
            "verify matching control hashes and different PV hashes before "
            "cross-case claims are allowed."
        ),
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
        "scenario_fleet_contract.json",
        "input_audit.json",
        "canonical_solver_result.json",
        "summary.json",
        "rolling_hourly_chain/rolling_chain_summary.json",
        "rolling_hourly_chain/executed_day_accounting.json",
        "rolling_hourly_chain/day_ahead_vs_rolling_summary.json",
        "rolling_hourly_chain/hourly_energy_flow_chart.csv",
        "rolling_hourly_chain/charging_schedule.csv",
        PHYSICAL_SCHEDULE_VALIDATION_ARTIFACT,
        COMPARISON_CASE_MANIFEST_ARTIFACT,
        "final_cost_reconciliation.json",
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
                "scenario_fleet_contract_hash",
                "active_vehicle_id_hash",
                "vehicle_parameter_hash",
                "initial_state_hash",
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
    fleet_contract = dict(metadata.get("scenario_fleet_contract") or {})
    if (
        fleet_contract.get("schema_version")
        != "scenario_fleet_contract_v2"
    ):
        raise ValueError(
            "Canonical problem is missing scenario_fleet_contract_v2"
        )
    _write_json(
        run_dir / "scenario_fleet_contract.json",
        fleet_contract,
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
        "scenario_fleet_contract_hash": fleet_contract.get(
            "fleet_contract_hash"
        ),
        "active_vehicle_id_hash": fleet_contract.get(
            "active_vehicle_id_hash"
        ),
        "vehicle_parameter_hash": fleet_contract.get(
            "vehicle_parameter_hash"
        ),
        "initial_state_hash": fleet_contract.get("initial_state_hash"),
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


def finalize_frontend_rolling_evidence(
    *,
    run_dir: Path,
    scenario: Mapping[str, Any],
    problem: Any,
    optimization_result: dict[str, Any],
) -> dict[str, Any]:
    """Promote accepted rolling execution to the final physical/cost evidence.

    The day-ahead solver objective remains untouched.  Only the accounting
    source is replaced, and only after the complete chain is independently
    accepted.
    """

    run_dir = Path(run_dir)
    chain_path = run_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    executed_day_path = (
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    input_audit_path = run_dir / "input_audit.json"
    chain = _load_json_object(chain_path)
    executed_day = _load_json_object(executed_day_path)
    input_audit = _load_json_object(input_audit_path)
    chain_audit = rolling_chain_acceptance_audit(chain)
    if chain_audit.get("accepted") is not True:
        raise RollingChainExecutionError(
            "Cannot finalize accounting from an unaccepted rolling chain"
        )
    if executed_day.get("eligible") is not True:
        raise RollingChainExecutionError(
            "Cannot finalize accounting from an ineligible executed day"
        )

    executed_result_for_validation = dict(optimization_result)
    executed_charging_path = (
        run_dir / "rolling_hourly_chain" / "charging_schedule.csv"
    )
    if not executed_charging_path.is_file():
        raise RollingChainExecutionError(
            "Executed rolling charging_schedule.csv is missing"
        )
    with executed_charging_path.open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        executed_result_for_validation["charging_schedule"] = list(
            csv.DictReader(handle)
        )
    event_validation = validate_physical_event_schedule(
        problem=problem,
        serialized_result=executed_result_for_validation,
    )
    _persist_physical_event_artifacts(
        run_dir=run_dir,
        event_validation=event_validation,
    )
    physical_validation = _physical_schedule_validation(
        run_dir=run_dir,
        optimization_result=optimization_result,
        chain=chain,
        executed_day=executed_day,
        event_validation=event_validation,
    )
    _write_json(
        run_dir / PHYSICAL_SCHEDULE_VALIDATION_ARTIFACT,
        physical_validation,
    )
    _write_json(
        run_dir / "graph" / "physical_schedule_validation.json",
        physical_validation,
    )
    if physical_validation.get("accepted") is not True:
        raise RollingChainExecutionError(
            "Physical schedule validation failed: "
            + ", ".join(physical_validation.get("failed_checks") or ())
        )

    executed_breakdown = dict(executed_day.get("cost_breakdown") or {})
    if not executed_breakdown:
        raise RollingChainExecutionError(
            "Executed-day accounting is missing cost_breakdown"
        )
    # Keep the executed accounting values authoritative while supplying the
    # stable reporting aliases consumed by CSV/XLSX writers.
    executed_breakdown["demand_charge"] = float(
        executed_breakdown.get("demand_cost", 0.0) or 0.0
    )
    executed_breakdown["total_demand_charge"] = float(
        executed_breakdown.get("demand_cost", 0.0) or 0.0
    )
    executed_breakdown["electricity_cost_final"] = float(
        executed_breakdown.get("electricity_cost", 0.0) or 0.0
    )
    executed_breakdown["fuel_cost_final"] = float(
        executed_breakdown.get("fuel_cost", 0.0) or 0.0
    )
    executed_breakdown["cost_component_flags"] = dict(
        problem.metadata.get("cost_component_flags") or {}
    )
    solver_metadata = dict(optimization_result.get("solver_metadata") or {})
    ledger = canonical_cost_ledger_from_breakdown(
        breakdown=executed_breakdown,
        scenario_id=str(optimization_result.get("scenario_id") or ""),
        source="rolling_hourly_chain/executed_day_accounting.json",
        objective_mode=str(
            optimization_result.get("objective_mode")
            or solver_metadata.get("objective_mode")
            or "total_cost"
        ),
        objective_value=(
            float(optimization_result["objective_value"])
            if optimization_result.get("objective_value") is not None
            else None
        ),
        # Phase 3's day-ahead objective is not the stitched rolling cost.
        objective_is_actual_cost=False,
        solver_objective_matches_accounting_total=False,
        carbon_price_jpy_per_kg=float(
            getattr(problem.scenario, "co2_price_per_kg", 0.0) or 0.0
        ),
        evidence={
            "accounting_basis": executed_day.get("accounting_basis"),
            "objective_aggregation": executed_day.get(
                "objective_aggregation"
            ),
            "executed_energy_flow_hash": executed_day.get(
                "executed_energy_flow_hash"
            ),
            "expected_slot_count": executed_day.get("expected_slot_count"),
            "executed_slot_count": executed_day.get("executed_slot_count"),
        },
    )
    if ledger.get("accounting_residual_satisfied") is not True:
        raise RollingChainExecutionError(
            "Executed-day canonical cost ledger does not reconcile: "
            f"{ledger.get('accounting_residual_jpy')}"
        )
    _write_json(
        run_dir / "graph" / "canonical_cost_ledger.json",
        ledger,
    )

    day_ahead_breakdown = dict(optimization_result.get("cost_breakdown") or {})
    optimization_result["day_ahead_cost_breakdown"] = day_ahead_breakdown
    optimization_result["cost_breakdown"] = executed_breakdown
    optimization_result["final_accounting_source"] = (
        "rolling_hourly_chain/executed_day_accounting.json"
    )
    optimization_result["final_accounting_total_cost_jpy"] = ledger[
        "accounting_total_cost_jpy"
    ]
    solution_validity = dict(
        optimization_result.get("solution_validity") or {}
    )
    solution_validity.update(
        {
            "validated_feasible": True,
            "validated_no_cancellation": True,
            "physical_schedule_validation_status": "VALID",
            "physical_schedule_validation_artifact": (
                PHYSICAL_SCHEDULE_VALIDATION_ARTIFACT
            ),
        }
    )
    optimization_result["solution_validity"] = solution_validity
    if isinstance(optimization_result.get("summary"), dict):
        optimization_result["summary"]["solution_validity"] = solution_validity

    comparison_case = _comparison_case_manifest(
        scenario=scenario,
        problem=problem,
        input_audit=input_audit,
        chain=chain,
        physical_validation=physical_validation,
        executed_day=executed_day,
        optimization_result=optimization_result,
    )
    _write_json(
        run_dir / COMPARISON_CASE_MANIFEST_ARTIFACT,
        comparison_case,
    )
    return {
        "physical_schedule_validation": physical_validation,
        "canonical_cost_ledger": ledger,
        "comparison_case_manifest": comparison_case,
    }


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
