"""Generate literature-aligned figures from accepted frontend run evidence.

The figures in this module are newly rendered from canonical run artifacts.
They reproduce analytical relationships used in the local literature (vehicle
operation, SOC, charging sources, charger occupancy, costs, and emissions);
they do not copy source-paper graphics or invent missing sensitivity results.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
import numpy as np


LITERATURE_FIGURE_SCHEMA_VERSION = "literature_figure_bundle_v1"

_INK = "#263238"
_BLUE = "#315C8C"
_LIGHT_BLUE = "#8CB9D9"
_GOLD = "#D8A62A"
_ORANGE = "#D97732"
_GREEN = "#5B9466"
_LIGHT_GREEN = "#A8CFB0"
_PURPLE = "#7566A8"
_GREY = "#9AA3AA"
_LIGHT_GREY = "#E7EAEC"
_GRID = "#D7DCE0"
_FIGURE_RENDER_LOCK = threading.RLock()

_EVENT_STYLES = {
    "service_trip": (_BLUE, None, "Service trip"),
    "startup_deadhead": (_GREY, "///", "Startup deadhead"),
    "connection_deadhead": (_GREY, "///", "Connection deadhead"),
    "terminal_return": (_GREY, "\\\\\\", "Terminal return"),
    "waiting": (_LIGHT_GREY, None, "Waiting"),
    "charging": (_GOLD, "xx", "Charging"),
    "refueling": (_PURPLE, "..", "Refueling"),
}

_COST_LABELS = {
    "electricity_cost_jpy": "Electricity",
    "fuel_cost_jpy": "Fuel",
    "demand_charge_cost_jpy": "Demand charge",
    "contract_overage_cost_jpy": "Contract overage",
    "vehicle_fixed_cost_jpy": "Vehicle fixed",
    "vehicle_usage_cost_jpy": "Vehicle usage",
    "driver_cost_jpy": "Driver",
    "unserved_penalty_jpy": "Unserved penalty",
    "switch_cost_jpy": "Switching",
    "battery_degradation_cost_jpy": "Battery degradation",
    "deviation_cost_jpy": "Deviation",
    "co2_cost_jpy": "CO2 cost",
}

_LITERATURE_REFERENCES = (
    {
        "reference_id": "No42",
        "relative_path": "先行文献/No42.pdf",
        "citation": (
            "J. He et al., Battery electricity bus charging schedule "
            "considering bus journey's energy consumption estimation, "
            "Transportation Research Part D 115 (2023) 103587."
        ),
        "pages": "9, 11",
        "figures_or_tables": "Fig. 7; charging-conflict formulation",
        "adapted_relationship": (
            "vehicle operation timeline, charging opportunities, and "
            "charger-conflict visibility"
        ),
    },
    {
        "reference_id": "No55",
        "relative_path": "先行文献/No55.pdf",
        "citation": (
            "Y. He et al., Joint optimization of electric bus charging "
            "infrastructure, vehicle scheduling, and charging management, "
            "Transportation Research Part D 117 (2023) 103653."
        ),
        "pages": "17, 19",
        "figures_or_tables": "Fig. 6; Table 5",
        "adapted_relationship": (
            "per-vehicle schedule and SOC profiles; separated operating-cost "
            "and demand-charge reporting"
        ),
    },
    {
        "reference_id": "No16",
        "relative_path": "先行文献/No16.pdf",
        "citation": (
            "L. Zhong et al., Joint optimization of electric bus charging "
            "and energy storage system scheduling, Frontiers of Engineering "
            "Management 11(4) (2024) 676-696."
        ),
        "pages": "11, 12, 14",
        "figures_or_tables": "Figs. 3-10",
        "adapted_relationship": (
            "bus charging heatmap, depot power/SOC profiles, cost components, "
            "and explicit separation of single-run evidence from uncertainty "
            "experiments"
        ),
    },
    {
        "reference_id": "No61",
        "relative_path": "先行文献/No61.pdf",
        "citation": (
            "Y. Xiao et al., Photovoltaic-energy storage systems empowered: "
            "Low-carbon and economic scheduling for electric buses, "
            "Transportation Research Part D 150 (2026) 105082."
        ),
        "pages": "12, 15, 16",
        "figures_or_tables": "Figs. 4, 7-9",
        "adapted_relationship": (
            "BEV SOC, charging-source composition, BESS SOC, and grid-load "
            "profiles on a common time axis"
        ),
    },
    {
        "reference_id": "IEEJ-rolling",
        "relative_path": (
            "先行文献/"
            "電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価.pdf"
        ),
        "citation": (
            "電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価, "
            "令和7年電気学会電力・エネルギー部門大会 (2025)."
        ),
        "pages": "2",
        "figures_or_tables": "Figs. 2-3",
        "adapted_relationship": (
            "rolling charging execution aligned with PV availability and "
            "grid carbon intensity"
        ),
    },
)


class LiteratureFigureError(RuntimeError):
    """Raised when a finalized run cannot produce evidence-safe figures."""


def _serialize_figure_generation(
    function: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    """Protect Matplotlib's process-global state across concurrent BFF jobs."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        with _FIGURE_RENDER_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise LiteratureFigureError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiteratureFigureError(f"Expected JSON object: {path}")
    return dict(payload)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise LiteratureFigureError(f"Required figure source is missing: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, csv.Error) as exc:
        raise LiteratureFigureError(f"Cannot read {path}: {exc}") from exc


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(
                            (
                                sorted(value, key=str)
                                if isinstance(value, set)
                                else value
                            ),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        if isinstance(value, (Mapping, list, tuple, set))
                        else value
                    )
                    for key, value in row.items()
                }
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path, *, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _save_figure(
    figure: plt.Figure,
    *,
    output_dir: Path,
    stem: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"
    figure.savefig(
        png_path,
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
    )
    figure.savefig(
        svg_path,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)
    return [png_path, svg_path]


def _configure_plotting() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": _INK,
            "axes.labelcolor": _INK,
            "axes.titlecolor": _INK,
            "xtick.color": _INK,
            "ytick.color": _INK,
            "text.color": _INK,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "legend.fontsize": 8,
            "axes.grid": True,
            "grid.color": _GRID,
            "grid.linewidth": 0.6,
            "grid.alpha": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _plot_label_map(
    fleet_contract: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    parameters = [
        dict(item)
        for item in list(fleet_contract.get("active_vehicle_parameters") or ())
        if isinstance(item, Mapping)
    ]
    powertrain_by_vehicle = {
        str(item.get("vehicle_id") or ""): str(
            item.get("powertrain") or "UNKNOWN"
        ).upper()
        for item in parameters
    }
    counters: dict[str, int] = {}
    labels: dict[str, str] = {}
    for vehicle_id in sorted(powertrain_by_vehicle):
        powertrain = powertrain_by_vehicle[vehicle_id]
        counters[powertrain] = counters.get(powertrain, 0) + 1
        labels[vehicle_id] = f"{powertrain}-{counters[powertrain]:02d}"
    return labels, powertrain_by_vehicle


def _event_figure(
    *,
    event_rows: Sequence[Mapping[str, Any]],
    labels: Mapping[str, str],
    powertrains: Mapping[str, str],
    output_dir: Path,
) -> tuple[list[Path], Path, dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in event_rows:
        event_type = str(row.get("event_type") or "")
        if event_type not in _EVENT_STYLES:
            continue
        vehicle_id = str(row.get("vehicle_id") or "")
        start_min = _int(row.get("start_min"))
        end_min = _int(row.get("end_min"))
        if not vehicle_id or end_min <= start_min:
            continue
        normalized.append(
            {
                **dict(row),
                "vehicle_id": vehicle_id,
                "plot_label": labels.get(vehicle_id, vehicle_id),
                "powertrain": powertrains.get(vehicle_id, "UNKNOWN"),
                "start_hour": start_min / 60.0,
                "end_hour": end_min / 60.0,
                "duration_hour": (end_min - start_min) / 60.0,
            }
        )
    vehicles = sorted(
        {str(row["vehicle_id"]) for row in normalized},
        key=lambda item: (powertrains.get(item, "UNKNOWN"), labels.get(item, item)),
    )
    height = max(5.5, min(15.0, 2.5 + 0.32 * max(len(vehicles), 1)))
    figure, axis = plt.subplots(figsize=(14.5, height))
    handles = [
        Patch(
            facecolor=color,
            edgecolor=_INK if hatch else "white",
            hatch=hatch,
            label=label,
        )
        for _event, (color, hatch, label) in _EVENT_STYLES.items()
    ]
    if not normalized:
        axis.text(
            0.5,
            0.5,
            "No vehicle events were recorded.",
            ha="center",
            va="center",
            transform=axis.transAxes,
        )
        axis.set_axis_off()
    else:
        y_by_vehicle = {vehicle_id: index for index, vehicle_id in enumerate(vehicles)}
        for row in normalized:
            color, hatch, _label = _EVENT_STYLES[str(row["event_type"])]
            axis.broken_barh(
                [(float(row["start_hour"]), float(row["duration_hour"]))],
                (y_by_vehicle[str(row["vehicle_id"])] - 0.38, 0.76),
                facecolors=color,
                edgecolors="white" if hatch is None else _INK,
                linewidth=0.35,
                hatch=hatch,
            )
        axis.set_yticks(range(len(vehicles)))
        axis.set_yticklabels([labels.get(item, item) for item in vehicles])
        axis.invert_yaxis()
        axis.set_xlim(
            min(0.0, min(float(row["start_hour"]) for row in normalized)),
            max(24.0, max(float(row["end_hour"]) for row in normalized)),
        )
        axis.set_xticks(np.arange(0, 25, 3))
        axis.set_xlabel("Time of day [hour]")
        axis.set_ylabel("Vehicle (full IDs in source CSV)")
    figure.suptitle(
        "Executed vehicle operation and charging timeline",
        fontsize=14,
        y=0.995,
    )
    figure.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.955),
        ncol=4,
        frameon=False,
    )
    figure.text(
        0.01,
        0.01,
        (
            "Source: independently reconstructed executed vehicle events. "
            "Inspired by No42 Fig. 7 and No16 Fig. 3; newly rendered."
        ),
        fontsize=8,
        color="#59636A",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.88))
    source_path = output_dir / "01_vehicle_operation_timeline_source.csv"
    fields = [
        "plot_label",
        "vehicle_id",
        "powertrain",
        "event_id",
        "event_type",
        "start_min",
        "end_min",
        "start_hour",
        "end_hour",
        "duration_hour",
        "start_location",
        "end_location",
        "distance_km",
        "energy_kwh",
        "fuel_l",
        "charger_id",
        "power_kw",
        "power_limit_kw",
        "trip_id",
        "source_artifact",
    ]
    _write_csv(source_path, normalized, fields)
    return (
        _save_figure(
            figure,
            output_dir=output_dir,
            stem="01_vehicle_operation_timeline",
        ),
        source_path,
        {
            "vehicle_count": len(vehicles),
            "event_count": len(normalized),
        },
    )


