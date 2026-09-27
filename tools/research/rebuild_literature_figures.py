"""Rebuild figures from a terminal worker's evidence copy; never restart a solve."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.optimization_run.literature_figures import generate_literature_figure_bundle
from bff.services.optimization_run.artifact_completeness import _validate_literature_artifact_integrity
from tools.cluster.atomic_file import replace_bytes


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def rebuild(run_dir: Path, worker_state: Path, output_dir: Path) -> dict:
    run_dir, worker_state, output_dir = (p.resolve() for p in (run_dir, worker_state, output_dir))
    if output_dir.exists() or output_dir.is_relative_to(run_dir):
        raise ValueError("Output must be a new directory outside the original run")
    if not run_dir.is_relative_to(worker_state.parent):
        raise ValueError("Run must belong to the collected worker evidence directory")
    state = read(worker_state)
    if state.get("state") not in {"FAILED", "COMPLETED"}:
        raise ValueError("Only terminal worker evidence can be rebuilt")
    if read(run_dir / "final_cost_reconciliation.json").get("status") != "OK":
        raise ValueError("Original final cost reconciliation must be OK")
    # Keep the failed attempt and all source bytes intact, including its original verdict.
    before = inventory(run_dir)
    state_hash = sha(worker_state)
    shutil.copytree(run_dir, output_dir)
    if inventory(output_dir) != before:
        raise ValueError("Evidence copy differs from original")
    manifest = generate_literature_figure_bundle(output_dir)
    errors: list[str] = []
    _validate_literature_artifact_integrity(
        run_dir=output_dir,
        manifest_path=output_dir / "graph/literature_figures/manifest.json",
        manifest=manifest, content_errors=errors,
    )
    if errors:
        raise ValueError("Rebuilt figure integrity failed: " + "; ".join(errors))
    if inventory(run_dir) != before or sha(worker_state) != state_hash:
        raise ValueError("Original evidence changed during rebuild")
    receipt = {
        "status": "FIGURES_REBUILT_ONLY", "new_solver_run": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_run": str(run_dir), "output_run": str(output_dir),
        "source_worker_state": str(worker_state), "source_worker_state_sha256": state_hash,
        "original_job_id": state.get("id"), "original_worker_state": state.get("state"),
        "original_provenance": state.get("provenance"),
        "source_files_sha256": before, "source_unchanged": True,
        "rebuild_code_sha256": {
            path.relative_to(ROOT).as_posix(): sha(path) for path in (
                Path(__file__), ROOT / "bff/services/optimization_run/literature_figures.py"
            )
        },
        "figure_count": manifest["figure_count"],
        "figure_integrity_verified": True,
        "research_submission_ready": manifest["research_submission_ready"],
        "campaign_status_changed": False,
        "limitations": ["Rebuilt figures do not turn a failed worker attempt into a completed job.",
                        "Original acceptance verdicts are preserved; full campaign audit remains separate."],
    }
    replace_bytes(output_dir / "figure_rebuild_receipt.json",
                  json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--worker-state", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = rebuild(args.run_dir, args.worker_state, args.output_dir)
    print(json.dumps({k: result[k] for k in ("status", "figure_count", "source_unchanged", "output_run")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
