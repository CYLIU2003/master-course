"""
app/system_config_editor.py

System settings and apply panel for the Settings tab.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.config_builder import BuildReport, build_problem_config_from_session_state
from app.model_core import config_to_dict, make_time_labels


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _service_type_options(data_dir: str) -> list[str]:
    path = Path(data_dir) / "route_master" / "timetable.csv"
    if not path.exists():
        return ["すべて"]

    try:
        timetable = pd.read_csv(path, encoding="utf-8")
    except Exception:
        return ["すべて"]

    if "service_type" not in timetable.columns:
        return ["すべて"]
    values = sorted(
        {
            str(x).strip()
            for x in timetable["service_type"].dropna().tolist()
            if str(x).strip()
        }
    )
    return ["すべて", *values] if values else ["すべて"]


def _reset_solver_outputs() -> None:
    st.session_state.result_gurobi = None
    st.session_state.result_alns = None
    st.session_state.result_ga = None
    st.session_state.result_abc = None


def _render_report(report: BuildReport) -> None:
    st.caption(
        "構築レポート: "
        f"source={report.source_mode}, "
        f"timetable_used={report.timetable_trips_used}/{report.timetable_trips_total}"
    )
    for msg in report.warnings:
        st.warning(msg)


def _build_dispatch_preview(data_dir: str) -> dict[str, Any]:
    from src.dispatch import TimetableDispatchPipeline, load_dispatch_context_from_csv

    vehicle_type = st.session_state.get("cfg_preview_vehicle_type", "BEV")
    selected_service_type = str(
        st.session_state.get("cfg_service_type", "すべて")
    ).strip()
    service_type = None if selected_service_type == "すべて" else selected_service_type
    turnaround_min = _safe_int(st.session_state.get("cfg_turnaround_min", 10), 10)

    service_date_value = st.session_state.get("cfg_service_date", date.today())
    if hasattr(service_date_value, "isoformat"):
        service_date = service_date_value.isoformat()
    else:
        service_date = str(service_date_value)

    context = load_dispatch_context_from_csv(
        data_dir=data_dir,
        service_date=service_date,
        default_turnaround_min=turnaround_min,
        service_type=service_type,
    )

    result = TimetableDispatchPipeline().run(context, vehicle_type=vehicle_type)
    edge_count = sum(len(v) for v in result.graph.values())
    eligible_count = len(
        [t for t in context.trips if vehicle_type in t.allowed_vehicle_types]
    )
    top_successors = sorted(
        ((trip_id, len(successors)) for trip_id, successors in result.graph.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    return {
        "vehicle_type": vehicle_type,
        "trip_count": len(context.trips),
        "eligible_trip_count": eligible_count,
        "edge_count": edge_count,
        "duty_count": len(result.duties),
        "invalid_duties": result.invalid_duties,
        "uncovered_trip_ids": result.uncovered_trip_ids,
        "duplicate_trip_ids": result.duplicate_trip_ids,
        "warnings": result.warnings,
        "top_successors": top_successors,
    }


def _render_config_summary() -> None:
    cfg = st.session_state.config
    if cfg is None:
        return

    st.markdown(
        """
    <div class="section-header">
      <div class="section-icon">📊</div>
      <h3>現在の設定概要</h3>
    </div>
    """,
        unsafe_allow_html=True,
    )

    pv_status = "✅ 有効" if cfg.enable_pv else "❌ 無効"
    demand_status = "✅ 有効" if cfg.enable_demand_charge else "—"

    st.markdown(
        f"""
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
      <div class="metric-card {"accent" if cfg.enable_pv else "warn"}">
        <div class="metric-label">☀️ PV</div>
        <div class="metric-value" style="font-size:1.3rem">{pv_status}</div>
        <div class="metric-unit">デマンド: {demand_status}</div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

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
                    "終了": labels[min(t.end_t, len(labels) - 1)]
                    if t.end_t < len(labels)
                    else t.end_t,
                    "消費 [kWh]": t.energy_kwh,
                    "距離 [km]": t.distance_km,
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
            labels = make_time_labels(cfg.start_time, cfg.delta_h, cfg.num_periods)
            energy_df = pd.DataFrame(
                {
                    "時刻": labels[: cfg.num_periods],
                    "PV発電 [kWh]": cfg.pv_gen_kwh[: cfg.num_periods],
                    "電力単価 [円/kWh]": cfg.grid_price_yen_per_kwh[: cfg.num_periods],
                }
            )
            st.dataframe(energy_df, use_container_width=True)

    with st.expander("📦 設定 JSON をエクスポート"):
        cfg_dict = config_to_dict(cfg)
        st.json(cfg_dict)
        st.download_button(
            "設定JSONをダウンロード",
            data=json.dumps(cfg_dict, ensure_ascii=False, indent=2),
            file_name="ebus_config_export.json",
            mime="application/json",
        )


