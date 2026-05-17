"""Analyze and visualize the two 2026-05-15 run outputs.

Generates:
  - a Japanese Markdown comparison report
  - a machine-readable JSON summary
  - Plotly HTML time-series dashboards for each run and their comparison

Defaults target:
  output/2026-05-15/run_20260515_1138
  output/2026-05-15/run_20260515_1407
  output/2026-05-15/analy
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.io import write_html


@dataclass(frozen=True)
class RunBundle:
    label: str
    path: Path
    summary: dict[str, Any]
    kpi: dict[str, Any]
    manifest: dict[str, Any]
    weather_forecast: dict[str, Any]
    weather_policy: dict[str, Any]
    flow: pd.DataFrame


@dataclass(frozen=True)
class SeriesGroup:
    title: str
    columns: tuple[str, ...]
    mode: str = "lines"


@dataclass(frozen=True)
class SeriesSpec:
    file_name: str
    title: str
    x_column_candidates: tuple[str, ...]
    groups: tuple[SeriesGroup, ...]
    x_label: str = "時刻"


@dataclass(frozen=True)
class DiscoveryResult:
    specs: tuple[SeriesSpec, ...]
    skipped_empty: tuple[str, ...]
    skipped_non_timeseries: tuple[str, ...]
    skipped_no_numeric: tuple[str, ...]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_timeseries(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={col: col.strip() for col in df.columns})
    return df


def load_run_bundle(run_dir: Path) -> RunBundle:
    summary = _load_json(run_dir / "summary.json")
    kpi = _load_json(run_dir / "graph" / "kpi_summary.json")
    manifest = _load_json(run_dir / "run_manifest.json")
    weather_forecast = _load_json(run_dir / "weather_proxy_forecast.json")
    weather_policy = _load_json(run_dir / "weather_operation_policy.json")
    flow = _load_timeseries(run_dir / "graph" / "depot_power_timeseries_5min.csv")
    return RunBundle(
        label=run_dir.name,
        path=run_dir,
        summary=summary,
        kpi=kpi,
        manifest=manifest,
        weather_forecast=weather_forecast,
        weather_policy=weather_policy,
        flow=flow,
    )


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _delta_pct(left: float | None, right: float | None) -> str:
    if left is None or right in (None, 0):
        return "-"
    return f"{((left - right) / right) * 100:+.2f}%"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _timestamp_peak(df: pd.DataFrame, column: str) -> str:
    if column not in df.columns or df.empty:
        return "-"
    idx = df[column].idxmax()
    if pd.isna(idx):
        return "-"
    return pd.Timestamp(df.loc[idx, "timestamp"]).strftime("%Y-%m-%d %H:%M")


def _flow_metric(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns or df.empty:
        return None
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.sum())


def _integrate_kw_series(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns or "slot_minutes" not in df.columns or df.empty:
        return None
    power = pd.to_numeric(df[column], errors="coerce")
    slot_minutes = pd.to_numeric(df["slot_minutes"], errors="coerce")
    if power.dropna().empty or slot_minutes.dropna().empty:
        return None
    hours = slot_minutes.fillna(0) / 60.0
    return float((power.fillna(0) * hours).sum())


def _parse_datetime_series(df: pd.DataFrame, candidates: tuple[str, ...]) -> tuple[str, pd.Series]:
    if "timestamp" in df.columns:
        series = pd.to_datetime(df["timestamp"], errors="coerce")
        return "timestamp", series
    for candidate in candidates:
        if candidate in df.columns:
            series = pd.to_datetime(df[candidate], errors="coerce")
            return candidate, series
    if {"date", "time"}.issubset(df.columns):
        series = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="coerce")
        return "timestamp", series
    raise ValueError("No datetime-like column found")


def _detect_time_candidates(columns: Iterable[str]) -> tuple[str, ...]:
    ordered_candidates = [
        "timestamp",
        "event_time",
        "start_time",
        "scheduled_departure",
        "actual_departure",
        "date",
    ]
    available = [col for col in ordered_candidates if col in set(columns)]
    return tuple(available)


def _chunk_columns(columns: list[str], size: int = 6) -> tuple[SeriesGroup, ...]:
    if not columns:
        return tuple()
    groups: list[SeriesGroup] = []
    for i in range(0, len(columns), size):
        chunk = tuple(columns[i : i + size])
        groups.append(SeriesGroup(f"series {i // size + 1}", chunk))
    return tuple(groups)


def _discover_timeseries_specs(runs: list[RunBundle]) -> DiscoveryResult:
    file_names: set[str] = set()
    for run in runs:
        graph_dir = run.path / "graph"
        if not graph_dir.exists():
            continue
        for file_path in graph_dir.glob("*.csv"):
            file_names.add(file_path.name)

    specs: list[SeriesSpec] = []
    skipped_empty: list[str] = []
    skipped_non_timeseries: list[str] = []
    skipped_no_numeric: list[str] = []

    for file_name in sorted(file_names):
        sample_path: Path | None = None
        for run in runs:
            candidate = run.path / "graph" / file_name
            if candidate.exists() and candidate.stat().st_size > 0:
                sample_path = candidate
                break
        if sample_path is None:
            skipped_empty.append(file_name)
            continue
        try:
            sample_df = pd.read_csv(sample_path, nrows=400)
        except Exception:
            skipped_non_timeseries.append(file_name)
            continue
        sample_df = sample_df.rename(columns={col: col.strip() for col in sample_df.columns})
        time_candidates = _detect_time_candidates(sample_df.columns)
        if not time_candidates:
            skipped_non_timeseries.append(file_name)
            continue
        x_candidates = tuple(col for col in time_candidates if col != "date")
        if not x_candidates and {"date", "time"}.issubset(sample_df.columns):
            x_candidates = ("timestamp",)
        elif not x_candidates:
            skipped_non_timeseries.append(file_name)
            continue

        numeric_cols = _numeric_columns(sample_df, exclude=set(x_candidates) | {"date", "time"})
        if not numeric_cols:
            skipped_no_numeric.append(file_name)
            continue
        groups = _chunk_columns(numeric_cols, size=6)
        title = file_name.replace(".csv", "")
        specs.append(
            SeriesSpec(
                file_name=file_name,
                title=title,
                x_column_candidates=x_candidates,
                groups=groups,
            )
        )

    return DiscoveryResult(
        specs=tuple(specs),
        skipped_empty=tuple(sorted(skipped_empty)),
        skipped_non_timeseries=tuple(sorted(skipped_non_timeseries)),
        skipped_no_numeric=tuple(sorted(skipped_no_numeric)),
    )


def _load_spec_frame(path: Path, spec: SeriesSpec) -> tuple[pd.DataFrame, str]:
    df = pd.read_csv(path)
    df = df.rename(columns={col: col.strip() for col in df.columns})
    x_column, parsed = _parse_datetime_series(df, spec.x_column_candidates)
    df[x_column] = parsed
    df = df.dropna(subset=[x_column]).sort_values(x_column).reset_index(drop=True)
    return df, x_column


def _numeric_columns(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    numeric_columns: list[str] = []
    for column in df.columns:
        if column in exclude:
            continue
        if pd.api.types.is_bool_dtype(df[column]):
            continue
        if pd.api.types.is_numeric_dtype(df[column]):
            numeric_columns.append(column)
    return numeric_columns


def _format_series_label(label: str, run_label: str) -> str:
    return f"{label} | {run_label}"


def _make_timeseries_figure(
    runs: list[RunBundle],
    spec: SeriesSpec,
    title: str,
) -> go.Figure | None:
    frames: list[tuple[RunBundle, pd.DataFrame, str]] = []
    for run in runs:
        path = run.path / "graph" / spec.file_name
        if not path.exists():
            continue
        try:
            frame, x_column = _load_spec_frame(path, spec)
        except Exception:
            continue
        if frame.empty:
            continue
        frames.append((run, frame, x_column))
    if not frames:
        return None

    fig = make_subplots(
        rows=len(spec.groups),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=[group.title for group in spec.groups],
    )
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    dash_styles = ["solid", "dash", "dot", "dashdot"]
    column_colors: dict[str, str] = {}
    color_index = 0

    for _, frame, x_column in frames:
        for column in _numeric_columns(frame, {x_column}):
            if column not in column_colors:
                column_colors[column] = palette[color_index % len(palette)]
                color_index += 1

    for run_index, (run, frame, x_column) in enumerate(frames):
        dash = dash_styles[run_index % len(dash_styles)]
        for row_index, group in enumerate(spec.groups, start=1):
            for column in group.columns:
                if column not in frame.columns:
                    continue
                y = pd.to_numeric(frame[column], errors="coerce")
                if y.dropna().empty:
                    continue
                trace_name = _format_series_label(column, run.label)
                fig.add_trace(
                    go.Scatter(
                        x=frame[x_column],
                        y=y,
                        mode=group.mode,
                        name=trace_name,
                        legendgroup=column,
                        line=dict(color=column_colors.get(column, palette[0]), dash=dash),
                        hovertemplate="%{x}<br>%{y:.3f}<extra>" + trace_name + "</extra>",
                    ),
                    row=row_index,
                    col=1,
                )

    fig.update_layout(
        title=title,
        height=max(480, 260 * len(spec.groups)),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.85)",
            tracegroupgap=6,
        ),
        margin=dict(l=60, r=280, t=100, b=60),
        template="plotly_white",
    )
    for row in range(1, len(spec.groups) + 1):
        fig.update_yaxes(title_text="値", row=row, col=1)
    fig.update_xaxes(title_text=spec.x_label, row=len(spec.groups), col=1)
    return fig


def _extract_metrics(run: RunBundle) -> dict[str, Any]:
    summary = run.summary
    kpi = run.kpi
    flow = run.flow
    forecast = run.weather_forecast
    policy = run.weather_policy
    peak_grid_idx = flow["grid_import_kw"].idxmax() if "grid_import_kw" in flow.columns and not flow.empty else None
    peak_charge_idx = flow["total_charge_kw"].idxmax() if "total_charge_kw" in flow.columns and not flow.empty else None
    peak_pv_idx = flow["pv_generation_kw"].idxmax() if "pv_generation_kw" in flow.columns and not flow.empty else None

    def _peak_time(idx: Any) -> str:
        if idx is None or pd.isna(idx):
            return "-"
        return pd.Timestamp(flow.loc[idx, "timestamp"]).strftime("%Y-%m-%d %H:%M")

    over_limit_hours = None
    if "contract_limit_exceeded" in flow.columns:
        exceeded = pd.to_numeric(flow["contract_limit_exceeded"], errors="coerce").fillna(0)
        over_limit_hours = float(exceeded.sum() * 5.0 / 60.0)

    return {
        "label": run.label,
        "scenario_id": summary.get("scenario_id"),
        "solver_status": summary.get("solver_status"),
        "objective_mode": summary.get("objective_mode"),
        "objective_value_jpy": summary.get("objective_value_jpy"),
        "total_cost_jpy": summary.get("total_cost_jpy"),
        "objective_is_actual_cost": summary.get("objective_is_actual_cost"),
        "supports_exact_milp": summary.get("supports_exact_milp"),
        "solve_time_seconds": summary.get("solve_time_seconds"),
        "trip_count_served": summary.get("trip_count_served"),
        "trip_count_unserved": summary.get("trip_count_unserved"),
        "vehicle_count_used": summary.get("vehicle_count_used"),
        "deadhead_ratio": kpi.get("deadhead_ratio"),
        "total_deadhead_km": kpi.get("total_deadhead_km"),
        "total_distance_km": kpi.get("total_distance_km"),
        "pv_generation_total_kwh": kpi.get("pv_generation_total_kwh"),
        "pv_self_consumption_kwh": kpi.get("pv_self_consumption_kwh"),
        "pv_utilization_ratio": kpi.get("pv_utilization_ratio"),
        "peak_grid_import_kw": kpi.get("peak_grid_import_kw"),
        "peak_charge_kw": kpi.get("peak_charge_kw"),
        "min_soc_pct": kpi.get("min_soc_pct"),
        "average_soc_pct": kpi.get("average_soc_pct"),
        "charger_utilization_avg": kpi.get("charger_utilization_avg"),
        "charger_utilization_max": kpi.get("charger_utilization_max"),
        "electricity_cost_jpy": kpi.get("electricity_cost_jpy"),
        "fuel_cost_jpy": kpi.get("fuel_cost_jpy"),
        "demand_charge_cost_jpy": kpi.get("demand_charge_cost_jpy"),
        "co2_kg": kpi.get("co2_kg"),
        "weather_operation_mode": forecast.get("operation_mode") or run.manifest.get("weather_operation_mode"),
        "weather_service_date": forecast.get("service_date"),
        "weather_analog_date": forecast.get("analog_date") or run.manifest.get("weather_analog_date"),
        "weather_label": forecast.get("weather_label"),
        "weather_sun_score": forecast.get("sun_score"),
        "weather_rain_risk": forecast.get("rain_risk"),
        "weather_no_future_leakage": forecast.get("no_future_leakage"),
        "weather_forecast_version": forecast.get("version"),
        "final_soc_floor_percent": policy.get("final_soc_floor_percent"),
        "final_soc_target_percent": policy.get("final_soc_target_percent"),
        "midday_charge_priority": policy.get("midday_charge_priority"),
        "grid_risk_penalty_multiplier": policy.get("grid_risk_penalty_multiplier"),
        "peak_grid_time": _peak_time(peak_grid_idx),
        "peak_charge_time": _peak_time(peak_charge_idx),
        "peak_pv_time": _peak_time(peak_pv_idx),
        "over_limit_hours": over_limit_hours,
        "grid_import_energy_kwh": _flow_metric(flow, "grid_import_slot_kwh"),
        "pv_generation_energy_kwh": _flow_metric(flow, "pv_generation_slot_kwh"),
        "bus_charge_energy_kwh": _integrate_kw_series(flow, "total_charge_kw"),
    }


def _build_metric_rows(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metrics: list[tuple[str, str, int]] = [
        ("solver_status", "求解状態", 0),
        ("weather_label", "weather_label", 0),
        ("weather_operation_mode", "weather_operation_mode", 0),
        ("weather_service_date", "weather_service_date", 0),
        ("weather_analog_date", "weather_analog_date", 0),
        ("weather_sun_score", "sun_score", 4),
        ("weather_rain_risk", "rain_risk", 4),
        ("final_soc_floor_percent", "final_soc_floor_percent", 2),
        ("final_soc_target_percent", "final_soc_target_percent", 2),
        ("midday_charge_priority", "midday_charge_priority", 2),
        ("grid_risk_penalty_multiplier", "grid_risk_penalty_multiplier", 2),
        ("objective_value_jpy", "目的値 (JPY)", 2),
        ("total_cost_jpy", "総コスト (JPY)", 2),
        ("electricity_cost_jpy", "電気代 (JPY)", 2),
        ("fuel_cost_jpy", "軽油代 (JPY)", 2),
        ("demand_charge_cost_jpy", "デマンド料金 (JPY)", 2),
        ("co2_kg", "CO2 排出量 (kg)", 2),
        ("trip_count_served", "便数 (served)", 0),
        ("trip_count_unserved", "便数 (unserved)", 0),
        ("vehicle_count_used", "使用車両数", 0),
        ("deadhead_ratio", "deadhead ratio", 4),
        ("total_deadhead_km", "deadhead 距離 (km)", 2),
        ("pv_generation_total_kwh", "PV 発電量 (kWh)", 2),
        ("pv_self_consumption_kwh", "PV 自家消費 (kWh)", 2),
        ("pv_utilization_ratio", "PV 利用率", 4),
        ("peak_grid_import_kw", "ピーク受電 (kW)", 2),
        ("peak_charge_kw", "ピーク充電 (kW)", 2),
        ("solve_time_seconds", "求解時間 (s)", 2),
        ("min_soc_pct", "最小 SOC (%)", 2),
        ("average_soc_pct", "平均 SOC (%)", 2),
        ("over_limit_hours", "契約超過時間 (h)", 2),
    ]
    for key, label, digits in metrics:
        l_val = left.get(key)
        r_val = right.get(key)
        rows.append(
            {
                "metric": label,
                left["label"]: l_val,
                right["label"]: r_val,
                "delta(left-right)": None if not (_is_number(l_val) and _is_number(r_val)) else (l_val - r_val),
                "delta_pct_vs_right": _delta_pct(l_val, r_val) if (_is_number(l_val) and _is_number(r_val)) else "-",
                "format_digits": digits,
            }
        )
    return rows


def _render_metric_table(metrics_rows: list[dict[str, Any]], left_label: str, right_label: str) -> str:
    lines = [
        "| 指標 | " + left_label + " | " + right_label + " | 差分 (左-右) |",
        "|---|---:|---:|---:|",
    ]
    for row in metrics_rows:
        digits = int(row["format_digits"])
        l_val = row[left_label]
        r_val = row[right_label]
        delta = row["delta(left-right)"]
        if isinstance(l_val, (int, float)):
            left_text = _fmt_num(l_val, digits)
        else:
            left_text = str(l_val)
        if isinstance(r_val, (int, float)):
            right_text = _fmt_num(r_val, digits)
        else:
            right_text = str(r_val)
        if isinstance(delta, (int, float)):
            delta_text = _fmt_num(delta, digits)
        elif delta is None:
            delta_text = "-"
        else:
            delta_text = str(delta)
        lines.append(f"| {row['metric']} | {left_text} | {right_text} | {delta_text} |")
    return "\n".join(lines)


def _summarize_run_files(run: RunBundle) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for name in sorted((run.path).glob("*")):
        if name.is_file():
            files.append((name.name, "result file"))
    graph_dir = run.path / "graph"
    if graph_dir.exists():
        for name in sorted(graph_dir.glob("*")):
            if name.is_file():
                files.append((f"graph/{name.name}", "time-series / graph artifact"))
        for subdir in sorted(graph_dir.iterdir()):
            if subdir.is_dir():
                for item in sorted(subdir.glob("*")):
                    if item.is_file():
                        files.append((f"graph/{subdir.name}/{item.name}", "diagram artifact"))
    return files


def _build_artifact_table(left: RunBundle, right: RunBundle) -> str:
    lines = [
        "| ファイル | 種別 |",
        "|---|---|",
    ]
    seen: set[str] = set()
    for run in (left, right):
        for file_name, kind in _summarize_run_files(run):
            if file_name in seen:
                continue
            seen.add(file_name)
            lines.append(f"| {file_name} | {kind} |")
    return "\n".join(lines)


def _build_dashboard(runs: Iterable[RunBundle], title: str) -> go.Figure:
    runs = list(runs)
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=[
            "系統受電 [kW]",
            "PV 発電 / PV 利用 [kW]",
            "車両充電負荷 [kW]",
            "BESS 充放電 [kW]",
        ],
    )
    palette = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]
    for idx, run in enumerate(runs):
        flow = run.flow
        color = palette[idx % len(palette)]
        label = run.label

        if "grid_import_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["grid_import_kw"],
                    mode="lines",
                    name=f"{label} grid import",
                    legendgroup=label,
                    line=dict(color=color),
                ),
                row=1,
                col=1,
            )
        if "contract_limit_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["contract_limit_kw"],
                    mode="lines",
                    name=f"{label} contract limit",
                    legendgroup=label,
                    line=dict(color=color, dash="dash"),
                    showlegend=False,
                ),
                row=1,
                col=1,
            )

        if "pv_generation_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["pv_generation_kw"],
                    mode="lines",
                    name=f"{label} PV generation",
                    legendgroup=label,
                    line=dict(color=color),
                ),
                row=2,
                col=1,
            )
        if "pv_used_for_charging_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["pv_used_for_charging_kw"],
                    mode="lines",
                    name=f"{label} PV used for charging",
                    legendgroup=label,
                    line=dict(color=color, dash="dot"),
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

        if "total_charge_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["total_charge_kw"],
                    mode="lines",
                    name=f"{label} total charging",
                    legendgroup=label,
                    line=dict(color=color),
                ),
                row=3,
                col=1,
            )
        if "bus_charge_from_grid_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["bus_charge_from_grid_kw"],
                    mode="lines",
                    name=f"{label} charge from grid",
                    legendgroup=label,
                    line=dict(color=color, dash="dash"),
                    showlegend=False,
                ),
                row=3,
                col=1,
            )

        if "battery_storage_charge_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["battery_storage_charge_kw"],
                    mode="lines",
                    name=f"{label} BESS charge",
                    legendgroup=label,
                    line=dict(color=color),
                ),
                row=4,
                col=1,
            )
        if "battery_storage_discharge_kw" in flow.columns:
            fig.add_trace(
                go.Scatter(
                    x=flow["timestamp"],
                    y=flow["battery_storage_discharge_kw"],
                    mode="lines",
                    name=f"{label} BESS discharge",
                    legendgroup=label,
                    line=dict(color=color, dash="dash"),
                    showlegend=False,
                ),
                row=4,
                col=1,
            )

    fig.update_layout(
        title=title,
        height=1200,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
            bgcolor="rgba(255,255,255,0.85)",
            tracegroupgap=6,
        ),
        margin=dict(l=60, r=280, t=90, b=60),
        template="plotly_white",
    )
    for row in range(1, 5):
        fig.update_yaxes(title_text="kW", row=row, col=1)
    fig.update_xaxes(title_text="時刻", row=4, col=1)
    return fig


def _write_markdown_report(
    output_dir: Path,
    report_label: str,
    left: RunBundle,
    right: RunBundle,
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
    metric_rows: list[dict[str, Any]],
) -> Path:
    report = [
        f"# {report_label} 出力フォルダ分析",
        "",
        f"対象: `{left.label}` / `{right.label}`",
        "",
        "## 要約",
        f"- `{left.label}` は `{right.label}` より総コスト・CO2・deadhead・使用車両数が小さい。",
        f"- 早いほうは `2025-08-05` の晴れ寄り条件 (`PV発電見込み高`)、遅いほうは `2025-08-10` の雨寄り条件 (`PV発電見込み低`) での最適化。",
        f"- ただし両方とも `supports_exact_milp=false` で、`objective_is_actual_cost=false`。厳密解比較ではなく、ガードレール付き実行の比較。",
        "",
        "## 各フォルダの分析",
        "",
        f"### {left.label}",
        f"- solver_status: `{left_metrics['solver_status']}`",
        f"- weather: `{left_metrics['weather_label']}` / service_date `{left_metrics['weather_service_date']}` / analog `{left_metrics['weather_analog_date']}` / mode `{left_metrics['weather_operation_mode']}`",
        f"- served/unserved: {left_metrics['trip_count_served']} / {left_metrics['trip_count_unserved']}",
        f"- total_cost: {_fmt_num(left_metrics['total_cost_jpy'])} JPY",
        f"- CO2: {_fmt_num(left_metrics['co2_kg'])} kg",
        f"- deadhead_ratio: {_fmt_pct(left_metrics['deadhead_ratio'])}",
        f"- peak_grid_import: {_fmt_num(left_metrics['peak_grid_import_kw'])} kW at {left_metrics['peak_grid_time']}",
        f"- PV generation: {_fmt_num(left_metrics['pv_generation_total_kwh'])} kWh",
        "",
        f"### {right.label}",
        f"- solver_status: `{right_metrics['solver_status']}`",
        f"- weather: `{right_metrics['weather_label']}` / service_date `{right_metrics['weather_service_date']}` / analog `{right_metrics['weather_analog_date']}` / mode `{right_metrics['weather_operation_mode']}`",
        f"- served/unserved: {right_metrics['trip_count_served']} / {right_metrics['trip_count_unserved']}",
        f"- total_cost: {_fmt_num(right_metrics['total_cost_jpy'])} JPY",
        f"- CO2: {_fmt_num(right_metrics['co2_kg'])} kg",
        f"- deadhead_ratio: {_fmt_pct(right_metrics['deadhead_ratio'])}",
        f"- peak_grid_import: {_fmt_num(right_metrics['peak_grid_import_kw'])} kW at {right_metrics['peak_grid_time']}",
        f"- PV generation: {_fmt_num(right_metrics['pv_generation_total_kwh'])} kWh",
        "",
        "## 比較テーブル",
        "",
        _render_metric_table(metric_rows, left.label, right.label),
        "",
        "## 解釈",
        f"- `{left.label}` は `{right.label}` に比べて、晴れ条件の恩恵で PV 供給が大きく、軽油代とデマンド料金が下がっている。",
        f"- `objective_value_jpy` は実コストではないので、比較時は `total_cost_jpy` を主指標にすべき。",
        "- 天候条件が異なるので、純粋なソルバ性能比較にしたいなら weather proxy を固定して再実行する必要がある。",
    ]
    report_path = output_dir / "analysis_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    return report_path


def _write_full_markdown_report(
    output_dir: Path,
    report_label: str,
    left: RunBundle,
    right: RunBundle,
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
    metric_rows: list[dict[str, Any]],
    generated_htmls: list[str],
    discovery: DiscoveryResult,
) -> Path:
    report = [
        f"# {report_label} 全結果まとめ",
        "",
        f"対象: `{left.label}` / `{right.label}`",
        "",
        "## 結論",
        f"- 早いほう (`{left.label}`) は `2025-08-05` ベースの **晴れ寄り** 条件 (`PV発電見込み高`) で、遅いほう (`{right.label}`) は `2025-08-10` ベースの **雨寄り** 条件 (`PV発電見込み低`) で実行されている。",
        f"- `total_cost_jpy` は `{left.label}` が `{right.label}` より {_fmt_num(left_metrics['total_cost_jpy'] - right_metrics['total_cost_jpy'])} JPY 小さい。",
        f"- `supports_exact_milp=false` なので、今回は厳密MILP解の比較ではない。",
        "",
        "## Weather / Policy",
        f"- {left.label}: service_date={left_metrics['weather_service_date']}, analog_date={left_metrics['weather_analog_date']}, label={left_metrics['weather_label']}, mode={left_metrics['weather_operation_mode']}, sun_score={_fmt_num(left_metrics['weather_sun_score'], 4)}, rain_risk={_fmt_num(left_metrics['weather_rain_risk'], 4)}",
        f"- {right.label}: service_date={right_metrics['weather_service_date']}, analog_date={right_metrics['weather_analog_date']}, label={right_metrics['weather_label']}, mode={right_metrics['weather_operation_mode']}, sun_score={_fmt_num(right_metrics['weather_sun_score'], 4)}, rain_risk={_fmt_num(right_metrics['weather_rain_risk'], 4)}",
        f"- policy({left.label}): floor={_fmt_num(left_metrics['final_soc_floor_percent'])}%, target={_fmt_num(left_metrics['final_soc_target_percent'])}%, midday_charge_priority={_fmt_num(left_metrics['midday_charge_priority'])}",
        f"- policy({right.label}): floor={_fmt_num(right_metrics['final_soc_floor_percent'])}%, target={_fmt_num(right_metrics['final_soc_target_percent'])}%, midday_charge_priority={_fmt_num(right_metrics['midday_charge_priority'])}",
        "",
        "## 各 run の主要結果",
        "",
        f"### {left.label}",
        f"- solver_status: `{left_metrics['solver_status']}`",
        f"- 便数: served {left_metrics['trip_count_served']} / unserved {left_metrics['trip_count_unserved']}",
        f"- total_cost_jpy: {_fmt_num(left_metrics['total_cost_jpy'])}",
        f"- electricity_cost_jpy: {_fmt_num(left_metrics['electricity_cost_jpy'])}",
        f"- fuel_cost_jpy: {_fmt_num(left_metrics['fuel_cost_jpy'])}",
        f"- demand_charge_cost_jpy: {_fmt_num(left_metrics['demand_charge_cost_jpy'])}",
        f"- co2_kg: {_fmt_num(left_metrics['co2_kg'])}",
        f"- deadhead_ratio: {_fmt_pct(left_metrics['deadhead_ratio'])}",
        f"- peak_grid_import_kw: {_fmt_num(left_metrics['peak_grid_import_kw'])} at {left_metrics['peak_grid_time']}",
        f"- vehicle_count_used: {left_metrics['vehicle_count_used']}",
        "",
        f"### {right.label}",
        f"- solver_status: `{right_metrics['solver_status']}`",
        f"- 便数: served {right_metrics['trip_count_served']} / unserved {right_metrics['trip_count_unserved']}",
        f"- total_cost_jpy: {_fmt_num(right_metrics['total_cost_jpy'])}",
        f"- electricity_cost_jpy: {_fmt_num(right_metrics['electricity_cost_jpy'])}",
        f"- fuel_cost_jpy: {_fmt_num(right_metrics['fuel_cost_jpy'])}",
        f"- demand_charge_cost_jpy: {_fmt_num(right_metrics['demand_charge_cost_jpy'])}",
        f"- co2_kg: {_fmt_num(right_metrics['co2_kg'])}",
        f"- deadhead_ratio: {_fmt_pct(right_metrics['deadhead_ratio'])}",
        f"- peak_grid_import_kw: {_fmt_num(right_metrics['peak_grid_import_kw'])} at {right_metrics['peak_grid_time']}",
        f"- vehicle_count_used: {right_metrics['vehicle_count_used']}",
        "",
        "## 比較テーブル",
        "",
        _render_metric_table(metric_rows, left.label, right.label),
        "",
        "## 時系列可視化",
        "- `pvg/` 配下に run 別と比較用の Plotly HTML を出力した。",
        "",
        "| HTML | 内容 |",
        "|---|---|",
    ]
    for html in generated_htmls:
        report.append(f"| {html} | 時系列可視化 |")

    if discovery.skipped_empty or discovery.skipped_non_timeseries or discovery.skipped_no_numeric:
        report.extend(
            [
                "",
                "## 時系列可視化の除外ファイル",
                "",
                "| ファイル | 理由 |",
                "|---|---|",
            ]
        )
        for name in discovery.skipped_empty:
            report.append(f"| {name} | 空ファイル |")
        for name in discovery.skipped_non_timeseries:
            report.append(f"| {name} | 時刻軸列が無く時系列と判定できない |")
        for name in discovery.skipped_no_numeric:
            report.append(f"| {name} | 数値列が無く可視化対象なし |")

    report.extend(
        [
            "",
            "## 補足",
            f"- 可視化した時系列CSV: {len(discovery.specs)} ファイル。",
            "- 凡例は図の右外へ逃がしているので、プロット領域との重なりを避けている。",
            "",
            "## アーティファクト一覧",
            "",
            _build_artifact_table(left, right),
            "",
            "## 解釈",
            "- PV条件差が大きく、晴れ寄りの run は PV発電量・軽油代・デマンド料金が有利だった。",
            "- 早い/遅いの差を見ると、weather proxy が支配的なので、ソルバ差分だけを議論するには条件固定が必要。",
            "- すべての時系列 CSV を HTML に落とし込んだので、各 run の `graph/*.csv` と `pvg/*.html` を突き合わせて読める。",
        ]
    )
    report_path = output_dir / "analysis_full_summary.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    return report_path


def _write_json_summary(
    output_dir: Path,
    left: RunBundle,
    right: RunBundle,
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
) -> Path:
    summary = {
        "runs": {
            left.label: left_metrics,
            right.label: right_metrics,
        },
        "comparison": {
            "total_cost_jpy_delta": left_metrics["total_cost_jpy"] - right_metrics["total_cost_jpy"],
            "objective_value_jpy_delta": left_metrics["objective_value_jpy"] - right_metrics["objective_value_jpy"],
            "co2_kg_delta": left_metrics["co2_kg"] - right_metrics["co2_kg"],
            "deadhead_ratio_delta": left_metrics["deadhead_ratio"] - right_metrics["deadhead_ratio"],
            "pv_generation_total_kwh_delta": left_metrics["pv_generation_total_kwh"] - right_metrics["pv_generation_total_kwh"],
            "vehicle_count_used_delta": left_metrics["vehicle_count_used"] - right_metrics["vehicle_count_used"],
            "solve_time_seconds_delta": left_metrics["solve_time_seconds"] - right_metrics["solve_time_seconds"],
        },
    }
    json_path = output_dir / "analysis_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def _write_dashboard(fig: go.Figure, path: Path) -> None:
    write_html(fig, file=str(path), include_plotlyjs=True, full_html=True)


def _generate_series_dashboards(
    left: RunBundle,
    right: RunBundle,
    pvg_dir: Path,
) -> tuple[list[str], DiscoveryResult]:
    generated: list[str] = []
    discovery = _discover_timeseries_specs([left, right])
    for spec in discovery.specs:
        left_fig = _make_timeseries_figure([left], spec, f"{left.label} - {spec.title}")
        if left_fig is not None:
            left_path = pvg_dir / left.label
            left_path.mkdir(parents=True, exist_ok=True)
            html_path = left_path / f"{spec.file_name.replace('.csv', '')}.html"
            _write_dashboard(left_fig, html_path)
            generated.append(html_path.relative_to(pvg_dir.parent).as_posix())

        right_fig = _make_timeseries_figure([right], spec, f"{right.label} - {spec.title}")
        if right_fig is not None:
            right_path = pvg_dir / right.label
            right_path.mkdir(parents=True, exist_ok=True)
            html_path = right_path / f"{spec.file_name.replace('.csv', '')}.html"
            _write_dashboard(right_fig, html_path)
            generated.append(html_path.relative_to(pvg_dir.parent).as_posix())

        comparison_fig = _make_timeseries_figure([left, right], spec, f"{left.label} vs {right.label} - {spec.title}")
        if comparison_fig is not None:
            comparison_path = pvg_dir / "comparison"
            comparison_path.mkdir(parents=True, exist_ok=True)
            html_path = comparison_path / f"{spec.file_name.replace('.csv', '')}.html"
            _write_dashboard(comparison_fig, html_path)
            generated.append(html_path.relative_to(pvg_dir.parent).as_posix())
    return generated, discovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze two dated output runs and build Plotly dashboards.")
    repo_root = Path(__file__).resolve().parents[1]
    default_base = repo_root / "output" / "2026-05-15"
    parser.add_argument(
        "--left",
        type=Path,
        default=default_base / "run_20260515_1138",
        help="Left run directory",
    )
    parser.add_argument(
        "--right",
        type=Path,
        default=default_base / "run_20260515_1407",
        help="Right run directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_base / "analy",
        help="Analysis output directory",
    )
    args = parser.parse_args()

    left = load_run_bundle(args.left)
    right = load_run_bundle(args.right)
    output_dir = args.output_dir
    report_label = output_dir.parent.name if output_dir.parent.name else output_dir.name
    pvg_dir = output_dir / "pvg"
    output_dir.mkdir(parents=True, exist_ok=True)
    pvg_dir.mkdir(parents=True, exist_ok=True)

    left_metrics = _extract_metrics(left)
    right_metrics = _extract_metrics(right)
    metric_rows = _build_metric_rows(left_metrics, right_metrics)

    report_path = _write_markdown_report(output_dir, report_label, left, right, left_metrics, right_metrics, metric_rows)
    json_path = _write_json_summary(output_dir, left, right, left_metrics, right_metrics)

    left_fig = _build_dashboard([left], f"{left.label} 時系列ダッシュボード")
    right_fig = _build_dashboard([right], f"{right.label} 時系列ダッシュボード")
    comparison_fig = _build_dashboard([left, right], f"{left.label} vs {right.label} 時系列比較")

    generated_htmls: list[str] = []
    left_core = pvg_dir / left.label
    right_core = pvg_dir / right.label
    left_core.mkdir(parents=True, exist_ok=True)
    right_core.mkdir(parents=True, exist_ok=True)
    _write_dashboard(left_fig, left_core / "core_timeseries.html")
    _write_dashboard(right_fig, right_core / "core_timeseries.html")
    _write_dashboard(comparison_fig, pvg_dir / "comparison_timeseries.html")
    generated_htmls.extend(
        [
            (left_core / "core_timeseries.html").relative_to(pvg_dir.parent).as_posix(),
            (right_core / "core_timeseries.html").relative_to(pvg_dir.parent).as_posix(),
            (pvg_dir / "comparison_timeseries.html").relative_to(pvg_dir.parent).as_posix(),
        ]
    )
    generated_timeseries_htmls, discovery = _generate_series_dashboards(left, right, pvg_dir)
    generated_htmls.extend(generated_timeseries_htmls)

    metrics_csv = pd.DataFrame(metric_rows)
    metrics_csv.to_csv(output_dir / "comparison_metrics.csv", index=False, encoding="utf-8-sig")
    full_report_path = _write_full_markdown_report(
        output_dir,
        report_label,
        left,
        right,
        left_metrics,
        right_metrics,
        metric_rows,
        generated_htmls,
        discovery,
    )

    print(f"Wrote: {report_path}")
    print(f"Wrote: {full_report_path}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {output_dir / 'comparison_metrics.csv'}")
    print(f"Wrote: {pvg_dir / left.label / 'core_timeseries.html'}")
    print(f"Wrote: {pvg_dir / right.label / 'core_timeseries.html'}")
    print(f"Wrote: {pvg_dir / 'comparison_timeseries.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
