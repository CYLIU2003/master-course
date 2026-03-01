"""
main.py — Streamlit アプリケーション エントリーポイント

電気バス運行・充電スケジューリング最適化シミュレータ

起動方法:
    streamlit run app/main.py

エラー: python -u app/main.py では動作しません。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 直接 python 実行時の早期エラーメッセージ
# streamlit run 時は sys.modules に 'streamlit' が既にロードされている
_via_streamlit = "streamlit" in sys.modules
if not _via_streamlit and __name__ == "__main__":
    print(
        "\n"
        "[ERROR] このアプリは Streamlit ウェブアプリです。\n"
        "  python -u app/main.py  ← この起動方法は使用できません。\n"
        "\n"
        "正しい起動方法:\n"
        "  streamlit run app/main.py\n"
    )
    sys.exit(1)

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
from app.solver_ga import GAParams, solve_ga
from app.solver_abc import ABCParams, solve_abc
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
# カスタム CSS ・ HTML 基盤
# ---------------------------------------------------------------------------
st.markdown("""
<style>
/* ===== グローバルリセット & ベース ===== */
:root {
    --color-primary:   #1a6fbf;
    --color-accent:    #00a99d;
    --color-warn:      #e07b39;
    --color-bg:        #f5f7fa;
    --color-card:      #ffffff;
    --color-border:    #dde3ec;
    --color-text:      #1f2b3e;
    --color-muted:     #6b7a99;
    --radius:          10px;
    --shadow-sm:       0 2px 6px rgba(0,0,0,.07);
    --shadow-md:       0 4px 16px rgba(0,0,0,.10);
}

/* ページ全体の背景 */
.stApp { background: var(--color-bg) !important; }

/* サイドバー */
[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #1a2942 0%, #243655 100%) !important;
    border-right: 1px solid #1a2942;
}
[data-testid="stSidebar"] * { color: #dce6f5 !important; }
[data-testid="stSidebar"] .stButton > button {
    background: var(--color-accent) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #008f85 !important;
    transform: translateY(-1px);
    box-shadow: var(--shadow-sm);
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] select,
[data-testid="stSidebar"] .stSelectbox > div > div {
    background: rgba(255,255,255,.08) !important;
    color: #dce6f5 !important;
    border: 1px solid rgba(255,255,255,.15) !important;
    border-radius: 6px !important;
}
[data-testid="stSidebar"] .stSlider .stMarkdown p { color: #b8cbdd !important; }

/* ヘッダーバナー */
.ebus-header {
    background: linear-gradient(135deg, #1a2942 0%, #1a6fbf 60%, #00a99d 100%);
    border-radius: var(--radius);
    padding: 28px 36px;
    margin-bottom: 24px;
    box-shadow: var(--shadow-md);
    display: flex;
    align-items: center;
    gap: 18px;
}
.ebus-header-icon { font-size: 3rem; line-height: 1; }
.ebus-header-text h1 {
    margin: 0;
    font-size: 1.9rem;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -.5px;
}
.ebus-header-text p {
    margin: 4px 0 0;
    font-size: .88rem;
    color: rgba(255,255,255,.75);
}
.ebus-badge {
    display: inline-block;
    background: rgba(255,255,255,.15);
    border: 1px solid rgba(255,255,255,.3);
    color: #fff;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: .75rem;
    font-weight: 600;
    margin-top: 8px;
    letter-spacing: .4px;
}

/* カードコンポーネント */
.ebus-card {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 20px 24px;
    box-shadow: var(--shadow-sm);
    margin-bottom: 16px;
}
.ebus-card-title {
    font-size: .8rem;
    font-weight: 700;
    letter-spacing: .8px;
    text-transform: uppercase;
    color: var(--color-muted);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
}

/* KPI メトリクグリッド */
.metric-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 24px;
}
.metric-card {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 16px 18px;
    box-shadow: var(--shadow-sm);
    text-align: center;
    transition: box-shadow .2s;
}
.metric-card:hover { box-shadow: var(--shadow-md); }
.metric-card .metric-label {
    font-size: .75rem;
    font-weight: 600;
    color: var(--color-muted);
    text-transform: uppercase;
    letter-spacing: .6px;
    margin-bottom: 6px;
}
.metric-card .metric-value {
    font-size: 1.75rem;
    font-weight: 800;
    color: var(--color-primary);
    line-height: 1;
}
.metric-card .metric-unit {
    font-size: .7rem;
    color: var(--color-muted);
    margin-top: 3px;
}
.metric-card.accent .metric-value { color: var(--color-accent); }
.metric-card.warn   .metric-value { color: var(--color-warn); }

/* ソルバータブパネル */
.solver-panel {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 24px;
    box-shadow: var(--shadow-sm);
}
.solver-desc {
    font-size: .85rem;
    color: var(--color-muted);
    margin-bottom: 16px;
    padding: 10px 14px;
    background: #f0f5ff;
    border-left: 3px solid var(--color-primary);
    border-radius: 0 6px 6px 0;
}

/* セクションヘッダー */
.section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 24px 0 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--color-border);
}
.section-header h3 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--color-text);
}
.section-header .section-icon {
    width: 28px; height: 28px;
    background: var(--color-primary);
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    color: #fff; font-size: .9rem;
}

