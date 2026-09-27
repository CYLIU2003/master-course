"""Read audited weekly campaigns and publish a versioned monthly comparison.

No submission, solver, source refresh, or notification is performed here.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.cluster.audit_batch import audit_batch
from tools.cluster.batch import canonical, digest
from tools.research.weekly_results import plotting, require_close, sha, write_csv, write_json


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def campaign_path(path: Path) -> Path:
    return (path.resolve().parent / read(path)["campaign"]).resolve()


def collect_verified(case: Path, week: str, operation: dict) -> tuple[dict, list[dict], dict]:
    """Recheck the archive binding; compare exported amounts to canonical accounting."""
    prepared, spec = read(case / "prepared.json"), read(case / "batch.json")
    state = read(case / "state/batch-state.json")
    row = read(case / "results/weekly_summary.json")
    if (prepared["source_git"] != {"sha": operation["git_sha"], "dirty": False}
            or prepared["parent_id"] != operation["parent"] or prepared["week"] != week
            or row["git_sha"] != operation["git_sha"] or row["week"] != week
            or spec["git_sha"] != operation["git_sha"]):
        raise ValueError("Prepared, summary or batch source differs from operation")
    audit = audit_batch(spec, state, case / "state")
    if (audit["unverified"] or len(audit["tasks"]) != 1
            or audit["tasks"][0]["task_id"] != week
            or not audit["tasks"][0].get("physical_feasibility_claim_eligible")):
        raise ValueError("Archive or recorded physical eligibility failed")
    item = state["tasks"][week]
    if row["job_id"] != item["job_id"] or row["worker_id"] != item["worker_id"]:
        raise ValueError("Summary attempt differs from collected archive")
    with zipfile.ZipFile(case / "state" / item["artifacts"]) as archive:
        names = [n for n in archive.namelist() if n.endswith("/rolling_hourly_chain/executed_day_accounting.json")]
        if len(names) != 1:
            raise ValueError("Expected one canonical executed accounting source")
        accounting = json.loads(archive.read(names[0]))
        bundle = json.loads(archive.read("bundle.json"))
        if digest(base64.b64decode(bundle["prepared_base64"], validate=True)) != prepared["prepared_sha256"]:
            raise ValueError("Prepared archive hash differs from recorded input")
    slots = 672 + prepared["overnight"]["extra_slots"]
    if (not accounting["eligible"] or accounting["missing_slots"] or accounting["duplicate_slots"]
            or accounting["executed_slot_count"] != slots or row["executed_slots_including_overnight"] != slots):
        raise ValueError("Executed week and final overnight coverage mismatch")
    for key, value in accounting["cost_breakdown"].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(float(value)) or not math.isfinite(float(row[key])):
                raise ValueError("Non-finite accounting value: " + key)
            require_close(float(row[key]), float(value), "exported " + key)
    with (case / "results/daily_summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        daily = list(csv.DictReader(stream))
    require_close(math.fsum(float(d["total_cost_jpy"]) for d in daily), row["total_cost"], "daily total")
    evidence = {"case": str(case.resolve()), "archive_sha256": item["collected_sha256"],
                "prepared_sha256": prepared["prepared_sha256"], "parent_hash": prepared["parent_hash"],
                "summary_sha256": sha(case / "results/weekly_summary.json"), "audit": audit}
    return row, [{"week": week, **d} for d in daily], evidence


def collect_reporting_recovery(folder: Path, case: Path, week: str, operation: dict) -> tuple[dict, list[dict], dict]:
    """Include a reporting repair as a separate evidence class, never job completion."""
    from tools.research.recover_weekly_reporting import verify_source
    receipt = read(folder / "recovery.json")
    if (receipt["status"] != "REPORTING_RECOVERED_CONDITIONAL_EVALUATION"
            or receipt["week"] != week or receipt["solver_git_sha"] != operation["git_sha"]
            or Path(receipt["case"]).resolve() != case.resolve() or receipt["original_worker_state"] != "FAILED"):
        raise ValueError("Reporting recovery binding mismatch")
    for name, expected in receipt["files_sha256"].items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder.resolve()) or sha(target) != expected:
            raise ValueError("Reporting recovery content changed: " + name)
    # Compare the distributed copy directly with the original ZIP. Do not follow
    # the historical output_run path in the figure receipt to another directory.
    evidence = verify_source(case, folder / "run", repaired_manifest=True)
    prepared = evidence["prepared"]
    if (prepared["parent_id"] != operation["parent"] or prepared["source_git"] != {"sha": operation["git_sha"], "dirty": False}
            or receipt["source_archive_sha256"] != evidence["source_archive_sha256"]):
        raise ValueError("Reporting recovery source differs from operation")
    audit = read(folder / "artifact-audit.json")
    if not audit["accepted"] or not evidence["original_claim"].get("physical_feasibility_claim_eligible"):
        raise ValueError("Reporting recovery artifact or physical gate failed")
    row = read(folder / "results/weekly_summary.json")
    account = read(folder / "run/rolling_hourly_chain/executed_day_accounting.json")
    slots = 672 + prepared["overnight"]["extra_slots"]
    if (row["week"] != week or row["job_id"] != evidence["item"]["job_id"] or row["git_sha"] != operation["git_sha"]
            or not account["eligible"] or account["missing_slots"] or account["duplicate_slots"]
            or account["executed_slot_count"] != slots or row["executed_slots_including_overnight"] != slots):
        raise ValueError("Recovered weekly identity or accounting coverage differs")
    for key, value in account["cost_breakdown"].items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(float(value)) or not math.isfinite(float(row[key])):
                raise ValueError("Non-finite recovery accounting")
            require_close(row[key], value, "recovered " + key)
    with (folder / "results/daily_summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        daily = list(csv.DictReader(stream))
    require_close(math.fsum(float(d["total_cost_jpy"]) for d in daily), row["total_cost"], "recovered daily total")
    proof = {"case": str(case.resolve()), "parent_hash": prepared["parent_hash"],
             "recovery": str(folder.resolve()), "recovery_receipt_sha256": sha(folder / "recovery.json"),
             "archive_sha256": evidence["source_archive_sha256"], "original_worker_state": "FAILED"}
    return row, [{"week": week, **d} for d in daily], proof


def snapshot(operations: list[Path], reporting_recoveries: list[Path] | None = None) -> dict:
    index, rows, daily, evidence = [], [], [], []
    repaired = {}
    for folder in reporting_recoveries or []:
        week = read(folder / "recovery.json")["week"]
        if week in repaired:
            raise ValueError("Duplicate reporting recovery: " + week)
        repaired[week] = folder
    identity, seen, parent_hash = None, set(), None
    for path in operations:
        operation = read(path)
        current = (operation["git_sha"], operation["parent"])
        if identity is not None and current != identity:
            raise ValueError("Cannot combine different source versions or parent scenarios")
        identity = current
        campaign = campaign_path(path)
        state = read(campaign / "state.json") if (campaign / "state.json").exists() else {}
        recovery_path = campaign / "operations/collection.json"
        recovery = read(recovery_path) if recovery_path.exists() else {}
        if state and state.get("git_sha") != operation["git_sha"]:
            raise ValueError("Campaign source differs from operation")
        for week in operation["weeks"]:
            date.fromisoformat(week)
            if week in seen:
                raise ValueError("Duplicate representative week: " + week)
            seen.add(week)
            recorded = state.get("cases", {}).get(week, {}).get("state", "NOT_STARTED")
            entry = {"week": week, "state": recorded, "campaign": str(campaign), "included": False}
            recovered = recovery.get("cases", {}).get(week, {})
            recovery_verified = (recovery.get("solver_git_sha") == operation["git_sha"]
                                  and recovered.get("state") == "VERIFIED" and recovered.get("job_id"))
            if recorded == "VERIFIED" or recovery_verified or week in repaired:
                try:
                    if week in repaired:
                        row, days, proof = collect_reporting_recovery(repaired[week], campaign / week, week, operation)
                        entry.update(state="REPORTING_RECOVERED", original_state=recorded, collection="reporting_recovery")
                    else:
                        row, days, proof = collect_verified(campaign / week, week, operation)
                    if recorded != "VERIFIED" and week not in repaired:
                        if row["job_id"] != recovered["job_id"]:
                            raise ValueError("Recovery receipt belongs to another attempt")
                        entry.update(state="VERIFIED", original_state=recorded, collection="operator_recovery")
                    if parent_hash is not None and proof["parent_hash"] != parent_hash:
                        raise ValueError("Parent input hash differs between weeks")
                    parent_hash = proof["parent_hash"]
                    rows.append(row); daily.extend(days); evidence.append(proof)
                    entry.update(included=True, job_id=row["job_id"], total_cost_jpy=row["total_cost"])
                except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                    entry.update(state="REPORT_REJECTED", error=str(exc))
            index.append(entry)
    if not index:
        raise ValueError("No declared representative weeks")
    if set(repaired) - seen:
        raise ValueError("Reporting recovery is not a declared representative week")
    return {"source_sha": identity[0], "parent": identity[1], "parent_hash": parent_hash,
            "cases": sorted(index, key=lambda r: r["week"]), "rows": sorted(rows, key=lambda r: r["week"]),
            "daily": daily, "evidence": evidence, "complete": len(rows) == len(index)}


def comparison_tables(rows: list[dict]) -> list[str]:
    """Keep recorded components separate; absent amounts are never free costs."""
    def number(row: dict, key: str) -> str:
        value = row.get(key)
        return f"{value:,.2f}" if isinstance(value, (int, float)) and math.isfinite(value) else "未記録"
    sections = [
        ("週次費用の分解 [円/週＋最終翌朝]", [
            ("total_cost", "総費用"), ("vehicle_usage_cost", "車両日費"),
            ("electricity_cost", "買電費"), ("fuel_cost", "燃料費・在庫評価"),
            ("contract_overage_cost", "契約超過モデル費"), ("co2_cost", "CO₂費"),
            ("cost_per_service_km_jpy", "円/営業km"), ("cost_per_trip_jpy", "円/便")]),
        ("電力利用・車両運用（最終翌朝を含む）", [
            ("grid_import_kwh", "買電 kWh"), ("pv_to_bus_kwh", "PV→バス kWh"),
            ("pv_to_bess_kwh", "PV→BESS kWh"), ("pv_curtailed_kwh", "PV抑制 kWh"),
            ("bess_to_bus_kwh", "BESS→バス kWh"), ("peak_grid_kw", "受電ピーク kW"),
            ("used_vehicle_day_count", "車両日数"), ("ice_fuel_consumed_l", "燃料 L")])]
    lines = []
    for title, fields in sections:
        lines += ["", "## " + title, "", "|代表週|" + "|".join(label for _, label in fields) + "|",
                  "|---|" + "---:|" * len(fields)]
        lines += ["|" + row["week"] + "|" + "|".join(number(row, key) for key, _ in fields) + "|" for row in rows]
    lines += ["", "## BESSの在庫 [kWh]", "", "|代表週|営業所|初期|終端|差（終端−初期）|", "|---|---|---:|---:|---:|"]
    for row in rows:
        for depot, values in row.get("bess_terminal", {}).items():
            lines.append("|" + row["week"] + "|" + depot + "|" + "|".join(number(values, key) for key in
                ("initial_soc_kwh", "terminal_soc_kwh", "terminal_soc_delta_kwh")) + "|")
    lines += ["", "PV→BESSとBESS→バスは別時点の流れで、合計をPV利用量としない。BESS初期在庫の由来も当該週のPVとはしない。",
              "契約超過モデル費は実際の電気料金の保証ではない。設備投資・保守・劣化等は原モデルの未計上範囲を引き継ぐ。",
              "燃料費は消費距離に基づく在庫評価を含む。総費用を現金支出だけと解釈しない。"]
    return lines


def descriptive_findings(rows: list[dict], declared: int) -> list[str]:
    """Describe audited outcomes without inferring causal or optimality effects."""
    def finite(row: dict, key: str) -> bool:
        value = row.get(key)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    lines = ["", "## 数値から読めること（記述的比較）", "",
             f"以下は集計採用した{len(rows)}/{declared}週の範囲です。未完了週をゼロや推定値で補いません。"]
    cost_rows = [r for r in rows if finite(r, "total_cost")]
    if len(cost_rows) >= 2:
        low = min(cost_rows, key=lambda r: r["total_cost"])
        high = max(cost_rows, key=lambda r: r["total_cost"])
        difference = high["total_cost"] - low["total_cost"]
        lines += [f"保存済み総費用の最小は{low['week']}開始週の{low['total_cost']:,.2f}円、"
                  f"最大は{high['week']}開始週の{high['total_cost']:,.2f}円、差は{difference:,.2f}円です。",
                  "これは取得した運用計画の費用差であり、各月の最適費用の順位や季節平均ではありません。"]
        components = [("vehicle_usage_cost", "車両日費"), ("electricity_cost", "買電費"),
                      ("fuel_cost", "燃料費・在庫評価"), ("contract_overage_cost", "契約超過モデル費"),
                      ("co2_cost", "CO₂費")]
        if all(finite(r, key) for r in (low, high) for key, _ in components):
            deltas = [(label, high[key] - low[key]) for key, label in components]
            lines += ["", "最大費用週−最小費用週の内訳（正値は最大費用週の方が高い）:", "",
                      "|費目|差 [円]|", "|---|---:|"]
            lines += [f"|{label}|{delta:,.2f}|" for label, delta in deltas]
            remainder = difference - math.fsum(delta for _, delta in deltas)
            lines += [f"|未分解の費目差（総費用差から上記差の和を引いた値）|{remainder:,.2f}|",
                      f"|総費用差|{difference:,.2f}|"]
            if abs(remainder) > 1e-6:
                lines.append("未分解の費目差が1e-6円を超えています。丸め誤差とみなさず、原会計の残る費目を確認してください。上記5費目だけでは総費用差の全額を説明できません。")
        else:
            lines.append("比較対象の費目に未記録値があるため、費用差の完全な内訳は算出していません。")
    lines.append("")
    for key, label, unit in [("grid_import_kwh", "買電量", "kWh"),
                             ("pv_to_bus_kwh", "PVからバスへの直接供給", "kWh"),
                             ("pv_to_bess_kwh", "PVからBESSへの充電", "kWh"),
                             ("pv_curtailed_kwh", "PV抑制量", "kWh"),
                             ("peak_grid_kw", "受電ピーク", "kW"),
                             ("used_vehicle_day_count", "車両日数", "車両日")]:
        values = [r[key] for r in rows if finite(r, key)]
        if values:
            lines.append(f"- {label}：{min(values):,.2f}〜{max(values):,.2f} {unit}（記録あり{len(values)}/{len(rows)}週）。")
    lines += ["", "費目差の分解は算術的な説明です。PVだけを変えた対照実験ではなく、日付別入力・配車・充電・探索到達度の差を含みます。",
              "総費用と買電・燃料費を分けて読むことで、車両日費や契約超過モデル費の変化を電力利用の効果と取り違えずに確認できます。",
              "BESS初終端差は別表を参照してください。在庫取り崩しを翌週以降も続く節約とせず、月額・年額への単純換算も行いません。"]
    return lines


def publish(result: dict, output: Path) -> Path:
    """Create an immutable report revision, then atomically publish its pointer."""
    revision = digest(canonical({"report_format": 3, "comparison": result}))
    destination = output / "revisions" / revision
    if (destination / "manifest.json").exists():
        manifest = read(destination / "manifest.json")
        for name, expected in manifest.items():
            if Path(name).name != name or sha(destination / name) != expected:
                raise ValueError("Published report content changed: " + name)
    if not (destination / "manifest.json").exists():
        destination.mkdir(parents=True, exist_ok=True)
        write_json(destination / "comparison.json", result)
        write_csv(destination / "experiment_index.csv", result["cases"])
        write_csv(destination / "weekly_summary.csv", result["rows"])
        write_csv(destination / "daily_summary.csv", result["daily"])
        lines = ["# 仮・正式用：各月の代表週の比較", "",
                 f"実行固定版 `{result['source_sha']}`。集計採用 {len(result['rows'])}/{len(result['cases'])}週。",
                 "各週は独立した連続7日間と最終翌朝の充電・受電・費用。月平均・年間連続運用ではない。",
                 "原本hashと記録済み物理判定、実行会計との一致を再確認した集計。新しい物理再求解ではない。",
                 "統合最適性・正式研究採用は別判定。未完了・検算不通過は費用比較へ含めない。", "",
                 "REPORTING_RECOVEREDは原試行の図表生成失敗を残した別出力での再検算済み集計。原ジョブの完了への変更ではない。", "",
                 "|代表週開始日|状態|週次費用 [円]|", "|---|---|---:|"]
        for case in result["cases"]:
            amount = f"{case['total_cost_jpy']:,.2f}" if case["included"] else "未確定"
            lines.append(f"|{case['week']}|{case['state']}|{amount}|")
        if result["rows"]:
            plt = plotting()
            fig, axes = plt.subplots(4, 1, figsize=(12, 14), constrained_layout=True)
            for ax, fields, label in zip(axes, [
                [("total_cost", "総費用"), ("vehicle_usage_cost", "車両日費")],
                [("electricity_cost", "買電費"), ("fuel_cost", "燃料費・在庫評価"), ("contract_overage_cost", "契約超過モデル費")],
                [("grid_import_kwh", "買電"), ("pv_to_bus_kwh", "PV→バス"), ("pv_to_bess_kwh", "PV→BESS"), ("pv_curtailed_kwh", "PV抑制")],
                [("used_vehicle_day_count", "車両日数")]], ["円/週＋最終翌朝", "円/週＋最終翌朝", "kWh/週＋最終翌朝", "車両日"]):
                for key, title in fields:
                    values = [r for r in result["rows"] if isinstance(r.get(key), (int, float)) and math.isfinite(r[key])]
                    if values:
                        ax.plot([r["week"] for r in values], [r[key] for r in values], marker="o", label=title)
                ax.set_ylabel(label)
                ax.tick_params(axis="x", rotation=35)
                ax.grid(alpha=.15)
                if ax.lines:
                    ax.legend()
            fig.suptitle("仮・正式用：検算済み代表週の費用・電力・車両利用（未記録値は除外）")
            fig.savefig(destination / "monthly_cost.png", dpi=140)
            plt.close(fig)
            lines += ["", "![週次費用](monthly_cost.png)"]
        lines += descriptive_findings(result["rows"], len(result["cases"]))
        lines += comparison_tables(result["rows"])
        lines += ["", "費目・電力量・車両台帳は各週の元resultsを参照。電費一定条件であり空調負荷差は未評価。",
                  "BESS初終端はcomparison.jsonのbess_terminalに原記録を保存。在庫取り崩しを恒常的節約やPV効果としない。",
                  "設備費等の未計上項目、受電設備・距離・fleetの仮定、元の研究判定は引き継ぐ。"]
        (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_json(destination / "manifest.json", {p.name: sha(p) for p in destination.iterdir() if p.is_file()})
    write_json(output / "latest.json", {"revision": revision, "directory": str(destination.resolve()),
               "complete": result["complete"], "included": len(result["rows"]), "declared": len(result["cases"]),
               "observed_at_utc": datetime.now(timezone.utc).isoformat()})
    return destination


def all_campaigns_terminal(states: list[Path]) -> bool:
    """A failed independent campaign must not stop collection of its live peers."""
    return bool(states) and all(
        path.exists() and read(path).get("status") in {"COMPLETED", "PARTIAL_OR_FAILED"}
        for path in states
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reporting-recovery", type=Path, action="append", default=[])
    parser.add_argument("--watch", action="store_true", help="Republish on campaign-state changes, without AI or job submission")
    args = parser.parse_args()
    previous = None
    while True:
        states = [campaign_path(p) / "state.json" for p in args.operation]
        recovery = [campaign_path(p) / "operations/collection.json" for p in args.operation]
        repaired = [p / "recovery.json" for p in args.reporting_recovery]
        fingerprint = digest(canonical({str(p): sha(p) if p.exists() else None for p in [*args.operation, *states, *recovery, *repaired]}))
        if fingerprint != previous:
            result = snapshot(args.operation, args.reporting_recovery)
            print(publish(result, args.output), flush=True)
            previous = fingerprint
            if result["complete"] or all_campaigns_terminal(states):
                return
        if not args.watch:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
