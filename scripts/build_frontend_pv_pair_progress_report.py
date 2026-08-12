"""Build a progress-report evidence bundle for a controlled frontend PV pair.

The builder is a read-only postprocessor with respect to the two source runs.
It reads canonical pair/run artifacts, emits comparison-ready tables and
figures under ``progress_report/``, and records SHA-256 lineage for every
source and generated artifact.  It never upgrades a research claim: pair and
standalone-case statuses are copied from their canonical acceptance files.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402


HIGH_PV_COLOR = "#E69F00"
LOW_PV_COLOR = "#4C78A8"
BEV_COLOR = "#2A9D8F"
ICE_COLOR = "#6C757D"
GRID_COLOR = "#7B2CBF"
PV_COLOR = "#F4B400"
BESS_COLOR = "#00A6A6"
PASS_COLOR = "#2E7D32"
FAIL_COLOR = "#C62828"
NEUTRAL_COLOR = "#546E7A"
CASE_LABELS = {
    "sunny": "High PV (sunny curve)",
    "rain": "Low PV (rain curve)",
}
REQUIRED_CASE_FILES = (
    "artifact_completeness.json",
    "case_execution_metadata.json",
    "comparison_case_manifest.json",
    "input_audit.json",
    "kpi_summary.json",
    "physical_schedule_validation.json",
    "research_claim_scope.json",
    "results.xlsx",
    "simulation_conditions.json",
    "solver_settings.json",
    "vehicle_timelines.csv",
    "graph/literature_figures/manifest.json",
    "rolling_hourly_chain/executed_day_accounting.json",
    "rolling_hourly_chain/hourly_energy_flow_chart.csv",
    "rolling_hourly_chain/rolling_chain_summary.json",
)
REQUIRED_PAIR_FILES = (
    "assignment_difference.json",
    "research_comparison.csv",
    "solver_comparison.csv",
    "pair/pair_control_audit.json",
    "pair/pair_manifest.json",
)
REQUIRED_CASE_GATE_KEYS = {
    "fresh_prepared_input",
    "git_sha_matches_frozen",
    "git_clean",
    "prepared_scope_all_trips_served",
    "physical_schedule_accepted",
    "physical_all_required_checks_passed",
    "physical_zero_metrics",
    "grid_contract_zero",
    "bess_soc_zero",
    "bev_terminal_accepted",
    "bess_terminal_accepted",
    "no_fallback",
    "no_postsolve_repair",
    "rolling_24_of_24",
    "rolling_assignment_constant",
    "executed_day_accounting_eligible",
    "final_cost_reconciliation_ok",
    "artifact_completeness_ok",
    "certified_gap_at_most_requested",
    "solver_controls_match_formal_request",
    "tariff_condition_verified_from_canonical_slots",
    "solver_telemetry_complete",
    "phase4_verified_same_problem_warm_start",
    "candidate_evidence_present",
    "assignment_economic_audit_present",
    "used_powertrain_composition_search_certified",
    "solver_objective_accounting_semantics_valid",
    "candidate_selection_complete",
    "slot_energy_recourse_used",
    "terminal_claim_message_consistent",
}
REQUIRED_PAIR_GATE_KEYS = {
    "all_required_controls_match",
    "day_ahead_solver_controls_complete",
    "rolling_solver_controls_complete",
    "comparison_control_hash_matches",
    "pv_profile_hashes_differ",
    "sunny_expected_pv_total",
    "rain_expected_pv_total",
    "pair_manifest_accepted",
    "pair_formal_research_submission_ready",
    "assignment_difference_or_strict_audit",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return dict(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _safe_child(parent: Path, relative: str) -> Path:
    """Resolve a manifest-relative path without allowing directory escape."""

    candidate = parent / relative
    try:
        candidate.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Artifact path escapes its declared directory: {relative}"
        ) from exc
    return candidate


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _n(value: Any, default: float = 0.0) -> float:
    parsed = _number(value)
    return default if parsed is None else parsed


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:,.{digits}f}"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _asset(conditions: Mapping[str, Any]) -> dict[str, Any]:
    assets = conditions.get("depot_energy_assets")
    if isinstance(assets, Mapping):
        assets = [assets]
    candidates = [dict(item) for item in list(assets or ()) if isinstance(item, Mapping)]
    if len(candidates) != 1:
        raise ValueError(
            "Progress report requires exactly one selected depot energy asset; "
            f"observed={len(candidates)}"
        )
    return candidates[0]


def _assignment_mix(path: Path) -> dict[str, int]:
    trips: dict[str, tuple[str, str]] = {}
    for row in _read_csv(path):
        if not _bool(row.get("is_service")):
            continue
        trip_id = str(row.get("trip_id") or "").strip()
        vehicle_id = str(row.get("vehicle_id") or "").strip()
        powertrain = str(row.get("vehicle_type") or "").upper()
        if not trip_id or not vehicle_id:
            continue
        candidate = (vehicle_id, powertrain)
        previous = trips.get(trip_id)
        if previous is not None and previous != candidate:
            raise ValueError(f"Duplicate conflicting assignment: {trip_id}")
        trips[trip_id] = candidate
    electric = {"BEV", "PHEV", "FCEV"}
    bev_vehicles = {
        vehicle for vehicle, powertrain in trips.values() if powertrain in electric
    }
    ice_vehicles = {
        vehicle for vehicle, powertrain in trips.values() if powertrain not in electric
    }
    return {
        "used_bev": len(bev_vehicles),
        "used_ice": len(ice_vehicles),
        "bev_trips": sum(powertrain in electric for _, powertrain in trips.values()),
        "ice_trips": sum(powertrain not in electric for _, powertrain in trips.values()),
    }


def _case_payload(pair_dir: Path, case: str) -> dict[str, Any]:
    case_dir = pair_dir / case
    for relative in REQUIRED_CASE_FILES:
        path = case_dir / relative
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Missing required {case} artifact: {path}")
    executed = _read_json(
        case_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    if executed.get("eligible") is not True:
        raise ValueError(f"{case} executed-day accounting is not eligible")
    hourly = _read_csv(
        case_dir / "rolling_hourly_chain" / "hourly_energy_flow_chart.csv"
    )
    if len(hourly) != 24:
        raise ValueError(f"{case} hourly flow row count is {len(hourly)}, expected 24")
    step_indices = sorted(int(row["step_index"]) for row in hourly)
    if step_indices != list(range(24)):
        raise ValueError(f"{case} hourly step indices are incomplete: {step_indices}")
    conditions = _read_json(case_dir / "simulation_conditions.json")
    return {
        "case": case,
        "case_dir": case_dir,
        "executed": executed,
        "cost": dict(executed.get("cost_breakdown") or {}),
        "kpi": _read_json(case_dir / "kpi_summary.json"),
        "settings": _read_json(case_dir / "solver_settings.json"),
        "conditions": conditions,
        "asset": _asset(conditions),
        "claim": _read_json(case_dir / "research_claim_scope.json"),
        "manifest": _read_json(case_dir / "comparison_case_manifest.json"),
        "artifact_completeness": _read_json(case_dir / "artifact_completeness.json"),
        "execution": _read_json(case_dir / "case_execution_metadata.json"),
        "input_audit": _read_json(case_dir / "input_audit.json"),
        "physical": _read_json(case_dir / "physical_schedule_validation.json"),
        "rolling": _read_json(
            case_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
        ),
        "literature": _read_json(
            case_dir / "graph" / "literature_figures" / "manifest.json"
        ),
        "hourly": hourly,
        "mix": _assignment_mix(case_dir / "vehicle_timelines.csv"),
    }


def _research_metric_map(pair_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_csv(pair_dir / "research_comparison.csv"):
        metric = str(row.get("metric") or "")
        if metric:
            result[metric] = {
                "unit": row.get("unit"),
                "sunny": _number(row.get("sunny")),
                "rain": _number(row.get("rain")),
                "rain_minus_sunny": _number(row.get("rain_minus_sunny")),
                "sunny_source_artifact": row.get("sunny_source_artifact"),
                "rain_source_artifact": row.get("rain_source_artifact"),
            }
    required = {
        "PV generation",
        "Grid import",
        "PV to bus",
        "PV to BESS",
        "BESS to bus",
        "PV curtailed",
        "Used BEV",
        "Used ICE",
        "BEV trips",
        "ICE trips",
        "Fuel consumption",
        "Electricity cost",
        "Fuel cost",
        "Demand charge",
        "Total cost",
        "CO2",
        "Certified MILP gap",
    }
    missing = sorted(required - set(result))
    if missing:
        raise ValueError(f"research_comparison.csv lacks metrics: {missing}")
    return result


def _load_case_gates(pair_dir: Path) -> tuple[dict[str, Any], str]:
    dedicated = pair_dir / "case_gate_audits.json"
    if dedicated.is_file():
        return _read_json(dedicated), "case_gate_audits.json"
    completion_path = pair_dir / "completion_audit.json"
    completion = _read_json(completion_path)
    gates = completion.get("case_gate_audits")
    if not isinstance(gates, Mapping):
        raise ValueError(
            "Neither case_gate_audits.json nor completion_audit.json with "
            "case_gate_audits is available"
        )
    return dict(gates), "completion_audit.json"


def _source_artifacts(
    pair_dir: Path,
    *,
    case_gate_source: str,
) -> list[dict[str, Any]]:
    paths = [pair_dir / relative for relative in REQUIRED_PAIR_FILES]
    paths.append(pair_dir / case_gate_source)
    for case in ("sunny", "rain"):
        paths.extend(pair_dir / case / relative for relative in REQUIRED_CASE_FILES)
        literature_dir = pair_dir / case / "graph" / "literature_figures"
        literature_manifest = _read_json(literature_dir / "manifest.json")
        for entry in list(literature_manifest.get("entries") or ()):
            if not isinstance(entry, Mapping):
                continue
            for artifact in list(entry.get("artifact_records") or ()):
                if not isinstance(artifact, Mapping):
                    continue
                relative = str(artifact.get("path") or "").strip()
                if not relative:
                    raise ValueError(
                        f"Missing literature artifact path in {case} manifest"
                    )
                artifact_path = _safe_child(literature_dir, relative)
                paths.append(artifact_path)
                expected_hash = str(artifact.get("sha256") or "").strip()
                if (
                    artifact_path.is_file()
                    and expected_hash
                    and _sha256(artifact_path) != expected_hash
                ):
                    raise ValueError(
                        f"Literature artifact hash mismatch: {artifact_path}"
                    )
    missing = [path for path in paths if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise FileNotFoundError(
            "Missing required progress-report sources: "
            + ", ".join(str(path) for path in missing)
        )
    return [_record(pair_dir, path) for path in sorted(set(paths))]


def _save_figure(figure: Any, output_base: Path) -> list[Path]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    png = output_base.with_suffix(".png")
    svg = output_base.with_suffix(".svg")
    figure.savefig(
        png,
        dpi=200,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": "master-course controlled PV pair reporter"},
    )
    figure.savefig(
        svg,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Date": None, "Creator": "master-course"},
    )
    plt.close(figure)
    return [png, svg]


def _style_axis(axis: Any) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(axis="y", alpha=0.22, linewidth=0.7)


def _annotate_bars(axis: Any, bars: Iterable[Any], *, digits: int = 0) -> None:
    for bar in bars:
        height = float(bar.get_height())
        axis.annotate(
            f"{height:,.{digits}f}",
            (bar.get_x() + bar.get_width() / 2.0, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )


def _figure_summary(
    output_dir: Path,
    metrics: Mapping[str, Mapping[str, Any]],
    pair_manifest: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
) -> list[Path]:
    figure, axis = plt.subplots(figsize=(13.2, 7.4))
    axis.set_axis_off()
    formal_ready = pair_manifest.get("formal_research_submission_ready") is True
    title_status = (
        "PAIR MANIFEST READY" if formal_ready else "PAIR MANIFEST BLOCKED"
    )
    status_color = PASS_COLOR if formal_ready else FAIL_COLOR
    figure.suptitle(
        "Controlled High-PV / Low-PV Progress Evidence",
        x=0.05,
        ha="left",
        fontsize=20,
        fontweight="bold",
    )
    axis.text(
        0.97,
        1.02,
        title_status,
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=12,
        fontweight="bold",
        color="white",
        bbox={"boxstyle": "round,pad=0.45", "fc": status_color, "ec": "none"},
    )
    cards = [
        (
            "PV generation",
            f"{_fmt(metrics['PV generation']['sunny'], 1)} vs "
            f"{_fmt(metrics['PV generation']['rain'], 1)} kWh",
            "Only the PV curve differs",
        ),
        (
            "Used BEVs",
            f"{int(_n(metrics['Used BEV']['sunny']))} vs "
            f"{int(_n(metrics['Used BEV']['rain']))}",
            f"High-PV response: +{int(_n(metrics['Used BEV']['sunny']) - _n(metrics['Used BEV']['rain']))}",
        ),
        (
            "BEV trips",
            f"{int(_n(metrics['BEV trips']['sunny']))} vs "
            f"{int(_n(metrics['BEV trips']['rain']))}",
            f"High-PV response: +{int(_n(metrics['BEV trips']['sunny']) - _n(metrics['BEV trips']['rain']))}",
        ),
        (
            "Executed total cost",
            f"JPY {_fmt(metrics['Total cost']['sunny'], 0)} vs "
            f"{_fmt(metrics['Total cost']['rain'], 0)}",
            f"Low minus high: JPY {_fmt(metrics['Total cost']['rain_minus_sunny'], 0)}",
        ),
        (
            "Fuel consumption",
            f"{_fmt(metrics['Fuel consumption']['sunny'], 1)} vs "
            f"{_fmt(metrics['Fuel consumption']['rain'], 1)} L",
            "Canonical run KPI",
        ),
        (
            "Operational CO2",
            f"{_fmt(metrics['CO2']['sunny'], 1)} vs "
            f"{_fmt(metrics['CO2']['rain'], 1)} kg",
            "Executed-day accounting",
        ),
    ]
    positions = [(0.04, 0.64), (0.36, 0.64), (0.68, 0.64), (0.04, 0.31), (0.36, 0.31), (0.68, 0.31)]
    for (heading, value, note), (left, bottom) in zip(cards, positions):
        patch = FancyBboxPatch(
            (left, bottom),
            0.28,
            0.23,
            transform=axis.transAxes,
            boxstyle="round,pad=0.012,rounding_size=0.015",
            facecolor="#F6F8FA",
            edgecolor="#D0D7DE",
            linewidth=1.0,
        )
        axis.add_patch(patch)
        axis.text(left + 0.018, bottom + 0.176, heading, transform=axis.transAxes, fontsize=10, color="#57606A")
        axis.text(left + 0.018, bottom + 0.105, value, transform=axis.transAxes, fontsize=14, fontweight="bold", color="#24292F")
        axis.text(left + 0.018, bottom + 0.040, note, transform=axis.transAxes, fontsize=8.5, color="#57606A")
    high_claim = cases["sunny"]["claim"]
    low_claim = cases["rain"]["claim"]
    axis.text(
        0.04,
        0.18,
        "Scope: same 2025-08-05 weekday service; low-PV uses the 2025-08-10 PV curve. "
        "This is a controlled PV-supply sensitivity, not two observed operating days.",
        transform=axis.transAxes,
        fontsize=9.5,
        color="#24292F",
    )
    axis.text(
        0.04,
        0.115,
        "Standalone case files remain "
        f"{high_claim.get('teacher_release_status')}/{low_claim.get('teacher_release_status')}; "
        "pair-level claims use pair/pair_manifest.json.",
        transform=axis.transAxes,
        fontsize=9,
        color="#57606A",
    )
    return _save_figure(figure, output_dir / "00_progress_summary")


def _figure_composition(
    output_dir: Path, metrics: Mapping[str, Mapping[str, Any]]
) -> list[Path]:
    figure, axes = plt.subplots(1, 2, figsize=(12.4, 5.2))
    labels = ["High PV", "Low PV"]
    x = [0, 1]
    bev = [_n(metrics["Used BEV"][case]) for case in ("sunny", "rain")]
    ice = [_n(metrics["Used ICE"][case]) for case in ("sunny", "rain")]
    axes[0].bar(x, bev, color=BEV_COLOR, label="BEV")
    axes[0].bar(x, ice, bottom=bev, color=ICE_COLOR, label="ICE")
    axes[0].set_title("Used vehicle composition")
    axes[0].set_ylabel("Vehicles")
    axes[0].set_xticks(x, labels)
    for idx in x:
        axes[0].text(idx, bev[idx] / 2, f"BEV {int(bev[idx])}", ha="center", va="center", color="white", fontweight="bold")
        if ice[idx] > 0:
            axes[0].text(idx, bev[idx] + ice[idx] / 2, f"ICE {int(ice[idx])}", ha="center", va="center", color="white", fontweight="bold")
    axes[0].legend(frameon=False)
    _style_axis(axes[0])

    bev_trips = [_n(metrics["BEV trips"][case]) for case in ("sunny", "rain")]
    ice_trips = [_n(metrics["ICE trips"][case]) for case in ("sunny", "rain")]
    axes[1].bar(x, bev_trips, color=BEV_COLOR, label="BEV")
    axes[1].bar(x, ice_trips, bottom=bev_trips, color=ICE_COLOR, label="ICE")
    axes[1].set_title("Served trip composition")
    axes[1].set_ylabel("Trips")
    axes[1].set_xticks(x, labels)
    for idx in x:
        axes[1].text(idx, bev_trips[idx] / 2, f"BEV {int(bev_trips[idx])}", ha="center", va="center", color="white", fontweight="bold")
        if ice_trips[idx] > 0:
            axes[1].text(idx, bev_trips[idx] + ice_trips[idx] / 2, f"ICE {int(ice_trips[idx])}", ha="center", va="center", color="white", fontweight="bold")
    axes[1].legend(frameon=False)
    _style_axis(axes[1])
    figure.suptitle("Powertrain response to PV availability", fontsize=15, fontweight="bold")
    figure.text(0.5, 0.01, "Source: vehicle_timelines.csv; all 264 trips served in both cases.", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    return _save_figure(figure, output_dir / "01_fleet_and_trip_composition")


def _figure_energy(
    output_dir: Path, metrics: Mapping[str, Mapping[str, Any]]
) -> list[Path]:
    names = ["PV generated", "PV to bus", "PV to BESS", "BESS to bus", "Grid to bus", "PV curtailed"]
    keys = ["PV generation", "PV to bus", "PV to BESS", "BESS to bus", "Grid import", "PV curtailed"]
    x = list(range(len(names)))
    width = 0.36
    high = [_n(metrics[key]["sunny"]) for key in keys]
    low = [_n(metrics[key]["rain"]) for key in keys]
    figure, axis = plt.subplots(figsize=(12.8, 5.8))
    high_bars = axis.bar([value - width / 2 for value in x], high, width, label="High PV", color=HIGH_PV_COLOR)
    low_bars = axis.bar([value + width / 2 for value in x], low, width, label="Low PV", color=LOW_PV_COLOR)
    axis.set_title("Executed-day depot energy metrics", fontsize=15, fontweight="bold")
    axis.set_ylabel("Energy (kWh)")
    axis.set_xticks(x, names, rotation=18, ha="right")
    axis.legend(frameon=False, ncol=2)
    _annotate_bars(axis, high_bars, digits=0)
    _annotate_bars(axis, low_bars, digits=0)
    _style_axis(axis)
    figure.text(0.5, 0.01, "Flows are shown as separate canonical metrics and are not summed as one energy balance.", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    return _save_figure(figure, output_dir / "02_energy_flow_comparison")


def _hourly_values(rows: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    return [_n(row.get(key)) for row in rows]


def _bess_soc(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = json.loads(str(row.get("bess_end_soc_kwh_by_depot") or "{}"))
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid BESS SOC mapping in hourly flow CSV")
        values.append(sum(_n(value) for value in raw.values()))
    return values


def _figure_hourly(
    output_dir: Path, cases: Mapping[str, Mapping[str, Any]]
) -> list[Path]:
    figure, axes = plt.subplots(2, 2, figsize=(14.2, 9.0), sharex=True)
    hours = list(range(24))
    for case, color in (("sunny", HIGH_PV_COLOR), ("rain", LOW_PV_COLOR)):
        rows = cases[case]["hourly"]
        axes[0, 0].plot(hours, _hourly_values(rows, "pv_generated_kwh"), marker="o", markersize=3, linewidth=2, color=color, label=CASE_LABELS[case])
        axes[0, 1].plot(hours, _bess_soc(rows), marker="o", markersize=3, linewidth=2, color=color, label=CASE_LABELS[case])
    axes[0, 0].set_title("PV generation by hour")
    axes[0, 0].set_ylabel("kWh per slot")
    axes[0, 1].set_title("BESS end-of-slot SOC")
    axes[0, 1].set_ylabel("kWh")
    axes[0, 0].legend(frameon=False)
    axes[0, 1].legend(frameon=False)
    for column, case in enumerate(("sunny", "rain")):
        rows = cases[case]["hourly"]
        pv = _hourly_values(rows, "pv_to_bus_kwh")
        bess = _hourly_values(rows, "bess_to_bus_kwh")
        grid = _hourly_values(rows, "grid_to_bus_kwh")
        axes[1, column].bar(hours, pv, color=PV_COLOR, label="PV to bus")
        axes[1, column].bar(hours, bess, bottom=pv, color=BESS_COLOR, label="BESS to bus")
        axes[1, column].bar(hours, grid, bottom=[pv[i] + bess[i] for i in hours], color=GRID_COLOR, label="Grid to bus")
        axes[1, column].set_title(f"Bus charging sources: {CASE_LABELS[case]}")
        axes[1, column].set_ylabel("kWh per slot")
        axes[1, column].set_xlabel("Hour of service day")
        axes[1, column].legend(frameon=False, ncol=3, fontsize=8)
    for axis in axes.flat:
        axis.set_xticks(range(0, 24, 3))
        _style_axis(axis)
    figure.suptitle("Executed 24-hour energy profiles", fontsize=16, fontweight="bold")
    figure.text(0.5, 0.01, "Source: rolling_hourly_chain/hourly_energy_flow_chart.csv (24 accepted rolling slots per case).", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.035, 1, 0.96))
    return _save_figure(figure, output_dir / "03_hourly_energy_profiles")


def _figure_cost(
    output_dir: Path, cases: Mapping[str, Mapping[str, Any]]
) -> list[Path]:
    candidate_components = [
        ("Electricity", "electricity_cost", "#4C78A8"),
        ("Fuel", "fuel_cost", "#F58518"),
        ("Demand", "demand_cost", "#B279A2"),
        ("Vehicle-day", "vehicle_usage_cost_jpy", "#54A24B"),
        ("CO2", "co2_cost", "#E45756"),
        ("Degradation", "stationary_battery_degradation_cost", "#72B7B2"),
        ("Contract overage", "contract_overage_cost", "#FF9DA6"),
    ]
    components = [
        component
        for component in candidate_components
        if component[1]
        in {"electricity_cost", "fuel_cost", "vehicle_usage_cost_jpy"}
        or any(
            abs(_n(cases[case]["cost"].get(component[1]))) > 1.0e-9
            for case in ("sunny", "rain")
        )
    ]
    labels = ["High PV", "Low PV"]
    figure, axis = plt.subplots(figsize=(10.8, 6.2))
    bottoms = [0.0, 0.0]
    for label, key, color in components:
        values = [_n(cases[case]["cost"].get(key)) for case in ("sunny", "rain")]
        axis.bar(labels, values, bottom=bottoms, color=color, label=label)
        bottoms = [bottoms[index] + values[index] for index in range(2)]
    canonical_totals = [
        _n(cases[case]["cost"].get("total_cost"))
        for case in ("sunny", "rain")
    ]
    residuals = [
        canonical_totals[index] - bottoms[index] for index in range(2)
    ]
    if any(value < -1.0e-6 for value in residuals):
        raise ValueError(
            "Selected canonical cost components exceed total cost: "
            f"components={bottoms}, totals={canonical_totals}"
        )
    if any(value > 1.0e-6 for value in residuals):
        axis.bar(
            labels,
            residuals,
            bottom=bottoms,
            color="#9D755D",
            label="Other canonical",
        )
        bottoms = canonical_totals
    for index, total in enumerate(bottoms):
        axis.text(index, total + max(bottoms) * 0.015, f"JPY {total:,.0f}", ha="center", fontweight="bold")
    axis.set_title("Canonical executed-day cost breakdown", fontsize=15, fontweight="bold")
    axis.set_ylabel("JPY/day")
    axis.set_ylim(0.0, max(bottoms) * 1.18)
    axis.legend(
        frameon=False,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.0),
    )
    _style_axis(axis)
    figure.text(0.5, 0.01, "Demand charge is 0 JPY/kW; vehicle-day cost is charged once per used bus.", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    return _save_figure(figure, output_dir / "04_cost_breakdown_comparison")


def _figure_environment(
    output_dir: Path, metrics: Mapping[str, Mapping[str, Any]]
) -> list[Path]:
    labels = ["High PV", "Low PV"]
    colors = [HIGH_PV_COLOR, LOW_PV_COLOR]
    figure, axes = plt.subplots(1, 2, figsize=(11.8, 5.2))
    fuel = [_n(metrics["Fuel consumption"][case]) for case in ("sunny", "rain")]
    co2 = [_n(metrics["CO2"][case]) for case in ("sunny", "rain")]
    fuel_bars = axes[0].bar(labels, fuel, color=colors)
    co2_bars = axes[1].bar(labels, co2, color=colors)
    axes[0].set_title("ICE fuel consumption")
    axes[0].set_ylabel("L/day")
    axes[1].set_title("Operational CO2")
    axes[1].set_ylabel("kgCO2/day")
    _annotate_bars(axes[0], fuel_bars, digits=1)
    _annotate_bars(axes[1], co2_bars, digits=1)
    for axis in axes:
        _style_axis(axis)
    figure.suptitle("Fuel and operational emissions", fontsize=15, fontweight="bold")
    figure.text(0.5, 0.01, "Source: executed-day accounting and canonical run KPI; asset lifecycle emissions are outside this scope.", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    return _save_figure(figure, output_dir / "05_fuel_and_emissions")


def _figure_acceptance(
    output_dir: Path,
    metrics: Mapping[str, Mapping[str, Any]],
    cases: Mapping[str, Mapping[str, Any]],
    case_gates: Mapping[str, Any],
    pair_control: Mapping[str, Any],
) -> list[Path]:
    figure, axes = plt.subplots(1, 2, figsize=(14.0, 6.2), gridspec_kw={"width_ratios": [0.8, 1.6]})
    gaps = [100.0 * _n(metrics["Certified MILP gap"][case]) for case in ("sunny", "rain")]
    requested = [
        100.0 * _n(cases[case]["settings"].get("mip_gap_requested_ratio"))
        for case in ("sunny", "rain")
    ]
    if requested[0] <= 0.0 or not math.isclose(
        requested[0], requested[1], rel_tol=0.0, abs_tol=1.0e-12
    ):
        raise ValueError(f"Invalid or mismatched requested MILP gaps: {requested}")
    bars = axes[0].bar(["High PV", "Low PV"], gaps, color=[HIGH_PV_COLOR, LOW_PV_COLOR])
    axes[0].axhline(
        requested[0],
        color=FAIL_COLOR,
        linestyle="--",
        linewidth=1.6,
        label=f"Declared target ({requested[0]:g}%)",
    )
    axes[0].set_title("Certified MILP gap")
    axes[0].set_ylabel("Percent")
    axes[0].legend(frameon=False, fontsize=8)
    _annotate_bars(axes[0], bars, digits=3)
    _style_axis(axes[0])

    selected_checks = [
        ("Fresh Prepare", "fresh_prepared_input", None),
        ("All trips served", "prepared_scope_all_trips_served", None),
        ("Physical validation", "physical_all_required_checks_passed", None),
        ("24/24 Rolling", "rolling_24_of_24", None),
        ("Accounting", "final_cost_reconciliation_ok", None),
        ("Artifact bundle", "artifact_completeness_ok", None),
        ("Gap target", "certified_gap_at_most_requested", None),
        ("Fixed controls", None, "all_required_controls_match"),
        ("PV hashes differ", None, "pv_profile_hashes_differ"),
        ("Pair formal ready", None, "pair_formal_research_submission_ready"),
    ]
    matrix: list[list[int]] = []
    for _, case_key, pair_key in selected_checks:
        if case_key:
            matrix.append([
                1 if dict(case_gates["sunny"]).get("checks", {}).get(case_key) is True else 0,
                1 if dict(case_gates["rain"]).get("checks", {}).get(case_key) is True else 0,
                -1,
            ])
        else:
            matrix.append([-1, -1, 1 if pair_control.get("checks", {}).get(pair_key) is True else 0])
    from matplotlib.colors import ListedColormap

    axes[1].imshow(matrix, aspect="auto", cmap=ListedColormap(["#ECEFF1", FAIL_COLOR, PASS_COLOR]), vmin=-1, vmax=1)
    axes[1].set_xticks([0, 1, 2], ["High PV", "Low PV", "Pair"])
    axes[1].set_yticks(range(len(selected_checks)), [item[0] for item in selected_checks])
    for row_index, row in enumerate(matrix):
        for column_index, value in enumerate(row):
            axes[1].text(column_index, row_index, "—" if value < 0 else ("PASS" if value else "FAIL"), ha="center", va="center", color="white" if value >= 0 else "#607D8B", fontsize=8, fontweight="bold")
    axes[1].set_title("Selected acceptance gates")
    axes[1].tick_params(length=0)
    figure.suptitle("Optimality certificate and evidence gates", fontsize=15, fontweight="bold")
    figure.text(0.5, 0.01, "The exhaustive gate matrix is provided in 03_validation_gate_matrix.csv.", ha="center", fontsize=8.5, color="#57606A")
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    return _save_figure(figure, output_dir / "06_solver_and_acceptance")


def _control_rows(
    cases: Mapping[str, Mapping[str, Any]], pair_control: Mapping[str, Any]
) -> list[dict[str, Any]]:
    controls = dict(pair_control.get("controls") or {})
    rows: list[dict[str, Any]] = []
    for key, value in controls.items():
        if not isinstance(value, Mapping):
            continue
        rows.append(
            {
                "control": key,
                "sunny": json.dumps(value.get("sunny"), ensure_ascii=False, sort_keys=True) if isinstance(value.get("sunny"), (dict, list)) else value.get("sunny"),
                "rain": json.dumps(value.get("rain"), ensure_ascii=False, sort_keys=True) if isinstance(value.get("rain"), (dict, list)) else value.get("rain"),
                "match": value.get("match"),
                "source_artifact": "pair/pair_control_audit.json",
            }
        )
    for field, label in (
        ("pv_capacity_kw", "pv_rated_output_kw"),
        ("estimated_installable_area_m2", "estimated_installable_area_m2"),
        ("estimated_depot_area_from_pv_capacity_m2", "estimated_depot_area_from_pv_capacity_m2"),
        ("bess_energy_kwh", "bess_energy_kwh"),
        ("bess_power_kw", "bess_power_kw"),
        ("bess_initial_soc_kwh", "bess_initial_soc_kwh"),
        ("bess_terminal_soc_target_kwh", "bess_terminal_soc_target_kwh"),
    ):
        rows.append(
            {
                "control": label,
                "sunny": cases["sunny"]["asset"].get(field),
                "rain": cases["rain"]["asset"].get(field),
                "match": cases["sunny"]["asset"].get(field) == cases["rain"]["asset"].get(field),
                "source_artifact": "sunny|rain/simulation_conditions.json",
            }
        )
    rows.append(
        {
            "control": "charger_count",
            "sunny": cases["sunny"]["conditions"].get("charger_count"),
            "rain": cases["rain"]["conditions"].get("charger_count"),
            "match": cases["sunny"]["conditions"].get("charger_count") == cases["rain"]["conditions"].get("charger_count"),
            "source_artifact": "sunny|rain/simulation_conditions.json",
        }
    )
    return rows


def _provenance_rows(
    cases: Mapping[str, Mapping[str, Any]],
    case_gates: Mapping[str, Any],
    pair_manifest: Mapping[str, Any],
    pair_control: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in ("sunny", "rain"):
        data = cases[case]
        execution = data["execution"]
        input_audit = data["input_audit"]
        comparison = data["manifest"]
        rows.append(
            {
                "scope": case,
                "label": CASE_LABELS[case],
                "scenario_id": execution.get("scenario_id")
                or input_audit.get("scenario_id"),
                "prepared_input_id": execution.get("prepared_input_id")
                or input_audit.get("prepared_input_id"),
                "job_id": execution.get("job_id"),
                "source_run_id": Path(
                    str(execution.get("run_dir") or "")
                ).name,
                "frozen_git_sha": execution.get("frozen_git_sha"),
                "comparison_control_hash": comparison.get(
                    "comparison_control_hash"
                ),
                "pv_profile_hash": comparison.get("pv_profile_hash"),
                "assignment_hash": comparison.get("assignment_hash"),
                "case_gate_accepted": dict(case_gates.get(case) or {}).get(
                    "accepted"
                ),
                "standalone_teacher_release_status": data["claim"].get(
                    "teacher_release_status"
                ),
                "standalone_blockers": ";".join(
                    data["claim"].get("teacher_release_failed_checks") or []
                ),
                "pair_control_accepted": None,
                "pair_formal_research_submission_ready": None,
                "source_artifacts": (
                    f"{case}/case_execution_metadata.json; "
                    f"{case}/input_audit.json; "
                    f"{case}/comparison_case_manifest.json; "
                    f"{case}/research_claim_scope.json"
                ),
            }
        )
    rows.append(
        {
            "scope": "pair",
            "label": "Controlled PV pair",
            "scenario_id": None,
            "prepared_input_id": None,
            "job_id": None,
            "source_run_id": None,
            "frozen_git_sha": rows[0]["frozen_git_sha"],
            "comparison_control_hash": pair_control.get(
                "comparison_control_hash"
            ),
            "pv_profile_hash": (
                f"sunny={pair_control.get('sunny_pv_profile_hash')};"
                f"rain={pair_control.get('rain_pv_profile_hash')}"
            ),
            "assignment_hash": None,
            "case_gate_accepted": None,
            "standalone_teacher_release_status": None,
            "standalone_blockers": None,
            "pair_control_accepted": pair_control.get("accepted"),
            "pair_formal_research_submission_ready": pair_manifest.get(
                "formal_research_submission_ready"
            ),
            "source_artifacts": (
                "pair/pair_manifest.json; pair/pair_control_audit.json"
            ),
        }
    )
    return rows


def _outcome_rows(
    cases: Mapping[str, Mapping[str, Any]], metrics: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in ("sunny", "rain"):
        case_data = cases[case]
        cost = case_data["cost"]
        kpi = case_data["kpi"]
        mix = case_data["mix"]
        rows.append(
            {
                "case": case,
                "label": CASE_LABELS[case],
                **mix,
                "served_trips": int(_n(kpi.get("served_trip_count"))),
                "unserved_trips": int(_n(kpi.get("unserved_trip_count"))),
                "service_km": kpi.get("service_km"),
                "deadhead_km": kpi.get("deadhead_total_km"),
                "pv_generated_kwh": metrics["PV generation"][case],
                "pv_to_bus_kwh": metrics["PV to bus"][case],
                "pv_to_bess_kwh": metrics["PV to BESS"][case],
                "bess_to_bus_kwh": metrics["BESS to bus"][case],
                "grid_import_kwh": metrics["Grid import"][case],
                "pv_curtailed_kwh": metrics["PV curtailed"][case],
                "fuel_consumption_l": metrics["Fuel consumption"][case],
                "electricity_cost_jpy": metrics["Electricity cost"][case],
                "fuel_cost_jpy": metrics["Fuel cost"][case],
                "vehicle_usage_cost_jpy": cost.get("vehicle_usage_cost_jpy"),
                "demand_charge_jpy": metrics["Demand charge"][case],
                "co2_cost_jpy": cost.get("co2_cost"),
                "battery_degradation_cost_jpy": cost.get(
                    "stationary_battery_degradation_cost"
                ),
                "contract_overage_cost_jpy": cost.get(
                    "contract_overage_cost"
                ),
                "driver_cost_jpy": cost.get("driver_cost"),
                "unserved_penalty_jpy": cost.get("unserved_penalty"),
                "switch_cost_jpy": cost.get("switch_cost"),
                "deviation_cost_jpy": cost.get("deviation_cost"),
                "total_cost_jpy": metrics["Total cost"][case],
                "total_co2_kg": metrics["CO2"][case],
                "certified_mip_gap_ratio": metrics["Certified MILP gap"][case],
                "teacher_release_status_standalone": case_data["claim"].get("teacher_release_status"),
                "standalone_release_blockers": ";".join(case_data["claim"].get("teacher_release_failed_checks") or []),
                "source_artifacts": "research_comparison.csv; kpi_summary.json; rolling_hourly_chain/executed_day_accounting.json; vehicle_timelines.csv",
            }
        )
    return rows


def _hourly_rows(cases: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fields = (
        "step_index",
        "current_time",
        "execution_minutes",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "bess_to_bus_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "bess_end_soc_kwh_by_depot",
        "bev_soc_min_kwh",
        "bev_soc_mean_kwh",
        "charging_kw_max",
    )
    for case in ("sunny", "rain"):
        for row in cases[case]["hourly"]:
            rows.append(
                {
                    "case": case,
                    "case_label": CASE_LABELS[case],
                    **{field: row.get(field) for field in fields},
                    "source_artifact": f"{case}/rolling_hourly_chain/hourly_energy_flow_chart.csv",
                }
            )
    return rows


def _gate_rows(
    case_gates: Mapping[str, Any],
    pair_control: Mapping[str, Any],
    *,
    case_gate_source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in ("sunny", "rain"):
        audit = dict(case_gates.get(case) or {})
        checks = dict(audit.get("checks") or {})
        missing = sorted(REQUIRED_CASE_GATE_KEYS - set(checks))
        if missing:
            raise ValueError(f"{case} case gate audit lacks checks: {missing}")
        for check, passed in checks.items():
            rows.append(
                {
                    "scope": case,
                    "check": check,
                    "passed": passed,
                    "source_artifact": case_gate_source,
                }
            )
    pair_checks = dict(pair_control.get("checks") or {})
    missing_pair_checks = sorted(REQUIRED_PAIR_GATE_KEYS - set(pair_checks))
    if missing_pair_checks:
        raise ValueError(
            f"Pair control audit lacks checks: {missing_pair_checks}"
        )
    for check, passed in pair_checks.items():
        rows.append(
            {
                "scope": "pair",
                "check": check,
                "passed": passed,
                "source_artifact": "pair/pair_control_audit.json",
            }
        )
    return rows


def _per_run_figure_rows(
    cases: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in ("sunny", "rain"):
        manifest = cases[case]["literature"]
        for entry in list(manifest.get("entries") or ()):
            if not isinstance(entry, Mapping) or entry.get("kind") != "figure":
                continue
            files = list(entry.get("artifact_files") or ())
            for filename in files:
                artifact_path = _safe_child(
                    cases[case]["case_dir"]
                    / "graph"
                    / "literature_figures",
                    str(filename),
                )
                if not artifact_path.is_file() or artifact_path.stat().st_size <= 0:
                    raise FileNotFoundError(
                        f"Missing per-run literature artifact: {artifact_path}"
                    )
            rows.append(
                {
                    "case": case,
                    "figure_id": entry.get("figure_id"),
                    "title": entry.get("title"),
                    "analytical_question": entry.get("analytical_question"),
                    "png": next((f"{case}/graph/literature_figures/{name}" for name in files if str(name).endswith(".png")), None),
                    "svg": next((f"{case}/graph/literature_figures/{name}" for name in files if str(name).endswith(".svg")), None),
                    "source_csv": next((f"{case}/graph/literature_figures/{name}" for name in files if str(name).endswith(".csv")), None),
                    "canonical_sources": ";".join(f"{case}/{name}" for name in list(entry.get("canonical_sources") or ())),
                    "eligibility": manifest.get("status"),
                }
            )
    if len(rows) != 10:
        raise ValueError(f"Expected 10 per-run literature figures, observed {len(rows)}")
    return rows


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    output = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    output.extend(
        "| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |"
        for row in rows
    )
    return output


def build_progress_report(pair_dir: Path) -> dict[str, Any]:
    pair_dir = pair_dir.resolve()
    for relative in REQUIRED_PAIR_FILES:
        path = pair_dir / relative
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Missing required pair artifact: {path}")
    output_dir = pair_dir / "progress_report"
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite progress report: {output_dir}")
    output_dir.mkdir(parents=True)

    cases = {case: _case_payload(pair_dir, case) for case in ("sunny", "rain")}
    metrics = _research_metric_map(pair_dir)
    pair_manifest = _read_json(pair_dir / "pair" / "pair_manifest.json")
    pair_control = _read_json(pair_dir / "pair" / "pair_control_audit.json")
    case_gates, case_gate_source = _load_case_gates(pair_dir)
    assignment = _read_json(pair_dir / "assignment_difference.json")
    source_records = _source_artifacts(
        pair_dir,
        case_gate_source=case_gate_source,
    )

    provenance_rows = _provenance_rows(
        cases,
        case_gates,
        pair_manifest,
        pair_control,
    )
    control_rows = _control_rows(cases, pair_control)
    outcome_rows = _outcome_rows(cases, metrics)
    hourly_rows = _hourly_rows(cases)
    gate_rows = _gate_rows(
        case_gates,
        pair_control,
        case_gate_source=case_gate_source,
    )
    per_run_figure_rows = _per_run_figure_rows(cases)
    table_paths = [
        output_dir / "00_release_and_provenance.csv",
        output_dir / "01_scenario_controls.csv",
        output_dir / "02_outcome_kpis.csv",
        output_dir / "03_validation_gate_matrix.csv",
        output_dir / "04_hourly_energy_comparison.csv",
        output_dir / "05_per_run_figure_catalog.csv",
    ]
    _write_csv(table_paths[0], list(provenance_rows[0]), provenance_rows)
    _write_csv(table_paths[1], ["control", "sunny", "rain", "match", "source_artifact"], control_rows)
    _write_csv(table_paths[2], list(outcome_rows[0]), outcome_rows)
    _write_csv(table_paths[3], ["scope", "check", "passed", "source_artifact"], gate_rows)
    _write_csv(table_paths[4], list(hourly_rows[0]), hourly_rows)
    _write_csv(table_paths[5], list(per_run_figure_rows[0]), per_run_figure_rows)

    figure_paths: list[Path] = []
    figure_paths.extend(_figure_summary(output_dir, metrics, pair_manifest, cases))
    figure_paths.extend(_figure_composition(output_dir, metrics))
    figure_paths.extend(_figure_energy(output_dir, metrics))
    figure_paths.extend(_figure_hourly(output_dir, cases))
    figure_paths.extend(_figure_cost(output_dir, cases))
    figure_paths.extend(_figure_environment(output_dir, metrics))
    figure_paths.extend(
        _figure_acceptance(
            output_dir,
            metrics,
            cases,
            case_gates,
            pair_control,
        )
    )

    pair_ready = pair_manifest.get("formal_research_submission_ready") is True
    report_lines = [
        "# 進捗報告用・制御PV pair結果",
        "",
        f"- Pair判定: `{'READY' if pair_ready else 'BLOCKED'}`",
        f"- 凍結Git SHA: `{pair_manifest.get('git_sha') or pair_control.get('controls', {}).get('git_sha', {}).get('sunny')}`",
        f"- 比較control hash: `{pair_control.get('comparison_control_hash')}`",
        "- 比較の意味: 同一2025-08-05平日ダイヤに対するhigh-PV/low-PV供給感度。実際の異なる2運行日の比較ではない。",
        "",
        "## 主要結果",
        "",
        *_markdown_table(
            ["指標", "High PV", "Low PV", "Low - High", "単位"],
            (
                (
                    metric,
                    _fmt(metrics[metric]["sunny"], 3),
                    _fmt(metrics[metric]["rain"], 3),
                    _fmt(metrics[metric]["rain_minus_sunny"], 3),
                    metrics[metric]["unit"],
                )
                for metric in (
                    "PV generation",
                    "Used BEV",
                    "Used ICE",
                    "BEV trips",
                    "ICE trips",
                    "Grid import",
                    "Fuel consumption",
                    "Total cost",
                    "CO2",
                    "Certified MILP gap",
                )
            ),
        ),
        "",
        "## 図表",
        "",
        "1. `00_progress_summary.png`: 進捗概要とclaim scope",
        "2. `01_fleet_and_trip_composition.png`: 使用車両・担当便の動力種構成",
        "3. `02_energy_flow_comparison.png`: PV・BESS・系統の実行日エネルギー",
        "4. `03_hourly_energy_profiles.png`: 24時間のPV、BESS SOC、充電源",
        "5. `04_cost_breakdown_comparison.png`: 正本会計の費用内訳",
        "6. `05_fuel_and_emissions.png`: 燃料消費と運用CO2",
        "7. `06_solver_and_acceptance.png`: certified gapと主要受入ゲート",
        "",
        "各図はPNGとSVGを併記し、比較表の元データはCSVに保存した。各run固有の既存5図×2ケースは `05_per_run_figure_catalog.csv` から参照できる。",
        "",
        "## CSVデータ",
        "",
        "- `00_release_and_provenance.csv`: scenario、fresh Prepare、job、source run、凍結SHA、比較hash、claim scope",
        "- `01_scenario_controls.csv`: 日付、ダイヤ、fleet、charger、tariff、PV定格/面積逆算、BESS、solver controls",
        "- `02_outcome_kpis.csv`: 配車、便、距離、エネルギー、費用、燃料、CO2、certified gap",
        "- `03_validation_gate_matrix.csv`: case/pairの全受入チェック",
        "- `04_hourly_energy_comparison.csv`: 2ケース×24時間の実行エネルギーとSOC",
        "- `05_per_run_figure_catalog.csv`: 各runの詳細5図、SVG、source CSV、正本データ",
        "",
        "## 判定上の注意",
        "",
        f"- High-PV standalone status: `{cases['sunny']['claim'].get('teacher_release_status')}`; blockers: `{cases['sunny']['claim'].get('teacher_release_failed_checks')}`",
        f"- Low-PV standalone status: `{cases['rain']['claim'].get('teacher_release_status')}`; blockers: `{cases['rain']['claim'].get('teacher_release_failed_checks')}`",
        f"- Pair formal readiness: `{str(pair_ready).lower()}`（pair-level claimの正本は `pair/pair_manifest.json`）",
        "- 図表生成はsource runを書き換えず、case単独のrelease判定も変更しない。",
        "",
        "## 証拠索引",
        "",
        "`evidence_index.json` に入力正本と生成物の相対パス、size、SHA-256を記録する。",
        "",
    ]
    report_path = output_dir / "progress_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# Progress report evidence bundle\n\n"
        "Start with `progress_report.md` and `00_progress_summary.png`. "
        "CSV files preserve the source values and `evidence_index.json` "
        "preserves SHA-256 lineage. Per-run detailed figures remain under "
        "`sunny|rain/graph/literature_figures/`.\n",
        encoding="utf-8",
    )

    generated_before_index = sorted(
        [*table_paths, *figure_paths, report_path, readme_path]
    )
    generated_records = [_record(pair_dir, path) for path in generated_before_index]
    evidence_index = {
        "schema_version": "frontend_pv_pair_progress_evidence_index_v1",
        "generated_at_utc": _utc_now(),
        "source_artifacts": source_records,
        "generated_artifacts": generated_records,
        "source_artifact_count": len(source_records),
        "generated_artifact_count_excluding_index_and_manifest": len(generated_records),
    }
    evidence_index_path = output_dir / "evidence_index.json"
    _write_json(evidence_index_path, evidence_index)

    required_outputs = [
        *table_paths,
        *figure_paths,
        report_path,
        readme_path,
        evidence_index_path,
    ]
    missing_outputs = [
        path.relative_to(pair_dir).as_posix()
        for path in required_outputs
        if not path.is_file() or path.stat().st_size <= 0
    ]
    all_gate_rows_pass = all(row["passed"] is True for row in gate_rows)
    manifest = {
        "schema_version": "frontend_pv_pair_progress_report_v1",
        "generated_at_utc": _utc_now(),
        "status": "READY" if not missing_outputs else "BLOCKED",
        "status_semantics": "progress_evidence_bundle_completeness_only",
        "bundle_complete": not missing_outputs,
        "missing_outputs": missing_outputs,
        "pair_formal_research_submission_ready": pair_ready,
        "pair_accepted_for_controlled_pv_sensitivity_comparison": pair_manifest.get("accepted_for_controlled_pv_sensitivity_comparison") is True,
        "all_exported_gate_rows_pass": all_gate_rows_pass,
        "standalone_case_statuses": {
            case: {
                "teacher_release_status": cases[case]["claim"].get("teacher_release_status"),
                "failed_checks": cases[case]["claim"].get("teacher_release_failed_checks") or [],
            }
            for case in ("sunny", "rain")
        },
        "comparison_scope": "same_service_date_high_pv_low_pv_supply_sensitivity",
        "assignment_difference": {
            "assignment_hashes_equal": assignment.get(
                "assignment_hashes_equal"
            ),
            "changed_trip_count": assignment.get("changed_trip_count"),
        },
        "figure_count": 7,
        "figure_format_count": 14,
        "table_count": len(table_paths),
        "per_run_detailed_figure_count": len(per_run_figure_rows),
        "source_artifact_count": len(source_records),
        "generated_artifacts": [
            _record(pair_dir, path) for path in required_outputs
        ],
        "canonical_claim_sources": {
            "pair": "pair/pair_manifest.json",
            "case": "sunny|rain/research_claim_scope.json",
            "cost_and_energy": "sunny|rain/rolling_hourly_chain/executed_day_accounting.json",
            "assignments": "sunny|rain/vehicle_timelines.csv",
            "acceptance": (
                f"{case_gate_source}; pair/pair_control_audit.json"
            ),
        },
    }
    manifest_path = output_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pair_dir", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = build_progress_report(args.pair_dir)
    print(
        f"progress_report_status={manifest['status']} "
        f"figures={manifest['figure_count']} "
        f"tables={manifest['table_count']}"
    )
    return 0 if manifest["bundle_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
