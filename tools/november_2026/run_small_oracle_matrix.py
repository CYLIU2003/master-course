"""Plan, validate, or execute a signed small-oracle matrix."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {
    "SUNNY": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
    "RAIN": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
}
TRIP_COUNTS = (8, 12, 24)
FORMULATIONS = ("P3_ALIGNED_REFERENCE", "P4_SCALAR_EXACT_REFERENCE")
PLANNING_SHA = "f183c85d3287dc11026448bd6f26ade6c0155197"
CANONICAL_REFERENCE_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "artifact_manifest.json"
    }


def _git_state() -> tuple[str, bool]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip())
    return sha, dirty


def _require_clean_sha(expected_sha: str) -> None:
    sha, dirty = _git_state()
    if dirty:
        raise RuntimeError("oracle execution worktree became dirty")
    if sha != expected_sha:
        raise RuntimeError(f"oracle execution SHA drift: expected={expected_sha}, actual={sha}")


def build_plan(args: argparse.Namespace, *, adapter_sha: str) -> dict[str, Any]:
    prepare_request = json.loads(Path(args.prepare_request).read_text(encoding="utf-8"))
    template = json.loads(Path(args.optimization_template).read_text(encoding="utf-8"))
    if not isinstance(prepare_request, dict) or not isinstance(template, dict):
        raise ValueError("Prepare request and optimization template must be JSON objects")
    scenario_code = args.scenario_code.upper()
    counts = tuple(int(value) for value in args.trip_counts)
    if scenario_code not in SCENARIOS or not counts or any(
        value not in TRIP_COUNTS for value in counts
    ) or len(set(counts)) != len(counts):
        raise ValueError("scenario must be SUNNY/RAIN and unique trip counts must be 8/12/24")
    case_definition = {
        "scenario_code": scenario_code,
        "scenario_id": SCENARIOS[scenario_code],
        "trip_counts": list(counts),
        "formulations": list(FORMULATIONS),
        "depot_id": args.depot_id,
        "service_id": args.service_id,
        "time_limit_sec": args.time_limit_sec,
        "random_seed": args.random_seed,
        "gurobi_threads": args.gurobi_threads,
        "vehicles_per_type": args.vehicles_per_type,
    }
    core = {
        **case_definition,
        "fresh_prepare_count": 1,
        "fresh_prepare_request": prepare_request,
        "fresh_prepare_request_sha256": _sha256(prepare_request),
        "optimization_template": template,
        "optimization_template_sha256": _sha256(template),
        "complete_request_sha256": _sha256({
            "prepare": prepare_request,
            "optimization_template": template,
        }),
        "case_definition_sha256": _sha256(case_definition),
        "prepared_input_contract": "one new Prepared ID shared by every case",
        "old_prepared_inputs_allowed": False,
        "p3_scalar_support": "P3_SCALAR_UNSUPPORTED",
        "comparison_name": "phase3_aligned_subset_to_scalar_integrated_reference_distance",
        "case_process_contract": "one independent process per trip count",
        "expected_case_outputs": [
            str(Path(args.output_dir) / f"trips_{count:02d}" / "oracle_result.json")
            for count in counts
        ],
    }
    return {
        "schema_version": "small_oracle_matrix_plan_v2",
        "mode": "PLAN_ONLY_NO_PREPARE_NO_SOLVE",
        "adapter_commit_sha": adapter_sha,
        **core,
        "plan_sha256": _sha256(core),
    }


def require_execution_approval(
    manifest: Mapping[str, Any], *, plan: Mapping[str, Any]
) -> None:
    required = (
        "schema_version", "experiment_id", "experiment_family", "planning_sha",
        "adapter_sha", "canonical_reference_sha", "scenario_ids", "request_sha",
        "case_definition_sha", "approved_run_list", "advisor_name",
        "advisor_decision_date", "approval_statement", "approved_threshold",
        "threshold_unit", "solver_budget", "wall_budget", "disk_budget",
        "stop_rules", "claim_boundary", "forbidden_claims",
    )
    missing = [key for key in required if manifest.get(key) in (None, "", [])]
    if missing:
        raise RuntimeError(f"execute blocked by incomplete small-oracle signoff: {missing}")
    if manifest.get("schema_version") != "small_oracle_approval_v1":
        raise RuntimeError("invalid small-oracle approval schema")
    if manifest.get("experiment_family") != "small_oracle":
        raise RuntimeError("approval is not for the small-oracle family")
    if manifest.get("scenario_ids") != [plan["scenario_id"]]:
        raise RuntimeError("approved scenario does not match plan")
    expected_runs = [f"{plan['scenario_code']}:{count}" for count in plan["trip_counts"]]
    if manifest.get("approved_run_list") != expected_runs:
        raise RuntimeError("approved run list does not match the exact matrix")
    expected_hashes = {
        "adapter_sha": plan["adapter_commit_sha"],
        "request_sha": plan["complete_request_sha256"],
        "case_definition_sha": plan["case_definition_sha256"],
    }
    for key, expected in expected_hashes.items():
        if manifest.get(key) != expected:
            raise RuntimeError(f"small-oracle approval hash mismatch: {key}")
    for key in ("planning_sha", "adapter_sha", "canonical_reference_sha"):
        if not _SHA40_RE.fullmatch(str(manifest.get(key) or "")):
            raise RuntimeError(f"invalid 40-hex SHA: {key}")
    if manifest.get("planning_sha") != PLANNING_SHA:
        raise RuntimeError("planning SHA does not match the audited base")
    if manifest.get("canonical_reference_sha") != CANONICAL_REFERENCE_SHA:
        raise RuntimeError("canonical reference SHA does not match bb0c005")
    for key in ("request_sha", "case_definition_sha"):
        if not _SHA256_RE.fullmatch(str(manifest.get(key) or "")):
            raise RuntimeError(f"invalid SHA-256: {key}")
    try:
        date.fromisoformat(str(manifest["advisor_decision_date"]))
    except (TypeError, ValueError):
        raise RuntimeError("advisor_decision_date must be ISO YYYY-MM-DD") from None
    threshold = manifest.get("approved_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RuntimeError("approved threshold must be numeric")
    if not math.isfinite(float(threshold)) or float(threshold) < 0:
        raise RuntimeError("approved threshold must be finite and nonnegative")
    if manifest.get("threshold_unit") != "percent":
        raise RuntimeError("threshold unit must be percent")
    for key in ("solver_budget", "wall_budget", "disk_budget"):
        value = manifest.get(key)
        if not isinstance(value, Mapping) or not value:
            raise RuntimeError(f"{key} must be a non-empty object")
        numbers = [
            float(item) for item in value.values()
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        if not numbers or any(not math.isfinite(item) or item <= 0 for item in numbers):
            raise RuntimeError(f"{key} must contain finite positive numeric limits")


def validate_inputs(args: argparse.Namespace, plan: Mapping[str, Any]) -> None:
    if int(args.gurobi_threads) < 1 or int(args.time_limit_sec) < 1:
        raise ValueError("solver controls must be positive")
    if args.approval_manifest:
        approval = json.loads(args.approval_manifest.read_text(encoding="utf-8"))
        require_execution_approval(approval, plan=plan)


def execute_approved_plan(
    *, plan: Mapping[str, Any], output_dir: Path, base_url: str,
    timeout_seconds: float,
    process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Execute only after signoff; tests replace every external boundary."""

    from scripts.run_frontend_controlled_pv_pair import HttpJsonClient

    expected_sha = str(plan["adapter_commit_sha"])
    _require_clean_sha(expected_sha)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty")
    _write_json(output_dir / "run_plan.json", plan)
    progress = {
        "schema_version": "small_oracle_progress_v1", "status": "IN_PROGRESS",
        "completed_trip_counts": [], "active_trip_count": None, "failure": None,
    }
    _write_json(output_dir / "progress_manifest.json", progress)
    try:
        client = HttpJsonClient(base_url)
        response, raw = client.request_json(
            "POST", f"/api/scenarios/{plan['scenario_id']}/simulation/prepare",
            dict(plan["fresh_prepare_request"]), timeout_seconds=timeout_seconds,
        )
        if response.get("ready") is not True or not response.get("preparedInputId"):
            raise RuntimeError("Fresh Prepare did not return ready=true and Prepared ID")
        prepared_id = str(response["preparedInputId"])
        _write_json(output_dir / "prepare_response.json", response)
        _write_json(output_dir / "prepared_manifest.json", {
            "scenario_id": plan["scenario_id"], "prepared_input_id": prepared_id,
            "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        })
        for count in plan["trip_counts"]:
            _require_clean_sha(expected_sha)
            progress["active_trip_count"] = count
            _write_json(output_dir / "progress_manifest.json", progress)
            case_dir = output_dir / f"trips_{int(count):02d}"
            case_dir.mkdir(parents=False, exist_ok=False)
            result_path = case_dir / "oracle_result.json"
            command = [
                sys.executable, str(REPO_ROOT / "scripts/audit_small_integrated_weather_milp.py"),
                "--scenario-id", str(plan["scenario_id"]),
                "--prepared-input-id", prepared_id, "--output", str(result_path),
                "--depot-id", str(plan["depot_id"]), "--service-id", str(plan["service_id"]),
                "--trip-count", str(count), "--time-limit-sec", str(plan["time_limit_sec"]),
                "--vehicles-per-type", str(plan["vehicles_per_type"]),
                "--random-seed", str(plan["random_seed"]),
                "--gurobi-threads", str(plan["gurobi_threads"]), "--skip-five-minute",
            ]
            _write_json(case_dir / "command.json", command)
            completed = process_runner(
                command, cwd=REPO_ROOT, capture_output=True, text=True,
                timeout=timeout_seconds, check=False,
            )
            (case_dir / "stdout.log").write_text(completed.stdout or "", encoding="utf-8")
            (case_dir / "stderr.log").write_text(completed.stderr or "", encoding="utf-8")
            if completed.returncode != 0 or not result_path.is_file():
                raise RuntimeError(f"oracle trip-count {count} failed: {completed.returncode}")
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if payload.get("prepared_input_id") != prepared_id or payload.get("trip_count") != count:
                raise RuntimeError(f"oracle trip-count {count} output identity mismatch")
            progress["completed_trip_counts"].append(count)
            progress["active_trip_count"] = None
            _write_json(output_dir / "progress_manifest.json", progress)
        _require_clean_sha(expected_sha)
        progress["status"] = "COMPLETED"
        _write_json(output_dir / "progress_manifest.json", progress)
        _write_json(output_dir / "complete_run_manifest.json", {
            "schema_version": "small_oracle_complete_run_v1", "code_sha": expected_sha,
            "prepared_input_id": prepared_id,
            "completed_trip_counts": progress["completed_trip_counts"],
        })
        _write_json(output_dir / "artifact_manifest.json", _artifact_hashes(output_dir))
    except BaseException as exc:
        progress["status"] = "INTERRUPTED"
        progress["failure"] = f"{type(exc).__name__}: {exc}"
        _write_json(output_dir / "progress_manifest.json", progress)
        _write_json(output_dir / "artifact_manifest.json", _artifact_hashes(output_dir))
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--validate-inputs-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--scenario-code", choices=tuple(SCENARIOS), required=True)
    parser.add_argument("--prepare-request", type=Path, required=True)
    parser.add_argument("--optimization-template", type=Path, required=True)
    parser.add_argument("--trip-counts", nargs="+", default=list(TRIP_COUNTS), type=int)
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--time-limit-sec", type=int, default=300)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--gurobi-threads", type=int, default=1)
    parser.add_argument("--vehicles-per-type", type=int, default=5)
    parser.add_argument("--approval-manifest", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--job-timeout-seconds", type=float, default=14400.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sha, dirty = _git_state()
    if dirty:
        raise RuntimeError("small-oracle package requires a clean adapter SHA")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty")
    plan = build_plan(args, adapter_sha=sha)
    validate_inputs(args, plan)
    if args.execute:
        if not args.approval_manifest:
            raise RuntimeError("--execute requires --approval-manifest")
        execute_approved_plan(
            plan=plan, output_dir=args.output_dir, base_url=args.base_url,
            timeout_seconds=args.job_timeout_seconds,
        )
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan["mode"] = (
        "VALIDATE_INPUTS_ONLY_NO_PREPARE_NO_SOLVE"
        if args.validate_inputs_only else "PLAN_ONLY_NO_PREPARE_NO_SOLVE"
    )
    _write_json(args.output_dir / "run_plan.json", plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
