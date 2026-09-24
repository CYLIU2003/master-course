"""Run the frozen Shibu21 diagnostic in day, week, then twelve-month gates.

This is a resumable local controller client, not a research-acceptance decision.
It never fetches ODPT data or starts a later solve after a failed gate.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import git_state
from bff.services.cluster.store import ControllerLock
from bff.services.cluster.system_metrics import memory_metrics
from bff.services.run_preparation import get_or_build_run_preparation
from scripts.benchmarks.shibu21_optimization_store import DATABASE_DIR, load_database
from tools.cluster.audit_batch import audit_batch
from tools.cluster.batch import canonical, digest, validate_batch

DAY = "2025-05-12"
WEEK_TASK = "month-2025-05"
WEEK_MINIMUM_FREE_RAM_GB = 20.0


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def require_frozen(settings: dict) -> dict:
    state = git_state(ROOT)
    if state["dirty"] or state["sha"] != settings["git_sha"]:
        raise ValueError("Campaign requires the controller's clean frozen SHA")
    if git_state(Path(settings["release"])) != state:
        raise ValueError("Controller release differs from this campaign")
    if output_paths.outputs_root().resolve() != Path(settings["outputs"]).resolve():
        raise ValueError("MC_OUTPUTS_DIR differs from the controller")
    if output_paths.scenarios_root().resolve() != Path(settings["scenarios"]).resolve():
        raise ValueError("Scenario store differs from the controller")
    return state


def verify_prepared(path: Path, expected_trips: int) -> None:
    payload = read(path)
    trips = payload.get("trips") or []
    if len(trips) != expected_trips:
        raise ValueError(f"Prepared trip count {len(trips)} differs from {expected_trips}")
    if any(not trip.get("operator_id") or str(trip["operator_id"]).upper() == "UNKNOWN"
           or not trip.get("distance_source") or float(trip.get("distance_km") or 0) <= 0
           for trip in trips):
        raise ValueError("Prepared Shibu21 trips lack operator or positive proven distance")
    if not payload.get("vehicles") or not payload.get("chargers"):
        raise ValueError("Prepared vehicle or charger inventory is empty")


def prepare_day(directory: Path) -> dict:
    path = directory / "day-prepared.json"
    if path.exists():
        state = read(path)
        prepared = (output_paths.outputs_root() / "prepared_inputs" / state["scenario_id"] /
                    f"{state['prepared_input_id']}.json")
        if monthly._sha(prepared) != state["prepared_input_sha256"]:
            raise ValueError("Day Prepared input changed")
        verify_prepared(prepared, 42)
        return state
    source, _, weeks = monthly._source_and_design()
    if DAY not in weeks or date.fromisoformat(DAY).weekday() != 0:
        raise ValueError("The declared day is not the selected May representative week")
    _, tables = load_database(DATABASE_DIR)
    parent = scenario_store._load(monthly.PARENT_ID, skip_graph_arcs=True)
    original_hash = parent_hash(parent)
    scenario_id = scenario_store.duplicate_scenario(
        monthly.PARENT_ID, name=f"渋21 {DAY} 実便1日・翌朝SOC段階診断"
    )["id"]
    doc = scenario_store._load(scenario_id, skip_graph_arcs=True)
    doc = configure_doc(doc, DAY, source, planning_days=1)
    overnight = monthly._overnight_contract(doc, tables["timetable_rows"])
    doc["simulation_config"].update(
        execution_profile="existing_solver_v1", solver_mode="mode_milp_only",
        time_limit_seconds=120, stage1_time_limit_seconds=600,
        stage2_time_limit_seconds=120, gurobi_threads=2, mip_gap=.01,
    )
    doc.setdefault("scenario_overlay", {}).setdefault("solver_config", {})["mode"] = "mode_milp_only"
    scenario_store._invalidate_dispatch_artifacts(doc)
    scenario_store._normalize_dispatch_scope(doc)
    scenario_store._save(doc)
    if parent_hash(scenario_store._load(monthly.PARENT_ID, skip_graph_arcs=True)) != original_hash:
        raise ValueError("Parent scenario changed during day Prepare")
    prepared = get_or_build_run_preparation(
        scenario=scenario_store._load(scenario_id, skip_graph_arcs=True),
        built_dir=ROOT / "data/built/tokyu_full", routes_df=None,
        scenarios_dir=output_paths.outputs_root() / "prepared_inputs",
    )
    if not prepared.is_valid or not prepared.solver_input_path:
        raise ValueError(f"Day Prepare failed: {prepared.error_code}: {prepared.error}")
    audit = dict((prepared.scope_summary or {}).get("prepared_scope_audit") or {})
    strict = dict(audit.get("strict_coverage_precheck") or {})
    if not (strict.get("checked") and not strict.get("infeasible")
            and audit.get("formal_transition_network_ready")
            and audit.get("formal_turnaround_sensitivity_ready")
            and audit.get("formal_vehicle_trip_compatibility_ready")):
        raise ValueError(f"Day strict Prepare audit failed: {audit.get('warning_codes')}")
    verify_prepared(prepared.solver_input_path, 42)
    state = {"scenario_id": scenario_id, "prepared_input_id": prepared.prepared_input_id,
             "prepared_input_sha256": monthly._sha(prepared.solver_input_path),
             "trip_count": 42, "overnight": overnight, "parent_sha256": original_hash}
    write(path, state)
    return state


def day_request(prepared_input_id: str) -> dict:
    return {"execution_profile": "existing_solver_v1", "mode": "mode_milp_only",
            "prepared_input_id": prepared_input_id, "rebuild_dispatch": False,
            "use_existing_duties": False, "research_run": False, "random_seed": 42,
            "gurobi_threads": 2, "run_profile": "day_ahead_exploratory",
            "run_hourly_rolling": False, "time_limit_seconds": 120,
            "stage1_time_limit_seconds": 600, "stage2_time_limit_seconds": 120,
            "mip_gap": .01, "timestep_min": 15}


def one_task_spec(settings: dict, task: dict, batch_id: str) -> dict:
    spec = {"schema_version": 1, "batch_id": batch_id,
            "controller_url": f"http://127.0.0.1:{settings['port']}",
            "git_sha": settings["git_sha"], "tasks": [task]}
    validate_batch(spec)
    return spec


def require_gate(report: dict, expected_tasks: int) -> None:
    if report["total"] != expected_tasks or report["unverified"]:
        raise ValueError("Collected batch artifacts failed independent hash/contract audit")
    failed = [row["task_id"] for row in report["tasks"]
              if not row.get("physical_feasibility_claim_eligible")]
    if failed:
        raise ValueError(f"Independent physical-feasibility gate failed: {failed}")


def batch_failure_detail(state_dir: Path) -> str:
    """Return a bounded, non-secret terminal reason for a failed batch."""
    state_path = state_dir / "batch-state.json"
    if not state_path.is_file():
        return "batch did not produce a state file"
    rows = read(state_path).get("tasks") or {}
    failures = []
    for task_id, row in sorted(rows.items()):
        if row.get("state") != "FAILED":
            continue
        reason = "worker failed"
        archive = state_dir / str(row.get("artifacts") or "")
        if archive.is_file():
            try:
                with zipfile.ZipFile(archive) as bundle:
                    result = json.loads(bundle.read("state.json")).get("result") or {}
                if not isinstance(result, dict):
                    result = {}
                failure = str(result.get("error") or "").strip().splitlines()
                last_line = failure[-1] if failure else ""
                if last_line.endswith("GurobiError: Out of memory"):
                    reason = "GurobiError: Out of memory"
                elif last_line.endswith("MemoryError"):
                    reason = "MemoryError"
                elif last_line.endswith("TimeoutError"):
                    reason = "TimeoutError"
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
                reason = "worker failed; collected state unreadable"
        failures.append(f"{task_id}: {reason}")
    return "; ".join(failures) if failures else "batch unresolved; same attempt requires reconciliation"


def require_week_capacity(settings: dict, minimum_ram_gb: float) -> None:
    """Reject a known underprovisioned local-only week before job submission."""
    workers = [row for row in read(Path(settings["config"])).get("workers", [])
               if row.get("enabled", True)]
    if not workers or any(row.get("transport") != "local" for row in workers):
        return  # The controller performs per-worker admission for a cluster.
    free_ram = memory_metrics().get("ram_free_gb")
    reserve = max(float(row.get("reserved_system_ram_gb") or 0) for row in workers)
    if free_ram is None or free_ram - reserve < minimum_ram_gb:
        raise ValueError(
            f"Insufficient local free RAM for the seven-day task: "
            f"requires {minimum_ram_gb:g} GB after system reserve; "
            f"observed {free_ram} GB before reserve. No job was submitted."
        )


def run_batch(spec: dict, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "batch.json"
    if manifest.exists() and read(manifest) != spec:
        raise ValueError("Existing batch manifest changed")
    write(manifest, spec)
    state_dir = directory / "state"
    command = [sys.executable, str(ROOT / "tools/cluster/batch.py"), "run",
               str(manifest), "--state-dir", str(state_dir), "--poll-seconds", "15"]
    with (directory / "batch.log").open("a", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   check=False)
    if completed.returncode:
        raise ValueError(f"Batch did not pass: {batch_failure_detail(state_dir)}; "
                         f"see {directory / 'batch.log'}")
    report = audit_batch(spec, read(state_dir / "batch-state.json"), state_dir)
    write(directory / "artifact-audit.json", report)
    require_gate(report, len(spec["tasks"]))
    return report


def verify_passed_stage(directory: Path, stage: str) -> None:
    if stage == "months":
        report = read(directory / "twelve-month-audit.json")
        rows = report["months"]
        if len(rows) != 12 or len({row["task_id"] for row in rows}) != 12:
            raise ValueError("Previously passed monthly audit is incomplete")
        if any(not row.get("collection_verified") or
               not row.get("physical_feasibility_claim_eligible") for row in rows):
            raise ValueError("Previously passed monthly audit contains an invalid week")
        return
    subdir = directory / ("day" if stage == "day" else "week")
    require_gate(read(subdir / "artifact-audit.json"), 1)


def run(settings_path: Path, directory: Path, minimum_ram_gb: float) -> dict:
    settings = read(settings_path)
    os.environ.update(MC_OUTPUTS_DIR=settings["outputs"],
                      SCENARIO_STORE_PATH=settings["scenarios"],
                      BUILT_ROOT=str(ROOT / "data/built"), DEFAULT_DATASET_ID="tokyu_full")
    # scenario_store freezes its store path at import time. Load these modules
    # only after binding this CLI process to the controller's isolated paths.
    global output_paths, scenario_store, configure_doc, parent_hash, monthly
    from bff.store import output_paths, scenario_store
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import configure_doc, parent_hash
    from tools.research import shibu21_monthly as monthly
    git = require_frozen(settings)
    preflight = monthly.check()
    binding = {"git_sha": git["sha"], "settings_sha256": monthly._sha(settings_path),
               "preflight_sha256": digest(canonical(preflight)),
               "optimization_database_sha256": preflight["optimization_database_sha256"],
               "weeks": [row["week"] for row in preflight["weeks"]]}
    binding_path = directory / "binding.json"
    if binding_path.exists() and read(binding_path) != binding:
        raise ValueError("Frozen code or source changed; use a new campaign directory")
    write(binding_path, binding)
    state_path = directory / "stage-state.json"
    state = read(state_path) if state_path.exists() else {"schema_version": 1, "stages": {},
                                                          "research_approval": "NOT_GRANTED"}
    week_minimum_ram_gb = max(minimum_ram_gb, WEEK_MINIMUM_FREE_RAM_GB)
    for stage in ("day", "week", "months"):
        if state["stages"].get(stage) == "PASSED":
            verify_passed_stage(directory, stage)
    active_stage = None
    try:
        if state["stages"].get("day") != "PASSED":
            active_stage = "day"
            state["stages"]["day"] = "PREPARING"
            write(state_path, state)
            day = prepare_day(directory)
            task = {"task_id": "day-2025-05-12", "submission": {
                "scenario_id": day["scenario_id"], "worker_id": "local",
                "minimum_ram_gb": minimum_ram_gb,
                "request": day_request(day["prepared_input_id"])}}
            state["stages"]["day"] = "RUNNING"
            write(state_path, state)
            run_batch(one_task_spec(settings, task, "shibu21-stage-day-v1"), directory / "day")
            state["stages"]["day"] = "PASSED"
            write(state_path, state)
        if state["stages"].get("week") != "PASSED":
            active_stage = "week"
            state["stages"]["week"] = "PREPARING"
            write(state_path, state)
            prepared = monthly.prepare(directory / "monthly-inputs", limit=5)
            may = next(row for row in prepared["cases"] if row["week"] == DAY)
            if may["status"] != "PREPARED":
                raise ValueError("May representative week did not pass strict Prepare")
            request = {"execution_profile": "existing_solver_v1", "mode": "mode_milp_only",
                       "prepared_input_id": may["prepared_input_id"], "rebuild_dispatch": False,
                       "use_existing_duties": False, "research_run": False, "random_seed": 42,
                       "gurobi_threads": 4, "run_profile": "day_ahead_and_hourly_rolling",
                       "run_hourly_rolling": True, "rolling_execution_minutes": 60,
                       "time_limit_seconds": 120, "stage1_time_limit_seconds": 1800,
                       "stage2_time_limit_seconds": 120, "mip_gap": .01, "timestep_min": 15}
            task = {"task_id": WEEK_TASK, "submission": {
                "scenario_id": may["scenario_id"], "minimum_ram_gb": week_minimum_ram_gb,
                "request": request}}
            write(directory / "week-task.json", task)
            require_week_capacity(settings, week_minimum_ram_gb)
            state["stages"]["week"] = "RUNNING"
            write(state_path, state)
            run_batch(one_task_spec(settings, task, "shibu21-stage-week-v1"), directory / "week")
            state["stages"]["week"] = "PASSED"
            write(state_path, state)
        if state["stages"].get("months") != "PASSED":
            active_stage = "months"
            state["stages"]["months"] = "PREPARING"
            write(state_path, state)
            month_dir = directory / "monthly-inputs"
            summary = monthly.prepare(month_dir, limit=12)
            write(month_dir / "summary.json", summary)
            if not summary["all_prepared"]:
                raise ValueError("All twelve monthly inputs must pass strict Prepare")
            monthly.create_batch(month_dir, settings_path, "shibu21-full-twelve-v1",
                                 minimum_ram_gb=week_minimum_ram_gb)
            full = read(month_dir / "batch.json")
            may_task = next(row for row in full["tasks"] if row["task_id"] == WEEK_TASK)
            if may_task != read(directory / "week-task.json"):
                raise ValueError("Stage week differs from the May monthly task")
            remaining = deepcopy(full)
            remaining["batch_id"] = "shibu21-stage-remaining-eleven-v1"
            remaining["tasks"] = [row for row in full["tasks"] if row["task_id"] != WEEK_TASK]
            validate_batch(remaining)
            state["stages"]["months"] = "RUNNING"
            write(state_path, state)
            rest = run_batch(remaining, directory / "remaining-eleven")
            week = read(directory / "week" / "artifact-audit.json")
            require_gate(week, 1)
            combined = {"schema_version": 1, "source_git_sha": git["sha"],
                        "months": sorted(week["tasks"] + rest["tasks"], key=lambda row: row["task_id"]),
                        "research_approval": "NOT_GRANTED_BY_DIAGNOSTIC_CAMPAIGN"}
            if len(combined["months"]) != 12 or len({row["task_id"] for row in combined["months"]}) != 12:
                raise ValueError("Monthly result does not cover exactly twelve distinct months")
            write(directory / "twelve-month-audit.json", combined)
            state["stages"]["months"] = "PASSED"
            write(state_path, state)
    except Exception as exc:
        state["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        if active_stage and state["stages"].get(active_stage) != "PASSED":
            batch_dir = directory / ("remaining-eleven" if active_stage == "months" else active_stage)
            batch_state = batch_dir / "state" / "batch-state.json"
            try:
                summary = (read(batch_state).get("summary") or {}) if batch_state.is_file() else {}
            except (OSError, ValueError):
                summary = {}
            state["stages"][active_stage] = (
                "STATE_UNKNOWN" if summary.get("unresolved", 0) else "FAILED"
            )
        write(state_path, state)
        raise
    state.pop("failure", None)
    write(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-ram-gb", type=float, default=18.0)
    args = parser.parse_args()
    if not 0 < args.minimum_ram_gb < 128:
        parser.error("minimum RAM must be in (0, 128) GB")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = ControllerLock(directory)
    try:
        result = run(args.settings.resolve(), directory, args.minimum_ram_gb)
    finally:
        lock.close()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

