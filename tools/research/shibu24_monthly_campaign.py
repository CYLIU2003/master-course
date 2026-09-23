"""Run the frozen Shibu24 monthly diagnostic without an AI monitor.

The existing Prepare, cluster batch and artifact audit CLIs remain the only
execution paths. Re-running this command resumes their durable state. A failed
gate stops the campaign and preserves inputs, logs, and worker attempts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import git_state
from bff.services.cluster.store import ControllerLock


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _stamp(status: str, **details: object) -> dict:
    return {"status": status, "at_utc": datetime.now(timezone.utc).isoformat(), **details}


def _setting_environment(settings: dict) -> dict[str, str]:
    required = {"git_sha", "release", "outputs", "scenarios", "queue", "config", "port"}
    if not required <= settings.keys():
        raise ValueError("Controller settings omit required paths or frozen SHA")
    expected = {"sha": settings["git_sha"], "dirty": False}
    if git_state(ROOT) != expected or git_state(Path(settings["release"])) != expected:
        raise ValueError("Controller release and campaign code must be the same clean commit")
    environment = os.environ.copy()
    environment.update(
        MC_OUTPUTS_DIR=str(settings["outputs"]),
        SCENARIO_STORE_PATH=str(settings["scenarios"]),
        MC_CLUSTER_DIR=str(settings["queue"]),
        MC_CLUSTER_CONFIG=str(settings["config"]),
        BUILT_ROOT=str(ROOT / "data/built"),
        DEFAULT_DATASET_ID="tokyu_full",
    )
    return environment


def _run_stage(name: str, arguments: list[str], output: Path,
               environment: dict[str, str]) -> int:
    log_path = output / "campaign.log"
    _write(output / "campaign-state.json", _stamp(name))
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now(timezone.utc).isoformat()}] {name}\n")
        log.flush()
        return subprocess.run(
            [sys.executable, *arguments], cwd=ROOT, env=environment,
            stdout=log, stderr=subprocess.STDOUT, check=False,
        ).returncode


def run_campaign(settings_path: Path, output: Path, batch_id: str) -> int:
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    environment = _setting_environment(settings)
    output.mkdir(parents=True, exist_ok=True)
    lock = ControllerLock(output / "_campaign_lock")
    try:
        stages = [
            ("CHECKING_INPUTS", ["tools/research/shibu24_monthly.py", "check"]),
            ("PREPARING_TWELVE_WEEKS", ["tools/research/shibu24_monthly.py", "prepare",
                                        "--output", str(output)]),
            ("FREEZING_BATCH", ["tools/research/shibu24_monthly.py", "batch",
                                "--output", str(output), "--settings", str(settings_path),
                                "--batch-id", batch_id]),
            ("RUNNING_CLUSTER_BATCH", ["tools/cluster/batch.py", "run", str(output / "batch.json"),
                                       "--state-dir", str(output / "batch-state")]),
        ]
        batch_return = 0
        for name, arguments in stages:
            code = _run_stage(name, arguments, output, environment)
            if name == "RUNNING_CLUSTER_BATCH":
                batch_return = code
                break
            if code != 0:
                _write(output / "campaign-state.json", _stamp("FAILED", stage=name,
                      exit_code=code, log="campaign.log"))
                return code
        audit = ["tools/cluster/audit_batch.py", str(output / "batch.json"),
                 "--state-dir", str(output / "batch-state"),
                 "--output", str(output / "artifact-audit.json")]
        audit_return = _run_stage("AUDITING_COLLECTED_ARTIFACTS", audit, output, environment)
        final = "COLLECTED_DIAGNOSTIC" if batch_return == audit_return == 0 else "FAILED"
        _write(output / "campaign-state.json", _stamp(
            final, batch_exit_code=batch_return, audit_exit_code=audit_return,
            research_approval="NOT_GRANTED_BY_CLUSTER", log="campaign.log"))
        return 0 if final == "COLLECTED_DIAGNOSTIC" else 1
    finally:
        lock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-id", default="shibu24-monthly-overnight-v1")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "status":
        state = output / "campaign-state.json"
        print(state.read_text(encoding="utf-8") if state.exists() else '{"status":"NOT_STARTED"}')
        return 0
    if args.settings is None:
        parser.error("run requires --settings")
    try:
        return run_campaign(args.settings.resolve(), output, args.batch_id)
    except Exception as exc:
        _write(output / "campaign-state.json", _stamp(
            "FAILED", stage="SUPERVISOR", error_type=type(exc).__name__,
            error=str(exc), log="campaign.log"))
        print(f"Monthly campaign stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
