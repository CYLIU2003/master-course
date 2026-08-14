"""Build an honest progress-report bundle from two day-ahead PV cases.

This postprocessor is intentionally separate from the formal controlled-pair
release builder.  It accepts physically validated day-ahead incumbents whose
requested MIP gap or rolling-horizon gates may still be incomplete, and it
preserves those limitations in every generated summary.  Source run
directories are read-only.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


CASE_LABELS = {
    "sunny": "High PV",
    "rain": "Low PV",
}
CASE_COLORS = {
    "sunny": "#E69F00",
    "rain": "#4C78A8",
}
BEV_COLOR = "#2A9D8F"
ICE_COLOR = "#6C757D"
GRID_COLOR = "#7B2CBF"
PV_COLOR = "#E69F00"
BESS_COLOR = "#00A6A6"
INK_COLOR = "#22272E"
GRIDLINE_COLOR = "#D8DEE4"
TOLERANCE = 1e-6
PRIMARY_COST_COMPONENTS = (
    "electricity_cost_jpy",
    "fuel_cost_jpy",
    "vehicle_usage_cost_jpy",
    "co2_cost_jpy",
)


@dataclass(frozen=True)
class CaseEvidence:
    key: str
    run_dir: Path
    payload: dict[str, Any]
    hourly_rows: tuple[dict[str, Any], ...]
    source_files: tuple[Path, ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return dict(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _number(value: Any, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric; observed={value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite; observed={value!r}")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assignment_mix(path: Path) -> dict[str, int]:
    trips: dict[str, tuple[str, str]] = {}
    for row in _read_csv(path):
        service = str(
            row.get("is_service", row.get("served_flag", "true"))
        ).strip().lower()
        if service not in {"true", "1", "yes"}:
            continue
        trip_id = str(row.get("trip_id") or "").strip()
        vehicle_id = str(
            row.get("vehicle_id") or row.get("assigned_vehicle_id") or ""
        ).strip()
        powertrain = str(
            row.get("vehicle_type") or row.get("assigned_vehicle_type") or ""
        ).strip().upper()
        if not trip_id or not vehicle_id or not powertrain:
            continue
        candidate = (vehicle_id, powertrain)
        previous = trips.get(trip_id)
        if previous is not None and previous != candidate:
            raise ValueError(f"Conflicting assignment for trip {trip_id}")
        trips[trip_id] = candidate
    electric = {"BEV", "PHEV", "FCEV"}
    return {
        "bev_trips": sum(powertrain in electric for _, powertrain in trips.values()),
        "ice_trips": sum(powertrain not in electric for _, powertrain in trips.values()),
        "used_bev": len(
            {vehicle for vehicle, powertrain in trips.values() if powertrain in electric}
        ),
        "used_ice": len(
            {
                vehicle
                for vehicle, powertrain in trips.values()
                if powertrain not in electric
            }
        ),
    }


def _single_asset(conditions: Mapping[str, Any]) -> dict[str, Any]:
    assets = conditions.get("depot_energy_assets")
    if isinstance(assets, Mapping):
        assets = [assets]
    candidates = [dict(value) for value in list(assets or ()) if isinstance(value, Mapping)]
    if len(candidates) != 1:
        raise ValueError(
            "Diagnostic pair reporting requires exactly one selected depot asset; "
            f"observed={len(candidates)}"
        )
    return candidates[0]


def _tariff(path: Path) -> dict[str, Any]:
    rows = _read_csv(path)
    if not rows:
        raise ValueError(f"Tariff artifact is empty: {path}")
    energy_prices = {
        round(_number(row.get("grid_energy_price_yen_per_kwh"), field="grid tariff"), 9)
        for row in rows
    }
    demand_weights = {
        round(_number(row.get("demand_charge_weight"), field="demand charge"), 9)
        for row in rows
    }
    return {
        "slot_count": len(rows),
        "energy_prices_yen_per_kwh": sorted(energy_prices),
        "demand_charge_weights": sorted(demand_weights),
    }


def _effective_controls(
    conditions: Mapping[str, Any],
    optimization_parameters: Mapping[str, Any],
    tariff: Mapping[str, Any],
    solver: Mapping[str, Any],
) -> dict[str, Any]:
    asset = _single_asset(conditions)
    problem = optimization_parameters.get("problem")
    if not isinstance(problem, Mapping):
        problem = optimization_parameters
    return {
        "service_date": conditions.get("service_date"),
        "day_type": conditions.get("day_type"),
        "depot_id": asset.get("depot_id"),
        "pv_capacity_kw": asset.get("pv_capacity_kw"),
        "bess_energy_kwh": asset.get("bess_energy_kwh"),
        "bess_power_kw": asset.get("bess_power_kw"),
        "bess_initial_soc_kwh": asset.get("bess_initial_soc_kwh"),
        "bess_terminal_soc_target_kwh": asset.get("bess_terminal_soc_target_kwh"),
        "allow_grid_to_bess": asset.get("allow_grid_to_bess"),
        "vehicle_usage_cost_jpy_per_used_bus": conditions.get(
            "vehicle_usage_cost_jpy_per_used_bus"
        ),
        "vehicle_usage_cost_semantics": conditions.get(
            "vehicle_usage_cost_semantics"
        ),
        "tariff": dict(tariff),
        "charger_count": conditions.get("charger_count"),
        "charger_power_kw": conditions.get("charger_power_kw"),
        "time_step_min": conditions.get("time_step_min"),
        "time_limit_seconds": conditions.get("time_limit_seconds"),
        "mip_gap_requested_ratio": conditions.get("mip_gap"),
        "random_seed": conditions.get("random_seed"),
        "gurobi_threads": solver.get("gurobi_threads"),
        "milp_max_successors_per_trip": conditions.get(
            "milp_max_successors_per_trip"
        ),
        "active_vehicle_count": problem.get("vehicle_count")
        or optimization_parameters.get("vehicle_count"),
    }


def _control_mismatches(
    sunny: Mapping[str, Any], rain: Mapping[str, Any]
) -> list[dict[str, Any]]:
    keys = sorted(set(sunny) | set(rain))
    return [
        {"field": key, "sunny": sunny.get(key), "rain": rain.get(key)}
        for key in keys
        if sunny.get(key) != rain.get(key)
    ]


def _load_case(key: str, run_dir: Path) -> CaseEvidence:
    required = (
        "kpi_summary.json",
        "summary.json",
        "solver_settings.json",
        "simulation_conditions.json",
        "optimization_parameters.json",
        "research_claim_scope.json",
        "artifact_completeness.json",
        "case_execution_metadata.json",
        "code_provenance.json",
        "simulation_conditions_tou_prices.csv",
        "graph/trip_assignment.csv",
        "graph/data_flow_validation.csv",
        "graph/energy_flow_timeseries.csv",
    )
    paths = tuple(run_dir / relative for relative in required)
    for path in paths:
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Missing required {key} artifact: {path}")

    kpi = _read_json(run_dir / "kpi_summary.json")
    summary = _read_json(run_dir / "summary.json")
    solver = _read_json(run_dir / "solver_settings.json")
    conditions = _read_json(run_dir / "simulation_conditions.json")
    parameters = _read_json(run_dir / "optimization_parameters.json")
    claim_scope = _read_json(run_dir / "research_claim_scope.json")
    completeness = _read_json(run_dir / "artifact_completeness.json")
    execution = _read_json(run_dir / "case_execution_metadata.json")
    provenance = _read_json(run_dir / "code_provenance.json")
    mix = _assignment_mix(run_dir / "graph" / "trip_assignment.csv")
    tariff = _tariff(run_dir / "simulation_conditions_tou_prices.csv")
    hourly_source = _read_csv(run_dir / "graph" / "energy_flow_timeseries.csv")
    data_flow_rows = _read_csv(run_dir / "graph" / "data_flow_validation.csv")

    if completeness.get("status") != "OK" or completeness.get("accepted") is not True:
        raise ValueError(f"{key} artifact completeness gate is not accepted")
    normalized_data_flow_statuses = [
        str(row.get("status") or "").strip().upper() for row in data_flow_rows
    ]
    failed_data_flow_checks = [
        row.get("check_name") or "unnamed"
        for row, status in zip(
            data_flow_rows, normalized_data_flow_statuses, strict=True
        )
        if status not in {"OK", "SKIPPED"}
        or (
            status == "SKIPPED"
            and (
                str(row.get("severity") or "").strip().upper() != "INFO"
                or not str(row.get("message") or "").strip()
            )
        )
    ]
    skipped_data_flow_checks = sum(
        status == "SKIPPED" for status in normalized_data_flow_statuses
    )
    if not data_flow_rows or failed_data_flow_checks:
        raise ValueError(
            f"{key} data-flow validation is not fully OK: "
            f"{failed_data_flow_checks or ['no_checks']}"
        )

    served = int(summary.get("trip_count_served") or 0)
    unserved = int(summary.get("trip_count_unserved") or 0)
    if served != mix["bev_trips"] + mix["ice_trips"] or unserved != 0:
        raise ValueError(
            f"{key} trip assignment does not reconcile: served={served}, "
            f"mix={mix}, unserved={unserved}"
        )
    if int(kpi.get("bev_trip_count") or 0) != mix["bev_trips"]:
        raise ValueError(f"{key} BEV trip count does not reconcile")
    if int(kpi.get("ice_trip_count") or 0) != mix["ice_trips"]:
        raise ValueError(f"{key} ICE trip count does not reconcile")

    canonical_source = summary.get("canonical_cost_components_jpy")
    if not isinstance(canonical_source, Mapping) or not canonical_source:
        raise ValueError(f"{key} canonical cost components are unavailable")
    canonical_components = {
        str(component): _number(value, field=f"{key} canonical {component}")
        for component, value in canonical_source.items()
    }
    missing_primary = [
        component
        for component in PRIMARY_COST_COMPONENTS
        if component not in canonical_components
    ]
    if missing_primary:
        raise ValueError(
            f"{key} canonical cost components are incomplete: {missing_primary}"
        )
    components = {
        component: canonical_components[component]
        for component in PRIMARY_COST_COMPONENTS
    }
    for component, canonical_value in components.items():
        kpi_value = _number(kpi.get(component), field=f"{key} KPI {component}")
        if abs(kpi_value - canonical_value) > TOLERANCE:
            raise ValueError(
                f"{key} KPI and canonical {component} do not reconcile: "
                f"kpi={kpi_value}, canonical={canonical_value}"
            )
    total_cost = _number(
        kpi.get("accounting_total_cost_jpy"), field=f"{key} accounting total"
    )
    summary_total = _number(
        summary.get("accounting_total_cost_jpy"), field=f"{key} summary accounting total"
    )
    if abs(total_cost - summary_total) > TOLERANCE:
        raise ValueError(
            f"{key} KPI and summary accounting totals do not reconcile: "
            f"kpi={total_cost}, summary={summary_total}"
        )
    component_total = sum(canonical_components.values())
    if abs(total_cost - component_total) > TOLERANCE:
        raise ValueError(
            f"{key} accounting components do not reconcile: "
            f"total={total_cost}, components={component_total}"
        )
    other_cost = sum(
        value
        for component, value in canonical_components.items()
        if component not in PRIMARY_COST_COMPONENTS
    )

    physical = summary.get("solution_validity")
    if not isinstance(physical, Mapping):
        physical = {}
    validation_metrics = physical.get("validation_metrics")
    if not isinstance(validation_metrics, Mapping):
        validation_metrics = {}
    physical_valid = (
        physical.get("physical_validation_status") == "VALID"
        and validation_metrics.get("all_required_validation_checks_passed") is True
    )
    if not physical_valid:
        raise ValueError(f"{key} day-ahead physical validation is not VALID")

    certified_gap = _number(
        solver.get("certified_mip_gap_percent"), field=f"{key} certified gap"
    )
    requested_gap = _number(
        kpi.get("mip_gap_requested_percent"), field=f"{key} requested gap"
    )
    hourly_rows: list[dict[str, Any]] = []
    for row in hourly_source:
        hourly_rows.append(
            {
                "case": key,
                "time": row.get("time"),
                "pv_generation_kwh": _number(
                    row.get("pv_generation_slot_kwh"), field=f"{key} hourly PV"
                ),
                "pv_to_bus_kwh": _number(
                    row.get("pv_to_bus_slot_kwh"), field=f"{key} hourly PV to bus"
                ),
                "pv_to_bess_kwh": _number(
                    row.get("pv_to_bess_slot_kwh"), field=f"{key} hourly PV to BESS"
                ),
                "bess_to_bus_kwh": _number(
                    row.get("bess_to_bus_slot_kwh"), field=f"{key} hourly BESS to bus"
                ),
                "grid_to_bus_kwh": _number(
                    row.get("grid_to_bus_slot_kwh"), field=f"{key} hourly grid to bus"
                ),
                "pv_curtailed_kwh": _number(
                    row.get("pv_curtailed_slot_kwh"), field=f"{key} hourly curtailment"
                ),
                "bess_soc_kwh": _number(
                    row.get("bess_soc_kwh"), field=f"{key} hourly BESS SOC"
                ),
            }
        )

    payload = {
        "case": key,
        "label": CASE_LABELS[key],
        "source_run_dir": str(run_dir.resolve()),
        "scenario_id": execution.get("scenario_id"),
        "prepared_input_id": execution.get("prepared_input_id"),
        "job_id": execution.get("job_id"),
        "service_date": conditions.get("service_date"),
        "pv_source_date": _single_asset(conditions).get("pv_source_date"),
        "git_sha": provenance.get("git_sha"),
        "git_clean": provenance.get("git_dirty") is False,
        "git_state_unchanged": solver.get("git_state_unchanged_during_solve") is True,
        "solver_status": summary.get("solver_status"),
        "certified_gap_percent": certified_gap,
        "requested_gap_percent": requested_gap,
        "gap_target_met": certified_gap <= requested_gap + 1e-12,
        "http_wall_time_sec": _number(
            execution.get("total_wall_time_sec"), field=f"{key} HTTP wall time"
        ),
        "final_solver_time_sec": _number(
            summary.get("solve_time_seconds"), field=f"{key} solver time"
        ),
        "served_trips": served,
        "unserved_trips": unserved,
        **mix,
        "used_vehicle_count": mix["used_bev"] + mix["used_ice"],
        "pv_generation_kwh": _number(
            kpi.get("pv_generation_kwh"), field=f"{key} PV generation"
        ),
        "pv_to_bus_kwh": _number(kpi.get("pv_to_bus_kwh"), field=f"{key} PV to bus"),
        "pv_to_bess_kwh": _number(
            kpi.get("pv_to_bess_kwh"), field=f"{key} PV to BESS"
        ),
        "bess_to_bus_kwh": _number(
            kpi.get("bess_to_bus_kwh"), field=f"{key} BESS to bus"
        ),
        "grid_import_kwh": _number(
            kpi.get("grid_import_kwh"), field=f"{key} grid import"
        ),
        "pv_curtailed_kwh": _number(
            kpi.get("pv_curtailed_kwh"), field=f"{key} PV curtailment"
        ),
        "peak_grid_import_kw": _number(
            kpi.get("peak_grid_import_kw"), field=f"{key} peak grid import"
        ),
        "total_co2_kg": _number(kpi.get("total_co2_kg"), field=f"{key} total CO2"),
        "accounting_total_cost_jpy": total_cost,
        "canonical_cost_components_jpy": canonical_components,
        "other_cost_jpy": other_cost,
        **components,
        "physical_validation": "VALID",
        "artifact_completeness_status": completeness.get("status"),
        "data_flow_validation_status": (
            "OK_WITH_DOCUMENTED_SKIPS" if skipped_data_flow_checks else "OK"
        ),
        "data_flow_check_count": len(data_flow_rows),
        "data_flow_skipped_check_count": skipped_data_flow_checks,
        "source_research_submission_ready": claim_scope.get(
            "research_submission_ready"
        ),
        "source_teacher_release_status": claim_scope.get("teacher_release_status"),
        "rolling_status": (summary.get("rolling_execution") or {}).get("status"),
        "effective_controls": _effective_controls(
            conditions, parameters, tariff, solver
        ),
    }
    return CaseEvidence(key, run_dir, payload, tuple(hourly_rows), paths)


def _style_axis(axis: Any) -> None:
    axis.set_facecolor("white")
    axis.grid(axis="y", color=GRIDLINE_COLOR, linewidth=0.8, alpha=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(GRIDLINE_COLOR)
    axis.spines["bottom"].set_color(GRIDLINE_COLOR)
    axis.tick_params(colors=INK_COLOR, labelsize=9)


def _finish_figure(figure: Any, output_base: Path) -> None:
    figure.patch.set_facecolor("white")
    figure.savefig(output_base.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(output_base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(figure)


def _add_bar_labels(axis: Any, bars: Iterable[Any], *, digits: int = 0) -> None:
    for bar in bars:
        height = float(bar.get_height())
        axis.annotate(
            f"{height:,.{digits}f}",
            (bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=INK_COLOR,
        )


def _plot_dispatch(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    labels = [case.payload["label"] for case in cases]
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 4.7))
    for axis, suffix, title in (
        (axes[0], "trips", "Assigned service trips"),
        (axes[1], "", "Used vehicles"),
    ):
        bev_key = "bev_trips" if suffix else "used_bev"
        ice_key = "ice_trips" if suffix else "used_ice"
        x = list(range(len(cases)))
        bev = [case.payload[bev_key] for case in cases]
        ice = [case.payload[ice_key] for case in cases]
        first = axis.bar(x, bev, color=BEV_COLOR, edgecolor="#1B6F66", label="BEV")
        second = axis.bar(
            x,
            ice,
            bottom=bev,
            color=ICE_COLOR,
            edgecolor="#4B5258",
            label="ICE",
        )
        axis.set_xticks(x, labels)
        axis.set_title(title, loc="left", fontsize=13, color=INK_COLOR)
        axis.set_ylabel("Count")
        axis.set_ylim(bottom=0)
        _style_axis(axis)
        for bars, bottoms in ((first, [0] * len(bev)), (second, bev)):
            for bar, bottom in zip(bars, bottoms, strict=True):
                value = float(bar.get_height())
                if value <= 0:
                    continue
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    bottom + value / 2,
                    f"{value:.0f}",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=10,
                    fontweight="bold",
                )
    handles, legend_labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        legend_labels,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.90),
        ncol=2,
    )
    figure.suptitle(
        "Day-ahead dispatch comparison",
        x=0.06,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=INK_COLOR,
    )
    figure.text(
        0.06,
        0.01,
        "264 service trips; diagnostic incumbents from the frontend/BFF execution path.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.84))
    _finish_figure(figure, output_dir / "dispatch_comparison")


def _plot_cost(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    components: tuple[tuple[str, str, str], ...] = (
        ("vehicle_usage_cost_jpy", "Vehicle-day", "#8C959F"),
        ("fuel_cost_jpy", "Fuel", "#D55E00"),
        ("electricity_cost_jpy", "Grid electricity", GRID_COLOR),
        ("co2_cost_jpy", "CO2 accounting", "#0072B2"),
    )
    if any(abs(case.payload["other_cost_jpy"]) > TOLERANCE for case in cases):
        components += (("other_cost_jpy", "Other canonical", "#CC79A7"),)
    figure, axis = plt.subplots(figsize=(8.6, 5.2))
    x = list(range(len(cases)))
    bottoms = [0.0] * len(cases)
    for key, label, color in components:
        values = [max(0.0, float(case.payload[key])) for case in cases]
        axis.bar(x, values, bottom=bottoms, label=label, color=color, edgecolor="white")
        bottoms = [left + value for left, value in zip(bottoms, values, strict=True)]
    axis.set_xticks(x, [case.payload["label"] for case in cases])
    axis.set_ylabel("JPY/day")
    axis.set_title("Canonical day-ahead operating cost", loc="left", fontsize=14)
    axis.set_ylim(bottom=0)
    _style_axis(axis)
    for index, total in enumerate(bottoms):
        axis.text(index, total + max(bottoms) * 0.015, f"¥{total:,.0f}", ha="center", fontsize=10)
    axis.legend(
        frameon=False,
        ncol=1,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
    )
    figure.text(
        0.10,
        0.01,
        "Accounting components reconcile within 1e-6 JPY; Rolling execution was not run.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 0.83, 1))
    _finish_figure(figure, output_dir / "cost_comparison")


def _plot_energy(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    metrics = (
        ("pv_generation_kwh", "PV generation", PV_COLOR),
        ("pv_to_bus_kwh", "PV to bus", "#F2C14E"),
        ("pv_to_bess_kwh", "PV to BESS", BESS_COLOR),
        ("bess_to_bus_kwh", "BESS to bus", "#007C83"),
        ("grid_import_kwh", "Grid import", GRID_COLOR),
        ("pv_curtailed_kwh", "PV curtailed", "#B8A169"),
    )
    figure, axis = plt.subplots(figsize=(10.5, 5.5))
    width = 0.12
    x = list(range(len(cases)))
    offsets = [index - (len(metrics) - 1) / 2 for index in range(len(metrics))]
    for offset, (key, label, color) in zip(offsets, metrics, strict=True):
        values = [case.payload[key] for case in cases]
        axis.bar(
            [position + offset * width for position in x],
            values,
            width=width,
            label=label,
            color=color,
        )
    axis.set_xticks(x, [case.payload["label"] for case in cases])
    axis.set_ylabel("kWh/day")
    axis.set_title("Day-ahead depot energy allocation", loc="left", fontsize=14)
    axis.set_ylim(bottom=0)
    _style_axis(axis)
    axis.legend(frameon=False, ncol=3, loc="upper right", fontsize=8.5)
    figure.text(
        0.09,
        0.01,
        "PV capacity is 1,000 kW and BESS capacity is 6,000 kWh in both cases.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    _finish_figure(figure, output_dir / "energy_comparison")


def _plot_co2(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    figure, axis = plt.subplots(figsize=(7.2, 4.8))
    bars = axis.bar(
        [case.payload["label"] for case in cases],
        [case.payload["total_co2_kg"] for case in cases],
        color=[CASE_COLORS[case.key] for case in cases],
        edgecolor="#4B5258",
    )
    axis.set_ylabel("kg-CO2/day")
    axis.set_title("Operational CO2 emissions", loc="left", fontsize=14)
    axis.set_ylim(bottom=0)
    _style_axis(axis)
    _add_bar_labels(axis, bars, digits=1)
    figure.text(
        0.12,
        0.01,
        "CO2 is an evaluated outcome; this run used total-cost minimization.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    _finish_figure(figure, output_dir / "co2_comparison")


def _plot_solver_quality(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11.0, 4.7))
    labels = [case.payload["label"] for case in cases]
    runtimes = [case.payload["http_wall_time_sec"] for case in cases]
    runtime_bars = axes[0].bar(labels, runtimes, color=[CASE_COLORS[c.key] for c in cases])
    axes[0].set_title("Frontend/BFF wall time", loc="left", fontsize=13)
    axes[0].set_ylabel("Seconds")
    axes[0].set_ylim(bottom=0)
    _style_axis(axes[0])
    _add_bar_labels(axes[0], runtime_bars, digits=1)

    gaps = [case.payload["certified_gap_percent"] for case in cases]
    gap_bars = axes[1].bar(labels, gaps, color=[CASE_COLORS[c.key] for c in cases])
    requested = max(case.payload["requested_gap_percent"] for case in cases)
    axes[1].axhline(
        requested,
        color="#C62828",
        linestyle="--",
        linewidth=1.4,
        label=f"Requested {requested:.1f}%",
    )
    axes[1].set_title("Certified optimality gap", loc="left", fontsize=13)
    axes[1].set_ylabel("Percent")
    axes[1].set_ylim(bottom=0)
    _style_axis(axes[1])
    _add_bar_labels(axes[1], gap_bars, digits=3)
    axes[1].legend(frameon=False, loc="upper right")
    figure.suptitle(
        "Day-ahead solve quality",
        x=0.06,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=INK_COLOR,
    )
    figure.text(
        0.06,
        0.01,
        "Both incumbents are physically valid but miss the predeclared 1% certificate.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.92))
    _finish_figure(figure, output_dir / "solver_quality")


def _plot_hourly(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(11.5, 8.0), sharex=True)
    for axis, case in zip(axes, cases, strict=True):
        hours = list(range(len(case.hourly_rows)))
        axis.plot(
            hours,
            [row["pv_generation_kwh"] for row in case.hourly_rows],
            color=PV_COLOR,
            linewidth=2.2,
            label="PV generation",
        )
        axis.plot(
            hours,
            [row["pv_to_bus_kwh"] for row in case.hourly_rows],
            color="#C68A00",
            linewidth=1.8,
            linestyle="--",
            label="PV to bus",
        )
        axis.plot(
            hours,
            [row["bess_to_bus_kwh"] for row in case.hourly_rows],
            color=BESS_COLOR,
            linewidth=1.8,
            label="BESS to bus",
        )
        axis.plot(
            hours,
            [row["grid_to_bus_kwh"] for row in case.hourly_rows],
            color=GRID_COLOR,
            linewidth=1.8,
            linestyle=":",
            label="Grid to bus",
        )
        axis.set_title(case.payload["label"], loc="left", fontsize=12)
        axis.set_ylabel("kWh/slot")
        axis.set_ylim(bottom=0)
        _style_axis(axis)
    axes[0].legend(frameon=False, ncol=4, loc="upper right", fontsize=8.5)
    axes[-1].set_xlabel("Hour of service day")
    axes[-1].set_xticks(range(0, 24, 2))
    figure.suptitle(
        "Hourly day-ahead energy flows",
        x=0.07,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=INK_COLOR,
    )
    figure.text(
        0.07,
        0.01,
        "Source: graph/energy_flow_timeseries.csv; values are day-ahead, not Rolling execution.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    _finish_figure(figure, output_dir / "hourly_energy_flows")


def _plot_bess_soc(cases: Sequence[CaseEvidence], output_dir: Path) -> None:
    figure, axis = plt.subplots(figsize=(10.5, 5.0))
    for case in cases:
        axis.plot(
            range(len(case.hourly_rows)),
            [row["bess_soc_kwh"] for row in case.hourly_rows],
            color=CASE_COLORS[case.key],
            linewidth=2.2,
            label=case.payload["label"],
        )
    axis.set_title("Stationary BESS state of charge", loc="left", fontsize=14)
    axis.set_xlabel("Hour of service day")
    axis.set_ylabel("kWh")
    axis.set_xticks(range(0, 24, 2))
    axis.set_ylim(bottom=0)
    _style_axis(axis)
    axis.legend(frameon=False, loc="upper right")
    figure.text(
        0.09,
        0.01,
        "Both cases enforce 3,000 kWh initial and terminal SOC.",
        fontsize=9,
        color="#57606A",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    _finish_figure(figure, output_dir / "bess_soc")


def _comparison_rows(cases: Sequence[CaseEvidence]) -> list[dict[str, Any]]:
    fields = (
        "label",
        "service_date",
        "pv_source_date",
        "served_trips",
        "unserved_trips",
        "bev_trips",
        "ice_trips",
        "used_bev",
        "used_ice",
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "bess_to_bus_kwh",
        "grid_import_kwh",
        "pv_curtailed_kwh",
        "peak_grid_import_kw",
        "electricity_cost_jpy",
        "fuel_cost_jpy",
        "vehicle_usage_cost_jpy",
        "co2_cost_jpy",
        "other_cost_jpy",
        "accounting_total_cost_jpy",
        "total_co2_kg",
        "http_wall_time_sec",
        "final_solver_time_sec",
        "solver_status",
        "certified_gap_percent",
        "requested_gap_percent",
        "gap_target_met",
        "physical_validation",
        "rolling_status",
    )
    return [
        {"case": case.key, **{field: case.payload[field] for field in fields}}
        for case in cases
    ]


def _write_report(
    output_dir: Path,
    cases: Sequence[CaseEvidence],
    control_mismatches: Sequence[Mapping[str, Any]],
) -> None:
    sunny, rain = (case.payload for case in cases)
    lines = [
        "# PV条件別 Phase 4 日前計画・診断比較",
        "",
        "> **判定: DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS**  ",
        "> 両ケースとも264便を物理的に充足したが、認証gap 1%を未達で、",
        "> 24時間Rollingも実施していない。したがって正式pairまたは最適解とは扱わない。",
        "",
        "## 技術要約",
        "",
        f"- 高PVではBEV {sunny['used_bev']}台・ICE {sunny['used_ice']}台、"
        f"BEV {sunny['bev_trips']}便となった。",
        f"- 低PVではBEV {rain['used_bev']}台・ICE {rain['used_ice']}台、"
        f"BEV {rain['bev_trips']}便となった。",
        f"- 高PV化によりBEV担当便は {sunny['bev_trips'] - rain['bev_trips']:+d}便、"
        f"使用BEVは {sunny['used_bev'] - rain['used_bev']:+d}台変化した。",
        f"- 会計総費用は高PV {sunny['accounting_total_cost_jpy']:,.2f}円、"
        f"低PV {rain['accounting_total_cost_jpy']:,.2f}円で、"
        f"差は {rain['accounting_total_cost_jpy'] - sunny['accounting_total_cost_jpy']:,.2f}円。",
        f"- 認証gapは高PV {sunny['certified_gap_percent']:.3f}%、"
        f"低PV {rain['certified_gap_percent']:.3f}%で、いずれも目標1%をわずかに超えた。",
        "",
        "## 比較条件と正本",
        "",
        "- 配車・エネルギー・費用は各runの日前計画成果物を参照した。",
        "- 系統従量単価30円/kWh、需要料金0円、PV定格1,000 kW、",
        "  BESS 6,000 kWh / 900 kW、初期・終端SOC 3,000 kWh、",
        "  車両使用費20,000円/使用台・日を両ケースで固定した。",
        "- 運行日は両方2025-08-05、PV参照日は高PV 2025-08-05、低PV 2025-08-10。",
        f"- 非PV control mismatch件数: {len(control_mismatches)}。",
        "",
        "## 結果の解釈",
        "",
        "PV曲線だけを低PVへ変更した条件では、費用最小の実行可能incumbentが",
        "BEV担当を大きく減らしICEへ切り替えた。これは、配車段階へPV/BESSの",
        "時間別エネルギー価値を戻す修正後に、天候シグナルが配車へ反映された",
        "診断的証拠である。ただしgap未達のため、差の全量を大域最適な転換量とは断定しない。",
        "",
        "## 求解時間と先行文献との比較範囲",
        "",
        f"frontend/BFF経路のwall timeは高PV {sunny['http_wall_time_sec']:.1f}秒、"
        f"低PV {rain['http_wall_time_sec']:.1f}秒だった。数百秒という桁は一部文献と同じだが、",
        "固定配車の充電最適化、ヒューリスティック、異なる問題規模・計算機を",
        "統合MILPの厳密性証拠として直接比較してはならない。",
        "",
        "## 未完了ゲート",
        "",
        "- 両ケースとも認証gap 1%未達。",
        "- 24/24 Rolling、executed-day accounting、正式pair manifest未生成。",
        "- research_run=falseの診断実行であり、teacher releaseはBLOCKED。",
        "- 高PVの32 BEV候補は充電機会・SOC制約を含むIISで不可行だったが、",
        "  31 BEVが最適または構造的上限であることは未証明。",
        "",
        "## 次の実行",
        "",
        "1. 同一のclean commitで、認証gap 1%以内までday-aheadを完了する。",
        "2. 両ケースを24時間Rollingし、executed-day accountingを正本化する。",
        "3. control hash・PV hash・物理・会計・artifact gateを通した正式pairを生成する。",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(sunny_run: Path, rain_run: Path, output_dir: Path) -> dict[str, Any]:
    cases = (
        _load_case("sunny", sunny_run.resolve()),
        _load_case("rain", rain_run.resolve()),
    )
    if cases[0].payload["git_sha"] != cases[1].payload["git_sha"]:
        raise ValueError("Source cases were not solved from the same Git SHA")
    if not all(case.payload["git_clean"] for case in cases):
        raise ValueError("Source cases are not both clean-commit executions")
    if not all(case.payload["git_state_unchanged"] for case in cases):
        raise ValueError("Git state changed during at least one source solve")

    controls = [case.payload["effective_controls"] for case in cases]
    mismatches = _control_mismatches(controls[0], controls[1])
    if mismatches:
        fields = ", ".join(str(item["field"]) for item in mismatches)
        raise ValueError(f"Non-PV pair controls differ: {fields}")

    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    comparison_rows = _comparison_rows(cases)
    _write_csv(output_dir / "comparison_summary.csv", comparison_rows[0].keys(), comparison_rows)
    component_names = sorted(
        {
            component
            for case in cases
            for component in case.payload["canonical_cost_components_jpy"]
        }
    )
    cost_rows = []
    for case in cases:
        canonical_components = case.payload["canonical_cost_components_jpy"]
        cost_rows.append(
            {
                "case": case.key,
                **{
                    component: canonical_components.get(component, 0.0)
                    for component in component_names
                },
                "other_cost_jpy": case.payload["other_cost_jpy"],
                "accounting_total_cost_jpy": case.payload[
                    "accounting_total_cost_jpy"
                ],
                "reconciliation_error_jpy": case.payload[
                    "accounting_total_cost_jpy"
                ]
                - sum(canonical_components.values()),
            }
        )
    _write_csv(output_dir / "cost_breakdown.csv", cost_rows[0].keys(), cost_rows)
    energy_rows = [
        {
            "case": case.key,
            **{
                key: case.payload[key]
                for key in (
                    "pv_generation_kwh",
                    "pv_to_bus_kwh",
                    "pv_to_bess_kwh",
                    "bess_to_bus_kwh",
                    "grid_import_kwh",
                    "pv_curtailed_kwh",
                    "peak_grid_import_kw",
                )
            },
            "pv_balance_error_kwh": case.payload["pv_generation_kwh"]
            - case.payload["pv_to_bus_kwh"]
            - case.payload["pv_to_bess_kwh"]
            - case.payload["pv_curtailed_kwh"],
        }
        for case in cases
    ]
    _write_csv(output_dir / "energy_balance.csv", energy_rows[0].keys(), energy_rows)
    solver_rows = [
        {
            "case": case.key,
            "solver_status": case.payload["solver_status"],
            "http_wall_time_sec": case.payload["http_wall_time_sec"],
            "final_solver_time_sec": case.payload["final_solver_time_sec"],
            "certified_gap_percent": case.payload["certified_gap_percent"],
            "requested_gap_percent": case.payload["requested_gap_percent"],
            "gap_target_met": case.payload["gap_target_met"],
            "physical_validation": case.payload["physical_validation"],
            "rolling_status": case.payload["rolling_status"],
        }
        for case in cases
    ]
    _write_csv(output_dir / "solver_quality.csv", solver_rows[0].keys(), solver_rows)
    hourly_rows = [row for case in cases for row in case.hourly_rows]
    _write_csv(output_dir / "hourly_energy_flow.csv", hourly_rows[0].keys(), hourly_rows)

    snapshot = {
        "schema_version": "day_ahead_diagnostic_pair_snapshot_v1",
        "generated_at_utc": _utc_now(),
        "status": "DIAGNOSTIC",
        "diagnostic_only": True,
        "research_submission_ready": False,
        "teacher_release_status": "BLOCKED",
        "blocking_reasons": [
            "day_ahead_certified_gap_target_not_met",
            "hourly_rolling_chain_not_executed",
            "controlled_counterfactual_pair_not_formally_verified",
            "research_run_not_requested",
        ],
        "claim_scope": [
            "physical_schedule_feasibility_under_recorded_inputs",
            "descriptive_day_ahead_incumbent_comparison",
        ],
        "disallowed_claims": [
            "global_optimality",
            "formal_controlled_counterfactual_effect",
            "executed_day_cost_or_energy",
            "research_submission_ready",
        ],
        "control_mismatches": mismatches,
        "effective_non_pv_controls": controls[0],
        "cases": {case.key: case.payload for case in cases},
        "differences": {
            "sunny_minus_rain_used_bev": cases[0].payload["used_bev"]
            - cases[1].payload["used_bev"],
            "sunny_minus_rain_bev_trips": cases[0].payload["bev_trips"]
            - cases[1].payload["bev_trips"],
            "rain_minus_sunny_total_cost_jpy": cases[1].payload[
                "accounting_total_cost_jpy"
            ]
            - cases[0].payload["accounting_total_cost_jpy"],
            "rain_minus_sunny_co2_kg": cases[1].payload["total_co2_kg"]
            - cases[0].payload["total_co2_kg"],
        },
    }
    _write_json(output_dir / "reporting_snapshot.json", snapshot)
    _write_report(output_dir, cases, mismatches)

    _plot_dispatch(cases, figure_dir)
    _plot_cost(cases, figure_dir)
    _plot_energy(cases, figure_dir)
    _plot_co2(cases, figure_dir)
    _plot_solver_quality(cases, figure_dir)
    _plot_hourly(cases, figure_dir)
    _plot_bess_soc(cases, figure_dir)

    generated_root_names = {
        "comparison_summary.csv",
        "cost_breakdown.csv",
        "energy_balance.csv",
        "hourly_energy_flow.csv",
        "report.md",
        "reporting_snapshot.json",
        "solver_quality.csv",
    }
    generated = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
        and (
            path.parent == figure_dir
            or (path.parent == output_dir and path.name in generated_root_names)
        )
    )
    source_records = []
    for case in cases:
        for path in case.source_files:
            source_records.append(
                {
                    "case": case.key,
                    "path": str(path.resolve()),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    manifest = {
        "schema_version": "day_ahead_diagnostic_pair_artifact_manifest_v1",
        "generated_at_utc": _utc_now(),
        "status": "DIAGNOSTIC",
        "reporting_snapshot_sha256": _sha256(output_dir / "reporting_snapshot.json"),
        "source_artifacts": source_records,
        "generated_artifacts": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in generated
        ],
    }
    _write_json(output_dir / "artifact_manifest.json", manifest)
    return snapshot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunny-run", required=True, type=Path)
    parser.add_argument("--rain-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    snapshot = build_report(args.sunny_run, args.rain_run, args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "status": snapshot["status"],
                "research_submission_ready": snapshot[
                    "research_submission_ready"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
