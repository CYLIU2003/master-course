"""Export verified weekly execution evidence without starting any optimizer.

The original run verdict is immutable. A separate conditional-evaluation label
allows descriptive operating-cost reports without claiming integrated optimality.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_four_season_interpretation import aggregate_slots, require_close
from scripts.build_monthly_interpretation import seasonal_summary

SEASON = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
          6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}
FLOWS = {"grid_import_kwh": ("grid_to_bus_kwh_by_depot_slot", "grid_to_bess_kwh_by_depot_slot"),
         "pv_to_bus_kwh": ("pv_to_bus_kwh_by_depot_slot",),
         "pv_to_bess_kwh": ("pv_to_bess_kwh_by_depot_slot",),
         "bess_to_bus_kwh": ("bess_to_bus_kwh_by_depot_slot",),
         "pv_curtailed_kwh": ("pv_curtail_kwh_by_depot_slot",)}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    from tools.cluster.atomic_file import replace_bytes
    replace_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def require_coverage(trips: dict, plan: dict) -> dict[str, str]:
    """Reject missing, invented, or multiply assigned trips independently."""
    assignments = [(trip, vehicle) for vehicle, path in plan["vehicle_paths"].items() for trip in path]
    counts = Counter(trip for trip, _ in assignments)
    if (set(counts) != set(trips) or any(count != 1 for count in counts.values())
            or plan.get("unserved_trip_ids") or set(plan["served_trip_ids"]) != set(trips)):
        raise ValueError("Executed plan does not cover each declared trip exactly once")
    return dict(assignments)


def export_week(row: dict, destination: Path) -> tuple[dict, list[dict], dict]:
    docs = {}
    for name, source in row["source_evidence"].items():
        path = Path(source["path"])
        if sha(path) != source["sha256"]:
            raise ValueError(f"{row['week']}: changed {name}")
        docs[name] = read(path)
    plan, prepared = docs["executed_plan"], docs["prepared_input"]
    accounting, physical = docs["executed_day_accounting"], docs["physical_validation"]
    if not accounting["eligible"] or not physical["accepted"] or physical["violations"]:
        raise ValueError("Physical/accounting evidence did not pass")
    if accounting["executed_slot_count"] != 672 or accounting["missing_slots"] or accounting["duplicate_slots"]:
        raise ValueError("Seven-day accepted execution coverage differs")
    trips = {trip["trip_id"]: trip for trip in prepared["trips"]}
    if len(trips) != len(prepared["trips"]):
        raise ValueError("Duplicate input trip identity")
    assignment = require_coverage(trips, plan)
    vehicles = {vehicle["id"]: vehicle for vehicle in prepared["vehicles"]}
    flows = {key: aggregate_slots(plan, fields) for key, fields in FLOWS.items()}
    for key, values in flows.items():
        require_close(math.fsum(values), accounting["cost_breakdown"][key], key)
    require_close(math.fsum(day["total_cost_jpy"] for day in plan["daily_cost_ledger"]), row["total_cost"], "daily costs")
    require_close(math.fsum(trip["distance_km"] for trip in trips.values()), row["scheduled_trip_distance_km"], "service km")
    initial = {v: float(data["batteryKwh"]) * float(data["initialSoc"])
               for v, data in vehicles.items() if data["type"] == "BEV"}
    recorded_initial = plan["metadata"].get("vehicle_initial_soc_kwh_by_vehicle", {})
    for vehicle, value in recorded_initial.items():
        require_close(initial[vehicle], value, "Prepared initial vehicle energy")
    soc_rows, inventory = [], []
    for vehicle, start in initial.items():
        trace = plan["vehicle_soc_kwh_by_vehicle_slot"].get(vehicle)
        used = vehicle in plan["vehicle_paths"]
        if used and not trace:
            raise ValueError(f"Missing used vehicle SOC trace: {vehicle}")
        end = float(trace[str(max(map(int, trace)))]) if trace else start
        inventory.append({"week": row["week"], "vehicle_id": vehicle, "used": used,
                          "initial_kwh": start, "terminal_kwh": end,
                          "inventory_change_kwh": end - start,
                          "trace_basis": "solver_trace" if trace else "unused_no_events"})
        for slot, value in (trace or {}).items():
            soc_rows.append({"week": row["week"], "vehicle_id": vehicle, "state_index": int(slot),
                             "soc_kwh": value, "soc_percent": 100 * value / vehicles[vehicle]["batteryKwh"]})
    bus_charge = [0.0] * 672
    for charge in plan["charging_schedule"]:
        slot = int(charge["slot_index"])
        if 0 <= slot < 672:
            bus_charge[slot] += float(charge["charge_kw"]) * .25
    trace = plan["bess_soc_kwh_by_depot_slot"]["tsurumaki"]
    start_date = datetime.fromisoformat(row["week"])
    times = []
    for slot in range(672):
        flow = {name: values[slot] for name, values in flows.items()}
        residual = flow["grid_import_kwh"] + flow["pv_to_bus_kwh"] + flow["bess_to_bus_kwh"] - bus_charge[slot]
        if abs(residual) > 1e-6:
            raise ValueError(f"Bus charging balance at {row['week']} slot {slot}: {residual}")
        times.append({"week": row["week"], "slot": slot,
                      "interval_start_jst": (start_date + timedelta(minutes=15 * slot)).isoformat(),
                      **flow, "bus_charge_kwh": bus_charge[slot], "bess_soc_end_kwh": trace[str(slot)]})
    operations = [{"week": row["week"], "vehicle_id": assignment[trip_id],
                   "vehicle_type": vehicles[assignment[trip_id]]["type"], **trip}
                  for trip_id, trip in trips.items()]
    # Nested provenance is retained in JSON; the CSV remains a usable table.
    operation_columns = ("week", "vehicle_id", "vehicle_type", "trip_id", "service_date", "day_index",
                         "service_id", "routeCode", "direction", "origin", "destination",
                         "departure", "arrival", "distance_km", "distance_source", "operator_id")
    daily = []
    for ledger in plan["daily_cost_ledger"]:
        day = int(ledger["day_index"])
        selected = [trip for trip in operations if trip["day_index"] == day]
        daily.append({"week": row["week"], "season": SEASON[row["month"]], **ledger,
                      "trip_count": len(selected), "service_km": math.fsum(t["distance_km"] for t in selected),
                      "bev_trip_count": sum(t["vehicle_type"] == "BEV" for t in selected),
                      "ice_trip_count": sum(t["vehicle_type"] == "ICE" for t in selected),
                      **{key: math.fsum(values[day * 96:(day + 1) * 96]) for key, values in flows.items()}})
    destination.mkdir(parents=True, exist_ok=True)
    write_csv(destination / "energy_15min.csv", times)
    write_csv(destination / "vehicle_soc.csv", soc_rows)
    write_csv(destination / "vehicle_inventory.csv", inventory)
    write_csv(destination / "vehicle_schedule.csv", [{key: t.get(key) for key in operation_columns} for t in operations])
    write_csv(destination / "charging_schedule.csv", plan["charging_schedule"])
    scalar = {key: value for key, value in row.items() if not isinstance(value, (dict, list))}
    scalar.update(season=SEASON[row["month"]], cost_per_service_km_jpy=row["total_cost"] / row["scheduled_trip_distance_km"],
                  cost_per_trip_jpy=row["total_cost"] / len(trips), bev_trip_count=sum(t["vehicle_type"] == "BEV" for t in operations),
                  ice_trip_count=sum(t["vehicle_type"] == "ICE" for t in operations),
                  bev_initial_kwh=math.fsum(v["initial_kwh"] for v in inventory),
                  bev_terminal_kwh=math.fsum(v["terminal_kwh"] for v in inventory),
                  bess_initial_kwh=row["bess_terminal"]["initial_soc_kwh"],
                  bess_terminal_kwh=row["bess_terminal"]["terminal_soc_kwh"],
                  evaluation_status="VERIFIED_CONDITIONAL_WEEKLY_EVALUATION",
                  integrated_weekly_gap=None, original_research_status="DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS")
    validation = {"week": row["week"], "verified_trips": len(trips), "verified_intervals": 672,
                  "physical_evidence": physical["status"], "recomputed_trip_coverage": True,
                  "recomputed_electricity_and_cost_totals": True, "cost_tolerance_jpy": 1e-6,
                  "energy_tolerance_kwh": 1e-6, "original_physical_audit_reused_with_hash_verification": True,
                  "new_solver_run": False, "original_evidence": row["source_evidence"]}
    render_week(destination, scalar, times, soc_rows)
    return scalar, daily, validation


def plotting():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def render_week(destination: Path, row: dict, times: list[dict], soc: list[dict]) -> None:
    plt = plotting()
    fig, axes = plt.subplots(4, 1, figsize=(15, 12), sharex=True, constrained_layout=True)
    x = [t["slot"] / 4 for t in times]
    for field, label, color in (("grid_import_kwh", "買電", "#245c99"), ("pv_to_bus_kwh", "PV→バス", "#cd9400"),
                                ("bess_to_bus_kwh", "BESS→バス", "#368968"), ("bus_charge_kwh", "バス充電", "#202020")):
        axes[0].plot(x, [t[field] * 4 for t in times], label=label, color=color, linewidth=.9)
    axes[0].set_ylabel("15分平均電力 [kW]")
    axes[0].legend(ncol=4, loc="upper right")
    for field, label, color in (("pv_to_bus_kwh", "PV→バス", "#cd9400"),
                                ("pv_to_bess_kwh", "PV→BESS", "#368968"),
                                ("pv_curtailed_kwh", "PV抑制", "#b25b58")):
        axes[1].plot(x, [t[field] * 4 for t in times], label=label, color=color, linewidth=.9)
    axes[1].set_ylabel("PV配分 [kW]")
    axes[1].legend(ncol=3, loc="upper right")
    axes[2].plot(x, [t["bess_soc_end_kwh"] for t in times], color="#368968")
    axes[2].set_ylabel("BESS残量 [kWh]")
    grouped = {}
    for state in soc:
        grouped.setdefault(state["vehicle_id"], []).append(state)
    for vehicle in sorted(grouped):
        values = sorted(grouped[vehicle], key=lambda t: t["state_index"])
        axes[3].plot([t["state_index"] / 4 for t in values], [t["soc_percent"] for t in values], linewidth=.45, alpha=.65)
    axes[3].set_ylabel("記録のある全BEV SOC [%]")
    axes[3].set_ylim(0, 100)
    axes[3].set_xlabel("週開始からの経過時間 [h]（15分ごとの保存状態）")
    hours = len(times) / 4
    for ax in axes:
        for hour in range(0, int(hours) + 1, 24):
            ax.axvline(hour, color="gray", linewidth=.5, alpha=.45)
        ax.grid(alpha=.15)
        ax.set_xlim(0, hours)
    title = row.get("figure_title") or (f"渋21〜23 / {row['week']}開始の連続7日間 / 原実行7cb46894\n"
                 "電費一定・BESS補助運用・BEV終端は初期残量へ復元（翌朝SOC版とは別条件）")
    fig.suptitle(title, fontsize=13)
    fig.savefig(destination / "weekly_energy_soc.png", dpi=140)
    plt.close(fig)


def render_seasons(rows: list[dict], destination: Path) -> None:
    plt = plotting()
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    x = list(range(len(rows)))
    labels = [f"{r['month']}月\n{r['season']}" for r in rows]
    bottom = [0.] * len(rows)
    for field, label in (("vehicle_usage_cost", "車両使用費"), ("electricity_cost", "買電費"),
                         ("fuel_cost", "燃料費"), ("co2_cost", "CO2費"), ("contract_overage_cost", "契約超過費")):
        values = [r[field] / 10000 for r in rows]
        axes[0, 0].bar(x, values, bottom=bottom, label=label)
        bottom = [a + b for a, b in zip(bottom, values)]
    axes[0, 0].set_ylabel("費用内訳 [万円/週]")
    axes[0, 0].legend(fontsize=8, ncol=3)
    axes[0, 1].bar(x, [r["cost_per_service_km_jpy"] for r in rows], color="#346b97")
    axes[0, 1].set_ylabel("費用 [円/営業km・代理距離]")
    axes[1, 0].bar([v-.2 for v in x], [r["pv_generated_kwh"] / 1000 for r in rows], width=.4, label="利用可能PV")
    axes[1, 0].bar([v+.2 for v in x], [r["grid_import_kwh"] / 1000 for r in rows], width=.4, label="買電")
    axes[1, 0].set_ylabel("電力量 [MWh/週]")
    axes[1, 0].legend()
    axes[1, 1].bar(x, [r["bess_terminal_kwh"] - r["bess_initial_kwh"] for r in rows], color="#368968")
    axes[1, 1].axhline(0, color="black", linewidth=.7)
    axes[1, 1].set_ylabel("BESS在庫変化：終端−初期 [kWh]")
    for ax in axes.flat:
        ax.set_xticks(x, labels)
        ax.grid(axis="y", alpha=.15)
    fig.suptitle("渋21〜23：各月の独立7日間ケース比較（旧条件・検算済み実行可能解）\n"
                 "2025年気象・2026年固定ダイヤ／季節全体の平均やPV単独効果を表す図ではない", fontsize=13)
    fig.savefig(destination / "seasonal_cost_energy.png", dpi=145)
    fig.savefig(destination / "seasonal_cost_energy.svg")
    plt.close(fig)


def report_markdown(rows: list[dict], source: dict) -> str:
    low, high = min(rows, key=lambda r: r["total_cost"]), max(rows, key=lambda r: r["total_cost"])
    lines = ["# 渋21〜23の週次運用・費用・季節比較", "",
             f"原実行 `{source['source_git_sha']}` の{len(rows)}週を原本照合・再集計。新しい最適化は実行していない。",
             "原判定DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONSは保持する。2026-09-24の方針に従い、"
             "当時の入力条件の範囲で、検算済み解による条件付き週次評価を別表示する。実設備運用・統合最適性を認定するものではない。", "",
             "各週1,704便・7日・168時間・672区間。日付別ダイヤ・PVを使い、日をまたぐ残量を引き継いだ実行会計である。",
             "旧BEV条件は終端を個別の初期残量へ戻す設定。現在の『翌朝までに運用SOC上限へ、最終翌朝の費用も含む』設定の証拠とはしない。",
             "BESSはPVのバス充電を優先し余剰から充電、20〜80%内、系統充電なし、追加予備・終端復元なし。", "",
             "|開始日|季節|費用 円/週|円/営業km|買電 kWh|PV供給 kWh|BESS初期→終端 kWh|",
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"|{r['week']}|{r['season']}|{r['total_cost']:,.0f}|{r['cost_per_service_km_jpy']:.2f}|"
                     f"{r['grid_import_kwh']:,.1f}|{r['pv_generated_kwh']:,.1f}|{r['bess_initial_kwh']:,.1f}→{r['bess_terminal_kwh']:,.1f}|")
    lines += ["", "![週別費用・電力](seasonal_cost_energy.png)", "", "## 読み取れる結果", "",
              f"週費用は{low['month']}月の{low['total_cost']:,.0f}円から{high['month']}月の{high['total_cost']:,.0f}円まで。"
              f"差は{high['total_cost']-low['total_cost']:,.0f}円である。",
              "車両使用費は410万〜412万円/週を占める。営業量が同じ条件では、買電量だけでなく契約超過費、燃料、配車の違いも総費用へ効く。"
              "PVが多い週の費用順位をPVだけの因果効果に読み替えない。", "",
              "電費・燃費は一定で、暖房・冷房の季節負荷を計算していない。各月1週の記述的比較であり月平均や年平均ではない。"
              "BESS在庫の増減を併記し、在庫の取り崩しを翌週も繰り返せる節約としない。", "",
              "Stage1 gapは対象目的関数のもの。週全体の統合gapは未算出。各窓の充電最適性と統合最適性は異なる。"
              "車両・設備の費用根拠、距離の道路距離照合、正式fleet承認等の元の限界は継続する。", "",
              "PV/BESS設備投資・保守・劣化費は未計上。契約基準200kW超過×500円/kWhは実験の費用設定であり、"
              "実設備の物理的な受電能力や実契約料金を保証しない。", "",
              "## 原本と再利用範囲", "",
              "`weekly_summary.csv`、`daily_summary.csv`、`experiment_index.csv`と`validation_summary.json`に数値と出典を保存。"
              "各週フォルダに全便・全車両IDの運用表、充電表、SOC時系列、15分需給表と図がある。",
              "日別費用は元の確定日別台帳の配賦値（期間費用の均等配賦等を含む）。物理的な日別電力・便数と区別し、"
              "需要料金等を独自に日次・週次重複計上していない。", "",
              "二つの元シナリオの週次化ルールは確認中。同一の実PV週に置き換えると高PV/低PVの差が消えるため、"
              "存在しない比較条件を推測して8ケースへ水増ししない。確認済みの単一構成12週を先に示す。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verified-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = read(args.verified_report)
    rows, daily, validations = [], [], []
    for week in source["weeks"]:
        row, days, validation = export_week(week, args.output / week["week"])
        rows.append(row); daily.extend(days); validations.append(validation)
        print(json.dumps({"week": row["week"], "status": row["evaluation_status"]}), flush=True)
    write_csv(args.output / "weekly_summary.csv", rows)
    write_csv(args.output / "daily_summary.csv", daily)
    write_csv(args.output / "experiment_index.csv", [{"week": row["week"], "scenario": "渋21〜23・旧BESS補助運用条件",
              "source_sha": source["source_git_sha"], "reuse": "REAGGREGATED_WITH_SOURCE_HASHES",
              "evaluation_status": row["evaluation_status"], "new_run": False} for row in rows])
    write_json(args.output / "validation_summary.json", {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "source_report": str(args.verified_report), "source_report_sha256": sha(args.verified_report),
               "source_sha": source["source_git_sha"], "weeks": validations})
    write_json(args.output / "seasonal_summary.json", seasonal_summary(rows))
    render_seasons(rows, args.output)
    (args.output / "weekly_seasonal_report.md").write_text(report_markdown(rows, source), encoding="utf-8")
    write_json(args.output / "artifact_manifest.json", {str(p.relative_to(args.output)): sha(p)
               for p in args.output.rglob("*") if p.is_file() and p.name != "artifact_manifest.json"})


if __name__ == "__main__":
    main()
