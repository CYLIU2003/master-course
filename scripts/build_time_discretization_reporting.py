"""Generate audited tables and figures from a completed sensitivity tranche."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.input_provenance import collect_git_state
from bff.services.optimization_run.time_discretization_reporting import (
    REPORTING_SCHEMA_VERSION,
    build_time_discretization_report,
    csv_columns,
    render_time_discretization_markdown,
)


BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GOLD = "#D6A72C"
GRAY = "#6B7280"
INK = "#252A34"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-dir", type=Path, required=True)
    args = parser.parse_args()
    execution_dir = args.execution_dir.resolve()
    source_path = execution_dir / "sensitivity_execution_manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    report = build_time_discretization_report(source)
    if report["status"] == "BLOCKED_INVALID_SOURCE_EVIDENCE":
        raise RuntimeError(
            "time-discretization source evidence failed: "
            + ", ".join(report["failed_checks"])
        )

    git_state = collect_git_state(repo_root=REPO_ROOT)
    if not (
        git_state.get("git_state_available") is True
        and git_state.get("git_dirty") is False
        and str(git_state.get("git_sha") or "")
    ):
        raise RuntimeError("A clean Git worktree is required for reporting")
    report_version = (
        f"{str(report['source_execution_payload_sha256'])[:16]}-"
        f"{str(git_state['git_sha'])[:12]}"
    )
    report_dir = execution_dir / "reporting" / report_version
    if report_dir.exists():
        raise FileExistsError(
            f"immutable reporting directory already exists: {report_dir}"
        )
    figures_dir = report_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = report_dir / "time_discretization_snapshot.json"
    csv_path = report_dir / "time_discretization_summary.csv"
    markdown_path = report_dir / "time_discretization_summary.md"
    snapshot_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(csv_path, report["rows"])
    markdown_path.write_text(
        render_time_discretization_markdown(report), encoding="utf-8"
    )
    figure_paths = [
        *_plot_executed_kpis(report["rows"], figures_dir),
        *_plot_solver_evidence(report["rows"], figures_dir),
    ]
    artifacts = [snapshot_path, csv_path, markdown_path, *figure_paths]
    manifest = _reporting_manifest(
        report,
        execution_dir=execution_dir,
        builder_git_state=git_state,
        artifact_paths=artifacts,
    )
    manifest_path = report_dir / "reporting_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report_dir)
    print(report["status"])
    return 0


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = list(csv_columns())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["failed_checks"] = ";".join(output["failed_checks"])
            writer.writerow({column: output.get(column) for column in columns})


def _plot_executed_kpis(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    labels = [f"{row['timestep_min']} min" for row in rows]
    cost_delta = [float(row["cost_delta_vs_60_jpy"]) for row in rows]
    grid_delta = [float(row["grid_delta_vs_60_kwh"]) for row in rows]
    co2_delta = [float(row["co2_delta_vs_60_kg"]) for row in rows]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.6))
    for ax, values, title, unit in (
        (axes[0], cost_delta, "Executed cost delta vs 60 min", "JPY/day"),
        (axes[1], grid_delta, "Grid-energy delta vs 60 min", "kWh/day"),
        (axes[2], co2_delta, "Operational CO2 delta vs 60 min", "kg/day"),
    ):
        colors = [
            GRAY
            if abs(value) < 1e-12
            else BLUE
            if value < 0
            else ORANGE
            for value in values
        ]
        bars = ax.bar(labels, values, color=colors, edgecolor=INK, linewidth=0.7)
        ax.axhline(0.0, color=INK, linewidth=0.8)
        ax.set_title(title, color=INK, fontsize=10)
        ax.set_ylabel(unit)
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.bar_label(
            bars,
            labels=[
                "" if abs(value) < 1e-12 else f"{value:+,.2f}"
                for value in values
            ],
            padding=3,
            fontsize=8,
        )
        ax.margins(y=0.25)
    fig.suptitle("Time-discretization sensitivity: executed KPI differences", color=INK, fontsize=14)
    fig.text(
        0.5,
        0.92,
        "Low-PV case; same 32 buses and 91 BEV / 173 ICE trips; feasible incumbents, 1% gap not met",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.86))
    return _save_figure(fig, figures_dir / "time_discretization_executed_kpis")


def _plot_solver_evidence(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    labels = [f"{row['timestep_min']} min" for row in rows]
    gaps = [float(row["certified_mip_gap_percent"]) for row in rows]
    wall_minutes = [float(row["wall_time_seconds"]) / 60.0 for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.7))
    bars = axes[0].bar(labels, gaps, color=ORANGE, edgecolor=INK, linewidth=0.7)
    axes[0].axhline(
        1.0,
        color=INK,
        linestyle="--",
        linewidth=1.0,
        label="Target: 1%",
    )
    axes[0].bar_label(
        bars,
        labels=[f"{value:.3f}%" for value in gaps],
        padding=3,
        fontsize=8,
    )
    axes[0].set_title("Certified MIP gap", fontsize=11, color=INK)
    axes[0].set_ylabel("Percent")
    axes[0].legend(frameon=False)
    wall_bars = axes[1].bar(
        labels,
        wall_minutes,
        color=BLUE,
        edgecolor=INK,
        linewidth=0.7,
    )
    axes[1].bar_label(
        wall_bars,
        labels=[f"{value:.1f} min" for value in wall_minutes],
        padding=3,
        fontsize=8,
    )
    axes[1].set_title("End-to-end wall time", fontsize=11, color=INK)
    axes[1].set_ylabel("Minutes")
    for ax in axes:
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.margins(y=0.18)
    fig.suptitle("Solver evidence and computational effort", color=INK, fontsize=14)
    fig.text(
        0.5,
        0.92,
        "All cases used a 3600 s day-ahead solver limit, 4 threads, seed 42, and 60-minute Rolling execution",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.86))
    return _save_figure(fig, figures_dir / "time_discretization_solver_evidence")


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = REPORTING_SCHEMA_VERSION
    from matplotlib import pyplot as plt

    return plt


def _save_figure(fig, stem: Path) -> list[Path]:
    png_path = stem.with_suffix(".png")
    svg_path = stem.with_suffix(".svg")
    fig.savefig(
        png_path,
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": REPORTING_SCHEMA_VERSION},
    )
    fig.savefig(
        svg_path,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": REPORTING_SCHEMA_VERSION, "Date": None},
    )
    _pyplot().close(fig)
    return [png_path, svg_path]


def _reporting_manifest(
    report: Mapping[str, Any],
    *,
    execution_dir: Path,
    builder_git_state: Mapping[str, Any],
    artifact_paths: Sequence[Path],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": REPORTING_SCHEMA_VERSION,
        "status": report.get("status"),
        "research_conclusion_eligible": report.get(
            "research_conclusion_eligible"
        ),
        "discretization_convergence_certified": report.get(
            "discretization_convergence_certified"
        ),
        "source_execution_payload_sha256": report.get(
            "source_execution_payload_sha256"
        ),
        "source_run_git_sha": report.get("source_run_git_sha"),
        "report_builder_git_sha": builder_git_state.get("git_sha"),
        "report_builder_git_dirty": builder_git_state.get("git_dirty"),
        "chart_map": [
            {
                "artifact": "figures/time_discretization_executed_kpis.png/svg",
                "question": "How much do executed cost, grid energy, and CO2 change relative to the 60-minute model?",
            },
            {
                "artifact": "figures/time_discretization_solver_evidence.png/svg",
                "question": "Did each solve meet the optimality target, and what wall time was required?",
            },
        ],
        "artifacts": {
            str(path.resolve().relative_to(execution_dir.resolve())).replace("\\", "/"): {
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for path in artifact_paths
        },
    }
    unsigned = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest["payload_sha256"] = sha256(unsigned).hexdigest()
    return manifest


if __name__ == "__main__":
    raise SystemExit(main())