def _soc_figure(
    *,
    soc_rows: Sequence[Mapping[str, Any]],
    labels: Mapping[str, str],
    output_dir: Path,
) -> tuple[list[Path], Path, dict[str, Any]]:
    normalized = [
        {
            **dict(row),
            "plot_label": labels.get(
                str(row.get("vehicle_id") or ""),
                str(row.get("vehicle_id") or ""),
            ),
            "time_hour": _float(row.get("time_min")) / 60.0,
            "soc_after_percent": _float(row.get("soc_after_percent")),
            "reserve_soc_percent": _float(row.get("reserve_soc_percent")),
        }
        for row in soc_rows
        if str(row.get("vehicle_id") or "")
    ]
    by_vehicle: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        by_vehicle.setdefault(str(row["vehicle_id"]), []).append(row)
    used_vehicles = sorted(
        vehicle_id
        for vehicle_id, rows in by_vehicle.items()
        if any(str(row.get("event_type")) != "initial_state" for row in rows)
    )
    column_count = max(1, min(3, len(used_vehicles)))
    row_count = max(1, math.ceil(max(len(used_vehicles), 1) / column_count))
    figure, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(max(8.0, 5.0 * column_count), 2.65 * row_count + 1.2),
        squeeze=False,
        sharex=True,
        sharey=True,
    )
    flat_axes = list(axes.flat)
    if not used_vehicles:
        flat_axes[0].text(
            0.5,
            0.5,
            "No used BEV SOC events were recorded.",
            ha="center",
            va="center",
            transform=flat_axes[0].transAxes,
        )
    for index, vehicle_id in enumerate(used_vehicles):
        axis = flat_axes[index]
        rows = sorted(
            by_vehicle[vehicle_id],
            key=lambda item: (
                float(item["time_hour"]),
                str(item.get("event_id") or ""),
            ),
        )
        x_values = [float(item["time_hour"]) for item in rows]
        y_values = [float(item["soc_after_percent"]) for item in rows]
        reserve = float(rows[0]["reserve_soc_percent"])
        axis.step(x_values, y_values, where="post", color=_BLUE, linewidth=1.4)
        axis.axhline(
            reserve,
            color=_ORANGE,
            linewidth=1.0,
            linestyle="--",
            label="Reserve",
        )
        axis.scatter(
            [x_values[0], x_values[-1]],
            [y_values[0], y_values[-1]],
            color=[_GREEN, _PURPLE],
            s=22,
            zorder=3,
        )
        axis.set_title(labels.get(vehicle_id, vehicle_id), fontsize=9)
        axis.set_xlim(0, max(24.0, max(x_values, default=24.0)))
        axis.set_ylim(0, 105)
        axis.set_xticks(np.arange(0, 25, 6))
        axis.set_yticks([0, 20, 40, 60, 80, 100])
    for index in range(len(used_vehicles), len(flat_axes)):
        flat_axes[index].set_axis_off()
    for axis in axes[-1, :]:
        if axis.axison:
            axis.set_xlabel("Time [hour]")
    for axis in axes[:, 0]:
        if axis.axison:
            axis.set_ylabel("SOC [%]")
    figure.suptitle("Executed BEV state-of-charge profiles", fontsize=14, y=0.995)
    figure.text(
        0.01,
        0.01,
        (
            "Green marker = initial SOC; purple marker = terminal SOC; "
            "orange dashed line = vehicle reserve.\nSource: independent "
            "event-level SOC reconstruction. Inspired by No55 Fig. 6."
        ),
        fontsize=8,
        color="#59636A",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.965))
    source_path = output_dir / "02_bev_soc_profiles_source.csv"
    fields = [
        "plot_label",
        "vehicle_id",
        "event_id",
        "event_type",
        "time_min",
        "time_hour",
        "soc_before_kwh",
        "soc_after_kwh",
        "soc_before_percent",
        "soc_after_percent",
        "reserve_soc_kwh",
        "reserve_soc_percent",
        "battery_capacity_kwh",
        "charging_efficiency",
        "source_artifact",
    ]
    _write_csv(source_path, normalized, fields)
    return (
        _save_figure(
            figure,
            output_dir=output_dir,
            stem="02_bev_soc_profiles",
        ),
        source_path,
        {
            "used_bev_count": len(used_vehicles),
            "active_bev_count": len(by_vehicle),
            "unused_bev_count": max(len(by_vehicle) - len(used_vehicles), 0),
        },
    )


