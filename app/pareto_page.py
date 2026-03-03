"""
app/pareto_page.py

Pareto frontier page for the Streamlit research dashboard.

Loads results/sensitivity/batch_results.csv produced by
scripts/batch_sensitivity.py and shows:
  1. Scatter plot: total_cost_yen vs co2_kg, coloured by ev_count,
     with Pareto-optimal front highlighted.
  2. Table of Pareto-optimal scenarios.

This module must be called from app/main.py (inside tab_research), e.g.:
    from app.pareto_page import render_pareto_page
    render_pareto_page()

Rule: NO solver logic here — display only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_DEFAULT_CSV = Path("results/sensitivity/batch_results.csv")


# ---------------------------------------------------------------------------
# Pareto helpers
# ---------------------------------------------------------------------------


def _pareto_mask(df: pd.DataFrame, col_x: str, col_y: str) -> pd.Series:
    """
    Return a boolean Series: True if row is Pareto-optimal
    (minimise both col_x and col_y).

    A point p dominates q if p[x] <= q[x] AND p[y] <= q[y]
    with at least one strict inequality.
    """
    x = df[col_x].values
    y = df[col_y].values
    n = len(x)
    dominated = [False] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if x[j] <= x[i] and y[j] <= y[i] and (x[j] < x[i] or y[j] < y[i]):
                dominated[i] = True
                break
    return pd.Series([not d for d in dominated], index=df.index)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------


def render_pareto_page(csv_path: str | Path | None = None) -> None:
    """Render the Pareto frontier analysis section into the current Streamlit context."""
    st.markdown(
        """
        <div style="margin-bottom:8px;">
          <strong>パレート最前線分析</strong>
          &nbsp;—&nbsp;
          <span style="color:var(--color-muted,#888);font-size:.86rem;">
            コスト vs CO₂ のトレードオフを可視化します。
            データは <code>scripts/batch_sensitivity.py</code> で生成してください。
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- CSV path resolution ----
    resolved_path = Path(csv_path) if csv_path else _DEFAULT_CSV

    # Allow user to override path
    _col_path, _col_run = st.columns([3, 1])
    with _col_path:
        user_path = st.text_input(
            "CSV パス",
            value=str(resolved_path),
            key="pareto_csv_path",
        )
    with _col_run:
        run_sweep = st.button("スイープ実行", key="pareto_run_sweep")

    if run_sweep:
        with st.spinner("batch_sensitivity.py を実行中…"):
            try:
                import subprocess
                import sys

                result = subprocess.run(
                    [
                        sys.executable,
                        "scripts/batch_sensitivity.py",
                        "--output",
                        user_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    st.success("スイープ完了。CSVを読み込みます。")
                else:
                    st.error(f"スイープ失敗:\n```\n{result.stderr}\n```")
            except Exception as _e:
                st.error(f"実行エラー: {_e}")

    # ---- Load CSV ----
    p = Path(user_path)
    if not p.exists():
        st.info(
            f"`{p}` が見つかりません。  \n"
            "「スイープ実行」ボタンを押すか、"
            "`python scripts/batch_sensitivity.py` を手動で実行してください。"
        )
        return

    try:
        df = pd.read_csv(p)
    except Exception as exc:
        st.error(f"CSV 読み込みエラー: {exc}")
        return

    required_cols = {"total_cost_yen", "co2_kg", "ev_count"}
    if not required_cols.issubset(df.columns):
        st.error(f"CSV に必須列が不足しています: {required_cols - set(df.columns)}")
        return

    # Drop rows where cost or co2 is missing
    df_clean = df.dropna(subset=["total_cost_yen", "co2_kg"]).copy()
    if df_clean.empty:
        st.warning("有効なデータ行がありません。")
        return

    df_clean["ev_count"] = df_clean["ev_count"].astype(int)

    # ---- Pareto mask ----
    pareto_mask = _pareto_mask(df_clean, "total_cost_yen", "co2_kg")
    df_clean["is_pareto"] = pareto_mask
    df_pareto = df_clean[pareto_mask].sort_values("total_cost_yen")

    # ---- Summary metrics ----
    _mc1, _mc2, _mc3 = st.columns(3)
    _mc1.metric("全シナリオ数", len(df_clean))
    _mc2.metric("パレート最適数", int(pareto_mask.sum()))
    _mc3.metric("最大 EV 台数", int(df_clean["ev_count"].max()))

    # ---- Scatter plot ----
    st.markdown("#### コスト vs CO₂ スキャッタープロット")

    fig = go.Figure()

    # Background: all non-Pareto points per ev_count
    _color_map = {0: "#9ecae1", 1: "#6baed6", 2: "#3182bd", 3: "#08519c"}
    for ec in sorted(df_clean["ev_count"].unique()):
        subset = df_clean[(df_clean["ev_count"] == ec) & (~df_clean["is_pareto"])]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["total_cost_yen"],
                y=subset["co2_kg"],
                mode="markers",
                name=f"EV {ec}台 (非最適)",
                marker=dict(
                    size=7,
                    color=_color_map.get(ec, "#aaa"),
                    opacity=0.45,
                    symbol="circle",
                ),
                customdata=subset[
                    ["scenario_id", "diesel_price", "tou_price", "daily_distance_km"]
                ].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "コスト: ¥%{x:,.0f}<br>"
                    "CO₂: %{y:.1f} kg<br>"
                    "軽油: %{customdata[1]} ¥/L, TOU: %{customdata[2]} ¥/kWh, "
                    "距離: %{customdata[3]} km<extra></extra>"
                ),
            )
        )

    # Pareto front points per ev_count
    for ec in sorted(df_pareto["ev_count"].unique()):
        subset_p = df_pareto[df_pareto["ev_count"] == ec]
        fig.add_trace(
            go.Scatter(
                x=subset_p["total_cost_yen"],
                y=subset_p["co2_kg"],
                mode="markers",
                name=f"EV {ec}台 (パレート最適)",
                marker=dict(
                    size=13,
                    color=_color_map.get(ec, "#e31a1c"),
                    opacity=1.0,
                    symbol="star",
                    line=dict(width=1.5, color="white"),
                ),
                customdata=subset_p[
                    ["scenario_id", "diesel_price", "tou_price", "daily_distance_km"]
                ].values,
                hovertemplate=(
                    "<b>★ %{customdata[0]}</b><br>"
                    "コスト: ¥%{x:,.0f}<br>"
                    "CO₂: %{y:.1f} kg<br>"
                    "軽油: %{customdata[1]} ¥/L, TOU: %{customdata[2]} ¥/kWh, "
                    "距離: %{customdata[3]} km<extra></extra>"
                ),
            )
        )

    # Connect Pareto front with a step line
    if not df_pareto.empty:
        pf_sorted = df_pareto.sort_values("total_cost_yen")
        fig.add_trace(
            go.Scatter(
                x=pf_sorted["total_cost_yen"],
                y=pf_sorted["co2_kg"],
                mode="lines",
                name="パレートフロント",
                line=dict(color="crimson", width=2, dash="dash"),
                showlegend=True,
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        xaxis_title="総コスト (¥/日)",
        yaxis_title="CO₂ 排出量 (kg/日)",
        legend_title="EV 台数",
        height=480,
        margin=dict(l=60, r=20, t=20, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---- Pareto table ----
    st.markdown("#### パレート最適シナリオ一覧")
    display_cols = [
        "scenario_id",
        "ev_count",
        "diesel_price",
        "tou_price",
        "daily_distance_km",
        "total_cost_yen",
        "fuel_cost_yen",
        "electricity_cost_yen",
        "demand_charge_yen",
        "total_fuel_L",
        "peak_grid_kW",
        "co2_kg",
    ]
    show_cols = [c for c in display_cols if c in df_pareto.columns]
    st.dataframe(
        df_pareto[show_cols].reset_index(drop=True),
        use_container_width=True,
    )

    # ---- CSV download ----
    pareto_csv = df_pareto[show_cols].to_csv(index=False)
    st.download_button(
        label="📥 パレート最適シナリオを CSV でダウンロード",
        data=pareto_csv,
        file_name="pareto_optimal_scenarios.csv",
        mime="text/csv",
        key="pareto_download",
    )

    # ---- Filter controls ----
    with st.expander("全シナリオを絞り込み表示", expanded=False):
        _f1, _f2, _f3, _f4 = st.columns(4)
        with _f1:
            ev_filter = st.multiselect(
                "EV 台数",
                options=sorted(df_clean["ev_count"].unique()),
                default=sorted(df_clean["ev_count"].unique()),
                key="pareto_filter_ev",
            )
        with _f2:
            dp_filter = st.multiselect(
                "軽油価格 (¥/L)",
                options=sorted(df_clean["diesel_price"].unique())
                if "diesel_price" in df_clean.columns
                else [],
                default=sorted(df_clean["diesel_price"].unique())
                if "diesel_price" in df_clean.columns
                else [],
                key="pareto_filter_dp",
            )
        with _f3:
            tou_filter = st.multiselect(
                "電力単価 (¥/kWh)",
                options=sorted(df_clean["tou_price"].unique())
                if "tou_price" in df_clean.columns
                else [],
                default=sorted(df_clean["tou_price"].unique())
                if "tou_price" in df_clean.columns
                else [],
                key="pareto_filter_tou",
            )
        with _f4:
            dist_filter = st.multiselect(
                "日走行距離 (km)",
                options=sorted(df_clean["daily_distance_km"].unique())
                if "daily_distance_km" in df_clean.columns
                else [],
                default=sorted(df_clean["daily_distance_km"].unique())
                if "daily_distance_km" in df_clean.columns
                else [],
                key="pareto_filter_dist",
            )

        df_filtered = df_clean[df_clean["ev_count"].isin(ev_filter)]
        if dp_filter and "diesel_price" in df_filtered.columns:
            df_filtered = df_filtered[df_filtered["diesel_price"].isin(dp_filter)]
        if tou_filter and "tou_price" in df_filtered.columns:
            df_filtered = df_filtered[df_filtered["tou_price"].isin(tou_filter)]
        if dist_filter and "daily_distance_km" in df_filtered.columns:
            df_filtered = df_filtered[
                df_filtered["daily_distance_km"].isin(dist_filter)
            ]

        st.caption(f"{len(df_filtered)} 件表示中")
        show_cols_all = [c for c in display_cols if c in df_filtered.columns]
        st.dataframe(
            df_filtered[show_cols_all].reset_index(drop=True), use_container_width=True
        )
