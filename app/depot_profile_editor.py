"""
app/depot_profile_editor.py — 営業所・車両プロフィール＋配車計画エディタ

機能:
  1. 営業所（ガレージ）プロフィールの管理
  2. 車両プロフィールの管理（どの営業所に所属するか）
  3. 配車計画（便チェーン）の作成
     - 時刻表（timetable.csv）から便を選択して「行路」を編成
     - 路線間移動の許可/禁止を営業所単位で設定可能
     - 便チェーン: 一方の便が終わったら次の便に継続する連鎖構造

設計方針:
  - 路線側は「停留所リスト＋時刻表」のみ保持
  - 行路（work_schedule）は営業所が管理する
  - 便チェーンの妥当性チェック（終着 ≤ 次発の発時刻）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
_PREFIX = "_dpe_"
_DEFAULT_CENTER = (35.6895, 139.6917)  # 東京（データなし時のフォールバック）

GARAGES_COLS = [
    "depot_id",
    "depot_name",
    "city",
    "address",
    "lat",
    "lon",
    "parking_capacity",
    "grid_connection_kw",
    "overnight_charging",
    "has_workshop",
    "notes",
]
VEHICLES_COLS = [
    "vehicle_id",
    "vehicle_type",
    "garage_id",
    "route_assignments",
    "battery_capacity_kwh",
    "soc_min_ratio",
    "soc_max_ratio",
    "efficiency_km_per_kwh",
    "status",
    "notes",
]
WORK_COLS = [
    "work_id",
    "garage_id",
    "vehicle_id",
    "service_date",
    "trips",
    "total_trips",
    "start_time",
    "end_time",
    "total_km",
    "notes",
]

_GARAGE_DRAG_JS = """(function () {
  'use strict';
  function resolveMap() {
    if (window.map && typeof window.map.getContainer === 'function') return window.map;
    var mapEl = document.querySelector('.folium-map') || document.querySelector('.leaflet-container');
    if (mapEl && mapEl.id && window[mapEl.id] && typeof window[mapEl.id].getContainer === 'function') {
      return window[mapEl.id];
    }
    return null;
  }

  function bindDrag() {
    var map = resolveMap();
    if (!map) { setTimeout(bindDrag, 250); return; }
    map.eachLayer(function (layer) {
      if (!layer || !layer.options || !layer.options.draggable) return;
      if (layer.__ebGarageDragBound) return;
      var title = String(layer.options.title || '');
      if (title.indexOf('__garage__') !== 0) return;
      layer.__ebGarageDragBound = true;
      layer.on('dragend', function (evt) {
        var ll = evt && evt.target && evt.target.getLatLng ? evt.target.getLatLng() : null;
        if (!ll || !window.__GLOBAL_DATA__) return;
        window.__GLOBAL_DATA__.lat_lng_clicked = {
          lat: ll.lat,
          lng: ll.lng,
          _action: 'move_depot',
          depot_id: title.slice('__garage__'.length)
        };
      });
    });
  }

  bindDrag();
})();
"""


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _sk(name: str) -> str:
    return f"{_PREFIX}{name}"


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8")
    return None


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            if c in ("overnight_charging", "has_workshop"):
                df[c] = False
            elif c in ("parking_capacity", "total_trips"):
                df[c] = 0
            elif c in (
                "lat",
                "lon",
                "grid_connection_kw",
                "battery_capacity_kwh",
                "soc_min_ratio",
                "soc_max_ratio",
                "efficiency_km_per_kwh",
                "total_km",
            ):
                df[c] = 0.0
            else:
                df[c] = ""
    return df


def _parse_time_to_min(t: str) -> int:
    m = re.match(r"(\d+):(\d+)", str(t))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


def _min_to_hhmm(mins: int) -> str:
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------


def _load_data(data_dir: str) -> dict:
    base = Path(data_dir)
    ops_dir = base / "operations"
    route_dir = base / "route_master"

    garages_df = _load_csv(ops_dir / "garages.csv")
    vehicles_df = _load_csv(ops_dir / "vehicles.csv")
    work_df = _load_csv(ops_dir / "work_schedules.csv")
    timetable_df = _load_csv(route_dir / "timetable.csv")
    routes_df = _load_csv(route_dir / "routes.csv")

    if garages_df is None:
        garages_df = pd.DataFrame(columns=GARAGES_COLS)
    garages_df = _ensure_cols(garages_df, GARAGES_COLS)

    if vehicles_df is None:
        vehicles_df = pd.DataFrame(columns=VEHICLES_COLS)
    vehicles_df = _ensure_cols(vehicles_df, VEHICLES_COLS)

    if work_df is None:
        work_df = pd.DataFrame(columns=WORK_COLS)
    work_df = _ensure_cols(work_df, WORK_COLS)

    if timetable_df is None:
        timetable_df = pd.DataFrame(
            columns=[
                "trip_id",
                "route_id",
                "direction",
                "service_type",
                "dep_time",
                "arr_time",
                "from_stop_id",
                "to_stop_id",
                "travel_time_min",
                "notes",
            ]
        )
    if routes_df is None:
        routes_df = pd.DataFrame(columns=["route_id", "route_name"])

    return {
        "garages": garages_df,
        "vehicles": vehicles_df,
        "work": work_df,
        "timetable": timetable_df,
        "routes": routes_df,
        "ops_dir": ops_dir,
    }


def _save_data(
    data_dir: str,
    garages_df: pd.DataFrame,
    vehicles_df: pd.DataFrame,
    work_df: pd.DataFrame,
) -> list[str]:
    ops_dir = Path(data_dir) / "operations"
    ops_dir.mkdir(parents=True, exist_ok=True)

    garages_df.to_csv(ops_dir / "garages.csv", index=False, encoding="utf-8")
    vehicles_df.to_csv(ops_dir / "vehicles.csv", index=False, encoding="utf-8")
    work_df.to_csv(ops_dir / "work_schedules.csv", index=False, encoding="utf-8")
    return ["garages.csv", "vehicles.csv", "work_schedules.csv"]


# ---------------------------------------------------------------------------
# 営業所マップ
# ---------------------------------------------------------------------------


def _build_garages_map(
    garages_df: pd.DataFrame,
    selected_depot: Optional[str] = None,
) -> "folium.Map":
    """全営業所をマーカーで描画した Folium マップを返す。
    マーカーの tooltip に __garage__{depot_id} を埋め込み、
    st_folium の last_object_clicked_tooltip で選択を検知する。
    選択中の営業所は赤、その他は darkred で表示。
    """
    all_coords: list[tuple[float, float]] = []
    if (
        len(garages_df) > 0
        and "lat" in garages_df.columns
        and "lon" in garages_df.columns
    ):
        valid = garages_df.dropna(subset=["lat", "lon"])
        valid = valid[
            (valid["lat"].astype(float) != 0) & (valid["lon"].astype(float) != 0)
        ]
        if len(valid) > 0:
            all_coords = list(
                zip(valid["lat"].astype(float), valid["lon"].astype(float))
            )

    center = (
        (
            sum(c[0] for c in all_coords) / len(all_coords),
            sum(c[1] for c in all_coords) / len(all_coords),
        )
        if all_coords
        else _DEFAULT_CENTER
    )

    m = folium.Map(location=list(center), zoom_start=13, tiles="cartodbpositron")
    from branca.element import Element as BrancaElement

    m.get_root().script.add_child(BrancaElement(f"<script>{_GARAGE_DRAG_JS}</script>"))

    for _, row in garages_df.iterrows():
        lat = row.get("lat", 0)
        lon = row.get("lon", 0)
        if pd.isna(lat) or pd.isna(lon) or float(lat) == 0:
            continue
        gid = str(row.get("depot_id", ""))
        gname = str(row.get("depot_name", gid))
        cap = row.get("parking_capacity", "—")
        grid = row.get("grid_connection_kw", "—")
        is_sel = gid == selected_depot

        folium.Marker(
            location=[float(lat), float(lon)],
            draggable=True,
            title=f"__garage__{gid}",
            icon=folium.Icon(
                color="red" if is_sel else "darkred",
                icon="home",
                prefix="glyphicon",
            ),
            tooltip=f"__garage__{gid}",
            popup=folium.Popup(
                f"<b>{gname}</b><br>"
                f"ID: {gid}<br>"
                f"駐車台数: {cap} 台<br>"
                f"系統接続: {grid} kW",
                max_width=220,
            ),
        ).add_to(m)

    return m


# ---------------------------------------------------------------------------
# 営業所一覧パネル
# ---------------------------------------------------------------------------


def _render_garages_panel(garages_df: pd.DataFrame) -> pd.DataFrame:
    """左: 営業所リスト＋追加フォーム / 右: 地図（クリックで選択・位置入力）。
    選択中の営業所は下部フォームで属性編集できる。
    テーブル一括編集は折りたたみ expander に収納。
    """
    sel_key = _sk("sel_garage_map")
    pending_moves_key = _sk("pending_garage_moves")
    if sel_key not in st.session_state:
        st.session_state[sel_key] = None
    if pending_moves_key not in st.session_state:
        st.session_state[pending_moves_key] = {}

    pending_moves: dict[str, dict] = st.session_state.get(pending_moves_key, {}) or {}
    garages_view = garages_df.copy()
    if pending_moves and len(garages_view) > 0 and "depot_id" in garages_view.columns:
        for depot_id, move in pending_moves.items():
            m = garages_view["depot_id"] == depot_id
            if m.any():
                garages_view.loc[m, "lat"] = float(move["lat"])
                garages_view.loc[m, "lon"] = float(move["lon"])

    # --- 2カラムレイアウト ---
    left_col, right_col = st.columns([1, 3])

    with left_col:
        st.markdown("#### 🏢 営業所一覧")
        depot_ids = garages_df["depot_id"].dropna().tolist()
        depot_ids = [d for d in depot_ids if d]

        for did in depot_ids:
            row = garages_df[garages_df["depot_id"] == did]
            dname = row["depot_name"].iloc[0] if len(row) > 0 else did
            is_sel = st.session_state[sel_key] == did
            if st.button(
                f"{'●' if is_sel else '○'} {dname}",
                key=_sk(f"btn_depot_{did}"),
                use_container_width=True,
                type="primary" if is_sel else "secondary",
            ):
                st.session_state[sel_key] = did
                st.rerun()

        st.markdown("---")
        with st.expander("＋ 営業所を追加", expanded=False):
            # 地図クリックで位置が仮セットされていれば反映
            pend_lat = float(st.session_state.get(_sk("pending_lat"), 0.0))
            pend_lon = float(st.session_state.get(_sk("pending_lon"), 0.0))
            with st.form(key=_sk("add_garage_form"), clear_on_submit=True):
                g_id = st.text_input("営業所 ID", placeholder="depot_north")
                g_name = st.text_input("営業所名", placeholder="北営業所")
                g_city = st.text_input("市区町村")
                g_lat = st.number_input(
                    "緯度", value=pend_lat, format="%.6f", step=0.0001
                )
                g_lon = st.number_input(
                    "経度", value=pend_lon, format="%.6f", step=0.0001
                )
                g_cap = st.number_input("駐車台数", min_value=1, value=10, step=1)
                g_grid = st.number_input(
                    "系統接続 [kW]", min_value=0.0, value=150.0, step=10.0
                )
                g_add = st.form_submit_button("追加")
            if g_add and g_id:
                new_g = pd.DataFrame(
                    [
                        {
                            "depot_id": g_id,
                            "depot_name": g_name,
                            "city": g_city,
                            "address": "",
                            "lat": g_lat,
                            "lon": g_lon,
                            "parking_capacity": g_cap,
                            "grid_connection_kw": g_grid,
                            "overnight_charging": True,
                            "has_workshop": False,
                            "notes": "",
                        }
                    ]
                )
                garages_df = pd.concat([garages_df, new_g], ignore_index=True)
                st.session_state[_sk("buf_garages")] = garages_df
                st.session_state.pop(_sk("garages_editor"), None)
                st.session_state[sel_key] = g_id
                st.session_state.pop(_sk("pending_lat"), None)
                st.session_state.pop(_sk("pending_lon"), None)
                st.toast(f"営業所 '{g_id}' を追加しました。", icon="✅")
                st.rerun()

    with right_col:
        st.markdown(
            "#### 地図（マーカーをクリックで選択 / 空きをクリックで位置入力 / ドラッグで一時移動）"
        )
        if FOLIUM_AVAILABLE:
            gmap = _build_garages_map(garages_view, st.session_state[sel_key])
            map_result = st_folium(
                gmap,
                key=_sk("garages_map"),
                height=320,
                use_container_width=True,
                returned_objects=["last_object_clicked_tooltip", "last_clicked"],
            )
            tooltip_val = (
                map_result.get("last_object_clicked_tooltip") if map_result else None
            )
            last_clicked = map_result.get("last_clicked") if map_result else None

            # マーカークリック → 営業所を選択
            if tooltip_val and str(tooltip_val).startswith("__garage__"):
                gid = str(tooltip_val)[len("__garage__") :]
                if gid in depot_ids and gid != st.session_state[sel_key]:
                    st.session_state[sel_key] = gid
                    st.rerun()

            # 空地クリック → 位置を仮セット（追加フォームに反映）
            elif last_clicked:
                if str(last_clicked.get("_action", "")) == "move_depot":
                    moved_id = str(last_clicked.get("depot_id", "") or "")
                    lat_c = last_clicked.get("lat")
                    lng_c = last_clicked.get("lng")
                    if moved_id and lat_c is not None and lng_c is not None:
                        pending = dict(
                            st.session_state.get(pending_moves_key, {}) or {}
                        )
                        pending[moved_id] = {"lat": float(lat_c), "lon": float(lng_c)}
                        st.session_state[pending_moves_key] = pending
                        st.toast(
                            f"一時移動: {moved_id} (未適用)",
                            icon="📍",
                        )
                        st.rerun()
                lat_c = last_clicked.get("lat")
                lng_c = last_clicked.get("lng")
                if lat_c and lng_c:
                    prev_lat = st.session_state.get(_sk("pending_lat"))
                    prev_lon = st.session_state.get(_sk("pending_lon"))
                    if prev_lat != lat_c or prev_lon != lng_c:
                        st.session_state[_sk("pending_lat")] = float(lat_c)
                        st.session_state[_sk("pending_lon")] = float(lng_c)
                        st.rerun()
            # 仮位置の表示
            if st.session_state.get(_sk("pending_lat")):
                st.caption(
                    f"📍 クリック位置: "
                    f"({st.session_state[_sk('pending_lat')]:.5f}, "
                    f"{st.session_state[_sk('pending_lon')]:.5f})"
                    " → 左の「＋ 営業所を追加」に反映済み"
                )

            current_pending = st.session_state.get(pending_moves_key, {}) or {}
            if current_pending:
                st.info(f"ドラッグ移動の未適用変更: {len(current_pending)} 件")
                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("✅ ドラッグ移動を適用", key=_sk("apply_garage_drag")):
                        for depot_id, move in current_pending.items():
                            mm = garages_df["depot_id"] == depot_id
                            if mm.any():
                                garages_df.loc[mm, "lat"] = float(move["lat"])
                                garages_df.loc[mm, "lon"] = float(move["lon"])
                        st.session_state[_sk("buf_garages")] = garages_df
                        st.session_state.pop(_sk("garages_editor"), None)
                        st.session_state[pending_moves_key] = {}
                        st.toast("営業所のドラッグ移動を適用しました", icon="✅")
                        st.rerun()
                with mc2:
                    if st.button(
                        "🗑️ ドラッグ移動を破棄", key=_sk("discard_garage_drag")
                    ):
                        st.session_state[pending_moves_key] = {}
                        st.toast("未適用のドラッグ移動を破棄しました", icon="🧹")
                        st.rerun()
        else:
            st.info(
                "folium が利用できません。`pip install folium streamlit-folium` を実行してください。"
            )

    # --- 選択中の営業所の属性編集フォーム ---
    selected = st.session_state.get(sel_key)
    if selected and selected in garages_df["depot_id"].tolist():
        st.markdown("---")
        ri = garages_df[garages_df["depot_id"] == selected]
        i0 = ri.index[0]
        r = ri.iloc[0]
        st.markdown(f"**編集中: {r.get('depot_name', selected)}** (ID: `{selected}`)")
        with st.expander("✏️ 営業所属性を編集", expanded=True):
            with st.form(key=_sk(f"edit_garage_{selected}"), clear_on_submit=False):
                ec = st.columns([2, 2, 2])
                with ec[0]:
                    new_name = st.text_input(
                        "営業所名", value=str(r.get("depot_name", "") or "")
                    )
                    new_city = st.text_input(
                        "市区町村", value=str(r.get("city", "") or "")
                    )
                    new_addr = st.text_input(
                        "住所", value=str(r.get("address", "") or "")
                    )
                with ec[1]:
                    new_lat = st.number_input(
                        "緯度",
                        value=float(r.get("lat") or 0.0),
                        format="%.6f",
                        step=0.0001,
                    )
                    new_lon = st.number_input(
                        "経度",
                        value=float(r.get("lon") or 0.0),
                        format="%.6f",
                        step=0.0001,
                    )
                    new_cap = st.number_input(
                        "駐車台数",
                        min_value=0,
                        value=int(r.get("parking_capacity") or 0),
                        step=1,
                    )
                with ec[2]:
                    new_grid = st.number_input(
                        "系統接続 [kW]",
                        min_value=0.0,
                        value=float(r.get("grid_connection_kw") or 0.0),
                        step=10.0,
                        format="%.0f",
                    )
                    new_overnight = st.checkbox(
                        "夜間充電可",
                        value=bool(r.get("overnight_charging", True)),
                    )
                    new_workshop = st.checkbox(
                        "整備工場あり",
                        value=bool(r.get("has_workshop", False)),
                    )
                new_notes = st.text_input("備考", value=str(r.get("notes", "") or ""))
                attr_save = st.form_submit_button("属性を更新")
            if attr_save:
                garages_df.at[i0, "depot_name"] = new_name
                garages_df.at[i0, "city"] = new_city
                garages_df.at[i0, "address"] = new_addr
                garages_df.at[i0, "lat"] = new_lat
                garages_df.at[i0, "lon"] = new_lon
                garages_df.at[i0, "parking_capacity"] = new_cap
                garages_df.at[i0, "grid_connection_kw"] = new_grid
                garages_df.at[i0, "overnight_charging"] = new_overnight
                garages_df.at[i0, "has_workshop"] = new_workshop
                garages_df.at[i0, "notes"] = new_notes
                st.session_state[_sk("buf_garages")] = garages_df
                st.session_state.pop(_sk("garages_editor"), None)
                st.toast(
                    "属性を更新しました。「💾 営業所データを保存」で確定してください。",
                    icon="✅",
                )
                st.rerun()

    # --- テーブル一括編集（折りたたみ） ---
    st.markdown("---")
    with st.expander("📋 テーブルで一括編集", expanded=False):
        st.markdown(
            '<div style="background:#f5f5dc;border-radius:8px;padding:8px 14px;'
            'margin-bottom:8px;font-size:0.83em;">'
            "<b>depot_id</b>=営業所の一意ID │ <b>depot_name</b>=表示名 │ "
            "<b>parking_capacity</b>=駐車台数 │ <b>grid_connection_kw</b>=系統接続[kW]<br>"
            "<b>overnight_charging</b>=夜間充電可否 │ <b>has_workshop</b>=整備工場あり"
            "</div>",
            unsafe_allow_html=True,
        )
        garages_df = st.data_editor(
            garages_df,
            num_rows="dynamic",
            use_container_width=True,
            key=_sk("garages_editor"),
            column_config={
                "depot_id": st.column_config.TextColumn(
                    "営業所 ID", help="例: depot_main"
                ),
                "depot_name": st.column_config.TextColumn("営業所名"),
                "city": st.column_config.TextColumn("市区町村"),
                "address": st.column_config.TextColumn("住所"),
                "lat": st.column_config.NumberColumn("緯度", format="%.6f"),
                "lon": st.column_config.NumberColumn("経度", format="%.6f"),
                "parking_capacity": st.column_config.NumberColumn(
                    "駐車台数", min_value=0, step=1
                ),
                "grid_connection_kw": st.column_config.NumberColumn(
                    "系統接続 [kW]", min_value=0.0, step=10.0, format="%.0f"
                ),
                "overnight_charging": st.column_config.CheckboxColumn(
                    "夜間充電", default=True
                ),
                "has_workshop": st.column_config.CheckboxColumn(
                    "整備工場", default=False
                ),
                "notes": st.column_config.TextColumn("備考"),
            },
        )

    return garages_df


# ---------------------------------------------------------------------------
# 車両一覧パネル
# ---------------------------------------------------------------------------


def _render_vehicles_panel(
    vehicles_df: pd.DataFrame, garage_ids: list[str], route_ids: list[str]
) -> pd.DataFrame:
    st.markdown("### 🚌 車両一覧")
    st.markdown(
        '<div style="background:#e8f5e9;border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.83em;">'
        "<b>vehicle_id</b>=車両ID │ <b>vehicle_type</b>=車両タイプ │ "
        "<b>garage_id</b>=所属営業所 │ <b>route_assignments</b>=担当路線(カンマ区切り)<br>"
        "<b>battery_capacity_kwh</b>=バッテリー容量[kWh] │ "
        "<b>efficiency_km_per_kwh</b>=電費[km/kWh]"
        "</div>",
        unsafe_allow_html=True,
    )

    display_cols = [c for c in VEHICLES_COLS if c in vehicles_df.columns]
    edited = st.data_editor(
        vehicles_df[display_cols],
        num_rows="dynamic",
        use_container_width=True,
        key=_sk("vehicles_editor"),
        column_config={
            "vehicle_id": st.column_config.TextColumn("車両 ID"),
            "vehicle_type": st.column_config.SelectboxColumn(
                "車両タイプ",
                options=["BEV_large", "BEV_mid", "BEV_small", "HEV", "ICE"],
                default="BEV_large",
            ),
            "garage_id": st.column_config.SelectboxColumn(
                "所属営業所",
                options=garage_ids if garage_ids else [""],
            )
            if garage_ids
            else st.column_config.TextColumn("所属営業所"),
            "route_assignments": st.column_config.TextColumn(
                "担当路線",
                help="カンマ区切りで複数指定（例: route_101,route_102）",
            ),
            "battery_capacity_kwh": st.column_config.NumberColumn(
                "バッテリー [kWh]",
                min_value=0.0,
                step=10.0,
                format="%.0f",
            ),
            "soc_min_ratio": st.column_config.NumberColumn(
                "SOC下限",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                format="%.2f",
            ),
            "soc_max_ratio": st.column_config.NumberColumn(
                "SOC上限",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                format="%.2f",
            ),
            "efficiency_km_per_kwh": st.column_config.NumberColumn(
                "電費 [km/kWh]",
                min_value=0.1,
                step=0.1,
                format="%.2f",
            ),
            "status": st.column_config.SelectboxColumn(
                "状態",
                options=["active", "maintenance", "retired"],
                default="active",
            ),
            "notes": st.column_config.TextColumn("備考"),
        },
    )

    # クイック追加
    st.markdown("#### ➕ 車両をすばやく追加")
    with st.form(key=_sk("add_vehicle"), clear_on_submit=True):
        vc = st.columns([1, 1, 1, 1, 1])
        with vc[0]:
            v_id = st.text_input("車両 ID", placeholder="bus_301")
        with vc[1]:
            v_type = st.selectbox("タイプ", ["BEV_large", "BEV_mid", "BEV_small"])
        with vc[2]:
            v_garage = st.selectbox("所属営業所", garage_ids if garage_ids else [""])
        with vc[3]:
            v_kwh = st.number_input(
                "容量 [kWh]", min_value=50.0, value=300.0, step=10.0
            )
        with vc[4]:
            v_add = st.form_submit_button("追加")
        if v_add and v_id:
            new_v = pd.DataFrame(
                [
                    {
                        "vehicle_id": v_id,
                        "vehicle_type": v_type,
                        "garage_id": v_garage,
                        "route_assignments": "",
                        "battery_capacity_kwh": v_kwh,
                        "soc_min_ratio": 0.2,
                        "soc_max_ratio": 0.95,
                        "efficiency_km_per_kwh": 1.0,
                        "status": "active",
                        "notes": "",
                    }
                ]
            )
            edited = pd.concat([edited, new_v], ignore_index=True)
            st.session_state[_sk("buf_vehicles")] = edited
            st.session_state.pop(_sk("vehicles_editor"), None)
            st.toast(f"車両 '{v_id}' を追加しました。", icon="✅")
            st.rerun()
    return edited


# ---------------------------------------------------------------------------
# 便チェーン妥当性チェック
# ---------------------------------------------------------------------------


def _check_trip_chain(trip_ids: list[str], timetable_df: pd.DataFrame) -> list[str]:
    """
    便チェーンの妥当性を検証する。
    - 各便の到着時刻 ≤ 次便の発車時刻 であること
    - 路線間移動の際は十分な余裕があること（5分以上）
    返り値: 警告メッセージのリスト（空ならOK）
    """
    if len(timetable_df) == 0 or len(trip_ids) < 2:
        return []

    tt_dict: dict[str, dict] = {}
    for _, row in timetable_df.iterrows():
        tt_dict[str(row["trip_id"])] = {
            "dep_time": str(row.get("dep_time", "00:00")),
            "arr_time": str(row.get("arr_time", "00:00")),
            "route_id": str(row.get("route_id", "")),
            "from_stop_id": str(row.get("from_stop_id", "")),
            "to_stop_id": str(row.get("to_stop_id", "")),
        }

    warnings = []
    for i in range(len(trip_ids) - 1):
        cur_id = trip_ids[i]
        nxt_id = trip_ids[i + 1]

        cur = tt_dict.get(cur_id)
        nxt = tt_dict.get(nxt_id)

        if cur is None:
            warnings.append(f"⚠️ 便 '{cur_id}' が時刻表に見つかりません。")
            continue
        if nxt is None:
            warnings.append(f"⚠️ 便 '{nxt_id}' が時刻表に見つかりません。")
            continue

        arr_min = _parse_time_to_min(cur["arr_time"])
        dep_min = _parse_time_to_min(nxt["dep_time"])

        # 深夜跨ぎ対応
        if dep_min < arr_min - 120:  # 2時間以上巻き戻りは翌日扱い
            dep_min += 24 * 60

        same_route = cur["route_id"] == nxt["route_id"]
        min_gap = 3 if same_route else 5  # 同一路線: 3分, 路線間: 5分

        if dep_min < arr_min:
            warnings.append(
                f"❌ 便チェーンエラー: '{cur_id}' 到着 {cur['arr_time']} > "
                f"'{nxt_id}' 発車 {nxt['dep_time']} (重複)"
            )
        elif dep_min - arr_min < min_gap:
            warnings.append(
                f"⚠️ 乗換余裕が短い: '{cur_id}' 到着 {cur['arr_time']} → "
                f"'{nxt_id}' 発車 {nxt['dep_time']} "
                f"(余裕 {dep_min - arr_min}分 < 最小 {min_gap}分)"
            )

    return warnings


# ---------------------------------------------------------------------------
# 配車計画（行路）編集パネル
# ---------------------------------------------------------------------------


def _render_work_schedule_panel(
    work_df: pd.DataFrame,
    timetable_df: pd.DataFrame,
    vehicles_df: pd.DataFrame,
    garages_df: pd.DataFrame,
    selected_garage: str,
    allow_cross_route: bool,
) -> pd.DataFrame:
    """指定された営業所の配車計画（行路）を編集するパネル。"""
    sub = (
        work_df[work_df["garage_id"] == selected_garage].copy()
        if len(work_df) > 0
        else pd.DataFrame(columns=WORK_COLS)
    )

    # 当該営業所の車両
    garage_vehicles = (
        vehicles_df[vehicles_df["garage_id"] == selected_garage]
        if len(vehicles_df) > 0
        else pd.DataFrame()
    )
    vehicle_ids = (
        garage_vehicles["vehicle_id"].tolist() if len(garage_vehicles) > 0 else []
    )

    # 当該営業所の車両が担当する路線の便
    available_routes: set[str] = set()
    if len(garage_vehicles) > 0:
        for _, v in garage_vehicles.iterrows():
            r_assign = str(v.get("route_assignments", ""))
            for r in r_assign.split(","):
                r = r.strip()
                if r:
                    available_routes.add(r)

    if allow_cross_route and len(timetable_df) > 0:
        available_trips = timetable_df.copy()
    elif len(available_routes) > 0 and len(timetable_df) > 0:
        available_trips = timetable_df[
            timetable_df["route_id"].isin(available_routes)
        ].copy()
    else:
        available_trips = (
            timetable_df.copy() if len(timetable_df) > 0 else pd.DataFrame()
        )

    trip_ids = available_trips["trip_id"].tolist() if len(available_trips) > 0 else []
    trip_label_map: dict[str, str] = {}
    if len(available_trips) > 0:
        for _, row in available_trips.iterrows():
            tid = str(row["trip_id"])
            trip_label_map[tid] = (
                f"{tid} [{row.get('route_id', '')} {row.get('direction', '')} "
                f"{row.get('dep_time', '')}→{row.get('arr_time', '')}]"
            )

    st.markdown(f"### 📋 行路表 — 営業所: `{selected_garage}`")
    st.markdown(
        '<div style="background:#f0f4ff;border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.83em;">'
        "<b>work_id</b>=行路ID │ <b>vehicle_id</b>=担当車両 │ "
        "<b>trips</b>=便IDのカンマ区切りリスト（便チェーン）<br>"
        "<b>start_time/end_time</b>=行路の開始・終了時刻"
        "</div>",
        unsafe_allow_html=True,
    )

    display_cols = [c for c in WORK_COLS if c in sub.columns]
    edited = st.data_editor(
        sub[display_cols] if len(sub) > 0 else sub,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk(f"work_{selected_garage}"),
        column_config={
            "work_id": st.column_config.TextColumn("行路 ID"),
            "garage_id": st.column_config.TextColumn("営業所 ID"),
            "vehicle_id": st.column_config.SelectboxColumn(
                "担当車両",
                options=vehicle_ids if vehicle_ids else [""],
            )
            if vehicle_ids
            else st.column_config.TextColumn("担当車両"),
            "service_date": st.column_config.TextColumn("運行日", help="YYYY-MM-DD"),
            "trips": st.column_config.TextColumn(
                "便チェーン",
                help="便IDをカンマ区切りで記述（例: trip_101_ob_0600,trip_101_ib_0640）",
            ),
            "total_trips": st.column_config.NumberColumn("便数", min_value=0),
            "start_time": st.column_config.TextColumn("開始時刻", help="HH:MM"),
            "end_time": st.column_config.TextColumn("終了時刻", help="HH:MM"),
            "total_km": st.column_config.NumberColumn(
                "総走行距離 [km]", min_value=0.0, format="%.1f"
            ),
            "notes": st.column_config.TextColumn("備考"),
        },
    )

    # ---- 行路ビルダー（ドラッグ＆ドロップ代替: マルチセレクト） ----
    st.markdown("---")
    st.markdown("#### 🔧 行路ビルダー（新しい行路を作成）")
    st.caption(
        "使用可能な便を選択して行路を組み立てます。"
        + (
            "（路線間移動: ✅ 許可）"
            if allow_cross_route
            else "（路線間移動: ❌ 禁止）"
        )
    )

    with st.expander("▶ 行路ビルダーを開く", expanded=False):
        builder_cols = st.columns([1, 2, 1])
        with builder_cols[0]:
            b_work_id = st.text_input(
                "行路 ID",
                key=_sk(f"b_wid_{selected_garage}"),
                placeholder=f"work_{selected_garage}_new",
            )
        with builder_cols[1]:
            b_vehicle = st.selectbox(
                "担当車両",
                vehicle_ids if vehicle_ids else [""],
                key=_sk(f"b_veh_{selected_garage}"),
            )
        with builder_cols[2]:
            b_date = st.text_input(
                "運行日", key=_sk(f"b_date_{selected_garage}"), placeholder="2024-04-01"
            )

        # 便の選択（時刻順にソート済みのリストから複数選択）
        sorted_trips = sorted(
            trip_ids,
            key=lambda tid: _parse_time_to_min(
                str(
                    available_trips[available_trips["trip_id"] == tid]["dep_time"].iloc[
                        0
                    ]
                )
                if len(available_trips[available_trips["trip_id"] == tid]) > 0
                else "00:00"
            ),
        )
        trip_labels = [trip_label_map.get(tid, tid) for tid in sorted_trips]

        selected_labels = st.multiselect(
            "便を選択（時刻順に選んでください）",
            trip_labels,
            key=_sk(f"b_trips_{selected_garage}"),
        )

        # ラベル -> trip_id に逆引き
        label_to_tid = {v: k for k, v in trip_label_map.items()}
        selected_trip_ids = [label_to_tid.get(lb, lb) for lb in selected_labels]

        # バリデーション
        if selected_trip_ids:
            chain_warnings = _check_trip_chain(selected_trip_ids, available_trips)
            if chain_warnings:
                for w in chain_warnings:
                    st.warning(w)
            else:
                st.success("✅ 便チェーンに問題はありません。")

            # 行路情報を計算
            trip_data_list = []
            for tid in selected_trip_ids:
                rows = available_trips[available_trips["trip_id"] == tid]
                if len(rows) > 0:
                    trip_data_list.append(rows.iloc[0])

            if trip_data_list:
                first_dep = trip_data_list[0].get("dep_time", "00:00")
                last_arr = trip_data_list[-1].get("arr_time", "00:00")
                st.caption(
                    f"開始: {first_dep} | 終了: {last_arr} | "
                    f"便数: {len(selected_trip_ids)}"
                )

        if st.button("📌 この行路を追加", key=_sk(f"b_add_{selected_garage}")):
            if b_work_id and selected_trip_ids:
                trip_data_list = []
                for tid in selected_trip_ids:
                    rows = available_trips[available_trips["trip_id"] == tid]
                    if len(rows) > 0:
                        trip_data_list.append(rows.iloc[0])

                first_dep = (
                    trip_data_list[0].get("dep_time", "00:00") if trip_data_list else ""
                )
                last_arr = (
                    trip_data_list[-1].get("arr_time", "00:00")
                    if trip_data_list
                    else ""
                )

                new_work = pd.DataFrame(
                    [
                        {
                            "work_id": b_work_id,
                            "garage_id": selected_garage,
                            "vehicle_id": b_vehicle,
                            "service_date": b_date,
                            "trips": ",".join(selected_trip_ids),
                            "total_trips": len(selected_trip_ids),
                            "start_time": str(first_dep),
                            "end_time": str(last_arr),
                            "total_km": 0.0,
                            "notes": "",
                        }
                    ]
                )
                edited = pd.concat([edited, new_work], ignore_index=True)
                # Buffer: merge edited subset back into full work_df
                _other = (
                    work_df[work_df["garage_id"] != selected_garage]
                    if len(work_df) > 0
                    else work_df
                )
                st.session_state[_sk("buf_work")] = pd.concat(
                    [_other, edited], ignore_index=True
                )
                _wk = _sk(f"work_{selected_garage}")
                if _wk in st.session_state:
                    del st.session_state[_wk]
                st.toast(
                    f"行路 '{b_work_id}' を追加しました（{len(selected_trip_ids)} 便）"
                )
                st.rerun()
            else:
                st.error("行路 ID と便を入力してください。")

    # ---- 行路チェーン可視化 ----
    if len(edited) > 0 and len(timetable_df) > 0:
        with st.expander("📊 行路タイムライン（可視化）", expanded=False):
            _render_work_timeline(edited, timetable_df)

    return edited


def _render_work_timeline(work_df: pd.DataFrame, timetable_df: pd.DataFrame) -> None:
    """行路の時刻表をテーブル形式で可視化する。"""
    tt_dict: dict[str, dict] = {}
    for _, row in timetable_df.iterrows():
        tt_dict[str(row["trip_id"])] = {
            "dep_time": str(row.get("dep_time", "")),
            "arr_time": str(row.get("arr_time", "")),
            "route_id": str(row.get("route_id", "")),
            "direction": str(row.get("direction", "")),
        }

    rows = []
    for _, work in work_df.iterrows():
        trips_str = str(work.get("trips", ""))
        trip_ids = [t.strip() for t in trips_str.split(",") if t.strip()]
        vehicle = str(work.get("vehicle_id", "—"))
        work_id = str(work.get("work_id", "—"))

        for seq, tid in enumerate(trip_ids, 1):
            info = tt_dict.get(tid, {})
            rows.append(
                {
                    "行路 ID": work_id,
                    "車両": vehicle,
                    "順序": seq,
                    "便 ID": tid,
                    "路線": info.get("route_id", "—"),
                    "方向": info.get("direction", "—"),
                    "発車": info.get("dep_time", "—"),
                    "到着": info.get("arr_time", "—"),
                }
            )

    if rows:
        timeline_df = pd.DataFrame(rows)
        st.dataframe(timeline_df, use_container_width=True)
    else:
        st.info("行路データがありません。")


# ---------------------------------------------------------------------------
# メインエントリー
# ---------------------------------------------------------------------------


def render_depot_profile_editor(
    data_dir: str = "data",
    show_energy_settings: bool = True,
) -> None:
    """
    営業所・車両プロフィール管理エディタのメイン関数。

    - 営業所プロフィールの管理
    - 車両プロフィールの管理
    - 配車計画（便チェーン / 行路）の作成
    """
    st.markdown(
        """
    <div style="
        background: linear-gradient(135deg, #e8f5e922, #fffde722);
        border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
    ">
        <h3 style="margin:0;">🏢 営業所・配車計画管理</h3>
        <p style="margin:4px 0 0; color:#666; font-size:0.9em;">
            営業所プロフィール・車両プロフィールを管理し、便チェーン（行路）を編成します。
        </p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    data = _load_data(data_dir)
    timetable_df = data["timetable"]
    routes_df = data["routes"]
    # Prefer session_state buffers over disk (edits survive st.rerun())
    garages_df = st.session_state.get(_sk("buf_garages"), data["garages"]).copy()
    vehicles_df = st.session_state.get(_sk("buf_vehicles"), data["vehicles"]).copy()
    work_df = st.session_state.get(_sk("buf_work"), data["work"]).copy()

    # ---- 上部タブ ----
    tab_garages, tab_vehicles, tab_dispatch = st.tabs(
        [
            "🏢 営業所",
            "🚌 車両",
            "📋 配車計画（行路）",
        ]
    )

    with tab_garages:
        garages_df = _render_garages_panel(garages_df)

    with tab_vehicles:
        garage_ids = garages_df["depot_id"].dropna().tolist()
        route_ids = (
            routes_df["route_id"].dropna().tolist() if len(routes_df) > 0 else []
        )
        vehicles_df = _render_vehicles_panel(vehicles_df, garage_ids, route_ids)

    with tab_dispatch:
        if len(garages_df) == 0:
            st.info("先に「営業所」タブで営業所を登録してください。")
        else:
            garage_ids = garages_df["depot_id"].dropna().tolist()
            garage_ids = [g for g in garage_ids if g]

            # --- 営業所選択 & 設定 ---
            dcol1, dcol2 = st.columns([2, 1])
            with dcol1:
                selected_garage = st.selectbox(
                    "配車計画を作成する営業所",
                    garage_ids,
                    key=_sk("selected_garage"),
                )
            with dcol2:
                allow_cross_route = st.checkbox(
                    "路線間移動を許可",
                    value=False,
                    key=_sk("allow_cross_route"),
                    help="チェックすると、一つの行路で複数路線の便を組み合わせられます。",
                )

            # 路線数の確認
            if len(timetable_df) == 0:
                st.info(
                    "時刻表データがありません。「路線管理」タブで時刻表を作成してください。"
                )
            else:
                st.markdown(f"---")
                _full_work = work_df.copy()
                _garage_work = _render_work_schedule_panel(
                    work_df,
                    timetable_df,
                    vehicles_df,
                    garages_df,
                    selected_garage,
                    allow_cross_route,
                )
                # Merge: keep other garages' rows intact, replace
                # only the selected garage's rows with the edited subset.
                _other_work = (
                    _full_work[_full_work["garage_id"] != selected_garage]
                    if len(_full_work) > 0
                    else _full_work
                )
                work_df = pd.concat([_other_work, _garage_work], ignore_index=True)

    if show_energy_settings:
        # ---- ⚙️ 充電設備・電力設定 ----
        st.markdown("---")
        st.markdown(
            """
        <div class="section-header">
          <div class="section-icon">⚡</div>
          <h3>充電設備・電力設定</h3>
        </div>
        """,
            unsafe_allow_html=True,
        )

        with st.expander("🔌 充電設備", expanded=False):
            cc1, cc2 = st.columns(2)
            with cc1:
                st.slider("充電拠点数", 1, 5, 2, key="cfg_depots")
                st.number_input(
                    "普通充電出力 [kW]",
                    10.0,
                    200.0,
                    50.0,
                    step=10.0,
                    key="cfg_slow_pw",
                )
                st.number_input("普通充電器台数", 0, 10, 2, step=1, key="cfg_slow_cnt")
            with cc2:
                st.slider("充電効率", 0.80, 1.00, 0.95, step=0.01, key="cfg_ch_eff")
                st.number_input(
                    "急速充電出力 [kW]",
                    50.0,
                    500.0,
                    150.0,
                    step=10.0,
                    key="cfg_fast_pw",
                )
                st.number_input("急速充電器台数", 0, 10, 1, step=1, key="cfg_fast_cnt")

        with st.expander("☀️ PV・電力料金", expanded=False):
            ec1, ec2 = st.columns(2)
            with ec1:
                st.checkbox("PV を有効にする", value=True, key="cfg_enable_pv")
                st.slider("PV 出力倍率", 0.0, 5.0, 1.0, step=0.1, key="cfg_pv_scale")
            with ec2:
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
                "軽油単価 [円/L]",
                80.0,
                250.0,
                145.0,
                step=5.0,
                key="cfg_diesel",
                help="ICE 比較用",
            )
    else:
        st.info("⚡ 充電設備・電力料金は **システム設定・適用** タブに集約しています。")

    # ---- 保存ボタン ----
    st.markdown("---")
    # Unsaved changes indicator
    _has_unsaved = any(
        _sk(k) in st.session_state for k in ("buf_garages", "buf_vehicles", "buf_work")
    )
    if _has_unsaved:
        st.warning(
            "⚠️ 未保存の変更があります。「営業所データを保存」で確定してください。"
        )
    col_save, col_info = st.columns([1, 3])
    with col_save:
        save_clicked = st.button(
            "💾 営業所データを保存",
            type="primary",
            key=_sk("save_btn"),
        )
    with col_info:
        if save_clicked:
            saved = _save_data(data_dir, garages_df, vehicles_df, work_df)
            # Clear all session_state buffers so next load reads fresh disk data
            for _buf_key in ("buf_garages", "buf_vehicles", "buf_work"):
                sk = _sk(_buf_key)
                if sk in st.session_state:
                    del st.session_state[sk]
            # Clear data_editor widget keys so they don't override fresh data
            for _wk in ("garages_editor", "vehicles_editor"):
                sk = _sk(_wk)
                if sk in st.session_state:
                    del st.session_state[sk]
            # Clear per-garage work editor keys
            for gid in garages_df["depot_id"].dropna().tolist():
                sk = _sk(f"work_{gid}")
                if sk in st.session_state:
                    del st.session_state[sk]
            st.success(f"保存しました: {', '.join(saved)}")
            st.rerun()
