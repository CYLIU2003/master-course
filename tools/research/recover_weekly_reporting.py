"""Recover terminal reporting-only failures without changing the original attempt.

Consumes an audited figure rebuild and original collected ZIP. Writes a new
directory; never submits, changes queue state, or invokes a solver.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.optimization_run.artifact_completeness import audit_frontend_run_artifacts
from tools.cluster.audit_batch import require
from tools.cluster.batch import canonical, digest, validate_batch
from tools.research.rebuild_literature_figures import inventory, read, sha
from tools.research.weekly_collection import export_executed_week
from tools.research.weekly_results import write_json


def figure_file(name: str) -> bool:
    return name == "graph/manifest.json" or name.startswith("graph/literature_figures/")


def verify_source(case: Path, rebuilt: Path, *, repaired_manifest: bool = False) -> dict:
    prepared, spec = read(case / "prepared.json"), read(case / "batch.json")
    state = read(case / "state/batch-state.json")
    validate_batch(spec, allow_formal=True)
    require(state["batch_sha256"] == digest(canonical(spec)), "Batch binding changed")
    require(len(spec["tasks"]) == 1, "Expected one representative week")
    task = spec["tasks"][0]
    require(task["task_id"] == prepared["week"], "Prepared week differs from task")
    item = state["tasks"][task["task_id"]]
    require(item["state"] == "FAILED", "Recovery only accepts terminal failed attempts")
    require(item["artifacts"] == item["job_id"] + ".zip", "Unexpected artifact filename")
    archive_path = case / "state" / item["artifacts"]
    require(archive_path.resolve().parent == (case / "state").resolve(), "Archive escapes case")
    require(sha(archive_path) == item["collected_sha256"], "Original archive hash changed")
    receipt = read(rebuilt / "figure_rebuild_receipt.json")
    require(receipt["original_job_id"] == item["job_id"] and receipt["original_worker_state"] == "FAILED",
            "Figure recovery belongs to a different attempt")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP members")
        require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                    and "\\" not in n and ":" not in n for n in names), "Unsafe ZIP member")
        manifest_bytes, bundle_bytes, worker_bytes = (archive.read(n) for n in ("manifest.json", "bundle.json", "state.json"))
        manifest, bundle, worker = (json.loads(b) for b in (manifest_bytes, bundle_bytes, worker_bytes))
        require(manifest["id"] == worker["id"] == item["job_id"], "Attempt identity mismatch")
        require(worker["state"] == "FAILED" and digest(worker_bytes) == receipt["source_worker_state_sha256"],
                "Original worker receipt changed")
        require("LiteratureFigureError: Conflicting grid CO2 factors" in str(worker.get("result", {})),
                "Failure is not the supported figure-finalization failure")
        require(digest(manifest_bytes) == worker["manifest_sha256"], "Worker manifest mismatch")
        require(digest(bundle_bytes) == manifest["bundle_sha256"], "Worker bundle mismatch")
        require(manifest["git"] == worker["provenance"]["git"] == prepared["source_git"]
                == {"sha": spec["git_sha"], "dirty": False}, "Frozen source mismatch")
        require(manifest["source_digest"] == worker["provenance"]["source_digest"], "Worker source digest mismatch")
        submission, kwargs = task["submission"], bundle["kwargs"]
        require(submission["scenario_id"] == prepared["scenario_id"] == kwargs["scenario_id"]
                == bundle["scenario"]["meta"]["id"], "Scenario mismatch")
        require(kwargs["prepared_input_id"] == prepared["prepared_input_id"], "Prepared ID mismatch")
        for key, value in submission["request"].items():
            if key in kwargs:
                require(kwargs[key] == value, "Request differs: " + key)
        raw = base64.b64decode(bundle["prepared_base64"], validate=True)
        require(digest(raw) == prepared["prepared_sha256"], "Prepared bytes differ")
        accounts = [n for n in names if n.endswith("/rolling_hourly_chain/executed_day_accounting.json")]
        require(len(accounts) == 1, "Expected one executed week")
        prefix = accounts[0].removesuffix("rolling_hourly_chain/executed_day_accounting.json")
        original = {n[len(prefix):]: digest(archive.read(n)) for n in names if n.startswith(prefix) and not n.endswith("/")}
        require(original == receipt["source_files_sha256"], "Rebuild source inventory differs from ZIP")
        current = inventory(rebuilt)
        for name, expected in original.items():
            if name == "run_manifest.json" and repaired_manifest:
                old_manifest = json.loads(archive.read(prefix + name))
                new_manifest = read(rebuilt / name)
                old_manifest.pop("files", None)
                new_manifest.pop("files", None)
                require(new_manifest == old_manifest, "Run verdict changed during reporting recovery")
            elif not figure_file(name):
                require(current.get(name) == expected, "Non-figure evidence changed: " + name)
        require(all(n in original or figure_file(n) or n == "figure_rebuild_receipt.json" for n in current),
                "Unexpected added evidence outside figure rebuild")
        profile = submission["request"].get("execution_profile", "existing_solver_v1")
        usage = read(rebuilt / "solver_usage.json")
        require(usage["execution_profile"] == manifest["execution_profile"] == profile
                and usage["counts_complete"] is True, "Solver usage profile mismatch")
        if profile == "alns_no_gurobi_v1":
            require(all(usage[k] == 0 for k in ("environment_starts", "model_creations", "optimize_calls", "forbidden_calls")),
                    "Forbidden solver use")
    return {"prepared": prepared, "item": item, "inputs": json.loads(raw), "rebuilt_inventory": current,
            "source_archive_sha256": item["collected_sha256"], "original_claim": read(rebuilt / "research_claim_scope.json")}


def recover(case: Path, rebuilt: Path, output: Path) -> dict:
    case, rebuilt, output = (p.resolve() for p in (case, rebuilt, output))
    require(not output.exists() and not output.is_relative_to(case) and not output.is_relative_to(rebuilt),
            "Output must be new and outside source evidence")
    verified = verify_source(case, rebuilt)
    target = output / "run"
    shutil.copytree(rebuilt, target)
    require(inventory(target) == verified["rebuilt_inventory"], "Copy differs from source")
    # The failed finalizer stopped before registering the complete file list.
    # Update only that inventory in the copy; preserve failure/acceptance fields.
    manifest = read(target / "run_manifest.json")
    manifest["files"] = sorted(inventory(target))
    write_json(target / "run_manifest.json", manifest)
    audit = audit_frontend_run_artifacts(target, research_run=True, require_rolling=True)
    write_json(output / "artifact-audit.json", audit)
    require(audit["accepted"], "Rebuilt artifact audit failed; inspect artifact-audit.json")
    claim = verified["original_claim"]
    require(claim.get("physical_feasibility_claim_eligible") is True, "Original physical gate failed")
    task_audit = {**claim, "task_id": verified["prepared"]["week"], "job_id": verified["item"]["job_id"],
                  "original_worker_state": "FAILED", "collection_verified": True,
                  "collection_basis": "reporting_recovery_original_archive_verified"}
    export_audit = {"unverified": 0, "tasks": [task_audit]}
    row = export_executed_week(verified["prepared"], verified["item"], output, export_audit,
        read(target / "rolling_hourly_chain/executed_day_accounting.json"),
        read(target / "rolling_hourly_chain/executed_plan.json"),
        read(target / "physical_schedule_validation.json"), verified["inputs"])
    require(inventory(rebuilt) == verified["rebuilt_inventory"], "Source changed during recovery")
    require(sha(case / "state" / verified["item"]["artifacts"]) == verified["source_archive_sha256"], "Original ZIP changed")
    record = {"status": "REPORTING_RECOVERED_CONDITIONAL_EVALUATION", "new_solver_run": False,
              "original_worker_state": "FAILED", "original_claim": claim, "case": str(case),
              "prepared_sha256": verified["prepared"]["prepared_sha256"],
              "source_archive_sha256": verified["source_archive_sha256"], "job_id": verified["item"]["job_id"],
              "week": row["week"], "solver_git_sha": row["git_sha"], "total_cost_jpy": row["total_cost"],
              "recovery_code_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in (
                  Path(__file__), ROOT / "tools/research/weekly_collection.py",
                  ROOT / "bff/services/optimization_run/artifact_completeness.py")},
              "required_artifacts_verified": audit["verified_artifact_count"], "campaign_status_changed": False,
              "limitations": ["Original failed worker and research verdicts are retained.",
                              "Recorded physical gates and accounting are rechecked; no new solver or physical model run."],
              "files_sha256": inventory(output)}
    write_json(output / "recovery.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--rebuilt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = recover(args.case, args.rebuilt, args.output)
    print(json.dumps({k: result[k] for k in ("status", "week", "total_cost_jpy", "required_artifacts_verified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
