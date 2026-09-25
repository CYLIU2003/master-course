"""Run independent, frozen three-route weeks on the existing cluster.

Prepare, dispatch, collection and audit use the existing production services.
An error in one case does not cancel other independent seasons. No ODPT network
request, SOC reset, pruning, fallback, or automatic model change is introduced.
"""
from __future__ import annotations

import argparse
import hashlib
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.contracts import git_state
from bff.services.cluster.store import ControllerLock
from bff.services.run_preparation import get_or_build_run_preparation, materialize_scenario_from_prepared_input
from bff.services.optimization_run.rolling_chain import bind_rolling_fleet_input
from bff.store import output_paths, scenario_store
from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import configure_doc, parent_hash
from scripts.benchmarks.shibu24_optimization_store import ARTIFACTS, SCHEMA_VERSION, _rowset_sha, _validate_rows, load_database
from tools.cluster.audit_batch import audit_batch
from tools.cluster.batch import validate_batch
from tools.research.shibu21_monthly import _overnight_contract
from tools.research.weekly_results import read, sha, write_json
from tools.research.weekly_collection import collect_week

DATABASE = ROOT / "data/optimization/shibu21_23_frozen_20260924"
PARENT = "771d115b-75b0-49f7-a7f0-25f259a2cd21"
# One preselected continuous week in EVERY calendar month. Seasons are only a
# reporting group; selecting four seasons must not silently remove eight months.
WEEKS = (
    "2025-01-06", "2025-02-03", "2025-03-03", "2025-04-07",
    "2025-05-12", "2025-06-02", "2025-07-07", "2025-08-04",
    "2025-09-01", "2025-10-06", "2025-11-10", "2025-12-01",
)


