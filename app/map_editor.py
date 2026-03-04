"""
app/map_editor.py — folium 地図ベース路線・デポ・充電器配置エディタ

機能:
  1. 停留所・デポ・充電拠点を地図上にプロット
  2. マーカードラッグで座標を変更
  3. ポリラインで路線セグメントを描画
  4. クリックで新規停留所/デポ/充電拠点を追加
  5. st.data_editor で属性を一括編集
  6. 「保存」で CSV に反映

依存: folium, streamlit-folium
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import folium
    from folium.plugins import Draw, MarkerCluster
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


# ---------------------------------------------------------------------------
# カラー定数
# ---------------------------------------------------------------------------
COLOR_DEPOT = "red"
COLOR_CHARGER = "green"
COLOR_STOP = "blue"
COLOR_TERMINAL = "orange"
COLOR_SEGMENT = "#3388ff"


def _load_csv_safe(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8")
    return None


def _build_map(
    center_lat: float = 35.6895,
    center_lon: float = 139.6917,
    zoom: int = 14,
) -> "folium.Map":
    """ベースマップを生成する。"""
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles="cartodbpositron",
    )
    return m


def _add_stops_layer(
    m: "folium.Map",
    stops_df: pd.DataFrame,
) -> "folium.Map":
    """停留所マーカーを追加する。"""
    fg = folium.FeatureGroup(name="🚏 停留所")
    for _, row in stops_df.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color=COLOR_STOP,
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(
                f"<b>{row.get('stop_name', row.get('stop_id', ''))}</b><br>"
                f"ID: {row.get('stop_id', '')}<br>"
                f"seq: {row.get('stop_sequence', '')}",
                max_width=200,
            ),
            tooltip=str(row.get("stop_name", row.get("stop_id", ""))),
        ).add_to(fg)
    fg.add_to(m)
    return m


def _add_terminals_layer(
    m: "folium.Map",
    terminals_df: pd.DataFrame,
) -> "folium.Map":
    """ターミナルマーカーを追加する。"""
    fg = folium.FeatureGroup(name="🏢 ターミナル")
    for _, row in terminals_df.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue

        is_depot = str(row.get("has_depot", row.get("is_depot", False))).lower() in (
            "true",
            "1",
            "yes",
        )
        has_charger = str(
            row.get("has_charger", row.get("has_charger_site", False))
        ).lower() in ("true", "1", "yes")

        if is_depot:
            color = COLOR_DEPOT
            icon = "home"
        elif has_charger:
            color = COLOR_CHARGER
            icon = "bolt"
        else:
            color = COLOR_TERMINAL
            icon = "info-sign"

        folium.Marker(
            location=[lat, lon],
            icon=folium.Icon(color=color, icon=icon, prefix="glyphicon"),
            popup=folium.Popup(
                f"<b>{row.get('terminal_name', row.get('terminal_id', ''))}</b><br>"
                f"ID: {row.get('terminal_id', '')}<br>"
                f"デポ: {is_depot}<br>"
                f"充電器: {has_charger}<br>"
                f"駐車容量: {row.get('depot_capacity', 'N/A')}",
                max_width=250,
            ),
            tooltip=str(row.get("terminal_name", row.get("terminal_id", ""))),
            draggable=True,
        ).add_to(fg)
    fg.add_to(m)
    return m


def _add_depots_layer(
    m: "folium.Map",
    depots_df: pd.DataFrame,
) -> "folium.Map":
    """デポ専用レイヤーを追加する。"""
    fg = folium.FeatureGroup(name="🅿️ デポ")
    for _, row in depots_df.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue

        folium.Marker(
            location=[lat, lon],
            icon=folium.Icon(color=COLOR_DEPOT, icon="home", prefix="glyphicon"),
            popup=folium.Popup(
                f"<b>{row.get('depot_name', row.get('depot_id', ''))}</b><br>"
                f"駐車容量: {row.get('parking_capacity', 'N/A')}<br>"
                f"夜間充電: {row.get('overnight_charging', '')}<br>"
                f"系統接続: {row.get('grid_connection_kw', '')} kW",
                max_width=250,
            ),
            tooltip=str(row.get("depot_name", row.get("depot_id", ""))),
            draggable=True,
        ).add_to(fg)
    fg.add_to(m)
    return m


def _add_charger_sites_layer(
    m: "folium.Map",
    charger_sites_df: pd.DataFrame,
) -> "folium.Map":
    """充電拠点レイヤーを追加する。"""
    fg = folium.FeatureGroup(name="⚡ 充電拠点")
    for _, row in charger_sites_df.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue

        folium.Marker(
            location=[lat, lon],
            icon=folium.Icon(color=COLOR_CHARGER, icon="flash", prefix="glyphicon"),
            popup=folium.Popup(
                f"<b>{row.get('site_name', row.get('site_id', ''))}</b><br>"
                f"タイプ: {row.get('site_type', '')}<br>"
                f"系統上限: {row.get('max_grid_kw', '')} kW<br>"
                f"PV: {row.get('pv_capacity_kw', 0)} kW",
                max_width=250,
            ),
            tooltip=str(row.get("site_name", row.get("site_id", ""))),
            draggable=True,
        ).add_to(fg)
    fg.add_to(m)
    return m


def _add_segments_layer(
    m: "folium.Map",
    segments_df: pd.DataFrame,
    stops_df: pd.DataFrame,
) -> "folium.Map":
    """セグメント（停留所間区間）をポリラインで描画する。"""
    fg = folium.FeatureGroup(name="📏 セグメント")

    # stop_id → (lat, lon) の変換テーブル
    stop_coords = {}
    for _, row in stops_df.iterrows():
        sid = row.get("stop_id")
        lat = row.get("lat")
        lon = row.get("lon")
        if sid and not pd.isna(lat) and not pd.isna(lon):
            stop_coords[sid] = (lat, lon)

    for _, row in segments_df.iterrows():
        from_id = row.get("from_stop_id")
        to_id = row.get("to_stop_id")
        from_coord = stop_coords.get(from_id)
        to_coord = stop_coords.get(to_id)
        if from_coord is None or to_coord is None:
            continue

        dist = row.get("distance_km", 0.0)
        runtime = row.get("scheduled_run_time_min", row.get("runtime_min", 0.0))

        folium.PolyLine(
            locations=[from_coord, to_coord],
            color=COLOR_SEGMENT,
            weight=3,
            opacity=0.8,
            tooltip=f"{from_id} → {to_id} ({dist:.1f} km, {runtime:.0f} min)",
        ).add_to(fg)
    fg.add_to(m)
    return m


def render_map_editor(data_dir: str = "data") -> None:
    """地図ベースの路線・デポ・充電器エディタを描画する。"""
    if not FOLIUM_AVAILABLE:
        st.error(
            "folium / streamlit-folium がインストールされていません。\n\n"
            "```\npip install folium streamlit-folium\n```"
        )
        return

    base = Path(data_dir)
    route_dir = base / "route_master"
    infra_dir = base / "infra"

    st.caption(
        "地図上でデポ・充電拠点・停留所の配置を確認・編集できます。"
        " マーカーをドラッグして位置を変更し、下部の表で属性を編集してください。"
    )

    # ---- CSV 読み込み ----
    terminals_df = _load_csv_safe(route_dir / "terminals.csv")
    stops_df = _load_csv_safe(route_dir / "stops.csv")
    segments_df = _load_csv_safe(route_dir / "segments.csv")
    depots_df = _load_csv_safe(infra_dir / "depots.csv")
    charger_sites_df = _load_csv_safe(infra_dir / "charger_sites.csv")
    chargers_df = _load_csv_safe(infra_dir / "chargers.csv")

    # 地図中心を決定
    center_lat, center_lon = 35.6895, 139.6917
    if terminals_df is not None and len(terminals_df) > 0:
        valid = terminals_df.dropna(subset=["lat", "lon"])
        if len(valid) > 0:
            center_lat = valid["lat"].mean()
            center_lon = valid["lon"].mean()

    # ---- 地図構築 ----
    m = _build_map(center_lat, center_lon, zoom=14)

    if terminals_df is not None:
        m = _add_terminals_layer(m, terminals_df)
    if depots_df is not None:
        m = _add_depots_layer(m, depots_df)
    if charger_sites_df is not None:
        m = _add_charger_sites_layer(m, charger_sites_df)
    if stops_df is not None:
        m = _add_stops_layer(m, stops_df)
        if segments_df is not None:
            m = _add_segments_layer(m, segments_df, stops_df)

    # Draw コントロール (新規マーカー追加用)
    Draw(
        draw_options={
            "polyline": True,
            "polygon": False,
            "circle": False,
            "rectangle": False,
            "circlemarker": True,
            "marker": True,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)

    # レイヤーコントロール
    folium.LayerControl().add_to(m)

    # ---- 地図表示 ----
    map_data = st_folium(m, width=800, height=500, key="map_editor_main")

    # ---- 地図からの座標更新 ----
    if map_data and map_data.get("last_object_clicked"):
        clicked = map_data["last_object_clicked"]
        st.info(
            f"クリック位置: lat={clicked.get('lat', ''):.6f}, lon={clicked.get('lng', ''):.6f}"
        )

    # ---- 新規ポイント追加 ----
    st.markdown("---")
    st.subheader("📌 新規ポイント追加")

    add_cols = st.columns(4)
    with add_cols[0]:
        new_type = st.selectbox(
            "追加タイプ",
            ["停留所", "デポ", "充電拠点"],
            key="map_add_type",
        )
    with add_cols[1]:
        new_id = st.text_input("ID", key="map_add_id")
    with add_cols[2]:
        new_name = st.text_input("名称", key="map_add_name")
    with add_cols[3]:
        add_clicked = st.button("➕ 地図クリック位置に追加", key="map_add_btn")

    if add_clicked and new_id and map_data and map_data.get("last_clicked"):
        lat = map_data["last_clicked"]["lat"]
        lon = map_data["last_clicked"]["lng"]

        if new_type == "停留所":
            if stops_df is not None:
                new_row = pd.DataFrame(
                    [
                        {
                            "stop_id": new_id,
                            "route_id": "",
                            "direction_id": "outbound",
                            "stop_sequence": len(stops_df) + 1,
                            "stop_name": new_name,
                            "lat": lat,
                            "lon": lon,
                        }
                    ]
                )
                stops_df = pd.concat([stops_df, new_row], ignore_index=True)
                st.session_state["_map_stops_df"] = stops_df
        elif new_type == "デポ":
            if depots_df is not None:
                new_row = pd.DataFrame(
                    [
                        {
                            "depot_id": new_id,
                            "depot_name": new_name,
                            "terminal_id": "",
                            "lat": lat,
                            "lon": lon,
                            "parking_capacity": 10,
                            "charger_site_id": "",
                            "overnight_charging": True,
                            "has_workshop": False,
                            "grid_connection_kw": 150.0,
                            "notes": "",
                        }
                    ]
                )
                depots_df = pd.concat([depots_df, new_row], ignore_index=True)
                st.session_state["_map_depots_df"] = depots_df
            else:
                depots_df = pd.DataFrame(
                    [
                        {
                            "depot_id": new_id,
                            "depot_name": new_name,
                            "terminal_id": "",
                            "lat": lat,
                            "lon": lon,
                            "parking_capacity": 10,
                            "charger_site_id": "",
                            "overnight_charging": True,
                            "has_workshop": False,
                            "grid_connection_kw": 150.0,
                            "notes": "",
                        }
                    ]
                )
                st.session_state["_map_depots_df"] = depots_df
        elif new_type == "充電拠点":
            if charger_sites_df is not None:
                new_row = pd.DataFrame(
                    [
                        {
                            "site_id": new_id,
                            "site_name": new_name,
                            "terminal_id": "",
                            "lat": lat,
                            "lon": lon,
                            "site_type": "charge_only",
                            "max_grid_kw": 100.0,
                            "pv_capacity_kw": 0.0,
                            "notes": "",
                        }
                    ]
                )
                charger_sites_df = pd.concat(
                    [charger_sites_df, new_row], ignore_index=True
                )
                st.session_state["_map_charger_sites_df"] = charger_sites_df

        st.success(f"追加しました: {new_type} '{new_name}' ({lat:.6f}, {lon:.6f})")
        st.rerun()

    # ---- データ編集タブ ----
    st.markdown("---")
    st.subheader("📋 データ表編集")

    edit_tabs = st.tabs(
        ["🏢 ターミナル", "🅿️ デポ", "⚡ 充電拠点", "⚡ 充電器", "🚏 停留所"]
    )

    edited_data = {}

    with edit_tabs[0]:
        if terminals_df is not None:
            edited_data["terminals"] = st.data_editor(
                terminals_df,
                num_rows="dynamic",
                use_container_width=True,
                key="map_edit_terminals",
            )
        else:
            st.info("terminals.csv が見つかりません。")

    with edit_tabs[1]:
        depots_df_use = st.session_state.get("_map_depots_df", depots_df)
        if depots_df_use is not None:
            edited_data["depots"] = st.data_editor(
                depots_df_use,
                num_rows="dynamic",
                use_container_width=True,
                key="map_edit_depots",
            )
        else:
            st.info(
                "depots.csv が見つかりません。data/infra/depots.csv を作成してください。"
            )

    with edit_tabs[2]:
        cs_df_use = st.session_state.get("_map_charger_sites_df", charger_sites_df)
        if cs_df_use is not None:
            edited_data["charger_sites"] = st.data_editor(
                cs_df_use,
                num_rows="dynamic",
                use_container_width=True,
                key="map_edit_charger_sites",
            )
        else:
            st.info("charger_sites.csv が見つかりません。")

    with edit_tabs[3]:
        if chargers_df is not None:
            edited_data["chargers"] = st.data_editor(
                chargers_df,
                num_rows="dynamic",
                use_container_width=True,
                key="map_edit_chargers",
            )
        else:
            st.info("chargers.csv が見つかりません。")

    with edit_tabs[4]:
        stops_df_use = st.session_state.get("_map_stops_df", stops_df)
        if stops_df_use is not None:
            edited_data["stops"] = st.data_editor(
                stops_df_use,
                num_rows="dynamic",
                use_container_width=True,
                key="map_edit_stops",
            )
        else:
            st.info("stops.csv が見つかりません。")

    # ---- 保存ボタン ----
    st.markdown("---")
    col_save, col_status = st.columns([1, 3])
    with col_save:
        save_clicked = st.button(
            "💾 地図データを保存",
            type="primary",
            key="save_map_data",
        )
    with col_status:
        if save_clicked:
            saved_files = []
            save_map = {
                "terminals": route_dir / "terminals.csv",
                "stops": route_dir / "stops.csv",
                "depots": infra_dir / "depots.csv",
                "charger_sites": infra_dir / "charger_sites.csv",
                "chargers": infra_dir / "chargers.csv",
            }
            for key, df_edited in edited_data.items():
                if df_edited is not None and key in save_map:
                    out_path = save_map[key]
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    df_edited.to_csv(out_path, index=False, encoding="utf-8")
                    saved_files.append(str(out_path.name))
            if saved_files:
                st.success(f"保存しました: {', '.join(saved_files)}")
                st.rerun()
            else:
                st.warning("保存するデータがありません。")
