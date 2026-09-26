"""Repeat the small native SOC regressions using the active shared license pool."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import ClusterConfig, git_state
from bff.services.cluster.license_broker import LicenseBroker
from bff.services.cluster.store import JobStore
from bff.services.cluster.local_resources import LocalResources
from bff.services.cluster.runner import process_identity
from bff.services.cluster.system_metrics import memory_metrics
from src.gurobi_session import managed_gurobi_session

TESTS = [
    "tests/test_daily_return_policy.py::test_rolling_window_reference_cannot_lower_next_morning_requirement",
    "tests/test_weekly_blocker_fixes.py::test_native_next_morning_target_precedes_daily_startup",
    "tests/test_daily_return_policy.py::test_next_morning_phase3_daily_return_native_stage2_preserves_deadlines",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path, help="Active controller's shared queue/settings")
    parser.add_argument("--output", required=True, type=Path, help="New evidence directory")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.settings = args.settings.resolve()
    before = git_state(ROOT)
    if before["dirty"]:
        parser.error("Freeze a clean commit before the native check")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
    config = ClusterConfig.model_validate_json(Path(settings["config"]).read_text(encoding="utf-8-sig"))
    broker = LicenseBroker(JobStore(Path(settings["queue"])), total=config.global_gurobi_slots, external=config.external_gurobi_slots)
    metrics = memory_metrics()
    if (metrics.get("installed_ram_gb") or metrics.get("ram_gb") or 0) < 31 or (metrics.get("ram_free_gb") or 0) < 8:
        raise RuntimeError("Native diagnostic needs a 32 GB class PC with 8 GB free")
    worker = next(worker for worker in config.workers if worker.transport == "local")
    resources = LocalResources(broker.store)
    resources.reconcile()
    identity = "weekly-soc-regression-" + str(uuid4())
    owner = f"{os.getpid()}:{process_identity(os.getpid())}"
    if not resources.acquire(identity, worker, 1):
        raise RuntimeError("Local diagnostic capacity is occupied")
    def acquire():
        if not broker.acquire(identity, owner_kind="local", owner_identity=owner):
            raise RuntimeError("No shared license slot: native validation did not start")
    def release(started):
        broker.finish(identity, cooldown_seconds=330 if started else 0)
    import pytest
    os.chdir(ROOT)
    try:
        with managed_gurobi_session(acquire, release):
            code = int(pytest.main([*TESTS, "-q", "--junitxml=" + str(args.output.resolve() / "tests.xml")]))
    finally:
        resources.release(identity)
    result = {"git_before": before, "git_after": git_state(ROOT), "tests": TESTS,
              "pytest_exit_code": code, "license_admission_id": identity,
              "host_memory_before": metrics,
              "scope": "two_day_native_regression;not_full_week_acceptance"}
    (args.output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return code if before == result["git_after"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
