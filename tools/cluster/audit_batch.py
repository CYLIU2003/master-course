"""Audit collected batch ZIPs offline without granting research approval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.cluster.batch import canonical, digest, save, validate_batch


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def audit_task(spec: dict, task: dict, item: dict, directory: Path) -> dict:
    """Check receipt bindings, required files and recorded solver policy."""
    require(item.get("state") == "COMPLETED", "Task did not complete")
    filename = item.get("artifacts", "")
    require(filename == item.get("job_id", "") + ".zip", "Unexpected artifact filename")
    target = directory / filename
    require(target.resolve().parent == directory.resolve(), "Artifact escapes batch directory")
    with target.open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == item.get("collected_sha256"),
                "Collected archive SHA-256 mismatch")
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate archive members")
        require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                    and "\\" not in n and ":" not in n for n in names), "Unsafe archive member")
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        receipt = json.loads(archive.read("state.json"))
        require(manifest["id"] == receipt["id"] == item["job_id"], "Attempt identity mismatch")
        require(receipt["state"] == "COMPLETED", "Worker did not complete")
        require(digest(manifest_bytes) == receipt["manifest_sha256"], "Manifest binding mismatch")
        bundle_bytes = archive.read("bundle.json")
        require(digest(bundle_bytes) == manifest["bundle_sha256"], "Input bundle mismatch")
        bundle = json.loads(bundle_bytes)
        submission = task["submission"]
        requested = submission["request"]
        kwargs = bundle["kwargs"]
        expected_prepared = requested.get("prepared_input_id") or item.get("prepared_input_id")
        require(bundle["scenario"].get("meta", {}).get("id") == submission["scenario_id"]
                and kwargs.get("scenario_id") == submission["scenario_id"], "Batch scenario mismatch")
        require(expected_prepared and kwargs.get("prepared_input_id") == expected_prepared,
                "Batch prepared input mismatch")
        for key, value in requested.items():
            if key in kwargs:
                require(kwargs[key] == value, "Batch request mismatch: " + key)
        require(manifest["git"] == {"sha": spec["git_sha"], "dirty": False}, "Frozen Git mismatch")
        require(receipt["provenance"]["git"] == manifest["git"], "Worker Git mismatch")
        require(receipt["provenance"]["source_digest"] == manifest["source_digest"], "Worker source mismatch")
        profile = task["submission"]["request"].get("execution_profile", "existing_solver_v1")
        require(manifest["execution_profile"] == profile, "Execution profile mismatch")
        paths = [n for n in names if n.endswith("/artifact_completeness.json")]
        require(len(paths) == 1, "Expected one reporting finalizer result")
        prefix = paths[0].removesuffix("artifact_completeness.json")
        completeness = json.loads(archive.read(paths[0]))
        require(completeness["accepted"] is True, "Required artifact contract failed")
        required = completeness["required_artifacts"]
        require(len(required) == completeness["required_artifact_count"] == completeness["verified_artifact_count"],
                "Required artifact counts differ")
        for name in required:
            record = completeness["artifacts"][name]
            data = archive.read(prefix + name)
            require(len(data) == record["size_bytes"] and digest(data) == record["sha256"],
                    "Required artifact content mismatch: " + name)
        usage = json.loads(archive.read(prefix + "solver_usage.json"))
        require(usage["execution_profile"] == profile and usage["counts_complete"] is True,
                "Solver usage is incomplete or has a different profile")
        if profile == "alns_no_gurobi_v1":
            require(all(usage[key] == 0 for key in ("environment_starts", "model_creations", "optimize_calls", "forbidden_calls")),
                    "No-Gurobi execution used a forbidden operation")
        claim = json.loads(archive.read(prefix + "research_claim_scope.json"))
        return {"collection_verified": True, "git_sha": spec["git_sha"],
                "source_digest": manifest["source_digest"], "solver_usage": usage,
                "required_artifacts_verified": len(required),
                "worker_message": receipt["result"].get("message"),
                "teacher_release_status": claim.get("teacher_release_status", "UNKNOWN"),
                "research_blocking_reasons": claim.get("teacher_release_failed_checks", []),
                "physical_feasibility_claim_eligible": claim.get("physical_feasibility_claim_eligible", False)}


def audit_batch(spec: dict, state: dict, directory: Path) -> dict:
    # Reading evidence does not authorize a formal run; no execution is possible here.
    validate_batch(spec, allow_formal=True)
    require(state["batch_sha256"] == digest(canonical(spec)), "Batch manifest changed")
    results = []
    for task in spec["tasks"]:
        item = state["tasks"].get(task["task_id"], {})
        row = {"task_id": task["task_id"], "job_id": item.get("job_id"), "worker_id": item.get("worker_id")}
        try:
            row.update(audit_task(spec, task, item, directory))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            row.update(collection_verified=False, error=str(exc))
        results.append(row)
    verified = sum(row["collection_verified"] for row in results)
    return {"schema_version": 1, "batch_id": spec["batch_id"], "total": len(results),
            "collection_verified": verified, "unverified": len(results) - verified,
            "excluded_tasks": 0, "research_approval": "NOT_GRANTED_BY_CLUSTER",
            "tasks": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_batch(json.loads(args.manifest.read_bytes()),
                         json.loads((args.state_dir / "batch-state.json").read_bytes()), args.state_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, report)
    print(json.dumps({key: value for key, value in report.items() if key != "tasks"}))
    return 0 if report["unverified"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
