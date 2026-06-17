"""Plot rebuilt reporting time-series artifacts without rerunning simulation.

This script reads canonical reporting CSV/JSON files from rebuilt run folders and
writes publication-oriented PNG/SVG figures plus daily summary tables.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd


BALANCE_TOLERANCE_KWH = 1e-3
DEFAULT_RUN_IDS = ["run_20260606_1559", "run_20260606_1624"]
DEFAULT_INPUT_ROOT = Path("output/2026-06-06/rebuilt_reporting_20260606")
DEFAULT_OUTPUT_ROOT = Path("output/visualization_data/2026-06-06/rebuilt_reporting_20260606")

RUN_DISPLAY_METADATA = {
    "run_20260606_1559": {"display_date": "2025/08/05", "weather": "晴", "label": "2025/08/05 晴"},
    "run_20260606_1624": {"display_date": "2025/08/10", "weather": "雨", "label": "2025/08/10 雨"},
}

PPT_FIGSIZE = (16.0, 9.0)
PPT_TALL_FIGSIZE = (16.0, 10.5)
TABLE_FIGSIZE = (16.0, 7.2)


PLOT_STYLE = {
    "pv_generation_kwh": "#f2b01e",
    "pv_to_bus_kwh": "#2ca02c",
    "pv_to_bess_kwh": "#8bc34a",
    "pv_curtailed_kwh": "#d62728",
    "pv_export_kwh": "#17becf",
    "grid_import_kwh": "#1f77b4",
    "grid_to_bus_kwh": "#4c78a8",
    "grid_to_bess_kwh": "#9ecae9",
    "bess_to_bus_kwh": "#9467bd",
    "bess_charge_kwh": "#6baed6",
    "bess_discharge_kwh": "#756bb1",
    "bus_charging_total_kwh": "#111111",
    "bess_soc_kwh": "#ff7f0e",
    "bess_soc_min_kwh": "#7f7f7f",
    "bess_soc_max_kwh": "#7f7f7f",
    "grid_purchase_cost_jpy": "#1f77b4",
    "demand_charge_cost_jpy": "#ff7f0e",
    "fuel_cost_jpy": "#8c564b",
    "co2_cost_jpy": "#2ca02c",
    "grid_co2_kg": "#1f77b4",
    "ice_co2_kg": "#8c564b",
    "total_co2_kg": "#111111",
    "fuel_consumption_l": "#8c564b",
    "refuel_l": "#ff7f0e",
}


DISPLAY_LABELS = {
    "pv_generation_kwh": "PV発電量",
    "pv_to_bus_kwh": "PV→バス",
    "pv_to_bess_kwh": "PV→BESS",
    "pv_curtailed_kwh": "PV出力抑制",
    "pv_export_kwh": "PV売電",
    "grid_import_kwh": "系統受電",
    "grid_to_bus_kwh": "系統→バス",
    "grid_to_bess_kwh": "系統→BESS",
    "bess_to_bus_kwh": "BESS→バス",
    "bess_charge_kwh": "BESS充電",
    "bess_discharge_kwh": "BESS放電",
    "bus_charging_total_kwh": "バス充電合計",
    "bess_soc_kwh": "BESS SOC",
    "bess_soc_min_kwh": "SOC下限",
    "bess_soc_max_kwh": "SOC上限",
    "grid_purchase_cost_jpy": "系統電力購入費",
    "demand_charge_cost_jpy": "デマンド料金",
    "fuel_cost_jpy": "燃料費",
    "co2_cost_jpy": "CO2費用",
    "grid_co2_kg": "系統由来CO2",
    "ice_co2_kg": "ガソリン車由来CO2",
    "total_co2_kg": "CO2合計",
    "fuel_consumption_l": "燃料使用量",
    "refuel_l": "給油量",
    "grid_to_vehicle_kwh": "系統→車両",
    "pv_to_vehicle_kwh": "PV→車両",
    "bess_to_vehicle_kwh": "BESS→車両",
    "total_charge_kwh": "車両充電合計",
    "objective_value_jpy": "目的関数値",
    "gross_operating_cost_jpy": "実運用費用",
}


def configure_japanese_fonts() -> None:
    available = {font.name for font in fm.fontManager.ttflist}
    for name in ["Meiryo", "Yu Gothic", "Yu Gothic UI", "MS Gothic", "Noto Sans CJK JP"]:
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.titlesize": 20,
            "axes.labelsize": 16,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "legend.fontsize": 13,
            "figure.titlesize": 22,
        }
    )


configure_japanese_fonts()


def display_metadata(run_id: str) -> dict[str, str]:
    fallback = {"display_date": "UNKNOWN", "weather": "UNKNOWN", "label": run_id}
    return {**fallback, **RUN_DISPLAY_METADATA.get(str(run_id), {})}


def run_display_label(run: dict[str, Any]) -> str:
    return str(run.get("display_label") or display_metadata(str(run.get("run_id") or ""))["label"])


def titled(run: dict[str, Any], title: str) -> str:
    return f"{title}（{run_display_label(run)}）"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot time-series charts from rebuilt reporting artifacts only."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="Root containing rebuilt reporting run directories.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root where visualization outputs will be written.",
    )
    parser.add_argument(
        "--run-ids",
        nargs="+",
        default=DEFAULT_RUN_IDS,
        help="Run directory names to plot.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def ensure_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0.0)
    return result


def normalize_curtailment(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if "pv_curtailed_kwh" not in result.columns:
        if "pv_curtailment_kwh" in result.columns:
            result["pv_curtailed_kwh"] = result["pv_curtailment_kwh"]
        else:
            result["pv_curtailed_kwh"] = 0.0
    return result


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = 0.0
    return ensure_numeric(result, columns)


def to_local_naive_datetime(values: Any) -> pd.Series:
    result = pd.to_datetime(values, errors="coerce")
    try:
        if result.dt.tz is not None:
            return result.dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return result


def time_axis(df: pd.DataFrame) -> pd.Series:
    if "timestamp" in df.columns:
        return to_local_naive_datetime(df["timestamp"])
    if "time" in df.columns and "date" in df.columns:
        return to_local_naive_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    if "slot_start" in df.columns:
        return to_local_naive_datetime(df["slot_start"])
    return pd.Series(range(len(df)), index=df.index)


def format_time_axis(ax: plt.Axes) -> None:
    try:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
        ax.figure.autofmt_xdate(rotation=25, ha="right")
    except (TypeError, ValueError):
        pass


def set_time_xlim(ax: plt.Axes, values: Any) -> None:
    try:
        series = pd.Series(values).dropna()
        if not series.empty:
            ax.set_xlim(series.min(), series.max())
    except Exception:
        pass


def finish_figure(fig: plt.Figure, output_base: Path) -> None:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_base.with_suffix(".png"), dpi=240, bbox_inches="tight")
    fig.savefig(output_base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def label_for(column: str) -> str:
    return DISPLAY_LABELS.get(column, column)


def color_for(column: str) -> str | None:
    return PLOT_STYLE.get(column)


def place_legend(ax: plt.Axes, ncol: int = 1) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    ax.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        borderaxespad=0.0,
        frameon=True,
        fontsize=13,
        ncol=ncol,
    )


def plot_lines(
    df: pd.DataFrame,
    columns: list[str],
    title: str,
    ylabel: str,
    output_base: Path,
    annotate: str | None = None,
) -> None:
    existing = [col for col in columns if col in df.columns]
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    x = time_axis(df)
    if existing:
        plot_df = ensure_numeric(df, existing)
        for col in existing:
            ax.plot(
                x,
                plot_df[col],
                marker="o",
                linewidth=1.8,
                label=label_for(col),
                color=color_for(col),
            )
    else:
        ax.text(0.5, 0.5, "対象列が見つかりません", ha="center", va="center")
    if annotate:
        ax.text(
            0.01,
            0.98,
            annotate,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=13,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
        )
    ax.set_title(title)
    ax.set_xlabel("時刻")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    if existing:
        place_legend(ax)
    set_time_xlim(ax, x)
    format_time_axis(ax)
    finish_figure(fig, output_base)


def plot_stacked_area(
    df: pd.DataFrame,
    stack_columns: list[str],
    line_column: str,
    title: str,
    ylabel: str,
    output_base: Path,
    annotate: str | None = None,
) -> None:
    plot_df = ensure_columns(df, stack_columns + [line_column])
    x = time_axis(plot_df)
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    ax.stackplot(
        x,
        [plot_df[col] for col in stack_columns],
        labels=[label_for(col) for col in stack_columns],
        colors=[color_for(col) for col in stack_columns],
        alpha=0.82,
    )
    ax.plot(
        x,
        plot_df[line_column],
        color=color_for(line_column) or "black",
        linewidth=2.2,
        marker="o",
        label=label_for(line_column),
    )
    if annotate:
        ax.text(
            0.01,
            0.98,
            annotate,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=13,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
        )
    ax.set_title(title)
    ax.set_xlabel("時刻")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    set_time_xlim(ax, x)
    format_time_axis(ax)
    finish_figure(fig, output_base)


def plot_daily_bar(values: dict[str, float], title: str, ylabel: str, output_base: Path) -> None:
    labels = [label_for(metric) for metric in values]
    y = [float(values[metric]) for metric in values]
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    bars = ax.bar(labels, y, color=[color_for(metric) for metric in values])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", alpha=0.25)
    ax.tick_params(axis="x", rotation=35)
    for bar, value in zip(bars, y):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            max(value, 0.0),
            f"{value:,.3f}",
            ha="center",
            va="bottom",
            fontsize=12,
            rotation=90 if len(labels) > 5 else 0,
        )
    finish_figure(fig, output_base)


def plot_bess_flow_soc(bess_df: pd.DataFrame, output_base: Path, title: str = "BESS充放電とSOC時系列") -> None:
    flow_cols = ["pv_to_bess_kwh", "grid_to_bess_kwh", "bess_to_bus_kwh"]
    soc_cols = ["bess_soc_kwh", "bess_soc_min_kwh", "bess_soc_max_kwh"]
    plot_df = ensure_columns(bess_df, flow_cols + soc_cols)
    x = time_axis(plot_df)
    fig, ax1 = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    for col in flow_cols:
        ax1.bar(
            x,
            plot_df[col],
            width=0.025,
            alpha=0.65,
            label=label_for(col),
            color=color_for(col),
        )
    ax1.set_ylabel("時間帯別エネルギー (kWh)")
    ax1.set_xlabel("時刻")
    ax1.grid(True, axis="y", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        x,
        plot_df["bess_soc_kwh"],
        color=color_for("bess_soc_kwh"),
        linewidth=2.2,
        marker="o",
        label=label_for("bess_soc_kwh"),
    )
    ax2.plot(
        x,
        plot_df["bess_soc_min_kwh"],
        color=color_for("bess_soc_min_kwh"),
        linewidth=1.8,
        linestyle="--",
        label=label_for("bess_soc_min_kwh"),
    )
    ax2.plot(
        x,
        plot_df["bess_soc_max_kwh"],
        color=color_for("bess_soc_max_kwh"),
        linewidth=1.8,
        linestyle=":",
        label=label_for("bess_soc_max_kwh"),
    )
    ax2.set_ylabel("SOC (kWh)")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        borderaxespad=0.0,
        frameon=True,
        fontsize=13,
    )
    ax1.set_title(title)
    set_time_xlim(ax1, x)
    format_time_axis(ax1)
    finish_figure(fig, output_base)


def aggregate_vehicle_sources(vehicle_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "grid_to_vehicle_kwh",
        "pv_to_vehicle_kwh",
        "bess_to_vehicle_kwh",
        "total_charge_kwh",
    ]
    if vehicle_df.empty:
        return pd.DataFrame(columns=["timestamp", *columns])
    df = ensure_columns(vehicle_df, columns)
    if "timestamp" in df.columns:
        key = "timestamp"
    elif "date" in df.columns and "time" in df.columns:
        df["timestamp"] = df["date"].astype(str) + "T" + df["time"].astype(str)
        key = "timestamp"
    else:
        df["timestamp"] = range(len(df))
        key = "timestamp"
    return df.groupby(key, as_index=False)[columns].sum()


def cost_detail_lookup(cost_detail: pd.DataFrame) -> dict[str, float]:
    if cost_detail.empty or not {"key", "value"}.issubset(cost_detail.columns):
        return {}
    values: dict[str, float] = {}
    for _, row in cost_detail.iterrows():
        try:
            values[str(row["key"])] = float(row["value"])
        except (TypeError, ValueError):
            continue
    return values


def first_number(*values: Any) -> float:
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return 0.0


def sum_column(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum())


def max_column(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).max())


def first_last_numeric(df: pd.DataFrame, col: str) -> tuple[float, float]:
    if df.empty or col not in df.columns:
        return 0.0, 0.0
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    if values.empty:
        return 0.0, 0.0
    return float(values.iloc[0]), float(values.iloc[-1])


def bess_efficiencies(run: dict[str, Any]) -> tuple[float, float]:
    conditions = run.get("simulation_conditions") or {}
    charge_eff = first_number(conditions.get("bess_charge_efficiency"), 0.95)
    discharge_eff = first_number(conditions.get("bess_discharge_efficiency"), 0.95)
    return charge_eff if charge_eff > 0 else 0.95, discharge_eff if discharge_eff > 0 else 0.95


def add_power_residuals(ledger: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "pv_export_kwh",
        "grid_import_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "depot_aux_grid_kwh",
        "bus_charging_total_kwh",
        "bess_charge_kwh",
        "bess_discharge_kwh",
        "bess_to_bus_kwh",
    ]
    df = ensure_columns(normalize_curtailment(ledger), cols)
    df["pv_allocation_residual_kwh"] = (
        df["pv_generation_kwh"]
        - df["pv_to_bus_kwh"]
        - df["pv_to_bess_kwh"]
        - df["pv_curtailed_kwh"]
        - df["pv_export_kwh"]
    )
    df["bus_charging_residual_kwh"] = (
        df["bus_charging_total_kwh"]
        - df["grid_to_bus_kwh"]
        - df["pv_to_bus_kwh"]
        - df["bess_to_bus_kwh"]
    )
    df["grid_import_residual_kwh"] = (
        df["grid_import_kwh"]
        - df["grid_to_bus_kwh"]
        - df["grid_to_bess_kwh"]
        - df["depot_aux_grid_kwh"]
    )
    df["bess_charge_residual_kwh"] = df["bess_charge_kwh"] - df["pv_to_bess_kwh"] - df["grid_to_bess_kwh"]
    df["bess_discharge_residual_kwh"] = df["bess_discharge_kwh"] - df["bess_to_bus_kwh"]
    return df


def load_run(run_dir: Path) -> dict[str, Any]:
    graph_dir = run_dir / "graph"
    meta = display_metadata(run_dir.name)
    ledger = normalize_curtailment(read_csv(graph_dir / "energy_flow_ledger.csv"))
    bess = read_csv(graph_dir / "bess_timeseries.csv")
    cost = read_csv(graph_dir / "cost_timeseries.csv")
    co2 = read_csv(graph_dir / "co2_timeseries.csv")
    fuel = read_csv(graph_dir / "fuel_timeseries.csv")
    vehicle = read_csv(graph_dir / "vehicle_charging_source_timeseries.csv")
    cost_detail = read_csv(run_dir / "cost_breakdown_detail.csv")
    return {
        "run_dir": run_dir,
        "run_id": run_dir.name,
        "display_date": meta["display_date"],
        "weather": meta["weather"],
        "display_label": meta["label"],
        "ledger": ledger,
        "bess": bess,
        "cost": cost,
        "co2": co2,
        "fuel": fuel,
        "vehicle": vehicle,
        "summary": read_json(run_dir / "summary.json"),
        "graph_kpi": read_json(graph_dir / "kpi_summary.json"),
        "legacy_kpi": read_json(run_dir / "kpi_summary.json"),
        "cost_detail": cost_detail,
        "cost_detail_values": cost_detail_lookup(cost_detail),
        "reconciliation": read_csv(run_dir / "strict_reconciliation_after_rebuild.csv"),
        "rebuild_log": read_json(run_dir / "rebuild_reporting_log.json"),
        "simulation_conditions": read_json(run_dir / "simulation_conditions.json"),
    }


def compute_daily_metrics(run: dict[str, Any]) -> dict[str, float]:
    ledger = run["ledger"]
    bess = run["bess"]
    fuel = run["fuel"]
    co2 = run["co2"]
    cost = run["cost"]
    summary = run["summary"]
    graph_kpi = run["graph_kpi"]
    cost_detail = run["cost_detail_values"]

    metrics = {
        "pv_generation_kwh": sum_column(ledger, "pv_generation_kwh"),
        "pv_to_bus_kwh": sum_column(ledger, "pv_to_bus_kwh"),
        "pv_to_bess_kwh": sum_column(ledger, "pv_to_bess_kwh"),
        "pv_curtailed_kwh": sum_column(ledger, "pv_curtailed_kwh"),
        "pv_export_kwh": sum_column(ledger, "pv_export_kwh"),
        "grid_to_bus_kwh": sum_column(ledger, "grid_to_bus_kwh"),
        "grid_to_bess_kwh": sum_column(ledger, "grid_to_bess_kwh"),
        "grid_import_kwh": sum_column(ledger, "grid_import_kwh"),
        "bess_to_bus_kwh": sum_column(ledger, "bess_to_bus_kwh"),
        "bess_charge_kwh": first_number(
            sum_column(ledger, "bess_charge_kwh"), sum_column(bess, "bess_charge_kwh")
        ),
        "bess_discharge_kwh": first_number(
            sum_column(ledger, "bess_discharge_kwh"), sum_column(bess, "bess_discharge_kwh")
        ),
        "bus_charging_total_kwh": sum_column(ledger, "bus_charging_total_kwh"),
        "fuel_consumption_l": sum_column(fuel, "fuel_consumption_l"),
        "fuel_cost_jpy": first_number(
            sum_column(fuel, "fuel_cost_jpy"),
            graph_kpi.get("fuel_cost_jpy"),
            summary.get("fuel_cost_jpy"),
            cost_detail.get("fuel_cost"),
        ),
        "grid_purchase_cost_jpy": first_number(
            sum_column(cost, "grid_purchase_cost_jpy"),
            graph_kpi.get("grid_purchase_cost_jpy"),
            summary.get("grid_purchase_cost_jpy"),
            cost_detail.get("grid_purchase_cost"),
        ),
        "demand_charge_cost_jpy": first_number(
            graph_kpi.get("demand_charge_cost_jpy"),
            summary.get("demand_charge_cost_jpy"),
            cost_detail.get("demand_charge"),
        ),
        "gross_operating_cost_jpy": first_number(
            summary.get("gross_operating_cost_jpy"),
            graph_kpi.get("gross_operating_cost_jpy"),
            cost_detail.get("total_operating_cost"),
            cost_detail.get("total_cost"),
        ),
        "objective_value_jpy": first_number(
            summary.get("objective_value_jpy"), graph_kpi.get("objective_value_jpy")
        ),
        "grid_co2_kg": first_number(sum_column(co2, "grid_co2_kg"), graph_kpi.get("grid_co2_kg")),
        "ice_co2_kg": first_number(sum_column(co2, "ice_co2_kg"), graph_kpi.get("ice_co2_kg")),
        "total_co2_kg": first_number(sum_column(co2, "total_co2_kg"), graph_kpi.get("total_co2_kg")),
    }
    bess_soc_initial, bess_soc_final = first_last_numeric(bess, "bess_soc_kwh")
    if bess_soc_initial == 0.0 and bess_soc_final == 0.0 and not ledger.empty:
        bess_soc_initial, _ = first_last_numeric(ledger, "bess_soc_start_kwh")
        _, bess_soc_final = first_last_numeric(ledger, "bess_soc_end_kwh")
    charge_eff, discharge_eff = bess_efficiencies(run)
    metrics["bess_initial_soc_kwh"] = bess_soc_initial
    metrics["bess_final_soc_kwh"] = bess_soc_final
    metrics["bess_soc_delta_kwh"] = bess_soc_final - bess_soc_initial
    metrics["bess_net_flow_before_efficiency_kwh"] = (
        metrics["pv_to_bess_kwh"] + metrics["grid_to_bess_kwh"] - metrics["bess_to_bus_kwh"]
    )
    metrics["bess_net_flow_after_efficiency_kwh"] = (
        (metrics["pv_to_bess_kwh"] + metrics["grid_to_bess_kwh"]) * charge_eff
        - metrics["bess_to_bus_kwh"] / discharge_eff
    )
    metrics["bess_soc_balance_error_after_efficiency_kwh"] = (
        metrics["bess_soc_delta_kwh"] - metrics["bess_net_flow_after_efficiency_kwh"]
    )
    metrics["bess_charge_efficiency"] = charge_eff
    metrics["bess_discharge_efficiency"] = discharge_eff
    pv_generation = metrics["pv_generation_kwh"]
    if pv_generation > 0:
        metrics["pv_utilization_ratio"] = (
            metrics["pv_to_bus_kwh"] + metrics["pv_to_bess_kwh"]
        ) / pv_generation
        metrics["pv_curtailment_ratio"] = metrics["pv_curtailed_kwh"] / pv_generation
    else:
        metrics["pv_utilization_ratio"] = 0.0
        metrics["pv_curtailment_ratio"] = 0.0
    metrics["bess_soc_min_observed_kwh"] = min_column_or_zero(bess, "bess_soc_kwh")
    metrics["bess_soc_max_observed_kwh"] = max_column(bess, "bess_soc_kwh")
    metrics["bess_soc_lower_buffer_kwh"] = max_column(bess, "bess_soc_min_kwh")
    metrics["bess_soc_upper_buffer_kwh"] = max_column(bess, "bess_soc_max_kwh")
    return metrics


def min_column_or_zero(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).min())


def metric_source(metric: str) -> str:
    if metric in {
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "pv_export_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "grid_import_kwh",
        "bess_to_bus_kwh",
        "bess_charge_kwh",
        "bess_discharge_kwh",
        "bess_initial_soc_kwh",
        "bess_final_soc_kwh",
        "bess_soc_delta_kwh",
        "bess_net_flow_after_efficiency_kwh",
        "bess_soc_balance_error_after_efficiency_kwh",
        "bus_charging_total_kwh",
    }:
        return "graph/energy_flow_ledger.csv"
    if metric in {"fuel_consumption_l", "fuel_cost_jpy"}:
        return "graph/fuel_timeseries.csv"
    if metric in {"grid_purchase_cost_jpy"}:
        return "graph/cost_timeseries.csv"
    if metric in {"demand_charge_cost_jpy"}:
        return "summary.json; cost_breakdown_detail.csv"
    if metric in {"gross_operating_cost_jpy", "objective_value_jpy"}:
        return "summary.json"
    if metric in {"grid_co2_kg", "ice_co2_kg", "total_co2_kg"}:
        return "graph/co2_timeseries.csv"
    return "derived"


def metric_unit(metric: str) -> str:
    if metric.endswith("_kwh"):
        return "kWh"
    if metric.endswith("_jpy"):
        return "JPY"
    if metric.endswith("_kg"):
        return "kg"
    if metric.endswith("_l"):
        return "L"
    if metric.endswith("_ratio"):
        return "ratio"
    if metric.endswith("_efficiency"):
        return "ratio"
    return ""


def write_daily_summary(output_dir: Path, metrics: dict[str, float]) -> None:
    ordered_metrics = [
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "pv_export_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "grid_import_kwh",
        "bess_to_bus_kwh",
        "bess_charge_kwh",
        "bess_discharge_kwh",
        "bess_initial_soc_kwh",
        "bess_final_soc_kwh",
        "bess_soc_delta_kwh",
        "bess_net_flow_after_efficiency_kwh",
        "bess_soc_balance_error_after_efficiency_kwh",
        "bus_charging_total_kwh",
        "fuel_consumption_l",
        "fuel_cost_jpy",
        "grid_purchase_cost_jpy",
        "demand_charge_cost_jpy",
        "gross_operating_cost_jpy",
        "objective_value_jpy",
        "grid_co2_kg",
        "ice_co2_kg",
        "total_co2_kg",
    ]
    rows = [
        {
            "metric": metric,
            "value": metrics.get(metric, 0.0),
            "unit": metric_unit(metric),
            "source": metric_source(metric),
        }
        for metric in ordered_metrics
    ]
    pd.DataFrame(rows).to_csv(output_dir / "daily_energy_summary.csv", index=False)


def balance_checks(metrics: dict[str, float]) -> dict[str, float]:
    return {
        "pv_allocation_balance_error_kwh": metrics["pv_generation_kwh"]
        - metrics["pv_to_bus_kwh"]
        - metrics["pv_to_bess_kwh"]
        - metrics["pv_curtailed_kwh"]
        - metrics["pv_export_kwh"],
        "bus_charging_balance_error_kwh": metrics["bus_charging_total_kwh"]
        - metrics["grid_to_bus_kwh"]
        - metrics["pv_to_bus_kwh"]
        - metrics["bess_to_bus_kwh"],
        "bess_charge_balance_error_kwh": metrics["bess_charge_kwh"]
        - metrics["pv_to_bess_kwh"]
        - metrics["grid_to_bess_kwh"],
        "bess_discharge_balance_error_kwh": metrics["bess_discharge_kwh"]
        - metrics["bess_to_bus_kwh"],
    }


def reconciliation_notes(run: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    recon = run["reconciliation"]
    if not recon.empty and {"category", "status", "message"}.issubset(recon.columns):
        for _, row in recon.iterrows():
            if str(row["status"]) != "OK":
                notes.append(f"{row['category']}: {row['status']} - {row['message']}")
    log = run["rebuild_log"]
    for item in log.get("out_of_scope_remaining", []) or []:
        notes.append(f"out_of_scope_remaining: {item}")
    if not notes:
        notes.append("strict_reconciliation_after_rebuild.csv に非OK項目はありません。")
    return notes


def write_visualization_summary(
    output_dir: Path, run: dict[str, Any], metrics: dict[str, float]
) -> None:
    graph_kpi = run["graph_kpi"]
    summary = run["summary"]
    checks = balance_checks(metrics)
    warnings = [
        f"警告: {name} = {value:.6f} kWh が {BALANCE_TOLERANCE_KWH} kWh を超過"
        for name, value in checks.items()
        if abs(value) > BALANCE_TOLERANCE_KWH
    ]
    if not warnings:
        warnings.append("1e-3 kWhを超える帳尻誤差はありません。")

    lines = [
        f"# 可視化サマリ: {run_display_label(run)}",
        "",
        f"1. 表示対象日: `{run.get('display_date')}` `{run.get('weather')}`",
        f"2. 元run ID: `{run['run_id']}`",
        f"3. ソルバー状態: `{graph_kpi.get('solver_status') or summary.get('solver_status') or 'UNKNOWN'}`",
        f"4. 物理実行可能性: `{graph_kpi.get('physical_feasibility_status') or summary.get('solution_validity', {}).get('status_reason') or 'UNKNOWN'}`",
        "5. PV発電量と配分:",
        f"   - PV発電量 = {metrics['pv_generation_kwh']:,.6f} kWh",
        f"   - PV→バス = {metrics['pv_to_bus_kwh']:,.6f} kWh",
        f"   - PV→BESS = {metrics['pv_to_bess_kwh']:,.6f} kWh",
        f"   - PV出力抑制 = {metrics['pv_curtailed_kwh']:,.6f} kWh",
        f"   - PV売電 = {metrics['pv_export_kwh']:,.6f} kWh",
        f"6. 系統受電量 = {metrics['grid_import_kwh']:,.6f} kWh",
        "7. バス充電量と内訳:",
        f"   - バス充電合計 = {metrics['bus_charging_total_kwh']:,.6f} kWh",
        f"   - 系統→バス = {metrics['grid_to_bus_kwh']:,.6f} kWh",
        f"   - PV→バス = {metrics['pv_to_bus_kwh']:,.6f} kWh",
        f"   - BESS→バス = {metrics['bess_to_bus_kwh']:,.6f} kWh",
        "8. BESS充放電とSOC範囲:",
        f"   - 初期SOC = {metrics['bess_initial_soc_kwh']:,.6f} kWh",
        f"   - 最終SOC = {metrics['bess_final_soc_kwh']:,.6f} kWh",
        f"   - 1日SOC差分 = {metrics['bess_soc_delta_kwh']:,.6f} kWh",
        f"   - BESS充電 = {metrics['bess_charge_kwh']:,.6f} kWh",
        f"   - BESS放電 = {metrics['bess_discharge_kwh']:,.6f} kWh",
        f"   - 効率込みBESS収支残差 = {metrics['bess_soc_balance_error_after_efficiency_kwh']:,.9f} kWh",
        f"   - 観測SOC範囲 = {metrics['bess_soc_min_observed_kwh']:,.6f} から {metrics['bess_soc_max_observed_kwh']:,.6f} kWh",
        f"   - SOC下限/上限 = {metrics['bess_soc_lower_buffer_kwh']:,.6f} / {metrics['bess_soc_upper_buffer_kwh']:,.6f} kWh",
        f"9. PV出力抑制量 = {metrics['pv_curtailed_kwh']:,.6f} kWh",
        f"   - PV出力抑制率 = {metrics['pv_curtailment_ratio'] * 100:.6f} %",
        f"   - PV利用率 = {metrics['pv_utilization_ratio'] * 100:.6f} %",
        f"10. 実運用費用 = {metrics['gross_operating_cost_jpy']:,.6f} JPY",
        f"11. 目的関数値 = {metrics['objective_value_jpy']:,.6f} JPY",
        "12. 残存問題:",
    ]
    lines.extend(f"   - {note}" for note in reconciliation_notes(run))
    lines.extend(["", "## 帳尻確認"])
    lines.extend(f"- {name}: {value:.9f} kWh" for name, value in checks.items())
    lines.extend(["", "## 警告"])
    lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## 再生成範囲",
            f"- 再最適化なし: `{run['rebuild_log'].get('no_reoptimization_performed', 'UNKNOWN')}`",
            f"- ソルバー再実行: `{run['rebuild_log'].get('solver_rerun', 'UNKNOWN')}`",
            f"- シミュレーション再実行: `{run['rebuild_log'].get('simulation_rerun', 'UNKNOWN')}`",
            f"- 車両割当再生成: `{run['rebuild_log'].get('vehicle_assignment_regenerated', 'UNKNOWN')}`",
        ]
    )
    (output_dir / "visualization_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def teacher_focus_rows(run: dict[str, Any], metrics: dict[str, float], ledger: pd.DataFrame) -> list[dict[str, Any]]:
    residuals = add_power_residuals(ledger)
    def max_abs(col: str) -> float:
        return float(pd.to_numeric(residuals[col], errors="coerce").fillna(0.0).abs().max())

    max_residuals = {
        "PV配分残差最大": max_abs("pv_allocation_residual_kwh"),
        "バス充電残差最大": max_abs("bus_charging_residual_kwh"),
        "系統受電残差最大": max_abs("grid_import_residual_kwh"),
        "BESS充電残差最大": max_abs("bess_charge_residual_kwh"),
    }
    base = {
        "run_id": run["run_id"],
        "display_date": run.get("display_date", ""),
        "weather": run.get("weather", ""),
        "scenario_label": run_display_label(run),
    }
    rows = [
        ("PV発電量", metrics["pv_generation_kwh"], "kWh", "PV総量"),
        ("PV→バス", metrics["pv_to_bus_kwh"], "kWh", "PVの直接利用"),
        ("PV→BESS", metrics["pv_to_bess_kwh"], "kWh", "PVから蓄電池への充電"),
        ("PV出力抑制", metrics["pv_curtailed_kwh"], "kWh", "PV発電の未利用分"),
        ("系統受電", metrics["grid_import_kwh"], "kWh", "系統から購入した電力量"),
        ("バス充電合計", metrics["bus_charging_total_kwh"], "kWh", "系統/PV/BESSからバスへの合計"),
        ("BESS初期SOC", metrics["bess_initial_soc_kwh"], "kWh", "1日の開始SOC"),
        ("BESS最終SOC", metrics["bess_final_soc_kwh"], "kWh", "1日の終了SOC"),
        ("BESS SOC差分", metrics["bess_soc_delta_kwh"], "kWh", "最終SOC - 初期SOC"),
        ("BESS効率込み収支残差", metrics["bess_soc_balance_error_after_efficiency_kwh"], "kWh", "SOC差分と充放電の照合"),
        ("燃料使用量", metrics["fuel_consumption_l"], "L", "ガソリン車燃料台帳"),
    ]
    rows.extend((name, value, "kWh", "時系列帳尻の最大絶対残差") for name, value in max_residuals.items())
    return [
        {**base, "metric": metric, "value": value, "unit": unit, "note": note}
        for metric, value, unit, note in rows
    ]


def write_teacher_focus_summary(
    output_dir: Path,
    run: dict[str, Any],
    metrics: dict[str, float],
    ledger: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = teacher_focus_rows(run, metrics, ledger)
    pd.DataFrame(rows).to_csv(output_dir / "00_teacher_focus_summary.csv", index=False)
    lines = [
        f"# 先生向け重点確認サマリ: {run_display_label(run)}",
        "",
        f"- 元run ID: `{run['run_id']}`",
        f"- BESS SOC差分: {metrics['bess_soc_delta_kwh']:,.6f} kWh",
        f"- PV→BESS: {metrics['pv_to_bess_kwh']:,.6f} kWh",
        f"- PV出力抑制: {metrics['pv_curtailed_kwh']:,.6f} kWh",
        f"- 系統受電: {metrics['grid_import_kwh']:,.6f} kWh",
        f"- バス充電合計: {metrics['bus_charging_total_kwh']:,.6f} kWh",
        f"- 燃料使用量: {metrics['fuel_consumption_l']:,.6f} L",
        "",
        "## 帳尻確認",
    ]
    for row in rows:
        if "残差" in str(row["metric"]):
            lines.append(f"- {row['metric']}: {float(row['value']):,.9f} {row['unit']}")
    (output_dir / "00_teacher_focus_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def plot_teacher_summary_table(rows: list[dict[str, Any]], output_base: Path) -> None:
    keep = [
        "PV発電量",
        "PV→バス",
        "PV→BESS",
        "PV出力抑制",
        "系統受電",
        "バス充電合計",
        "BESS初期SOC",
        "BESS最終SOC",
        "BESS SOC差分",
        "BESS効率込み収支残差",
        "燃料使用量",
    ]
    visible = [row for row in rows if row["metric"] in keep]
    cell_text = [[row["metric"], f"{float(row['value']):,.3f}", row["unit"], row["note"]] for row in visible]
    fig, ax = plt.subplots(figsize=TABLE_FIGSIZE)
    ax.axis("off")
    table = ax.table(
        cellText=cell_text,
        colLabels=["確認項目", "値", "単位", "意味"],
        cellLoc="left",
        colLoc="left",
        loc="center",
        colWidths=[0.22, 0.16, 0.08, 0.54],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(13)
    table.scale(1.0, 1.55)
    for (row_idx, _col_idx), cell in table.get_celld().items():
        if row_idx == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#e8eef7")
        else:
            cell.set_facecolor("#ffffff" if row_idx % 2 else "#f7f7f7")
    ax.set_title("先生向け重点確認表", fontsize=22, pad=18)
    finish_figure(fig, output_base)


def plot_teacher_focus_dashboard(
    run: dict[str, Any],
    ledger: pd.DataFrame,
    bess_df: pd.DataFrame,
    metrics: dict[str, float],
    output_base: Path,
) -> None:
    ledger = add_power_residuals(ledger)
    bess = ensure_columns(
        bess_df,
        ["pv_to_bess_kwh", "grid_to_bess_kwh", "bess_to_bus_kwh", "bess_soc_kwh", "bess_soc_min_kwh", "bess_soc_max_kwh"],
    )
    x = time_axis(ledger)
    bx = time_axis(bess)
    fig, axes = plt.subplots(2, 2, figsize=(18.0, 11.2), constrained_layout=True)

    ax = axes[0, 0]
    ax.stackplot(
        x,
        ledger["pv_to_bus_kwh"],
        ledger["pv_to_bess_kwh"],
        ledger["pv_curtailed_kwh"],
        ledger["pv_export_kwh"],
        labels=["PV→バス", "PV→BESS", "PV出力抑制", "PV売電"],
        colors=["#2ca02c", "#8bc34a", "#d62728", "#17becf"],
        alpha=0.84,
    )
    ax.plot(x, ledger["pv_generation_kwh"], color="#111111", marker="o", linewidth=2.2, label="PV発電量")
    ax.set_title("PV発電量の行き先")
    ax.set_ylabel("kWh/時")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    set_time_xlim(ax, x)

    ax = axes[0, 1]
    ax.stackplot(
        x,
        ledger["grid_to_bus_kwh"],
        ledger["pv_to_bus_kwh"],
        ledger["bess_to_bus_kwh"],
        labels=["系統→バス", "PV→バス", "BESS→バス"],
        colors=["#4c78a8", "#2ca02c", "#9467bd"],
        alpha=0.84,
    )
    ax.plot(x, ledger["bus_charging_total_kwh"], color="#111111", marker="o", linewidth=2.2, label="バス充電合計")
    ax.plot(x, ledger["grid_import_kwh"], color="#1f77b4", linestyle="--", linewidth=2.0, label="系統受電")
    ax.set_title("バス充電需要と供給元")
    ax.set_ylabel("kWh/時")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    set_time_xlim(ax, x)

    ax = axes[1, 0]
    ax.bar(bx, bess["pv_to_bess_kwh"], width=0.026, color="#8bc34a", alpha=0.78, label="PV→BESS")
    ax.bar(bx, bess["grid_to_bess_kwh"], width=0.026, bottom=bess["pv_to_bess_kwh"], color="#9ecae9", alpha=0.78, label="系統→BESS")
    ax.bar(bx, -bess["bess_to_bus_kwh"], width=0.026, color="#9467bd", alpha=0.78, label="BESS→バス")
    ax.set_title("BESS充放電とSOC差分")
    ax.set_ylabel("充電+ / 放電- (kWh)")
    ax.grid(True, axis="y", alpha=0.25)
    ax_soc = ax.twinx()
    ax_soc.plot(bx, bess["bess_soc_kwh"], color="#ff7f0e", marker="o", linewidth=2.4, label="BESS SOC")
    ax_soc.plot(bx, bess["bess_soc_min_kwh"], color="#7f7f7f", linestyle="--", linewidth=1.8, label="SOC下限")
    ax_soc.plot(bx, bess["bess_soc_max_kwh"], color="#7f7f7f", linestyle=":", linewidth=1.8, label="SOC上限")
    ax_soc.set_ylabel("SOC (kWh)")
    set_time_xlim(ax, bx)
    ax.text(
        0.02,
        0.97,
        f"初期 {metrics['bess_initial_soc_kwh']:,.1f} → 最終 {metrics['bess_final_soc_kwh']:,.1f} kWh\n差分 {metrics['bess_soc_delta_kwh']:,.1f} kWh",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=14,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.86},
    )
    handles1, labels1 = ax.get_legend_handles_labels()
    handles2, labels2 = ax_soc.get_legend_handles_labels()
    ax.legend(handles1 + handles2, labels1 + labels2, loc="center left", bbox_to_anchor=(1.12, 0.5), fontsize=13, frameon=True)

    ax = axes[1, 1]
    residual_cols = [
        ("pv_allocation_residual_kwh", "PV配分残差"),
        ("bus_charging_residual_kwh", "バス充電残差"),
        ("grid_import_residual_kwh", "系統受電残差"),
        ("bess_charge_residual_kwh", "BESS充電残差"),
    ]
    for col, label in residual_cols:
        ax.plot(x, ledger[col], marker="o", linewidth=2.0, label=label)
    ax.axhline(BALANCE_TOLERANCE_KWH, color="#d62728", linestyle="--", linewidth=1.4, label="許容誤差 ±1e-3 kWh")
    ax.axhline(-BALANCE_TOLERANCE_KWH, color="#d62728", linestyle="--", linewidth=1.4)
    ax.axhline(0.0, color="#111111", linewidth=1.0)
    ax.set_title("電力需給帳尻の残差")
    ax.set_ylabel("残差 (kWh)")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    set_time_xlim(ax, x)

    for axis in axes.ravel():
        axis.set_xlabel("時刻")
        format_time_axis(axis)
    fig.suptitle(f"電力需給・BESS・PV出力抑制の重点確認（{run_display_label(run)}）", y=1.02)
    finish_figure(fig, output_base)


def plot_run(run: dict[str, Any], output_dir: Path) -> dict[str, float]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = normalize_curtailment(run["ledger"])
    ledger = ensure_columns(
        ledger,
        [
            "grid_import_kwh",
            "grid_to_bus_kwh",
            "grid_to_bess_kwh",
            "bus_charging_total_kwh",
            "pv_to_bus_kwh",
            "bess_to_bus_kwh",
            "pv_generation_kwh",
            "pv_to_bess_kwh",
            "pv_curtailed_kwh",
            "pv_export_kwh",
            "bess_charge_kwh",
            "bess_discharge_kwh",
        ],
    )
    metrics = compute_daily_metrics({**run, "ledger": ledger})
    curtailment_annotation = (
        f"PV出力抑制: {metrics['pv_curtailed_kwh']:,.3f} kWh\n"
        f"出力抑制率: {metrics['pv_curtailment_ratio'] * 100:.3f}%"
    )
    teacher_rows = write_teacher_focus_summary(output_dir, run, metrics, ledger)
    plot_teacher_summary_table(teacher_rows, output_dir / "00_teacher_focus_summary_table")
    plot_teacher_focus_dashboard(run, ledger, run["bess"], metrics, output_dir / "00_teacher_focus_power_balance_dashboard")

    plot_lines(
        ledger,
        ["grid_import_kwh", "grid_to_bus_kwh", "grid_to_bess_kwh"],
        titled(run, "系統受電量の時系列"),
        "時間帯別エネルギー (kWh)",
        output_dir / "01_grid_import_timeseries",
    )
    plot_lines(
        ledger,
        ["bus_charging_total_kwh", "grid_to_bus_kwh", "pv_to_bus_kwh", "bess_to_bus_kwh"],
        titled(run, "バス充電量と電源内訳の時系列"),
        "時間帯別エネルギー (kWh)",
        output_dir / "02_bus_charging_sources_timeseries",
    )
    plot_stacked_area(
        ledger,
        ["grid_to_bus_kwh", "pv_to_bus_kwh", "bess_to_bus_kwh"],
        "bus_charging_total_kwh",
        titled(run, "バス充電量の電源構成"),
        "時間帯別エネルギー (kWh)",
        output_dir / "02b_bus_charging_sources_stacked",
    )
    plot_lines(
        ledger,
        [
            "pv_generation_kwh",
            "pv_to_bus_kwh",
            "pv_to_bess_kwh",
            "pv_curtailed_kwh",
            "pv_export_kwh",
        ],
        titled(run, "PV発電量と配分先の時系列"),
        "時間帯別エネルギー (kWh)",
        output_dir / "03_pv_generation_allocation_timeseries",
        annotate=curtailment_annotation,
    )
    plot_stacked_area(
        ledger,
        ["pv_to_bus_kwh", "pv_to_bess_kwh", "pv_curtailed_kwh", "pv_export_kwh"],
        "pv_generation_kwh",
        titled(run, "PV発電量の配分先（積み上げ）"),
        "時間帯別エネルギー (kWh)",
        output_dir / "04_pv_allocation_stacked_area",
        annotate=curtailment_annotation,
    )
    plot_daily_bar(
        {
            "pv_to_bus_kwh": metrics["pv_to_bus_kwh"],
            "pv_to_bess_kwh": metrics["pv_to_bess_kwh"],
            "pv_curtailed_kwh": metrics["pv_curtailed_kwh"],
            "pv_export_kwh": metrics["pv_export_kwh"],
        },
        titled(run, "PV発電量の日合計配分"),
        "日合計エネルギー (kWh)",
        output_dir / "04b_pv_daily_allocation",
    )
    plot_bess_flow_soc(run["bess"], output_dir / "05_bess_flow_soc_timeseries", titled(run, "BESS充放電とSOC時系列"))
    plot_daily_bar(
        {
            "pv_generation_kwh": metrics["pv_generation_kwh"],
            "pv_to_bus_kwh": metrics["pv_to_bus_kwh"],
            "pv_to_bess_kwh": metrics["pv_to_bess_kwh"],
            "pv_curtailed_kwh": metrics["pv_curtailed_kwh"],
            "grid_to_bus_kwh": metrics["grid_to_bus_kwh"],
            "grid_to_bess_kwh": metrics["grid_to_bess_kwh"],
            "bess_to_bus_kwh": metrics["bess_to_bus_kwh"],
            "bus_charging_total_kwh": metrics["bus_charging_total_kwh"],
            "grid_import_kwh": metrics["grid_import_kwh"],
        },
        titled(run, "電力フローの日合計"),
        "日合計エネルギー (kWh)",
        output_dir / "06_energy_flow_daily_totals",
    )
    plot_lines(
        run["cost"],
        ["grid_purchase_cost_jpy", "demand_charge_cost_jpy", "fuel_cost_jpy", "co2_cost_jpy"],
        titled(run, "費用の時系列"),
        "時間帯別費用 (JPY)",
        output_dir / "07_cost_timeseries",
    )
    plot_lines(
        run["co2"],
        ["grid_co2_kg", "ice_co2_kg", "total_co2_kg"],
        titled(run, "CO2排出量の時系列"),
        "時間帯別CO2 (kg)",
        output_dir / "08_co2_timeseries",
    )
    plot_lines(
        run["fuel"],
        ["fuel_consumption_l", "fuel_cost_jpy", "refuel_l"],
        titled(run, "燃料使用量・燃料費・給油量の時系列"),
        "時間帯別の燃料量または費用",
        output_dir / "09_fuel_timeseries",
    )
    vehicle_agg = aggregate_vehicle_sources(run["vehicle"])
    plot_lines(
        vehicle_agg,
        ["grid_to_vehicle_kwh", "pv_to_vehicle_kwh", "bess_to_vehicle_kwh", "total_charge_kwh"],
        titled(run, "車両別充電元配分の時系列"),
        "時間帯別エネルギー (kWh)",
        output_dir / "10_vehicle_charging_source_timeseries",
    )

    write_daily_summary(output_dir, metrics)
    write_visualization_summary(output_dir, run, metrics)
    return metrics


def plot_grouped_bar(
    rows: list[dict[str, Any]],
    metrics: list[str],
    title: str,
    ylabel: str,
    output_base: Path,
) -> None:
    df = pd.DataFrame(rows)
    x = range(len(df))
    width = 0.8 / max(len(metrics), 1)
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    for i, metric in enumerate(metrics):
        offsets = [pos - 0.4 + width / 2 + i * width for pos in x]
        values = [float(value) for value in df[metric]]
        bars = ax.bar(offsets, values, width=width, label=label_for(metric), color=color_for(metric))
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                max(value, 0.0),
                f"{value:,.1f}",
                ha="center",
                va="bottom",
                fontsize=12,
                rotation=90,
            )
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(list(x))
    label_col = "scenario_label" if "scenario_label" in df.columns else "run"
    ax.set_xticklabels(df[label_col], rotation=15, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    place_legend(ax)
    finish_figure(fig, output_base)


def plot_grid_import_comparison(runs: list[dict[str, Any]], output_base: Path) -> None:
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    for run in runs:
        ledger = ensure_columns(normalize_curtailment(run["ledger"]), ["grid_import_kwh"])
        ax.plot(
            time_axis(ledger),
            ledger["grid_import_kwh"],
            marker="o",
            linewidth=1.8,
            label=run_display_label(run),
        )
    ax.set_title("系統受電量のrun間比較")
    ax.set_xlabel("時刻")
    ax.set_ylabel("時間帯別エネルギー (kWh)")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    format_time_axis(ax)
    finish_figure(fig, output_base)


def plot_total_cost_comparison(rows: list[dict[str, Any]], output_base: Path) -> None:
    metrics = [
        "gross_operating_cost_jpy",
        "objective_value_jpy",
        "grid_purchase_cost_jpy",
        "demand_charge_cost_jpy",
        "fuel_cost_jpy",
        "co2_cost_jpy",
    ]
    df = pd.DataFrame(rows)
    if "co2_cost_jpy" not in df.columns:
        df["co2_cost_jpy"] = 0.0
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    x = range(len(metrics))
    width = 0.8 / max(len(df), 1)
    for i, (_, row) in enumerate(df.iterrows()):
        offsets = [pos - 0.4 + width / 2 + i * width for pos in x]
        values = [float(row.get(metric, 0.0)) for metric in metrics]
        ax.bar(offsets, values, width=width, label=row.get("scenario_label", row["run"]))
    ax.set_title("総費用と目的関数値のrun間比較")
    ax.set_ylabel("費用 (JPY)")
    ax.set_xticks(list(x))
    ax.set_xticklabels([label_for(metric) for metric in metrics], rotation=25, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    place_legend(ax)
    finish_figure(fig, output_base)


def comparison_row(run: dict[str, Any], metrics: dict[str, float]) -> dict[str, Any]:
    graph_kpi = run["graph_kpi"]
    summary = run["summary"]
    cost_detail = run["cost_detail_values"]
    return {
        "run": run["run_id"],
        "scenario_label": run_display_label(run),
        "simulation_service_date": run.get("display_date") or "UNKNOWN",
        "weather": run.get("weather") or "UNKNOWN",
        "pv_generation_kwh": metrics["pv_generation_kwh"],
        "pv_to_bus_kwh": metrics["pv_to_bus_kwh"],
        "pv_to_bess_kwh": metrics["pv_to_bess_kwh"],
        "pv_curtailed_kwh": metrics["pv_curtailed_kwh"],
        "pv_export_kwh": metrics["pv_export_kwh"],
        "pv_utilization_ratio": metrics["pv_utilization_ratio"],
        "pv_curtailment_ratio": metrics["pv_curtailment_ratio"],
        "grid_import_kwh": metrics["grid_import_kwh"],
        "grid_to_bus_kwh": metrics["grid_to_bus_kwh"],
        "bess_to_bus_kwh": metrics["bess_to_bus_kwh"],
        "bess_charge_kwh": metrics["bess_charge_kwh"],
        "bess_discharge_kwh": metrics["bess_discharge_kwh"],
        "bus_charging_total_kwh": metrics["bus_charging_total_kwh"],
        "gross_operating_cost_jpy": metrics["gross_operating_cost_jpy"],
        "objective_value_jpy": metrics["objective_value_jpy"],
        "total_co2_kg": metrics["total_co2_kg"],
        "fuel_consumption_l": metrics["fuel_consumption_l"],
        "bess_initial_soc_kwh": metrics["bess_initial_soc_kwh"],
        "bess_final_soc_kwh": metrics["bess_final_soc_kwh"],
        "bess_soc_delta_kwh": metrics["bess_soc_delta_kwh"],
        "bess_soc_balance_error_after_efficiency_kwh": metrics["bess_soc_balance_error_after_efficiency_kwh"],
        "solver_status": graph_kpi.get("solver_status") or summary.get("solver_status") or "UNKNOWN",
        "physical_feasibility_status": graph_kpi.get("physical_feasibility_status")
        or summary.get("solution_validity", {}).get("status_reason")
        or "UNKNOWN",
        "grid_purchase_cost_jpy": metrics["grid_purchase_cost_jpy"],
        "demand_charge_cost_jpy": metrics["demand_charge_cost_jpy"],
        "fuel_cost_jpy": metrics["fuel_cost_jpy"],
        "co2_cost_jpy": first_number(
            summary.get("co2_cost_jpy"), graph_kpi.get("co2_cost_jpy"), cost_detail.get("co2_cost")
        ),
    }


def write_comparison_report(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# run間比較レポート", ""]
    for row in rows:
        lines.extend(
            [
                f"## {row['scenario_label']}",
                f"- 元run ID: {row['run']}",
                f"- 対象日: {row['simulation_service_date']} {row['weather']}",
                f"- PV出力抑制量 = {row['pv_curtailed_kwh']:,.6f} kWh",
                f"- PV出力抑制率 = {row['pv_curtailment_ratio'] * 100:.6f} %",
                f"- PV利用率 = {row['pv_utilization_ratio'] * 100:.6f} %",
                f"- 系統受電量 = {row['grid_import_kwh']:,.6f} kWh",
                f"- バス充電合計 = {row['bus_charging_total_kwh']:,.6f} kWh",
                f"- BESS SOC差分 = {row['bess_soc_delta_kwh']:,.6f} kWh",
                f"- 実運用費用 = {row['gross_operating_cost_jpy']:,.6f} JPY",
                f"- 目的関数値 = {row['objective_value_jpy']:,.6f} JPY",
                f"- ソルバー状態: {row['solver_status']}",
                f"- 物理実行可能性: {row['physical_feasibility_status']}",
                "",
            ]
        )
    (output_dir / "comparison_report.md").write_text("\n".join(lines), encoding="utf-8")


def plot_comparison(
    runs: list[dict[str, Any]], metrics_by_run: dict[str, dict[str, float]], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [comparison_row(run, metrics_by_run[run["run_id"]]) for run in runs]

    summary_columns = [
        "run",
        "scenario_label",
        "simulation_service_date",
        "weather",
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "pv_export_kwh",
        "pv_utilization_ratio",
        "pv_curtailment_ratio",
        "grid_import_kwh",
        "grid_to_bus_kwh",
        "bess_to_bus_kwh",
        "bess_charge_kwh",
        "bess_discharge_kwh",
        "bus_charging_total_kwh",
        "gross_operating_cost_jpy",
        "objective_value_jpy",
        "total_co2_kg",
        "fuel_consumption_l",
        "bess_initial_soc_kwh",
        "bess_final_soc_kwh",
        "bess_soc_delta_kwh",
        "bess_soc_balance_error_after_efficiency_kwh",
        "solver_status",
        "physical_feasibility_status",
    ]
    pd.DataFrame(rows)[summary_columns].to_csv(output_dir / "comparison_summary.csv", index=False)
    write_comparison_report(output_dir, rows)

    plot_grouped_bar(
        rows,
        ["grid_to_bus_kwh", "pv_to_bus_kwh", "bess_to_bus_kwh"],
        "バス充電元の日合計比較",
        "日合計エネルギー (kWh)",
        output_dir / "01_daily_bus_charging_source_comparison",
    )
    plot_grouped_bar(
        rows,
        ["pv_to_bus_kwh", "pv_to_bess_kwh", "pv_curtailed_kwh", "pv_export_kwh"],
        "PV発電量配分の日合計比較",
        "日合計エネルギー (kWh)",
        output_dir / "02_daily_pv_allocation_comparison",
    )
    plot_grid_import_comparison(runs, output_dir / "03_grid_import_comparison")
    plot_grouped_bar(
        rows,
        ["pv_to_bess_kwh", "bess_to_bus_kwh", "bess_charge_kwh", "bess_discharge_kwh"],
        "BESS利用量の日合計比較",
        "日合計エネルギー (kWh)",
        output_dir / "04_bess_utilization_comparison",
    )
    plot_total_cost_comparison(rows, output_dir / "05_total_cost_comparison")


def main() -> int:
    args = parse_args()
    runs: list[dict[str, Any]] = []
    metrics_by_run: dict[str, dict[str, float]] = {}
    for run_id in args.run_ids:
        run_dir = args.input_root / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        run = load_run(run_dir)
        runs.append(run)
        metrics_by_run[run_id] = plot_run(run, args.output_root / run_id)
    if len(runs) >= 2:
        plot_comparison(runs, metrics_by_run, args.output_root / "comparison")
    print(
        json.dumps(
            {
                "input_root": str(args.input_root),
                "output_root": str(args.output_root),
                "runs": args.run_ids,
                "generated_comparison": len(runs) >= 2,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
