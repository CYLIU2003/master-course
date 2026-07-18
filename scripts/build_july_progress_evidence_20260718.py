"""Build July progress evidence using only the saved 2026-07-17 runs.

The two saved runs are infeasible.  This script therefore visualizes solver
quality, reporting consistency, input PV profiles, and artifact availability.
It deliberately does not turn zero-filled ledgers into operating KPIs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "output" / "2026-07-17"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "monthly_progress_202607" / "figures"
EXPECTED_RUN_NAMES = ("run_20260717_0003", "run_20260717_1240")

NAVY = "#123B5D"
BLUE = "#3B82B6"
LIGHT_BLUE = "#8EC5E8"
ORANGE = "#E07A2D"
RED = "#C03A32"
GREEN = "#2F7D5B"
GRAY = "#6B7280"
LIGHT_GRAY = "#E5E7EB"


@dataclass(frozen=True)
class RunEvidence:
    """Evidence extracted from one immutable saved run."""

    run_id: str
    service_date: str
    case_label: str
    operation_mode: str
    git_sha: str
    timestep_min: int
    canonical_status: str
    canonical_served: int
    canonical_unserved: int
    summary_unserved: int
    kpi_unserved: int
    summary_total_cost_jpy: float | None
    validated_operating_cost_jpy: float | None
    objective_is_actual_cost_summary: bool
    objective_is_actual_cost_kpi: bool
    research_kpi_eligible: bool
    stage1_status: str
    stage1_candidate_trips: int
    stage1_gap_percent: float
    stage1_runtime_seconds: float
    stage2_status: str
    stage2_runtime_seconds: float
    candidate_arcs_before: int
    candidate_arcs_after: int
    pruned_arcs: int
    successor_cap: int
    saved_supports_exact_milp: bool
    pv_generated_kwh: float
    pv_peak_kw: float
    weather_forecast_applied: bool
    weather_forecast_skip_reason: str
    artifact_rows: dict[str, int]
    pv_profile: tuple[tuple[str, float], ...]


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
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _artifact_row_counts(run_dir: Path) -> dict[str, int]:
    paths = {
        "最終便割当": "vehicle_schedule.csv",
        "充電計画": "charging_schedule.csv",
        "車両タイムライン": "vehicle_timeline_gantt.csv",
        "SOC時系列": "graph/vehicle_soc_timeseries.csv",
        "充電源時系列": "graph/vehicle_charging_source_timeseries.csv",
        "PV入力時系列": "graph/pv_generation_timeseries.csv",
        "未充足便": "raw/unserved_trips.csv",
    }
    return {label: len(_read_csv(run_dir / relative_path)) for label, relative_path in paths.items()}


def _load_run(run_dir: Path) -> RunEvidence:
    canonical = _load_json(run_dir / "canonical_solver_result.json")
    summary = _load_json(run_dir / "summary.json")
    kpi = _load_json(run_dir / "kpi_summary.json")
    manifest = _load_json(run_dir / "run_manifest.json")
    weather = _load_json(run_dir / "weather_proxy_forecast.json")
    weather_audit = _load_json(run_dir / "weather_policy_audit.json")
    pv_rows = _read_csv(run_dir / "graph" / "pv_generation_timeseries.csv")
    metadata = canonical.get("solver_metadata") or {}
    execution_metadata = canonical.get("metadata") or {}
    validity = canonical.get("solution_validity") or {}
    pruning = metadata.get("arc_pruning_summary") or {}
    pv_profile = tuple((row["time"], float(row["pv_generation_kw"])) for row in pv_rows)
    return RunEvidence(
        run_id=run_dir.name,
        service_date=str(manifest.get("service_date") or weather.get("service_date") or ""),
        case_label=str(weather.get("weather_label") or run_dir.name),
        operation_mode=str(weather.get("operation_mode") or ""),
        git_sha=str(manifest.get("git_sha") or ""),
        timestep_min=int(execution_metadata.get("timestep_min") or 60),
        canonical_status=str(canonical.get("solver_status") or "unknown"),
        canonical_served=int(canonical.get("trip_count_served") or 0),
        canonical_unserved=int(canonical.get("trip_count_unserved") or 0),
        summary_unserved=int(summary.get("trip_count_unserved") or 0),
        kpi_unserved=int(kpi.get("unserved_trip_count") or 0),
        summary_total_cost_jpy=_finite_float(summary.get("total_cost_jpy")),
        validated_operating_cost_jpy=_finite_float(kpi.get("validated_operating_cost_jpy")),
        objective_is_actual_cost_summary=bool(summary.get("objective_is_actual_cost")),
        objective_is_actual_cost_kpi=bool(kpi.get("objective_is_actual_cost")),
        research_kpi_eligible=bool(validity.get("research_kpi_eligible")),
        stage1_status=str(metadata.get("stage1_solver_status") or "unknown"),
        stage1_candidate_trips=int(
            execution_metadata.get("assignment_candidate_trip_count")
            or len(execution_metadata.get("assignment_candidate_trip_ids") or [])
        ),
        stage1_gap_percent=100.0 * float(metadata.get("stage1_mip_gap_ratio") or 0.0),
        stage1_runtime_seconds=float(metadata.get("stage1_runtime_seconds") or 0.0),
        stage2_status=str(metadata.get("stage2_solver_status") or "unknown"),
        stage2_runtime_seconds=float(metadata.get("stage2_runtime_seconds") or 0.0),
        candidate_arcs_before=int(pruning.get("candidate_arc_count_before_successor_pruning") or 0),
        candidate_arcs_after=int(pruning.get("arc_count_after_successor_pruning") or 0),
        pruned_arcs=int(pruning.get("pruned_arc_count") or 0),
        successor_cap=int(pruning.get("milp_max_successors_per_trip") or 0),
        saved_supports_exact_milp=bool(metadata.get("supports_exact_milp")),
        pv_generated_kwh=sum(value for _, value in pv_profile),
        pv_peak_kw=max((value for _, value in pv_profile), default=0.0),
        weather_forecast_applied=bool(weather_audit.get("weather_pv_forecast_applied")),
        weather_forecast_skip_reason=str(weather_audit.get("weather_pv_forecast_skip_reason") or ""),
        artifact_rows=_artifact_row_counts(run_dir),
        pv_profile=pv_profile,
    )


def collect_evidence(source_root: Path) -> list[RunEvidence]:
    """Load the two requested runs and reject accidental source expansion."""

    resolved_root = source_root.resolve()
    run_dirs = [resolved_root / name for name in EXPECTED_RUN_NAMES]
    for run_dir in run_dirs:
        if run_dir.parent != resolved_root or not run_dir.is_dir():
            raise FileNotFoundError(f"expected run directory not found: {run_dir}")
    return [_load_run(run_dir) for run_dir in run_dirs]


def _configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Yu Gothic", "Meiryo", "DejaVu Sans"],
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.axisbelow": True,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def _save_figure(fig: plt.Figure, output_path: Path) -> None:
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _short_labels(runs: list[RunEvidence]) -> list[str]:
    return [f"{run.run_id.removeprefix('run_')}\n{run.case_label}" for run in runs]


def _plot_truthfulness_gap(runs: list[RunEvidence], output_dir: Path) -> None:
    labels = _short_labels(runs)
    x = np.arange(len(runs))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.4, 5.7))
    series = (
        ("canonical", [run.canonical_unserved for run in runs], NAVY),
        ("summary.json", [run.summary_unserved for run in runs], ORANGE),
        ("kpi_summary.json", [run.kpi_unserved for run in runs], RED),
    )
    for offset, (name, values, color) in zip((-width, 0.0, width), series, strict=True):
        bars = ax.bar(x + offset, values, width, color=color, label=name)
        ax.bar_label(bars, padding=3, fontsize=10)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 290)
    ax.set_ylabel("未充足便数 [便]")
    ax.set_title("同一run内で未充足便数が一致していない")
    ax.legend(frameon=False, ncols=3, loc="upper center")
    ax.text(
        0.5,
        -0.19,
        "canonical: Stage 2不可行・264便未充足／読者向け集計: 0便と記録",
        transform=ax.transAxes,
        ha="center",
        color=RED,
        fontsize=10,
    )
    _save_figure(fig, output_dir / "01_kpi_truthfulness_gap.png")


def _plot_two_stage_acceptance(runs: list[RunEvidence], output_dir: Path) -> None:
    labels = _short_labels(runs)
    x = np.arange(len(runs))
    width = 0.32
    fig, ax = plt.subplots(figsize=(10.4, 5.7))
    candidate = [run.stage1_candidate_trips for run in runs]
    accepted = [run.canonical_served for run in runs]
    candidate_bars = ax.bar(x - width / 2, candidate, width, color=LIGHT_BLUE, label="Stage 1 割当候補")
    accepted_bars = ax.bar(x + width / 2, accepted, width, color=RED, label="Stage 2後の正式担当")
    ax.bar_label(candidate_bars, labels=[f"{value}便" for value in candidate], padding=3)
    ax.bar_label(accepted_bars, labels=[f"{value}便" for value in accepted], padding=3)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 290)
    ax.set_ylabel("便数 [便]")
    ax.set_title("Stage 1の割当候補は、Stage 2の可行解ではない")
    ax.legend(frameon=False, ncols=2, loc="upper center")
    for index, run in enumerate(runs):
        ax.text(index, 22, f"Stage 2: {run.stage2_status}", ha="center", color=RED, fontweight="bold")
    _save_figure(fig, output_dir / "02_two_stage_acceptance.png")


def _plot_solver_quality(runs: list[RunEvidence], output_dir: Path) -> None:
    labels = _short_labels(runs)
    x = np.arange(len(runs))
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.4, 5.4))
    gaps = [run.stage1_gap_percent for run in runs]
    bars = left.bar(x, gaps, width=0.58, color=ORANGE)
    left.axhline(10.0, color=RED, linestyle="--", linewidth=1.6, label="要求値 10%")
    left.bar_label(bars, labels=[f"{value:.2f}%" for value in gaps], padding=3)
    left.set_xticks(x, labels)
    left.set_ylim(0, 55)
    left.set_ylabel("Stage 1 MIP gap [%]")
    left.set_title("最適性ギャップ")
    left.legend(frameon=False)

    stage1 = [run.stage1_runtime_seconds for run in runs]
    stage2 = [run.stage2_runtime_seconds for run in runs]
    right.bar(x, stage1, width=0.58, color=NAVY, label="Stage 1")
    right.bar(x, stage2, width=0.58, bottom=stage1, color=RED, label="Stage 2")
    right.set_xticks(x, labels)
    right.set_ylabel("実行時間 [s]")
    right.set_title("計算時間")
    right.legend(frameon=False)
    for index, run in enumerate(runs):
        right.text(index, run.stage1_runtime_seconds + 18, f"{run.stage1_runtime_seconds:.1f}s", ha="center")
        right.text(index, 28, f"S2 {run.stage2_runtime_seconds:.3f}s", ha="center", color="white", fontweight="bold")
    fig.suptitle("2 runとも時間制限到達後の暫定解であり、大域最適性は未保証", fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    _save_figure(fig, output_dir / "03_solver_gap_runtime.png")


def _plot_pv_profiles(runs: list[RunEvidence], output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    colors = (NAVY, ORANGE)
    for run, color in zip(runs, colors, strict=True):
        hours = np.arange(len(run.pv_profile))
        values = [value for _, value in run.pv_profile]
        label = f"{run.case_label}: {run.pv_generated_kwh:.1f} kWh/日"
        ax.plot(hours, values, marker="o", markersize=4, linewidth=2.2, color=color, label=label)
        peak_hour = int(np.argmax(values))
        annotation_offset = -10 if run.pv_peak_kw > 50 else 5
        ax.annotate(
            f"最大 {run.pv_peak_kw:.1f} kW",
            xy=(peak_hour, values[peak_hour]),
            xytext=(peak_hour + 0.5, values[peak_hour] + annotation_offset),
            arrowprops={"arrowstyle": "->", "color": color},
            color=color,
        )
    ax.set_xticks(np.arange(0, 24, 3), [f"{hour:02d}:00" for hour in range(0, 24, 3)])
    ax.set_xlim(0, 23)
    ax.set_ylabel("PV発電入力 [kW]")
    ax.set_xlabel("時刻")
    ax.set_title("PV入力時系列（比較可能なのは入力条件まで）")
    ax.legend(frameon=False, loc="upper right")
    ax.text(
        0.5,
        -0.18,
        "注: 両runともStage 2不可行のため、PV→バス・PV→BESS・抑制量は研究結果として評価しない",
        transform=ax.transAxes,
        ha="center",
        color=RED,
        fontsize=9.5,
    )
    _save_figure(fig, output_dir / "04_pv_input_profiles.png")


def _plot_successor_pruning(runs: list[RunEvidence], output_dir: Path) -> None:
    representative = runs[0]
    retained = representative.candidate_arcs_after
    removed = representative.pruned_arcs
    pruned_ratio = 100.0 * removed / representative.candidate_arcs_before
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.barh([0], [retained], color=NAVY, height=0.42, label="保持")
    ax.barh([0], [removed], left=[retained], color=LIGHT_GRAY, height=0.42, label="削減")
    ax.text(retained / 2, 0, f"保持\n{retained:,}本", ha="center", va="center", color="white", fontweight="bold")
    ax.text(retained + removed / 2, 0, f"削減\n{removed:,}本 ({pruned_ratio:.1f}%)", ha="center", va="center", color=GRAY, fontweight="bold")
    ax.set_xlim(0, representative.candidate_arcs_before)
    ax.set_yticks([])
    ax.set_xlabel("便間接続候補arc数 [本]")
    ax.set_title(f"successor上限{representative.successor_cap}により候補arcの83.2%を削減")
    ax.legend(frameon=False, ncols=2, loc="upper center")
    ax.text(
        0.5,
        -0.24,
        "保存済みmetadataでは supports_exact_milp=true だが、削減前ネットワークの大域最適性は示していない",
        transform=ax.transAxes,
        ha="center",
        color=RED,
        fontsize=10,
    )
    _save_figure(fig, output_dir / "05_successor_pruning.png")


def _plot_ledger_completeness(runs: list[RunEvidence], output_dir: Path) -> None:
    artifact_labels = list(runs[0].artifact_rows)
    values = np.array([[run.artifact_rows[label] for run in runs] for label in artifact_labels], dtype=float)
    displayed = np.log10(values + 1.0)
    fig, ax = plt.subplots(figsize=(10.4, 6.0))
    image = ax.imshow(displayed, cmap="Blues", aspect="auto", vmin=0, vmax=np.log10(265))
    ax.set_xticks(np.arange(len(runs)), _short_labels(runs))
    ax.set_yticks(np.arange(len(artifact_labels)), artifact_labels)
    ax.set_title("出力ledgerの行数：運用結果は空、未充足便だけが264行")
    for row_index in range(values.shape[0]):
        for column_index in range(values.shape[1]):
            value = int(values[row_index, column_index])
            color = "white" if displayed[row_index, column_index] > 1.35 else NAVY
            ax.text(column_index, row_index, f"{value}行", ha="center", va="center", color=color, fontweight="bold")
    colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.04)
    colorbar.set_label("log10(行数 + 1)")
    fig.tight_layout()
    _save_figure(fig, output_dir / "06_output_ledger_completeness.png")


def _plot_literature_figure_eligibility(runs: list[RunEvidence], output_dir: Path) -> None:
    categories = [
        "solver品質",
        "便カバレッジ検証",
        "PV入力時系列",
        "車両運用ダイヤ",
        "EV SOC時系列",
        "充電源別電力需給",
        "費用内訳",
        "CO₂排出量",
    ]
    eligibility = [1, 1, 1, 0, 0, 0, 0, 0]
    colors = [GREEN if value else RED for value in eligibility]
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    y = np.arange(len(categories))
    bars = ax.barh(y, eligibility, color=colors, height=0.58)
    ax.set_yticks(y, categories)
    ax.set_xlim(0, 1.15)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.set_title("先行文献で一般的な図のうち、7月17日runから監査図として示せるもの")
    for bar, value in zip(bars, eligibility, strict=True):
        label = "掲載可" if value else "掲載不可"
        ax.text(0.52 if value else 0.04, bar.get_y() + bar.get_height() / 2, label, va="center", color="white" if value else RED, fontweight="bold")
    ax.text(
        0.02,
        -0.10,
        "掲載不可の理由: Stage 2不可行、正式割当・SOC・充電ledgerが0行、research_kpi_eligible=false",
        transform=ax.transAxes,
        color=RED,
        fontsize=9.5,
    )
    _save_figure(fig, output_dir / "07_literature_figure_eligibility.png")


def _plot_result_acceptance_gate(runs: list[RunEvidence], output_dir: Path) -> None:
    checks = [
        ("全264便を担当", all(run.canonical_served == 264 for run in runs)),
        ("Stage 2に可行 incumbent", all(run.stage2_status in {"optimal", "time_limit"} for run in runs)),
        ("独立検証に合格", all(run.canonical_unserved == 0 for run in runs)),
        ("研究KPIを利用可能", all(run.research_kpi_eligible for run in runs)),
        ("MIP gap ≤ 10%", all(run.stage1_gap_percent <= 10.0 for run in runs)),
        ("運用ledgerが非空", all(run.artifact_rows["最終便割当"] > 0 for run in runs)),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.9))
    y = np.arange(len(checks))
    values = [1 if passed else 0 for _, passed in checks]
    colors = [GREEN if passed else RED for _, passed in checks]
    ax.barh(y, [1] * len(checks), color=LIGHT_GRAY, height=0.58)
    ax.barh(y, values, color=colors, height=0.58)
    ax.set_yticks(y, [label for label, _ in checks])
    ax.set_xlim(0, 1.15)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.set_title("正式な修論結果としての受理ゲート：6項目すべて未達")
    for index, (_, passed) in enumerate(checks):
        ax.text(0.04, index, "✓ 合格" if passed else "× 未達", va="center", color="white" if passed else RED, fontweight="bold")
    ax.text(
        0.5,
        -0.12,
        "結論: 7月17日runはデバッグ証拠として使用し、費用・エネルギー・CO₂の主結果には使用しない",
        transform=ax.transAxes,
        ha="center",
        color=RED,
        fontweight="bold",
    )
    _save_figure(fig, output_dir / "08_result_acceptance_gate.png")


def _plot_source_contract_matrix(runs: list[RunEvidence], output_dir: Path) -> None:
    representative = runs[0]
    rows = [
        ["solver status", representative.canonical_status, representative.canonical_status, "記載なし"],
        ["未充足便数", str(representative.canonical_unserved), str(representative.summary_unserved), str(representative.kpi_unserved)],
        ["費用", "評価不能", f"{representative.summary_total_cost_jpy or 0:.0f}円", f"{representative.summary_total_cost_jpy or 0:.0f}円"],
        ["validated cost", "評価不能", "未分離", "null" if representative.validated_operating_cost_jpy is None else str(representative.validated_operating_cost_jpy)],
        ["research KPI", "false", "false", "明示なし"],
    ]
    columns = ["項目", "canonical", "summary.json", "kpi_summary.json"]
    fig, ax = plt.subplots(figsize=(11.2, 5.4))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=columns, cellLoc="center", loc="center", colWidths=[0.22, 0.26, 0.26, 0.26])
    table.auto_set_font_size(False)
    table.set_fontsize(10.5)
    table.scale(1, 1.75)
    for column in range(len(columns)):
        cell = table[(0, column)]
        cell.set_facecolor(NAVY)
        cell.get_text().set_color("white")
        cell.get_text().set_fontweight("bold")
    for row_index in range(1, len(rows) + 1):
        table[(row_index, 0)].set_facecolor("#EAF2F8")
        for column_index in range(1, len(columns)):
            cell = table[(row_index, column_index)]
            cell.set_facecolor("white")
            if row_index in {2, 3, 4} and column_index >= 2:
                cell.get_text().set_color(RED)
                cell.get_text().set_fontweight("bold")
    ax.set_title("同一run内の出力契約：statusは一致しても、便数・費用の意味が不一致", pad=18, fontweight="bold")
    _save_figure(fig, output_dir / "09_source_contract_matrix.png")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _run_rows(runs: list[RunEvidence]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": run.run_id,
            "service_date": run.service_date,
            "case_label": run.case_label,
            "git_sha": run.git_sha,
            "timestep_min": run.timestep_min,
            "canonical_status": run.canonical_status,
            "canonical_served": run.canonical_served,
            "canonical_unserved": run.canonical_unserved,
            "summary_unserved": run.summary_unserved,
            "kpi_unserved": run.kpi_unserved,
            "research_kpi_eligible": run.research_kpi_eligible,
            "stage1_status": run.stage1_status,
            "stage1_candidate_trips": run.stage1_candidate_trips,
            "stage1_gap_percent": run.stage1_gap_percent,
            "stage1_runtime_seconds": run.stage1_runtime_seconds,
            "stage2_status": run.stage2_status,
            "stage2_runtime_seconds": run.stage2_runtime_seconds,
            "candidate_arcs_before": run.candidate_arcs_before,
            "candidate_arcs_after": run.candidate_arcs_after,
            "pruned_arcs": run.pruned_arcs,
            "successor_cap": run.successor_cap,
            "saved_supports_exact_milp": run.saved_supports_exact_milp,
            "pv_generated_kwh": run.pv_generated_kwh,
            "pv_peak_kw": run.pv_peak_kw,
            "weather_forecast_applied": run.weather_forecast_applied,
            "weather_forecast_skip_reason": run.weather_forecast_skip_reason,
        }
        for run in runs
    ]


def build_evidence(source_root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _configure_plotting()
    runs = collect_evidence(source_root)
    _plot_truthfulness_gap(runs, output_dir)
    _plot_two_stage_acceptance(runs, output_dir)
    _plot_solver_quality(runs, output_dir)
    _plot_pv_profiles(runs, output_dir)
    _plot_successor_pruning(runs, output_dir)
    _plot_ledger_completeness(runs, output_dir)
    _plot_literature_figure_eligibility(runs, output_dir)
    _plot_result_acceptance_gate(runs, output_dir)
    _plot_source_contract_matrix(runs, output_dir)

    run_rows = _run_rows(runs)
    _write_csv(output_dir.parent / "run_audit_20260717.csv", run_rows)
    artifact_rows = [
        {"run_id": run.run_id, "artifact": label, "row_count": count}
        for run in runs
        for label, count in run.artifact_rows.items()
    ]
    _write_csv(output_dir.parent / "artifact_row_counts_20260717.csv", artifact_rows)
    summary = {
        "generated_on": "2026-07-18",
        "source_root": str(source_root.resolve()),
        "source_run_ids": list(EXPECTED_RUN_NAMES),
        "source_policy": "visualized result data are restricted to output/2026-07-17",
        "research_result_eligible": False,
        "reason": "both runs are Stage 2 infeasible and canonical results leave 264 trips unserved",
        "runs": run_rows,
        "figures": sorted(path.name for path in output_dir.glob("*.png")),
    }
    (output_dir.parent / "audit_summary_20260717.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    build_evidence(args.source_root, args.output_dir)


if __name__ == "__main__":
    main()
