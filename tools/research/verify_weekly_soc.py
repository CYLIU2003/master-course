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
from src.gurobi_session import managed_gurobi_session

TESTS = [
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
    identity = "weekly-soc-regression-" + str(uuid4())
    def acquire():
        if not broker.acquire(identity, owner_kind="local", owner_identity=identity):
            raise RuntimeError("No shared license slot: native validation did not start")
    def release(started):
        broker.finish(identity, cooldown_seconds=330 if started else 0)
    import pytest
    os.chdir(ROOT)
    with managed_gurobi_session(acquire, release):
        code = int(pytest.main([*TESTS, "-q", "--junitxml=" + str(args.output.resolve() / "tests.xml")]))
    result = {"git_before": before, "git_after": git_state(ROOT), "tests": TESTS,
              "pytest_exit_code": code, "license_admission_id": identity,
              "scope": "two_day_native_regression;not_full_week_acceptance"}
    (args.output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return code if before == result["git_after"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
