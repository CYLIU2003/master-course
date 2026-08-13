"""Build an audited M0--M3 day-ahead comparison from two frontend runs."""

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

from bff.services.optimization_run.thesis_ablation_comparison import (
    build_complete_day_ahead_ablation_comparison,
    comparison_csv_rows,
)
from bff.services.optimization_run.input_provenance import collect_git_state
from bff.services.optimization_run.thesis_ablation_reporting import (
    REPORTING_SCHEMA_VERSION,
    comparison_effect_rows,
    method_reporting_rows,
    render_comparison_markdown,
)


BLUE = "#2F6B9A"
ORANGE = "#D9822B"
GOLD = "#D6A72C"
GRAY = "#6B7280"
INK = "#252A34"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1-run", type=Path, required=True)
    parser.add_argument("--phase4-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = build_complete_day_ahead_ablation_comparison(
        phase1_run_dir=args.phase1_run,
        phase4_run_dir=args.phase4_run,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "day_ahead_method_comparison.json"
    csv_path = output_dir / "day_ahead_method_comparison.csv"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = comparison_csv_rows(payload)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    reporting_dir = _write_reporting_artifacts(
        payload,
        output_dir=output_dir,
        comparison_json_path=json_path,
        comparison_csv_path=csv_path,
    )
    print(json_path)
    print(csv_path)
    if reporting_dir is not None:
        print(reporting_dir)
    print(payload["status"])
    return 0 if payload["status"] == "READY_FOR_DAY_AHEAD_METHOD_COMPARISON" else 2


def _write_reporting_artifacts(
    payload: Mapping[str, Any],
    *,
    output_dir: Path,
    comparison_json_path: Path,
    comparison_csv_path: Path,
) -> Path | None:
    if payload.get("status") != "READY_FOR_DAY_AHEAD_METHOD_COMPARISON":
        return None
    git_state = collect_git_state(repo_root=REPO_ROOT)
    if not (
        git_state.get("git_state_available") is True
        and git_state.get("git_dirty") is False
        and str(git_state.get("git_sha") or "")
    ):
        raise RuntimeError(
            "A clean Git worktree is required for thesis ablation reporting"
        )
    report_version = (
        f"{str(payload['payload_sha256'])[:16]}-"
        f"{str(git_state['git_sha'])[:12]}"
    )
    report_dir = output_dir / "reporting" / report_version
    report_dir.mkdir(parents=True, exist_ok=True)
    method_rows = method_reporting_rows(payload)
    effect_rows = comparison_effect_rows(payload)
    method_path = report_dir / "method_results.csv"
    effect_path = report_dir / "method_effects.csv"
    markdown_path = report_dir / "method_comparison_report.md"
    _write_csv(method_path, method_rows)
    _write_csv(effect_path, effect_rows)
    markdown_path.write_text(
        render_comparison_markdown(
            payload,
            method_rows=method_rows,
            effect_rows=effect_rows,
        ),
        encoding="utf-8",
    )
    figure_paths = [
        *_plot_cost_and_co2_effects(method_rows, report_dir),
        *_plot_dispatch_and_energy(method_rows, report_dir),
    ]
    artifact_paths = [
        comparison_json_path,
        comparison_csv_path,
        method_path,
        effect_path,
        markdown_path,
        *figure_paths,
    ]
    manifest = _reporting_manifest(
        payload,
        output_dir=output_dir,
        builder_git_state=git_state,
        artifact_paths=artifact_paths,
    )
    manifest_path = report_dir / "reporting_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_dir


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_cost_and_co2_effects(
    rows: Sequence[Mapping[str, Any]],
    report_dir: Path,
) -> list[Path]:
    plt = _pyplot()
    labels = [str(row["method_id"]) for row in rows]
    base_cost = float(rows[0]["total_cost_jpy"])
    base_co2 = float(rows[0]["total_co2_kg"])
    cost_delta = [float(row["total_cost_jpy"]) - base_cost for row in rows]
    co2_delta = [float(row["total_co2_kg"]) - base_co2 for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    _signed_bar_panel(
        axes[0], labels, cost_delta, title="Total cost delta vs M0", unit="JPY"
    )
    _signed_bar_panel(
        axes[1], labels, co2_delta, title="Operational CO2 delta vs M0", unit="kg"
    )
    fig.suptitle("Day-ahead method effects relative to M0", color=INK, fontsize=15)
    fig.text(
        0.5,
        0.925,
        "Low-PV case, 264 trips; negative values indicate reductions; Rolling excluded",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.87))
    return _save_figure(fig, report_dir / "m0_m3_cost_co2_effects")


def _signed_bar_panel(
    ax,
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str,
    unit: str,
) -> None:
    colors = [BLUE if value <= 0.0 else ORANGE for value in values]
    bars = ax.bar(labels, values, color=colors, edgecolor=INK, linewidth=0.7)
    ax.axhline(0.0, color=INK, linewidth=0.8)
    ax.set_title(title, color=INK, fontsize=11)
    ax.set_ylabel(unit, color=INK)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.bar_label(
        bars,
        labels=[f"{value:+,.1f}" for value in values],
        padding=3,
        fontsize=8,
    )
    ax.margins(y=0.22)


def _plot_dispatch_and_energy(
    rows: Sequence[Mapping[str, Any]],
    report_dir: Path,
) -> list[Path]:
    plt = _pyplot()
    labels = [str(row["method_id"]) for row in rows]
    bev_trips = [float(row["bev_trip_count"]) for row in rows]
    ice_trips = [float(row["ice_trip_count"]) for row in rows]
    grid = [float(row["grid_import_kwh"]) for row in rows]
    pv_direct = [float(row["pv_to_bus_kwh"]) for row in rows]
    bess = [float(row["bess_to_bus_kwh"]) for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.0))
    axes[0].bar(
        labels,
        bev_trips,
        label="BEV trips",
        color=BLUE,
        edgecolor=INK,
        linewidth=0.7,
    )
    axes[0].bar(
        labels,
        ice_trips,
        bottom=bev_trips,
        label="ICE trips",
        color=ORANGE,
        edgecolor=INK,
        linewidth=0.7,
    )
    axes[0].set_title("Assigned trips by powertrain", color=INK, fontsize=11)
    axes[0].set_ylabel("Trips")
    maximum_trip_count = max(
        bev_trips[i] + ice_trips[i] for i in range(len(rows))
    )
    axes[0].set_ylim(0, maximum_trip_count * 1.12)
    for index, total in enumerate(
        bev_trips[i] + ice_trips[i] for i in range(len(rows))
    ):
        axes[0].text(index, total + 4, f"{int(total)}", ha="center", fontsize=8)
        axes[0].text(
            index,
            bev_trips[index] / 2,
            f"{int(bev_trips[index])}",
            ha="center",
            va="center",
            color="white",
            fontsize=8,
        )
        axes[0].text(
            index,
            bev_trips[index] + ice_trips[index] / 2,
            f"{int(ice_trips[index])}",
            ha="center",
            va="center",
            color="white",
            fontsize=8,
        )
    axes[0].legend(frameon=False, loc="upper center", ncol=2)
    _stacked_energy_panel(axes[1], labels, grid, pv_direct, bess)
    for ax in axes:
        ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
    fig.suptitle("Day-ahead dispatch and bus-energy supply", color=INK, fontsize=15)
    fig.text(
        0.5,
        0.925,
        "Low-PV case; PV-to-BESS is represented when discharged as BESS-to-bus",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.87))
    return _save_figure(fig, report_dir / "m0_m3_dispatch_energy")