def _time_key(value: Any) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.split("T", 1)[1]
    return text[:5]


def _json_number_sum(value: Any) -> float:
    if isinstance(value, Mapping):
        return sum(_float(item) for item in value.values())
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        loaded = json.loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise LiteratureFigureError(
            f"Invalid BESS SOC mapping in hourly energy-flow chart: {value!r}"
        ) from exc
    if not isinstance(loaded, Mapping):
        raise LiteratureFigureError(
            "BESS SOC field must be a JSON object keyed by depot"
        )
    return sum(_float(item) for item in loaded.values())


def _energy_management_figure(
    *,
    hourly_rows: Sequence[Mapping[str, Any]],
    co2_rows: Sequence[Mapping[str, Any]],
    cost_rows: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> tuple[list[Path], Path, dict[str, Any]]:
    co2_by_time = {
        _time_key(row.get("timestamp") or row.get("time")): _float(
            row.get("grid_emission_factor_kg_per_kwh")
        )
        for row in co2_rows
    }
    price_by_time = {
        _time_key(row.get("time") or row.get("timestamp")): _float(
            row.get("grid_energy_price_yen_per_kwh")
        )
        for row in cost_rows
    }
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(hourly_rows):
        time = _time_key(row.get("current_time") or row.get("time"))
        normalized.append(
            {
                "step_index": _int(row.get("step_index"), index),
                "time": time,
                "pv_generated_kwh": _float(row.get("pv_generated_kwh")),
                "pv_to_bus_kwh": _float(row.get("pv_to_bus_kwh")),
                "pv_to_bess_kwh": _float(row.get("pv_to_bess_kwh")),
                "pv_curtailed_kwh": _float(row.get("pv_curtailed_kwh")),
                "bess_to_bus_kwh": _float(row.get("bess_to_bus_kwh")),
                "grid_to_bus_kwh": _float(row.get("grid_to_bus_kwh")),
                "grid_to_bess_kwh": _float(row.get("grid_to_bess_kwh")),
                "grid_import_kwh": (
                    _float(row.get("grid_to_bus_kwh"))
                    + _float(row.get("grid_to_bess_kwh"))
                ),
                "bess_soc_total_kwh": _json_number_sum(
                    row.get("bess_end_soc_kwh_by_depot")
                ),
                "grid_emission_factor_kg_per_kwh": co2_by_time.get(time, 0.0),
                "grid_energy_price_yen_per_kwh": price_by_time.get(time, 0.0),
                "execution_minutes": _int(row.get("execution_minutes"), 60),
            }
        )
    if not normalized:
        raise LiteratureFigureError(
            "rolling_hourly_chain/hourly_energy_flow_chart.csv has no rows"
        )
    x_values = np.arange(len(normalized))
    labels = [str(row["time"]) for row in normalized]
    pv_bus = np.array([float(row["pv_to_bus_kwh"]) for row in normalized])
    bess_bus = np.array([float(row["bess_to_bus_kwh"]) for row in normalized])
    grid_bus = np.array([float(row["grid_to_bus_kwh"]) for row in normalized])
    pv_generated = np.array(
        [float(row["pv_generated_kwh"]) for row in normalized]
    )
    pv_bess = np.array([float(row["pv_to_bess_kwh"]) for row in normalized])
    curtailed = np.array([float(row["pv_curtailed_kwh"]) for row in normalized])
    bess_soc = np.array(
        [float(row["bess_soc_total_kwh"]) for row in normalized]
    )
    grid_import = np.array(
        [float(row["grid_import_kwh"]) for row in normalized]
    )
    grid_ci = np.array(
        [float(row["grid_emission_factor_kg_per_kwh"]) for row in normalized]
    )
    grid_price = np.array(
        [float(row["grid_energy_price_yen_per_kwh"]) for row in normalized]
    )

    figure, axes = plt.subplots(4, 1, figsize=(14.5, 12.5), sharex=True)
    axis = axes[0]
    axis.bar(x_values, pv_bus, color=_BLUE, label="PV to bus")
    axis.bar(
        x_values,
        bess_bus,
        bottom=pv_bus,
        color=_GOLD,
        label="BESS to bus",
    )
    axis.bar(
        x_values,
        grid_bus,
        bottom=pv_bus + bess_bus,
        color=_GREEN,
        label="Grid to bus",
    )
    axis.set_ylabel("Bus charging [kWh]")
    axis.set_title("Executed bus-charging source composition")
    axis.legend(ncol=3, frameon=False, loc="upper left")

    axis = axes[1]
    axis.bar(x_values, pv_bus, color=_BLUE, label="PV to bus")
    axis.bar(
        x_values,
        pv_bess,
        bottom=pv_bus,
        color=_LIGHT_BLUE,
        label="PV to BESS",
    )
    axis.bar(
        x_values,
        curtailed,
        bottom=pv_bus + pv_bess,
        color=_GREY,
        label="PV curtailed",
    )
    axis.plot(
        x_values,
        pv_generated,
        color=_INK,
        marker="o",
        markersize=3,
        linewidth=1.2,
        label="PV generated",
    )
    axis.set_ylabel("PV energy [kWh]")
    axis.set_title("Executed PV allocation")
    axis.legend(ncol=4, frameon=False, loc="upper left")

    axis = axes[2]
    axis.bar(
        x_values,
        grid_import,
        color=_LIGHT_GREEN,
        edgecolor=_GREEN,
        label="Grid import",
    )
    axis.set_ylabel("Grid import [kWh]")
    twin = axis.twinx()
    twin.plot(
        x_values,
        bess_soc,
        color=_PURPLE,
        marker="o",
        markersize=3,
        linewidth=1.3,
        label="BESS SOC",
    )
    twin.set_ylabel("BESS SOC [kWh]")
    axis.set_title("Executed grid import and BESS SOC")
    handles_1, labels_1 = axis.get_legend_handles_labels()
    handles_2, labels_2 = twin.get_legend_handles_labels()
    axis.legend(
        handles_1 + handles_2,
        labels_1 + labels_2,
        ncol=2,
        frameon=False,
        loc="upper left",
    )

    axis = axes[3]
    axis.plot(
        x_values,
        grid_ci,
        color=_ORANGE,
        marker="o",
        markersize=3,
        linestyle="--",
        linewidth=1.2,
        label="Grid CO2 factor",
    )
    axis.set_ylabel("Grid CO2 factor [kg/kWh]")
    price_axis = axis.twinx()
    price_axis.step(
        x_values,
        grid_price,
        where="mid",
        color=_INK,
        linewidth=1.3,
        label="Grid energy price",
    )
    price_axis.set_ylabel("Grid energy price [JPY/kWh]")
    axis.set_title("Executed grid carbon and price signals")
    handles_1, labels_1 = axis.get_legend_handles_labels()
    handles_2, labels_2 = price_axis.get_legend_handles_labels()
    axis.legend(
        handles_1 + handles_2,
        labels_1 + labels_2,
        ncol=2,
        frameon=False,
        loc="upper left",
    )
    axes[-1].set_xticks(x_values)
    axes[-1].set_xticklabels(labels, rotation=45, ha="right")
    axes[-1].set_xlabel("Rolling execution interval")
    figure.suptitle("Executed-day energy management profile", fontsize=14)
    figure.text(
        0.01,
        0.008,
        (
            "Canonical source: accepted hourly rolling prefixes. Inspired by "
            "No61 Figs. 7-9 and the IEEJ rolling study Figs. 2-3; newly rendered."
        ),
        fontsize=8,
        color="#59636A",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.965))
    source_path = output_dir / "03_energy_management_profile_source.csv"
    fields = [
        "step_index",
        "time",
        "execution_minutes",
        "pv_generated_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "bess_to_bus_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "grid_import_kwh",
        "bess_soc_total_kwh",
        "grid_emission_factor_kg_per_kwh",
        "grid_energy_price_yen_per_kwh",
    ]
    _write_csv(source_path, normalized, fields)
    return (
        _save_figure(
            figure,
            output_dir=output_dir,
            stem="03_energy_management_profile",
        ),
        source_path,
        {
            "interval_count": len(normalized),
            "pv_generated_kwh": float(pv_generated.sum()),
            "grid_import_kwh": float(grid_import.sum()),
        },
    )


