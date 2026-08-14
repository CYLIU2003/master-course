"""Execute declared thesis sensitivities through the frontend BFF HTTP path.

The runner consumes complete Prepare and optimization payloads exported from
the frontend. It changes only the fields declared by the experiment matrix,
uses fresh Prepare IDs, polls the public job endpoint, copies the immutable run
bundle, and records fail-closed provenance. It never imports or calls a solver.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.input_provenance import (  # noqa: E402
    PREPARED_TRIP_INPUT_SCHEMA,
    validate_run_input_provenance,
)
from scripts.build_thesis_experiment_matrix import (  # noqa: E402
    build_experiment_matrix,
)
from scripts.run_frontend_controlled_pv_pair import (  # noqa: E402
    HttpJsonClient,
    _assert_clean_frozen_repository,
    _copy_run_contents,
    _poll_job,
    _utc_now,
    _write_json,
    _write_raw_json_response,
)


SCHEMA_VERSION = "thesis_sensitivity_execution_v3_turnaround_buffer"
CSV_COLUMNS = (
    "case_id",
    "family",
    "case_accepted",
    "prepared_input_id",
    "job_id",
    "solver_status",
    "mip_gap_target_met",
    "certified_mip_gap_percent",
    "solve_time_seconds",
    "wall_time_seconds",
    "timestep_min",
    "turnaround_buffer_min",
    "rolling_execution_minutes_submitted",
    "rolling_execution_minutes_requested",
    "rolling_execution_minutes_effective",
    "trip_count_served",
    "trip_count_unserved",
    "vehicle_count_used",
    "used_vehicle_day_count",
    "vehicle_usage_cost_jpy_per_used_bus",
    "vehicle_usage_cost_jpy",
    "vehicle_usage_cost_formula_residual_jpy",
    "vehicle_usage_cost_semantics",
    "vehicle_usage_cost_semantics_research_eligible",
    "bev_trip_count",
    "ice_trip_count",
    "total_cost_jpy",
    "total_co2_kg",
    "grid_import_kwh",
    "pv_generated_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "bess_to_bus_kwh",
    "rolling_min_bev_soc_kwh",
    "rolling_min_bev_soc_percent",
    "rolling_min_bev_soc_margin_percent",
    "rolling_min_bev_soc_vehicle_id",
    "rolling_min_bev_soc_time",
    "source_run_dir",
)


def build_case_requests(
    *,
    case: Mapping[str, Any],
    base_prepare_request: Mapping[str, Any],
    base_optimization_request: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one matrix row to complete frontend request payloads."""

    prepare = _json_copy(base_prepare_request)
    settings = prepare.get("simulation_settings")
    if not isinstance(settings, dict):
        raise ValueError("base Prepare request must contain simulation_settings")
    settings.update(dict(case.get("prepare_settings") or {}))
    prepare.update(dict(case.get("prepare_request_overrides") or {}))

    optimization = _json_copy(base_optimization_request)
    optimization.update(
        dict(case.get("optimization_request_overrides") or {})
    )
    optimization.pop("prepared_input_id", None)
    optimization.pop("preparedInputId", None)
    return prepare, optimization


def execute_sensitivity_matrix(
    *,
    scenario_id: str,
    base_url: str,
    base_prepare_request: Mapping[str, Any],
    base_optimization_request: Mapping[str, Any],
    output_dir: Path,
    selected_case_ids: set[str] | None = None,
    timeout_seconds: float = 14_400.0,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    """Execute selected cases and return an audited matrix manifest."""

    matrix = build_experiment_matrix()
    declared_cases = list(matrix.get("cases") or [])
    declared_ids = {str(case.get("case_id") or "") for case in declared_cases}
    selected_ids = set(selected_case_ids or declared_ids)
    unknown = sorted(selected_ids - declared_ids)
    if unknown:
        raise ValueError(f"unknown sensitivity case IDs: {', '.join(unknown)}")
    cases = [
        case
        for case in declared_cases
        if str(case.get("case_id") or "") in selected_ids
    ]
    if not cases:
        raise ValueError("at least one sensitivity case must be selected")

    frozen_sha = _assert_clean_frozen_repository()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"sensitivity output directory must be empty: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "experiment_matrix.json", matrix)
    _write_json(
        output_dir / "base_frontend_requests.json",
        {
            "prepare": dict(base_prepare_request),
            "optimization": dict(base_optimization_request),
        },
    )

    client = HttpJsonClient(base_url)
    progress_log: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["case_id"])
        case_dir = output_dir / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=False)
        prepare_request, optimization_template = build_case_requests(
            case=case,
            base_prepare_request=base_prepare_request,
            base_optimization_request=base_optimization_request,
        )
        _write_json(case_dir / "frontend_prepare_request.json", prepare_request)
        before_sha = _assert_clean_frozen_repository()
        if before_sha != frozen_sha:
            raise RuntimeError("Git SHA changed before a sensitivity case")

        prepare_response, prepare_raw = client.request_json(
            "POST",
            f"/api/scenarios/{scenario_id}/simulation/prepare",
            prepare_request,
            timeout_seconds=timeout_seconds,
        )
        _write_raw_json_response(
            case_dir / "frontend_prepare_response.json",
            prepare_raw,
        )
        prepared_input_id = str(
            prepare_response.get("preparedInputId") or ""
        ).strip()
        if prepare_response.get("ready") is not True or not prepared_input_id:
            raise RuntimeError(f"{case_id} Prepare did not produce a ready input")

        optimization_request = dict(optimization_template)
        optimization_request["prepared_input_id"] = prepared_input_id
        _write_json(
            case_dir / "frontend_optimization_request.json",
            optimization_request,
        )
        started_at = _utc_now()
        started = time.monotonic()
        submit_response, submit_raw = client.request_json(
            "POST",
            f"/api/scenarios/{scenario_id}/run-optimization",
            optimization_request,
            timeout_seconds=timeout_seconds,
        )
        _write_raw_json_response(
            case_dir / "frontend_optimization_submit_response.json",
            submit_raw,
        )
        job_id = str(
            submit_response.get("job_id") or submit_response.get("jobId") or ""
        ).strip()
        if not job_id:
            raise RuntimeError(f"{case_id} optimization returned no job ID")
        terminal, terminal_raw = _poll_job(
            client=client,
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            log=progress_log,
        )
        _write_raw_json_response(
            case_dir / "frontend_job_terminal_response.json",
            terminal_raw,
        )
        source_run_dir_text = str(
            dict(terminal.get("metadata") or {}).get("run_dir") or ""
        ).strip()
        source_run_dir = (
            Path(source_run_dir_text).resolve()
            if source_run_dir_text
            else None
        )
        copied_run_dir = case_dir / "source_run"
        if source_run_dir is not None and source_run_dir.is_dir():
            _copy_run_contents(source_run_dir, copied_run_dir)
        try:
            outcome = _audit_case(
                case=case,
                run_dir=copied_run_dir,
                terminal=terminal,
                submitted_optimization_request=optimization_request,
            )
        except (OSError, ValueError) as exc:
            outcome = {
                "case_id": case_id,
                "family": case.get("family"),
                "case_accepted": False,
                "failed_checks": ["source_artifact_validation_failed"],
                "source_artifact_error": f"{type(exc).__name__}: {exc}",
            }
        outcome.update(
            {
                "prepared_input_id": prepared_input_id,
                "job_id": job_id,
                "started_at_utc": started_at,
                "completed_at_utc": _utc_now(),
                "wall_time_seconds": time.monotonic() - started,
                "source_run_dir": (
                    str(source_run_dir) if source_run_dir is not None else None
                ),
                "copied_run_dir": str(copied_run_dir),
            }
        )
        after_sha = _assert_clean_frozen_repository()
        outcome["git_sha_unchanged"] = after_sha == before_sha == frozen_sha
        if not outcome["git_sha_unchanged"]:
            outcome["case_accepted"] = False
            outcome.setdefault("failed_checks", []).append(
                "git_sha_unchanged"
            )
        outcomes.append(outcome)
        _write_json(case_dir / "case_execution_audit.json", outcome)
        _write_json(output_dir / "progress_log.json", progress_log)
        _write_manifest(
            output_dir=output_dir,
            matrix=matrix,
            frozen_sha=frozen_sha,
            audit_builder_sha=frozen_sha,
            selected_ids=selected_ids,
            outcomes=outcomes,
        )

    return _write_manifest(
        output_dir=output_dir,
        matrix=matrix,
        frozen_sha=frozen_sha,
        audit_builder_sha=frozen_sha,
        selected_ids=selected_ids,
        outcomes=outcomes,
    )


