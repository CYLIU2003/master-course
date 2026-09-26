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


def snapshot(operations: list[Path]) -> dict:
    index, rows, daily, evidence = [], [], [], []
    identity, seen, parent_hash = None, set(), None
    for path in operations:
        operation = read(path)
        current = (operation["git_sha"], operation["parent"])
        if identity is not None and current != identity:
            raise ValueError("Cannot combine different source versions or parent scenarios")
        identity = current
        campaign = Path(operation["campaign"])
        state = read(campaign / "state.json") if (campaign / "state.json").exists() else {}
        if state and state.get("git_sha") != operation["git_sha"]:
            raise ValueError("Campaign source differs from operation")
        for week in operation["weeks"]:
            date.fromisoformat(week)
            if week in seen:
                raise ValueError("Duplicate representative week: " + week)
            seen.add(week)
            recorded = state.get("cases", {}).get(week, {}).get("state", "NOT_STARTED")
            entry = {"week": week, "state": recorded, "campaign": str(campaign), "included": False}
            if recorded == "VERIFIED":
                try:
                    row, days, proof = collect_verified(campaign / week, week, operation)
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
    return {"source_sha": identity[0], "parent": identity[1], "parent_hash": parent_hash,
            "cases": sorted(index, key=lambda r: r["week"]), "rows": sorted(rows, key=lambda r: r["week"]),
            "daily": daily, "evidence": evidence, "complete": len(rows) == len(index)}


def publish(result: dict, output: Path) -> Path:
    """Create an immutable report revision, then atomically publish its pointer."""
    revision = digest(canonical(result))
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
                 "|代表週開始日|状態|週次費用 [円]|", "|---|---|---:|"]
        for case in result["cases"]:
            amount = f"{case['total_cost_jpy']:,.2f}" if case["included"] else "未確定"
            lines.append(f"|{case['week']}|{case['state']}|{amount}|")
        if result["rows"]:
            plt = plotting()
            fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
            ax.bar([r["week"] for r in result["rows"]], [r["total_cost"] for r in result["rows"]])
            ax.set_ylabel("実行会計の費用 [円/週＋最終翌朝]")
            ax.tick_params(axis="x", rotation=35)
            ax.set_title("仮・正式用：検算済み代表週（未完了週は除外）")
            fig.savefig(destination / "monthly_cost.png", dpi=140)
            plt.close(fig)
            lines += ["", "![週次費用](monthly_cost.png)"]
        lines += ["", "費目・電力量・車両台帳は各週の元resultsを参照。電費一定条件であり空調負荷差は未評価。",
                  "BESS初終端はcomparison.jsonのbess_terminalに原記録を保存。在庫取り崩しを恒常的節約やPV効果としない。",
                  "設備費等の未計上項目、受電設備・距離・fleetの仮定、元の研究判定は引き継ぐ。"]
        (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_json(destination / "manifest.json", {p.name: sha(p) for p in destination.iterdir() if p.is_file()})
    write_json(output / "latest.json", {"revision": revision, "directory": str(destination.resolve()),
               "complete": result["complete"], "included": len(result["rows"]), "declared": len(result["cases"]),
               "observed_at_utc": datetime.now(timezone.utc).isoformat()})
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true", help="Republish on campaign-state changes, without AI or job submission")
    args = parser.parse_args()
    previous = None
    while True:
        states = [Path(read(p)["campaign"]) / "state.json" for p in args.operation]
        fingerprint = digest(canonical({str(p): sha(p) if p.exists() else None for p in [*args.operation, *states]}))
        if fingerprint != previous:
            result = snapshot(args.operation)
            print(publish(result, args.output), flush=True)
            previous = fingerprint
            failed = any(p.exists() and read(p).get("status") == "PARTIAL_OR_FAILED" for p in states)
            if result["complete"] or failed:
                return
        if not args.watch:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
