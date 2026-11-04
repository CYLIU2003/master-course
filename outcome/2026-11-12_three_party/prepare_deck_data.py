"""Collect every number the 11/12 deck and the poster read, from saved verified results only.

Inputs (read-only): output/midterm_20261128/results_rc20 (summarize_midterm.py output), the rc20
executed plans and rolling summaries, results_rc20/lab_question_tables.md, the rc20 900 kW
all-diesel estimate, the rc18/rc20 recourse audits, and results_rc20_hs when it exists.
Output: deck_data_rc20.json next to this file. Nothing is solved or rewritten.
Run from the repository root:  .venv/Scripts/python.exe outcome/2026-11-12_three_party/prepare_deck_data.py
"""
import collections
import csv
import glob
import json
import re
from pathlib import Path

OPS = Path("output/midterm_20261128")
HERE = Path(__file__).parent
LIMITS = (90, 200, 400, 600, 900)
WEEKS = ("2025-01-06", "2025-04-07", "2025-07-07")
BANDS = (("05-06", 0, 7), ("07-21", 7, 22), ("22-", 22, 48))


def run_dir(campaign, limit, week):
    runs = glob.glob(str(OPS / campaign / f"{'hs' if campaign.endswith('_hs') else 'wk'}{limit:03d}" / week / "original/output/*/*"))
    return Path(runs[0]) if len(runs) == 1 else None


def main():
    cases = json.loads((OPS / "results_rc20/midterm_pillarA_cases.json").read_text(encoding="utf-8"))
    verified = {(r["grid_limit_kw"], r["week"]) for r in cases if r["status"] == "VERIFIED"}
    ice, rolling = [], []
    for limit in LIMITS:
        for week in WEEKS:
            if (limit, week) not in verified:
                continue
            run = Path(glob.glob(str(OPS / "rc20" / f"wk{limit:03d}" / week / "original/output/*/*"))[0])
            duties = json.loads((run / "rolling_hourly_chain/executed_plan.json").read_text(encoding="utf-8"))["duties"]
            total, diesel = collections.Counter(), collections.Counter()
            for duty in duties:
                for trip in duty["trip_ids"]:
                    hour = int(re.search(r"\.(\d{2})(\d{2})$", trip).group(1))
                    band = next(name for name, lo, hi in BANDS if lo <= hour < hi)
                    total[band] += 1
                    diesel[band] += duty["vehicle_type"] != "BEV"
            ice.append({"grid_limit_kw": limit, "week": week,
                        "bands": {b: {"diesel": diesel[b], "total": total[b]} for b, _, _ in BANDS}})
            statuses = collections.Counter(
                str(json.loads(Path(f).read_text(encoding="utf-8")).get("stage2_solver_status"))
                for f in glob.glob(str(run / "rolling_hourly_chain/step_*/hourly_summary.json")))
            rolling.append({"grid_limit_kw": limit, "week": week, "steps": sum(statuses.values()),
                            "time_limit": statuses.get("time_limit", 0)})
    # Q-F2 table rows as written by lab_question_tables.py.
    qf2 = []
    text = (OPS / "results_rc20/lab_question_tables.md").read_text(encoding="utf-8")
    block = text.split("## Q-F2", 1)[1].split("##", 1)[0]
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and cells[0] in ("冬", "春", "夏"):
            qf2.append({"season": cells[0], "n": int(cells[1]), "pv_generated": float(cells[2].replace(",", "")),
                        "pv_used": float(cells[3].replace(",", "")), "pv_curtailed": float(cells[4].replace(",", "")),
                        "grid_import": float(cells[5].replace(",", "")), "bus_charging": float(cells[6].replace(",", "")),
                        "grid_share_pct": float(cells[7].rstrip("%"))})
    with (OPS / "results_rc20/all_diesel_estimate.csv").open(encoding="utf-8-sig") as f:
        diesel_rows = list(csv.DictReader(f))
    audit = {name: json.loads((HERE / f"audit_stage1_recourse_{name}.json").read_text(encoding="utf-8"))
             for name in ("rc18", "rc20") if (HERE / f"audit_stage1_recourse_{name}.json").exists()}
    hs_path = OPS / "results_rc20_hs/midterm_pillarA_cases.json"
    hindsight = json.loads(hs_path.read_text(encoding="utf-8")) if hs_path.exists() else []
    first_attempt_failures = []
    for case in ("wk090/2025-07-07", "wk400/2025-01-06"):
        if glob.glob(str(OPS / "rc20" / case / "state.failed-*")):
            first_attempt_failures.append(case)
    out = {"cases": cases, "ice_by_hour": ice, "rolling": rolling, "qf2": qf2, "diesel": diesel_rows,
           "audit": audit, "hindsight": hindsight, "first_attempt_failures": first_attempt_failures}
    (HERE / "deck_data_rc20.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("cases", len(cases), "verified", len(verified), "rolling", rolling, "hindsight", len(hindsight))


if __name__ == "__main__":
    main()
