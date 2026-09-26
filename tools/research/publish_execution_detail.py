"""Publish detailed campaign progress without modifying or submitting calculations."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import ClusterConfig, canonical, digest
from bff.services.cluster.store import ControllerLock
from bff.services.cluster.transport import ssh_command
from tools.cluster.atomic_file import replace_bytes
from tools.cluster.batch import Client
from tools.cluster.release import quote_ps
from tools.research import execution_detail
from tools.research.publish_campaign_progress import _safe_message
from tools.research.weekly_operator import load_operation, snapshot


def probe(worker, job: dict) -> dict:
    directory = str(Path(worker.workspace) / job["id"])
    if worker.transport == "local":
        result = execution_detail.inspect_attempt(Path(directory))
    else:
        program = Path(execution_detail.__file__).read_text(encoding="utf-8")
        program += "\nprint(json.dumps(inspect_attempt(Path(" + repr(directory) + ")),ensure_ascii=True))\n"
        # Keep the Windows command line small; read-only code travels over stdin.
        command = "& " + quote_ps(worker.python) + " -X utf8 -; exit $LASTEXITCODE"
        encoded = base64.b64encode(command.encode("utf-16le")).decode()
        response = subprocess.run(ssh_command(worker, "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded),
                                  input=program.encode("utf-8"), capture_output=True, timeout=25)
        if response.returncode:
            raise RuntimeError("REMOTE_DETAIL_READ_FAILED")
        result = json.loads(response.stdout)
    if result["job_id"] != job["id"] or result["manifest_sha256"] != digest(canonical(job["manifest"])):
        raise ValueError("PROGRESS_ATTEMPT_BINDING_MISMATCH")
    return result


def campaign_rows(operation_path: Path) -> list[dict]:
    operation, settings, campaign = load_operation(operation_path)
    client = Client(f"http://127.0.0.1:{settings['port']}")
    report = snapshot(operation, settings, campaign, client)
    jobs = {j["id"]: j for j in client.request("/api/cluster/jobs")}
    fleet = client.request("/api/cluster/workers")
    license_state = {k: fleet.get(k) for k in ("global_gurobi_slots", "external_gurobi_slots", "reserved_gurobi_slots", "cooling_gurobi_slots")}
    workers = {w.id: w for w in ClusterConfig.model_validate_json(Path(settings["config"]).read_text()).workers}
    def one(case):
        job = jobs.get(case["job_id"], {})
        manifest = job.get("manifest", {})
        detail = {**case, "parent": operation["parent"], "campaign": campaign.name,
                  "solver_git_sha": operation["git_sha"], "observed_at": report["observed_at_utc"],
                  "connection": report["connection"], "started_at": job.get("created_at"),
                  "expected_windows": manifest.get("summary", {}).get("expected_rolling_windows"),
                  "trip_count": manifest.get("summary", {}).get("trip_count"),
                  "memory_budget_gib": (manifest.get("resource_requirements") or {}).get("task_memory_budget_gib"),
                  "checkpoint": job.get("execution_progress"), "execution": None, "license": license_state}
        failure = (job.get("result") or {}).get("result") or {}
        detail["error"] = _safe_message(case.get("error") or failure.get("error"))
        cache = campaign / case["week"] / "operations/execution-detail.json"
        try:
            cached = execution_detail.read_object(cache)
        except (OSError, ValueError):
            cached = {}
        fingerprint = digest(canonical(manifest))
        if cached.get("job_id") == job.get("id") and cached.get("manifest_sha256") == fingerprint:
            detail["execution"] = cached
        terminal = job.get("state") in {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED"}
        should_probe = job.get("state") in {"RUNNING", "COLLECTING", "LOST"} or (terminal and not (detail["execution"] or {}).get("terminal_snapshot"))
        if should_probe and job.get("worker_id") in workers:
            try:
                detail["execution"] = probe(workers[job["worker_id"]], job)
                detail["execution"]["terminal_snapshot"] = terminal
                replace_bytes(cache, canonical(detail["execution"]))
                if (detail["execution"].get("memory") or {}).get("status") == "OBSERVED":
                    sample = {key: detail["execution"].get(key) for key in (
                        "job_id", "manifest_sha256", "observed_at", "phase", "rolling_saved", "memory",
                    )}
                    # One controller-owned reader writes each attempt's history.
                    # These observations never modify the frozen worker artifacts.
                    with (cache.parent / "process-memory.jsonl").open("ab") as stream:
                        stream.write(canonical(sample) + b"\n")
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
                detail["probe_error"] = type(exc).__name__ + ": 詳細の読取に失敗（計算終了とは判定しません）"
        # Do not publish private paths or SSH configuration.
        detail.pop("directory", None)
        return detail
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(one, report["cases"]))


def collect_snapshot(paths: list[Path], previous: dict) -> dict:
    """Keep the last evidence on controller failure, explicitly disconnected."""
    rows, errors = [], []
    for path in paths:
        operation_id = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
        try:
            rows.extend({**row, "operation_id": operation_id} for row in campaign_rows(path))
        except (OSError, ValueError, KeyError) as exc:
            errors.append({"operation": path.name, "error": type(exc).__name__})
            rows.extend({**row, "connection": "UNKNOWN"} for row in previous.get("cases", [])
                        if row.get("operation_id") == operation_id)
    return {"schema_version": "execution_detail_v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "cases": rows, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    lock = ControllerLock(args.output.parent / ".execution-detail-lock")
    try:
        try:
            previous = execution_detail.read_object(args.output)
        except (OSError, ValueError):
            previous = {}
        while True:
            payload = collect_snapshot(args.operation, previous)
            replace_bytes(args.output, canonical(payload))
            previous = payload
            print(json.dumps({"cases": len(payload["cases"]), "errors": payload["errors"]}), flush=True)
            if not args.watch:
                return
            time.sleep(30)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