def render_system_config_editor(config_mode: str, data_dir: str = "data") -> None:
    st.markdown(
        """
    <div class="section-header">
      <div class="section-icon">⚙️</div>
      <h3>システム設定・適用</h3>
    </div>
    """,
        unsafe_allow_html=True,
    )

    if config_mode == "JSON インポート":
        if st.session_state.config is not None:
            st.success("✅ JSON 設定を読み込み済みです。")
        else:
            st.info("サイドバーから JSON ファイルを読み込んでください。")
        _render_config_summary()
        return

    with st.expander("📐 計画軸・データソース", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.selectbox(
                "便データソース",
                ["時刻表（推奨）", "簡易サンプル"],
                key="cfg_trip_source_mode",
            )
            st.date_input("計画日", value=date.today(), key="cfg_service_date")
        with c2:
            st.selectbox("時間刻み [h]", [0.25, 0.5, 1.0], index=1, key="cfg_delta_h")
            st.slider("開始時刻", 0, 12, 6, key="cfg_start_hour")
        with c3:
            opts = _service_type_options(data_dir)
            default_idx = opts.index("weekday") if "weekday" in opts else 0
            st.selectbox(
                "サービス種別", opts, index=default_idx, key="cfg_service_type"
            )
            st.slider("終了時刻", 12, 24, 22, key="cfg_end_hour")

        source_mode = st.session_state.get("cfg_trip_source_mode", "時刻表（推奨）")
        if source_mode == "時刻表（推奨）":
            d1, d2, d3 = st.columns(3)
            with d1:
                st.number_input(
                    "使用便数上限 (0=無制限)", 0, 5000, 0, key="cfg_max_trips"
                )
            with d2:
                st.number_input(
                    "距離フォールバック [km]",
                    1.0,
                    100.0,
                    10.0,
                    step=1.0,
                    key="cfg_default_trip_distance",
                )
            with d3:
                st.number_input(
                    "既定ターンアラウンド [分]",
                    0,
                    60,
                    10,
                    step=1,
                    key="cfg_turnaround_min",
                )
        else:
            st.number_input("生成便数", 1, 500, 30, step=1, key="cfg_num_trips")

        delta_h = float(st.session_state.get("cfg_delta_h", 0.5))
        start_hour = int(st.session_state.get("cfg_start_hour", 6))
        end_hour = int(st.session_state.get("cfg_end_hour", 22))
        slots = int((end_hour - start_hour) / delta_h) if end_hour > start_hour else 0
        st.caption(
            f"計画スロット数: {slots} ({start_hour}:00 〜 {end_hour}:00, Δt={delta_h}h)"
        )

    with st.expander("🚌 車両フォールバック（フリート未設定時）", expanded=False):
        vc1, vc2, vc3 = st.columns(3)
        with vc1:
            st.number_input("フォールバック台数", 1, 200, 3, key="cfg_num_buses")
            st.number_input(
                "バッテリ容量 [kWh]", 50.0, 1000.0, 300.0, step=10.0, key="cfg_cap"
            )
        with vc2:
            st.slider("初期 SOC [%]", 30, 100, 80, key="cfg_soc_init")
            st.slider("SOC 下限 [%]", 5, 50, 20, key="cfg_soc_min")
        with vc3:
            st.slider("SOC 上限 [%]", 60, 100, 95, key="cfg_soc_max")
            st.number_input("電費 [km/kWh]", 0.3, 3.0, 1.0, step=0.1, key="cfg_eff")

    with st.expander("⚡ 充電設備・料金設定", expanded=False):
        cc1, cc2 = st.columns(2)
        with cc1:
            st.slider("充電拠点数（営業所未設定時）", 1, 5, 2, key="cfg_depots")
            st.number_input(
                "普通充電出力 [kW]", 10.0, 200.0, 50.0, step=10.0, key="cfg_slow_pw"
            )
            st.number_input("普通充電器台数", 0, 20, 2, step=1, key="cfg_slow_cnt")
            st.number_input(
                "急速充電出力 [kW]", 50.0, 500.0, 150.0, step=10.0, key="cfg_fast_pw"
            )
            st.number_input("急速充電器台数", 0, 20, 1, step=1, key="cfg_fast_cnt")
        with cc2:
            st.slider("充電効率", 0.80, 1.00, 0.95, step=0.01, key="cfg_ch_eff")
            st.checkbox("PV を有効化", value=True, key="cfg_enable_pv")
            st.slider("PV 出力倍率", 0.0, 5.0, 1.0, step=0.1, key="cfg_pv_scale")
            price_mode = st.selectbox(
                "電力料金モード",
                ["デフォルト TOU", "一律 [円/kWh]"],
                key="cfg_price_mode",
            )
            if price_mode == "一律 [円/kWh]":
                st.number_input(
                    "電力単価 [円/kWh]",
                    10.0,
                    100.0,
                    25.0,
                    step=1.0,
                    key="cfg_flat_price",
                )
            st.number_input(
                "軽油単価 [円/L]", 80.0, 250.0, 145.0, step=5.0, key="cfg_diesel"
            )

        op1, op2 = st.columns(2)
        with op1:
            st.checkbox("終端 SOC 条件", value=False, key="cfg_term_soc")
            if st.session_state.get("cfg_term_soc", False):
                st.slider("終端 SOC [%]", 20, 80, 50, key="cfg_term_ratio")
        with op2:
            st.checkbox("デマンドチャージ", value=False, key="cfg_demand")
            if st.session_state.get("cfg_demand", False):
                st.number_input(
                    "契約電力上限 [kW]",
                    50.0,
                    1000.0,
                    200.0,
                    step=10.0,
                    key="cfg_contract",
                )

    with st.expander("🔗 時刻表→接続グラフ プレビュー", expanded=False):
        st.caption("DispatchContext を生成し、接続グラフと配車カバレッジを検証します。")
        st.selectbox(
            "プレビュー車両種別", ["BEV", "ICE"], key="cfg_preview_vehicle_type"
        )
        if st.button("プレビューを更新", key="cfg_refresh_dispatch_preview"):
            try:
                st.session_state["cfg_dispatch_preview"] = _build_dispatch_preview(
                    data_dir
                )
            except Exception as exc:
                st.error(f"プレビュー作成に失敗しました: {exc}")

        preview = st.session_state.get("cfg_dispatch_preview")
        if preview:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("全Trip", preview["trip_count"])
            m2.metric("対象Trip", preview["eligible_trip_count"])
            m3.metric("Feasible Arc", preview["edge_count"])
            m4.metric("生成Duty", preview["duty_count"])

            if preview["uncovered_trip_ids"]:
                st.error(
                    "未割当 trip: " + ", ".join(preview["uncovered_trip_ids"][:20])
                )
            if preview["duplicate_trip_ids"]:
                st.error(
                    "重複割当 trip: " + ", ".join(preview["duplicate_trip_ids"][:20])
                )
            for msg in preview["warnings"][:10]:
                st.warning(msg)

            if preview["top_successors"]:
                top_df = pd.DataFrame(
                    preview["top_successors"], columns=["Trip", "後続候補数"]
                )
                st.dataframe(top_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.info(
        "時刻表・車両・営業所を更新したら、ここで **設定を適用** してソルバーの入力を再構築します。"
    )

    if st.button(
        "🔄 設定を適用", type="primary", key="apply_config", use_container_width=True
    ):
        try:
            cfg, report = build_problem_config_from_session_state(data_dir=data_dir)
            st.session_state.config = cfg
            st.session_state.cfg_build_report = report
            _reset_solver_outputs()
            st.success("✅ 設定を適用しました（時刻表→内部モデル変換完了）。")
        except Exception as exc:
            st.error(f"設定適用に失敗しました: {exc}")

    report = st.session_state.get("cfg_build_report")
    if report:
        _render_report(report)

    _render_config_summary()
