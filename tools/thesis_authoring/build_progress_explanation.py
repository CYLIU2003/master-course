"""Derive explanatory statistics from frozen results, without optimization.

Reuses the existing sealed-bundle and Rolling-series readers. Service-distance
statistics exclude deadhead; charging counts merge source-allocation rows.
PV indicators describe coincident states, not counterfactual causes.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_thesis_weather_result_package import load_and_validate_bundle
from tools.thesis_authoring.build_authoring_evidence import (
    EXECUTION_SHA, SCENARIOS, build_executed_power_series, load_json,
    read_csv, require_close, require_equal, sha256_file, verify_run_identity,
    write_csv, write_json,
)


def minutes(clock: str) -> int:
    hour, minute = map(int, clock.split(":"))
    if hour < 0 or not 0 <= minute < 60:
        raise ValueError(f"Invalid service clock: {clock}")
    return hour * 60 + minute


def dispatch_rows(prepared: dict, paths: dict, scenario: str) -> list[dict]:
    trips = {t["trip_id"]: t for t in prepared["trips"]}
    vehicles = {v["id"]: v for v in prepared["vehicles"]}
    require_equal(len(trips), len(prepared["trips"]), "unique input trips")
    assigned = [t for ids in paths.values() for t in ids]
    require_equal(len(assigned), len(set(assigned)), "unique assigned trips")
    require_equal(set(assigned), set(trips), "complete assignment")
    rows = []
    for vehicle_id, ids in sorted(paths.items()):
        vehicle = vehicles[vehicle_id]
        if vehicle["type"] not in ("BEV", "ICE"):
            raise ValueError("Unknown powertrain")
        for trip_id in ids:
            trip = trips[trip_id]
            distance = float(trip["distance_km"])
            duration = minutes(trip["arrival"]) - minutes(trip["departure"])
            if not math.isfinite(distance) or distance <= 0 or duration <= 0:
                raise ValueError(f"Invalid trip quantity: {trip_id}")
            rows.append(dict(scenario=scenario, trip_id=trip_id,
                vehicle_id=vehicle_id, powertrain=vehicle["type"],
                route_id=trip["route_id"], route_family=trip["routeFamilyCode"],
                direction=trip["direction"], departure=trip["departure"],
                arrival=trip["arrival"], departure_min=minutes(trip["departure"]),
                arrival_min=minutes(trip["arrival"]), service_distance_km=distance,
                service_minutes=duration, distance_source=trip["distance_source"]))
    return sorted(rows, key=lambda r: (r["departure_min"], r["trip_id"]))


def dispatch_statistics(rows: list[dict]) -> list[dict]:
    total_distance = sum(r["service_distance_km"] for r in rows)
    total_minutes = sum(r["service_minutes"] for r in rows)
    result = []
    for kind in ("BEV", "ICE"):
        subset = [r for r in rows if r["powertrain"] == kind]
        used = len({r["vehicle_id"] for r in subset})
        distance = sum(r["service_distance_km"] for r in subset)
        duration = sum(r["service_minutes"] for r in subset)
        result.append(dict(scenario=rows[0]["scenario"], powertrain=kind,
            trips=len(subset), used_vehicles=used, service_distance_km=distance,
            service_minutes=duration, trip_share=len(subset) / len(rows),
            service_distance_share=distance / total_distance,
            service_time_share=duration / total_minutes,
            trips_per_used_vehicle=len(subset) / used if used else None,
            service_km_per_used_vehicle=distance / used if used else None))
    return result


def charging_by_slot(rows: list[dict], charger_ids: list[str]) -> list[dict]:
    # A single session may have several proportional power-source rows.
    sessions = defaultdict(float)
    for row in rows:
        slot = int(row["slot_index"])
        power, energy = float(row["charge_kw"]), float(row["energy_kwh"])
        if not 0 <= slot < 96 or row["charger_id"] not in charger_ids:
            raise ValueError("Unknown charger or slot")
        if not math.isfinite(power) or power < 0:
            raise ValueError("Invalid charging power")
        require_close(energy, power * 0.25, "kW to kWh")
        sessions[(slot, row["charger_id"], row["vehicle_id"])] += power
    result = []
    for slot in range(96):
        selected = [(c, v, p) for (t, c, v), p in sessions.items() if t == slot and p > 1e-6]
        if len({c for c, _, _ in selected}) != len(selected):
            raise ValueError("Several vehicles on a one-port charger")
        if len({v for _, v, _ in selected}) != len(selected):
            raise ValueError("Vehicle assigned multiple chargers")
        if any(p > 90 + 1e-6 for _, _, p in selected):
            raise ValueError("Power exceeds frozen 90 kW charger rating")
        result.append(dict(slot_index=slot, charging_sessions_gt_1e_minus6_kw=len(selected),
            charging_sessions_ge_1_kw=sum(p >= 1 for _, _, p in selected),
            charging_kw=sum(p for _, _, p in selected)))
    return result


def write_table(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Empty derived table: {path}")
    write_csv(path, list(rows[0]), rows)


def render_figures(target: Path, assignments: dict, summaries: list, slot_rows: list) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font_path = Path("C:/Windows/Fonts/meiryo.ttc")
    if not font_path.exists():
        raise FileNotFoundError(font_path)
    matplotlib.rcParams.update({"font.family": FontProperties(fname=str(font_path)).get_name(),
        "font.size": 11, "svg.fonttype": "path", "svg.hashsalt": "progress-20260905"})
    fig_dir = target / "figures"
    fig_dir.mkdir(exist_ok=True)
    colors = {"BEV": "#147D76", "ICE": "#AE6635"}
    # Sub-lanes keep overlapping trips within a route visible.
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    routes = sorted({r["route_family"] for r in assignments["SUNNY"]})
    for ax, (name, rows) in zip(axes, assignments.items()):
        for idx, route in enumerate(routes):
            trip_rows = [r for r in rows if r["route_family"] == route]
            lane_ends = []
            for row in trip_rows:
                lane = next((i for i, end in enumerate(lane_ends) if end <= row["departure_min"]), len(lane_ends))
                if lane == len(lane_ends):
                    lane_ends.append(row["arrival_min"])
                else:
                    lane_ends[lane] = row["arrival_min"]
                row["plot_lane"] = lane
            lanes = max(1, len(lane_ends))
            for row in trip_rows:
                ax.broken_barh([(row["departure_min"] / 60, row["service_minutes"] / 60)],
                    (idx + row["plot_lane"] * 0.8 / lanes, 0.7 / lanes),
                    facecolors=colors[row["powertrain"]])
        ax.set_yticks([i + .4 for i in range(len(routes))], routes)
        ax.set_title(name + "：営業便の配車（緑 BEV／茶 ICE）", loc="left")
        ax.grid(axis="x", alpha=.2)
    axes[-1].set_xlabel("時刻（営業便のみ。回送・待機・充電は含まない）")
    axes[-1].set_xticks(range(0, 27, 2))
    axes[-1].set_xlim(5, 26)
    fig.tight_layout()
    for suffix in ("png", "svg"):
        fig.savefig(fig_dir / f"01_dispatch_by_route.{suffix}", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for name, color in (("SUNNY", "#147D76"), ("RAIN", "#574CA0")):
        data = [r for r in slot_rows if r["scenario"] == name]
        axes[0].step([r["slot_index"] / 4 for r in data], [r["charging_sessions_gt_1e_minus6_kw"] for r in data], where="post", label=name, color=color)
        axes[1].plot([r["slot_index"] / 4 for r in data], [r["pv_curtailed_kwh"] * 4 for r in data], label=name, color=color)
    axes[0].axhline(10, color="gray", linestyle="--", label="設置10ポート")
    axes[0].set_ylabel("正の充電電力を持つセッション数")
    axes[0].legend(ncol=3)
    axes[1].set_ylabel("PV抑制 [kW]")
    axes[1].set_xlabel("時刻（各15分枠）")
    axes[1].set_xticks(range(0, 25, 2))
    fig.suptitle("実行済み充電とPV抑制の同時観測。因果の分解ではない")
    fig.tight_layout()
    for suffix in ("png", "svg"):
        fig.savefig(fig_dir / f"02_charging_and_curtailment.{suffix}", dpi=180)
    plt.close(fig)


def build(target: Path) -> dict:
    if target.exists() and any(target.iterdir()):
        raise ValueError("Choose a new empty analysis directory; existing results are preserved")
    bundle = load_and_validate_bundle(ROOT / "docs/evidence/weather_dispatch_rerun_bb0c005")
    target.mkdir(parents=True, exist_ok=True)
    sources = {}
    def source(path: Path) -> None:
        sources[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    for rel in bundle.source_hashes:
        source(bundle.root / rel)
    for rel in bundle.parameter_source_hashes:
        source(bundle.parameter_source_root / rel)
    assignments, stats, slots, operational, costs = {}, [], [], [], []
    for name, expected in SCENARIOS.items():
        run = ROOT / expected["run_dir"]
        verify_run_identity(ROOT, name, run)
        scenario = bundle.scenarios[name]
        canonical_path = run / "canonical_solver_result.json"
        require_equal(sha256_file(canonical_path), scenario.rolling["day_ahead_result_sha256"], "sealed canonical result")
        chain_path = run / "rolling_hourly_chain/rolling_chain_summary.json"
        require_equal(load_json(chain_path), dict(scenario.rolling), "sealed Rolling chain")
        prepared_path = ROOT / "output/prepared_inputs" / expected["scenario_id"] / (expected["prepared_input_id"] + ".json")
        require_equal(sha256_file(prepared_path), expected["prepared_source_sha256"], "sealed Prepared input")
        prepared = load_json(prepared_path)
        canonical = load_json(canonical_path)
        rows = dispatch_rows(prepared, canonical["vehicle_paths"], name)
        require_equal(len(rows), 264, "264 served trips")
        for path in (canonical_path, chain_path, prepared_path, run / "run_input_manifest.json", run / "stage1_stage2_candidate_evaluation.json"):
            source(path)
        assignments[name] = rows
        group_stats = dispatch_statistics(rows)
        public = scenario.selected_candidate["selected_candidate"]
        for s in group_stats:
            kind = s["powertrain"].lower()
            require_equal(s["trips"], public[kind + "_trips"], "published trip count")
            require_equal(s["used_vehicles"], public["used_" + kind], "published fleet count")
        stats.extend(group_stats)
        power = build_executed_power_series(ROOT, name, target)
        for item in power["raw_hourly_solver_results"]:
            source(ROOT / item["path"])
        charge_path = run / "rolling_hourly_chain/charging_schedule.csv"
        source(charge_path)
        charge_rows = read_csv(charge_path)
        charge_slots = charging_by_slot(charge_rows, bundle.shared_parameters["charger_ids"])
        # Cross-check the serialized allocation against solver-native executed rows.
        raw_sessions = []
        for item in power["raw_hourly_solver_results"]:
            hourly = load_json(ROOT / item["path"])
            for row in hourly["charging_schedule"]:
                if item["executed_start_slot"] <= row["slot_index"] < item["executed_stop_slot_exclusive"]:
                    raw_sessions.append({**row, "energy_kwh": row["charge_kw"] * .25})
        require_equal(charge_slots, charging_by_slot(raw_sessions, bundle.shared_parameters["charger_ids"]), "executed session aggregation")
        for flow, charge in zip(power["rows"], charge_slots):
            require_close(charge["charging_kw"] / 4, flow["bev_charging_load_kwh"], "slot load")
            slots.append({**flow, **charge,
                "bess_at_upper_bound_1e3_kwh": abs(flow["bess_soc_end_kwh"] - bundle.shared_parameters["bess_soc_max_kwh"]) <= 1e-3,
                "all_ports_power_active": charge["charging_sessions_gt_1e_minus6_kw"] == 10})
        data = slots[-96:]
        curtailed = [r for r in data if r["pv_curtailed_kwh"] > 1e-6]
        operational.append(dict(scenario=name,
            peak_power_active_sessions=max(r["charging_sessions_gt_1e_minus6_kw"] for r in data),
            peak_sessions_ge_1_kw=max(r["charging_sessions_ge_1_kw"] for r in data),
            active_port_hours=sum(r["charging_sessions_gt_1e_minus6_kw"] for r in data) / 4,
            active_port_share_24h=sum(r["charging_sessions_gt_1e_minus6_kw"] for r in data) / (96 * 10),
            charge_energy_kwh=sum(r["bev_charging_load_kwh"] for r in data),
            energy_utilization_rated_24h=sum(r["bev_charging_load_kwh"] for r in data) / (90 * 10 * 24),
            curtailment_slots=len(curtailed),
            curtailment_kwh=sum(r["pv_curtailed_kwh"] for r in curtailed),
            curtailed_kwh_when_all_ports_active=sum(r["pv_curtailed_kwh"] for r in curtailed if r["all_ports_power_active"]),
            curtailed_kwh_when_bess_at_upper_bound=sum(r["pv_curtailed_kwh"] for r in curtailed if r["bess_at_upper_bound_1e3_kwh"]),
            curtailed_kwh_when_no_charging_power=sum(r["pv_curtailed_kwh"] for r in curtailed if r["charging_sessions_gt_1e_minus6_kw"] == 0),
            charging_wait_minutes=None, minimum_required_chargers=None,
            causal_curtailment_attribution="NOT_IDENTIFIED_FROM_SELECTED_PLAN"))
        c = scenario.costs
        costs.append(dict(scenario=name, total_jpy=c["total_cost"], vehicle_usage_jpy=c["vehicle_usage_cost"],
            excluding_vehicle_usage_jpy=c["total_cost"] - c["vehicle_usage_cost"],
            vehicle_share=c["vehicle_usage_cost"] / c["total_cost"], fuel_jpy=c["fuel_cost"],
            electricity_jpy=c["electricity_cost"], co2_jpy=c["co2_cost"]))
    sunny = {r["trip_id"]: r for r in assignments["SUNNY"]}
    rain = {r["trip_id"]: r for r in assignments["RAIN"]}
    same_fields = ("route_id", "departure", "arrival", "service_distance_km", "service_minutes", "distance_source")
    transitions = []
    for trip_id, row in sunny.items():
        require_equal({k: row[k] for k in same_fields}, {k: rain[trip_id][k] for k in same_fields}, "same trip inputs")
        transitions.append(dict(trip_id=trip_id, route_family=row["route_family"], departure=row["departure"],
            sunny_powertrain=row["powertrain"], rain_powertrain=rain[trip_id]["powertrain"], service_distance_km=row["service_distance_km"]))
    write_table(target / "dispatch_assignments.csv", assignments["SUNNY"] + assignments["RAIN"])
    write_table(target / "dispatch_statistics.csv", stats)
    write_table(target / "trip_powertrain_changes.csv", transitions)
    write_table(target / "executed_slots.csv", slots)
    write_table(target / "charging_and_curtailment_summary.csv", operational)
    write_table(target / "cost_comparison.csv", costs)
    render_figures(target, assignments, stats, slots)
    result = dict(status="DESCRIPTIVE_REANALYSIS_COMPLETE", execution_git_sha=EXECUTION_SHA,
        derivation_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        dispatch=stats, charging=operational, costs=costs,
        transitions={f"SUNNY_{a}_RAIN_{b}": sum(r["sunny_powertrain"] == a and r["rain_powertrain"] == b for r in transitions) for a in ("BEV", "ICE") for b in ("BEV", "ICE")},
        scope="Frozen selected plans only; service distances exclude deadhead; observed port use is not minimum required capacity; PV indicators overlap and are not causal attribution.")
    write_json(target / "summary.json", result)
    for path in (Path(__file__), ROOT / "tools/thesis_authoring/build_authoring_evidence.py", ROOT / "scripts/build_thesis_weather_result_package.py"):
        source(path)
    write_json(target / "manifest.json", dict(schema_version="progress_explanation_manifest_v1",
        execution_git_sha=EXECUTION_SHA, derivation_head=result["derivation_head"], source_sha256=sources,
        outputs={p.relative_to(target).as_posix(): sha256_file(p) for p in sorted(target.rglob("*")) if p.is_file()},
        local_only=True, solver_runs=0))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir.resolve()), ensure_ascii=False, indent=2))
