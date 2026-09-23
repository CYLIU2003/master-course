"""Prepare a genuine Shibu24 weekday diagnostic for one job on every worker.

The captured ODPT timetable and the existing Shibu21-23 scenario supply the
inputs. This command writes a batch; batch.py owns execution and collection.
The date is a 2025 weather counterfactual with a 2026 scheduled timetable,
not a reconstruction of actual 2025 bus operations or research approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "output/shibu21_24_seasonal_20260911/shibu24_source_audit"


def validated_source(source_dir: Path) -> tuple[dict, dict]:
    from scripts.audits.audit_shibu24_source import sha256

    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING":
        raise ValueError("Unexpected Shibu24 source status")
    for entry in manifest["capture_manifest"]["sources"]:
        raw = Path(entry["path"])
        if not raw.is_file() or sha256(raw) != entry["sha256"]:
            raise ValueError("Original ODPT capture is missing or has changed")
    for name, entry in manifest["artifacts"].items():
        if sha256(source_dir / name) != entry["sha256"]:
            raise ValueError(f"Shibu24 source hash mismatch: {name}")
    routes = json.loads((source_dir / "selected_routes.json").read_text(encoding="utf-8"))
    rows = json.loads((source_dir / "timetable_rows.json").read_text(encoding="utf-8"))
    expected = {"WEEKDAY": 224, "SAT": 188, "SUN_HOL": 170}
    if (len(routes) != 6 or len(rows) != 582 or
        dict(Counter(row["service_id"] for row in rows)) != expected or
        {row["routeCode"] for row in routes} != {"渋２４"} or
        any(not row.get("operator_id") or row["operator_id"] == "UNKNOWN" or
            not row.get("distance_source") or float(row.get("distance_km") or 0) <= 0
            for row in rows)):
        raise ValueError("Official Shibu24 source no longer has the audited route/trip contract")
    source = {
        "source_directory": str(source_dir.resolve()),
        "source_id": "tsurumaki_shibu24_odpt_20260901_diagnostic_v1",
        "route_codes": ["渋24"],
        "distance_semantics": manifest["source_validation"]["distance_semantics"],
    }
    return source, {"route_count": len(routes), "template_count": len(rows),
                    "service_counts": expected, "source_manifest_sha256": sha256(source_dir / "manifest.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--service-date", default="2025-05-12")
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    for key in ("release", "config", "queue", "outputs", "scenarios"):
        if key not in settings:
            raise ValueError(f"Missing controller setting: {key}")
    os.environ.update(
        MC_CLUSTER_CONFIG=settings["config"], MC_CLUSTER_DIR=settings["queue"],
        MC_OUTPUTS_DIR=settings["outputs"], SCENARIO_STORE_PATH=settings["scenarios"],
        BUILT_ROOT=str(Path(settings["release"]) / "data/built"),
        DEFAULT_DATASET_ID="tokyu_full",
    )
    from bff.services.cluster.contracts import canonical, git_state, read_config, segment
    from bff.services.run_preparation import get_or_build_run_preparation
    from bff.store import output_paths, scenario_store
    from scripts.audits.audit_shibu24_source import sha256
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import (
        PARENT_SCENARIO_ID, configure_doc, parent_hash,
    )
    if git_state(ROOT) != {"sha": settings["git_sha"], "dirty": False}:
        raise ValueError("Prepare requires the same clean code SHA as the frozen controller")
    segment(args.batch_id)
    selected_date = date.fromisoformat(args.service_date)
    if selected_date.weekday() != 0:
        raise ValueError("The fixed Shibu24 diagnostic date must be a Monday")
    args.output = args.output.resolve()
    if args.output.exists():
        raise ValueError("Batch already exists; resume it with batch.py")
    if Path(settings["scenarios"]).resolve() != output_paths.scenarios_root().resolve():
        raise ValueError("Scenario store differs from controller's configured legacy store")
    source, source_audit = validated_source(args.source_dir.resolve())
    config = read_config()
    workers = [worker for worker in config.workers if worker.enabled]
    if len(workers) != 16 or len({worker.id for worker in workers}) != 16:
        raise ValueError("This diagnostic requires 16 distinct enabled workers")
    parent = scenario_store._load(PARENT_SCENARIO_ID, skip_graph_arcs=True)
    before = parent_hash(parent)
    created = scenario_store.duplicate_scenario(
        PARENT_SCENARIO_ID,
        name=f"渋24 ODPT実便 {args.service_date} 16台診断（研究採用外）",
    )
    scenario_id = str(created["id"])
    doc = scenario_store._load(scenario_id, skip_graph_arcs=True)
    doc = configure_doc(doc, args.service_date, source, planning_days=1)
    doc["simulation_config"].update(
        execution_profile="alns_no_gurobi_v1",
        solver_mode="mode_alns_only",
        time_limit_seconds=180,
        alns_iterations=30,
        no_improvement_limit=15,
    )
    doc.setdefault("scenario_overlay", {}).setdefault("solver_config", {})["mode"] = "mode_alns_only"
    scenario_store._invalidate_dispatch_artifacts(doc)
    scenario_store._normalize_dispatch_scope(doc)
    scenario_store._save(doc)
    persisted = scenario_store._load(scenario_id, skip_graph_arcs=True)
    if before != parent_hash(scenario_store._load(PARENT_SCENARIO_ID, skip_graph_arcs=True)):
        raise ValueError("Parent Shibu21-23 scenario changed during Shibu24 preparation")
    if len(persisted["timetable_rows"]) != 224:
        raise ValueError("Expected all 224 genuine weekday Shibu24 trips")
    prepared = get_or_build_run_preparation(
        persisted, Path(settings["release"]) / "data/built/tokyu_full",
        output_paths.outputs_root() / "prepared_inputs", None,
    )
    if not prepared.is_valid:
        raise ValueError(f"Shibu24 Prepare rejected input: {prepared.error_code}: {prepared.error}")
    canonical_input = json.loads(prepared.solver_input_path.read_text(encoding="utf-8"))
    trips = canonical_input.get("trips") or []
    if (len(trips) != 224 or
        any(not row.get("operator_id") or row["operator_id"] == "UNKNOWN" or
            not row.get("distance_source") or float(row.get("distance_km") or 0) <= 0
            for row in trips)):
        raise ValueError("Prepared Shibu24 trips lost mandatory source fields")
    if not canonical_input.get("vehicles") or not canonical_input.get("chargers"):
        raise ValueError("Prepared Shibu24 vehicle or charger inventory is empty")
    request = {
        "execution_profile": "alns_no_gurobi_v1", "mode": "alns",
        "prepared_input_id": prepared.prepared_input_id,
        "rebuild_dispatch": False, "use_existing_duties": False,
        "research_run": False, "random_seed": 42,
        "run_hourly_rolling": False, "run_profile": "day_ahead_exploratory",
        "time_limit_seconds": 180, "alns_iterations": 30,
        "no_improvement_limit": 15, "timestep_min": 15,
    }
    tasks = [{"task_id": f"worker-{worker.id}", "submission": {
        "scenario_id": scenario_id, "worker_id": worker.id,
        "minimum_ram_gb": 1, "request": dict(request),
    }} for worker in workers]
    manifest = {"schema_version": 1, "batch_id": args.batch_id,
                "controller_url": f"http://127.0.0.1:{settings['port']}",
                "git_sha": settings["git_sha"], "tasks": tasks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(canonical(manifest))
    audit = {"status": "PREPARED_DIAGNOSTIC_ONLY", "source": source_audit,
             "scenario_id": scenario_id, "prepared_input_id": prepared.prepared_input_id,
             "prepared_path": str(prepared.solver_input_path), "actual_trips": len(trips),
             "vehicles": len(canonical_input["vehicles"]),
             "chargers": len(canonical_input["chargers"]),
             "worker_ids": [worker.id for worker in workers],
             "parent_sha256_before_after": before,
             "research_approval": "NOT_GRANTED",
             "limitations": ["2026 scheduled timetable paired with 2025 historical weather",
                             "distance is stop-coordinate geographic proxy",
                             "browser comparison and formal fleet contract pending",
                             "no-Gurobi ALNS differs from legacy solver"]}
    (args.output.parent / "input-audit.json").write_bytes(canonical(audit))
    print(json.dumps({"status": audit["status"], "tasks": len(tasks),
                      "actual_trips": len(trips), "scenario_id": scenario_id,
                      "prepared_input_id": prepared.prepared_input_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
