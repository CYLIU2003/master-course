"""Plot June 6 power-balance and ICE fuel-operation consistency checks.

The script reads rebuilt reporting artifacts only. It does not rerun the solver,
simulation, or vehicle assignment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd


RUN_IDS = ["run_20260606_1559", "run_20260606_1624"]
TOLERANCE = 1e-3
DEFAULT_INPUT_ROOT = Path("output/2026-06-06/rebuilt_reporting_20260606")
DEFAULT_OUTPUT_ROOT = Path("output/visualization_data/2026-06-06/rebuilt_reporting_20260606")

RUN_DISPLAY_METADATA = {
    "run_20260606_1559": {"display_date": "2025/08/05", "weather": "晴", "label": "2025/08/05 晴"},
    "run_20260606_1624": {"display_date": "2025/08/10", "weather": "雨", "label": "2025/08/10 雨"},
}

PPT_FIGSIZE = (16.0, 9.0)
PPT_TALL_FIGSIZE = (16.0, 11.0)


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


def run_display_label(run: dict) -> str:
    return str(run.get("display_label") or display_metadata(str(run.get("run_id") or ""))["label"])


def titled(run: dict, title: str) -> str:
    return f"{title}（{run_display_label(run)}）"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot power balance and ICE fuel consistency checks for June 6 rebuilt reporting."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument("--run-ids", nargs="+", default=RUN_IDS)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def first_number(*values) -> float:
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if pd.notna(parsed):
            return parsed
    return 0.0


def first_last_numeric(df: pd.DataFrame, col: str) -> tuple[float, float]:
    if df.empty or col not in df.columns:
        return 0.0, 0.0
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    if values.empty:
        return 0.0, 0.0
    return float(values.iloc[0]), float(values.iloc[-1])


def bess_summary(run: dict) -> dict[str, float]:
    bess = run.get("bess", pd.DataFrame())
    ledger = run.get("ledger", pd.DataFrame())
    initial, final = first_last_numeric(bess, "bess_soc_kwh")
    if initial == 0.0 and final == 0.0 and not ledger.empty:
        initial, _ = first_last_numeric(ledger, "bess_soc_start_kwh")
        _, final = first_last_numeric(ledger, "bess_soc_end_kwh")
    conditions = run.get("simulation_conditions") or {}
    charge_eff = first_number(conditions.get("bess_charge_efficiency"), 0.95)
    discharge_eff = first_number(conditions.get("bess_discharge_efficiency"), 0.95)
    ledger = ensure_columns(
        ledger,
        ["pv_to_bess_kwh", "grid_to_bess_kwh", "bess_to_bus_kwh"],
    )
    pv_to_bess = float(ledger["pv_to_bess_kwh"].sum()) if not ledger.empty else 0.0
    grid_to_bess = float(ledger["grid_to_bess_kwh"].sum()) if not ledger.empty else 0.0
    bess_to_bus = float(ledger["bess_to_bus_kwh"].sum()) if not ledger.empty else 0.0
    after_efficiency = (pv_to_bess + grid_to_bess) * charge_eff - bess_to_bus / discharge_eff
    return {
        "bess_initial_soc_kwh": initial,
        "bess_final_soc_kwh": final,
        "bess_soc_delta_kwh": final - initial,
        "pv_to_bess_kwh": pv_to_bess,
        "grid_to_bess_kwh": grid_to_bess,
        "bess_to_bus_kwh": bess_to_bus,
        "bess_soc_balance_error_after_efficiency_kwh": (final - initial) - after_efficiency,
    }


def normalize_curtailment(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "pv_curtailed_kwh" not in out.columns:
        out["pv_curtailed_kwh"] = out.get("pv_curtailment_kwh", 0.0)
    return out


def to_local_naive_datetime(values) -> pd.Series:
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
    if "slot_start" in df.columns:
        return to_local_naive_datetime(df["slot_start"])
    if "date" in df.columns and "time" in df.columns:
        return to_local_naive_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    return pd.Series(range(len(df)), index=df.index)


def format_time_axis(ax: plt.Axes) -> None:
    try:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
        ax.figure.autofmt_xdate(rotation=25, ha="right")
    except (TypeError, ValueError):
        pass


def set_time_xlim(ax: plt.Axes, values) -> None:
    try:
        series = pd.Series(values).dropna()
        if not series.empty:
            ax.set_xlim(series.min(), series.max())
    except Exception:
        pass


def save_figure(fig: plt.Figure, output_base: Path) -> None:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_base.with_suffix(".png"), dpi=240, bbox_inches="tight")
    fig.savefig(output_base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def place_legend(ax: plt.Axes, handles=None, labels=None) -> None:
    if handles is None or labels is None:
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
    )


def load_run(input_root: Path, run_id: str) -> dict:
    run_dir = input_root / run_id
    graph = run_dir / "graph"
    meta = display_metadata(run_id)
    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "display_date": meta["display_date"],
        "weather": meta["weather"],
        "display_label": meta["label"],
        "ledger": normalize_curtailment(read_csv(graph / "energy_flow_ledger.csv")),
        "bess": read_csv(graph / "bess_timeseries.csv"),
        "fuel": read_csv(graph / "fuel_canonical_ledger.csv"),
        "fuel_ts": read_csv(graph / "fuel_timeseries.csv"),
        "timeline": read_csv(graph / "vehicle_timeline.csv"),
        "trip_assignment": read_csv(graph / "trip_assignment.csv"),
        "summary": read_json(run_dir / "summary.json"),
        "kpi": read_json(graph / "kpi_summary.json"),
        "rebuild_log": read_json(run_dir / "rebuild_reporting_log.json"),
        "simulation_conditions": read_json(run_dir / "simulation_conditions.json"),
    }


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
    df["bess_charge_residual_kwh"] = (
        df["bess_charge_kwh"] - df["pv_to_bess_kwh"] - df["grid_to_bess_kwh"]
    )
    df["bess_discharge_residual_kwh"] = df["bess_discharge_kwh"] - df["bess_to_bus_kwh"]
    return df


def plot_power_flow(run: dict, output_dir: Path) -> None:
    ledger = add_power_residuals(run["ledger"])
    bess = ensure_columns(
        run["bess"],
        ["pv_to_bess_kwh", "grid_to_bess_kwh", "bess_to_bus_kwh", "bess_soc_kwh", "bess_soc_min_kwh", "bess_soc_max_kwh"],
    )
    x = time_axis(ledger)
    fig, axes = plt.subplots(3, 1, figsize=PPT_TALL_FIGSIZE, sharex=True, constrained_layout=True)

    axes[0].stackplot(
        x,
        ledger["pv_to_bus_kwh"],
        ledger["pv_to_bess_kwh"],
        ledger["pv_curtailed_kwh"],
        ledger["pv_export_kwh"],
        labels=["PV→バス", "PV→BESS", "PV出力抑制", "PV売電"],
        colors=["#2ca02c", "#8bc34a", "#d62728", "#17becf"],
        alpha=0.82,
    )
    axes[0].plot(x, ledger["pv_generation_kwh"], color="#111111", marker="o", label="PV発電量")
    axes[0].set_title("PV発電量の行き先確認")
    axes[0].set_ylabel("時間帯別エネルギー (kWh)")
    place_legend(axes[0])
    axes[0].grid(True, alpha=0.25)
    set_time_xlim(axes[0], x)

    axes[1].stackplot(
        x,
        ledger["grid_to_bus_kwh"],
        ledger["pv_to_bus_kwh"],
        ledger["bess_to_bus_kwh"],
        labels=["系統→バス", "PV→バス", "BESS→バス"],
        colors=["#4c78a8", "#2ca02c", "#9467bd"],
        alpha=0.82,
    )
    axes[1].plot(x, ledger["bus_charging_total_kwh"], color="#111111", marker="o", label="バス充電合計")
    axes[1].plot(x, ledger["grid_import_kwh"], color="#1f77b4", linestyle="--", label="系統受電")
    axes[1].set_title("バス充電需要と供給元")
    axes[1].set_ylabel("時間帯別エネルギー (kWh)")
    place_legend(axes[1])
    axes[1].grid(True, alpha=0.25)
    set_time_xlim(axes[1], x)

    bx = time_axis(bess)
    axes[2].bar(bx, bess["pv_to_bess_kwh"], width=0.025, label="PV→BESS", color="#8bc34a", alpha=0.75)
    axes[2].bar(bx, bess["grid_to_bess_kwh"], width=0.025, bottom=bess["pv_to_bess_kwh"], label="系統→BESS", color="#9ecae9", alpha=0.75)
    axes[2].bar(bx, -bess["bess_to_bus_kwh"], width=0.025, label="BESS→バス", color="#9467bd", alpha=0.75)
    ax_soc = axes[2].twinx()
    ax_soc.plot(bx, bess["bess_soc_kwh"], color="#ff7f0e", marker="o", label="BESS SOC")
    ax_soc.plot(bx, bess["bess_soc_min_kwh"], color="#7f7f7f", linestyle="--", label="SOC下限")
    ax_soc.plot(bx, bess["bess_soc_max_kwh"], color="#7f7f7f", linestyle=":", label="SOC上限")
    axes[2].set_title("BESS充放電とSOC")
    axes[2].set_ylabel("充電+ / 放電- (kWh)")
    axes[2].set_xlabel("時刻")
    ax_soc.set_ylabel("SOC (kWh)")
    handles1, labels1 = axes[2].get_legend_handles_labels()
    handles2, labels2 = ax_soc.get_legend_handles_labels()
    place_legend(axes[2], handles1 + handles2, labels1 + labels2)
    axes[2].grid(True, alpha=0.25)
    set_time_xlim(axes[2], bx)
    format_time_axis(axes[2])
    summary = bess_summary(run)
    axes[2].text(
        0.02,
        0.97,
        f"BESS SOC差分: {summary['bess_soc_delta_kwh']:,.1f} kWh\nPV→BESS: {summary['pv_to_bess_kwh']:,.1f} kWh",
        transform=axes[2].transAxes,
        ha="left",
        va="top",
        fontsize=14,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.86},
    )
    fig.suptitle(f"電力需給帳尻確認（{run_display_label(run)}）", y=0.995)
    save_figure(fig, output_dir / "11_power_balance_flow_timeseries")


def plot_power_residuals(run: dict, output_dir: Path) -> dict[str, float]:
    ledger = add_power_residuals(run["ledger"])
    residuals = [
        "pv_allocation_residual_kwh",
        "bus_charging_residual_kwh",
        "grid_import_residual_kwh",
        "bess_charge_residual_kwh",
        "bess_discharge_residual_kwh",
    ]
    labels = {
        "pv_allocation_residual_kwh": "PV配分残差",
        "bus_charging_residual_kwh": "バス充電残差",
        "grid_import_residual_kwh": "系統受電残差",
        "bess_charge_residual_kwh": "BESS充電残差",
        "bess_discharge_residual_kwh": "BESS放電残差",
    }
    x = time_axis(ledger)
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    for col in residuals:
        ax.plot(x, ledger[col], marker="o", linewidth=1.8, label=labels[col])
    ax.axhline(TOLERANCE, color="#d62728", linestyle="--", linewidth=1.2, label="許容誤差 +/- 1e-3 kWh")
    ax.axhline(-TOLERANCE, color="#d62728", linestyle="--", linewidth=1.2)
    ax.axhline(0.0, color="#111111", linewidth=1.0)
    ax.set_title(titled(run, "電力帳尻残差の時系列"))
    ax.set_xlabel("時刻")
    ax.set_ylabel("残差 (kWh)")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    set_time_xlim(ax, x)
    format_time_axis(ax)
    save_figure(fig, output_dir / "12_power_balance_residuals_timeseries")
    return {col: float(ledger[col].abs().max()) for col in residuals}


def fuel_with_expected(fuel: pd.DataFrame) -> pd.DataFrame:
    cols = ["distance_km", "fuel_efficiency_km_per_l", "fuel_consumption_l", "fuel_cost_jpy"]
    df = ensure_columns(fuel, cols)
    df["timestamp"] = to_local_naive_datetime(df["timestamp"]) if "timestamp" in df.columns else pd.NaT
    df["expected_fuel_l"] = 0.0
    valid = df["fuel_efficiency_km_per_l"] > 0
    df.loc[valid, "expected_fuel_l"] = df.loc[valid, "distance_km"] / df.loc[valid, "fuel_efficiency_km_per_l"]
    df["fuel_residual_l"] = df["fuel_consumption_l"] - df["expected_fuel_l"]
    return df


def hourly_fuel(fuel: pd.DataFrame) -> pd.DataFrame:
    df = fuel_with_expected(fuel)
    if df.empty:
        return pd.DataFrame()
    df["hour"] = df["timestamp"].dt.floor("h")
    return (
        df.groupby("hour", as_index=False)
        .agg(
            distance_km=("distance_km", "sum"),
            fuel_consumption_l=("fuel_consumption_l", "sum"),
            expected_fuel_l=("expected_fuel_l", "sum"),
            trip_count=("trip_id", "nunique") if "trip_id" in df.columns else ("distance_km", "count"),
        )
        .rename(columns={"hour": "timestamp"})
    )


def plot_fuel_timeseries(run: dict, output_dir: Path) -> None:
    hourly = hourly_fuel(run["fuel"])
    if hourly.empty:
        return
    x = pd.to_datetime(hourly["timestamp"], errors="coerce")
    fig, ax1 = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    ax1.bar(x, hourly["distance_km"], width=0.025, alpha=0.65, color="#4c78a8", label="ガソリン車走行距離")
    ax1.set_ylabel("ガソリン車走行距離 (km/時)")
    ax1.set_xlabel("時刻")
    ax1.grid(True, axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, hourly["fuel_consumption_l"], color="#8c564b", marker="o", label="燃料使用量")
    ax2.plot(x, hourly["expected_fuel_l"], color="#ff7f0e", linestyle="--", marker="x", label="距離/燃費からの期待燃料量")
    ax2.set_ylabel("燃料量 (L/時)")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    place_legend(ax1, handles1 + handles2, labels1 + labels2)
    ax1.set_title(titled(run, "ガソリン車走行距離と燃料使用量"))
    set_time_xlim(ax1, x)
    format_time_axis(ax1)
    save_figure(fig, output_dir / "13_fuel_vs_ice_operation_timeseries")


def plot_fuel_scatter(run: dict, output_dir: Path) -> float:
    fuel = fuel_with_expected(run["fuel"])
    if fuel.empty:
        return 0.0
    max_value = max(float(fuel["expected_fuel_l"].max()), float(fuel["fuel_consumption_l"].max()), 1.0)
    fig, ax = plt.subplots(figsize=(10.5, 8.2), constrained_layout=True)
    ax.scatter(fuel["expected_fuel_l"], fuel["fuel_consumption_l"], alpha=0.55, color="#8c564b", edgecolor="none")
    ax.plot([0, max_value], [0, max_value], color="#111111", linestyle="--", label="y = x（一致線）")
    ax.set_title(titled(run, "燃料台帳の整合確認"))
    ax.set_xlabel("距離/燃費からの期待燃料量 (L)")
    ax.set_ylabel("記録された燃料使用量 (L)")
    ax.grid(True, alpha=0.25)
    place_legend(ax)
    save_figure(fig, output_dir / "14_fuel_distance_consistency_scatter")
    return float(fuel["fuel_residual_l"].abs().max())


def trip_assignment_ice_totals(df: pd.DataFrame) -> tuple[float, float, float, int]:
    if df.empty or "assigned_vehicle_type" not in df.columns:
        return 0.0, 0.0, 0.0, 0
    ice = df[df["assigned_vehicle_type"].astype(str).str.upper().eq("ICE")].copy()
    ice = ensure_columns(ice, ["distance_km", "deadhead_before_km", "deadhead_after_km"])
    service = float(ice["distance_km"].sum())
    deadhead = float(ice["deadhead_before_km"].sum() + ice["deadhead_after_km"].sum())
    return service, deadhead, service + deadhead, int(len(ice))


def timeline_ice_distance(df: pd.DataFrame) -> float:
    if df.empty or "vehicle_type" not in df.columns:
        return 0.0
    ice = df[df["vehicle_type"].astype(str).str.upper().eq("ICE")].copy()
    ice = ensure_columns(ice, ["distance_km"])
    return float(ice["distance_km"].sum())


def plot_fuel_daily_totals(run: dict, output_dir: Path) -> dict[str, float]:
    fuel = fuel_with_expected(run["fuel"])
    service, deadhead, trip_total, trip_count = trip_assignment_ice_totals(run["trip_assignment"])
    timeline_total = timeline_ice_distance(run["timeline"])
    fuel_distance = float(fuel["distance_km"].sum()) if not fuel.empty else 0.0
    fuel_l = float(fuel["fuel_consumption_l"].sum()) if not fuel.empty else 0.0
    expected_l = float(fuel["expected_fuel_l"].sum()) if not fuel.empty else 0.0
    fig, ax1 = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    distance_labels = ["燃料台帳距離", "運行サービス距離", "回送距離", "運行+回送距離", "タイムライン距離"]
    distance_values = [fuel_distance, service, deadhead, trip_total, timeline_total]
    ax1.bar(distance_labels, distance_values, color=["#4c78a8", "#2ca02c", "#9ecae9", "#1f77b4", "#9467bd"], alpha=0.8)
    ax1.set_ylabel("距離 (km)")
    ax1.tick_params(axis="x", rotation=25)
    ax1.grid(True, axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(["燃料台帳距離", "運行サービス距離"], [fuel_l, expected_l], color="#8c564b", marker="o", linewidth=0, label="燃料使用量 / 期待燃料量")
    ax2.set_ylabel("燃料量 (L)")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    if handles2:
        place_legend(ax1, handles1 + handles2, labels1 + labels2)
    ax1.set_title(titled(run, "ガソリン車の日合計距離と燃料量"))
    save_figure(fig, output_dir / "15_fuel_operation_daily_totals")
    return {
        "fuel_ledger_distance_km": fuel_distance,
        "trip_assignment_ice_service_km": service,
        "trip_assignment_ice_deadhead_km": deadhead,
        "trip_assignment_ice_total_km": trip_total,
        "timeline_ice_distance_km": timeline_total,
        "fuel_consumption_l": fuel_l,
        "expected_fuel_l": expected_l,
        "fuel_total_residual_l": fuel_l - expected_l,
        "fuel_distance_vs_trip_total_residual_km": fuel_distance - trip_total,
        "fuel_distance_vs_timeline_residual_km": fuel_distance - timeline_total,
        "ice_trip_count": trip_count,
    }


def write_run_summary(output_dir: Path, run: dict, power_max: dict[str, float], fuel_max_residual_l: float, fuel_summary: dict[str, float]) -> dict:
    bess = bess_summary(run)
    row = {
        "run": run["run_id"],
        "scenario_label": run_display_label(run),
        "display_date": run.get("display_date", ""),
        "weather": run.get("weather", ""),
        "solver_status": run["kpi"].get("solver_status") or run["summary"].get("solver_status") or "UNKNOWN",
        "physical_feasibility_status": run["kpi"].get("physical_feasibility_status") or "UNKNOWN",
        "no_reoptimization_performed": run["rebuild_log"].get("no_reoptimization_performed"),
        **bess,
        **power_max,
        **fuel_summary,
        "fuel_max_row_residual_l": fuel_max_residual_l,
    }
    pd.DataFrame([row]).to_csv(output_dir / "power_fuel_check_summary.csv", index=False)
    warnings = []
    for key, value in power_max.items():
        if value > TOLERANCE:
            warnings.append(f"{key} が {TOLERANCE} kWh を超過: {value:.9f}")
    if abs(fuel_summary["fuel_total_residual_l"]) > 1e-9 or fuel_max_residual_l > 1e-9:
        warnings.append("燃料使用量が距離/燃費からの期待値と1e-9 Lを超えて不一致です。")
    if abs(fuel_summary["fuel_distance_vs_trip_total_residual_km"]) > TOLERANCE:
        warnings.append("燃料台帳距離がtrip_assignmentのガソリン車サービス距離+回送距離と一致しません。")
    if not warnings:
        warnings.append("電力帳尻および燃料距離/燃費の確認で許容誤差を超える警告はありません。")
    lines = [
        f"# 電力帳尻・燃料整合確認: {run_display_label(run)}",
        "",
        f"- 元run ID: `{run['run_id']}`",
        f"- ソルバー状態: `{row['solver_status']}`",
        f"- 物理実行可能性: `{row['physical_feasibility_status']}`",
        f"- 再最適化なし: `{row['no_reoptimization_performed']}`",
        f"- BESS SOC差分: {bess['bess_soc_delta_kwh']:,.6f} kWh",
        f"- PV→BESS: {bess['pv_to_bess_kwh']:,.6f} kWh",
        f"- BESS効率込みSOC収支残差: {bess['bess_soc_balance_error_after_efficiency_kwh']:,.9f} kWh",
        "",
        "## 電力帳尻の最大絶対残差",
    ]
    lines.extend(f"- {key}: {value:.9f} kWh" for key, value in power_max.items())
    lines.extend(
        [
            "",
            "## 燃料使用量とガソリン車運行量",
            f"- 燃料台帳距離: {fuel_summary['fuel_ledger_distance_km']:,.6f} km",
            f"- trip_assignmentのガソリン車サービス距離: {fuel_summary['trip_assignment_ice_service_km']:,.6f} km",
            f"- trip_assignmentのガソリン車回送距離: {fuel_summary['trip_assignment_ice_deadhead_km']:,.6f} km",
            f"- trip_assignmentのガソリン車合計距離: {fuel_summary['trip_assignment_ice_total_km']:,.6f} km",
            f"- vehicle_timelineのガソリン車距離: {fuel_summary['timeline_ice_distance_km']:,.6f} km",
            f"- 燃料使用量: {fuel_summary['fuel_consumption_l']:,.6f} L",
            f"- 距離/燃費からの期待燃料量: {fuel_summary['expected_fuel_l']:,.6f} L",
            f"- 燃料量残差: {fuel_summary['fuel_total_residual_l']:.12f} L",
            f"- 燃料台帳距離 - trip_assignment合計距離: {fuel_summary['fuel_distance_vs_trip_total_residual_km']:.9f} km",
            f"- 燃料台帳距離 - vehicle_timeline距離: {fuel_summary['fuel_distance_vs_timeline_residual_km']:.9f} km",
            "",
            "## 警告",
        ]
    )
    lines.extend(f"- {warning}" for warning in warnings)
    (output_dir / "power_fuel_check_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return row


def process_run(run: dict, output_root: Path) -> dict:
    output_dir = output_root / run["run_id"] / "power_fuel_checks"
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_power_flow(run, output_dir)
    power_max = plot_power_residuals(run, output_dir)
    plot_fuel_timeseries(run, output_dir)
    fuel_max_residual_l = plot_fuel_scatter(run, output_dir)
    fuel_summary = plot_fuel_daily_totals(run, output_dir)
    return write_run_summary(output_dir, run, power_max, fuel_max_residual_l, fuel_summary)


def plot_comparison(rows: list[dict], output_root: Path) -> None:
    output_dir = output_root / "comparison"
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(output_dir / "power_fuel_check_comparison.csv", index=False)

    residual_cols = [
        "pv_allocation_residual_kwh",
        "bus_charging_residual_kwh",
        "grid_import_residual_kwh",
        "bess_charge_residual_kwh",
        "bess_discharge_residual_kwh",
    ]
    fig, ax = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    width = 0.8 / len(residual_cols)
    x = range(len(df))
    for i, col in enumerate(residual_cols):
        label = {
            "pv_allocation_residual_kwh": "PV配分残差",
            "bus_charging_residual_kwh": "バス充電残差",
            "grid_import_residual_kwh": "系統受電残差",
            "bess_charge_residual_kwh": "BESS充電残差",
            "bess_discharge_residual_kwh": "BESS放電残差",
        }[col]
        ax.bar([pos - 0.4 + width / 2 + i * width for pos in x], df[col], width=width, label=label)
    ax.axhline(TOLERANCE, color="#d62728", linestyle="--", label="許容誤差 1e-3 kWh")
    ax.set_xticks(list(x))
    ax.set_xticklabels(df.get("scenario_label", df["run"]), rotation=15, ha="right")
    ax.set_ylabel("最大絶対残差 (kWh)")
    ax.set_title("電力帳尻残差のrun間比較")
    ax.grid(True, axis="y", alpha=0.25)
    place_legend(ax)
    save_figure(fig, output_dir / "06_power_balance_residual_comparison")

    fig, ax1 = plt.subplots(figsize=PPT_FIGSIZE, constrained_layout=True)
    xlabels = list(df.get("scenario_label", df["run"]))
    ax1.bar([x - 0.2 for x in range(len(df))], df["trip_assignment_ice_total_km"], width=0.4, label="trip_assignment ガソリン車合計距離", color="#4c78a8")
    ax1.bar([x + 0.2 for x in range(len(df))], df["fuel_ledger_distance_km"], width=0.4, label="燃料台帳距離", color="#2ca02c")
    ax1.set_ylabel("距離 (km)")
    ax2 = ax1.twinx()
    ax2.plot(range(len(df)), df["fuel_consumption_l"], color="#8c564b", marker="o", label="燃料使用量")
    ax2.plot(range(len(df)), df["expected_fuel_l"], color="#ff7f0e", marker="x", linestyle="--", label="期待燃料量")
    ax2.set_ylabel("燃料量 (L)")
    ax1.set_xticks(list(range(len(df))))
    ax1.set_xticklabels(xlabels, rotation=20, ha="right")
    ax1.set_title("ガソリン車運行距離と燃料使用量のrun間比較")
    ax1.grid(True, axis="y", alpha=0.25)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    place_legend(ax1, handles1 + handles2, labels1 + labels2)
    save_figure(fig, output_dir / "07_fuel_operation_consistency_comparison")


def main() -> int:
    args = parse_args()
    rows = []
    for run_id in args.run_ids:
        run = load_run(args.input_root, run_id)
        rows.append(process_run(run, args.output_root))
    if len(rows) >= 2:
        plot_comparison(rows, args.output_root)
    print(json.dumps({"runs": args.run_ids, "output_root": str(args.output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