def _stacked_energy_panel(
    ax,
    labels: Sequence[str],
    grid: Sequence[float],
    pv_direct: Sequence[float],
    bess: Sequence[float],
) -> None:
    energy_totals = [
        grid[i] + pv_direct[i] + bess[i] for i in range(len(labels))
    ]
    ax.bar(
        labels,
        grid,
        label="Grid-to-bus",
        color="#9CA3AF",
        edgecolor=INK,
        linewidth=0.7,
    )
    ax.bar(
        labels,
        pv_direct,
        bottom=grid,
        label="PV-to-bus",
        color=GOLD,
        edgecolor=INK,
        linewidth=0.7,
    )
    pv_bottom = [grid[i] + pv_direct[i] for i in range(len(labels))]
    ax.bar(
        labels,
        bess,
        bottom=pv_bottom,
        label="BESS-to-bus",
        color=BLUE,
        edgecolor=INK,
        linewidth=0.7,
    )
    for index, total in enumerate(energy_totals):
        ax.text(index, total + 18, f"{total:,.0f}", ha="center", fontsize=8)
        for value, bottom in (
            (grid[index], 0.0),
            (pv_direct[index], grid[index]),
            (bess[index], pv_bottom[index]),
        ):
            if value >= 40.0:
                ax.text(
                    index,
                    bottom + value / 2,
                    f"{value:,.0f}",
                    ha="center",
                    va="center",
                    color="white" if bottom > 0.0 or value == bess[index] else INK,
                    fontsize=7,
                )
    ax.set_ylim(0, max(energy_totals) * 1.14)
    ax.set_title("Energy delivered to buses by source", color=INK, fontsize=11)
    ax.set_ylabel("kWh")
    ax.legend(frameon=False, loc="upper center", ncol=3, fontsize=8)


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
        metadata={
            "Creator": REPORTING_SCHEMA_VERSION,
            "Date": None,
        },
    )
    _pyplot().close(fig)
    return [png_path, svg_path]


def _reporting_manifest(
    payload: Mapping[str, Any],
    *,
    output_dir: Path,
    builder_git_state: Mapping[str, Any],
    artifact_paths: Sequence[Path],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": REPORTING_SCHEMA_VERSION,
        "status": "READY",
        "source_comparison_payload_sha256": payload.get("payload_sha256"),
        "source_run_git_sha": payload.get("git_sha"),
        "report_builder_git_sha": builder_git_state.get("git_sha"),
        "report_builder_git_dirty": builder_git_state.get("git_dirty"),
        "comparison_scope": payload.get("comparison_scope"),
        "rolling_costs_mixed_into_comparison": False,
        "chart_map": [
            {
                "artifact": "m0_m3_cost_co2_effects.png/svg",
                "question": "How do M1--M3 change day-ahead cost and CO2 relative to M0?",
                "family": "signed comparison bar",
            },
            {
                "artifact": "m0_m3_dispatch_energy.png/svg",
                "question": "How do dispatch composition and bus-energy sources differ across M0--M3?",
                "family": "stacked comparison bar",
            },
        ],
        "artifacts": {
            str(path.resolve().relative_to(output_dir.resolve())).replace("\\", "/"): {
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