def _charger_figure(
    *,
    charger_rows: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> tuple[list[Path], Path, dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in charger_rows:
        start_min = _int(row.get("start_min"))
        end_min = _int(row.get("end_min"))
        duration_min = max(end_min - start_min, 0)
        energy_kwh = _float(row.get("energy_kwh"))
        power_kw = _float(
            row.get("power_kw"),
            energy_kwh * 60.0 / duration_min if duration_min > 0 else 0.0,
        )
        normalized.append(
            {
                **dict(row),
                "start_min": start_min,
                "end_min": end_min,
                "duration_min": duration_min,
                "power_kw": power_kw,
                "power_limit_kw": _float(row.get("power_limit_kw")),
                "utilization_ratio": (
                    power_kw / _float(row.get("power_limit_kw"))
                    if _float(row.get("power_limit_kw")) > 0.0
                    else 0.0
                ),
            }
        )
    positive_durations = [
        int(row["duration_min"])
        for row in normalized
        if int(row["duration_min"]) > 0
    ]
    resolution_min = min(positive_durations, default=60)
    resolution_min = max(min(resolution_min, 60), 1)
    charger_ids = sorted(
        {
            str(row.get("charger_id") or "")
            for row in normalized
            if str(row.get("charger_id") or "")
        }
    )
    slot_count = max(math.ceil(1440 / resolution_min), 1)
    matrix = np.zeros((max(len(charger_ids), 1), slot_count))
    charger_index = {charger_id: index for index, charger_id in enumerate(charger_ids)}
    for row in normalized:
        charger_id = str(row.get("charger_id") or "")
        if charger_id not in charger_index:
            continue
        first = max(int(row["start_min"]) // resolution_min, 0)
        last = min(
            math.ceil(int(row["end_min"]) / resolution_min),
            slot_count,
        )
        matrix[charger_index[charger_id], first:last] = np.maximum(
            matrix[charger_index[charger_id], first:last],
            float(row["power_kw"]),
        )
    figure, axis = plt.subplots(
        figsize=(14.5, max(4.2, 2.0 + 0.46 * max(len(charger_ids), 1)))
    )
    cmap = LinearSegmentedColormap.from_list(
        "charger_power",
        ["#FFFFFF", _LIGHT_BLUE, _BLUE],
    )
    image = axis.imshow(
        matrix,
        aspect="auto",
        interpolation="nearest",
        cmap=cmap,
        vmin=0.0,
        vmax=max(float(matrix.max()), 1.0),
        extent=(0, 24, max(len(charger_ids), 1) - 0.5, -0.5),
    )
    if charger_ids:
        axis.set_yticks(range(len(charger_ids)))
        axis.set_yticklabels(charger_ids)
    else:
        axis.set_yticks([0])
        axis.set_yticklabels(["No charging sessions"])
    axis.set_xticks(np.arange(0, 25, 3))
    axis.set_xlabel("Time of day [hour]")
    axis.set_ylabel("Physical charger ID")
    axis.set_title("Executed charger occupancy and charging power")
    colorbar = figure.colorbar(image, ax=axis, pad=0.015)
    colorbar.set_label("Charging power [kW]")
    figure.text(
        0.01,
        0.01,
        (
            "Blank charger IDs and unknown charger IDs are formal failures. "
            "Inspired by No42 charging-conflict analysis; newly rendered."
        ),
        fontsize=8,
        color="#59636A",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.98))
    source_path = output_dir / "04_charger_occupancy_heatmap_source.csv"
    fields = [
        "event_id",
        "vehicle_id",
        "charger_id",
        "depot_id",
        "start_min",
        "end_min",
        "duration_min",
        "energy_kwh",
        "power_kw",
        "power_limit_kw",
        "utilization_ratio",
        "source_artifact",
    ]
    _write_csv(source_path, normalized, fields)
    return (
        _save_figure(
            figure,
            output_dir=output_dir,
            stem="04_charger_occupancy_heatmap",
        ),
        source_path,
        {
            "charger_count_observed": len(charger_ids),
            "charging_session_count": len(normalized),
            "time_resolution_minutes": resolution_min,
        },
    )


def _cost_emissions_figure(
    *,
    ledger: Mapping[str, Any],
    output_dir: Path,
) -> tuple[list[Path], Path, dict[str, Any]]:
    components = dict(ledger.get("components") or {})
    cost_rows = [
        {
            "category": "cost_component",
            "key": key,
            "label": _COST_LABELS.get(key, key),
            "value": _float(value),
            "unit": "JPY",
            "canonical_source": str(ledger.get("source") or ""),
        }
        for key, value in components.items()
    ]
    nonzero_cost_rows = [
        row for row in cost_rows if abs(float(row["value"])) > 1.0e-9
    ]
    plotted_cost_rows = nonzero_cost_rows or cost_rows
    co2 = dict(ledger.get("co2") or {})
    emission_rows = [
        {
            "category": "emission_component",
            "key": "grid_co2_kg",
            "label": "Grid electricity",
            "value": _float(co2.get("grid_co2_kg")),
            "unit": "kg-CO2",
            "canonical_source": str(ledger.get("source") or ""),
        },
        {
            "category": "emission_component",
            "key": "ice_co2_kg",
            "label": "ICE fuel",
            "value": _float(co2.get("ice_co2_kg")),
            "unit": "kg-CO2",
            "canonical_source": str(ledger.get("source") or ""),
        },
    ]
    summary_rows = [
        {
            "category": "total",
            "key": "accounting_total_cost_jpy",
            "label": "Executed accounting total",
            "value": _float(ledger.get("accounting_total_cost_jpy")),
            "unit": "JPY",
            "canonical_source": str(ledger.get("source") or ""),
        },
        {
            "category": "total",
            "key": "total_co2_kg",
            "label": "Total operational CO2",
            "value": _float(co2.get("total_co2_kg")),
            "unit": "kg-CO2",
            "canonical_source": str(ledger.get("source") or ""),
        },
    ]
    figure, axes = plt.subplots(2, 1, figsize=(12.5, 8.5))
    axis = axes[0]
    cost_values = [float(row["value"]) for row in plotted_cost_rows]
    cost_labels = [str(row["label"]) for row in plotted_cost_rows]
    y_values = np.arange(len(plotted_cost_rows))
    axis.barh(y_values, cost_values, color=_BLUE)
    axis.set_yticks(y_values)
    axis.set_yticklabels(cost_labels)
    axis.invert_yaxis()
    axis.set_xlabel("Cost [JPY]")
    axis.set_title("Executed-day canonical cost components")
    for y_value, value in zip(y_values, cost_values):
        axis.text(
            value,
            y_value,
            f" {value:,.1f}",
            va="center",
            fontsize=8,
        )
    axis = axes[1]
    emission_values = [float(row["value"]) for row in emission_rows]
    emission_labels = [str(row["label"]) for row in emission_rows]
    y_values = np.arange(len(emission_rows))
    axis.barh(y_values, emission_values, color=[_GREEN, _ORANGE])
    axis.set_yticks(y_values)
    axis.set_yticklabels(emission_labels)
    axis.invert_yaxis()
    axis.set_xlabel("Operational emissions [kg-CO2]")
    axis.set_title("Executed-day operational CO2 components")
    for y_value, value in zip(y_values, emission_values):
        axis.text(
            value,
            y_value,
            f" {value:,.2f}",
            va="center",
            fontsize=8,
        )
    figure.suptitle("Executed-day accounting and emissions", fontsize=14)
    figure.text(
        0.01,
        0.01,
        (
            "Cost bars use the canonical executed-day ledger, not the Stage 1 "
            "proxy objective. Inspired by No16 Fig. 6 and No55 Table 5."
        ),
        fontsize=8,
        color="#59636A",
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.965))
    source_path = output_dir / "05_cost_and_emissions_source.csv"
    rows = [*cost_rows, *emission_rows, *summary_rows]
    _write_csv(
        source_path,
        rows,
        [
            "category",
            "key",
            "label",
            "value",
            "unit",
            "canonical_source",
        ],
    )
    return (
        _save_figure(
            figure,
            output_dir=output_dir,
            stem="05_cost_and_emissions",
        ),
        source_path,
        {
            "accounting_total_cost_jpy": _float(
                ledger.get("accounting_total_cost_jpy")
            ),
            "total_co2_kg": _float(co2.get("total_co2_kg")),
            "accounting_residual_jpy": _float(
                ledger.get("accounting_residual_jpy")
            ),
        },
    )


def _literature_reference_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _LITERATURE_REFERENCES:
        path = repo_root / str(item["relative_path"])
        rows.append(
            {
                **dict(item),
                "local_file_available": path.is_file(),
                "local_file_size_bytes": path.stat().st_size if path.is_file() else None,
                "local_file_sha256": _sha256(path) if path.is_file() else None,
                "reuse_policy": (
                    "analytical relationship adapted; source image not copied"
                ),
            }
        )
    return rows


def _eligibility_rows() -> list[dict[str, Any]]:
    return [
        {
            "literature_output_family": "vehicle schedule and SOC",
            "single_run_status": "GENERATED",
            "artifact": (
                "01_vehicle_operation_timeline; 02_bev_soc_profiles"
            ),
            "reason": "executed event and independent SOC evidence are available",
        },
        {
            "literature_output_family": "PV/BESS/grid energy management",
            "single_run_status": "GENERATED",
            "artifact": "03_energy_management_profile",
            "reason": "accepted rolling prefixes provide executed hourly flows",
        },
        {
            "literature_output_family": "charger occupancy/conflict",
            "single_run_status": "GENERATED",
            "artifact": "04_charger_occupancy_heatmap",
            "reason": "physical charger IDs and executed sessions are available",
        },
        {
            "literature_output_family": "cost and CO2 components",
            "single_run_status": "GENERATED",
            "artifact": "05_cost_and_emissions",
            "reason": "executed-day canonical ledger is reconciled",
        },
        {
            "literature_output_family": "high-PV versus low-PV comparison",
            "single_run_status": "REQUIRES_PAIRED_RUNS",
            "artifact": "",
            "reason": "one run cannot establish a counterfactual comparison",
        },
        {
            "literature_output_family": "Monte Carlo uncertainty distribution",
            "single_run_status": "REQUIRES_MULTI_RUN_EXPERIMENT",
            "artifact": "",
            "reason": "probability distributions cannot be inferred from one solve",
        },
        {
            "literature_output_family": "charger/PV/BESS capacity sensitivity",
            "single_run_status": "REQUIRES_PARAMETER_SWEEP",
            "artifact": "",
            "reason": "capacity response requires controlled repeated solves",
        },
        {
            "literature_output_family": "runtime distribution",
            "single_run_status": "REQUIRES_REPEATED_RUNS",
            "artifact": "",
            "reason": "one runtime is not a distribution or stability result",
        },
    ]


def _kpi_rows(
    *,
    fleet_contract: Mapping[str, Any],
    event_rows: Sequence[Mapping[str, Any]],
    physical: Mapping[str, Any],
    executed: Mapping[str, Any],
    ledger: Mapping[str, Any],
    claim_scope: Mapping[str, Any],
) -> list[dict[str, Any]]:
    parameters = [
        dict(item)
        for item in list(fleet_contract.get("active_vehicle_parameters") or ())
        if isinstance(item, Mapping)
    ]
    powertrain_by_vehicle = {
        str(item.get("vehicle_id") or ""): str(
            item.get("powertrain") or "UNKNOWN"
        ).upper()
        for item in parameters
    }
    used_vehicle_ids = {
        str(row.get("vehicle_id") or "")
        for row in event_rows
        if str(row.get("event_type") or "") == "service_trip"
    }
    used_counts: dict[str, int] = {}
    for vehicle_id in used_vehicle_ids:
        powertrain = powertrain_by_vehicle.get(vehicle_id, "UNKNOWN")
        used_counts[powertrain] = used_counts.get(powertrain, 0) + 1
    unique_trip_ids = {
        str(row.get("trip_id") or "")
        for row in event_rows
        if str(row.get("event_type") or "") == "service_trip"
        and str(row.get("trip_id") or "")
    }
    inventory = dict(
        fleet_contract.get("active_inventory_by_powertrain") or {}
    )
    cost_breakdown = dict(executed.get("cost_breakdown") or {})
    co2 = dict(ledger.get("co2") or {})
    rows = [
        ("active_bev_count", inventory.get("BEV", 0), "vehicles", "scenario_fleet_contract.json"),
        ("active_ice_count", inventory.get("ICE", 0), "vehicles", "scenario_fleet_contract.json"),
        ("used_bev_count", used_counts.get("BEV", 0), "vehicles", "graph/vehicle_event_timeline.csv"),
        ("used_ice_count", used_counts.get("ICE", 0), "vehicles", "graph/vehicle_event_timeline.csv"),
        ("served_trip_count", len(unique_trip_ids), "trips", "graph/vehicle_event_timeline.csv"),
        (
            "unassigned_trip_count",
            dict(physical.get("validation_metrics") or {}).get(
                "unassigned_trip_count", 0
            ),
            "trips",
            "physical_schedule_validation.json",
        ),
        (
            "executed_slot_count",
            executed.get("executed_slot_count"),
            "slots",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        (
            "accounting_total_cost_jpy",
            ledger.get("accounting_total_cost_jpy"),
            "JPY",
            "graph/canonical_cost_ledger.json",
        ),
        (
            "total_co2_kg",
            co2.get("total_co2_kg"),
            "kg-CO2",
            "graph/canonical_cost_ledger.json",
        ),
        (
            "pv_generated_kwh",
            cost_breakdown.get("pv_generated_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        (
            "grid_import_kwh",
            cost_breakdown.get("grid_import_kwh"),
            "kWh",
            "rolling_hourly_chain/executed_day_accounting.json",
        ),
        (
            "physical_schedule_accepted",
            physical.get("accepted"),
            "boolean",
            "physical_schedule_validation.json",
        ),
        (
            "teacher_release_status",
            claim_scope.get("teacher_release_status"),
            "status",
            "research_claim_scope.json",
        ),
    ]
    return [
        {
            "metric": metric,
            "value": value,
            "unit": unit,
            "canonical_source": source,
        }
        for metric, value, unit, source in rows
    ]


def _mapping_rows(
    values: Mapping[str, Any],
    *,
    key_name: str,
    source_artifact: str,
) -> list[dict[str, Any]]:
    return [
        {
            key_name: key,
            "value": value,
            "source_artifact": source_artifact,
        }
        for key, value in sorted(values.items())
    ]


def _fieldnames_for_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback: Sequence[str],
) -> list[str]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            key_text = str(key)
            if key_text not in fields:
                fields.append(key_text)
    return fields or list(fallback)


def _write_raw_data_bundle(
    *,
    run_dir: Path,
    output_dir: Path,
    event_rows: Sequence[Mapping[str, Any]],
    soc_rows: Sequence[Mapping[str, Any]],
    charger_rows: Sequence[Mapping[str, Any]],
    hourly_rows: Sequence[Mapping[str, Any]],
    co2_rows: Sequence[Mapping[str, Any]],
    cost_rows: Sequence[Mapping[str, Any]],
    fleet_contract: Mapping[str, Any],
    physical: Mapping[str, Any],
    executed: Mapping[str, Any],
    ledger: Mapping[str, Any],
    normalized_energy_path: Path,
) -> tuple[list[Path], Path]:
    """Persist analysis-ready CSV evidence without changing canonical values."""

    raw_dir = output_dir / "raw_data"
    raw_dir.mkdir(parents=True, exist_ok=True)
    catalog_rows: list[dict[str, Any]] = []
    artifacts: list[Path] = []

    canonical_copies = [
        (
            run_dir / "graph" / "vehicle_event_timeline.csv",
            "01_executed_vehicle_events.csv",
            len(event_rows),
            "event-level vehicle movement, service, charging, and refueling",
        ),
        (
            run_dir / "graph" / "vehicle_soc_event_timeline.csv",
            "02_executed_bev_soc_events.csv",
            len(soc_rows),
            "independently reconstructed BEV SOC transitions",
        ),
        (
            run_dir / "graph" / "charger_occupancy_timeline.csv",
            "03_executed_charger_sessions.csv",
            len(charger_rows),
            "physical charger occupancy and power",
        ),
        (
            run_dir
            / "rolling_hourly_chain"
            / "hourly_energy_flow_chart.csv",
            "04_executed_hourly_energy_flows_original.csv",
            len(hourly_rows),
            "accepted rolling-prefix depot energy flows",
        ),
        (
            run_dir / "graph" / "cost_timeseries.csv",
            "05_executed_cost_timeseries.csv",
            len(cost_rows),
            "canonical time-resolved cost evidence",
        ),
        (
            run_dir / "graph" / "co2_timeseries.csv",
            "06_executed_co2_timeseries.csv",
            len(co2_rows),
            "canonical time-resolved operational CO2 evidence",
        ),
        (
            run_dir / "vehicle_schedule.csv",
            "07_vehicle_trip_assignment_schedule.csv",
            len(_read_csv(run_dir / "vehicle_schedule.csv")),
            "final vehicle-trip assignment and timetable rows",
        ),
        (
            run_dir
            / "rolling_hourly_chain"
            / "charging_schedule.csv",
            "08_executed_charging_schedule_source_rows.csv",
            len(
                _read_csv(
                    run_dir
                    / "rolling_hourly_chain"
                    / "charging_schedule.csv"
                )
            ),
            (
                "accepted executed charging rows before physical "
                "source-session aggregation"
            ),
        ),
    ]
    for source_path, filename, row_count, description in canonical_copies:
        target = raw_dir / filename
        shutil.copy2(source_path, target)
        artifacts.append(target)
        catalog_rows.append(
            {
                "dataset": target.stem,
                "file": target.name,
                "row_count": row_count,
                "data_level": "canonical_copy",
                "canonical_source": source_path.relative_to(run_dir).as_posix(),
                "description": description,
            }
        )

    normalized_energy_target = (
        raw_dir / "09_executed_hourly_energy_flows_normalized.csv"
    )
    shutil.copy2(normalized_energy_path, normalized_energy_target)
    normalized_energy_rows = _read_csv(normalized_energy_target)
    artifacts.append(normalized_energy_target)
    catalog_rows.append(
        {
            "dataset": normalized_energy_target.stem,
            "file": normalized_energy_target.name,
            "row_count": len(normalized_energy_rows),
            "data_level": "deterministic_normalization",
            "canonical_source": (
                "rolling_hourly_chain/hourly_energy_flow_chart.csv;"
                "graph/co2_timeseries.csv;graph/cost_timeseries.csv"
            ),
            "description": (
                "hourly PV, BESS, grid, price, and emission-factor columns "
                "joined by execution time"
            ),
        }
    )

    parameter_rows = [
        dict(row)
        for row in list(
            fleet_contract.get("active_vehicle_parameters") or ()
        )
        if isinstance(row, Mapping)
    ]
    vehicle_path = raw_dir / "10_active_vehicle_parameters.csv"
    _write_csv(
        vehicle_path,
        parameter_rows,
        _fieldnames_for_rows(
            parameter_rows,
            fallback=["vehicle_id", "powertrain"],
        ),
    )
    artifacts.append(vehicle_path)
    catalog_rows.append(
        {
            "dataset": vehicle_path.stem,
            "file": vehicle_path.name,
            "row_count": len(parameter_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": "scenario_fleet_contract.json",
            "description": (
                "active vehicle IDs, initial state, capacity, consumption, "
                "depot, availability, and compatibility parameters"
            ),
        }
    )

    cost_component_rows = _mapping_rows(
        dict(ledger.get("components") or {}),
        key_name="cost_component",
        source_artifact="graph/canonical_cost_ledger.json",
    )
    cost_component_path = raw_dir / "11_canonical_cost_components.csv"
    _write_csv(
        cost_component_path,
        cost_component_rows,
        ["cost_component", "value", "source_artifact"],
    )
    artifacts.append(cost_component_path)
    catalog_rows.append(
        {
            "dataset": cost_component_path.stem,
            "file": cost_component_path.name,
            "row_count": len(cost_component_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": "graph/canonical_cost_ledger.json",
            "description": "all canonical executed-day cost components",
        }
    )

    co2_component_rows = _mapping_rows(
        dict(ledger.get("co2") or {}),
        key_name="co2_component",
        source_artifact="graph/canonical_cost_ledger.json",
    )
    co2_component_path = raw_dir / "12_canonical_co2_components.csv"
    _write_csv(
        co2_component_path,
        co2_component_rows,
        ["co2_component", "value", "source_artifact"],
    )
    artifacts.append(co2_component_path)
    catalog_rows.append(
        {
            "dataset": co2_component_path.stem,
            "file": co2_component_path.name,
            "row_count": len(co2_component_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": "graph/canonical_cost_ledger.json",
            "description": "grid, ICE, and total operational CO2 components",
        }
    )

    validation_rows = _mapping_rows(
        dict(physical.get("validation_metrics") or {}),
        key_name="validation_metric",
        source_artifact="physical_schedule_validation.json",
    )
    validation_path = raw_dir / "13_physical_validation_metrics.csv"
    _write_csv(
        validation_path,
        validation_rows,
        ["validation_metric", "value", "source_artifact"],
    )
    artifacts.append(validation_path)
    catalog_rows.append(
        {
            "dataset": validation_path.stem,
            "file": validation_path.name,
            "row_count": len(validation_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": "physical_schedule_validation.json",
            "description": "independent physical schedule validation metrics",
        }
    )

    executed_cost_rows = _mapping_rows(
        dict(executed.get("cost_breakdown") or {}),
        key_name="executed_day_metric",
        source_artifact=(
            "rolling_hourly_chain/executed_day_accounting.json"
        ),
    )
    executed_cost_path = raw_dir / "14_executed_day_accounting_metrics.csv"
    _write_csv(
        executed_cost_path,
        executed_cost_rows,
        ["executed_day_metric", "value", "source_artifact"],
    )
    artifacts.append(executed_cost_path)
    catalog_rows.append(
        {
            "dataset": executed_cost_path.stem,
            "file": executed_cost_path.name,
            "row_count": len(executed_cost_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": (
                "rolling_hourly_chain/executed_day_accounting.json"
            ),
            "description": (
                "executed-day energy, fuel, cost, and accounting metrics"
            ),
        }
    )

    excluded_rows = [
        dict(row)
        for row in list(
            fleet_contract.get("excluded_vehicle_records") or ()
        )
        if isinstance(row, Mapping)
    ]
    excluded_path = raw_dir / "15_excluded_vehicle_records.csv"
    _write_csv(
        excluded_path,
        excluded_rows,
        _fieldnames_for_rows(
            excluded_rows,
            fallback=["vehicle_id", "reason"],
        ),
    )
    artifacts.append(excluded_path)
    catalog_rows.append(
        {
            "dataset": excluded_path.stem,
            "file": excluded_path.name,
            "row_count": len(excluded_rows),
            "data_level": "canonical_json_to_csv",
            "canonical_source": "scenario_fleet_contract.json",
            "description": "vehicles excluded from the active run scope and reasons",
        }
    )

    catalog_path = raw_dir / "raw_data_catalog.csv"
    _write_csv(
        catalog_path,
        catalog_rows,
        [
            "dataset",
            "file",
            "row_count",
            "data_level",
            "canonical_source",
            "description",
        ],
    )
    artifacts.append(catalog_path)
    return artifacts, catalog_path


def _write_bundle_index(
    *,
    output_dir: Path,
    claim_scope: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
) -> Path:
    release_status = str(
        claim_scope.get("teacher_release_status") or "UNKNOWN"
    )
    blocked_reasons = [
        str(item)
        for item in list(claim_scope.get("teacher_release_failed_checks") or ())
        if str(item)
    ]
    lines = [
        "# Literature-aligned run figures",
        "",
        (
            "These figures are newly generated from this run's canonical "
            "artifacts. They adapt analytical relationships used in the local "
            "literature; no paper figure is reproduced."
        ),
        "",
        f"- Teacher release status: `{release_status}`",
        "- Physical/rolling evidence and teacher release are separate gates.",
    ]
    if blocked_reasons:
        lines.extend(
            [
                "- This bundle is diagnostic and is not used for research "
                "conclusions until the listed release blockers are cleared:",
                *[f"  - `{item}`" for item in blocked_reasons],
            ]
        )
    lines.extend(["", "## Figures", ""])
    for entry in entries:
        if str(entry.get("kind")) != "figure":
            continue
        files = [
            str(path)
            for path in list(entry.get("artifact_files") or ())
            if str(path).endswith(".png")
        ]
        link = f"[PNG]({files[0]})" if files else ""
        lines.append(
            f"- `{entry.get('figure_id')}` - {entry.get('title')} {link}".rstrip()
        )
    lines.extend(
        [
            "",
            "## Evidence rules",
            "",
            "- Executed costs come from `rolling_hourly_chain/executed_day_accounting.json`.",
            "- SOC comes from independent event-level reconstruction of the executed charging schedule.",
            "- Charger plots require physical charger IDs; inferred energy-source labels are not charger IDs.",
            "- Paired comparison, uncertainty, capacity sensitivity, and runtime distributions require separate controlled experiments.",
            "- Analysis-ready CSV evidence is collected under `raw_data/`; `raw_data/raw_data_catalog.csv` defines every dataset and canonical source.",
            "",
            "See `literature_source_mapping.csv`, `figure_eligibility.csv`, and "
            "`run_kpi_table.csv` for exact provenance and scope.",
            "",
        ]
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _register_graph_manifest(
    *,
    run_dir: Path,
    figure_count: int,
) -> None:
    manifest_path = run_dir / "graph" / "manifest.json"
    manifest = _load_json(manifest_path)
    optional = dict(manifest.get("optional_exports") or {})
    optional["literature_figures"] = {
        "enabled": True,
        "manifest_file": "literature_figures/manifest.json",
        "figure_count": int(figure_count),
        "formats": ["png", "svg", "csv", "markdown"],
        "source": "accepted_rolling_and_canonical_run_artifacts",
    }
    manifest["optional_exports"] = optional
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@_serialize_figure_generation
def generate_literature_figure_bundle(run_dir: Path) -> dict[str, Any]:
    """Generate and register research figures for one finalized rolling run."""

    run_dir = Path(run_dir).resolve()
    graph_dir = run_dir / "graph"
    output_dir = graph_dir / "literature_figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    _configure_plotting()

    executed_path = (
        run_dir / "rolling_hourly_chain" / "executed_day_accounting.json"
    )
    hourly_path = (
        run_dir / "rolling_hourly_chain" / "hourly_energy_flow_chart.csv"
    )
    physical_path = run_dir / "physical_schedule_validation.json"
    fleet_path = run_dir / "scenario_fleet_contract.json"
    ledger_path = graph_dir / "canonical_cost_ledger.json"
    event_path = graph_dir / "vehicle_event_timeline.csv"
    soc_path = graph_dir / "vehicle_soc_event_timeline.csv"
    charger_path = graph_dir / "charger_occupancy_timeline.csv"
    co2_path = graph_dir / "co2_timeseries.csv"
    cost_path = graph_dir / "cost_timeseries.csv"
    claim_path = run_dir / "research_claim_scope.json"

    executed = _load_json(executed_path)
    physical = _load_json(physical_path)
    fleet_contract = _load_json(fleet_path)
    ledger = _load_json(ledger_path)
    claim_scope = _load_json(claim_path)
    if executed.get("eligible") is not True:
        raise LiteratureFigureError(
            "Literature figures require eligible executed-day accounting"
        )
    if physical.get("accepted") is not True:
        raise LiteratureFigureError(
            "Literature figures require accepted physical schedule validation"
        )
    if ledger.get("accounting_residual_satisfied") is not True:
        raise LiteratureFigureError(
            "Literature figures require a reconciled canonical cost ledger"
        )

    event_rows = _read_csv(event_path)
    soc_rows = _read_csv(soc_path)
    charger_rows = _read_csv(charger_path)
    hourly_rows = _read_csv(hourly_path)
    co2_rows = _read_csv(co2_path)
    cost_rows = _read_csv(cost_path)
    labels, powertrains = _plot_label_map(fleet_contract)

    figure_specs: list[dict[str, Any]] = []

    artifacts, source, metrics = _event_figure(
        event_rows=event_rows,
        labels=labels,
        powertrains=powertrains,
        output_dir=output_dir,
    )
    figure_specs.append(
        {
            "kind": "figure",
            "figure_id": "vehicle_operation_timeline",
            "title": "Executed vehicle operation and charging timeline",
            "analytical_question": (
                "When is each vehicle serving, moving, charging, or refueling?"
            ),
            "literature_analogues": ["No42 Fig. 7", "No16 Fig. 3"],
            "canonical_sources": [event_path.relative_to(run_dir).as_posix()],
            "artifact_files": [
                path.name for path in [*artifacts, source]
            ],
            "metrics": metrics,
        }
    )

    artifacts, source, metrics = _soc_figure(
        soc_rows=soc_rows,
        labels=labels,
        output_dir=output_dir,
    )
    figure_specs.append(
        {
            "kind": "figure",
            "figure_id": "bev_soc_profiles",
            "title": "Executed BEV state-of-charge profiles",
            "analytical_question": (
                "Does every used BEV remain above reserve and meet its terminal "
                "condition?"
            ),
            "literature_analogues": [
                "No55 Fig. 6",
                "No16 Fig. 5",
                "No61 Fig. 4",
            ],
            "canonical_sources": [soc_path.relative_to(run_dir).as_posix()],
            "artifact_files": [
                path.name for path in [*artifacts, source]
            ],
            "metrics": metrics,
        }
    )

    artifacts, source, metrics = _energy_management_figure(
        hourly_rows=hourly_rows,
        co2_rows=co2_rows,
        cost_rows=cost_rows,
        output_dir=output_dir,
    )
    normalized_energy_path = source
    figure_specs.append(
        {
            "kind": "figure",
            "figure_id": "energy_management_profile",
            "title": "Executed-day energy management profile",
            "analytical_question": (
                "How do PV, BESS, grid charging, BESS SOC, and the carbon "
                "signal evolve through the executed rolling day?"
            ),
            "literature_analogues": [
                "No61 Figs. 7-9",
                "IEEJ rolling study Figs. 2-3",
                "No16 Figs. 4 and 8",
            ],
            "canonical_sources": [
                hourly_path.relative_to(run_dir).as_posix(),
                "vehicle_schedule.csv",
                "rolling_hourly_chain/charging_schedule.csv",
                co2_path.relative_to(run_dir).as_posix(),
                cost_path.relative_to(run_dir).as_posix(),
            ],
            "artifact_files": [
                path.name for path in [*artifacts, source]
            ],
            "metrics": metrics,
        }
    )

    artifacts, source, metrics = _charger_figure(
        charger_rows=charger_rows,
        output_dir=output_dir,
    )
    figure_specs.append(
        {
            "kind": "figure",
            "figure_id": "charger_occupancy_heatmap",
            "title": "Executed charger occupancy and charging power",
            "analytical_question": (
                "Which physical charger is occupied at each time, and at what "
                "power?"
            ),
            "literature_analogues": ["No42 charging-conflict formulation"],
            "canonical_sources": [charger_path.relative_to(run_dir).as_posix()],
            "artifact_files": [
                path.name for path in [*artifacts, source]
            ],
            "metrics": metrics,
        }
    )

    artifacts, source, metrics = _cost_emissions_figure(
        ledger=ledger,
        output_dir=output_dir,
    )
    figure_specs.append(
        {
            "kind": "figure",
            "figure_id": "cost_and_emissions",
            "title": "Executed-day accounting and emissions",
            "analytical_question": (
                "Which canonical cost and operational CO2 components explain "
                "the executed-day totals?"
            ),
            "literature_analogues": ["No16 Fig. 6", "No55 Table 5"],
            "canonical_sources": [ledger_path.relative_to(run_dir).as_posix()],
            "artifact_files": [
                path.name for path in [*artifacts, source]
            ],
            "metrics": metrics,
        }
    )

    repo_root = Path(__file__).resolve().parents[3]
    reference_rows = _literature_reference_rows(repo_root)
    reference_path = output_dir / "literature_source_mapping.csv"
    _write_csv(
        reference_path,
        reference_rows,
        [
            "reference_id",
            "relative_path",
            "citation",
            "pages",
            "figures_or_tables",
            "adapted_relationship",
            "reuse_policy",
            "local_file_available",
            "local_file_size_bytes",
            "local_file_sha256",
        ],
    )
    eligibility_path = output_dir / "figure_eligibility.csv"
    eligibility_rows = _eligibility_rows()
    _write_csv(
        eligibility_path,
        eligibility_rows,
        [
            "literature_output_family",
            "single_run_status",
            "artifact",
            "reason",
        ],
    )
    kpi_path = output_dir / "run_kpi_table.csv"
    kpi_rows = _kpi_rows(
        fleet_contract=fleet_contract,
        event_rows=event_rows,
        physical=physical,
        executed=executed,
        ledger=ledger,
        claim_scope=claim_scope,
    )
    _write_csv(
        kpi_path,
        kpi_rows,
        ["metric", "value", "unit", "canonical_source"],
    )
    raw_data_artifacts, raw_data_catalog_path = _write_raw_data_bundle(
        run_dir=run_dir,
        output_dir=output_dir,
        event_rows=event_rows,
        soc_rows=soc_rows,
        charger_rows=charger_rows,
        hourly_rows=hourly_rows,
        co2_rows=co2_rows,
        cost_rows=cost_rows,
        fleet_contract=fleet_contract,
        physical=physical,
        executed=executed,
        ledger=ledger,
        normalized_energy_path=normalized_energy_path,
    )
    index_path = _write_bundle_index(
        output_dir=output_dir,
        claim_scope=claim_scope,
        entries=figure_specs,
    )
    figure_specs.append(
        {
            "kind": "bundle_metadata",
            "figure_id": "bundle_provenance",
            "title": "Literature mapping, eligibility, and KPI tables",
            "artifact_files": [
                index_path.name,
                reference_path.name,
                eligibility_path.name,
                kpi_path.name,
            ],
            "canonical_sources": [
                fleet_path.relative_to(run_dir).as_posix(),
                physical_path.relative_to(run_dir).as_posix(),
                executed_path.relative_to(run_dir).as_posix(),
                claim_path.relative_to(run_dir).as_posix(),
            ],
        }
    )
    figure_specs.append(
        {
            "kind": "raw_data_bundle",
            "figure_id": "analysis_ready_raw_data",
            "title": "Analysis-ready CSV evidence bundle",
            "artifact_files": [
                path.relative_to(output_dir).as_posix()
                for path in raw_data_artifacts
            ],
            "catalog_file": raw_data_catalog_path.relative_to(
                output_dir
            ).as_posix(),
            "canonical_sources": [
                event_path.relative_to(run_dir).as_posix(),
                soc_path.relative_to(run_dir).as_posix(),
                charger_path.relative_to(run_dir).as_posix(),
                hourly_path.relative_to(run_dir).as_posix(),
                co2_path.relative_to(run_dir).as_posix(),
                cost_path.relative_to(run_dir).as_posix(),
                fleet_path.relative_to(run_dir).as_posix(),
                physical_path.relative_to(run_dir).as_posix(),
                ledger_path.relative_to(run_dir).as_posix(),
                executed_path.relative_to(run_dir).as_posix(),
            ],
        }
    )

    source_paths = sorted(
        {
            path
            for entry in figure_specs
            for path in list(entry.get("canonical_sources") or ())
        }
    )
    source_artifacts = {
        relative_path: _artifact_record(
            run_dir / relative_path,
            root=run_dir,
        )
        for relative_path in source_paths
    }
    for entry in figure_specs:
        entry["artifact_records"] = [
            _artifact_record(output_dir / relative_path, root=output_dir)
            for relative_path in list(entry.get("artifact_files") or ())
        ]

    manifest = {
        "schema_version": LITERATURE_FIGURE_SCHEMA_VERSION,
        "status": "READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_scope": (
            "accepted_hourly_rolling_executed_day_and_independent_physical_"
            "event_validation"
        ),
        "teacher_release_status": claim_scope.get("teacher_release_status"),
        "research_submission_ready": bool(
            claim_scope.get("research_submission_ready", False)
        ),
        "diagnostic_only": not bool(
            claim_scope.get("research_submission_ready", False)
        ),
        "figure_count": sum(
            1 for entry in figure_specs if entry.get("kind") == "figure"
        ),
        "raw_data_csv_count": len(raw_data_artifacts),
        "raw_data_catalog": raw_data_catalog_path.relative_to(
            output_dir
        ).as_posix(),
        "entries": figure_specs,
        "source_artifacts": source_artifacts,
        "literature_references": reference_rows,
        "limitations": [
            (
                "The visual relationships are adapted from the cited local "
                "literature; all plotted values come from this run and no "
                "source-paper image is copied."
            ),
            (
                "A single run cannot establish a high/low-PV comparison, "
                "uncertainty distribution, capacity sensitivity, or runtime "
                "distribution."
            ),
            (
                "Teacher release status is independent of successful figure "
                "generation."
            ),
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _register_graph_manifest(
        run_dir=run_dir,
        figure_count=int(manifest["figure_count"]),
    )
    return manifest


__all__ = [
    "LITERATURE_FIGURE_SCHEMA_VERSION",
    "LiteratureFigureError",
    "generate_literature_figure_bundle",
]
