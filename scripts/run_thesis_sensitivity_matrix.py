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


SCHEMA_VERSION = "thesis_sensitivity_execution_v1"
CSV_COLUMNS = (
    "case_id",
    "family",
    "case_accepted",
    "prepared_input_id",
    "job_id",
    "solver_status",
    "mip_gap_target_met",
    "solve_time_seconds",
    "trip_count_served",
    "trip_count_unserved",
    "vehicle_count_used",
    "bev_trip_count",
    "ice_trip_count",
    "total_cost_jpy",
    "total_co2_kg",
    "grid_import_kwh",
    "pv_generated_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "bess_to_bus_kwh",
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
            selected_ids=selected_ids,
            outcomes=outcomes,
        )

    return _write_manifest(
        output_dir=output_dir,
        matrix=matrix,
        frozen_sha=frozen_sha,
        selected_ids=selected_ids,
        outcomes=outcomes,
    )


def _audit_case(
    *,
    case: Mapping[str, Any],
    run_dir: Path,
    terminal: Mapping[str, Any],
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
            "rolling_hourly_chain/executed_day_accounting.json",
        )
    }
    input_validation = validate_run_input_provenance(
        run_dir,
        verify_prepared_source=True,
    )
    settings = required["solver_settings.json"]
    physical = required["physical_schedule_validation.json"]
    completeness = required["artifact_completeness.json"]
    accounting = required[
        "rolling_hourly_chain/executed_day_accounting.json"
    ]
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
        "declared_case_parameter_effective": parameter_match,
        "declared_common_controls_effective": declared_controls_match,
    }
    failed = [name for name, passed in checks.items() if not passed]
    summary = required["summary.json"]
    costs = dict(accounting.get("cost_breakdown") or {})
    trip_types = dict(summary.get("trip_count_by_type") or {})
    return {
        "case_id": case_id,
        "family": case.get("family"),
        "case_accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "stable_control_fingerprint": _stable_control_fingerprint(
            parameters=required["optimization_parameters.json"],
            economic_audit=required["assignment_economic_audit.json"],
        ),
        "input_validation": input_validation,
        "solver_status": summary.get("solver_status"),
        "mip_gap_target_met": summary.get("mip_gap_target_met"),
        "solve_time_seconds": summary.get("solve_time_seconds"),
        "trip_count_served": summary.get("trip_count_served"),
        "trip_count_unserved": summary.get("trip_count_unserved"),
        "vehicle_count_used": summary.get("vehicle_count_used"),
        "bev_trip_count": trip_types.get("BEV", 0),
        "ice_trip_count": trip_types.get("ICE", 0),
        "total_cost_jpy": costs.get("total_cost"),
        "total_co2_kg": costs.get("total_co2_kg"),
        "grid_import_kwh": costs.get("grid_import_kwh"),
        "pv_generated_kwh": costs.get("pv_generated_kwh"),
        "pv_to_bus_kwh": costs.get("pv_to_bus_kwh"),
        "pv_to_bess_kwh": costs.get("pv_to_bess_kwh"),
        "bess_to_bus_kwh": costs.get("bess_to_bus_kwh"),
    }


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
        metadata.get("allow_partial_service")
        is expected.get("allow_partial_service"),
        metadata.get("milp_max_successors_per_trip")
        is expected.get("milp_max_successors_per_trip"),
        metadata.get("vehicle_usage_cost_semantics")
        == expected.get("vehicle_usage_cost_semantics"),
        bool(semantics_by_depot)
        and all(
            value == expected.get("pv_input_semantics")
            for value in semantics_by_depot.values()
        ),
    )
    return all(checks)


def _write_manifest(
    *,
    output_dir: Path,
    matrix: Mapping[str, Any],
    frozen_sha: str,
    selected_ids: set[str],
    outcomes: list[dict[str, Any]],
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
    parameters: Mapping[str, Any],
    economic_audit: Mapping[str, Any],
) -> str:
    dimensions = dict(parameters.get("canonical_input_dimensions") or {})
    scenario = dict(parameters.get("effective_problem_scenario") or {})
    metadata = dict(parameters.get("effective_model_metadata") or {})
    marginal = dict(economic_audit.get("marginal_cost_assumptions") or {})
    payload = {
        "scenario_id": parameters.get("scenario_id"),
        "service_date": metadata.get("service_date"),
        "trip_ids_sha256": dimensions.get("trip_ids_sha256"),
        "trip_structure_input_sha256": dimensions.get(
            "trip_structure_input_sha256"
        ),
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
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--base-prepare-request", type=Path, required=True)
    parser.add_argument("--base-optimization-request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=14_400.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
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