def _audit_case(
    *,
    case: Mapping[str, Any],
    run_dir: Path,
    terminal: Mapping[str, Any],
    submitted_optimization_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    if not run_dir.is_dir():
        return {
            "case_id": case_id,
            "family": case.get("family"),
            "case_accepted": False,
            "failed_checks": ["source_run_missing"],
        }
    required = {
        name: _read_json(run_dir / name)
        for name in (
            "optimization_parameters.json",
            "solver_settings.json",
            "summary.json",
            "physical_schedule_validation.json",
            "artifact_completeness.json",
            "assignment_economic_audit.json",
            "scenario_input_snapshot.json",
            "rolling_hourly_chain/executed_day_accounting.json",
            "rolling_hourly_chain/rolling_chain_summary.json",
        )
    }
    input_validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    prepare_audit = _read_json(run_dir / "prepare_input_audit.json")
    prepared_trip_input_sha256 = None
    prepared_trip_input_hash_source = None
    if str(case.get("family") or "") == "trip_energy_sensitivity":
        (
            prepared_trip_input_sha256,
            prepared_trip_input_hash_source,
        ) = _verified_prepared_trip_input_hash(
            prepare_audit=prepare_audit,
            input_validation=input_validation,
        )
    settings = required["solver_settings.json"]
    physical = required["physical_schedule_validation.json"]
    completeness = required["artifact_completeness.json"]
    accounting = required[
        "rolling_hourly_chain/executed_day_accounting.json"
    ]
    rolling_soc = _rolling_min_bev_soc_evidence(
        run_dir=run_dir,
        completeness=completeness,
        scenario_snapshot=required["scenario_input_snapshot.json"],
        rolling_summary=required[
            "rolling_hourly_chain/rolling_chain_summary.json"
        ],
    )
    parameter_match = _case_parameter_matches(
        case=case,
        parameters=required["optimization_parameters.json"],
        economic_audit=required["assignment_economic_audit.json"],
    )
    declared_controls_match = _declared_controls_match(
        case=case,
        parameters=required["optimization_parameters.json"],
        economic_audit=required["assignment_economic_audit.json"],
    )
    request_provenance_match = _submitted_request_matches_provenance(
        submitted_request=submitted_optimization_request,
        parameters=required["optimization_parameters.json"],
    )
    summary = required["summary.json"]
    accounting = required[
        "rolling_hourly_chain/executed_day_accounting.json"
    ]
    vehicle_day_cost_audit = _vehicle_day_cost_case_audit(
        case=case,
        parameters=required["optimization_parameters.json"],
        solver_settings=settings,
        accounting=accounting,
        summary=summary,
    )
    checks = {
        "frontend_job_completed": terminal.get("status") == "completed",
        "run_input_valid": input_validation.get("valid") is True,
        "run_input_research_ready": (
            input_validation.get("research_ready") is True
        ),
        "artifact_bundle_complete": bool(
            completeness.get("status") == "OK"
            and completeness.get("accepted") is True
            and completeness.get("research_run") is True
        ),
        "finalized_artifact_hashes_match": _artifact_snapshot_matches(
            run_dir=run_dir,
            completeness=completeness,
            relative_paths=_snapshotted_artifact_paths(tuple(required)),
        ),
        "explicit_phase4_integrated": bool(
            settings.get("requested_phase") == "phase4_integrated"
            and settings.get("resolved_phase") == "phase4_integrated"
            and settings.get("executed_phase") == "phase4_integrated"
        ),
        "research_run_accepted": settings.get("research_run_accepted") is True,
        "mip_gap_target_met": settings.get("mip_gap_target_met") is True,
        "no_successor_pruning": (
            settings.get("successor_pruning_enabled") is False
        ),
        "physical_schedule_valid": bool(
            physical.get("status") == "VALID"
            and physical.get("accepted") is True
        ),
        "rolling_accounting_eligible": accounting.get("eligible") is True,
        "rolling_soc_evidence_verified": (
            rolling_soc.get("source_artifacts_verified") is True
        ),
        "declared_case_parameter_effective": parameter_match,
        "declared_common_controls_effective": declared_controls_match,
        "submitted_request_provenance_matches": request_provenance_match,
        "prepared_trip_structure_verified": bool(
            str(case.get("family") or "") != "trip_energy_sensitivity"
            or prepared_trip_input_sha256
        ),
        "vehicle_day_cost_semantics_and_formula_valid": bool(
            vehicle_day_cost_audit.get("passed") is True
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    costs = dict(accounting.get("cost_breakdown") or {})
    trip_types = dict(summary.get("trip_count_by_type") or {})
    frontend_request = dict(
        required["optimization_parameters.json"].get("frontend_request") or {}
    )
    raw_frontend_body = dict(frontend_request.get("raw_frontend_body") or {})
    effective_rolling = dict(
        frontend_request.get("effective_rolling_controls") or {}
    )
    return {
        "case_id": case_id,
        "family": case.get("family"),
        "case_accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "stable_control_fingerprint": _stable_control_fingerprint(
            case=case,
            parameters=required["optimization_parameters.json"],
            economic_audit=required["assignment_economic_audit.json"],
            prepared_trip_input_sha256=prepared_trip_input_sha256,
        ),
        "prepared_trip_input_sha256": prepared_trip_input_sha256,
        "prepared_trip_input_hash_source": prepared_trip_input_hash_source,
        "input_validation": input_validation,
        "solver_status": summary.get("solver_status"),
        "mip_gap_target_met": summary.get("mip_gap_target_met"),
        "certified_mip_gap_percent": settings.get(
            "certified_mip_gap_percent"
        ),
        "solve_time_seconds": summary.get("solve_time_seconds"),
        "timestep_min": dict(
            required["optimization_parameters.json"].get(
                "effective_problem_scenario"
            )
            or {}
        ).get("timestep_min"),
        "turnaround_buffer_min": dict(
            required["optimization_parameters.json"].get(
                "effective_model_metadata"
            )
            or {}
        ).get("turnaround_buffer_min"),
        "rolling_execution_minutes_submitted": dict(
            submitted_optimization_request or {}
        ).get("rolling_execution_minutes"),
        "rolling_execution_minutes_requested": raw_frontend_body.get(
            "rolling_execution_minutes"
        ),
        "rolling_execution_minutes_effective": effective_rolling.get(
            "rolling_execution_minutes"
        ),
        "trip_count_served": summary.get("trip_count_served"),
        "trip_count_unserved": summary.get("trip_count_unserved"),
        "vehicle_count_used": summary.get("vehicle_count_used"),
        "used_vehicle_day_count": costs.get("used_vehicle_day_count"),
        "vehicle_usage_cost_jpy_per_used_bus": costs.get(
            "vehicle_usage_cost_jpy_per_used_bus"
        ),
        "vehicle_usage_cost_jpy": costs.get("vehicle_usage_cost_jpy"),
        "vehicle_usage_cost_formula_residual_jpy": (
            vehicle_day_cost_audit.get("formula_residual_jpy")
        ),
        "vehicle_usage_cost_semantics": vehicle_day_cost_audit.get(
            "effective_semantics"
        ),
        "vehicle_usage_cost_semantics_research_eligible": (
            vehicle_day_cost_audit.get("research_eligible")
        ),
        "vehicle_day_cost_audit": vehicle_day_cost_audit,
        "bev_trip_count": trip_types.get("BEV", 0),
        "ice_trip_count": trip_types.get("ICE", 0),
        "total_cost_jpy": costs.get("total_cost"),
        "total_co2_kg": costs.get("total_co2_kg"),
        "grid_import_kwh": costs.get("grid_import_kwh"),
        "pv_generated_kwh": costs.get("pv_generated_kwh"),
        "pv_to_bus_kwh": costs.get("pv_to_bus_kwh"),
        "pv_to_bess_kwh": costs.get("pv_to_bess_kwh"),
        "bess_to_bus_kwh": costs.get("bess_to_bus_kwh"),
        "rolling_min_bev_soc_kwh": rolling_soc.get("minimum_soc_kwh"),
        "rolling_min_bev_soc_percent": rolling_soc.get(
            "minimum_soc_percent"
        ),
        "rolling_min_bev_soc_margin_percent": rolling_soc.get(
            "minimum_margin_above_vehicle_limit_percent"
        ),
        "rolling_min_bev_soc_vehicle_id": rolling_soc.get("vehicle_id"),
        "rolling_min_bev_soc_time": rolling_soc.get("time"),
        "rolling_soc_evidence": rolling_soc,
    }


def _vehicle_day_cost_case_audit(
    *,
    case: Mapping[str, Any],
    parameters: Mapping[str, Any],
    solver_settings: Mapping[str, Any],
    accounting: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify one-time vehicle-day activation cost for its sensitivity family."""

    if str(case.get("family") or "") != "vehicle_day_cost_sensitivity":
        return {
            "applicable": False,
            "passed": True,
            "reason": "not_vehicle_day_cost_sensitivity",
        }

    expected = dict(case.get("prepare_settings") or {})
    metadata = dict(parameters.get("effective_model_metadata") or {})
    flags = dict(metadata.get("cost_component_flags") or {})
    costs = dict(accounting.get("cost_breakdown") or {})
    expected_unit = expected.get("vehicle_usage_cost_jpy_per_used_bus")
    effective_unit = metadata.get("vehicle_usage_cost_jpy_per_used_bus")
    accounting_unit = costs.get("vehicle_usage_cost_jpy_per_used_bus")
    used_vehicle_days = costs.get("used_vehicle_day_count")
    vehicle_count_used = summary.get("vehicle_count_used")
    accounting_cost = costs.get("vehicle_usage_cost_jpy")

    formula_residual: float | None = None
    try:
        formula_residual = float(accounting_cost) - (
            float(used_vehicle_days) * float(accounting_unit)
        )
    except (TypeError, ValueError):
        pass
    checks = {
        "objective_preset_is_scalar_total_cost": (
            metadata.get("objective_preset") == "scalar_total_cost_v1"
        ),
        "integrated_primary_objective_is_canonical_cost": (
            solver_settings.get("integrated_primary_objective_kind")
            == "canonical_actual_cost"
            and solver_settings.get("integrated_actual_cost_objective_requested")
            is True
        ),
        "actual_cost_structural_contract_applied": (
            solver_settings.get("integrated_actual_cost_contract_applied") is True
            and solver_settings.get(
                "actual_cost_objective_structural_contract_passed"
            )
            is True
        ),
        "vehicle_usage_cost_component_enabled": (
            flags.get("vehicle_usage_cost") is True
        ),
        "declared_unit_reaches_model": _numbers_equal(
            effective_unit, expected_unit
        ),
        "declared_unit_reaches_accounting": _numbers_equal(
            accounting_unit, expected_unit
        ),
        "one_day_vehicle_count_matches_vehicle_days": _numbers_equal(
            vehicle_count_used, used_vehicle_days
        ),
        "accounting_formula_reconciles": bool(
            formula_residual is not None
            and abs(formula_residual) <= 1.0e-6
        ),
        "semantics_is_fixed_vehicle_day_cost": (
            metadata.get("vehicle_usage_cost_semantics")
            == "fixed_vehicle_day_cost"
        ),
        "semantics_classified": (
            metadata.get("vehicle_usage_cost_semantics_classified") is True
        ),
        "semantics_research_eligible": (
            metadata.get("vehicle_usage_cost_semantics_research_eligible")
            is True
        ),
        "economic_claim_not_blocked_by_semantics": (
            metadata.get(
                "research_economic_claim_blocked_by_vehicle_usage_cost_semantics",
                False,
            )
            is False
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "applicable": True,
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "expected_unit_jpy_per_vehicle_day": expected_unit,
        "effective_unit_jpy_per_vehicle_day": effective_unit,
        "accounting_unit_jpy_per_vehicle_day": accounting_unit,
        "used_vehicle_day_count": used_vehicle_days,
        "summary_vehicle_count_used": vehicle_count_used,
        "accounting_vehicle_usage_cost_jpy": accounting_cost,
        "formula_residual_jpy": formula_residual,
        "effective_semantics": metadata.get("vehicle_usage_cost_semantics"),
        "semantics_classified": metadata.get(
            "vehicle_usage_cost_semantics_classified"
        ),
        "research_eligible": metadata.get(
            "vehicle_usage_cost_semantics_research_eligible"
        ),
        "integrated_primary_objective_kind": solver_settings.get(
            "integrated_primary_objective_kind"
        ),
    }


def _rolling_min_bev_soc_evidence(
    *,
    run_dir: Path,
    completeness: Mapping[str, Any],
    scenario_snapshot: Mapping[str, Any],
    rolling_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the minimum executed BEV SOC from hash-verified Rolling states.

    The day-ahead SOC CSV is intentionally excluded.  The evidence sequence is
    the active fleet's 00:00 cyclic target, the 23 persisted hourly state
    handoffs (01:00 through 23:00), and the same validated terminal target at
    24:00.  This keeps the reported minimum on the canonical executed Rolling
    trajectory while preserving the cyclic end-of-day boundary.
    """

    inventory = dict(scenario_snapshot.get("prepared_inventory") or {})
    vehicles = inventory.get("vehicles")
    if not isinstance(vehicles, list):
        raise ValueError("scenario snapshot has no prepared vehicle inventory")
    bev_parameters: dict[str, tuple[float, float]] = {}
    for raw_vehicle in vehicles:
        if not isinstance(raw_vehicle, Mapping):
            raise ValueError("prepared vehicle inventory contains a non-object")
        if str(raw_vehicle.get("type") or "").upper() != "BEV":
            continue
        vehicle_id = str(raw_vehicle.get("id") or "").strip()
        capacity = _finite_number(raw_vehicle.get("batteryKwh"))
        minimum_fraction = _finite_number(raw_vehicle.get("minSoc"))
        if (
            not vehicle_id
            or capacity <= 0.0
            or minimum_fraction < 0.0
            or minimum_fraction > 1.0
        ):
            raise ValueError("invalid BEV capacity or minimum SOC in snapshot")
        bev_parameters[vehicle_id] = (capacity, minimum_fraction)
    if not bev_parameters:
        raise ValueError("scenario snapshot contains no BEV parameters")

    steps = rolling_summary.get("steps")
    if not isinstance(steps, list) or len(steps) != 24:
        raise ValueError("Rolling summary must contain exactly 24 hourly steps")
    first_step = steps[0]
    if not isinstance(first_step, Mapping):
        raise ValueError("Rolling step 0 is not an object")
    terminal_targets = first_step.get(
        "bev_terminal_soc_target_kwh_by_vehicle"
    )
    if not isinstance(terminal_targets, Mapping):
        raise ValueError("Rolling summary has no active-BEV cyclic SOC target")
    active_ids = {str(vehicle_id) for vehicle_id in terminal_targets}
    if not active_ids.issubset(bev_parameters):
        raise ValueError("Rolling active BEV is missing from prepared inventory")

    source_paths = [
        "scenario_input_snapshot.json",
        "rolling_hourly_chain/rolling_chain_summary.json",
    ]
    samples: list[dict[str, Any]] = []
    _append_soc_samples(
        samples=samples,
        time_label="00:00",
        soc_by_vehicle=terminal_targets,
        active_ids=active_ids,
        bev_parameters=bev_parameters,
    )
    for step_index in range(23):
        step = steps[step_index]
        expected_time = f"{step_index:02d}:00"
        if (
            not isinstance(step, Mapping)
            or int(step.get("step_index", -1)) != step_index
            or step.get("current_time") != expected_time
        ):
            raise ValueError(f"Rolling step ordering mismatch at {step_index}")
        current_time = expected_time.replace(":", "")
        relative_path = (
            "rolling_hourly_chain/"
            f"step_{step_index:02d}_{current_time}/state_for_next_hour.json"
        )
        state = _read_json(run_dir / relative_path)
        semantics = dict(state.get("state_semantics") or {})
        if semantics.get("vehicle_soc") != "start_of_next_slot":
            raise ValueError(f"unsupported vehicle SOC semantics: {relative_path}")
        next_time = str(state.get("current_time") or "").strip()
        soc_by_vehicle = state.get("actual_vehicle_soc_kwh")
        if (
            next_time != f"{step_index + 1:02d}:00"
            or not isinstance(soc_by_vehicle, Mapping)
        ):
            raise ValueError(f"invalid Rolling SOC state: {relative_path}")
        _append_soc_samples(
            samples=samples,
            time_label=next_time,
            soc_by_vehicle=soc_by_vehicle,
            active_ids=active_ids,
            bev_parameters=bev_parameters,
        )
        source_paths.append(relative_path)
    _append_soc_samples(
        samples=samples,
        time_label="24:00",
        soc_by_vehicle=terminal_targets,
        active_ids=active_ids,
        bev_parameters=bev_parameters,
    )
    if not _artifact_snapshot_matches(
        run_dir=run_dir,
        completeness=completeness,
        relative_paths=tuple(source_paths),
    ):
        raise ValueError("Rolling SOC source artifact hash mismatch")

    source_hashes = {
        relative_path: sha256((run_dir / relative_path).read_bytes()).hexdigest()
        for relative_path in source_paths
    }
    minimum = (
        min(samples, key=lambda row: float(row["soc_percent"]))
        if samples
        else None
    )
    return {
        "schema_version": "rolling_min_bev_soc_evidence_v1",
        "source_semantics": "executed_hourly_state_handoffs_with_cyclic_boundaries",
        "source_artifacts_verified": True,
        "applicable": bool(active_ids),
        "active_bev_count": len(active_ids),
        "timepoint_count": 25,
        "sample_count": len(samples),
        "minimum_soc_kwh": minimum["soc_kwh"] if minimum else None,
        "minimum_soc_percent": minimum["soc_percent"] if minimum else None,
        "minimum_margin_above_vehicle_limit_percent": (
            minimum["margin_above_vehicle_limit_percent"]
            if minimum
            else None
        ),
        "vehicle_id": minimum["vehicle_id"] if minimum else None,
        "time": minimum["time"] if minimum else None,
        "battery_capacity_kwh": (
            minimum["battery_capacity_kwh"] if minimum else None
        ),
        "vehicle_minimum_soc_percent": (
            minimum["vehicle_minimum_soc_percent"] if minimum else None
        ),
        "source_artifact_sha256": source_hashes,
        "source_bundle_sha256": _canonical_hash(source_hashes),
    }


def _append_soc_samples(
    *,
    samples: list[dict[str, Any]],
    time_label: str,
    soc_by_vehicle: Mapping[str, Any],
    active_ids: set[str],
    bev_parameters: Mapping[str, tuple[float, float]],
) -> None:
    observed_ids = {str(vehicle_id) for vehicle_id in soc_by_vehicle}
    if observed_ids != active_ids:
        raise ValueError("Rolling SOC vehicle set differs from active BEV set")
    for vehicle_id in sorted(active_ids):
        soc_kwh = _finite_number(soc_by_vehicle[vehicle_id])
        capacity, minimum_fraction = bev_parameters[vehicle_id]
        if soc_kwh < -1.0e-6 or soc_kwh > capacity + 1.0e-6:
            raise ValueError("Rolling BEV SOC is outside physical capacity")
        soc_percent = 100.0 * soc_kwh / capacity
        minimum_percent = 100.0 * minimum_fraction
        samples.append(
            {
                "time": time_label,
                "vehicle_id": vehicle_id,
                "soc_kwh": soc_kwh,
                "soc_percent": soc_percent,
                "battery_capacity_kwh": capacity,
                "vehicle_minimum_soc_percent": minimum_percent,
                "margin_above_vehicle_limit_percent": (
                    soc_percent - minimum_percent
                ),
            }
        )


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"expected finite numeric value, got {value!r}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"expected finite numeric value, got {value!r}")
    return number


def _case_parameter_matches(
    *,
    case: Mapping[str, Any],
    parameters: Mapping[str, Any],
    economic_audit: Mapping[str, Any],
) -> bool:
    expected = dict(case.get("prepare_settings") or {})
    scenario = dict(parameters.get("effective_problem_scenario") or {})
    metadata = dict(parameters.get("effective_model_metadata") or {})
    family = str(case.get("family") or "")
    if family == "time_discretization":
        return scenario.get("timestep_min") == expected.get("timestep_min")
    if family == "trip_energy_sensitivity":
        return _numbers_equal(
            metadata.get("trip_energy_sensitivity_scale"),
            expected.get("trip_energy_sensitivity_scale"),
        )
    if family == "pv_supply_transition":
        scales = dict(metadata.get("pv_supply_scale_by_depot") or {})
        return bool(scales) and all(
            _numbers_equal(value, expected.get("pv_scale"))
            for value in scales.values()
        )
    if family == "route_band_ablation":
        request = dict(case.get("prepare_request_overrides") or {})
        return bool(
            metadata.get("fixed_route_band_mode")
            is expected.get("fixed_route_band_mode")
            and metadata.get("allow_intra_depot_route_swap")
            is request.get("allow_intra_depot_route_swap")
        )
    if family == "turnaround_buffer_sensitivity":
        return _numbers_equal(
            metadata.get("turnaround_buffer_min"),
            expected.get("turnaround_buffer_min"),
        )
    if family == "vehicle_day_cost_sensitivity":
        return bool(
            _numbers_equal(
                metadata.get("vehicle_usage_cost_jpy_per_used_bus"),
                expected.get("vehicle_usage_cost_jpy_per_used_bus"),
            )
            and metadata.get("objective_preset")
            == expected.get("objective_preset")
        )
    if family == "cost_co2_epsilon_frontier":
        return _numbers_equal(
            economic_audit.get("co2_emissions_cap_kg"),
            expected.get("co2_emissions_cap_kg"),
        )
    return False


def _declared_controls_match(
    *,
    case: Mapping[str, Any],
    parameters: Mapping[str, Any],
    economic_audit: Mapping[str, Any],
) -> bool:
    expected = dict(case.get("prepare_settings") or {})
    scenario = dict(parameters.get("effective_problem_scenario") or {})
    metadata = dict(parameters.get("effective_model_metadata") or {})
    semantics_by_depot = dict(
        economic_audit.get("pv_input_semantics_by_depot") or {}
    )
    frontend_request = dict(parameters.get("frontend_request") or {})
    effective_rolling = dict(
        frontend_request.get("effective_rolling_controls") or {}
    )
    expected_optimization = dict(
        case.get("optimization_request_overrides") or {}
    )
    checks = (
        scenario.get("objective_mode") == expected.get("objective_mode"),
        metadata.get("objective_preset") == expected.get("objective_preset"),
        metadata.get("trip_energy_model") == expected.get("trip_energy_model"),
        metadata.get("charging_power_model")
        == expected.get("charging_power_model"),
        metadata.get("charge_setup_minutes")
        == expected.get("charge_setup_minutes"),
        metadata.get("charge_teardown_minutes")
        == expected.get("charge_teardown_minutes"),
        metadata.get("minimum_charge_session_minutes")
        == expected.get("minimum_charge_session_minutes"),
        metadata.get("turnaround_buffer_min")
        == expected.get("turnaround_buffer_min"),
        metadata.get("allow_partial_service")
        is expected.get("allow_partial_service"),
        _successor_limits_match(
            metadata.get("milp_max_successors_per_trip"),
            expected.get("milp_max_successors_per_trip"),
        ),
        metadata.get("vehicle_usage_cost_semantics")
        == expected.get("vehicle_usage_cost_semantics"),
        effective_rolling.get("run_hourly_rolling")
        is expected_optimization.get("run_hourly_rolling"),
        effective_rolling.get("rolling_execution_minutes")
        == expected_optimization.get("rolling_execution_minutes"),
        bool(semantics_by_depot)
        and all(
            value == expected.get("pv_input_semantics")
            for value in semantics_by_depot.values()
        ),
    )
    return all(checks)


def _successor_limits_match(effective: Any, declared: Any) -> bool:
    """Compare successor limits while normalizing the unlimited sentinel.

    The Prepare contract uses ``None`` for a complete successor network while
    effective model metadata serializes the same setting as integer ``0``.
    Positive finite caps must still match exactly.
    """

    if _is_unlimited_successor_limit(effective):
        return _is_unlimited_successor_limit(declared)
    if _is_unlimited_successor_limit(declared):
        return False
    return _numbers_equal(effective, declared)


def _is_unlimited_successor_limit(value: Any) -> bool:
    if value is None:
        return True
    try:
        return int(value) == 0 and float(value) == 0.0
    except (TypeError, ValueError, OverflowError):
        return False


def _submitted_request_matches_provenance(
    *,
    submitted_request: Mapping[str, Any] | None,
    parameters: Mapping[str, Any],
) -> bool:
    """Verify that persisted raw request fields match the sent JSON body."""

    if submitted_request is None:
        return False
    frontend_request = dict(parameters.get("frontend_request") or {})
    recorded = frontend_request.get("raw_frontend_body")
    if not isinstance(recorded, Mapping):
        return False
    return all(
        key in recorded and _json_values_equal(recorded[key], value)
        for key, value in submitted_request.items()
    )


def _json_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        if isinstance(right, (int, float)) and not isinstance(right, bool):
            return _numbers_equal(left, right)
    return left == right


def rebuild_existing_sensitivity_audit(
    *,
    source_execution_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Re-audit immutable sensitivity runs without invoking Prepare or solve."""

    audit_builder_sha = _assert_clean_frozen_repository()
    source_execution_dir = Path(source_execution_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if source_execution_dir == output_dir:
        raise ValueError("re-audit output must differ from the source execution")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"re-audit output directory must be empty: {output_dir}"
        )

    matrix_path = source_execution_dir / "experiment_matrix.json"
    source_manifest_path = (
        source_execution_dir / "sensitivity_execution_manifest.json"
    )
    matrix = _read_json(matrix_path)
    source_manifest = _read_json(source_manifest_path)
    claimed_source_payload_hash = str(
        source_manifest.get("payload_sha256") or ""
    ).strip()
    unsigned_source_manifest = _json_copy(source_manifest)
    unsigned_source_manifest.pop("payload_sha256", None)
    if (
        not claimed_source_payload_hash
        or _canonical_hash(unsigned_source_manifest)
        != claimed_source_payload_hash
    ):
        raise ValueError("source sensitivity manifest payload hash mismatch")
    source_frozen_sha = str(source_manifest.get("frozen_git_sha") or "").strip()
    if not source_frozen_sha:
        raise ValueError("source sensitivity manifest has no frozen Git SHA")
    selected_ids = {
        str(value) for value in source_manifest.get("selected_case_ids") or []
    }
    if not selected_ids:
        raise ValueError("source sensitivity manifest has no selected cases")

    declared_cases = {
        str(case.get("case_id") or ""): case
        for case in matrix.get("cases") or []
    }
    unknown = sorted(selected_ids - set(declared_cases))
    if unknown:
        raise ValueError(
            "source manifest references undeclared cases: " + ", ".join(unknown)
        )
    original_outcomes = {
        str(row.get("case_id") or ""): dict(row)
        for row in source_manifest.get("outcomes") or []
    }
    missing_outcomes = sorted(selected_ids - set(original_outcomes))
    if missing_outcomes:
        raise ValueError(
            "source sensitivity manifest has no outcome for: "
            + ", ".join(missing_outcomes)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "experiment_matrix.json", matrix)
    _write_json(
        output_dir / "reaudit_source.json",
        {
            "schema_version": "thesis_sensitivity_reaudit_source_v1",
            "source_execution_dir": str(source_execution_dir),
            "source_execution_manifest_sha256": sha256(
                source_manifest_path.read_bytes()
            ).hexdigest(),
            "source_execution_payload_sha256": source_manifest.get(
                "payload_sha256"
            ),
            "source_frozen_git_sha": source_frozen_sha,
            "audit_builder_git_sha": audit_builder_sha,
        },
    )

    outcomes: list[dict[str, Any]] = []
    for case_id in sorted(selected_ids):
        case = declared_cases[case_id]
        source_case_dir = source_execution_dir / "cases" / case_id
        run_dir = source_case_dir / "source_run"
        terminal = _read_json(
            source_case_dir / "frontend_job_terminal_response.json"
        )
        submitted_request = _read_json(
            source_case_dir / "frontend_optimization_request.json"
        )
        outcome = _audit_case(
            case=case,
            run_dir=run_dir,
            terminal=terminal,
            submitted_optimization_request=submitted_request,
        )
        original = original_outcomes.get(case_id, {})
        settings = _read_json(run_dir / "solver_settings.json")
        source_git_matches = bool(
            settings.get("git_sha") == source_frozen_sha
            and settings.get("git_sha_after_solve") == source_frozen_sha
            and settings.get("git_dirty") is False
            and settings.get("git_dirty_after_solve") is False
            and settings.get("git_state_unchanged_during_solve") is True
        )
        checks = dict(outcome.get("checks") or {})
        checks["source_run_matches_original_frozen_git_sha"] = (
            source_git_matches
        )
        outcome["checks"] = checks
        outcome["failed_checks"] = [
            name for name, passed in checks.items() if not passed
        ]
        outcome["case_accepted"] = not outcome["failed_checks"]
        for key in (
            "prepared_input_id",
            "job_id",
            "started_at_utc",
            "completed_at_utc",
            "wall_time_seconds",
            "source_run_dir",
            "copied_run_dir",
            "git_sha_unchanged",
        ):
            if key in original:
                outcome[key] = original[key]
        outcome.update(
            {
                "reaudited_source_run_dir": str(run_dir),
                "source_frozen_git_sha": source_frozen_sha,
                "audit_builder_git_sha": audit_builder_sha,
            }
        )
        outcomes.append(outcome)
        case_output_dir = output_dir / "cases" / case_id
        case_output_dir.mkdir(parents=True, exist_ok=False)
        _write_json(case_output_dir / "case_execution_audit.json", outcome)

    return _write_manifest(
        output_dir=output_dir,
        matrix=matrix,
        frozen_sha=source_frozen_sha,
        audit_builder_sha=audit_builder_sha,
        selected_ids=selected_ids,
        outcomes=outcomes,
        source_execution_dir=source_execution_dir,
        source_execution_manifest_sha256=sha256(
            source_manifest_path.read_bytes()
        ).hexdigest(),
    )


def _write_manifest(
    *,
    output_dir: Path,
    matrix: Mapping[str, Any],
    frozen_sha: str,
    selected_ids: set[str],
    outcomes: list[dict[str, Any]],
    audit_builder_sha: str | None = None,
    source_execution_dir: Path | None = None,
    source_execution_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    declared_ids = {
        str(case.get("case_id") or "")
        for case in list(matrix.get("cases") or [])
    }
    completed_ids = {str(row.get("case_id") or "") for row in outcomes}
    all_selected_completed = completed_ids == selected_ids
    all_selected_accepted = all(
        row.get("case_accepted") is True for row in outcomes
    ) and len(outcomes) == len(selected_ids)
    control_fingerprints = {
        str(row.get("stable_control_fingerprint") or "")
        for row in outcomes
    }
    stable_controls_match = bool(
        control_fingerprints
        and "" not in control_fingerprints
        and len(control_fingerprints) == 1
    )
    full_matrix = selected_ids == declared_ids
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "frozen_git_sha": frozen_sha,
        "audit_builder_git_sha": audit_builder_sha or frozen_sha,
        "source_execution_dir": (
            str(source_execution_dir) if source_execution_dir else None
        ),
        "source_execution_manifest_sha256": (
            source_execution_manifest_sha256
        ),
        "matrix_schema_version": matrix.get("schema_version"),
        "selected_case_ids": sorted(selected_ids),
        "completed_case_ids": sorted(completed_ids),
        "all_selected_cases_completed": all_selected_completed,
        "all_selected_cases_accepted": all_selected_accepted,
        "stable_nonvaried_controls_match": stable_controls_match,
        "full_matrix_selected": full_matrix,
        "research_matrix_complete": bool(
            full_matrix
            and all_selected_completed
            and all_selected_accepted
            and stable_controls_match
        ),
        "status": (
            "READY_FOR_SENSITIVITY_ANALYSIS"
            if (
                full_matrix
                and all_selected_completed
                and all_selected_accepted
                and stable_controls_match
            )
            else "COMPLETED_SUBSET"
            if (
                all_selected_completed
                and all_selected_accepted
                and stable_controls_match
            )
            else "BLOCKED"
        ),
        "claim_scope": (
            "Sensitivity results only. This manifest does not upgrade any "
            "individual run or PV comparison pair beyond its own gates."
        ),
        "outcomes": outcomes,
    }
    unsigned = _json_copy(payload)
    payload["payload_sha256"] = _canonical_hash(unsigned)
    _write_json(output_dir / "sensitivity_execution_manifest.json", payload)
    _write_results_csv(output_dir / "sensitivity_results.csv", outcomes)
    return payload


def _write_results_csv(path: Path, outcomes: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(
                {column: outcome.get(column) for column in CSV_COLUMNS}
            )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required sensitivity artifact missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return dict(payload)


def _artifact_snapshot_matches(
    *,
    run_dir: Path,
    completeness: Mapping[str, Any],
    relative_paths: tuple[str, ...],
) -> bool:
    artifacts = dict(completeness.get("artifacts") or {})
    for relative_path in relative_paths:
        path = run_dir / relative_path
        record = dict(artifacts.get(relative_path) or {})
        if not path.is_file():
            return False
        if record.get("size_bytes") != path.stat().st_size:
            return False
        if str(record.get("sha256") or "") != sha256(
            path.read_bytes()
        ).hexdigest():
            return False
    return True


def _snapshotted_artifact_paths(
    relative_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Return files covered by the final completeness hash snapshot.

    ``artifact_completeness.json`` is the snapshot container written after
    the hashes are computed, so it cannot contain a stable hash of itself.
    Its schema/status are validated separately by ``_audit_case``.
    """

    return tuple(
        path
        for path in relative_paths
        if path != "artifact_completeness.json"
    )


def _stable_control_fingerprint(
    *,
    case: Mapping[str, Any],
    parameters: Mapping[str, Any],
    economic_audit: Mapping[str, Any],
    prepared_trip_input_sha256: str | None = None,
) -> str:
    dimensions = dict(parameters.get("canonical_input_dimensions") or {})
    scenario = dict(parameters.get("effective_problem_scenario") or {})
    metadata = dict(parameters.get("effective_model_metadata") or {})
    marginal = dict(economic_audit.get("marginal_cost_assumptions") or {})
    family = str(case.get("family") or "")
    trip_structure_control_sha256 = (
        prepared_trip_input_sha256
        if family == "trip_energy_sensitivity"
        else dimensions.get("trip_structure_input_sha256")
    )
    payload = {
        "schema_version": "sensitivity_stable_controls_v2_family_aware",
        "scenario_id": parameters.get("scenario_id"),
        "service_date": metadata.get("service_date"),
        "trip_ids_sha256": dimensions.get("trip_ids_sha256"),
        "trip_structure_control_sha256": trip_structure_control_sha256,
        "vehicle_ids_sha256": dimensions.get("vehicle_ids_sha256"),
        "vehicle_input_sha256": dimensions.get("vehicle_input_sha256"),
        "charger_input_sha256": dimensions.get("charger_input_sha256"),
        "vehicle_type_input_sha256": dimensions.get(
            "vehicle_type_input_sha256"
        ),
        "depot_input_sha256": dimensions.get("depot_input_sha256"),
        "price_value_set_sha256": dimensions.get("price_value_set_sha256"),
        "energy_asset_control_input_sha256": dimensions.get(
            "energy_asset_control_input_sha256"
        ),
        "objective_weights_sha256": dimensions.get(
            "objective_weights_sha256"
        ),
        "scenario_fleet_contract_hash": metadata.get(
            "scenario_fleet_contract_hash"
        ),
        "grid_price_jpy_per_kwh": marginal.get(
            "uniform_grid_price_jpy_per_kwh"
        ),
        "diesel_price_jpy_per_l": marginal.get("diesel_price_jpy_per_l"),
        "demand_charge_on_peak_yen_per_kw": scenario.get(
            "demand_charge_on_peak_yen_per_kw"
        ),
        "demand_charge_off_peak_yen_per_kw": scenario.get(
            "demand_charge_off_peak_yen_per_kw"
        ),
    }
    return _canonical_hash(payload)


def _verified_prepared_trip_input_hash(
    *,
    prepare_audit: Mapping[str, Any],
    input_validation: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """Return a verified, energy-scale-independent prepared-trip hash.

    New runs persist this compact hash before solving.  Legacy runs can be
    re-audited without re-solving by reading the already hash-verified
    prepared artifact.  The fallback is permitted only when the complete run
    input provenance validation passed, including prepared source size/hash.
    """

    declared = str(
        prepare_audit.get("prepared_trip_input_sha256") or ""
    ).strip()
    if declared:
        declared_count = prepare_audit.get("prepared_trip_count")
        expected_count = dict(
            prepare_audit.get("prepare_snapshot") or {}
        ).get("trip_count")
        if (
            prepare_audit.get("prepared_trip_input_schema")
            != PREPARED_TRIP_INPUT_SCHEMA
            or len(declared) != 64
            or any(character not in "0123456789abcdef" for character in declared)
            or declared_count is None
            or (
                expected_count is not None
                and int(declared_count) != int(expected_count)
            )
        ):
            return None, None
        return declared, "prepare_input_audit"

    checks = dict(input_validation.get("checks") or {})
    required_checks = (
        "prepared_source_exists",
        "prepared_source_size",
        "prepared_source_sha256",
    )
    if not (
        input_validation.get("valid") is True
        and all(checks.get(name) is True for name in required_checks)
    ):
        return None, None
    source_text = str(
        dict(input_validation.get("details") or {}).get(
            "prepared_source_path_checked"
        )
        or ""
    ).strip()
    if not source_text:
        return None, None
    prepared = _read_json(Path(source_text))
    trips = prepared.get("trips")
    if not isinstance(trips, list):
        return None, None
    expected_count = dict(prepare_audit.get("prepare_snapshot") or {}).get(
        "trip_count"
    )
    if expected_count is not None and len(trips) != int(expected_count):
        return None, None
    return _canonical_hash(trips), "verified_prepared_source_legacy_fallback"


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _canonical_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _numbers_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return abs(float(left) - float(right)) <= 1.0e-9
    except (TypeError, ValueError):
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-id")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--base-prepare-request", type=Path)
    parser.add_argument("--base-optimization-request", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--rebuild-existing-dir",
        type=Path,
        help=(
            "Re-audit an existing sensitivity execution without any HTTP or "
            "solver call; --output-dir must be a new directory."
        ),
    )
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=14_400.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.rebuild_existing_dir is not None:
        if args.case_id:
            parser.error("--case-id cannot be used with --rebuild-existing-dir")
        result = rebuild_existing_sensitivity_audit(
            source_execution_dir=args.rebuild_existing_dir,
            output_dir=args.output_dir,
        )
    else:
        missing = [
            flag
            for flag, value in (
                ("--scenario-id", args.scenario_id),
                ("--base-prepare-request", args.base_prepare_request),
                ("--base-optimization-request", args.base_optimization_request),
            )
            if value is None
        ]
        if missing:
            parser.error("normal execution requires " + ", ".join(missing))
        result = execute_sensitivity_matrix(
            scenario_id=args.scenario_id,
            base_url=args.base_url,
            base_prepare_request=_read_json(args.base_prepare_request),
            base_optimization_request=_read_json(
                args.base_optimization_request
            ),
            output_dir=args.output_dir,
            selected_case_ids=set(args.case_id) if args.case_id else None,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
