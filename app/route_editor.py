"""
route_editor.py — Streamlit 路線データ編集コンポーネント

data/route_master/ と data/fleet/ の CSV を読み込み、
st.data_editor で編集 → 保存できる UI を提供する。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st


def render_route_editor(data_dir: str = "data") -> None:
    """路線データの表示・編集 UI を描画する。"""
    base = Path(data_dir)
    route_dir = base / "route_master"
    fleet_dir = base / "fleet"

    if not route_dir.exists():
        st.warning(f"路線マスタディレクトリが見つかりません: `{route_dir}`")
        st.caption("data/route_master/ を作成し、CSV を配置してください。")
        return

    st.caption(
        "路線・停留所・セグメントを編集し「💾 路線データを保存」で反映します。"
        " セグメント (segments.csv) の distance_km / grade_avg_pct / congestion_index が感度分析の主要パラメータです。"
    )

    # ---- 編集用 DataFrames を読み込み ----
    _csvs = {}

    # Routes
    _p = route_dir / "routes.csv"
    if _p.exists():
        _csvs["routes"] = (_p, pd.read_csv(_p))
    # Terminals
    _p = route_dir / "terminals.csv"
    if _p.exists():
        _csvs["terminals"] = (_p, pd.read_csv(_p))
    # Stops
    _p = route_dir / "stops.csv"
    if _p.exists():
        _csvs["stops"] = (_p, pd.read_csv(_p))
    # Segments
    _p = route_dir / "segments.csv"
    if _p.exists():
        _csvs["segments"] = (_p, pd.read_csv(_p))
    # Timetable patterns
    _p = route_dir / "timetable_patterns.csv"
    if _p.exists():
        _csvs["timetable"] = (_p, pd.read_csv(_p))
    # Service calendar
    _p = route_dir / "service_calendar.csv"
    if _p.exists():
        _csvs["calendar"] = (_p, pd.read_csv(_p))
    # Vehicle types
    _p = fleet_dir / "vehicle_types.csv"
    if _p.exists():
        _csvs["vehicle_types"] = (_p, pd.read_csv(_p))

    # Route variants (JSON)
    variants_path = route_dir / "route_variants.json"
    variants_data = None
    if variants_path.exists():
        with open(variants_path, encoding="utf-8") as f:
            variants_data = json.load(f)

    if not _csvs:
        st.info("CSV ファイルが見つかりません。data/route_master/ にサンプル CSV を配置してください。")
        return

    # ---- 編集タブ ----
    tab_names = []
    tab_keys = []
    for key, (_, df) in _csvs.items():
        label_map = {
            "routes": "🛤️ 路線",
            "terminals": "🏢 ターミナル",
            "stops": "🚏 停留所",
            "segments": "📏 セグメント",
            "timetable": "🕐 ダイヤ",
            "calendar": "📅 運行日",
            "vehicle_types": "🚌 車両タイプ",
        }
        tab_names.append(label_map.get(key, key))
        tab_keys.append(key)

    if variants_data is not None:
        tab_names.append("🔀 運行パターン")
        tab_keys.append("variants")

    tabs = st.tabs(tab_names)

    edited: dict[str, pd.DataFrame] = {}

    for i, key in enumerate(tab_keys):
        with tabs[i]:
            if key == "variants":
                # JSON 表示 (read-only for now)
                st.json(variants_data)
                st.caption("route_variants.json は JSON エディタで編集してください。")
            else:
                path, df = _csvs[key]
                st.caption(f"`{path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}`")

                # セグメントは感度パラメータを強調
                if key == "segments":
                    st.info(
                        "⚡ **感度分析軸**: `distance_km` `grade_avg_pct` `signal_count` "
                        "`traffic_level` `congestion_index` — これらの列を変更すると "
                        "エネルギーモデルの推定値が変わります。",
                        icon="📊",
                    )

                if key == "timetable":
                    st.info(
                        "⚡ **感度分析軸**: `headway_min` `start_time` `end_time` — "
                        "便数（ヘッドウェイ）と運行時間帯を変更できます。",
                        icon="🕐",
                    )

                if key == "vehicle_types":
                    st.info(
                        "⚡ **感度分析軸**: `battery_capacity_kwh` `base_energy_rate_kwh_per_km` "
                        "`charging_power_max_kw` `base_fuel_rate_l_per_km`",
                        icon="🔋",
                    )

                edited[key] = st.data_editor(
                    df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"route_edit_{key}",
                )

    # ---- 統計サマリー ----
    if "segments" in _csvs:
        _, seg_df = _csvs["segments"]
        with st.expander("📊 路線統計サマリー", expanded=False):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("総距離", f"{seg_df['distance_km'].sum():.1f} km")
            with col2:
                st.metric("総走行時間", f"{seg_df['runtime_min'].sum():.0f} min")
            with col3:
                avg_speed = (
                    seg_df["distance_km"].sum()
                    / (seg_df["runtime_min"].sum() / 60.0)
                    if seg_df["runtime_min"].sum() > 0
                    else 0
                )
                st.metric("平均速度", f"{avg_speed:.1f} km/h")
            with col4:
                st.metric("セグメント数", f"{len(seg_df)}")

    # ---- 保存ボタン ----
    st.markdown("---")
    col_save, col_status = st.columns([1, 3])
    with col_save:
        save_clicked = st.button("💾 路線データを保存", type="primary", key="save_route_data")
    with col_status:
        if save_clicked:
            saved = []
            for key, df_edited in edited.items():
                if key in _csvs:
                    path, _ = _csvs[key]
                    df_edited.to_csv(path, index=False, encoding="utf-8")
                    saved.append(str(path.name))
            st.success(f"保存しました: {', '.join(saved)}")
