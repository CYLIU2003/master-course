"""Build monthly/seasonal reports from frozen execution evidence only.

This reporting entrypoint never prepares inputs or invokes an optimizer.
Default mode requires all twelve independently audited weeks; --partial writes
an explicitly incomplete monthly table without seasonal conclusions or charts.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.monthly_week_contract import validate_balanced_week
from scripts.build_four_season_interpretation import (
    COST_KEYS, FLOW_FIELDS, aggregate_slots, require_close,
)
from src.optimization.common.date_series import content_hash

SEASONS = {"冬": (12, 1, 2), "春": (3, 4, 5), "夏": (6, 7, 8), "秋": (9, 10, 11)}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_document(path: Path) -> tuple[dict, str]:
    """Retry a transient progress-file write without restarting any job."""
    for attempt in range(5):
        raw = path.read_bytes()
        try:
            return json.loads(raw), hashlib.sha256(raw).hexdigest()
        except json.JSONDecodeError:
            if attempt == 4:
                raise
            time.sleep(0.2)
    raise RuntimeError("Unreachable JSON read state")


def verify_week(week: str, audited: dict, design: dict, source_sha: str) -> dict:
    require(audited["status"] == "DIAGNOSTIC_EXECUTION_PASSED", f"{week}: incomplete independent audit")
    case = Path(audited["case_root"])
    chain = case / "rolling_hourly_chain"
    paths = {
        "case_summary": case / "summary.json",
        "executed_day_accounting": chain / "executed_day_accounting.json",
        "executed_plan": chain / "executed_plan.json",
        "physical_validation": chain / "physical_validation.json",
        "prepared_input": Path(audited["prepared_input_path"]),
    }
    documents, evidence = {}, {}
    for key, path in paths.items():
        document, digest = read_document(path)
        require(digest == audited["hashes"][key], f"{week}: {key} source hash mismatch")
        documents[key] = document
        evidence[key] = {"path": str(path), "sha256": digest}
    summary = documents["case_summary"]
    accounting = documents["executed_day_accounting"]
    plan = documents["executed_plan"]
    prepared = documents["prepared_input"]
    physical = documents["physical_validation"]
    expected_state = {"sha": source_sha, "status_porcelain": ""}
    require(summary["git_state_before"] == summary["git_state_after"] == expected_state,
            f"{week}: source state drift")
    require(summary["hourly_steps_accepted"] == 168 and summary["day_ahead_physical_accepted"]
            and summary["physical_accepted"] and physical["accepted"]
            and physical["status"] == "VALID" and not physical["violations"], f"{week}: physical gate")
    require(accounting["eligible"] and accounting["expected_slot_count"] == 672
            and accounting["executed_slot_count"] == 672 and not accounting["missing_slots"]
            and not accounting["duplicate_slots"], f"{week}: accounting or slot coverage gate")
    controls = audited["controls"]
    require(controls["pruned_arc_count"] == 0 and controls["pruned_origin_count"] == 0
            and controls["successor_pruning_enabled"] is False
            and controls["allow_postsolve_repair"] is False
            and controls["synthetic_pv_fallback_applied"] is False, f"{week}: control drift")
    contract = prepared["simulation_config"]["date_series_contract"]
    balanced = validate_balanced_week(prepared["trips"], contract, week=week)
    require(contract["source_provenance"]["holiday_source_sha256"] == design["calendar_source_sha256"],
            f"{week}: holiday source drift")
    fleet = dict(Counter(vehicle["type"] for vehicle in prepared["vehicles"]))
    require({"count": len(prepared["vehicles"]), **fleet} == design["expected_fleet"], f"{week}: fleet drift")
    cost = accounting["cost_breakdown"]
    require_close(math.fsum(day["total_cost_jpy"] for day in plan["daily_cost_ledger"]), cost["total_cost"], "daily ledger")
    require_close(math.fsum(cost[key] for key in ("vehicle_usage_cost", "electricity_cost", "fuel_cost", "co2_cost", "contract_overage_cost")), cost["total_cost"], "cost components")
    flow_fields = {**FLOW_FIELDS,
        "pv_to_bus_kwh": ("pv_to_bus_kwh_by_depot_slot",),
        "pv_to_bess_kwh": ("pv_to_bess_kwh_by_depot_slot",),
        "bess_to_bus_kwh": ("bess_to_bus_kwh_by_depot_slot",)}
    slots = {key: aggregate_slots(plan, fields) for key, fields in flow_fields.items()}
    for key, values in slots.items():
        require_close(math.fsum(values), cost[key], key)
    require_close(max(slots["grid_import_kwh"]) / 0.25, cost["peak_grid_kw"], "peak")
    require_close(cost["pv_used_total_kwh"] + cost["pv_curtailed_kwh"], cost["pv_generated_kwh"], "PV balance")
    require_close(math.fsum(max(value - 50, 0) for value in slots["grid_import_kwh"]), cost["contract_over_limit_kwh"], "200 kW contractual excess")
    require_close(cost["contract_over_limit_kwh"] * 500, cost["contract_overage_cost"], "overage price")
    terminal = accounting["bess_terminal_soc_by_depot"]["tsurumaki"]
    row = {key: cost[key] for key in COST_KEYS}
    row.update(month=int(week[5:7]), week=week, status=summary["status"],
               trip_count=summary["trip_count"], scheduled_trip_distance_km=summary["distance_km"],
               used_vehicle_count=summary["used_vehicles"], stage1_gap=summary["stage1_certified_gap"],
               hourly_steps_accepted=168, quarter_hour_slots=672, physical_violations=0,
               day_type_counts=balanced["day_type_counts"], fleet_types=fleet,
               fleet_parameters_sha256=content_hash(prepared["vehicles"]),
               chargers_sha256=content_hash(prepared["chargers"]),
               template_rows_sha256=contract["template_rows_sha256"],
               forecast_model_sha256=contract["forecast_audit"]["model_sha256"],
               non_vehicle_usage_cost_jpy=cost["total_cost"] - cost["vehicle_usage_cost"],
               pv_curtailment_pct=ratio_percent(cost["pv_curtailed_kwh"], cost["pv_generated_kwh"]),
               bess_terminal=terminal,
               bess_inventory_drawdown_kwh=terminal["initial_soc_kwh"] - terminal["terminal_soc_kwh"],
               source_evidence=evidence)
    return row


def ratio_percent(numerator: float, denominator: float) -> float | None:
    require(math.isfinite(numerator) and math.isfinite(denominator), "Non-finite ratio")
    require(denominator >= 0, "Negative ratio denominator")
    return numerator / denominator * 100 if denominator > 0 else None


def seasonal_summary(rows: list[dict]) -> list[dict]:
    """Aggregate three separate weekly cases; never label them a 21-day run."""
    by_month = {row["month"]: row for row in rows}
    require(len(by_month) == len(rows), "Duplicate monthly result")
    result = []
    for season, months in SEASONS.items():
        require(all(month in by_month for month in months), f"{season}: missing monthly result")
        selected = [by_month[month] for month in months]
        totals = {key: math.fsum(row[key] for row in selected) for key in (
            "total_cost", "non_vehicle_usage_cost_jpy", "grid_import_kwh", "pv_generated_kwh",
            "pv_used_total_kwh", "pv_curtailed_kwh", "bess_inventory_drawdown_kwh")}
        result.append({"season": season, "months": list(months), "independent_week_count": 3,
            "mean_weekly_cost_jpy": totals["total_cost"] / 3,
            "min_weekly_cost_jpy": min(row["total_cost"] for row in selected),
            "max_weekly_cost_jpy": max(row["total_cost"] for row in selected),
            "mean_weekly_non_vehicle_cost_jpy": totals["non_vehicle_usage_cost_jpy"] / 3,
            "mean_weekly_grid_import_kwh": totals["grid_import_kwh"] / 3,
            "min_weekly_grid_import_kwh": min(row["grid_import_kwh"] for row in selected),
            "max_weekly_grid_import_kwh": max(row["grid_import_kwh"] for row in selected),
            "maximum_peak_grid_kw": max(row["peak_grid_kw"] for row in selected),
            "minimum_peak_grid_kw": min(row["peak_grid_kw"] for row in selected),
            "pv_utilization_pct": ratio_percent(totals["pv_used_total_kwh"], totals["pv_generated_kwh"]),
            "pv_curtailment_pct": ratio_percent(totals["pv_curtailed_kwh"], totals["pv_generated_kwh"]),
            "three_case_inventory_drawdown_kwh": totals["bess_inventory_drawdown_kwh"]})
    return result


def report_status(campaign_status: str, completed_count: int) -> str:
    """Preserve stopped/failed states even when some weeks passed."""
    if campaign_status.startswith(("STOPPED_", "BLOCKED_")):
        return campaign_status
    if completed_count == 12:
        require(campaign_status == "COMPLETED", "Final campaign gate failed")
        return "COMPLETED"
    return "IN_PROGRESS"


def collect(campaign: Path, audit_path: Path, *, partial: bool) -> dict:
    design, _ = read_document(campaign / "design.json")
    audit, audit_hash = read_document(audit_path)
    progress, _ = read_document(campaign / "progress.json")
    require(audit["expected_sha"] == progress["base_git_sha"], "Audit belongs to another source revision")
    declared = design["campaign_declared_weeks"]
    require(len(declared) == 12 and len(set(declared)) == 12, "Twelve declared weeks required")
    rows, failed_weeks = [], []
    for week in declared:
        audited = audit["weeks"].get(week)
        if not audited or audited["status"] != "DIAGNOSTIC_EXECUTION_PASSED":
            if audited and audited.get("failure"):
                path = campaign / "cases" / week / "diagnostic" / week / "summary.json"
                failure, digest = read_document(path)
                require(digest == audited["hashes"]["case_summary"], f"{week}: failure source hash mismatch")
                failed_weeks.append({"week": week, "status": failure["status"],
                    "hourly_steps_accepted": failure.get("hourly_steps_accepted", 0),
                    "failed_hour": failure.get("failed_hour"),
                    "reasons": failure.get("hourly_reasons", failure.get("reasons", [])),
                    "source_evidence": {"path": str(path), "sha256": digest}})
            continue
        expected_case = campaign / "cases" / week / "diagnostic" / week
        require(Path(audited["case_root"]).resolve() == expected_case.resolve(), "Audit belongs to another campaign")
        rows.append(verify_week(week, audited, design, audit["expected_sha"]))
    require(bool(rows), "No independently verified completed week")
    complete = len(rows) == 12
    require(partial or complete, "Monthly campaign remains incomplete; use --partial for an explicit snapshot")
    if complete:
        final, _ = read_document(campaign / "summary.json")
        require(final["status"] == "COMPLETED" and final["source_state_stable"]
                and final["base_git_sha"] == audit["expected_sha"], "Final campaign gate failed")
    for key in ("fleet_parameters_sha256", "chargers_sha256", "template_rows_sha256", "forecast_model_sha256"):
        require(len({row[key] for row in rows}) == 1, f"Cross-month {key} mismatch")
    require(len({row["scheduled_trip_distance_km"] for row in rows}) == 1, "Scheduled distance drift")
    return {"schema_version": "monthly_result_report_v2",
        "status": report_status(progress["status"], len(rows)), "campaign_status": progress["status"],
        "source_git_sha": audit["expected_sha"], "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(rows), "declared_week_count": 12,
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        "independent_audit": {"path": str(audit_path), "sha256": audit_hash},
        "weeks": rows, "seasons": seasonal_summary(rows) if complete else [],
        "failed_weeks": failed_weeks,
        "pending_weeks": [week for week in declared if week not in {row["week"] for row in rows}]}


def render_figure(rows: list[dict], destination: Path, *, is_layout_preview: bool = False) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({"font.size": 10, "axes.unicode_minus": False, "svg.fonttype": "none"})
    figure, axes = plt.subplots(2, 3, figsize=(17, 10))
    x = [row["month"] for row in rows]
    panels = list(axes.flat)
    bottom = [0.0] * len(rows)
    for key, label, color in (("pv_to_bus_kwh", "バスへ直接", "#2a8278"),
                               ("pv_to_bess_kwh", "BESSへ充電", "#95c8aa"),
                               ("pv_curtailed_kwh", "抑制", "#d9d6cd")):
        values = [row[key] / 1000 for row in rows]
        panels[0].bar(x, values, bottom=bottom, label=label, color=color)
        bottom = [a + b for a, b in zip(bottom, values)]
    panels[0].set(title="PV発電の行き先", ylabel="MWh / 選択週")
    panels[0].legend(fontsize=9)
    for axis, key, scale, title, unit in ((panels[1], "grid_import_kwh", 1000, "購入電力量", "MWh / 選択週"),
        (panels[2], "peak_grid_kw", 1, "最大15分平均受電", "kW"),
        (panels[4], "total_cost", 10000, "確定総費用", "万円 / 選択週"),
        (panels[5], "used_vehicle_day_count", 1, "使用車両日数", "台・日 / 選択週")):
        bars = axis.bar(x, [row[key] / scale for row in rows], color="#466e99")
        if key == "used_vehicle_day_count":
            axis.bar_label(bars, fmt="%d", padding=3, fontsize=9)
        axis.set(title=title, ylabel=unit)
    panels[2].axhline(200, color="#b26c36", linestyle="--", label="契約基準 200 kW（有料超過可）")
    panels[2].legend(fontsize=8)
    bottom = [0.0] * len(rows)
    for key, label, color in (("electricity_cost", "購入電力", "#466e99"), ("fuel_cost", "燃料", "#be9853"),
                               ("co2_cost", "CO₂", "#91a479"), ("contract_overage_cost", "契約超過", "#b85e57")):
        values = [row[key] / 10000 for row in rows]
        panels[3].bar(x, values, bottom=bottom, label=label, color=color)
        bottom = [a + b for a, b in zip(bottom, values)]
    panels[3].set(title="車両使用費以外の内訳", ylabel="万円 / 選択週")
    panels[3].legend(fontsize=8)
    for axis in panels:
        axis.margins(y=.25)
        axis.set_xticks(x, [f"{month}月" for month in x])
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    title = ("表示確認用の仮データ（研究結果ではありません）" if is_layout_preview
             else "各月1週・平日5日＋土休日2日の診断結果")
    figure.suptitle(title, fontsize=19)
    figure.text(.03, .035, "2025年の選択週／同じ時刻表・60台入力・全接続保持。月平均・年平均の推計ではありません。\n"
                "各週は同じ初期状態から開始。BESS初期在庫を使用する条件。最適性gap・研究採用条件は未達。", fontsize=11)
    figure.tight_layout(rect=(0, .085, 1, .95), h_pad=3)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination.with_suffix(".png"), dpi=170)
    figure.savefig(destination.with_suffix(".svg"), metadata={"Date": None})
    svg = destination.with_suffix(".svg")
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(figure)


def cost_difference(rows: list[dict]) -> dict:
    """Explain the observed highest-minus-lowest weekly cost without causality."""
    highest = max(rows, key=lambda row: row["total_cost"])
    lowest = min(rows, key=lambda row: row["total_cost"])
    difference = {key: highest[key] - lowest[key] for key in (
        "total_cost", "vehicle_usage_cost", "non_vehicle_usage_cost_jpy")}
    require_close(difference["vehicle_usage_cost"] + difference["non_vehicle_usage_cost_jpy"],
                  difference["total_cost"], "monthly cost difference")
    return {"highest_month": highest["month"], "lowest_month": lowest["month"], **difference}


def observation_paragraphs(data: dict) -> list[str]:
    """Describe completed cases and distinguish arithmetic from explanations."""
    require(data["status"] == "COMPLETED", "Observations require a completed campaign")
    rows = data["weeks"]
    pv_high = max(rows, key=lambda row: row["pv_generated_kwh"])
    pv_low = min(rows, key=lambda row: row["pv_generated_kwh"])
    grid_high = max(rows, key=lambda row: row["grid_import_kwh"])
    grid_low = min(rows, key=lambda row: row["grid_import_kwh"])
    season_high = max(data["seasons"], key=lambda row: row["mean_weekly_grid_import_kwh"])
    season_low = min(data["seasons"], key=lambda row: row["mean_weekly_grid_import_kwh"])
    peak = max(rows, key=lambda row: row["peak_grid_kw"])
    difference = cost_difference(rows)
    inventory = [row["bess_inventory_drawdown_kwh"] for row in rows]
    return [
        f"選択した12週のPV発電量は{pv_high['month']}月の{pv_high['pv_generated_kwh']:,.1f} kWhが最多、"
        f"{pv_low['month']}月の{pv_low['pv_generated_kwh']:,.1f} kWhが最少だった。購入電力量は"
        f"{grid_high['month']}月の{grid_high['grid_import_kwh']:,.1f} kWhが最多、"
        f"{grid_low['month']}月の{grid_low['grid_import_kwh']:,.1f} kWhが最少で、差は"
        f"{grid_high['grid_import_kwh'] - grid_low['grid_import_kwh']:,.1f} kWhだった。"
        "PV総量と購入量の対応を解釈するには、直接利用・BESS充電・抑制と充電時刻の対応も確認する必要がある。",
        f"季節ごとの選択3週では、平均購入量は{season_high['season']}の"
        f"{season_high['mean_weekly_grid_import_kwh']:,.1f} kWh/週が最多、{season_low['season']}の"
        f"{season_low['mean_weekly_grid_import_kwh']:,.1f} kWh/週が最少だった。"
        f"それぞれの平均週間費用は{season_high['mean_weekly_cost_jpy']:,.0f}円と"
        f"{season_low['mean_weekly_cost_jpy']:,.0f}円である。"
        "月ごとの範囲も併記し、この3週平均を季節全体の期待値や統計的な季節効果とは扱わない。",
        f"週間総費用の最大月{difference['highest_month']}月と最小月{difference['lowest_month']}月の差は"
        f"{difference['total_cost']:,.2f}円で、車両使用費の差{difference['vehicle_usage_cost']:+,.2f}円と、"
        f"電力・燃料・CO₂・契約超過費の合計差{difference['non_vehicle_usage_cost_jpy']:+,.2f}円に分かれる"
        "（ともに最大月から最小月を引いた符号付きの差）。使用車両日数と割当も求解で変わるため、"
        "総費用の差からPV単独の削減効果を取り出すことはできない。",
        f"最大15分平均受電が最も高かったのは{peak['month']}月の{peak['peak_grid_kw']:,.1f} kWで、"
        f"その週の契約超過費は{peak['contract_overage_cost']:,.2f}円だった。"
        "契約基準200 kWは有料超過を許す条件であり、購入電力量と受電ピークを別々に評価する。"
        "充電時刻や受電制限の政策を変える効果は、同じ気象・配車条件を固定した追加比較で確かめる必要がある。",
        f"各週のBESS在庫減少量（初期−終端）は{min(inventory):,.1f}〜{max(inventory):,.1f} kWhだった。"
        "毎週同じ初期状態から始めた計算なので、この在庫利用を繰り返し使える運用上の節約とは解釈しない。"
        "PVからBESSへの充電はPV利用として数えるが、その全量が評価週内にバスへ供給されたことまでは示さない。",
    ]


def markdown(data: dict, figure_name: str | None) -> str:
    complete = data["status"] == "COMPLETED"
    lines = ["# 月別12週の結果" + ("" if complete else "（途中経過）"), "",
        f"更新: {data['generated_at_utc']}。**{data['completed_count']}/12週が完了**。固定版 `{data['source_git_sha'][:8]}` の確定会計を掲載する。",
        "", "各週は平日5日・土曜1日・日曜1日。同じ時刻表原本、車両60台（BEV35・ICE25）のパラメータ、充電器、予測モデルをハッシュで照合した。完了週は各168時間・672 slot、物理違反0件、日別台帳との差1e-6円以内を確認済み。", "",
        "| 月 | 開始日 | 確定総費用［円］ | 車両日数 | 車両使用費以外［円］ | 購入量［kWh］ | ピーク［kW］ | PV抑制率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    if data["status"].startswith(("STOPPED_", "BLOCKED_")):
        lines[3:3] = [f"**実行状態: `{data['status']}`。計算プロセスは停止しており、原因調査中。**", ""]
    for row in data["weeks"]:
        rate = f"{row['pv_curtailment_pct']:.2f}%" if row["pv_curtailment_pct"] is not None else "算出不可"
        lines.append(f"| {row['month']}月 | {row['week']} | {row['total_cost']:,.6f} | {row['used_vehicle_day_count']} | {row['non_vehicle_usage_cost_jpy']:,.6f} | {row['grid_import_kwh']:,.3f} | {row['peak_grid_kw']:,.3f} | {rate} |")
    if figure_name:
        lines += ["", f"![月別比較](figures/{figure_name}.png)", "", f"[編集可能なSVG](figures/{figure_name}.svg)"]
    if complete:
        lines += ["", "## 季節別の記述的比較", "", "各季節3つの独立した7日間ケース。連続21日間の運用結果ではない。費用と購入量は選択週当たり平均、PV率は3週の合計量から求める。", "",
            "| 季節 | 平均週間費用［円］ | 費用の最小〜最大［円］ | 平均購入量［kWh/週］ | 購入量の最小〜最大［kWh/週］ | 受電ピーク範囲［kW］ | 合計量でのPV抑制率 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for row in data["seasons"]:
            rate = f"{row['pv_curtailment_pct']:.2f}%" if row["pv_curtailment_pct"] is not None else "算出不可"
            lines.append(f"| {row['season']} | {row['mean_weekly_cost_jpy']:,.2f} | {row['min_weekly_cost_jpy']:,.2f}〜{row['max_weekly_cost_jpy']:,.2f} | {row['mean_weekly_grid_import_kwh']:,.3f} | {row['min_weekly_grid_import_kwh']:,.3f}〜{row['max_weekly_grid_import_kwh']:,.3f} | {row['minimum_peak_grid_kw']:.3f}〜{row['maximum_peak_grid_kw']:.3f} | {rate} |")
        lines += ["", "## 観察と示唆"]
        for paragraph in observation_paragraphs(data):
            lines += ["", paragraph]
    else:
        lines += ["", "未確定の週: " + "、".join(data["pending_weeks"]) + "。費用を0として扱わず、全12週と季節別の整理を継続する。"]
        for failed in data.get("failed_weeks", []):
            lines += ["", f"- {failed['week']}開始週: `{failed['status']}`。{failed['hourly_steps_accepted']}/168時間まで受理。週間会計は未成立。理由: " + " / ".join(failed["reasons"])]
    lines += ["", "## 原本・定義・限界", "",
        "費用原本は各週の `rolling_hourly_chain/executed_day_accounting.json`。日別台帳、PV/購入flowの672 slot合計、ピーク、費用内訳、契約超過量×500円/kWhを再照合した。丸め前の値と原本パス・SHAは同名JSONに保存する。PV利用量はバスへの直接供給とBESSへの充電の和であり、BESS放電を再加算しない。営業便距離は停留所座標に基づく地理的代理距離で、回送を含む実道路走行距離ではない。", "",
        "[選択週の日射量と月全体の比較](SHIBU21_23_MONTHLY_IRRADIANCE_CONTEXT_20260914.md)では、3月の選択週は月全体の日平均GHIより35.2%少なく、10月は20.2%多い。週選択は固定し、この天候条件も解釈へ含める。冬12/1/2月は同年内の非連続な週である。", "",
        "各週は同じ初期状態へ戻して開始する。BESSは初期3,000 kWhから最低1,200 kWhまで使える条件で、在庫減少をJSONに併記する。季節別の合計を連続21日間の費用とは扱わない。2026年時刻表・2025年評価日・2024年のみのclimatology予測であり、実運行再現やSolcast予測技能を示さない。", "",
        "季節別入力は日付ごとのPV履歴と学習済みPV予測を扱う。走行需要は固定の電費・燃費を用いた距離ベースの設定で、気温に応じた空調負荷の月別変化は入力していない。したがって、結果を冷暖房等を含む季節的な需要変化の評価とは解釈しない。", "",
        "同じseed・threads・時間制限でも、各月の探索の到達度が同じとは限らない。費用の順位は、その条件で得られた実行可能解の順位として読む。Stage 1 gapはその目的関数の最適性指標であり、確定週間費用の誤差幅・信頼区間や季節差の統計的有意性を表さない。", "",
        "Stage 1 gap、二段階解法の統合最適性、正式research fleet contract、既存PowerPoint証拠2件の採用条件は別に残る。**DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS、研究採用BLOCKED**。各月1週から月平均・年平均・季節一般やPV単独の因果を主張しない。", "",
        "[選択日・固定条件・集計規則](SHIBU21_23_MONTHLY_FAIR_WEEKS_20260914.md)"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/notes/SHIBU21_23_MONTHLY_RESULTS_20260914")
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    data = collect(args.campaign, args.audit, partial=args.partial)
    figure_name = "shibu21_23_monthly_20260914" if data["status"] == "COMPLETED" else None
    if figure_name:
        render_figure(data["weeks"], args.output.parent / "figures" / figure_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(data, figure_name), encoding="utf-8")
    print(json.dumps({"status": data["status"], "completed_weeks": data["completed_count"], "report": str(args.output.with_suffix('.md'))}))


if __name__ == "__main__":
    main()
