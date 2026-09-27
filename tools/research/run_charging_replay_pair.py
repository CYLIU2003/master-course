"""Run a saved charging window twice under the existing local resource broker.

Diagnostic only: no campaign submission, no changes to original results or
worker modes. Enable the local worker explicitly before running this command.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.cluster.batch import Client, save
from tools.research.prepare_charging_replay import prepare
from bff.services.cluster.contracts import ClusterConfig, git_state
from bff.services.cluster.license_authority import authority_path, has_authority
from bff.services.cluster.license_broker import LicenseBroker
from bff.services.cluster.local_resources import LocalResources
from bff.services.cluster.resource_policy import resource_fit
from bff.services.cluster.runner import process_identity
from bff.services.cluster.store import JobStore
from bff.services.cluster.system_metrics import memory_metrics
from src.gurobi_session import managed_gurobi_session
from src.solver_policy import solver_policy_scope
from src.solver_memory import ENV_KEY


def json_value(value):
    """Preserve unavailable/nonfinite diagnostics explicitly, never as zero."""
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def check_admission(worker, row, capability, budget, threads, jobs):
    if not worker.enabled or not worker.gurobi or row.get("mode") != "active":
        raise RuntimeError("Local worker is disabled, draining, or not Gurobi enabled")
    manifest = {"minimum_ram_gb": budget, "requires_gurobi": True,
                "resource_requirements": {"cpu_threads": threads}}
    fit = resource_fit(worker, capability, manifest, jobs)
    if not fit["eligible"]:
        raise RuntimeError("Resource admission refused: " + ",".join(fit["reasons"]))
    return fit


def solve_profile(problem, config, directory, expected_models=None):
    """Record native models at the real optimize boundary without changing them."""
    from src.optimization.engine import OptimizationEngine
    from src.optimization.milp import solver_adapter
    directory.mkdir()
    observed = []
    original = solver_adapter.optimize_model

    def recorded(model, *args, **kwargs):
        from gurobipy import GurobiError
        model.update()
        path = directory / f"model-{len(observed)}.mps"
        model.write(str(path))
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_models is not None:
            index = len(observed)
            if index >= len(expected_models) or checksum != expected_models[index]["mps_sha256"]:
                raise ValueError("Native MPS differs between policies; candidate solve refused")
        row = {"mps_sha256": checksum, "variables": model.NumVars,
               "constraints": model.NumConstrs, "nonzeros": model.NumNZs}
        observed.append(row)
        save(directory / "native-models.json", observed)
        started = time.perf_counter()
        try:
            return original(model, *args, **kwargs)
        finally:
            row["wall_seconds"] = time.perf_counter() - started
            for key in ("Status", "SolCount", "Runtime", "MaxMemUsed", "ObjVal", "ObjBound", "MIPGap"):
                try:
                    row[key] = getattr(model, key)
                except (AttributeError, GurobiError):
                    row[key] = None
            save(directory / "native-models.json", json_value(observed))

    problem = deepcopy(problem)
    problem = replace(problem, metadata={**problem.metadata, "stage2_native_log_enabled": True,
        "phase3_diagnostics_dir": str(directory)})
    started = time.perf_counter()
    with patch.object(solver_adapter, "optimize_model", recorded):
        result = OptimizationEngine().solve(problem, config)
    save(directory / "result.json", json_value(asdict(result)))
    if not observed or expected_models is not None and len(observed) != len(expected_models):
        raise ValueError("Unexpected native solve count")
    return {"policy": config.stage2_charging_start_policy,
            "wall_seconds": time.perf_counter() - started,
            "feasible": result.feasible, "solver_status": result.solver_status,
            "objective_value": result.objective_value, "native_models": observed,
            "infeasibility_reasons": result.infeasibility_reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--memory-gib", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.memory_gib) or args.memory_gib < 4:
        parser.error("Memory budget must be finite and at least 4 GiB")
    before = git_state(ROOT)
    if before["dirty"]:
        parser.error("Freeze a clean checkout before native execution")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "git_before": before, "profiles": [],
              "memory_budget_gib": args.memory_gib, "scope": "saved_window_diagnostic_only"}
    save(output / "state.json", report)
    try:
        settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
        queue = Path(settings["queue"])
        if not has_authority(authority_path(), queue):
            raise ValueError("Settings do not identify the existing license authority")
        config = ClusterConfig.model_validate_json(Path(settings["config"]).read_text(encoding="utf-8-sig"))
        worker, = [w for w in config.workers if w.transport == "local"]
        client = Client(f"http://127.0.0.1:{settings['port']}")
        window, baseline, candidate, preflight = prepare(args.archive, args.archive_sha256, args.step)
        save(output / "preflight.json", preflight)
        snapshot = client.request("/api/cluster/workers")
        row = next(r for r in snapshot["workers"] if r["id"] == worker.id)
        if (snapshot["global_gurobi_slots"], snapshot["external_gurobi_slots"]) != (config.global_gurobi_slots, config.external_gurobi_slots):
            raise ValueError("Controller and settings license limits differ")
        capability = {**row["capability"], **memory_metrics()}
        store = JobStore(queue)
        resources = LocalResources(store)
        broker = LicenseBroker(store, total=config.global_gurobi_slots, external=config.external_gurobi_slots)
        owner = f"{os.getpid()}:{process_identity(os.getpid())}"
        identity = "charging-replay-" + str(uuid4())
        report["reservation_id"] = identity
        report["admission"] = check_admission(worker, row, capability, args.memory_gib,
            baseline.gurobi_threads, client.request("/api/cluster/jobs") + resources.rows())
        if not resources.acquire(identity, worker, baseline.gurobi_threads):
            raise RuntimeError("Local execution slot was claimed by another job")

        def acquire():
            if not broker.acquire(identity, owner_kind="local", owner_identity=owner):
                raise RuntimeError("Shared Gurobi slot unavailable; no solve started")

        def release(started):
            broker.finish(identity, cooldown_seconds=330 if started else 0)

        try:
            # Slot claiming is transactional. Recheck physical headroom after
            # claiming it; external applications are not governed by our queue.
            current = client.request("/api/cluster/workers")
            row = next(r for r in current["workers"] if r["id"] == worker.id)
            report["admission_after_claim"] = check_admission(worker, row,
                {**row["capability"], **memory_metrics()}, args.memory_gib, baseline.gurobi_threads,
                client.request("/api/cluster/jobs") + [r for r in resources.rows() if r["id"] != identity])
            with patch.dict(os.environ, {ENV_KEY: str(args.memory_gib)}):
                with solver_policy_scope() as usage, managed_gurobi_session(acquire, release):
                    for control in (baseline, candidate):
                        report["status"] = "RUNNING_" + control.stage2_charging_start_policy
                        save(output / "state.json", report)
                        expected = report["profiles"][0]["native_models"] if report["profiles"] else None
                        report["profiles"].append(solve_profile(window, control,
                            output / control.stage2_charging_start_policy, expected))
                    report["solver_usage"] = asdict(usage)
        finally:
            resources.release(identity)
        report["git_after"] = git_state(ROOT)
        report["status"] = "DIAGNOSTIC_COMPLETED"
        if before != report["git_after"]:
            raise ValueError("Code changed during diagnostic")
        report["limits"] = ["Engine feasibility is not a new independent whole-week audit.",
            "Single-window pair is not proof of general speedup; no production defaults changed.",
            "8 GiB or another selected budget is a diagnostic control, not historical week parity."]
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        save(output / "state.json", json_value(report))


if __name__ == "__main__":
    main()
