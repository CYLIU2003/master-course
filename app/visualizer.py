"""
visualizer.py — 結果の可視化モジュール

Plotly ベースのインタラクティブグラフを生成。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .model_core import ProblemConfig, SolveResult, make_time_labels


# ---------------------------------------------------------------------------
# カラーパレット
# ---------------------------------------------------------------------------
BUS_COLORS = [
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


def _bus_color(idx: int) -> str:
    return BUS_COLORS[idx % len(BUS_COLORS)]


# ---------------------------------------------------------------------------
# SOC 推移グラフ
# ---------------------------------------------------------------------------


def plot_soc_timeseries(
    cfg: ProblemConfig,
    result: SolveResult,
    title: str = "SOC 推移 [kWh]",
) -> go.Figure:
    """各バスの SOC 時系列を折れ線グラフで描画"""
    labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
    labels_ext = labels + ["END"]

    fig = go.Figure()

    for i, (bus_id, soc_arr) in enumerate(result.soc_series.items()):
        bus_spec = next((b for b in cfg.buses if b.bus_id == bus_id), None)
        fig.add_trace(
            go.Scatter(
                x=labels_ext[: len(soc_arr)],
                y=soc_arr,
                mode="lines+markers",
                name=bus_id,
                line=dict(color=_bus_color(i)),
                marker=dict(size=4),
            )
        )

        # SOC 下限ライン
        if bus_spec:
            fig.add_trace(
                go.Scatter(
                    x=labels_ext[: len(soc_arr)],
                    y=[bus_spec.soc_min_kwh] * len(soc_arr),
                    mode="lines",
                    name=f"{bus_id} 下限",
                    line=dict(color=_bus_color(i), dash="dash", width=1),
                    showlegend=False,
                )
            )

    fig.update_layout(
        title=title,
        xaxis_title="時刻",
        yaxis_title="SOC [kWh]",
        hovermode="x unified",
        height=450,
    )
    return fig


# ---------------------------------------------------------------------------
# 電力バランスグラフ（PV vs 買電）
# ---------------------------------------------------------------------------


def plot_power_balance(
    cfg: ProblemConfig,
    result: SolveResult,
    title: str = "電力バランス",
) -> go.Figure:
    """PV 利用量 / 買電量を積み上げ棒グラフで描画"""
    labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
    T = list(range(cfg.num_periods))

    pv_vals = [result.pv_use.get(t, 0.0) for t in T]
    grid_vals = [result.grid_buy.get(t, 0.0) for t in T]
    pv_gen = (
        cfg.pv_gen_kwh[: cfg.num_periods] if cfg.pv_gen_kwh else [0.0] * cfg.num_periods
    )

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=pv_vals,
            name="PV 利用",
            marker_color="#ffd700",
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=grid_vals,
            name="系統買電",
            marker_color="#ff6347",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=pv_gen,
            name="PV 発電可能量",
            mode="lines",
            line=dict(color="#228b22", dash="dot"),
        )
    )

    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis_title="時刻",
        yaxis_title="電力量 [kWh]",
        hovermode="x unified",
        height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# 電力単価とコストグラフ
# ---------------------------------------------------------------------------


def plot_cost_breakdown(
    cfg: ProblemConfig,
    result: SolveResult,
    title: str = "時刻別買電コスト",
) -> go.Figure:
    """時刻別の買電コストと電力単価を2軸で描画"""
    labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
    T = list(range(cfg.num_periods))
    prices = cfg.grid_price_yen_per_kwh

    grid_vals = [result.grid_buy.get(t, 0.0) for t in T]
    cost_per_t = [prices[t] * grid_vals[t] if t < len(prices) else 0.0 for t in T]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=labels,
            y=cost_per_t,
            name="買電コスト [円]",
            marker_color="#ff6347",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=prices[: len(labels)],
            name="電力単価 [円/kWh]",
            mode="lines+markers",
            line=dict(color="#4169e1"),
            marker=dict(size=4),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title=title,
        hovermode="x unified",
        height=400,
    )
    fig.update_yaxes(title_text="コスト [円]", secondary_y=False)
    fig.update_yaxes(title_text="単価 [円/kWh]", secondary_y=True)

    return fig


# ---------------------------------------------------------------------------
# 便割当ガントチャート
# ---------------------------------------------------------------------------


def plot_assignment_gantt(
    cfg: ProblemConfig,
    result: SolveResult,
    title: str = "便割当スケジュール",
) -> go.Figure:
    """便割当とチャージイベントをガントチャート風に描画"""
    labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
    trip_lut = {tr.trip_id: tr for tr in cfg.trips}
    bus_ids = [b.bus_id for b in cfg.buses]

    fig = go.Figure()

    for i, bus_id in enumerate(bus_ids):
        color = _bus_color(i)
        assigned = result.assignment.get(bus_id, [])

        for trip_id in assigned:
            tr = trip_lut.get(trip_id)
            if not tr:
                continue
            start_label = (
                labels[tr.start_t] if tr.start_t < len(labels) else str(tr.start_t)
            )
            end_idx = min(tr.end_t, len(labels) - 1)
            end_label = labels[end_idx] if end_idx < len(labels) else str(tr.end_t)
            fig.add_trace(
                go.Bar(
                    y=[bus_id],
                    x=[tr.end_t - tr.start_t + 1],
                    base=[tr.start_t],
                    orientation="h",
                    name=trip_id,
                    marker_color=color,
                    text=f"{trip_id} ({tr.energy_kwh}kWh)",
                    textposition="inside",
                    hovertemplate=(
                        f"{trip_id}<br>"
                        f"バス: {bus_id}<br>"
                        f"時間: {start_label}〜{end_label}<br>"
                        f"消費: {tr.energy_kwh} kWh"
                    ),
                    showlegend=False,
                )
            )

        # 充電イベント
        if bus_id in result.charge_schedule:
            for key, series in result.charge_schedule[bus_id].items():
                for t in range(len(series)):
                    if series[t] > 0:
                        fig.add_trace(
                            go.Bar(
                                y=[bus_id],
                                x=[1],
                                base=[t],
                                orientation="h",
                                name="充電",
                                marker_color="rgba(0,128,0,0.3)",
                                marker_line=dict(color="green", width=1),
                                text="⚡",
                                textposition="inside",
                                showlegend=False,
                            )
                        )

    fig.update_layout(
        title=title,
        xaxis=dict(
            title="時間スロット",
            tickvals=list(range(cfg.num_periods)),
            ticktext=labels,
            tickangle=45,
        ),
        yaxis_title="バス",
        barmode="overlay",
        height=max(300, 100 * len(bus_ids)),
    )
    return fig


# ---------------------------------------------------------------------------
# ALNS 収束グラフ
# ---------------------------------------------------------------------------


def plot_alns_convergence(
    result: SolveResult,
    title: str = "ALNS 収束曲線",
) -> go.Figure:
    """ALNS の反復ごとのコスト推移"""
    if not result.iteration_log:
        fig = go.Figure()
        fig.add_annotation(
            text="ALNS ログなし", xref="paper", yref="paper", x=0.5, y=0.5
        )
        return fig

    iters = [e["iteration"] for e in result.iteration_log]
    current = [e["current_cost"] for e in result.iteration_log]
    best = [e["best_cost"] for e in result.iteration_log]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=iters,
            y=current,
            name="現在解コスト",
            mode="lines",
            line=dict(color="#aaaaaa", width=1),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=iters,
            y=best,
            name="最良解コスト",
            mode="lines",
            line=dict(color="#d62728", width=2),
        )
    )

    fig.update_layout(
        title=title,
        xaxis_title="反復回数",
        yaxis_title="コスト [円]",
        hovermode="x unified",
        height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# KPI テーブル
# ---------------------------------------------------------------------------


def make_kpi_table(result: SolveResult) -> Dict[str, Any]:
    """主要 KPI を辞書で返す"""
    return {
        "ソルバー": result.solver_name.upper(),
        "ステータス": result.status,
        "目的関数値 [円]": f"{result.objective_value:,.0f}"
        if result.objective_value
        else "N/A",
        "総買電コスト [円]": f"{result.total_grid_cost_yen:,.0f}",
        "総買電量 [kWh]": f"{result.total_grid_kwh:,.1f}",
        "PV利用量 [kWh]": f"{result.total_pv_kwh:,.1f}",
        "最低SOC [kWh]": f"{result.min_soc_kwh:,.1f}",
        "最大同時充電台数": str(result.max_simultaneous_chargers),
        "計算時間 [秒]": f"{result.solve_time_sec:.2f}",
    }


# ---------------------------------------------------------------------------
# src パイプライン対応グラフ (raw dict/list 入力 — app.model_core 非依存)
# ---------------------------------------------------------------------------


def plot_soc_src(
    soc_series: Dict[str, List[float]],
    time_labels: Optional[List[str]] = None,
    soc_min_lines: Optional[Dict[str, float]] = None,
    title: str = "SOC 推移 [kWh]",
) -> go.Figure:
    """
    src.milp_model.MILPResult.soc_series に対応した SOC 折れ線グラフ。

    Parameters
    ----------
    soc_series  : {vehicle_id: [soc_0, soc_1, ...]}
    time_labels : 表示用時刻ラベル (None の場合はインデックス番号)
    soc_min_lines : {vehicle_id: soc_min_kwh} — 下限ラインを追加描画
    """
    fig = go.Figure()
    for i, (vid, series) in enumerate(soc_series.items()):
        x = time_labels[: len(series)] if time_labels else list(range(len(series)))
        fig.add_trace(
            go.Scatter(
                x=x,
                y=series,
                mode="lines+markers",
                name=vid,
                line=dict(color=_bus_color(i)),
                marker=dict(size=3),
            )
        )
        if soc_min_lines and vid in soc_min_lines:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=[soc_min_lines[vid]] * len(x),
                    mode="lines",
                    name=f"{vid} 下限",
                    showlegend=False,
                    line=dict(color=_bus_color(i), dash="dash", width=1),
                )
            )
    fig.update_layout(
        title=title,
        xaxis_title="時刻",
        yaxis_title="SOC [kWh]",
        hovermode="x unified",
        height=450,
    )
    return fig


def plot_charger_occupancy_src(
    charger_totals: Dict[str, List[float]],
    time_labels: Optional[List[str]] = None,
    title: str = "充電器稼働状況",
) -> go.Figure:
    """
    充電器ごとの同時接続台数を積み上げ棒グラフで描画。

    Parameters
    ----------
    charger_totals : {charger_id: [台数 per slot, ...]}
    """
    fig = go.Figure()
    if not charger_totals:
        fig.add_annotation(
            text="充電スケジュールなし", xref="paper", yref="paper", x=0.5, y=0.5
        )
        return fig
    max_len = max(len(v) for v in charger_totals.values())
    labels = time_labels[:max_len] if time_labels else list(range(max_len))
    for i, (cid, series) in enumerate(charger_totals.items()):
        fig.add_trace(
            go.Bar(
                x=labels[: len(series)],
                y=series,
                name=cid,
                marker_color=_bus_color(i),
            )
        )
    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis_title="時刻",
        yaxis_title="稼働台数",
        hovermode="x unified",
        height=350,
    )
    return fig


def plot_site_power_src(
    grid_import: Dict[str, List[float]],
    pv_used: Optional[Dict[str, List[float]]] = None,
    time_labels: Optional[List[str]] = None,
    title: str = "サイト電力収支 [kW]",
) -> go.Figure:
    """
    グリッド受電量と PV 利用量を積み上げ棒グラフで描画。

    Parameters
    ----------
    grid_import : {site_id: [kW per slot, ...]}
    pv_used     : {site_id: [kW per slot, ...]} (None の場合は省略)
    """
    fig = go.Figure()
    all_series = list(grid_import.values()) + (list((pv_used or {}).values()))
    max_len = max((len(s) for s in all_series), default=1)
    labels = time_labels[:max_len] if time_labels else list(range(max_len))

    for site_id, series in grid_import.items():
        fig.add_trace(
            go.Bar(
                x=labels[: len(series)],
                y=series,
                name=f"{site_id} 系統受電",
                marker_color="#ff6347",
            )
        )
    if pv_used:
        for site_id, series in pv_used.items():
            fig.add_trace(
                go.Bar(
                    x=labels[: len(series)],
                    y=series,
                    name=f"{site_id} PV",
                    marker_color="#ffd700",
                )
            )
    fig.update_layout(
        title=title,
        barmode="stack",
        xaxis_title="時刻",
        yaxis_title="電力 [kW]",
        hovermode="x unified",
        height=380,
    )
    return fig


def plot_feasibility_radar(
    report_dict: Dict[str, bool],
    title: str = "実行可能性ダッシュボード",
) -> go.Figure:
    """
    実行可能性診断の6カテゴリをレーダーチャートで表示。

    Parameters
    ----------
    report_dict : {category_name: bool}  OK=True, NG=False
    """
    categories = list(report_dict.keys())
    values = [1.0 if v else 0.0 for v in report_dict.values()]
    # レーダーを閉じる
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]

    color_ok = "rgba(0,169,157,0.25)"
    color_ng = "rgba(220,80,60,0.25)"
    all_ok = all(report_dict.values())

    fig = go.Figure(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill="toself",
            fillcolor=color_ok if all_ok else color_ng,
            line=dict(color="#00a99d" if all_ok else "#dc503c", width=2),
            name="実行可能性",
        )
    )
    fig.update_layout(
        title=title,
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                tickvals=[0, 1],
                ticktext=["NG", "OK"],
            )
        ),
        height=380,
        showlegend=False,
    )
    return fig


def plot_gantt_src(
    assignment: Dict[str, List[str]],
    task_info: Dict[str, Any],
    charge_schedule: Optional[Dict[str, Dict[str, List[float]]]] = None,
    num_periods: int = 64,
    time_labels: Optional[List[str]] = None,
    title: str = "便割当スケジュール (src)",
) -> go.Figure:
    """
    src.milp_model.MILPResult 対応のガントチャート。

    Parameters
    ----------
    assignment    : {vehicle_id: [task_id, ...]}
    task_info     : {task_id: {"start": int, "end": int, "energy": float}}
    charge_schedule : {vehicle_id: {charger_id: [z_t, ...]}} (None の場合は省略)
    """
    fig = go.Figure()
    vehicle_ids = list(assignment.keys())
    labels = time_labels or [str(i) for i in range(num_periods)]

    for i, vid in enumerate(vehicle_ids):
        color = _bus_color(i)
        for task_id in assignment.get(vid, []):
            info = task_info.get(task_id, {})
            s = info.get("start", 0)
            e = info.get("end", s + 1)
            energy = info.get("energy", 0.0)
            s_label = labels[s] if s < len(labels) else str(s)
            e_label = labels[e] if e < len(labels) else str(e)
            fig.add_trace(
                go.Bar(
                    y=[vid],
                    x=[e - s + 1],
                    base=[s],
                    orientation="h",
                    marker_color=color,
                    text=f"{task_id} ({energy:.0f}kWh)",
                    textposition="inside",
                    name=task_id,
                    showlegend=False,
                    hovertemplate=(
                        f"{task_id}<br>車両: {vid}<br>"
                        f"時間: {s_label}〜{e_label}<br>"
                        f"消費: {energy:.1f} kWh<extra></extra>"
                    ),
                )
            )

        # 充電イベント
        if charge_schedule and vid in charge_schedule:
            for c_id, series in charge_schedule[vid].items():
                for t, val in enumerate(series):
                    if val > 0:
                        fig.add_trace(
                            go.Bar(
                                y=[vid],
                                x=[1],
                                base=[t],
                                orientation="h",
                                marker_color="rgba(0,128,0,0.3)",
                                marker_line=dict(color="green", width=1),
                                text="⚡",
                                textposition="inside",
                                showlegend=False,
                                hovertemplate=f"充電 {c_id} t={t}<extra></extra>",
                            )
                        )

    fig.update_layout(
        title=title,
        xaxis=dict(
            title="時間スロット",
            tickvals=list(range(0, num_periods, max(1, num_periods // 16))),
            ticktext=labels[:: max(1, num_periods // 16)],
            tickangle=45,
        ),
        yaxis_title="車両",
        barmode="overlay",
        height=max(300, 100 * max(len(vehicle_ids), 1)),
    )
    return fig
