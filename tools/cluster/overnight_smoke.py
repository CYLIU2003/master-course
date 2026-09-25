"""Prepare a small dated, continuous test for the normal cluster execution path.

Fictional data, never a reduced real timetable or a research result. Does not
submit jobs: use batch.py to submit/resume and audit_batch.py to verify collection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def scenario_for_days(days: int) -> dict:
    from tools.cluster.monthly_smoke import scenario_for_month
    from src.optimization.common.date_series import content_hash, materialize_dated_timetable

    if days not in (1, 2, 7):
        raise ValueError("Test duration must be 1, 2 or 7 days")
    document = scenario_for_month(2025, 1)
    templates = []
    for service, count in (("WEEKDAY", 4), ("SATURDAY", 3), ("SUNDAY", 2)):
        for row in document["timetable_rows"][:count]:
            template = {key: value for key, value in row.items() if key not in {
                "template_trip_id", "service_date", "day_index", "source_departure", "source_arrival"}}
            template.update(trip_id=f"test-{service}-{len(templates)}", service_id=service)
            templates.append(template)
    dates = [(date(2025, 1, 20) + timedelta(days=i)).isoformat() for i in range(days)]
    rows, contract = materialize_dated_timetable(templates, service_dates=dates, holiday_dates=[],
        source_provenance={"data_kind": "synthetic_overnight_test", "research_eligible": False})
    profiles = [{"date": day, "slot_minutes": 30, "capacity_factor_by_slot": [0.0] * 48} for day in dates]
    contract["pv_capacity_factor_rows_sha256"] = content_hash(profiles)
    config = document["simulation_config"]
    config.update(service_date=dates[0], service_dates=dates, planning_days=days,
                  end_time=f"{24 * days}:00", date_series_contract=contract,
                  daily_return_depot_id="SMOKE_DEPOT", execution_profile="existing_solver_v1",
                  rolling_window_terminal_policy="day_ahead_boundary_state",
                  final_soc_target_tolerance_percent=0)
    asset = config["depot_energy_assets"][0]
    asset.update(pv_generation_kwh_by_slot=[0.0] * (48 * days), pv_capacity_factor_by_date=profiles)
    document["energy_price_profiles"][0]["values"] = [20.0] * (48 * days)
    document["timetable_rows"] = rows
    document["scenario_overlay"]["dataset_version"] = "synthetic-overnight-v1"
    document["meta"]["name"] = f"テスト専用・連続{days}日・翌日引継ぎ（架空データ）"
    # The short direct edge and longer depot detour reproduce the real bug.
    for rule in document["deadhead_rules"]:
        rule["travel_time_min"] = 3 if rule["from_stop"] == "SMOKE_DEPOT" else 5
        if (rule["from_stop"], rule["to_stop"]) == ("SMOKE_B", "SMOKE_A"):
            rule["travel_time_min"] = 3
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--days", type=int, choices=(1, 2, 7), default=2)
    parser.add_argument("--worker", required=True, help="Explicit verified >=32 GB Gurobi worker")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Manifest exists; resume it with batch.py, do not regenerate")
    from tools.cluster.serve_controller import configure
    settings = configure(args.settings.resolve())
    from bff.services.cluster.contracts import canonical, read_config, segment
    from bff.services.run_preparation import get_or_build_run_preparation
    from bff.store import scenario_store, output_paths
    from tools.research.weekly_campaign import validate_rolling_fleet
    from tools.cluster.batch import validate_batch

    segment(args.batch_id)
    if not any(w.id == args.worker and w.enabled and w.gurobi for w in read_config().workers):
        raise ValueError("Worker is not enabled for managed Gurobi execution")
    document = scenario_for_days(args.days)
    document["meta"]["id"] = args.batch_id
    try:
        scenario_store.get_scenario_document_shallow(args.batch_id)
    except KeyError:
        pass
    else:
        raise ValueError("Scenario already exists; use a new ID or resume the saved manifest")
    scenario_store._save(deepcopy(document))
    scenario_store.set_dispatch_scope(args.batch_id, {"depotId": "SMOKE_DEPOT", "serviceId": "WEEKDAY"})
    persisted = scenario_store.get_scenario_document(args.batch_id)
    prepared = get_or_build_run_preparation(persisted, Path(settings["release"]) / "data/built/tokyu_full",
        output_paths.outputs_root() / "prepared_inputs", None)
    if not prepared.is_valid:
        raise ValueError(f"Test Prepare failed: {prepared.error}")
    payload = json.loads(prepared.solver_input_path.read_bytes())
    if len(payload["trips"]) != len(document["timetable_rows"]):
        raise ValueError("Prepare changed the declared test trip count")
    validate_rolling_fleet(persisted, payload)
    request = {"execution_profile": "existing_solver_v1", "mode": "mode_milp_only",
        "prepared_input_id": prepared.prepared_input_id, "rebuild_dispatch": False,
        "use_existing_duties": False, "research_run": False, "random_seed": 42,
        "gurobi_threads": 1, "timestep_min": 30, "mip_gap": .01,
        "run_profile": "day_ahead_and_hourly_rolling", "run_hourly_rolling": True,
        "rolling_execution_minutes": 60, "time_limit_seconds": 600,
        "stage1_time_limit_seconds": 60, "stage2_time_limit_seconds": 60,
        "stage1_gurobi_search_profile": "bounded_presolve_barrier_no_crossover"}
    spec = {"schema_version": 1, "batch_id": args.batch_id,
        "controller_url": f"http://127.0.0.1:{settings['port']}", "git_sha": settings["git_sha"],
        "tasks": [{"task_id": f"continuous-{args.days}-days", "submission": {
            "scenario_id": args.batch_id, "worker_id": args.worker, "minimum_ram_gb": 2,
            "request": request}}]}
    validate_batch(spec)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical(spec))
    print(json.dumps({"manifest": str(output), "days": args.days, "trips": len(payload["trips"]),
                      "prepared_input_id": prepared.prepared_input_id, "research_eligible": False}))


if __name__ == "__main__":
    main()
