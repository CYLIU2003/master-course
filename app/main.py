"""
main.py — Streamlit アプリケーション エントリーポイント

電気バス運行・充電スケジューリング最適化シミュレータ
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st
import pandas as pd

# パスを通す
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.model_core import (
    BusSpec,
    ChargerSpec,
    ProblemConfig,
    SolveResult,
    TripSpec,
    config_to_dict,
    load_config_from_json,
    make_time_labels,
    precompute_helpers,
)
from app.solver_gurobi import VALID_STAGES, is_gurobi_available, solve_gurobi
from app.solver_alns import ALNSParams, solve_alns
from app.visualizer import (
    make_kpi_table,
    plot_alns_convergence,
    plot_assignment_gantt,
    plot_cost_breakdown,
    plot_power_balance,
    plot_soc_timeseries,
)


# ---------------------------------------------------------------------------
# ページ設定
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="E-Bus Sim — 電気バス最適化シミュレータ",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# セッション初期化
# ---------------------------------------------------------------------------
if "config" not in st.session_state:
    st.session_state.config = None
if "result_gurobi" not in st.session_state:
    st.session_state.result_gurobi = None
if "result_alns" not in st.session_state:
    st.session_state.result_alns = None


# ---------------------------------------------------------------------------
# サイドバー: 設定パネル
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ シミュレーション設定")

config_mode = st.sidebar.radio(
    "設定方法",
    ["手動設定", "JSON インポート"],
    help="手動でパラメータを調整するか、既存JSONを読み込むか選択",
)

if config_mode == "JSON インポート":
    uploaded = st.sidebar.file_uploader(
        "設定JSON をアップロード",
        type=["json"],
        help="ebus_prototype_config.json 形式",
    )
    # ローカルファイル自動読み込み
    default_json = Path(__file__).resolve().parent.parent / "ebus_prototype_config.json"
    if uploaded is not None:
        raw = json.loads(uploaded.read().decode("utf-8"))
        # 一時ファイルに書き出して読み込み
        tmp_path = Path(__file__).resolve().parent / "_tmp_upload.json"
        tmp_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        st.session_state.config = load_config_from_json(tmp_path)
        st.sidebar.success("JSON を読み込みました")
    elif default_json.exists():
        if st.sidebar.button("デフォルト JSON を読み込む"):
            st.session_state.config = load_config_from_json(default_json)
            st.sidebar.success("デフォルト設定を読み込みました")

else:
    # ============================================================
    # 手動設定モード
    # ============================================================
    st.sidebar.markdown("---")
    st.sidebar.subheader("📐 システム規模")

    num_buses = st.sidebar.slider("バス台数", 1, 20, 3, help="BEV バスの台数")
    num_trips = st.sidebar.slider("便数", 1, 30, 6, help="運行便の数")
    delta_h = st.sidebar.selectbox("時間刻み [h]", [0.25, 0.5, 1.0], index=1)
    start_hour = st.sidebar.slider("開始時刻", 0, 12, 6)
    end_hour = st.sidebar.slider("終了時刻", 12, 24, 22)
    num_periods = int((end_hour - start_hour) / delta_h)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🚌 車両性能")

    cap_kwh = st.sidebar.number_input("バッテリ容量 [kWh]", 50.0, 1000.0, 300.0, step=10.0)
    soc_init_ratio = st.sidebar.slider("初期 SOC [%]", 30, 100, 80) / 100.0
    soc_min_ratio = st.sidebar.slider("SOC 下限 [%]", 5, 50, 20) / 100.0
    efficiency = st.sidebar.number_input(
        "電費 [km/kWh]", 0.3, 3.0, 1.0, step=0.1,
        help="BEV の電費。値が大きいほど燃費が良い",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔌 充電設備")

    num_depots = st.sidebar.slider("充電拠点数", 1, 5, 2)
    slow_power = st.sidebar.number_input("普通充電出力 [kW]", 10.0, 200.0, 50.0, step=10.0)
    slow_count = st.sidebar.number_input("普通充電器台数", 0, 10, 2, step=1)
    fast_power = st.sidebar.number_input("急速充電出力 [kW]", 50.0, 500.0, 150.0, step=10.0)
    fast_count = st.sidebar.number_input("急速充電器台数", 0, 10, 1, step=1)
    charge_eff = st.sidebar.slider("充電効率", 0.80, 1.00, 0.95, step=0.01)

    st.sidebar.markdown("---")
    st.sidebar.subheader("☀️ PV・電力料金")

    enable_pv = st.sidebar.checkbox("PV を有効にする", value=True)
    pv_scale = st.sidebar.slider(
        "PV 出力倍率", 0.0, 5.0, 1.0, step=0.1,
        help="デフォルト PV プロファイルのスケール倍率",
    )

    price_mode = st.sidebar.selectbox(
        "電力料金モード",
        ["デフォルト TOU", "一律 [円/kWh]"],
    )
    flat_price = 25.0
    if price_mode == "一律 [円/kWh]":
        flat_price = st.sidebar.number_input("電力単価 [円/kWh]", 10.0, 100.0, 25.0, step=1.0)

    diesel_price = st.sidebar.number_input(
        "軽油単価 [円/L]", 80.0, 250.0, 145.0, step=5.0,
        help="ICE 比較用",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔧 拡張オプション")

    enable_terminal_soc = st.sidebar.checkbox("終端 SOC 条件", value=False)
    terminal_soc_ratio = 0.5
    if enable_terminal_soc:
        terminal_soc_ratio = st.sidebar.slider("終端 SOC [%]", 20, 80, 50) / 100.0

    enable_demand_charge = st.sidebar.checkbox("デマンドチャージ", value=False)
    contract_power = None
    if enable_demand_charge:
        contract_power = st.sidebar.number_input(
            "契約電力上限 [kW]", 50.0, 1000.0, 200.0, step=10.0,
        )

    # ---- 便を自動生成 ----
    if st.sidebar.button("🔄 設定を適用", type="primary"):
        import random as _rng

        _rng.seed(42)

        depots = [f"depot_{chr(65 + i)}" for i in range(num_depots)]

        buses = []
        for i in range(num_buses):
            buses.append(BusSpec(
                bus_id=f"bus_{i+1}",
                category="BEV",
                cap_kwh=cap_kwh,
                soc_init_kwh=round(cap_kwh * soc_init_ratio, 1),
                soc_min_kwh=round(cap_kwh * soc_min_ratio, 1),
                soc_max_kwh=cap_kwh,
                efficiency_km_per_kwh=efficiency,
            ))

        trips = []
        used_slots = []
        for i in range(num_trips):
            # 均等に配置して重複を制御
            slot_start = int(i * (num_periods - 3) / max(num_trips, 1))
            duration = _rng.randint(2, 4)
            slot_end = min(slot_start + duration, num_periods - 1)
            energy = round(_rng.uniform(25, 55), 1)
            sn = depots[i % len(depots)]
            en = depots[(i + 1) % len(depots)]
            trips.append(TripSpec(
                trip_id=f"trip_{i+1}",
                start_t=slot_start,
                end_t=slot_end,
                energy_kwh=energy,
                start_node=sn,
                end_node=en,
            ))

        chargers = []
        for depot in depots:
            if slow_count > 0:
                chargers.append(ChargerSpec(
                    depot=depot, charger_type="slow",
                    power_kw=slow_power, count=slow_count,
                    efficiency=charge_eff,
                ))
            if fast_count > 0:
                chargers.append(ChargerSpec(
                    depot=depot, charger_type="fast",
                    power_kw=fast_power, count=fast_count,
                    efficiency=charge_eff,
                ))

        # PV プロファイル（ベル曲線近似）
        import math
        pv_profile = []
        for t in range(num_periods):
            hour = start_hour + t * delta_h
            if 6 <= hour <= 18:
                val = 60.0 * math.exp(-0.5 * ((hour - 12.0) / 3.0) ** 2)
            else:
                val = 0.0
            pv_profile.append(round(val * pv_scale, 2))

        # 電力単価
        if price_mode == "一律 [円/kWh]":
            prices = [flat_price] * num_periods
        else:
            prices = []
            for t in range(num_periods):
                hour = start_hour + t * delta_h
                if hour < 8 or hour >= 22:
                    prices.append(18.0)
                elif hour < 10:
                    prices.append(22.0)
                elif hour < 16:
                    prices.append(30.0)
                elif hour < 20:
                    prices.append(34.0)
                else:
                    prices.append(25.0)

        charger_type_list = list(set(c.charger_type for c in chargers))

        cfg = ProblemConfig(
            num_buses=num_buses,
            num_trips=num_trips,
            num_periods=num_periods,
            delta_h=delta_h,
            start_time=f"{start_hour:02d}:00",
            end_time=f"{end_hour:02d}:00",
            buses=buses,
            trips=trips,
            depots=depots,
            charger_types=charger_type_list if charger_type_list else ["slow", "fast"],
            chargers=chargers,
            charge_efficiency=charge_eff,
            pv_gen_kwh=pv_profile,
            grid_price_yen_per_kwh=prices,
            diesel_yen_per_l=diesel_price,
            enable_pv=enable_pv,
            enable_terminal_soc=enable_terminal_soc,
            terminal_soc_kwh=round(cap_kwh * terminal_soc_ratio, 1) if enable_terminal_soc else None,
            enable_demand_charge=enable_demand_charge,
            contract_power_kw=contract_power,
        )
        st.session_state.config = precompute_helpers(cfg)
        st.session_state.result_gurobi = None
        st.session_state.result_alns = None
        st.sidebar.success("設定を適用しました")


# ---------------------------------------------------------------------------
# メインコンテンツ
# ---------------------------------------------------------------------------
st.title("🚌 電気バス運行・充電 最適化シミュレータ")
st.markdown(
    "PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 — 試作アプリケーション"
)

cfg = st.session_state.config

if cfg is None:
    st.info("👈 サイドバーから設定を行い「設定を適用」を押してください。")
    st.stop()

# ---- 設定概要 ----
st.markdown("---")
st.subheader("📋 現在の設定概要")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("バス台数", cfg.num_buses)
col2.metric("便数", cfg.num_trips)
col3.metric("時間スロット数", cfg.num_periods)
col4.metric("充電拠点数", len(cfg.depots))
col5.metric("PV", "有効" if cfg.enable_pv else "無効")

# 設定の詳細表示
with st.expander("🔍 詳細設定を表示"):
    tab_bus, tab_trip, tab_charger, tab_energy = st.tabs(
        ["バス", "便", "充電器", "エネルギー"]
    )
    with tab_bus:
        bus_data = [
            {
                "ID": b.bus_id,
                "カテゴリ": b.category,
                "容量 [kWh]": b.cap_kwh,
                "初期SOC [kWh]": b.soc_init_kwh,
                "SOC下限 [kWh]": b.soc_min_kwh,
                "SOC上限 [kWh]": b.soc_max_kwh,
                "電費 [km/kWh]": b.efficiency_km_per_kwh,
            }
            for b in cfg.buses
        ]
        st.dataframe(pd.DataFrame(bus_data), use_container_width=True)

    with tab_trip:
        labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
        trip_data = [
            {
                "ID": t.trip_id,
                "開始": labels[t.start_t] if t.start_t < len(labels) else t.start_t,
                "終了": labels[min(t.end_t, len(labels)-1)] if t.end_t < len(labels) else t.end_t,
                "消費 [kWh]": t.energy_kwh,
                "出発地": t.start_node,
                "到着地": t.end_node,
            }
            for t in cfg.trips
        ]
        st.dataframe(pd.DataFrame(trip_data), use_container_width=True)

    with tab_charger:
        charger_data = [
            {
                "拠点": c.depot,
                "種別": c.charger_type,
                "出力 [kW]": c.power_kw,
                "台数": c.count,
                "効率": c.efficiency,
            }
            for c in cfg.chargers
        ]
        st.dataframe(pd.DataFrame(charger_data), use_container_width=True)

    with tab_energy:
        energy_df = pd.DataFrame({
            "時刻": labels[:cfg.num_periods],
            "PV発電 [kWh]": cfg.pv_gen_kwh[:cfg.num_periods],
            "電力単価 [円/kWh]": cfg.grid_price_yen_per_kwh[:cfg.num_periods],
        })
        st.dataframe(energy_df, use_container_width=True)

# JSON エクスポート
with st.expander("📦 設定 JSON をエクスポート"):
    cfg_dict = config_to_dict(cfg)
    st.json(cfg_dict)
    st.download_button(
        "設定JSONをダウンロード",
        data=json.dumps(cfg_dict, ensure_ascii=False, indent=2),
        file_name="ebus_config_export.json",
        mime="application/json",
    )


# ---------------------------------------------------------------------------
# ソルバー実行パネル
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("🧮 ソルバー実行")

solver_tab_gurobi, solver_tab_alns, solver_tab_compare = st.tabs(
    ["Gurobi (MILP)", "ALNS", "比較"]
)

# ---- Gurobi タブ ----
with solver_tab_gurobi:
    if not is_gurobi_available():
        st.warning("⚠️ Gurobi (gurobipy) がインストールされていません。ALNS を使用してください。")
    else:
        gcol1, gcol2, gcol3 = st.columns(3)
        with gcol1:
            stage = st.selectbox("ステージ", VALID_STAGES, index=len(VALID_STAGES) - 1)
        with gcol2:
            time_limit = st.number_input("制限時間 [秒]", 10.0, 3600.0, 300.0, step=10.0)
        with gcol3:
            mip_gap = st.number_input("MIP Gap", 0.001, 0.5, 0.01, step=0.005, format="%.3f")

        verbose = st.checkbox("Gurobi ログ表示", value=False)

        if st.button("▶️ Gurobi で求解", type="primary"):
            with st.spinner("Gurobi で最適化中..."):
                result = solve_gurobi(
                    cfg, stage=stage,
                    time_limit_sec=time_limit,
                    mip_gap=mip_gap,
                    verbose=verbose,
                )
                st.session_state.result_gurobi = result

            if result.status == "OPTIMAL":
                st.success(f"✅ 最適解を取得 — 目的関数値: {result.objective_value:,.0f} 円")
            elif result.status == "INFEASIBLE":
                st.error("❌ 実行不能 — 制約を緩和してください")
            else:
                st.warning(f"⚠️ ステータス: {result.status}")

    # 結果表示
    res_g = st.session_state.result_gurobi
    if res_g is not None and res_g.status not in ("UNAVAILABLE", "INFEASIBLE"):
        st.markdown("#### 📊 Gurobi 結果")

        kpi = make_kpi_table(res_g)
        kpi_df = pd.DataFrame([kpi]).T
        kpi_df.columns = ["値"]
        st.table(kpi_df)

        if res_g.soc_series:
            st.plotly_chart(plot_soc_timeseries(cfg, res_g), use_container_width=True)

        if res_g.grid_buy or res_g.pv_use:
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(plot_power_balance(cfg, res_g), use_container_width=True)
            with col_b:
                st.plotly_chart(plot_cost_breakdown(cfg, res_g), use_container_width=True)

        if res_g.assignment:
            st.plotly_chart(plot_assignment_gantt(cfg, res_g), use_container_width=True)

        # 結果ダウンロード
        result_json = json.dumps({
            "solver": res_g.solver_name,
            "status": res_g.status,
            "objective": res_g.objective_value,
            "assignment": res_g.assignment,
            "grid_buy": {str(k): v for k, v in res_g.grid_buy.items()},
            "pv_use": {str(k): v for k, v in res_g.pv_use.items()},
            "soc_series": res_g.soc_series,
        }, ensure_ascii=False, indent=2)
        st.download_button(
            "結果 JSON をダウンロード",
            data=result_json,
            file_name="result_gurobi.json",
            mime="application/json",
        )


# ---- ALNS タブ ----
with solver_tab_alns:
    st.markdown("ALNS (Adaptive Large Neighbourhood Search) — 大規模問題向けメタヒューリスティクス")

    acol1, acol2, acol3 = st.columns(3)
    with acol1:
        alns_iters = st.number_input("最大反復回数", 50, 5000, 500, step=50)
        alns_no_improve = st.number_input("改善なし上限", 10, 1000, 100, step=10)
    with acol2:
        alns_temp = st.number_input("初期温度", 100.0, 10000.0, 1000.0, step=100.0)
        alns_cooling = st.number_input("冷却率", 0.90, 0.999, 0.995, step=0.001, format="%.3f")
    with acol3:
        alns_seed = st.number_input("乱数シード", 0, 9999, 42, step=1)
        alns_destroy_max = st.slider("最大破壊率", 0.1, 0.8, 0.4, step=0.05)

    if st.button("▶️ ALNS で求解", type="primary"):
        params = ALNSParams(
            max_iterations=alns_iters,
            max_no_improve=alns_no_improve,
            init_temp=alns_temp,
            cooling_rate=alns_cooling,
            seed=alns_seed,
            destroy_ratio_max=alns_destroy_max,
        )

        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def alns_callback(it: int, cur: float, best: float):
            progress_bar.progress(min(it / alns_iters, 1.0))
            cost_str = f"{best:,.0f}" if best < float("inf") else "N/A"
            status_text.text(f"反復 {it}/{alns_iters} | 最良: {cost_str} 円")

        result_a = solve_alns(cfg, params=params, callback=alns_callback)
        st.session_state.result_alns = result_a
        progress_bar.progress(1.0)

        if result_a.status == "FEASIBLE":
            st.success(f"✅ 実行可能解を取得 — コスト: {result_a.objective_value:,.0f} 円")
        else:
            st.error(f"❌ ステータス: {result_a.status}")

    res_a = st.session_state.result_alns
    if res_a is not None and res_a.status != "INFEASIBLE":
        st.markdown("#### 📊 ALNS 結果")

        kpi = make_kpi_table(res_a)
        kpi_df = pd.DataFrame([kpi]).T
        kpi_df.columns = ["値"]
        st.table(kpi_df)

        # 収束曲線
        st.plotly_chart(plot_alns_convergence(res_a), use_container_width=True)

        if res_a.soc_series:
            st.plotly_chart(plot_soc_timeseries(cfg, res_a, title="SOC 推移 (ALNS)"), use_container_width=True)

        if res_a.grid_buy or res_a.pv_use:
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(plot_power_balance(cfg, res_a, title="電力バランス (ALNS)"), use_container_width=True)
            with col_b:
                st.plotly_chart(plot_cost_breakdown(cfg, res_a, title="買電コスト (ALNS)"), use_container_width=True)

        if res_a.assignment:
            st.plotly_chart(plot_assignment_gantt(cfg, res_a, title="便割当 (ALNS)"), use_container_width=True)


# ---- 比較タブ ----
with solver_tab_compare:
    st.markdown("### Gurobi vs ALNS 比較")

    res_g = st.session_state.result_gurobi
    res_a = st.session_state.result_alns

    if res_g is None and res_a is None:
        st.info("少なくとも 1 つのソルバーを実行してください。")
    else:
        compare_data = {}
        if res_g is not None:
            compare_data["Gurobi (MILP)"] = make_kpi_table(res_g)
        if res_a is not None:
            compare_data["ALNS"] = make_kpi_table(res_a)

        if compare_data:
            compare_df = pd.DataFrame(compare_data)
            st.table(compare_df)

        # SOC 比較
        if res_g is not None and res_a is not None:
            if res_g.soc_series and res_a.soc_series:
                st.markdown("#### SOC 推移比較")
                import plotly.graph_objects as go
                labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
                labels_ext = labels + ["END"]

                fig = go.Figure()
                for bus_id in res_g.soc_series:
                    fig.add_trace(go.Scatter(
                        x=labels_ext[:len(res_g.soc_series[bus_id])],
                        y=res_g.soc_series[bus_id],
                        name=f"{bus_id} (Gurobi)",
                        mode="lines",
                        line=dict(dash="solid"),
                    ))
                for bus_id in res_a.soc_series:
                    fig.add_trace(go.Scatter(
                        x=labels_ext[:len(res_a.soc_series[bus_id])],
                        y=res_a.soc_series[bus_id],
                        name=f"{bus_id} (ALNS)",
                        mode="lines",
                        line=dict(dash="dash"),
                    ))
                fig.update_layout(
                    title="SOC 推移比較: Gurobi vs ALNS",
                    xaxis_title="時刻",
                    yaxis_title="SOC [kWh]",
                    height=450,
                )
                st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# フッター
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "E-Bus Sim v0.1.0 — PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 試作アプリ"
)
