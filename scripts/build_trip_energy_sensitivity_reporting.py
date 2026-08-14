"""Generate audited tables, workbook, and figures for trip-energy sensitivity."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.input_provenance import collect_git_state
from bff.services.optimization_run.trip_energy_sensitivity_reporting import (
    REPORTING_SCHEMA_VERSION,
    build_trip_energy_sensitivity_report,
    csv_columns,
    render_trip_energy_sensitivity_markdown,
)


WORKBOOK_BUILDER = (
    REPO_ROOT / "scripts" / "build_trip_energy_sensitivity_workbook.mjs"
)
WORKBOOK_SHEET_NAMES = [
    "Summary",
    "Executed KPIs",
    "Energy Flows",
    "Solver Evidence",
    "Provenance",
]
BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GOLD = "#D6A72C"
GRAY = "#6B7280"
GREEN = "#2A9D8F"
INK = "#252A34"


class ReportingError(RuntimeError):
    """Raised when immutable report creation cannot be certified."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-dir", type=Path, required=True)
    parser.add_argument("--node-executable", type=Path, required=True)
    parser.add_argument("--node-modules-dir", type=Path, required=True)
    args = parser.parse_args()
    execution_dir = args.execution_dir.resolve()
    source_path = execution_dir / "sensitivity_execution_manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    report = build_trip_energy_sensitivity_report(source)
    allowed_statuses = {
        "READY_FOR_TRIP_ENERGY_SENSITIVITY",
        "DIAGNOSTIC_FEASIBLE_NOT_OPTIMALITY_CERTIFIED",
    }
    if report["status"] not in allowed_statuses:
        raise ReportingError(
            "trip-energy sensitivity source evidence failed: "
            + ", ".join(report["failed_checks"])
        )

    git_state = collect_git_state(repo_root=REPO_ROOT)
    if not (
        git_state.get("git_state_available") is True
        and git_state.get("git_dirty") is False
        and str(git_state.get("git_sha") or "")
    ):
        raise ReportingError("A clean Git worktree is required for reporting")
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
    preview_dir = report_dir / "workbook_previews"
    figures_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = report_dir / "trip_energy_sensitivity_snapshot.json"
    csv_path = report_dir / "trip_energy_sensitivity_summary.csv"
    markdown_path = report_dir / "trip_energy_sensitivity_summary.md"
    workbook_path = report_dir / "results.xlsx"
    workbook_verification_path = report_dir / "workbook_verification.json"
    snapshot_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(csv_path, report["rows"])
    markdown_path.write_text(
        render_trip_energy_sensitivity_markdown(report), encoding="utf-8"
    )
    figure_paths = [
        *_plot_dispatch(report["rows"], figures_dir),
        *_plot_executed_kpis(report["rows"], figures_dir),
        *_plot_energy_flows(report["rows"], figures_dir),
        *_plot_solver_and_soc(report["rows"], figures_dir),
    ]
    workbook_verification = _run_workbook_builder(
        report,
        output_path=workbook_path,
        node_executable=args.node_executable.resolve(),
        node_modules_dir=args.node_modules_dir.resolve(),
        preview_dir=preview_dir,
    )
    workbook_verification_path.write_text(
        json.dumps(workbook_verification, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    preview_paths = sorted(preview_dir.glob("*.png"))
    artifacts = [
        snapshot_path,
        csv_path,
        markdown_path,
        workbook_path,
        workbook_verification_path,
        *figure_paths,
        *preview_paths,
    ]
    manifest = _reporting_manifest(
        report,
        execution_dir=execution_dir,
        builder_git_state=git_state,
        source_manifest_path=source_path,
        workbook_verification=workbook_verification,
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


def _plot_dispatch(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    scales = [float(row["trip_energy_scale"]) for row in rows]
    bev = [int(row["bev_trip_count"]) for row in rows]
    ice = [int(row["ice_trip_count"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    bars_bev = ax.bar(scales, bev, width=0.075, color=BLUE, label="BEV trips")
    bars_ice = ax.bar(
        scales,
        ice,
        bottom=bev,
        width=0.075,
        color=ORANGE,
        label="ICE trips",
    )
    ax.bar_label(bars_bev, labels=[str(value) for value in bev], fontsize=8)
    ax.bar_label(
        bars_ice,
        labels=[str(value) for value in ice],
        label_type="center",
        color="white",
        fontsize=8,
    )
    ax.set_title("Observed dispatch shifts as trip energy demand rises")
    ax.set_xlabel("Trip-energy demand scale")
    ax.set_ylabel("Assigned trips (264 total)")
    ax.set_xticks(scales)
    ax.set_ylim(0, 285)
    ax.legend(frameon=False, ncol=2, loc="upper center")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    ax.set_axisbelow(True)
    fig.text(
        0.5,
        0.01,
        "Gap-limited feasible incumbents; bars do not certify exact transition boundaries",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _save_figure(fig, figures_dir / "trip_energy_dispatch_response")


def _plot_executed_kpis(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    labels = [f"{row['trip_energy_scale']:.1f}" for row in rows]
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.7))
    series = (
        (
            [float(row["cost_delta_vs_1_0_jpy"]) for row in rows],
            "Executed cost delta vs 1.0",
            "JPY/day",
        ),
        (
            [float(row["co2_delta_vs_1_0_kg"]) for row in rows],
            "Operational CO2 delta vs 1.0",
            "kg/day",
        ),
        (
            [float(row["grid_delta_vs_1_0_kwh"]) for row in rows],
            "Grid-energy delta vs 1.0",
            "kWh/day",
        ),
    )
    for ax, (values, title, unit) in zip(axes, series):
        colors = [
            GRAY
            if abs(value) < 1.0e-12
            else BLUE
            if value < 0.0
            else ORANGE
            for value in values
        ]
        bars = ax.bar(labels, values, color=colors, edgecolor=INK, linewidth=0.7)
        ax.axhline(0.0, color=INK, linewidth=0.8)
        ax.bar_label(
            bars,
            labels=[
                "" if abs(value) < 1.0e-12 else f"{value:+,.1f}"
                for value in values
            ],
            padding=3,
            fontsize=8,
        )
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Demand scale")
        ax.set_ylabel(unit)
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.margins(y=0.22)
    fig.suptitle("Executed KPI differences relative to the 1.0 case", fontsize=14)
    fig.tight_layout(rect=(0, 0.02, 1, 0.92))
    return _save_figure(fig, figures_dir / "trip_energy_executed_kpi_deltas")


def _plot_energy_flows(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    scales = [float(row["trip_energy_scale"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.8, 5.3))
    for key, label, color, marker in (
        ("pv_to_bus_kwh", "PV to bus", GOLD, "o"),
        ("pv_to_bess_kwh", "PV to BESS", GREEN, "s"),
        ("bess_to_bus_kwh", "BESS to bus", BLUE, "D"),
        ("grid_import_kwh", "Grid import", ORANGE, "^")
    ):
        ax.plot(
            scales,
            [float(row[key]) for row in rows],
            color=color,
            marker=marker,
            linewidth=2.0,
            label=label,
        )
    ax.set_title("Accepted Rolling energy flows by demand scale")
    ax.set_xlabel("Trip-energy demand scale")
    ax.set_ylabel("Energy (kWh/day)")
    ax.set_xticks(scales)
    ax.grid(color="#E5E7EB", linewidth=0.7)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    return _save_figure(fig, figures_dir / "trip_energy_rolling_energy_flows")


def _plot_solver_and_soc(
    rows: Sequence[Mapping[str, Any]], figures_dir: Path
) -> list[Path]:
    plt = _pyplot()
    labels = [f"{row['trip_energy_scale']:.1f}" for row in rows]
    gaps = [float(row["certified_mip_gap_percent"]) for row in rows]
    wall_minutes = [float(row["wall_time_seconds"]) / 60.0 for row in rows]
    minimum_soc = [
        float(row["rolling_min_bev_soc_percent"]) for row in rows
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.7))
    gap_bars = axes[0].bar(labels, gaps, color=ORANGE, edgecolor=INK)
    axes[0].axhline(1.0, color=INK, linestyle="--", label="Target: 1%")
    axes[0].bar_label(gap_bars, labels=[f"{v:.2f}%" for v in gaps], fontsize=8)
    axes[0].set_title("Certified MIP gap")
    axes[0].set_ylabel("Percent")
    axes[0].legend(frameon=False)
    wall_bars = axes[1].bar(labels, wall_minutes, color=BLUE, edgecolor=INK)
    axes[1].bar_label(
        wall_bars, labels=[f"{v:.1f}" for v in wall_minutes], fontsize=8
    )
    axes[1].set_title("End-to-end wall time")
    axes[1].set_ylabel("Minutes")
    axes[2].plot(labels, minimum_soc, color=GREEN, marker="o", linewidth=2.0)
    axes[2].axhline(20.0, color=INK, linestyle="--", label="Vehicle limit: 20%")
    for label, value in zip(labels, minimum_soc):
        axes[2].annotate(
            f"{value:.2f}%",
            (label, value),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    axes[2].set_title("Minimum executed BEV SOC")
    axes[2].set_ylabel("SOC (%)")
    axes[2].legend(frameon=False)
    for ax in axes:
        ax.set_xlabel("Demand scale")
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.margins(y=0.2)
    fig.suptitle("Solver quality, computational effort, and SOC margin", fontsize=14)
    fig.tight_layout(rect=(0, 0.02, 1, 0.92))
    return _save_figure(fig, figures_dir / "trip_energy_solver_soc_evidence")


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = REPORTING_SCHEMA_VERSION
    from matplotlib import pyplot as plt

    return plt


def _save_figure(fig: Any, stem: Path) -> list[Path]:
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


def _create_node_modules_link(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        raise ReportingError(f"Temporary node_modules already exists: {link}")
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReportingError(
            "Cannot create temporary node_modules junction: "
            + (completed.stderr or completed.stdout).strip()
        )


def _run_workbook_builder(
    report: Mapping[str, Any],
    *,
    output_path: Path,
    node_executable: Path,
    node_modules_dir: Path,
    preview_dir: Path,
) -> dict[str, Any]:
    if not node_executable.is_file():
        raise ReportingError(f"Node executable not found: {node_executable}")
    if not node_modules_dir.is_dir():
        raise ReportingError(f"Bundled node_modules not found: {node_modules_dir}")
    if not WORKBOOK_BUILDER.is_file():
        raise ReportingError(f"Workbook builder not found: {WORKBOOK_BUILDER}")
    preview_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="energy-sensitivity-workbook-") as raw:
        temp_dir = Path(raw)
        builder_copy = temp_dir / WORKBOOK_BUILDER.name
        shutil.copy2(WORKBOOK_BUILDER, builder_copy)
        link = temp_dir / "node_modules"
        _create_node_modules_link(link, node_modules_dir)
        payload_path = temp_dir / "workbook_payload.json"
        verification_path = temp_dir / "workbook_verification.json"
        payload_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        completed = subprocess.run(
            [
                str(node_executable),
                str(builder_copy),
                str(payload_path),
                str(output_path),
                str(preview_dir),
                str(verification_path),
            ],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        try:
            link.rmdir()
        except OSError:
            pass
        if completed.returncode != 0:
            raise ReportingError(
                "Workbook builder failed: "
                + (completed.stderr or completed.stdout).strip()
            )
        sidecar = output_path.with_name(output_path.name + ".inspect.ndjson")
        if sidecar.exists():
            sidecar.unlink()
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if verification.get("status") != "OK":
        raise ReportingError(f"Workbook verification failed: {verification}")
    if verification.get("formula_error_count") != 0:
        raise ReportingError("Workbook formula-error scan found errors")
    if verification.get("sheet_names") != WORKBOOK_SHEET_NAMES:
        raise ReportingError("Workbook sheet contract mismatch")
    previews = verification.get("previews")
    if not isinstance(previews, list) or len(previews) != len(
        WORKBOOK_SHEET_NAMES
    ):
        raise ReportingError("Workbook preview count mismatch")
    normalized_previews: list[dict[str, str]] = []
    preview_root = preview_dir.resolve()
    for sheet_name, record in zip(WORKBOOK_SHEET_NAMES, previews):
        if not isinstance(record, Mapping) or record.get("sheet") != sheet_name:
            raise ReportingError("Workbook preview sheet mismatch")
        preview_path = Path(str(record.get("path") or "")).resolve()
        if (
            preview_path.parent != preview_root
            or not preview_path.is_file()
            or preview_path.stat().st_size <= 0
        ):
            raise ReportingError(f"Workbook preview invalid: {preview_path}")
        normalized_previews.append(
            {"sheet": sheet_name, "file": preview_path.name}
        )
    verification["previews"] = normalized_previews
    return verification


def _reporting_manifest(
    report: Mapping[str, Any],
    *,
    execution_dir: Path,
    builder_git_state: Mapping[str, Any],
    source_manifest_path: Path,
    workbook_verification: Mapping[str, Any],
    artifact_paths: Sequence[Path],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": REPORTING_SCHEMA_VERSION,
        "status": report.get("status"),
        "reporting_eligible": report.get("reporting_eligible"),
        "research_conclusion_eligible": report.get(
            "research_conclusion_eligible"
        ),
        "transition_boundary_certified": report.get(
            "transition_boundary_certified"
        ),
        "source_execution_payload_sha256": report.get(
            "source_execution_payload_sha256"
        ),
        "source_reaudit_manifest_file_sha256": sha256(
            source_manifest_path.read_bytes()
        ).hexdigest(),
        "source_run_git_sha": report.get("source_run_git_sha"),
        "source_audit_builder_git_sha": report.get(
            "source_audit_builder_git_sha"
        ),
        "report_builder_git_sha": builder_git_state.get("git_sha"),
        "report_builder_git_dirty": builder_git_state.get("git_dirty"),
        "workbook_verification": dict(workbook_verification),
        "chart_map": [
            {
                "artifact": "figures/trip_energy_dispatch_response.png/svg",
                "question": "How did the feasible incumbent BEV/ICE trip split change with demand?",
            },
            {
                "artifact": "figures/trip_energy_executed_kpi_deltas.png/svg",
                "question": "How did executed cost, CO2, and grid energy differ from scale 1.0?",
            },
            {
                "artifact": "figures/trip_energy_rolling_energy_flows.png/svg",
                "question": "How did accepted Rolling source flows respond to demand?",
            },
            {
                "artifact": "figures/trip_energy_solver_soc_evidence.png/svg",
                "question": "What solver gap, wall time, and executed minimum SOC support each case?",
            },
        ],
        "artifacts": {
            str(path.resolve().relative_to(execution_dir.resolve())).replace(
                "\\", "/"
            ): {
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
