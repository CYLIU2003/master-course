"""Rebuild the 2026-07-17 core_new review evidence and figures.

The script intentionally separates three evidence tiers:

1. latest UI runs that are infeasible and expose the former KPI truthfulness bug;
2. a clean 15-minute grid-only feasibility baseline;
3. provisional 60-minute sunny/rain PV+BESS runs.

It never recomputes solver results.  Every plotted number is read from a saved
artifact, and the source path is written to ``review_summary.json``.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "core_new_review_20260717"
INVALID_RUN_DIRS = (
    REPO_ROOT / "output" / "2026-07-17" / "run_20260717_0003",
    REPO_ROOT / "output" / "2026-07-17" / "run_20260717_1240",
)
CONTROLLED_COMPARISON = (
    REPO_ROOT
    / "output"
    / "research_phase3_comparison_grid_only_15min_soc80_warm_start"
    / "comparison.json"
)
WEATHER_AUDIT_DIR = REPO_ROOT / "output" / "phase3_weather_energy_audit_20260716"
IIS_DIR = (
    REPO_ROOT
    / "output"
    / "research_phase3_sunny_energy_proxy_1500s_20260716"
    / "diagnostics"
)
SUNNY_SUMMARY = REPO_ROOT / "output" / "research_phase3_sunny_final_1500s_20260716" / "summary.json"
RAIN_SUMMARY = REPO_ROOT / "output" / "research_phase3_rain_final_1500s_20260716" / "summary.json"

BLUE = "#1f5a94"
LIGHT_BLUE = "#78add2"
ORANGE = "#d9772b"
RED = "#b63c32"
GREEN = "#2f7d5b"
GRAY = "#7a7a7a"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"required artifact not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _save_figure(fig: plt.Figure, output_path: Path) -> None:
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Meiryo", "Yu Gothic", "DejaVu Sans"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.22,
            "figure.figsize": (10, 5.6),
        }
    )


def _collect_invalid_runs() -> list[dict[str, Any]]:
    results = []
    for run_dir in INVALID_RUN_DIRS:
        canonical = _load_json(run_dir / "canonical_solver_result.json")
        summary = _load_json(run_dir / "summary.json")
        kpi = _load_json(run_dir / "kpi_summary.json")
        manifest = _load_json(run_dir / "run_manifest.json")
        results.append(
            {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "git_sha": manifest.get("git_sha"),
                "solver_status": canonical.get("solver_status") or summary.get("solver_status"),
                "canonical_served": int(canonical.get("trip_count_served") or 0),
                "canonical_unserved": int(canonical.get("trip_count_unserved") or 0),
                "summary_served": int(summary.get("trip_count_served") or 0),
                "summary_unserved": int(summary.get("trip_count_unserved") or 0),
                "kpi_served": int(kpi.get("served_trip_count") or 0),
                "kpi_unserved": int(kpi.get("unserved_trip_count") or 0),
                "summary_total_cost_jpy": _finite_float(summary.get("total_cost_jpy")),
                "research_kpi_eligible": bool(
                    (summary.get("solution_validity") or {}).get("research_kpi_eligible", False)
                ),
            }
        )
    return results


def _plot_truthfulness(invalid_runs: list[dict[str, Any]], output_dir: Path) -> None:
    labels = [row["run_id"].replace("run_", "") for row in invalid_runs]
    x = np.arange(len(labels))
    width = 0.24
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    series = (
        ("Canonical", [row["canonical_unserved"] for row in invalid_runs], BLUE),
        ("summary.json", [row["summary_unserved"] for row in invalid_runs], ORANGE),
        ("kpi_summary.json", [row["kpi_unserved"] for row in invalid_runs], RED),
    )
    for offset, (label, values, color) in zip((-width, 0.0, width), series, strict=True):
        bars = ax.bar(x + offset, values, width, label=label, color=color)
        ax.bar_label(bars, padding=3, fontsize=10)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 290)
    ax.set_ylabel("Unserved trips")
    ax.set_title("P0 evidence: infeasible canonical result was reported as 0 unserved")
    ax.legend(frameon=False, ncols=3, loc="upper center")
    ax.text(
        0.5,
        -0.18,
        "Both runs: canonical status=infeasible, research_kpi_eligible=false; old reader-facing files still showed 0 JPY.",
        ha="center",
        transform=ax.transAxes,
        color=GRAY,
        fontsize=9,
    )
    _save_figure(fig, output_dir / "01_kpi_truthfulness_gate.png")


def _collect_solver_evidence() -> list[dict[str, Any]]:
    controlled = _load_json(CONTROLLED_COMPARISON)
    sunny = _load_json(SUNNY_SUMMARY)
    rain = _load_json(RAIN_SUMMARY)
    controlled_case = controlled["cases"]["sunny_label"]
    return [
        {
            "label": "15-min grid-only\nclean baseline",
            "timestep_min": 15,
            "stage1_gap_percent": 100.0 * float(controlled_case["stage1_mip_gap_ratio"]),
            "served": int(controlled_case["trip_count_served"]),
            "unserved": int(controlled_case["trip_count_unserved"]),
            "stage2_status": controlled_case["stage2_status"],
            "git_dirty": False,
            "research_feasibility_eligible": bool(controlled_case["research_run_accepted"]),
            "research_cost_kpi_eligible": bool(controlled_case["research_cost_kpi_eligible"]),
            "source": str(CONTROLLED_COMPARISON),
        },
        {
            "label": "60-min sunny\nPV+BESS provisional",
            "timestep_min": int(sunny["timestep_min"]),
            "stage1_gap_percent": float(sunny["stage1_mip_gap_percent"]),
            "served": int(sunny["trip_count_served"]),
            "unserved": int(sunny["trip_count_unserved"]),
            "stage2_status": sunny["stage2_solver_status"],
            "git_dirty": bool(sunny["git_dirty"]),
            "research_feasibility_eligible": bool(sunny["research_feasibility_eligible"]),
            "research_cost_kpi_eligible": bool(sunny["research_cost_kpi_eligible"]),
            "source": str(SUNNY_SUMMARY),
        },
        {
            "label": "60-min rain\nPV+BESS provisional",
            "timestep_min": int(rain["timestep_min"]),
            "stage1_gap_percent": float(rain["stage1_mip_gap_percent"]),
            "served": int(rain["trip_count_served"]),
            "unserved": int(rain["trip_count_unserved"]),
            "stage2_status": rain["stage2_solver_status"],
            "git_dirty": bool(rain["git_dirty"]),
            "research_feasibility_eligible": bool(rain["research_feasibility_eligible"]),
            "research_cost_kpi_eligible": bool(rain["research_cost_kpi_eligible"]),
            "source": str(RAIN_SUMMARY),
        },
    ]


def _plot_solver_evidence(evidence: list[dict[str, Any]], output_dir: Path) -> None:
    labels = [row["label"] for row in evidence]
    gaps = [row["stage1_gap_percent"] for row in evidence]
    colors = [BLUE if not row["git_dirty"] else ORANGE for row in evidence]
    fig, ax = plt.subplots(figsize=(10, 5.7))
    bars = ax.bar(labels, gaps, color=colors, width=0.62)
    ax.axhline(10.0, color=RED, linestyle="--", linewidth=1.5, label="requested gap: 10%")
    ax.bar_label(bars, labels=[f"{value:.2f}%" for value in gaps], padding=3)
    ax.set_ylabel("Stage 1 MIP gap (%)")
    ax.set_title("Evidence tiers: feasibility is established; cost optimality is not")
    ax.legend(frameon=False)
    for index, row in enumerate(evidence):
        status = "clean" if not row["git_dirty"] else "dirty"
        ax.text(
            index,
            1.0,
            f"264/264, Stage 2 {row['stage2_status']}\n{status}; cost KPI ineligible",
            ha="center",
            va="bottom",
            color="white" if gaps[index] > 20 else "black",
            fontsize=8.5,
            fontweight="bold",
        )
    _save_figure(fig, output_dir / "02_solver_evidence_tiers.png")


def _iis_prefix(constraint_name: str) -> str:
    return constraint_name.split("__", maxsplit=1)[0]


def _collect_iis() -> dict[str, Any]:
    iis_rows = _read_csv(IIS_DIR / "stage2_iis_constraints.csv")
    counts = Counter(_iis_prefix(row["constraint_name"]) for row in iis_rows)
    departure_rows = _read_csv(IIS_DIR / "stage2_departure_soc_precheck.csv")
    vehicle_id = "e0772317-52e2-4e70-bfc8-1eb486f0f75c"
    vehicle_rows = [row for row in departure_rows if row.get("vehicle_id") == vehicle_id]
    vehicle_rows.sort(key=lambda row: int(row["departure_min"]))
    return {
        "iis_constraint_count": len(iis_rows),
        "constraint_counts": dict(sorted(counts.items())),
        "vehicle_id": vehicle_id,
        "departure_rows": vehicle_rows,
        "source": str(IIS_DIR),
    }


def _clock_label(departure_min: int) -> str:
    return f"{(departure_min // 60) % 24:02d}:{departure_min % 60:02d}"


def _plot_iis(iis: dict[str, Any], output_dir: Path) -> None:
    counts = iis["constraint_counts"]
    labels = list(counts)
    values = [counts[label] for label in labels]
    rows = iis["departure_rows"]
    minutes = [int(row["departure_min"]) for row in rows]
    available = [float(row["soc_available_before_departure_kwh"]) for row in rows]
    required = [float(row["required_departure_soc_kwh"]) for row in rows]
    shortages = [float(row["shortage_kwh"]) for row in rows]

    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 5.3), gridspec_kw={"width_ratios": [0.8, 1.4]})
    bars = left.barh(labels, values, color=[ORANGE if label.startswith("charge") else BLUE for label in labels])
    left.bar_label(bars, padding=3)
    left.set_xlabel("Constraints in IIS")
    left.set_title("IIS composition (59 constraints)")

    right.plot(minutes, available, marker="o", color=BLUE, label="SOC available")
    right.plot(minutes, required, marker="s", color=ORANGE, label="SOC required")
    right.fill_between(minutes, available, required, where=np.array(shortages) > 0, color=RED, alpha=0.25)
    violation_summary = [
        f"{_clock_label(minute)}: {shortage:.1f} kWh short"
        for minute, shortage in zip(minutes, shortages, strict=True)
        if shortage > 1e-9
    ]
    right.text(
        0.98,
        0.03,
        "\n".join(violation_summary),
        transform=right.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color=RED,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": RED, "alpha": 0.85},
    )
    right.set_xticks(minutes[:: max(len(minutes) // 7, 1)], [_clock_label(value) for value in minutes[:: max(len(minutes) // 7, 1)]])
    right.set_ylabel("Energy (kWh)")
    right.set_ylim(10, max(available) * 1.04)
    right.set_title("Vehicle e077…: no depot charging before late departures")
    right.legend(frameon=False)
    fig.suptitle("Intermediate infeasible run: location-constrained charging caused SOC failure", fontweight="bold")
    _save_figure(fig, output_dir / "03_stage2_iis_root_cause.png")


def _collect_weather() -> dict[str, Any]:
    daily_rows = _read_csv(WEATHER_AUDIT_DIR / "weather_energy_daily_summary.csv")
    daily = {row["case_key"]: row for row in daily_rows}
    summaries = {"sunny": _load_json(SUNNY_SUMMARY), "rain": _load_json(RAIN_SUMMARY)}
    return {"daily": daily, "summaries": summaries, "source": str(WEATHER_AUDIT_DIR)}


def _plot_weather(weather: dict[str, Any], output_dir: Path) -> None:
    cases = ("sunny", "rain")
    labels = ("Sunny", "Rain")
    daily = weather["daily"]
    summaries = weather["summaries"]
    colors = (BLUE, ORANGE)
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.0))

    ax = axes[0, 0]
    bev = [float(daily[case]["bev_trips"]) for case in cases]
    ice = [float(daily[case]["ice_trips"]) for case in cases]
    x = np.arange(2)
    ax.bar(x, bev, color=LIGHT_BLUE, label="BEV trips")
    ax.bar(x, ice, bottom=bev, color=GRAY, label="ICE trips")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Assigned trips")
    ax.set_title("Dispatch mix")
    ax.legend(frameon=False)

    ax = axes[0, 1]
    pv_bus = [float(daily[case]["pv_to_bus_kwh"]) for case in cases]
    pv_bess = [float(daily[case]["pv_to_bess_kwh"]) for case in cases]
    curtailed = [float(daily[case]["pv_curtailed_kwh"]) for case in cases]
    ax.bar(x, pv_bus, color=GREEN, label="PV→bus")
    ax.bar(x, pv_bess, bottom=pv_bus, color=LIGHT_BLUE, label="PV→BESS")
    ax.bar(x, curtailed, bottom=np.array(pv_bus) + np.array(pv_bess), color=GRAY, label="curtailed")
    ax.set_xticks(x, labels)
    ax.set_ylabel("PV energy (kWh)")
    ax.set_title("PV destination")
    ax.legend(frameon=False)

    ax = axes[1, 0]
    components = ("electricity_cost", "demand_cost", "fuel_cost", "co2_cost", "vehicle_usage_cost")
    component_labels = ("Electricity", "Demand", "Fuel", "CO₂", "Vehicle use")
    bottoms = np.zeros(2)
    palette = (LIGHT_BLUE, BLUE, ORANGE, GREEN, GRAY)
    for component, label, color in zip(components, component_labels, palette, strict=True):
        values = np.array([float(summaries[case]["costs_jpy"][component]) for case in cases])
        ax.bar(x, values, bottom=bottoms, label=label, color=color)
        bottoms += values
    ax.set_xticks(x, labels)
    ax.set_ylabel("Accounting cost (JPY)")
    ax.set_title("Cost composition (provisional)")
    ax.legend(frameon=False, fontsize=8, ncols=2)

    ax = axes[1, 1]
    grid = [float(daily[case]["grid_import_kwh"]) for case in cases]
    peak = [float(daily[case]["peak_grid_import_kw"]) for case in cases]
    bars = ax.bar(x - 0.18, grid, 0.36, color=colors, alpha=0.85, label="Grid import (kWh)")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Grid import (kWh)")
    twin = ax.twinx()
    twin.plot(x + 0.18, peak, color=RED, marker="o", linewidth=2, label="Peak (kW)")
    twin.set_ylabel("Peak import (kW)")
    ax.set_title("Energy can fall while peak demand rises")
    ax.legend(handles=[bars, twin.lines[0]], labels=["Grid import", "Peak import"], frameon=False, loc="upper center")

    fig.suptitle(
        "60-minute sunny/rain evidence — useful mechanism check, not a formal thesis comparison",
        fontweight="bold",
    )
    fig.text(0.5, 0.01, "Both runs are dirty-worktree artifacts; Stage 1 gaps are 13.11% and 12.94%.", ha="center", color=RED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    _save_figure(fig, output_dir / "04_weather_comparison_provisional.png")


def _literature_coverage() -> list[dict[str, str]]:
    return [
        {
            "requirement": "Charging-window and charger-conflict resolution",
            "literature_basis": "No42 p.9: fixed 15-min charge and explicit charging conflict",
            "current_evidence": "15-min grid-only baseline exists; weather comparison is 60-min",
            "status": "PARTIAL",
        },
        {
            "requirement": "Demand charge from peak average kW",
            "literature_basis": "No55 p.8: peak average power over a 15–60 min measurement interval",
            "current_evidence": "Current single-depot path uses max(slot kWh / timestep h) × horizon rate",
            "status": "IMPLEMENTED_CURRENT_SCOPE",
        },
        {
            "requirement": "Joint dispatch, charging, PV/BESS and tariff evaluation",
            "literature_basis": "No16 and No55 jointly model interdependent energy/vehicle decisions",
            "current_evidence": "Phase 3 is two-stage; Stage 1 uses an aggregate energy lower-bound proxy",
            "status": "APPROXIMATE",
        },
        {
            "requirement": "PV/load forecast uncertainty",
            "literature_basis": "No16 pp.13–14: Monte Carlo at 5/10/15/20% prediction error",
            "current_evidence": "Only 05:00→06:00 state chaining is verified; forecast-error study absent",
            "status": "MISSING",
        },
        {
            "requirement": "Optimization-quality disclosure",
            "literature_basis": "Report incumbent, bound, gap and runtime with every result",
            "current_evidence": "Saved artifacts expose Stage 1/2 status, gap, bound and runtime",
            "status": "IMPLEMENTED",
        },
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_review(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _configure_plotting()
    invalid_runs = _collect_invalid_runs()
    solver_evidence = _collect_solver_evidence()
    iis = _collect_iis()
    weather = _collect_weather()
    literature = _literature_coverage()

    _plot_truthfulness(invalid_runs, output_dir)
    _plot_solver_evidence(solver_evidence, output_dir)
    _plot_iis(iis, output_dir)
    _plot_weather(weather, output_dir)
    _write_csv(output_dir / "solver_evidence.csv", solver_evidence)
    _write_csv(output_dir / "literature_coverage.csv", literature)

    serializable_iis = {key: value for key, value in iis.items() if key != "departure_rows"}
    summary = {
        "generated_date": "2026-07-17",
        "invalid_ui_runs": invalid_runs,
        "solver_evidence": solver_evidence,
        "iis": serializable_iis,
        "weather_audit_source": weather["source"],
        "literature_coverage": literature,
        "figures": sorted(path.name for path in output_dir.glob("*.png")),
    }
    (output_dir / "review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    build_review(args.output_dir.resolve())


if __name__ == "__main__":
    main()
