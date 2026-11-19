"""How the objective decreased before the time limit, tariff A (rc42 et), for Prof. Urabe's question of 2026-11-19.

Read-only inputs: output/midterm_20261128/rc42/et<b|i><limit>/<week>/original/output/<date>/run_*/ (and the single
24 GiB rerun rc42m24/etb200m24/2025-07-07 that replaces the failed first attempt, as in prepare_deck_data_rc42.py).

Two time-limited searches are summarized for every one of the 24 tariff-A runs (2 initial assignments x 12 cases):
1. Stage 1 (trip assignment): the LNS record diagnostics/stage1_lns.json. Each iteration has its duration (sec) and the
   best weekly objective so far (best_objective, JPY, the Stage 1 planning objective - not the executed accounting).
   The LNS stops at its time budget (settings.time_budget_sec); it is a heuristic and never an optimality certificate.
2. Hourly re-plans (Stage 2 of each rolling step, 300 s limit): every diagnostics/stage2_native_*.log that ends with
   "Time limit reached". The Gurobi progress table gives (time, incumbent, best bound, gap). The earliest stage2 log of a
   run is the day-ahead plan; the others are the rolling steps, and their time-limit count is checked against the
   step summaries (stage2_solver_status == "time_limit").
Output: cutoff_trajectory_rc42_et.json (no numbers are changed; ratios are computed from the logged values).
"""
import collections
import glob
import json
import re
from pathlib import Path

OPS = Path("output/midterm_20261128")
WEEKS = ("2025-01-06", "2025-04-07", "2025-07-07")
LIMITS = (90, 200, 400, 900)
MEM24 = {(200, "2025-07-07", "bev")}
CHECK_T = (10, 30, 60, 120, 180, 240)


def run_dir(limit, week, start):
    k = "b" if start == "bev" else "i"
    if (limit, week, start) in MEM24:
        pat = OPS / "rc42m24" / f"et{k}{limit:03d}m24" / week / "original/output/2026-*/run_*"
    else:
        pat = OPS / "rc42" / f"et{k}{limit:03d}" / week / "original/output/2026-*/run_*"
    runs = sorted(glob.glob(str(pat)))
    if len(runs) != 1:
        raise SystemExit(f"expected one run for {limit} {week} {start}: {runs}")
    return Path(runs[0])


def parse_log(path):
    rows, final = [], None
    in_table = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Expl Unexpl" in line:
            in_table = True
            continue
        if line.startswith("Best objective"):
            m = re.match(r"Best objective ([^,]+), best bound ([^,]+), gap (.+)$", line)
            final = {"objective": float(m.group(1)), "bound": None if m.group(2).strip() == "-" else float(m.group(2)),
                     "gap_pct": None if m.group(3).strip() == "-" else float(m.group(3).rstrip("%"))}
        if not in_table or not line.strip():
            continue
        tok = line.split()
        if not tok[-1].endswith("s") or not re.fullmatch(r"\d+s", tok[-1]):
            in_table = False if line.startswith(("Explored", "Cutting")) else in_table
            continue
        inc = tok[-5]
        rows.append({"t": int(tok[-1][:-1]), "incumbent": None if inc == "-" else float(inc),
                     "bound": float(tok[-4]) if re.fullmatch(r"[-\d.e+]+", tok[-4]) else None})
    return rows, final


def summarize_step(rows, final):
    best = final["objective"]
    inc_rows = [r for r in rows if r["incumbent"] is not None]
    t_first = inc_rows[0]["t"] if inc_rows else None
    t_last = next((r["t"] for r in inc_rows if abs(r["incumbent"] - best) <= 1e-6 * max(1.0, abs(best))), None)
    at = {}
    for t in CHECK_T:
        cur = [r["incumbent"] for r in inc_rows if r["t"] <= t]
        at[str(t)] = None if not cur else (cur[-1] - best) / abs(best) * 100.0
    return {"t_first_incumbent_s": t_first, "t_final_incumbent_s": t_last, "final_objective": best,
            "final_bound": final["bound"], "final_gap_pct": final["gap_pct"], "excess_over_final_pct_at_s": at}


out = {"source": "rc42 tariff A (et), 24 runs", "check_times_s": CHECK_T, "runs": []}
for limit in LIMITS:
    for week in WEEKS:
        for start in ("bev", "ice"):
            run = run_dir(limit, week, start)
            lns = json.loads((run / "diagnostics/stage1_lns.json").read_text(encoding="utf-8"))
            t, traj = lns["initial_load_sec"], [[0.0, lns["initial_objective"]]]
            for it in lns["iterations"]:
                t += it["sec"]
                traj.append([round(t, 1), it["best_objective"]])
            logs = sorted(glob.glob(str(run / "diagnostics/stage2_native_*.log")))
            steps = collections.Counter(json.loads(Path(f).read_text(encoding="utf-8")).get("stage2_solver_status")
                                        for f in glob.glob(str(run / "rolling_hourly_chain/step_*/hourly_summary.json")))
            limited = []
            day_ahead_limited = False
            for i, f in enumerate(logs):
                txt = Path(f).read_text(encoding="utf-8", errors="replace")
                if "Time limit reached" not in txt:
                    continue
                if i == 0:
                    day_ahead_limited = True
                    continue
                rows, final = parse_log(Path(f))
                limited.append(summarize_step(rows, final))
            if len(limited) != steps.get("time_limit", 0):
                raise SystemExit(f"{run}: {len(limited)} time-limited logs vs {steps.get('time_limit', 0)} time_limit steps")
            out["runs"].append({
                "grid_limit_kw": limit, "week": week, "start": start, "run": str(run).replace("\\", "/"),
                "stage1": {"time_budget_sec": lns["settings"]["time_budget_sec"], "elapsed_sec": lns["elapsed_sec"],
                           "iterations": len(lns["iterations"]), "initial_objective": lns["initial_objective"],
                           "best_objective": lns["best_objective"], "trajectory_sec_objective": traj,
                           "semantics": lns["semantics"]},
                "hourly": {"steps": sum(steps.values()), "time_limit_steps": len(limited),
                           "day_ahead_stage2_time_limited": day_ahead_limited, "time_limited_steps": limited}})
Path("outcome/2026-11-12_three_party/cutoff_trajectory_rc42_et.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", len(out["runs"]), "runs")
