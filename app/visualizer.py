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
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
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
        fig.add_trace(go.Scatter(
            x=labels_ext[:len(soc_arr)],
            y=soc_arr,
            mode="lines+markers",
            name=bus_id,
            line=dict(color=_bus_color(i)),
            marker=dict(size=4),
        ))

        # SOC 下限ライン
        if bus_spec:
            fig.add_trace(go.Scatter(
                x=labels_ext[:len(soc_arr)],
                y=[bus_spec.soc_min_kwh] * len(soc_arr),
                mode="lines",
                name=f"{bus_id} 下限",
                line=dict(color=_bus_color(i), dash="dash", width=1),
                showlegend=False,
            ))

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
    pv_gen = cfg.pv_gen_kwh[:cfg.num_periods] if cfg.pv_gen_kwh else [0.0] * cfg.num_periods

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=pv_vals, name="PV 利用",
        marker_color="#ffd700",
    ))
    fig.add_trace(go.Bar(
        x=labels, y=grid_vals, name="系統買電",
        marker_color="#ff6347",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=pv_gen, name="PV 発電可能量",
        mode="lines", line=dict(color="#228b22", dash="dot"),
    ))

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
    cost_per_t = [
        prices[t] * grid_vals[t] if t < len(prices) else 0.0
        for t in T
    ]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=labels, y=cost_per_t, name="買電コスト [円]",
            marker_color="#ff6347",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=labels, y=prices[:len(labels)], name="電力単価 [円/kWh]",
            mode="lines+markers", line=dict(color="#4169e1"),
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
            start_label = labels[tr.start_t] if tr.start_t < len(labels) else str(tr.start_t)
            end_idx = min(tr.end_t, len(labels) - 1)
            end_label = labels[end_idx] if end_idx < len(labels) else str(tr.end_t)
            fig.add_trace(go.Bar(
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
            ))

        # 充電イベント
        if bus_id in result.charge_schedule:
            for key, series in result.charge_schedule[bus_id].items():
                for t in range(len(series)):
                    if series[t] > 0:
                        fig.add_trace(go.Bar(
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
                        ))

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
        fig.add_annotation(text="ALNS ログなし", xref="paper", yref="paper", x=0.5, y=0.5)
        return fig

    iters = [e["iteration"] for e in result.iteration_log]
    current = [e["current_cost"] for e in result.iteration_log]
    best = [e["best_cost"] for e in result.iteration_log]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=iters, y=current, name="現在解コスト",
        mode="lines", line=dict(color="#aaaaaa", width=1),
    ))
    fig.add_trace(go.Scatter(
        x=iters, y=best, name="最良解コスト",
        mode="lines", line=dict(color="#d62728", width=2),
    ))

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
        "目的関数値 [円]": f"{result.objective_value:,.0f}" if result.objective_value else "N/A",
        "総買電コスト [円]": f"{result.total_grid_cost_yen:,.0f}",
        "総買電量 [kWh]": f"{result.total_grid_kwh:,.1f}",
        "PV利用量 [kWh]": f"{result.total_pv_kwh:,.1f}",
        "最低SOC [kWh]": f"{result.min_soc_kwh:,.1f}",
        "最大同時充電台数": result.max_simultaneous_chargers,
        "計算時間 [秒]": f"{result.solve_time_sec:.2f}",
    }
