"""Plan a Fresh-Prepare small-oracle matrix without starting any solver."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {
    "SUNNY": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
    "RAIN": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
}
TRIP_COUNTS = (8, 12, 24)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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


def build_plan(args: argparse.Namespace, *, adapter_sha: str) -> dict[str, Any]:
    prepare_request = json.loads(Path(args.prepare_request).read_text(encoding="utf-8"))
    template = json.loads(Path(args.optimization_template).read_text(encoding="utf-8"))
    scenario_code = args.scenario_code.upper()
    counts = tuple(int(value) for value in args.trip_counts)
    if scenario_code not in SCENARIOS or any(value not in TRIP_COUNTS for value in counts):
        raise ValueError("scenario must be SUNNY/RAIN and trip counts must be 8/12/24")
    core = {
        "scenario_code": scenario_code,
        "scenario_id": SCENARIOS[scenario_code],
        "fresh_prepare_count": 1,
        "fresh_prepare_request": prepare_request,
        "fresh_prepare_request_sha256": _sha256(prepare_request),
        "optimization_template_sha256": _sha256(template),
        "prepared_input_contract": "one new Prepared ID shared by every case",
        "old_prepared_inputs_allowed": False,
        "trip_counts": list(counts),
        "formulations": ["P3_DEPLOYED", "P4_SCALAR"],
        "p3_scalar_support": "P3_SCALAR_UNSUPPORTED",
        "case_process_contract": "one independent process per formulation and trip count",
        "expected_case_outputs": [
            str(Path(args.output_dir) / f"trips_{count:02d}" / f"{formulation}.json")
            for count in counts for formulation in ("P3_DEPLOYED", "P4_SCALAR")
        ],
    }
    return {
        "schema_version": "small_oracle_matrix_plan_v1",
        "mode": "PLAN_ONLY_NO_PREPARE_NO_SOLVE",
        "adapter_commit_sha": adapter_sha,
        **core,
        "plan_sha256": _sha256(core),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true", required=True)
    parser.add_argument("--scenario-code", choices=tuple(SCENARIOS), required=True)
    parser.add_argument("--prepare-request", type=Path, required=True)
    parser.add_argument("--optimization-template", type=Path, required=True)
    parser.add_argument("--trip-counts", nargs="+", default=list(TRIP_COUNTS), type=int)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    sha, dirty = _git_state()
    if dirty:
        raise RuntimeError("plan requires a clean adapter SHA")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("output directory must be absent or empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_plan(args, adapter_sha=sha)
    (args.output_dir / "run_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