/* 比較テーブル */
.compare-table-wrap {
    overflow-x: auto;
    border-radius: var(--radius);
    border: 1px solid var(--color-border);
    box-shadow: var(--shadow-sm);
}
.compare-table-wrap table {
    width: 100%;
    border-collapse: collapse;
    font-size: .88rem;
}
.compare-table-wrap th {
    background: var(--color-primary);
    color: #fff;
    padding: 10px 14px;
    text-align: left;
    font-weight: 700;
    letter-spacing: .3px;
}
.compare-table-wrap td {
    padding: 9px 14px;
    border-bottom: 1px solid var(--color-border);
    color: var(--color-text);
}
.compare-table-wrap tr:last-child td { border-bottom: none; }
.compare-table-wrap tr:hover td { background: #f8fafc; }

/* インフォボックス */
.info-box {
    background: #eef5ff;
    border: 1px solid #b3d0ff;
    border-radius: var(--radius);
    padding: 16px 20px;
    font-size: .88rem;
    color: var(--color-text);
    display: flex;
    gap: 10px;
    align-items: flex-start;
}
.info-box .info-icon { font-size: 1.2rem; flex-shrink: 0; margin-top: 1px; }

/* フッター */
.ebus-footer {
    margin-top: 40px;
    padding: 16px 24px;
    background: var(--color-card);
    border-top: 1px solid var(--color-border);
    border-radius: var(--radius);
    font-size: .75rem;
    color: var(--color-muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

/* Streamlit デフォルト要素の調整 */
.stButton > button {
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
    transition: all .2s !important;
}
.stButton > button[kind="primary"] {
    background: var(--color-primary) !important;
    border-color: var(--color-primary) !important;
}
.stButton > button[kind="primary"]:hover {
    background: #155aa8 !important;
    transform: translateY(-1px);
    box-shadow: var(--shadow-sm);
}
[data-testid="stMetric"] {
    background: var(--color-card);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    padding: 16px;
    box-shadow: var(--shadow-sm);
}
[data-testid="stExpander"] {
    background: var(--color-card);
    border: 1px solid var(--color-border) !important;
    border-radius: var(--radius) !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    gap: 4px;
    border-bottom: 2px solid var(--color-border);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    padding: 8px 18px;
    font-weight: 600;
    font-size: .88rem;
}
.stTabs [aria-selected="true"] {
    background: var(--color-primary) !important;
    color: white !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# セッション初期化
# ---------------------------------------------------------------------------
if "config" not in st.session_state:
    st.session_state.config = None
if "result_gurobi" not in st.session_state:
    st.session_state.result_gurobi = None
if "result_alns" not in st.session_state:
    st.session_state.result_alns = None
if "result_ga" not in st.session_state:
    st.session_state.result_ga = None
if "result_abc" not in st.session_state:
    st.session_state.result_abc = None



# ---------------------------------------------------------------------------
# サイドバー: 設定モード選択 (最小化)
# ---------------------------------------------------------------------------
st.sidebar.markdown("""
<div style="text-align:center; padding: 12px 0 8px;">
  <span style="font-size:2rem;">🚌</span><br>
  <span style="font-size:.95rem; font-weight:700; letter-spacing:.5px;">E-Bus Sim</span>
</div>
""", unsafe_allow_html=True)

config_mode = st.sidebar.radio(
    "設定方法",
    ["手動設定", "JSON インポート"],
    help="手動で調整するか、既存 JSON を読み込むか選択",
)

if config_mode == "JSON インポート":
    uploaded = st.sidebar.file_uploader(
        "設定 JSON をアップロード",
        type=["json"],
        help="ebus_prototype_config.json 形式",
    )
    default_json = Path(__file__).resolve().parent.parent / "config" / "ebus_prototype_config.json"
    if uploaded is not None:
        raw = json.loads(uploaded.read().decode("utf-8"))
        tmp_path = Path(__file__).resolve().parent / "_tmp_upload.json"
        tmp_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        st.session_state.config = load_config_from_json(tmp_path)
        st.sidebar.success("✅ JSON を読み込みました")
    elif default_json.exists():
        if st.sidebar.button("デフォルト JSON を読み込む"):
            st.session_state.config = load_config_from_json(default_json)
            st.sidebar.success("✅ デフォルト設定を読み込みました")

# サイドバーステータス
st.sidebar.markdown("---")
if st.session_state.config is not None:
    st.sidebar.success("✅ 設定適用済み")
elif config_mode == "手動設定":
    st.sidebar.info("⚙️ 設定タブで設定を適用してください")


# ---------------------------------------------------------------------------
# メインコンテンツ
# ---------------------------------------------------------------------------

# ヘッダーバナー
st.markdown("""
<div class="ebus-header">
  <div class="ebus-header-icon">🚌</div>
  <div class="ebus-header-text">
    <h1>E-Bus Sim — 電気バス最適化シミュレータ</h1>
    <p>PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 — 試作アプリケーション</p>
    <span class="ebus-badge">v0.3.0&nbsp;•&nbsp;Route-Editable&nbsp;•&nbsp;Gurobi / ALNS / GA / ABC</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ===========================================================================
# タブ構成: 設定 → ソルバー → 比較
# ===========================================================================
tab_settings, solver_tab_gurobi, solver_tab_alns, solver_tab_ga, solver_tab_abc, solver_tab_src, solver_tab_compare, solver_tab_milp_only, solver_tab_alns_only, solver_tab_alns_milp, tab_map = st.tabs(
    ["⚙️ 設定", "🔬 Gurobi (MILP)", "🎡 ALNS", "🧬 GA", "🐝 ABC", "🆕 新アーキ (src/)", "📊 比較",
     "🎯 MILP専用", "🔄 ALNS専用", "⚡ ALNS+MILP", "�️ 路線詳細"]
)

# ===========================================================================
# ⚙️ 設定タブ
# ===========================================================================
with tab_settings:
    if config_mode == "JSON インポート":
        # --- JSON インポートモード ---
        if st.session_state.config is not None:
            st.success("✅ JSON を読み込み済みです。サイドバーから別の JSON を読み込めます。")
        else:
            st.info("サイドバーから JSON ファイルを読み込んでください。")
    else:
        # --- 手動設定モード ---
        st.markdown("""
        <div class="section-header">
          <div class="section-icon">⚙️</div>
          <h3>シミュレーション設定</h3>
        </div>
        """, unsafe_allow_html=True)

        # ---- 📐 システム規模 ----
        with st.expander("📐 システム規模", expanded=True):
            sc1, sc2, sc3, sc4 = st.columns(4)
            with sc1:
                num_buses = st.number_input("バス台数", 1, 20, 3, key="cfg_num_buses")
            with sc2:
                num_trips = st.number_input("便数", 1, 30, 6, key="cfg_num_trips")
            with sc3:
                delta_h = st.selectbox("時間刻み [h]", [0.25, 0.5, 1.0], index=1, key="cfg_delta_h")
            with sc4:
                pass
            sc5, sc6 = st.columns(2)
            with sc5:
                start_hour = st.slider("開始時刻", 0, 12, 6, key="cfg_start_hour")
            with sc6:
                end_hour = st.slider("終了時刻", 12, 24, 22, key="cfg_end_hour")
            num_periods = int((end_hour - start_hour) / delta_h)
            st.caption(f"📊 計画スロット数: **{num_periods}** ({start_hour}:00 〜 {end_hour}:00, Δt={delta_h}h)")

        # ---- 🚌 車両性能 ----
        with st.expander("🚌 車両性能"):
            vc1, vc2 = st.columns(2)
            with vc1:
                cap_kwh = st.number_input("バッテリ容量 [kWh]", 50.0, 1000.0, 300.0, step=10.0, key="cfg_cap")
                soc_init_ratio = st.slider("初期 SOC [%]", 30, 100, 80, key="cfg_soc_init") / 100.0
            with vc2:
                efficiency = st.number_input("電費 [km/kWh]", 0.3, 3.0, 1.0, step=0.1, key="cfg_eff")
                soc_min_ratio = st.slider("SOC 下限 [%]", 5, 50, 20, key="cfg_soc_min") / 100.0
            soc_max_ratio = st.slider("SOC 上限 [%]", 60, 100, 95, key="cfg_soc_max") / 100.0

        # ---- 🛣️ 路線設定 ----
        with st.expander("🛣️ 路線詳細設定", expanded=False):
            st.markdown("""
            路線・停留所・セグメント・車庫を編集します。  
            「単純編集」でテーブル入力、「地図入力」で地図上クリック配置が選べます。
            """)
            from app.route_detail_editor import render_route_detail_editor
            render_route_detail_editor(data_dir="data")

        # ---- 🔌 充電設備 ----
        with st.expander("🔌 充電設備"):
            cc1, cc2 = st.columns(2)
            with cc1:
                num_depots = st.slider("充電拠点数", 1, 5, 2, key="cfg_depots")
                slow_power = st.number_input("普通充電出力 [kW]", 10.0, 200.0, 50.0, step=10.0, key="cfg_slow_pw")
                slow_count = st.number_input("普通充電器台数", 0, 10, 2, step=1, key="cfg_slow_cnt")
            with cc2:
                charge_eff = st.slider("充電効率", 0.80, 1.00, 0.95, step=0.01, key="cfg_ch_eff")
                fast_power = st.number_input("急速充電出力 [kW]", 50.0, 500.0, 150.0, step=10.0, key="cfg_fast_pw")
                fast_count = st.number_input("急速充電器台数", 0, 10, 1, step=1, key="cfg_fast_cnt")

        # ---- ☀️ エネルギー ----
        with st.expander("☀️ PV・電力料金"):
            ec1, ec2 = st.columns(2)
            with ec1:
                enable_pv = st.checkbox("PV を有効にする", value=True, key="cfg_enable_pv")
                pv_scale = st.slider("PV 出力倍率", 0.0, 5.0, 1.0, step=0.1, key="cfg_pv_scale")
            with ec2:
                price_mode = st.selectbox("電力料金モード", ["デフォルト TOU", "一律 [円/kWh]"], key="cfg_price_mode")
                flat_price = 25.0
                if price_mode == "一律 [円/kWh]":
                    flat_price = st.number_input("電力単価 [円/kWh]", 10.0, 100.0, 25.0, step=1.0, key="cfg_flat_price")
            diesel_price = st.number_input("軽油単価 [円/L]", 80.0, 250.0, 145.0, step=5.0, key="cfg_diesel", help="ICE 比較用")

        # ---- 🔧 拡張オプション ----
        with st.expander("🔧 拡張オプション"):
            oc1, oc2 = st.columns(2)
            with oc1:
                enable_terminal_soc = st.checkbox("終端 SOC 条件", value=False, key="cfg_term_soc")
                terminal_soc_ratio = 0.5
                if enable_terminal_soc:
                    terminal_soc_ratio = st.slider("終端 SOC [%]", 20, 80, 50, key="cfg_term_ratio") / 100.0
            with oc2:
                enable_demand_charge = st.checkbox("デマンドチャージ", value=False, key="cfg_demand")
                contract_power = None
                if enable_demand_charge:
                    contract_power = st.number_input("契約電力上限 [kW]", 50.0, 1000.0, 200.0, step=10.0, key="cfg_contract")

        # ---- 🔄 設定を適用ボタン ----
        st.markdown("---")
        if st.button("🔄 設定を適用", type="primary", key="apply_config", use_container_width=True):
            import random as _rng
            import math

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
                    soc_max_kwh=round(cap_kwh * soc_max_ratio, 1),
                    efficiency_km_per_kwh=efficiency,
                ))

            trips = []
            for i in range(num_trips):
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

            pv_profile = []
            for t in range(num_periods):
                hour = start_hour + t * delta_h
                if 6 <= hour <= 18:
                    val = 60.0 * math.exp(-0.5 * ((hour - 12.0) / 3.0) ** 2)
                else:
                    val = 0.0
                pv_profile.append(round(val * pv_scale, 2))

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

            _new_cfg = ProblemConfig(
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
            st.session_state.config = precompute_helpers(_new_cfg)
            st.session_state.result_gurobi = None
            st.session_state.result_alns = None
            st.session_state.result_ga = None
            st.session_state.result_abc = None
            st.success("✅ 設定を適用しました")

    # ---- 現在の設定概要 (常に表示) ----
    cfg = st.session_state.config
    if cfg is not None:
        st.markdown("""
        <div class="section-header">
          <div class="section-icon">📊</div>
          <h3>現在の設定概要</h3>
        </div>
        """, unsafe_allow_html=True)

        pv_status = "✅ 有効" if cfg.enable_pv else "❌ 無効"
        demand_status = "✅ 有効" if cfg.enable_demand_charge else "—"

        st.markdown(f"""
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">🚌 バス台数</div>
            <div class="metric-value">{cfg.num_buses}</div>
            <div class="metric-unit">台</div>
          </div>
          <div class="metric-card accent">
            <div class="metric-label">🗓️ 便数</div>
            <div class="metric-value">{cfg.num_trips}</div>
            <div class="metric-unit">本</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">⏱️ 時間スロット</div>
            <div class="metric-value">{cfg.num_periods}</div>
            <div class="metric-unit">スロット ({cfg.delta_h}h)</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">🔌 充電拠点数</div>
            <div class="metric-value">{len(cfg.depots)}</div>
            <div class="metric-unit">拠点</div>
          </div>
          <div class="metric-card {'accent' if cfg.enable_pv else 'warn'}">
            <div class="metric-label">☀️ PV</div>
            <div class="metric-value" style="font-size:1.3rem">{pv_status}</div>
            <div class="metric-unit">デマンド: {demand_status}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

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
                _labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
                energy_df = pd.DataFrame({
                    "時刻": _labels[:cfg.num_periods],
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

# ---- cfg 参照を更新 ----
cfg = st.session_state.config


# ---- Gurobi タブ ----
with solver_tab_gurobi:
    if cfg is None:
        st.warning("⚙️ 設定タブでパラメータを設定し「🔄 設定を適用」を押してください。")
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
    if cfg is None:
        st.warning("⚙️ 設定タブでパラメータを設定し「🔄 設定を適用」を押してください。")
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


# ---- GA タブ ----
with solver_tab_ga:
    if cfg is None:
        st.warning("⚙️ 設定タブでパラメータを設定し「🔄 設定を適用」を押してください。")
    st.markdown("GA (遺伝的アルゴリズム) — 集団ベース進化的最適化。コスト・時間の比較用。")

    gc1, gc2, gc3 = st.columns(3)
    with gc1:
        ga_pop = st.number_input("集団サイズ", 10, 200, 30, step=10, key="ga_pop")
        ga_gens = st.number_input("最大世代数", 20, 2000, 200, step=20, key="ga_gens")
    with gc2:
        ga_cross = st.number_input("交叉率", 0.5, 1.0, 0.85, step=0.05, format="%.2f", key="ga_cross")
        ga_mut = st.number_input("突然変異率", 0.01, 0.5, 0.15, step=0.01, format="%.2f", key="ga_mut")
    with gc3:
        ga_tourn = st.number_input("トーナメントサイズ", 2, 10, 3, step=1, key="ga_tourn")
        ga_elite = st.number_input("エリート数", 1, 10, 2, step=1, key="ga_elite")
        ga_seed = st.number_input("乱数シード", 0, 9999, 42, step=1, key="ga_seed")

    ga_no_improve = st.number_input("改善なし上限", 10, 500, 50, step=10, key="ga_no_improve")

    if st.button("▶️ GA で求解", type="primary"):
        ga_params = GAParams(
            population_size=ga_pop,
            max_generations=ga_gens,
            max_no_improve=ga_no_improve,
            crossover_rate=ga_cross,
            mutation_rate=ga_mut,
            tournament_size=ga_tourn,
            elitism_count=ga_elite,
            seed=ga_seed,
        )

        progress_bar_ga = st.progress(0.0)
        status_text_ga = st.empty()

        def ga_callback(gen: int, cur: float, best: float):
            progress_bar_ga.progress(min(gen / ga_gens, 1.0))
            cost_str = f"{best:,.0f}" if best < float("inf") else "N/A"
            status_text_ga.text(f"世代 {gen}/{ga_gens} | 最良: {cost_str} 円")

        result_ga = solve_ga(cfg, params=ga_params, callback=ga_callback)
        st.session_state.result_ga = result_ga
        progress_bar_ga.progress(1.0)

        if result_ga.status == "FEASIBLE":
            st.success(f"✅ 実行可能解を取得 — コスト: {result_ga.objective_value:,.0f} 円")
        else:
            st.error(f"❌ ステータス: {result_ga.status}")

    res_ga = st.session_state.result_ga
    if res_ga is not None and res_ga.status != "INFEASIBLE":
        st.markdown("#### 📊 GA 結果")

        kpi = make_kpi_table(res_ga)
        kpi_df = pd.DataFrame([kpi]).T
        kpi_df.columns = ["値"]
        st.table(kpi_df)

        # 収束曲線
        st.plotly_chart(plot_alns_convergence(res_ga, title="GA 収束曲線"), use_container_width=True)

        if res_ga.soc_series:
            st.plotly_chart(plot_soc_timeseries(cfg, res_ga, title="SOC 推移 (GA)"), use_container_width=True)

        if res_ga.grid_buy or res_ga.pv_use:
            col_ga1, col_ga2 = st.columns(2)
            with col_ga1:
                st.plotly_chart(plot_power_balance(cfg, res_ga, title="電力バランス (GA)"), use_container_width=True)
            with col_ga2:
                st.plotly_chart(plot_cost_breakdown(cfg, res_ga, title="買電コスト (GA)"), use_container_width=True)

        if res_ga.assignment:
            st.plotly_chart(plot_assignment_gantt(cfg, res_ga, title="便割当 (GA)"), use_container_width=True)


# ---- ABC タブ ----
with solver_tab_abc:
    if cfg is None:
        st.warning("⚙️ 設定タブでパラメータを設定し「🔄 設定を適用」を押してください。")
    st.markdown("ABC (人工蜂コロニー) — 群知能ベース最適化。コスト・時間の比較用。")

    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        abc_colony = st.number_input("コロニーサイズ（食料源数）", 10, 200, 30, step=10, key="abc_colony")
        abc_iters = st.number_input("最大サイクル数", 20, 2000, 200, step=20, key="abc_iters")
    with ac2:
        abc_limit = st.number_input("limit（偵察蜂発動閾値）", 5, 100, 20, step=5, key="abc_limit")
        abc_perturb = st.slider("近傍変更便数", 1, 10, 3, key="abc_perturb")
    with ac3:
        abc_no_improve = st.number_input("改善なし上限", 10, 500, 50, step=10, key="abc_no_improve")
        abc_seed = st.number_input("乱数シード", 0, 9999, 42, step=1, key="abc_seed")

    if st.button("▶️ ABC で求解", type="primary"):
        abc_params = ABCParams(
            colony_size=abc_colony,
            max_iterations=abc_iters,
            max_no_improve=abc_no_improve,
            limit=abc_limit,
            perturbation_size=abc_perturb,
            seed=abc_seed,
        )

        progress_bar_abc = st.progress(0.0)
        status_text_abc = st.empty()

        def abc_callback(cyc: int, cur: float, best: float):
            progress_bar_abc.progress(min(cyc / abc_iters, 1.0))
            cost_str = f"{best:,.0f}" if best < float("inf") else "N/A"
            status_text_abc.text(f"サイクル {cyc}/{abc_iters} | 最良: {cost_str} 円")

        result_abc = solve_abc(cfg, params=abc_params, callback=abc_callback)
        st.session_state.result_abc = result_abc
        progress_bar_abc.progress(1.0)

        if result_abc.status == "FEASIBLE":
            st.success(f"✅ 実行可能解を取得 — コスト: {result_abc.objective_value:,.0f} 円")
        else:
            st.error(f"❌ ステータス: {result_abc.status}")

    res_abc = st.session_state.result_abc
    if res_abc is not None and res_abc.status != "INFEASIBLE":
        st.markdown("#### 📊 ABC 結果")

        kpi = make_kpi_table(res_abc)
        kpi_df = pd.DataFrame([kpi]).T
        kpi_df.columns = ["値"]
        st.table(kpi_df)

        # 収束曲線
        st.plotly_chart(plot_alns_convergence(res_abc, title="ABC 収束曲線"), use_container_width=True)

        if res_abc.soc_series:
            st.plotly_chart(plot_soc_timeseries(cfg, res_abc, title="SOC 推移 (ABC)"), use_container_width=True)

        if res_abc.grid_buy or res_abc.pv_use:
            col_abc1, col_abc2 = st.columns(2)
            with col_abc1:
                st.plotly_chart(plot_power_balance(cfg, res_abc, title="電力バランス (ABC)"), use_container_width=True)
            with col_abc2:
                st.plotly_chart(plot_cost_breakdown(cfg, res_abc, title="買電コスト (ABC)"), use_container_width=True)

        if res_abc.assignment:
            st.plotly_chart(plot_assignment_gantt(cfg, res_abc, title="便割当 (ABC)"), use_container_width=True)


# ---- 新アーキテクチャ (src/) タブ ----
with solver_tab_src:
    st.markdown("""
    <div class="solver-desc">
    <b>新アーキテクチャ (src/)</b> — CSV ベースのデータ読込、モード切替 (mode_A / mode_B / thesis_mode)、
    ALNS 比較実験、実行可能性診断を統合したパネルです。
    </div>
    """, unsafe_allow_html=True)

    # --- セッション初期化 ---
    if "src_data" not in st.session_state:
        st.session_state.src_data = None
    if "src_milp_result" not in st.session_state:
        st.session_state.src_milp_result = None
    if "src_alns_result" not in st.session_state:
        st.session_state.src_alns_result = None
    if "src_sim_result" not in st.session_state:
        st.session_state.src_sim_result = None

    # --- データ読込 ---
    st.markdown("##### 📂 データ読込")
    src_config_path = st.text_input(
        "config JSON パス",
        value="config/experiment_config.json",
        key="src_config_path",
        help="config/experiment_config.json 形式の設定ファイル",
    )

    src_col1, src_col2 = st.columns(2)
    with src_col1:
        src_enable_pv = st.checkbox("PV 有効", value=True, key="src_pv")
        src_enable_demand = st.checkbox("デマンド料金", value=True, key="src_demand")
    with src_col2:
        src_enable_v2g = st.checkbox("V2G", value=False, key="src_v2g")
        src_enable_deg = st.checkbox("電池劣化", value=True, key="src_deg")

    if st.button("📥 データ読込", key="src_load"):
        try:
            from src.data_loader import load_problem_data
            from src.model_sets import build_model_sets
            from src.parameter_builder import build_derived_params

            _src_data = load_problem_data(src_config_path)
            _src_data.enable_pv = src_enable_pv
            _src_data.enable_demand_charge = src_enable_demand
            _src_data.enable_v2g = src_enable_v2g
            _src_data.enable_battery_degradation = src_enable_deg

            _src_ms = build_model_sets(_src_data)
            _src_dp = build_derived_params(_src_data, _src_ms)
            st.session_state.src_data = (_src_data, _src_ms, _src_dp)
            st.session_state.src_milp_result = None
            st.session_state.src_alns_result = None
            st.session_state.src_sim_result = None
            st.success(
                f"✅ データ読込完了: BEV {len(_src_ms.K_BEV)} 台, ICE {len(_src_ms.K_ICE)} 台, "
                f"タスク {len(_src_ms.R)} 件, 充電器 {len(_src_ms.C)} 基, "
                f"スロット {_src_data.num_periods}"
            )
        except Exception as e:
            st.error(f"❌ データ読込エラー: {e}")

    if st.session_state.src_data is not None:
        _src_data, _src_ms, _src_dp = st.session_state.src_data

        st.markdown("---")
        st.markdown("##### 🧠 モード選択 & 求解")

        from src.model_factory import AVAILABLE_MODES, MODE_DESCRIPTIONS

        src_mode = st.selectbox(
            "モデルモード",
            AVAILABLE_MODES,
            index=2,  # thesis_mode
            format_func=lambda m: f"{m}",
            key="src_mode",
        )
        st.caption(MODE_DESCRIPTIONS.get(src_mode, ""))

        src_solver = st.radio(
            "ソルバー",
            ["Gurobi (MILP)", "ALNS", "両方 (比較)"],
            horizontal=True,
            key="src_solver",
        )

        src_sc1, src_sc2 = st.columns(2)
        with src_sc1:
            src_time_limit = st.number_input("MILP 制限時間 [秒]", 10.0, 3600.0, 120.0, step=10.0, key="src_tlim")
        with src_sc2:
            src_alns_iters = st.number_input("ALNS 反復回数", 20, 5000, 200, step=50, key="src_alns_it")

        if st.button("▶️ 求解実行", type="primary", key="src_solve"):
            run_milp = src_solver in ("Gurobi (MILP)", "両方 (比較)")
            run_alns = src_solver in ("ALNS", "両方 (比較)")

            # --- MILP ---
            if run_milp:
                with st.spinner("Gurobi (src/) で最適化中..."):
                    try:
                        from src.model_factory import build_model_by_mode, generate_greedy_assignment
                        from src.milp_model import extract_result as _extract
                        from src.simulator import simulate as _simulate
                        import time as _time

                        if src_mode == "mode_A_journey_charge":
                            fixed = generate_greedy_assignment(_src_data, _src_ms, _src_dp)
                            _model, _vars = build_model_by_mode(
                                src_mode, _src_data, _src_ms, _src_dp, fixed_assignment=fixed
                            )
                        else:
                            _model, _vars = build_model_by_mode(
                                src_mode, _src_data, _src_ms, _src_dp
                            )
                        _model.Params.OutputFlag = 0
                        _model.Params.TimeLimit = src_time_limit
                        _t0 = _time.perf_counter()
                        _model.optimize()
                        _elapsed = _time.perf_counter() - _t0
                        _milp_res = _extract(_model, _src_data, _src_ms, _src_dp, _vars, _elapsed)
                        st.session_state.src_milp_result = _milp_res

                        _sim = _simulate(_src_data, _src_ms, _src_dp, _milp_res)
                        st.session_state.src_sim_result = _sim

                        if _milp_res.status == "OPTIMAL":
                            st.success(f"✅ MILP OPTIMAL — {_milp_res.objective_value:,.0f} 円 ({_elapsed:.2f}s)")
                        elif _milp_res.status == "INFEASIBLE":
                            st.error(f"❌ INFEASIBLE: {_milp_res.infeasibility_info}")
                        else:
                            st.warning(f"⚠️ Status: {_milp_res.status}")
                    except Exception as e:
                        st.error(f"❌ MILP エラー: {e}")

            # --- ALNS ---
            if run_alns:
                with st.spinner("ALNS (src/) で最適化中..."):
                    try:
                        from src.solver_alns import solve_alns as _solve_alns
                        from src.solver_alns import ALNSParams as _ALNSParams

                        _alns_params = _ALNSParams(
                            max_iterations=src_alns_iters,
                            max_no_improve=max(src_alns_iters // 5, 20),
                        )
                        _alns_res = _solve_alns(_src_data, _src_ms, _src_dp, params=_alns_params)
                        st.session_state.src_alns_result = _alns_res

                        if _alns_res.status == "FEASIBLE":
                            st.success(f"✅ ALNS FEASIBLE — {_alns_res.objective_value:,.0f} 円 ({_alns_res.solve_time_sec:.2f}s)")
                        else:
                            st.error(f"❌ ALNS Status: {_alns_res.status}")
                    except Exception as e:
                        st.error(f"❌ ALNS エラー: {e}")

        # --- 結果表示 ---
        _milp_res = st.session_state.src_milp_result
        _alns_res = st.session_state.src_alns_result
        _sim_res = st.session_state.src_sim_result

        if _milp_res is not None or _alns_res is not None:
            st.markdown("---")
            st.markdown("##### 📊 結果")

            # KPI 比較テーブル
            _src_kpi = {}
            if _milp_res is not None and _milp_res.objective_value is not None:
                _src_kpi["MILP"] = {
                    "ステータス": _milp_res.status,
                    "目的関数値 [円]": f"{_milp_res.objective_value:,.0f}",
                    "計算時間 [秒]": f"{_milp_res.solve_time_sec:.2f}",
                    "割当タスク数": sum(len(v) for v in _milp_res.assignment.values()),
                    "未割当": len(_milp_res.unserved_tasks),
                }
            if _alns_res is not None and _alns_res.objective_value is not None:
                _src_kpi["ALNS"] = {
                    "ステータス": _alns_res.status,
                    "目的関数値 [円]": f"{_alns_res.objective_value:,.0f}",
                    "計算時間 [秒]": f"{_alns_res.solve_time_sec:.2f}",
                    "割当タスク数": sum(len(v) for v in _alns_res.assignment.values()),
                    "未割当": len(_alns_res.unserved_tasks),
                }
            if _src_kpi:
                st.dataframe(pd.DataFrame(_src_kpi), use_container_width=True)

            # シミュレーション結果
            if _sim_res is not None:
                st.markdown("##### 📈 シミュレーション評価")
                sm1, sm2, sm3, sm4 = st.columns(4)
                with sm1:
                    st.metric("タスク担当率", f"{_sim_res.served_task_ratio*100:.1f}%")
                with sm2:
                    st.metric("系統受電量", f"{_sim_res.total_grid_kwh:.1f} kWh")
                with sm3:
                    st.metric("電力量料金", f"¥{_sim_res.total_energy_cost:,.0f}")
                with sm4:
                    st.metric("デマンド料金", f"¥{_sim_res.total_demand_charge:,.0f}")

                sm5, sm6, sm7, sm8 = st.columns(4)
                with sm5:
                    st.metric("劣化コスト", f"¥{_sim_res.total_degradation_cost:,.0f}")
                with sm6:
                    st.metric("総コスト", f"¥{_sim_res.total_operating_cost:,.0f}")
                with sm7:
                    st.metric("SOC 最低値", f"{_sim_res.soc_min_kwh:.1f} kWh")
                with sm8:
                    st.metric("SOC 違反", f"{len(_sim_res.soc_violations)} 件")

            # 実行可能性診断
            if _sim_res is not None and _sim_res.feasibility_report is not None:
                with st.expander("🔍 実行可能性診断 (Feasibility Report)"):
                    st.text(_sim_res.feasibility_report.summary())

            # グラフ (MILP 結果の SOC 推移)
            if _milp_res is not None and _milp_res.soc_series:
                st.markdown("##### SOC 推移 (src/ MILP)")
                import plotly.graph_objects as _pgo
                _fig_soc = _pgo.Figure()
                for _k, _soc in _milp_res.soc_series.items():
                    _fig_soc.add_trace(_pgo.Scatter(
                        x=list(range(len(_soc))),
                        y=_soc,
                        name=_k,
                        mode="lines",
                    ))
                _veh0 = list(_src_dp.vehicle_lut.values())[0] if _src_dp.vehicle_lut else None
                if _veh0 and _veh0.soc_min is not None:
                    _fig_soc.add_hline(y=_veh0.soc_min, line_dash="dash", line_color="red",
                                       annotation_text="SOC 下限")
                _fig_soc.update_layout(
                    title="SOC 推移 [kWh]",
                    xaxis_title="time_idx",
                    yaxis_title="SOC [kWh]",
                    height=400,
                )
                st.plotly_chart(_fig_soc, use_container_width=True)

            # 系統受電グラフ
            if _milp_res is not None and _milp_res.grid_import_kw:
                st.markdown("##### 系統受電電力 (src/ MILP)")
                _fig_grid = _pgo.Figure()
                for _site, _series in _milp_res.grid_import_kw.items():
                    _fig_grid.add_trace(_pgo.Scatter(
                        x=list(range(len(_series))),
                        y=_series,
                        name=f"Grid {_site}",
                        mode="lines+markers",
                    ))
                if _milp_res.pv_used_kw:
                    for _site, _series in _milp_res.pv_used_kw.items():
                        _fig_grid.add_trace(_pgo.Scatter(
                            x=list(range(len(_series))),
                            y=_series,
                            name=f"PV {_site}",
                            fill="tozeroy",
                            line=dict(dash="dot"),
                        ))
                _fig_grid.update_layout(
                    title="受電電力 & PV 自家消費 [kW]",
                    xaxis_title="time_idx",
                    yaxis_title="[kW]",
                    height=400,
                )
                st.plotly_chart(_fig_grid, use_container_width=True)

            # 割当ガントチャート
            if _milp_res is not None and _milp_res.assignment:
                st.markdown("##### 車両運行ガントチャート (src/ MILP)")
                _gantt_data = []
                for _k, _tasks in _milp_res.assignment.items():
                    for _r in _tasks:
                        _t = _src_dp.task_lut.get(_r)
                        if _t:
                            _gantt_data.append({
                                "車両": _k,
                                "タスク": _r,
                                "開始": _t.start_time_idx,
                                "終了": _t.end_time_idx,
                            })
                if _gantt_data:
                    _gdf = pd.DataFrame(_gantt_data)
                    _fig_gantt = _pgo.Figure()
                    _colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#F44336", "#00BCD4", "#795548", "#607D8B"]
                    for _i, _k in enumerate(sorted(_gdf["車両"].unique())):
                        _kdf = _gdf[_gdf["車両"] == _k]
                        for _, _row in _kdf.iterrows():
                            _fig_gantt.add_trace(_pgo.Bar(
                                x=[_row["終了"] - _row["開始"] + 1],
                                y=[_k],
                                base=_row["開始"],
                                orientation="h",
                                name=_row["タスク"],
                                marker_color=_colors[_i % len(_colors)],
                                text=_row["タスク"],
                                textposition="inside",
                                showlegend=False,
                                hovertext=f"{_row['タスク']} ({_row['開始']}-{_row['終了']})",
                            ))
                    _fig_gantt.update_layout(
                        title="車両運行ガントチャート",
                        xaxis_title="time_idx",
                        barmode="stack",
                        height=max(250, len(_milp_res.assignment) * 60),
                    )
                    st.plotly_chart(_fig_gantt, use_container_width=True)


# ---- 比較タブ ----
with solver_tab_compare:
    st.markdown("### 全ソルバー比較 — コスト・計算時間")

    res_g = st.session_state.result_gurobi
    res_a = st.session_state.result_alns
    res_ga = st.session_state.result_ga
    res_abc = st.session_state.result_abc

    all_results = {
        "Gurobi (MILP)": res_g,
        "ALNS": res_a,
        "GA": res_ga,
        "ABC": res_abc,
    }
    available = {k: v for k, v in all_results.items() if v is not None}

    if not available:
        st.info("少なくとも 1 つのソルバーを実行してください。")
    else:
        # ---- KPI 比較テーブル ----
        compare_data = {}
        for name, res in available.items():
            compare_data[name] = make_kpi_table(res)
        compare_df = pd.DataFrame(compare_data)
        st.table(compare_df)

        # ---- コスト比較棒グラフ ----
        st.markdown("#### 目的関数値（総コスト）比較")
        import plotly.graph_objects as go

        cost_names = []
        cost_vals = []
        cost_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
        for i, (name, res) in enumerate(available.items()):
            if res.objective_value is not None:
                cost_names.append(name)
                cost_vals.append(res.objective_value)

        if cost_vals:
            fig_cost = go.Figure(go.Bar(
                x=cost_names,
                y=cost_vals,
                marker_color=cost_colors[:len(cost_names)],
                text=[f"{v:,.0f}" for v in cost_vals],
                textposition="auto",
            ))
            fig_cost.update_layout(
                title="ソルバー別 目的関数値 [円]",
                yaxis_title="コスト [円]",
                height=400,
            )
            st.plotly_chart(fig_cost, use_container_width=True)

        # ---- 計算時間比較 ----
        st.markdown("#### 計算時間比較")
        time_names = []
        time_vals = []
        for name, res in available.items():
            time_names.append(name)
            time_vals.append(res.solve_time_sec)

        if time_vals:
            fig_time = go.Figure(go.Bar(
                x=time_names,
                y=time_vals,
                marker_color=cost_colors[:len(time_names)],
                text=[f"{v:.2f}s" for v in time_vals],
                textposition="auto",
            ))
            fig_time.update_layout(
                title="ソルバー別 計算時間 [秒]",
                yaxis_title="時間 [秒]",
                height=400,
            )
            st.plotly_chart(fig_time, use_container_width=True)

        # ---- 収束曲線比較（メタヒューリスティクス同士）----
        meta_results = {k: v for k, v in available.items() if v.iteration_log}
        if len(meta_results) >= 2:
            st.markdown("#### 収束曲線比較")
            fig_conv = go.Figure()
            line_styles = ["solid", "dash", "dot", "dashdot"]
            for i, (name, res) in enumerate(meta_results.items()):
                iters = [e["iteration"] for e in res.iteration_log]
                bests = [e.get("best_cost") for e in res.iteration_log]
                fig_conv.add_trace(go.Scatter(
                    x=iters,
                    y=bests,
                    mode="lines",
                    name=name,
                    line=dict(
                        color=cost_colors[i % len(cost_colors)],
                        dash=line_styles[i % len(line_styles)],
                    ),
                ))
            fig_conv.update_layout(
                title="収束曲線比較 (最良コスト)",
                xaxis_title="反復 / 世代 / サイクル",
                yaxis_title="コスト [円]",
                hovermode="x unified",
                height=450,
            )
            st.plotly_chart(fig_conv, use_container_width=True)

        # ---- SOC 比較 ----
        results_with_soc = {k: v for k, v in available.items() if v.soc_series}
        if len(results_with_soc) >= 2:
            st.markdown("#### SOC 推移比較")
            labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods) if cfg else []
            labels_ext = (labels + ["END"]) if labels else []

            fig_soc = go.Figure()
            dash_styles = ["solid", "dash", "dot", "dashdot"]
            for s_idx, (s_name, s_res) in enumerate(results_with_soc.items()):
                for bus_id in s_res.soc_series:
                    fig_soc.add_trace(go.Scatter(
                        x=labels_ext[:len(s_res.soc_series[bus_id])],
                        y=s_res.soc_series[bus_id],
                        name=f"{bus_id} ({s_name})",
                        mode="lines",
                        line=dict(dash=dash_styles[s_idx % len(dash_styles)]),
                    ))
            fig_soc.update_layout(
                title="SOC 推移比較: 全ソルバー",
                xaxis_title="時刻",
                yaxis_title="SOC [kWh]",
                height=500,
            )
            st.plotly_chart(fig_soc, use_container_width=True)


# ===========================================================================
# 🎯 MILP 専用タブ (mode_milp_only)
# ===========================================================================
with solver_tab_milp_only:
    st.markdown("""
    <div class="section-header">
      <div class="section-icon">🎯</div>
      <h3>MILP 専用モード — mode_milp_only</h3>
    </div>
    """, unsafe_allow_html=True)
    st.caption(
        "src/ パイプラインの MILP 専用モード。data/ の CSV・JSON を直接読み込み、"
        "Gurobi で厳密最適化を実行します。"
    )

    milp_only_col1, milp_only_col2 = st.columns(2)
    with milp_only_col1:
        milp_config_path = st.text_input(
            "設定ファイル", "config/experiment_config.json",
            key="milp_only_config")
        milp_time_limit = st.number_input(
            "制限時間 [秒]", 10.0, 3600.0, 300.0, step=10.0,
            key="milp_only_timelimit")
    with milp_only_col2:
        milp_mip_gap = st.number_input(
            "MIP Gap", 0.001, 0.1, 0.01, step=0.005,
            key="milp_only_gap")
        milp_flag_overrides_str = st.text_area(
            "Flag Overrides (JSON)", '{}',
            key="milp_only_flags", height=100)

    if st.button("🎯 MILP 専用モードで求解", key="btn_milp_only", type="primary"):
        with st.spinner("MILP を求解中..."):
            try:
                import json as _json
                overrides = _json.loads(milp_flag_overrides_str) if milp_flag_overrides_str.strip() else None
                # 一時的に config を上書き
                _cfg_path = Path(milp_config_path)
                with open(_cfg_path, encoding="utf-8") as f:
                    _cfg = json.load(f)
                _cfg["time_limit_sec"] = milp_time_limit
                _cfg["mip_gap"] = milp_mip_gap
                if overrides:
                    _cfg["milp_flag_overrides"] = overrides

                import tempfile, os
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(_cfg, tmp, ensure_ascii=False, indent=2)
                    tmp_path = tmp.name

                from src.pipeline.solve import solve as src_solve
                result = src_solve(tmp_path, mode="mode_milp_only")
                os.unlink(tmp_path)

                st.success(
                    f"✅ status={result['result'].status}, "
                    f"obj={result['result'].objective_value:.2f}, "
                    f"time={result['result'].solve_time_sec:.2f}s"
                )
                if result.get("sim_result"):
                    st.json({"simulator_feasible": True})
            except Exception as e:
                st.error(f"エラー: {e}")
                import traceback
                st.code(traceback.format_exc())


# ===========================================================================
# 🔄 ALNS 専用タブ (mode_alns_only)
# ===========================================================================
with solver_tab_alns_only:
    st.markdown("""
    <div class="section-header">
      <div class="section-icon">🔄</div>
      <h3>ALNS 専用モード — mode_alns_only</h3>
    </div>
    """, unsafe_allow_html=True)
    st.caption(
        "ALNS (Adaptive Large Neighbourhood Search) のみで便割当 + 簡易充電を求解します。"
    )

    alns_only_col1, alns_only_col2 = st.columns(2)
    with alns_only_col1:
        alns_only_config = st.text_input(
            "設定ファイル", "config/experiment_config.json",
            key="alns_only_config")
        alns_only_iters = st.number_input(
            "最大反復数", 50, 5000, 500, step=50,
            key="alns_only_iters")
        alns_only_no_improve = st.number_input(
            "改善停止反復数", 10, 1000, 100, step=10,
            key="alns_only_no_improve")
    with alns_only_col2:
        alns_only_temp = st.number_input(
            "初期温度", 100.0, 10000.0, 1000.0, step=100.0,
            key="alns_only_temp")
        alns_only_cooling = st.number_input(
            "冷却率", 0.900, 0.999, 0.995, step=0.001, format="%.3f",
            key="alns_only_cooling")
        alns_only_seed = st.number_input(
            "乱数シード", 0, 999, 42,
            key="alns_only_seed")

    if st.button("🔄 ALNS 専用モードで求解", key="btn_alns_only", type="primary"):
        with st.spinner("ALNS を求解中..."):
            try:
                _cfg_path = Path(alns_only_config)
                with open(_cfg_path, encoding="utf-8") as f:
                    _cfg = json.load(f)
                _cfg["alns"] = {
                    "max_iterations": alns_only_iters,
                    "max_no_improve": alns_only_no_improve,
                    "init_temp": alns_only_temp,
                    "cooling_rate": alns_only_cooling,
                    "seed": alns_only_seed,
                }

                import tempfile, os
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(_cfg, tmp, ensure_ascii=False, indent=2)
                    tmp_path = tmp.name

                from src.pipeline.solve import solve as src_solve
                result = src_solve(tmp_path, mode="mode_alns_only")
                os.unlink(tmp_path)

                st.success(
                    f"✅ status={result['result'].status}, "
                    f"obj={result['result'].objective_value:.2f}, "
                    f"time={result['result'].solve_time_sec:.2f}s"
                )
            except Exception as e:
                st.error(f"エラー: {e}")
                import traceback
                st.code(traceback.format_exc())


# ===========================================================================
# ⚡ ALNS+MILP ハイブリッドタブ (mode_alns_milp)
# ===========================================================================
with solver_tab_alns_milp:
    st.markdown("""
    <div class="section-header">
      <div class="section-icon">⚡</div>
      <h3>ALNS+MILP ハイブリッド — mode_alns_milp</h3>
    </div>
    """, unsafe_allow_html=True)
    st.caption(
        "Phase 1: ALNS で便割当を高速探索 → Phase 2: MILP で充電/SOC/電力料金を厳密最適化。"
        " 大規模問題でも MILP 品質の充電スケジュールが得られます。"
    )

    hybrid_col1, hybrid_col2 = st.columns(2)
    with hybrid_col1:
        hybrid_config = st.text_input(
            "設定ファイル", "config/experiment_config.json",
            key="hybrid_config")
        hybrid_alns_iters = st.number_input(
            "ALNS 最大反復数", 50, 5000, 500, step=50,
            key="hybrid_alns_iters")
        hybrid_milp_timelimit = st.number_input(
            "MILP 制限時間 [秒]", 10.0, 3600.0, 300.0, step=10.0,
            key="hybrid_milp_timelimit")
    with hybrid_col2:
        hybrid_alns_temp = st.number_input(
            "ALNS 初期温度", 100.0, 10000.0, 1000.0, step=100.0,
            key="hybrid_alns_temp")
        hybrid_cooling = st.number_input(
            "冷却率", 0.900, 0.999, 0.995, step=0.001, format="%.3f",
            key="hybrid_cooling")
        hybrid_mip_gap = st.number_input(
            "MILP MIP Gap", 0.001, 0.1, 0.01, step=0.005,
            key="hybrid_mip_gap")

    if st.button("⚡ ALNS+MILP で求解", key="btn_alns_milp", type="primary"):
        with st.spinner("ALNS フェーズ → MILP フェーズ 実行中..."):
            try:
                _cfg_path = Path(hybrid_config)
                with open(_cfg_path, encoding="utf-8") as f:
                    _cfg = json.load(f)
                _cfg["alns"] = {
                    "max_iterations": hybrid_alns_iters,
                    "max_no_improve": 100,
                    "init_temp": hybrid_alns_temp,
                    "cooling_rate": hybrid_cooling,
                    "seed": 42,
                }
                _cfg["time_limit_sec"] = hybrid_milp_timelimit
                _cfg["mip_gap"] = hybrid_mip_gap

                import tempfile, os
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(_cfg, tmp, ensure_ascii=False, indent=2)
                    tmp_path = tmp.name

                from src.pipeline.solve import solve as src_solve
                result = src_solve(tmp_path, mode="mode_alns_milp")
                os.unlink(tmp_path)

                st.success(
                    f"✅ method={result['method']}, "
                    f"status={result['result'].status}, "
                    f"obj={result['result'].objective_value:.2f}, "
                    f"time={result['result'].solve_time_sec:.2f}s"
                )
            except Exception as e:
                st.error(f"エラー: {e}")
                import traceback
                st.code(traceback.format_exc())


# ===========================================================================
# 🗺️ 地図エディタタブ
# ===========================================================================
with tab_map:
    st.markdown("""
    <div class="section-header">
      <div class="section-icon">�️</div>
      <h3>路線詳細エディタ</h3>
    </div>
    """, unsafe_allow_html=True)

    try:
        from app.route_detail_editor import render_route_detail_editor
        render_route_detail_editor(data_dir="data")
    except Exception as e:
        st.error(
            f"路線エディタの読み込みに失敗しました: {e}\n\n"
            "地図モードを使う場合は以下をインストールしてください:\n"
            "```\npip install folium streamlit-folium\n```"
        )


# ---------------------------------------------------------------------------
# フッター
# ---------------------------------------------------------------------------
st.markdown("""
<div class="ebus-footer">
  <span>🚌 <b>E-Bus Sim v0.4.0 — Route-Editable + Multi-Solver</b> — PV出力を考慮した混成フリートの電気バス充電・運行スケジューリング最適化 試作アプリ</span>
  <span>Gurobi (MILP) &nbsp;•&nbsp; ALNS &nbsp;•&nbsp; GA &nbsp;•&nbsp; ABC &nbsp;•&nbsp; ALNS+MILP</span>
</div>
""", unsafe_allow_html=True)
