"""Plan and validate the November RAIN 2x2 candidate-profile experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/research/november_2026/rain_candidate_profiles_v2.json"
EXPECTED_PROFILES = {"BASE", "RANGE_ONLY", "BUDGET_ONLY", "FULL_EXPANDED"}
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
        unexpected = set(profile) - allowlist
        if unexpected:
            raise ValueError(f"{name} contains non-allowlisted fields: {sorted(unexpected)}")
        expected_total = (
            int(profile["stage1_time_limit_seconds"])
            + int(profile["stage1_stage2_candidate_limit"])
            * int(profile["stage2_time_limit_seconds"])
            + 24 * int(profile["stage2_time_limit_seconds"])
            + 300
        )
        if int(profile["time_limit_seconds"]) != expected_total:
            raise ValueError(f"{name} total time limit violates the preregistered formula")
        if int(profile["stage2_time_limit_seconds"]) != 30:
            raise ValueError(f"{name} must keep Stage 2 at 30 seconds")
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
        "adapter_commit_sha", "complete_request_sha", "profile_definition_sha",
        "advisor_decision_date", "advisor_approved_threshold", "approved_profiles",
    )
    missing = [key for key in required if manifest.get(key) in (None, "", [])]
    if missing:
        raise RuntimeError(f"execute blocked by advisor fields: {missing}")
    if set(manifest.get("approved_profiles") or ()) != EXPECTED_PROFILES:
        raise RuntimeError("execute requires approval for the exact four-profile matrix")
    expected_values = {
        "adapter_commit_sha": adapter_sha,
        "profile_definition_sha": profile_sha,
        "complete_request_sha": complete_request_sha,
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
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "run_plan.json", plan)
    prepare_request = dict(plan["common_prepare_request"])
    _write_json(output_dir / "common_prepare_request.json", prepare_request)
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
        "scenario_id": scenario_id, "prepared_input_id": prepared_id,
        "prepare_response_sha256": hashlib.sha256(prepare_raw.encode()).hexdigest(),
    })
    for profile_name, raw_request in dict(plan["requested_requests"]).items():
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
        run_dir = Path(run_dir_text)
        _copy_run_contents(run_dir, case_dir)
        _validate_effective_controls(case_dir, request)
        _write_json(case_dir / "source_artifact_hashes.json", _artifact_hashes(case_dir))
    _write_json(output_dir / "run_manifest.json", {
        "schema_version": "rain_candidate_run_manifest_v1",
        "prepared_input_id": prepared_id, "artifact_hashes": _artifact_hashes(output_dir),
    })


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
        "allowed_overlay_fields": sorted(allowlist),
        "requested_requests": requests,
        "effective_controls": {
            name: {key: request[key] for key in sorted(allowlist)}
            for name, request in requests.items()
        },
        "planned_artifacts": [
            "run_plan.json", "profile_definition.json", "common_prepare_request.json",
            "common_optimization_request.json", "requested_request.json",
            "effective_controls.json", "prepared_manifest.json", "run_manifest.json",
            "candidate_inventory.json", "selected_candidate.json",
            "physical_schedule_validation.json", "rolling_chain_summary.json",
            "executed_day_accounting.json", "source_artifact_hashes.json",
        ],
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