def freeze_database(source: Path, destination: Path = DATABASE) -> dict:
    """Manual offline conversion; preserve every row of the three-route capture."""
    manifest = read(source / "manifest.json")
    if (manifest.get("route_codes") != ["渋21", "渋22", "渋23"] or
            manifest.get("status") != "DIAGNOSTIC_SOURCE_CAPTURE_VALIDATED_DISTANCE_PROXY_DECLARED"):
        raise ValueError("Expected the previously validated complete three-route capture")
    data = {}
    for name in ARTIFACTS:
        path = source / f"{name}.json"
        if sha(path) != manifest["artifacts"][path.name]["sha256"]:
            raise ValueError(f"Source changed: {name}")
        data[name] = read(path)
    _validate_rows(data)
    if destination.exists():
        old, _ = load_database(destination)
        if old["source_manifest_sha256"] != sha(source / "manifest.json"):
            raise ValueError("Existing database has a different source")
        return old
    destination.mkdir(parents=True)
    db_path = destination / "source.sqlite3"
    with closing(sqlite3.connect(db_path)) as db:
        for name, rows in data.items():
            db.execute(f"CREATE TABLE {name}(position INTEGER PRIMARY KEY, route_id TEXT, service_id TEXT, entity_id TEXT, payload_json TEXT NOT NULL)")
            db.executemany(f"INSERT INTO {name} VALUES(?,?,?,?,?)", ((i, row.get("route_id"), row.get("service_id"),
                row.get("trip_id") or row.get("id"), json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                for i, row in enumerate(rows)))
        db.commit()
    result = {"schema_version": SCHEMA_VERSION, "source_status": manifest["status"],
              "source_manifest_sha256": sha(source / "manifest.json"), "database_sha256": sha(db_path),
              "distance_semantics": "trip_stop_sequence_polyline_haversine_not_road_distance",
              "tables": {name: {"count": len(rows), "rowset_sha256": _rowset_sha(rows)} for name, rows in data.items()},
              "route_codes": manifest["route_codes"], "source_provenance": manifest.get("provenance", {}),
              "manual_offline_freeze": True}
    write_json(destination / "manifest.json", result)
    load_database(destination)
    return result


def request(prepared_id: str) -> dict:
    result = {"execution_profile": "existing_solver_v1", "mode": "mode_milp_only",
              "prepared_input_id": prepared_id, "rebuild_dispatch": False, "use_existing_duties": False,
              "research_run": False, "random_seed": 42, "gurobi_threads": 4,
              "run_profile": "day_ahead_and_hourly_rolling", "run_hourly_rolling": True,
              "rolling_execution_minutes": 60, "time_limit_seconds": 7200,
              "stage1_time_limit_seconds": 1800, "stage2_time_limit_seconds": 600,
              "stage1_gurobi_search_profile": "bounded_presolve_barrier_no_crossover",
              "stage1_fragment_transition_cut_mode": "lazy", "mip_gap": .01, "timestep_min": 15}
    validate_budget(result)
    return result


def validate_budget(controls: dict) -> None:
    """Reject a solve that spends its global deadline before the declared stages."""
    stages = controls["stage1_time_limit_seconds"] + controls["stage2_time_limit_seconds"]
    if controls["time_limit_seconds"] <= stages:
        raise ValueError("Shared wall budget must leave model-build time beyond Stage1 and Stage2 allowances")


def placement_worker(workers: list[str], index: int) -> str | None:
    """Use the controller's verified resource policy, or explicit pinned workers."""
    if not workers or ("auto" in workers and workers != ["auto"]):
        raise ValueError("Use either auto alone or explicit verified worker IDs")
    return None if workers == ["auto"] else workers[index % len(workers)]


def validate_rolling_fleet(scenario: dict, payload: dict) -> dict:
    """Check the real Prepared fleet before paying for a day-ahead solve."""
    materialized = materialize_scenario_from_prepared_input(scenario, payload)
    bound = bind_rolling_fleet_input(materialized, payload.get("primary_depot_id"))
    contract = bound["simulation_config"]["scenario_fleet_contract"]
    return {"schema_version": contract["schema_version"],
            "fleet_contract_hash": contract["fleet_contract_hash"],
            "status": "INPUT_HANDOFF_VALIDATED_NOT_RESEARCH_APPROVAL"}


def prepare_week(week: str, directory: Path, parent_id: str, expected_parent_hash: str) -> dict:
    parent = scenario_store._load(parent_id, skip_graph_arcs=True)
    before = parent_hash(parent)
    if before != expected_parent_hash:
        raise ValueError("Base scenario changed between weekly cases")
    path = directory / "prepared.json"
    if path.exists():
        result = read(path)
        if sha(Path(result["prepared_path"])) != result["prepared_sha256"]:
            raise ValueError("Prepared input changed")
        return result
    manifest, tables = load_database(DATABASE)
    source = {"optimization_database": DATABASE.relative_to(ROOT).as_posix(),
              "optimization_database_sha256": manifest["database_sha256"],
              "optimization_manifest_sha256": sha(DATABASE / "manifest.json"),
              "source_manifest_sha256": manifest["source_manifest_sha256"],
              "source_id": "tsurumaki_shibu21_23_frozen_20260924", "route_codes": ["渋21", "渋22", "渋23"],
              "distance_semantics": manifest["distance_semantics"]}
    design = deepcopy(read(ROOT / "output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json")["design"])
    if week not in design["evaluation_weeks"]:
        raise ValueError("Week is outside the existing predeclared selection")
    design.update(bess_priority_mode="pv_self_consumption", bess_terminal_soc_policy="minimum_only",
                  rolling_bess_terminal_policy="minimum_only", bess_forecast_reserve_policy="physical_floor_only")
    # Immutable run instances stay in the campaign's private store; no monthly
    # replacement of the user's base scenario or automatic ODPT retrieval.
    state_file = directory / "instance.json"
    if state_file.exists():
        instance = read(state_file)
        if instance["parent_hash"] != before or instance["parent_id"] != parent_id:
            raise ValueError("Run instance belongs to another base scenario revision")
        identity = instance["scenario_id"]
    else:
        identity = scenario_store.duplicate_scenario(parent_id, name=f"渋21〜23 週次実行 {week}")["id"]
        write_json(state_file, {"scenario_id": identity, "parent_id": parent_id, "parent_hash": before})
    doc = configure_doc(scenario_store._load(identity, skip_graph_arcs=True), week, source, design=design)
    extension = _overnight_contract(doc, tables["timetable_rows"])
    controls = request("placeholder")
    doc["simulation_config"].update({key: value for key, value in controls.items()
        if key not in ("prepared_input_id", "rebuild_dispatch", "use_existing_duties", "research_run")})
    doc["simulation_config"].update(stage1_native_log_enabled=True, stage2_native_log_enabled=True,
                                     allow_postsolve_repair=False, stage1_sparse_charge_window_support=True,
                                     stage1_exact_depot_connection_factors=True)
    doc.setdefault("meta", {}).update(base_scenario_id=parent_id, run_instance=True,
                                      evaluation_scope="conditional_weekly_operation_cost")
    scenario_store._invalidate_dispatch_artifacts(doc)
    scenario_store._normalize_dispatch_scope(doc)
    scenario_store._save(doc)
    if parent_hash(scenario_store._load(parent_id, skip_graph_arcs=True)) != before:
        raise ValueError("Original scenario changed during Prepare")
    prepared = get_or_build_run_preparation(scenario=scenario_store._load(identity, skip_graph_arcs=True),
        built_dir=ROOT / "data/built/tokyu_full", routes_df=None,
        scenarios_dir=output_paths.outputs_root() / "prepared_inputs")
    if not prepared.is_valid or not prepared.solver_input_path:
        raise ValueError(f"Prepare rejected input: {prepared.error_code}: {prepared.error}")
    audit = (prepared.scope_summary or {}).get("prepared_scope_audit") or {}
    strict = audit.get("strict_coverage_precheck") or {}
    if not (strict.get("checked") and not strict.get("infeasible") and
            audit.get("formal_transition_network_ready") and audit.get("formal_turnaround_sensitivity_ready") and
            audit.get("formal_vehicle_trip_compatibility_ready")):
        raise ValueError(f"Prepare scope checks failed: {audit.get('warning_codes')}")
    payload = read(prepared.solver_input_path)
    fleet_handoff = validate_rolling_fleet(doc, payload)
    if len(payload["trips"]) != len(doc["timetable_rows"]) or any(not t.get("operator_id") or
            str(t["operator_id"]).upper() == "UNKNOWN" or float(t.get("distance_km") or 0) <= 0 for t in payload["trips"]):
        raise ValueError("Prepared timetable coverage/operator/distance changed")
    result = {"week": week, "scenario_id": identity, "parent_id": parent_id, "parent_hash": before,
              "prepared_input_id": prepared.prepared_input_id, "prepared_path": str(prepared.solver_input_path),
              "prepared_sha256": sha(prepared.solver_input_path), "trips": len(payload["trips"]),
              "overnight": extension, "fleet_handoff": fleet_handoff,
              "source_git": git_state(ROOT), "request": request(prepared.prepared_input_id)}
    write_json(path, result)
    return result


def run(settings_path: Path, directory: Path, parent: str, weeks: list[str], workers: list[str]) -> dict:
    placement_worker(workers, 0)  # Reject ambiguous placement before Prepare.
    settings = read(settings_path)
    expected = git_state(ROOT)
    if expected["dirty"] or expected["sha"] != settings["git_sha"] or git_state(Path(settings["release"])) != expected:
        raise ValueError("A matching clean, frozen controller release is required")
    if output_paths.outputs_root().resolve() != Path(settings["outputs"]).resolve():
        raise ValueError("Campaign and controller output roots differ")
    frozen_parent_hash = parent_hash(scenario_store._load(parent, skip_graph_arcs=True))
    binding = {"git": expected, "parent": parent, "parent_hash": frozen_parent_hash,
               "weeks": weeks, "workers": workers, "request": request("declared"),
               "source_manifest_sha256": sha(DATABASE / "manifest.json")}
    binding_path = directory / "binding.json"
    if binding_path.exists() and read(binding_path) != binding:
        raise ValueError("Existing campaign has different frozen controls")
    write_json(binding_path, binding)
    state = {"status": "RUNNING", "git_sha": expected["sha"], "cases": {}}
    clients = []
    for index, week in enumerate(weeks):
        case_dir = directory / week
        try:
            state["cases"][week] = {"state": "PREPARING"}
            write_json(directory / "state.json", state)
            prepared = prepare_week(week, case_dir, parent, frozen_parent_hash)
            # Auto uses the existing scheduler's verified release, free RAM,
            # CPU and license checks; a busy parent does not strand half the weeks.
            worker = placement_worker(workers, index)
            spec = {"schema_version": 1, "batch_id": f"weekly-{expected['sha'][:8]}-{hashlib.sha256(parent.encode()).hexdigest()[:12]}-{week}",
                    "controller_url": f"http://127.0.0.1:{settings['port']}", "git_sha": expected["sha"],
                    "tasks": [{"task_id": week, "submission": {"scenario_id": prepared["scenario_id"],
                               "worker_id": worker, "minimum_ram_gb": 18., "request": prepared["request"]}}]}
            validate_batch(spec)
            manifest = case_dir / "batch.json"
            if manifest.exists() and read(manifest) != spec:
                raise ValueError("An existing case's request cannot change")
            write_json(manifest, spec)
            log = (case_dir / "batch.log").open("a", encoding="utf-8")
            process = subprocess.Popen([sys.executable, str(ROOT / "tools/cluster/batch.py"), "run", str(manifest),
                "--state-dir", str(case_dir / "state"), "--poll-seconds", "20"], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            clients.append((week, process, log, spec, case_dir))
            state["cases"][week] = {"state": "SUBMITTED", "worker": worker, "client_pid": process.pid}
        except Exception as exc:
            state["cases"][week] = {"state": "PREPARE_OR_SUBMIT_FAILED", "error": str(exc), "error_type": type(exc).__name__}
        write_json(directory / "state.json", state)
    while clients:
        for entry in clients[:]:
            week, process, log, spec, case_dir = entry
            code = process.poll()
            if code is None:
                continue
            clients.remove(entry)
            log.close()
            try:
                batch_state = read(case_dir / "state/batch-state.json")
                audit = audit_batch(spec, batch_state, case_dir / "state")
                write_json(case_dir / "artifact-audit.json", audit)
                passed = code == 0 and not audit["unverified"] and all(t.get("physical_feasibility_claim_eligible") for t in audit["tasks"])
                if passed:
                    summary = collect_week(read(case_dir / "prepared.json"), batch_state["tasks"][week], case_dir, audit)
                    state["cases"][week]["total_cost_jpy"] = summary["total_cost"]
                state["cases"][week].update(state="VERIFIED" if passed else "FAILED_OR_UNVERIFIED", audit=str(case_dir / "artifact-audit.json"))
            except Exception as exc:
                state["cases"][week].update(state="STATE_UNKNOWN", error=str(exc))
            write_json(directory / "state.json", state)
        if clients:
            time.sleep(20)
    state.update(status="COMPLETED" if all(c["state"] == "VERIFIED" for c in state["cases"].values()) else "PARTIAL_OR_FAILED",
                 finished_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(directory / "state.json", state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent", default=PARENT)
    parser.add_argument("--weeks", nargs="+", default=list(WEEKS))
    parser.add_argument("--period-plan", type=Path, help="Frozen scenario_periods export; determines parent and weeks")
    parser.add_argument("--workers", nargs="+", default=["desktop-6ae0mir", "local"],
                        help="Verified worker IDs assigned in order, or auto for resource-aware placement")
    args = parser.parse_args()
    if args.period_plan:
        plan = read(args.period_plan)
        if plan.get("schema_version") != "scenario_week_plan_v1" or not plan.get("weeks"):
            parser.error("Invalid exported period plan")
        args.parent, args.weeks = plan["scenario_id"], plan["weeks"]
    if args.command == "freeze":
        if not args.source:
            parser.error("freeze requires an explicit --source")
        print(json.dumps(freeze_database(args.source, args.output)))
        return
    if not args.settings:
        parser.error("run requires --settings")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = ControllerLock(args.output)
    try:
        print(json.dumps(run(args.settings, args.output, args.parent, args.weeks, args.workers), ensure_ascii=False))
    finally:
        lock.close()


if __name__ == "__main__":
    main()
