"""Plan and validate the November RAIN 2x2 candidate-profile experiment."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from tools.november_2026.normalize_rain_profile_result import (
    normalize_profile_result,
    write_profile_result,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PLANNING_SHA = "f183c85d3287dc11026448bd6f26ade6c0155197"
CANONICAL_REFERENCE_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/research/november_2026/rain_candidate_profiles_v3.json"
EXPECTED_PROFILES = {"BASE", "RANGE_ONLY", "BUDGET_ONLY", "FULL_EXPANDED"}
PROFILE_ORDER = ("BASE", "RANGE_ONLY", "BUDGET_ONLY", "FULL_EXPANDED")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RANGE_VECTOR = {
    "stage1_stage2_candidate_limit", "stage1_composition_search_radius",
    "stage1_bev_frontier_min_count", "stage1_bev_frontier_max_count",
}
_BUDGET_VECTOR = {
    "time_limit_seconds", "stage1_time_limit_seconds",
    "stage1_bev_frontier_target_time_limit_seconds",
}
_REQUEST_TO_EFFECTIVE = {
    "time_limit_seconds": "time_limit_sec",
    "stage1_time_limit_seconds": "stage1_time_limit_sec",
    "stage2_time_limit_seconds": "stage2_time_limit_sec",
    "stage1_stage2_candidate_limit": "stage1_stage2_candidate_limit",
    "stage1_composition_search_radius": "stage1_composition_search_radius",
    "stage1_bev_frontier_enabled": "stage1_bev_frontier_enabled",
    "stage1_bev_frontier_min_count": "stage1_bev_frontier_min_count",
    "stage1_bev_frontier_max_count": "stage1_bev_frontier_max_count",
    "stage1_bev_frontier_target_time_limit_seconds": "stage1_bev_frontier_target_time_limit_sec",
}


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_profiles(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowlist = set(payload.get("allowed_overlay_fields") or ())
    profiles = dict(payload.get("profiles") or {})
    if set(profiles) != EXPECTED_PROFILES:
        raise ValueError("profile file must contain exactly the preregistered 2x2 matrix")
    for name, profile in profiles.items():
        missing = allowlist - set(profile)
        if missing:
            raise ValueError(f"{name} omits allowlisted fields: {sorted(missing)}")
        unexpected = set(profile) - allowlist
        if unexpected:
            raise ValueError(f"{name} contains non-allowlisted fields: {sorted(unexpected)}")
        if int(profile["stage2_time_limit_seconds"]) != 30:
            raise ValueError(f"{name} must keep Stage 2 at 30 seconds")
    comparison_fields = allowlist
    base = profiles["BASE"]
    range_only = profiles["RANGE_ONLY"]
    budget_only = profiles["BUDGET_ONLY"]
    full = profiles["FULL_EXPANDED"]
    for field in comparison_fields:
        if field in _RANGE_VECTOR:
            if budget_only[field] != base[field] or full[field] != range_only[field]:
                raise ValueError(f"broken 2x2 range vector at {field}")
        elif field in _BUDGET_VECTOR:
            if range_only[field] != base[field] or full[field] != budget_only[field]:
                raise ValueError(f"broken 2x2 budget vector at {field}")
        elif not (base[field] == range_only[field] == budget_only[field] == full[field]):
            raise ValueError(f"non-factor profile field drift at {field}")
    return payload


def apply_profile(common_request: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    request = dict(common_request)
    request.update(profile)
    return request


def validate_nonprofile_drift(
    requests: Mapping[str, Mapping[str, Any]], allowlist: set[str]
) -> None:
    baseline = dict(requests["BASE"])
    for name, request in requests.items():
        drift = {
            key for key in set(baseline) | set(request)
            if key not in allowlist and baseline.get(key) != request.get(key)
        }
        if drift:
            raise ValueError(f"{name} has forbidden non-profile drift: {sorted(drift)}")


def require_execution_approval(
    manifest: Mapping[str, Any], *, adapter_sha: str | None = None,
    profile_sha: str | None = None, complete_request_sha: str | None = None,
) -> None:
    required = (
        "schema_version", "experiment_id", "experiment_family", "planning_sha",
        "adapter_sha", "canonical_reference_sha", "scenario_ids", "request_sha",
        "profile_definition_sha", "approved_run_list", "advisor_name",
        "advisor_decision_date", "approval_statement", "approved_threshold",
        "threshold_unit", "solver_budget", "wall_budget", "disk_budget",
        "stop_rules", "claim_boundary", "forbidden_claims",
    )
    missing = [key for key in required if manifest.get(key) in (None, "", [])]
    if missing:
        raise RuntimeError(f"execute blocked by advisor fields: {missing}")
    if set(manifest.get("approved_run_list") or ()) != EXPECTED_PROFILES:
        raise RuntimeError("execute requires approval for the exact four-profile matrix")
    if manifest.get("scenario_ids") != ["b23fd26c-1233-4c73-bb9e-bdb8b1584760"]:
        raise RuntimeError("execute requires the exact preregistered RAIN scenario")
    if manifest.get("schema_version") != "rain_2x2_approval_v1":
        raise RuntimeError("invalid preregistration schema_version")
    if manifest.get("experiment_family") != "rain_2x2":
        raise RuntimeError("invalid experiment_family")
    for key in ("planning_sha", "adapter_sha", "canonical_reference_sha"):
        if not _SHA40_RE.fullmatch(str(manifest.get(key) or "")):
            raise RuntimeError(f"invalid 40-hex SHA: {key}")
    if manifest.get("planning_sha") != PLANNING_SHA:
        raise RuntimeError("planning SHA does not match the audited base")
    if manifest.get("canonical_reference_sha") != CANONICAL_REFERENCE_SHA:
        raise RuntimeError("canonical reference SHA does not match bb0c005")
    for key in ("profile_definition_sha", "request_sha"):
        if not _SHA256_RE.fullmatch(str(manifest.get(key) or "")):
            raise RuntimeError(f"invalid SHA-256: {key}")
    try:
        date.fromisoformat(str(manifest["advisor_decision_date"]))
    except (TypeError, ValueError):
        raise RuntimeError("advisor_decision_date must be ISO YYYY-MM-DD") from None
    threshold = manifest.get("approved_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RuntimeError("advisor threshold must be numeric")
    if not math.isfinite(float(threshold)) or float(threshold) < 0.0:
        raise RuntimeError("advisor threshold must be finite and nonnegative")
    if manifest.get("threshold_unit") != "percent":
        raise RuntimeError("advisor threshold unit must be percent")
    for key in ("solver_budget", "wall_budget", "disk_budget"):
        if not isinstance(manifest.get(key), Mapping) or not manifest[key]:
            raise RuntimeError(f"{key} must be a non-empty object")
        numeric_values = [
            float(value) for value in manifest[key].values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if not numeric_values or any(
            not math.isfinite(value) or value <= 0.0 for value in numeric_values
        ):
            raise RuntimeError(f"{key} must contain finite positive numeric limits")
    expected_values = {
        "adapter_sha": adapter_sha,
        "profile_definition_sha": profile_sha,
        "request_sha": complete_request_sha,
    }
    mismatches = {
        key: {"manifest": manifest.get(key), "expected": expected}
        for key, expected in expected_values.items()
        if expected is not None and manifest.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"execute manifest hashes do not match: {mismatches}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _require_clean_expected_sha(expected_sha: str) -> None:
    sha, dirty = _git_state()
    if dirty:
        raise RuntimeError("execution worktree became dirty")
    if sha != expected_sha:
        raise RuntimeError(f"execution Git SHA drifted: expected={expected_sha}, actual={sha}")


def _write_progress(
    output_dir: Path,
    *,
    status: str,
    completed_profiles: list[str],
    code_sha: str,
    failed_profile: str | None = None,
    failure_reason: str | None = None,
) -> None:
    payload = {
        "schema_version": "rain_candidate_progress_v1",
        "status": status,
        "completed_profiles": list(completed_profiles),
        "failed_profile": failed_profile,
        "failure_reason": failure_reason,
        "code_sha": code_sha,
        "artifact_hashes": _artifact_hashes(output_dir),
    }
    _write_json(output_dir / "progress_manifest.json", payload)


def _write_interrupted_profile_result(
    case_dir: Path, *, profile_name: str, plan: Mapping[str, Any], reason: str,
) -> None:
    path = case_dir / "profile_result_v1.json"
    if path.exists():
        return
    _write_json(path, {
        "schema_version": "rain_profile_result_v1",
        "status": "INTERRUPTED",
        "profile_name": profile_name,
        "scenario_id": plan.get("scenario_id"),
        "prepared_input_id": None,
        "code_sha": plan.get("adapter_commit_sha"),
        "requested_controls": dict(plan.get("requested_requests") or {}).get(
            profile_name
        ),
        "termination_reason": reason,
        "candidate_counts": None,
        "candidates": [],
        "selected_candidate": None,
        "source_artifact_hashes": _artifact_hashes(case_dir),
    })


def _validate_effective_controls(case_dir: Path, requested: Mapping[str, Any]) -> dict[str, Any]:
    parameters_path = case_dir / "optimization_parameters.json"
    if not parameters_path.is_file():
        raise FileNotFoundError(f"missing effective-control artifact: {parameters_path}")
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    effective_config = dict(parameters.get("effective_optimization_config") or {})
    effective = {
        request_key: effective_config.get(effective_key)
        for request_key, effective_key in _REQUEST_TO_EFFECTIVE.items()
    }
    mismatches = {
        key: {"requested": requested.get(key), "effective": effective.get(key)}
        for key in _REQUEST_TO_EFFECTIVE
        if requested.get(key) != effective.get(key)
    }
    payload = {
        "schema_version": "rain_requested_effective_controls_v1",
        "requested": {key: requested.get(key) for key in _REQUEST_TO_EFFECTIVE},
        "effective": effective,
        "matched": not mismatches,
        "mismatches": mismatches,
    }
    _write_json(case_dir / "effective_controls.json", payload)
    if mismatches:
        raise RuntimeError(f"requested/effective profile controls differ: {mismatches}")
    return payload


def execute_approved_plan(
    *, base_url: str, output_dir: Path, plan: Mapping[str, Any],
    timeout_seconds: float, poll_interval_seconds: float,
) -> None:
    """Use existing HTTP/poll/copy helpers after a separately approved gate."""

    from scripts.run_frontend_controlled_pv_pair import (  # local: plan-only imports no HTTP
        HttpJsonClient, _copy_run_contents, _poll_job,
    )

    client = HttpJsonClient(base_url)
    scenario_id = str(plan["scenario_id"])
    expected_sha = str(plan["adapter_commit_sha"])
    _require_clean_expected_sha(expected_sha)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty")
    _write_json(output_dir / "run_plan.json", plan)
    _write_json(output_dir / "profile_definition.json", plan["profile_definition"])
    prepare_request = dict(plan["common_prepare_request"])
    _write_json(output_dir / "common_prepare_request.json", prepare_request)
    _write_json(
        output_dir / "common_optimization_request.json",
        plan["common_optimization_request"],
    )
    completed_profiles: list[str] = []
    active_profile: str | None = None
    fixed_hashes_reference: dict[str, Any] | None = None
    _write_progress(
        output_dir, status="IN_PROGRESS", completed_profiles=completed_profiles,
        code_sha=expected_sha,
    )
    try:
        prepare_response, prepare_raw = client.request_json(
            "POST", f"/api/scenarios/{scenario_id}/simulation/prepare",
            prepare_request, timeout_seconds=timeout_seconds,
        )
        _write_json(output_dir / "prepare_response.json", prepare_response)
        if prepare_response.get("ready") is not True:
            raise RuntimeError("Fresh Prepare did not return ready=true")
        prepared_id = str(prepare_response.get("preparedInputId") or "").strip()
        if not prepared_id:
            raise RuntimeError("Fresh Prepare returned no Prepared ID")
        _write_json(output_dir / "prepared_manifest.json", {
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_id,
            "prepare_response_sha256": hashlib.sha256(prepare_raw.encode()).hexdigest(),
        })
        for profile_name in PROFILE_ORDER:
            active_profile = profile_name
            _require_clean_expected_sha(expected_sha)
            raw_request = dict(plan["requested_requests"])[profile_name]
            case_dir = output_dir / profile_name
            case_dir.mkdir(parents=False, exist_ok=False)
            request = {**dict(raw_request), "prepared_input_id": prepared_id}
            _write_json(case_dir / "requested_request.json", request)
            submitted, _ = client.request_json(
                "POST", f"/api/scenarios/{scenario_id}/run-optimization",
                request, timeout_seconds=timeout_seconds,
            )
            job_id = str(submitted.get("job_id") or submitted.get("jobId") or "").strip()
            if not job_id:
                raise RuntimeError(f"{profile_name} submission returned no job ID")
            terminal, _ = _poll_job(
                client=client, job_id=job_id, timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds, log=[],
            )
            _write_json(case_dir / "frontend_job_terminal_response.json", terminal)
            if str(terminal.get("status") or "") != "completed":
                raise RuntimeError(f"{profile_name} ended with status={terminal.get('status')}")
            run_dir_text = str(dict(terminal.get("metadata") or {}).get("run_dir") or "").strip()
            if not run_dir_text:
                raise RuntimeError(f"{profile_name} terminal response has no run_dir")
            _copy_run_contents(Path(run_dir_text), case_dir)
            _validate_effective_controls(case_dir, request)
            result = normalize_profile_result(
                case_dir,
                profile_name=profile_name,
                requested_controls=request,
                expected_code_sha=expected_sha,
            )
            write_profile_result(case_dir / "profile_result_v1.json", result)
            if result["status"] != "ACCEPTED":
                raise RuntimeError(f"{profile_name} failed formal profile_result gates")
            fixed_hashes = dict(result["canonical_fixed_input_hashes"])
            if fixed_hashes_reference is None:
                fixed_hashes_reference = fixed_hashes
            elif fixed_hashes != fixed_hashes_reference:
                raise RuntimeError(f"{profile_name} canonical fixed-input hashes drifted")
            if result["prepared_input_id"] != prepared_id:
                raise RuntimeError(f"{profile_name} did not use the shared Prepared ID")
            _write_json(case_dir / "source_artifact_hashes.json", _artifact_hashes(case_dir))
            completed_profiles.append(profile_name)
            _require_clean_expected_sha(expected_sha)
            _write_progress(
                output_dir, status="IN_PROGRESS", completed_profiles=completed_profiles,
                code_sha=expected_sha,
            )
        _require_clean_expected_sha(expected_sha)
        prepared_source_sha = (fixed_hashes_reference or {}).get("prepared_input_sha256")
        if not _SHA256_RE.fullmatch(str(prepared_source_sha or "")):
            raise RuntimeError("completed profiles did not expose a valid prepared source SHA-256")
        _write_json(output_dir / "prepared_manifest.json", {
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_id,
            "prepare_response_sha256": hashlib.sha256(prepare_raw.encode()).hexdigest(),
            "prepared_payload_sha256": canonical_sha256(prepare_response),
            "prepared_source_sha256": prepared_source_sha,
            "canonical_fixed_input_hashes": fixed_hashes_reference,
        })
        _write_json(output_dir / "run_manifest.json", {
            "schema_version": "rain_candidate_run_manifest_v1",
            "prepared_input_id": prepared_id,
            "code_sha": expected_sha,
            "completed_profiles": completed_profiles,
        })
        _write_progress(
            output_dir, status="COMPLETED", completed_profiles=completed_profiles,
            code_sha=expected_sha,
        )
        _write_json(output_dir / "artifact_hashes.json", _artifact_hashes(output_dir))
    except BaseException as exc:
        failure_reason = f"{type(exc).__name__}: {exc}"
        if active_profile is not None:
            case_dir = output_dir / active_profile
            if case_dir.is_dir():
                _write_interrupted_profile_result(
                    case_dir, profile_name=active_profile, plan=plan,
                    reason=failure_reason,
                )
        _write_progress(
            output_dir, status="INTERRUPTED", completed_profiles=completed_profiles,
            failed_profile=active_profile, failure_reason=failure_reason,
            code_sha=expected_sha,
        )
        _write_json(output_dir / "artifact_hashes.json", _artifact_hashes(output_dir))
        raise


def build_plan(
    *, common_prepare: Mapping[str, Any], common_optimization: Mapping[str, Any],
    profile_payload: Mapping[str, Any], adapter_sha: str,
) -> dict[str, Any]:
    allowlist = set(profile_payload["allowed_overlay_fields"])
    requests = {
        name: apply_profile(common_optimization, profile)
        for name, profile in profile_payload["profiles"].items()
    }
    validate_nonprofile_drift(requests, allowlist)
    profile_sha = canonical_sha256(profile_payload)
    complete_request_sha = canonical_sha256({
        "prepare": common_prepare,
        "requested_requests": requests,
    })
    planned_artifacts = [
        "run_plan.json", "profile_definition.json", "common_prepare_request.json",
        "common_optimization_request.json", "prepare_response.json",
        "prepared_manifest.json", "run_manifest.json", "progress_manifest.json",
        "artifact_hashes.json",
    ]
    profile_artifacts = (
        "requested_request.json", "frontend_job_terminal_response.json",
        "effective_controls.json", "profile_result_v1.json", "source_artifact_hashes.json",
        "stage1_stage2_candidate_evaluation.json", "physical_schedule_validation.json",
        "rolling_hourly_chain/rolling_chain_summary.json",
        "rolling_hourly_chain/executed_day_accounting.json",
        "final_cost_reconciliation.json", "summary.json", "optimization_parameters.json",
        "code_provenance.json", "input_audit.json",
    )
    planned_artifacts.extend(
        f"{profile}/{artifact}"
        for profile in PROFILE_ORDER
        for artifact in profile_artifacts
    )
    return {
        "schema_version": "rain_candidate_run_v1",
        "mode": "PLAN_ONLY_NO_HTTP_NO_PREPARE_NO_SOLVE",
        "adapter_commit_sha": adapter_sha,
        "profile_definition_sha": profile_sha,
        "complete_request_sha": complete_request_sha,
        "scenario_id": profile_payload["scenario_id"],
        "fresh_prepare_count": 1,
        "prepared_input_sharing": "one new Prepared ID shared by all four profiles",
        "common_prepare_request": dict(common_prepare),
        "common_prepare_request_sha256": canonical_sha256(common_prepare),
        "common_optimization_request": dict(common_optimization),
        "profile_definition": dict(profile_payload),
        "allowed_overlay_fields": sorted(allowlist),
        "requested_requests": requests,
        "effective_controls": {
            name: {key: request[key] for key in sorted(allowlist)}
            for name, request in requests.items()
        },
        "planned_artifacts": planned_artifacts,
    }


def _git_state() -> tuple[str, bool]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
                         capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                                check=True, capture_output=True, text=True).stdout.strip())
    return sha, dirty


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan-only", action="store_true")
    modes.add_argument("--validate-inputs-only", action="store_true")
    modes.add_argument("--execute", action="store_true")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--prepare-request", type=Path, required=True)
    parser.add_argument("--optimization-request", type=Path, required=True)
    parser.add_argument("--preregistration-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    sha, dirty = _git_state()
    if dirty:
        raise RuntimeError("adapter SHA is dirty")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty")
    profiles = load_profiles(args.profiles)
    prepare = json.loads(args.prepare_request.read_text(encoding="utf-8"))
    optimization = json.loads(args.optimization_request.read_text(encoding="utf-8"))
    plan = build_plan(common_prepare=prepare, common_optimization=optimization,
                      profile_payload=profiles, adapter_sha=sha)
    if args.validate_inputs_only:
        plan["mode"] = "VALIDATE_INPUTS_ONLY"
        if args.preregistration_manifest is None:
            raise RuntimeError("validate-inputs-only requires --preregistration-manifest")
        manifest = json.loads(args.preregistration_manifest.read_text(encoding="utf-8"))
        require_execution_approval(
            manifest, adapter_sha=sha,
            profile_sha=plan["profile_definition_sha"],
            complete_request_sha=plan["complete_request_sha"],
        )
    if args.execute:
        if args.preregistration_manifest is None:
            raise RuntimeError("execute requires --preregistration-manifest")
        manifest = json.loads(args.preregistration_manifest.read_text(encoding="utf-8"))
        require_execution_approval(
            manifest, adapter_sha=sha,
            profile_sha=plan["profile_definition_sha"],
            complete_request_sha=plan["complete_request_sha"],
        )
        plan["mode"] = "EXECUTE"
        execute_approved_plan(
            base_url=args.base_url, output_dir=args.output_dir, plan=plan,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "run_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "profile_definition.json").write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
