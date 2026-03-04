"""
app/route_profile_editor.py  --  路線プロフィール管理エディタ (v2)

機能:
  1. 複数路線を横断的に管理 (routes.csv)
  2. 地図上のクリックで始点→途中停留所→終点を順に配置
     - 左クリック: 即座に停留所を追加（自動命名）
     - 右クリック: 最寄りの停留所を削除
     - 各停留所に「片道フラグ」(outbound_only / inbound_only) を設定可能
     - 往路の停留所リストから復路を自動生成
  3. 路線ごとに管理営業所を選択 (garages.csv から参照、編集は営業所タブ)
  4. 時刻表 (timetable.csv) の便単位編集
  5. CSV 保存

設計方針:
  - 行路 (便チェーン) は営業所側 (depot_profile_editor.py) に委ねる
  - 路線プロフィールは「停留所リスト」と「時刻表」のみ管理
  - 右クリックは folium.MacroElement で contextmenu イベントを注入し、
    window.__GLOBAL_DATA__.lat_lng_clicked に {lat, lng, _action:'delete'} を
    セットして st_folium の last_clicked 経由で受け取る
"""

from __future__ import annotations

import math
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
_PREFIX = "_rpe_"
_DEFAULT_CENTER = (35.6895, 139.6917)

ROUTES_COLS = [
    "route_id",
    "route_name",
    "operator",
    "city",
    "garage_id",  # 管理営業所
    "route_type",  # "bidirectional" | "circular"
    "total_distance_km",
    "num_stops",
    "description",
]
STOPS_COLS = [
    "stop_id",
    "stop_name",
    "route_id",
    "direction",
    "sequence",
    "lat",
    "lon",
    "is_terminal",
    "terminal_id",
    "is_depot",
    "is_revenue_stop",
    "outbound_only",
    "inbound_only",  # 片道フラグ
    "distance_from_prev_km",
]
TIMETABLE_COLS = [
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
TRIP_STOPS_COLS = [
    "trip_id",
    "stop_id",
    "stop_sequence",
    "passing_time",
]


def _sk(name: str) -> str:
    return f"{_PREFIX}{name}"


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            if c in (
                "is_depot",
                "is_revenue_stop",
                "is_terminal",
                "outbound_only",
                "inbound_only",
            ):
                df[c] = False
            elif c in ("distance_from_prev_km", "lat", "lon", "total_distance_km"):
                df[c] = 0.0
            elif c in ("sequence", "num_stops", "travel_time_min"):
                df[c] = 0
            elif c == "route_type":
                df[c] = "bidirectional"
            else:
                df[c] = ""
    return df


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8")
    return None


def _parse_time_to_min(t: str) -> int:
    m = re.match(r"(\d+):(\d+)", str(t))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


def _min_to_hhmm(minutes: int) -> str:
    """Convert integer minutes-from-midnight to 'HH:MM' string.

    Handles midnight wraparound: 1440 → '00:00', 1500 → '01:00', etc.
    """
    minutes = minutes % (24 * 60)
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _compute_distances(df: pd.DataFrame) -> pd.DataFrame:
    """lat/lon から distance_from_prev_km を再計算する。"""
    df = df.copy()
    df["distance_from_prev_km"] = 0.0
    for i in range(1, len(df)):
        la1, lo1 = df.iloc[i - 1]["lat"], df.iloc[i - 1]["lon"]
        la2, lo2 = df.iloc[i]["lat"], df.iloc[i]["lon"]
        if not any(pd.isna(v) or float(v) == 0 for v in [la1, lo1, la2, lo2]):
            df.iloc[i, df.columns.get_loc("distance_from_prev_km")] = round(
                _haversine_km(float(la1), float(lo1), float(la2), float(lo2)), 3
            )
    return df


def _generate_inbound_stops(outbound: pd.DataFrame, route_id: str) -> pd.DataFrame:
    """往路の停留所リストから復路を自動生成する。

    - outbound_only=True の停留所は復路に含めない
    - 順序を反転し sequence を振り直す
    - stop_id に '_in' サフィックスを付与
    """
    candidates = outbound[outbound.get("outbound_only", False) != True].copy()  # noqa: E712
    if len(candidates) == 0:
        return pd.DataFrame(columns=STOPS_COLS)

    inbound = candidates.iloc[::-1].reset_index(drop=True).copy()
    inbound["direction"] = "inbound"
    inbound["sequence"] = range(1, len(inbound) + 1)
    inbound["stop_id"] = inbound["stop_id"].apply(
        lambda x: x if str(x).endswith("_in") else f"{x}_in"
    )
    inbound["route_id"] = route_id
    inbound["distance_from_prev_km"] = 0.0
    inbound = _compute_distances(inbound)
    return _ensure_cols(inbound, STOPS_COLS)


def _generate_segments(stops_df: pd.DataFrame, route_id: str) -> pd.DataFrame:
    """停留所リストからセグメント DataFrame を自動生成する。

    各連続停留所ペアについて:
    - distance_km: distance_from_prev_km があればそれを使い、なければ Haversine 計算
    - runtime_min: distance / 25 km/h * 60 (デフォルト平均速度)
    - grade_avg_pct: 0.0
    - congestion_index: 1.0
    - road_type: "urban"
    """
    rows = []
    for direction in stops_df["direction"].unique():
        sub = (
            stops_df[stops_df["direction"] == direction]
            .sort_values("sequence")
            .reset_index(drop=True)
        )
        ids = sub["stop_id"].tolist()
        for i in range(len(ids) - 1):
            from_row = sub.iloc[i]
            to_row = sub.iloc[i + 1]
            dist = to_row.get("distance_from_prev_km", 0.0)
            if pd.isna(dist) or float(dist) == 0:
                la1, lo1 = from_row.get("lat"), from_row.get("lon")
                la2, lo2 = to_row.get("lat"), to_row.get("lon")
                try:
                    if all(
                        v is not None and not pd.isna(v) for v in [la1, lo1, la2, lo2]
                    ):
                        dist = round(
                            _haversine_km(
                                float(la1), float(lo1), float(la2), float(lo2)
                            ),
                            3,
                        )
                    else:
                        dist = 0.0
                except (TypeError, ValueError):
                    dist = 0.0
            avg_speed_kmh = 25.0
            runtime = (
                round(float(dist) / avg_speed_kmh * 60.0, 1) if float(dist) > 0 else 0.0
            )
            dir_abbr = str(direction)[:3]
            rows.append(
                {
                    "segment_id": f"seg_{dir_abbr}_{i + 1:02d}",
                    "route_id": route_id,
                    "direction": direction,
                    "from_stop_id": ids[i],
                    "to_stop_id": ids[i + 1],
                    "distance_km": round(float(dist), 3),
                    "runtime_min": runtime,
                    "grade_avg_pct": 0.0,
                    "signal_count": 0,
                    "traffic_level": "medium",
                    "congestion_index": 1.0,
                    "speed_limit_kmh": 40,
                    "road_type": "urban",
                }
            )
    return (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(
            columns=[
                "segment_id",
                "route_id",
                "direction",
                "from_stop_id",
                "to_stop_id",
                "distance_km",
                "runtime_min",
                "grade_avg_pct",
                "signal_count",
                "traffic_level",
                "congestion_index",
                "speed_limit_kmh",
                "road_type",
            ]
        )
    )


# ---------------------------------------------------------------------------
# データ読み込み / 保存
# ---------------------------------------------------------------------------


def _load_data(data_dir: str) -> dict:
    base = Path(data_dir)
    rm = base / "route_master"
    ops = base / "operations"

    routes_df = _load_csv(rm / "routes.csv")
    stops_df = _load_csv(rm / "stops.csv")
    timetable_df = _load_csv(rm / "timetable.csv")
    garages_df = _load_csv(ops / "garages.csv")
    trip_stops_df = _load_csv(rm / "trip_stops.csv")

    if routes_df is None:
        routes_df = pd.DataFrame(columns=ROUTES_COLS)
    routes_df = _ensure_cols(routes_df, ROUTES_COLS)

    if stops_df is None:
        stops_df = pd.DataFrame(columns=STOPS_COLS)
    stops_df = _ensure_cols(stops_df, STOPS_COLS)

    if timetable_df is None:
        timetable_df = pd.DataFrame(columns=TIMETABLE_COLS)
    timetable_df = _ensure_cols(timetable_df, TIMETABLE_COLS)
    # Streamlit data_editor の TextColumn と型不一致を避けるため、
    # 時刻表の文字列列は明示的に文字列へ正規化する。
    timetable_text_cols = [
        "trip_id",
        "route_id",
        "direction",
        "service_type",
        "dep_time",
        "arr_time",
        "from_stop_id",
        "to_stop_id",
        "notes",
    ]
    for col in timetable_text_cols:
        if col in timetable_df.columns:
            timetable_df[col] = timetable_df[col].fillna("").astype(str)

    if garages_df is None:
        garages_df = pd.DataFrame(columns=["depot_id", "depot_name"])

    if trip_stops_df is None:
        trip_stops_df = pd.DataFrame(columns=TRIP_STOPS_COLS)
    trip_stops_df = _ensure_cols(trip_stops_df, TRIP_STOPS_COLS)

    return {
        "routes": routes_df,
        "stops": stops_df,
        "timetable": timetable_df,
        "garages": garages_df,
        "trip_stops": trip_stops_df,
    }


def _save_data(
    data_dir: str,
    routes_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    timetable_df: pd.DataFrame,
    segments_df: Optional[pd.DataFrame] = None,
    trip_stops_df: Optional[pd.DataFrame] = None,
) -> list[str]:
    d = Path(data_dir) / "route_master"
    d.mkdir(parents=True, exist_ok=True)
    routes_df.to_csv(d / "routes.csv", index=False, encoding="utf-8")
    stops_df.to_csv(d / "stops.csv", index=False, encoding="utf-8")
    timetable_df.to_csv(d / "timetable.csv", index=False, encoding="utf-8")
    saved = ["routes.csv", "stops.csv", "timetable.csv"]
    if segments_df is not None and len(segments_df) > 0:
        segments_df.to_csv(d / "segments.csv", index=False, encoding="utf-8")
        saved.append("segments.csv")
    if trip_stops_df is not None and len(trip_stops_df) > 0:
        trip_stops_df.to_csv(d / "trip_stops.csv", index=False, encoding="utf-8")
        saved.append("trip_stops.csv")
    return saved


# ---------------------------------------------------------------------------
# UI: 路線一覧パネル
# ---------------------------------------------------------------------------


def _render_routes_panel(
    routes_df: pd.DataFrame, garage_ids: list[str]
) -> pd.DataFrame:
    """路線テーブル編集 + 追加フォーム（後方互換で保持）。"""
    cc = {
        "route_id": st.column_config.TextColumn("路線 ID"),
        "route_name": st.column_config.TextColumn("路線名"),
        "operator": st.column_config.TextColumn("事業者"),
        "city": st.column_config.TextColumn("市区町村"),
        "garage_id": st.column_config.SelectboxColumn(
            "管理営業所",
            options=garage_ids if garage_ids else ["(未登録)"],
            help="営業所の追加・編集は「営業所管理」タブで行います",
        ),
        "route_type": st.column_config.SelectboxColumn(
            "路線タイプ",
            options=["bidirectional", "circular"],
            help="bidirectional: 往復路線 / circular: 循環路線",
        ),
        "total_distance_km": st.column_config.NumberColumn(
            "総距離 [km]", format="%.1f", min_value=0.0
        ),
        "num_stops": st.column_config.NumberColumn("停留所数", min_value=0),
        "description": st.column_config.TextColumn("説明"),
    }
    edited = st.data_editor(
        routes_df,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk("routes_editor"),
        column_config=cc,
    )
    edited = _render_add_route_form(edited, garage_ids)
    return edited


def _render_add_route_form(
    routes_df: pd.DataFrame, garage_ids: list[str]
) -> pd.DataFrame:
    """新規路線追加フォームのみ（左カラムの Expander 内で使用）。"""
    with st.form(key=_sk("add_route_form"), clear_on_submit=True):
        rc = st.columns([1, 2, 2, 1, 1, 1])
        with rc[0]:
            r_id = st.text_input("路線 ID", placeholder="route_102")
        with rc[1]:
            r_name = st.text_input("路線名", placeholder="東西幹線102号")
        with rc[2]:
            r_op = st.text_input("事業者", placeholder="市交通局")
        with rc[3]:
            r_garage = st.selectbox(
                "営業所", options=[""] + garage_ids, key=_sk("add_route_garage")
            )
        with rc[4]:
            r_type = st.selectbox(
                "タイプ",
                options=["bidirectional", "circular"],
                key=_sk("add_route_type"),
            )
        with rc[5]:
            r_add = st.form_submit_button("追加")
        if r_add and r_id:
            new = pd.DataFrame(
                [
                    {
                        "route_id": r_id,
                        "route_name": r_name,
                        "operator": r_op,
                        "city": "",
                        "garage_id": r_garage,
                        "route_type": r_type,
                        "total_distance_km": 0.0,
                        "num_stops": 0,
                        "description": "",
                    }
                ]
            )
            routes_df = pd.concat([routes_df, new], ignore_index=True)
            st.success(f"路線 '{r_id}' を追加しました。")
    return routes_df


# ---------------------------------------------------------------------------
# 路線カラーパレット
# ---------------------------------------------------------------------------

_ROUTE_COLORS = [
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#84cc16",  # lime
    "#f97316",  # orange
    "#6366f1",  # indigo
]


def _route_color(idx: int) -> str:
    return _ROUTE_COLORS[idx % len(_ROUTE_COLORS)]


# ---------------------------------------------------------------------------
# 概観マップ（全路線 + 営業所を一枧表示、クリックで路線選択）
# ---------------------------------------------------------------------------


def _build_overview_map(
    routes_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    garages_df: pd.DataFrame,
    selected_route: Optional[str] = None,
) -> "folium.Map":
    """全路線を色分けして描画した Folium マップを返す。
    各路線の停留所マーカーに route_id を埋め込み、
    st_folium の last_object_clicked_tooltip で選択を検知する。
    """
    # 中心座標を全停留所の平均で求める
    all_coords = []
    if len(stops_df) > 0:
        valid = stops_df.dropna(subset=["lat", "lon"])
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

    route_ids = routes_df["route_id"].dropna().tolist()

    for idx, rid in enumerate(route_ids):
        color = _route_color(idx)
        is_selected = rid == selected_route
        weight = 6 if is_selected else 3
        opacity = 1.0 if is_selected else 0.55

        rsub = stops_df[stops_df["route_id"] == rid]
        ob = rsub[rsub["direction"] == "outbound"].sort_values("sequence")
        ib = rsub[rsub["direction"] == "inbound"].sort_values("sequence")

        # 往路ライン
        ob_coords = [
            [float(r["lat"]), float(r["lon"])]
            for _, r in ob.iterrows()
            if not pd.isna(r.get("lat")) and float(r["lat"]) != 0
        ]
        if len(ob_coords) >= 2:
            rname = routes_df.loc[routes_df["route_id"] == rid, "route_name"]
            rname = rname.iloc[0] if len(rname) > 0 else rid
            folium.PolyLine(
                ob_coords,
                color=color,
                weight=weight,
                opacity=opacity,
                tooltip=f"__route__{rid}",
            ).add_to(m)

        # 停留所マーカー（往路のみ）
        for _, row in ob.iterrows():
            lat = row.get("lat", 0)
            lon = row.get("lon", 0)
            if pd.isna(lat) or pd.isna(lon) or float(lat) == 0:
                continue
            r_label = (
                routes_df.loc[routes_df["route_id"] == rid, "route_name"].iloc[0]
                if len(routes_df[routes_df["route_id"] == rid]) > 0
                else rid
            )
            folium.CircleMarker(
                location=[float(lat), float(lon)],
                radius=5 if is_selected else 4,
                color=color,
                fill=True,
                fill_opacity=0.9 if is_selected else 0.6,
                tooltip=f"__route__{rid}",
            ).add_to(m)

    # 営業所マーカー
    if (
        len(garages_df) > 0
        and "lat" in garages_df.columns
        and "lon" in garages_df.columns
    ):
        for _, row in garages_df.iterrows():
            lat = row.get("lat", 0)
            lon = row.get("lon", 0)
            if pd.isna(lat) or pd.isna(lon) or float(lat) == 0:
                continue
            gid = str(row.get("depot_id", ""))
            gname = str(row.get("depot_name", gid))
            folium.Marker(
                location=[float(lat), float(lon)],
                icon=folium.Icon(color="darkred", icon="home", prefix="glyphicon"),
                tooltip=f"__garage__{gid}",
                popup=folium.Popup(
                    f"<b>{gname}</b><br>営業所 ID: {gid}", max_width=200
                ),
            ).add_to(m)

    return m


# ---------------------------------------------------------------------------
# UI: 地図エディタ  (メイン機能)
# ---------------------------------------------------------------------------

# Cities Skylines 風 編集ツールバー
#
# 地図右下に浮動ツールバーを注入する。
# ・追加ボタン (A キー): 左クリックで停留所を追加
# ・削除ボタン (D キー): 左クリックで最寄り停留所を削除
# ・右クリックは常に削除ショートカット
# ・アクティブボタンを再クリック / Escape で「編集なし」モードへ
#
# 仕組み:
#   map.on('click', ...) を後付けし、streamlit-folium の onMapClick が
#   セットした window.__GLOBAL_DATA__.lat_lng_clicked を上書きする。
#   debouncedUpdateComponentValue は 250ms 後に起動するため、
#   上書きは必ずその前に完了する（JS はシングルスレッド）。
_EDITOR_JS = """(function () {
  'use strict';
  /* MODE: 'none' | 'add' | 'delete' | 'outbound' | 'terminal' */
  var MODE      = 'add';
  var pendingRC = false;

  function resolveMap() {
    if (window.map && typeof window.map.getContainer === 'function') {
      return window.map;
    }
    var mapEl = document.querySelector('.folium-map') || document.querySelector('.leaflet-container');
    if (mapEl && mapEl.id) {
      var byId = window[mapEl.id];
      if (byId && typeof byId.getContainer === 'function') {
        return byId;
      }
    }
    var keys = Object.keys(window);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (!(k.indexOf('map_') === 0 || k.indexOf('map') === 0)) {
        continue;
      }
      var candidate = window[k];
      if (candidate && typeof candidate.getContainer === 'function' && typeof candidate.on === 'function') {
        return candidate;
      }
    }
    return null;
  }

  function inject() {
    if (document.getElementById('ebus-panel')) return; /* 二重注入防止 */
    var map = resolveMap();
    if (!map) { setTimeout(inject, 300); return; }

    /* ---- CSS ---- */
    var s = document.createElement('style');
    s.id = 'ebus-style';
    s.textContent =
      /* === 下部メニューバー本体 === */
      '#ebus-panel{' +
        'position:absolute;bottom:0;left:50%;transform:translateX(-50%);' +
        'z-index:1000;' +
        'background:rgba(15,15,20,.93);backdrop-filter:blur(8px);' +
        'border:1px solid rgba(255,255,255,.12);border-bottom:none;' +
        'border-radius:12px 12px 0 0;' +
        'padding:8px 18px 11px;' +
        'display:flex;flex-direction:column;align-items:center;gap:6px;' +
        'box-shadow:0 -6px 28px rgba(0,0,0,.6);' +
        'font-family:system-ui,sans-serif;user-select:none;}' +
      /* タイトル */
      '#ebus-panel .eb-title{' +
        'font-size:9px;color:rgba(255,255,255,.28);' +
        'letter-spacing:.14em;text-transform:uppercase;}' +
      /* ボタン行 */
      '#ebus-panel .eb-buttons{display:flex;gap:7px;align-items:center;}' +
      /* 区切り線 */
      '#ebus-panel .eb-sep{' +
        'width:1px;height:42px;' +
        'background:rgba(255,255,255,.11);margin:0 5px;}' +
      /* 各ボタン */
      '#ebus-panel button{' +
        'width:76px;padding:8px 6px 6px;' +
        'border:1.5px solid rgba(255,255,255,.14);border-radius:9px;' +
        'background:rgba(255,255,255,.05);color:rgba(255,255,255,.55);' +
        'font-size:11px;font-weight:600;cursor:pointer;transition:all .12s;' +
        'display:flex;flex-direction:column;align-items:center;gap:3px;}' +
      '#ebus-panel button .eb-icon{font-size:17px;line-height:1;}' +
      '#ebus-panel button .eb-key{font-size:9px;font-weight:400;opacity:.32;}' +
      '#ebus-panel button:hover{background:rgba(255,255,255,.14);color:#fff;}' +
      /* アクティブ状態 */
      '#ebus-panel button.eb-on-none{' +
        'background:rgba(100,116,139,.45);border-color:#94a3b8;color:#fff;}' +
      '#ebus-panel button.eb-on-add{' +
        'background:#16a34a;border-color:#4ade80;color:#fff;' +
        'box-shadow:0 0 14px #16a34a55;}' +
      '#ebus-panel button.eb-on-del{' +
        'background:#dc2626;border-color:#f87171;color:#fff;' +
        'box-shadow:0 0 14px #dc262655;}' +
      '#ebus-panel button.eb-on-out{' +
        'background:#d97706;border-color:#fbbf24;color:#fff;' +
        'box-shadow:0 0 14px #d9770655;}' +
      '#ebus-panel button.eb-on-term{' +
        'background:#7c3aed;border-color:#a78bfa;color:#fff;' +
        'box-shadow:0 0 14px #7c3aed55;}' +
      /* ヒントテキスト */
      '#ebus-panel .eb-hint{' +
        'font-size:10px;color:rgba(255,255,255,.38);' +
        'min-height:13px;text-align:center;}';
    document.head.appendChild(s);

    /* ---- Panel DOM ---- */
    var p = document.createElement('div');
    p.id = 'ebus-panel';
    p.innerHTML =
      '<div class="eb-title">編集ツール</div>' +
      '<div class="eb-buttons">' +
        '<button id="eb-none">' +
          '<span class="eb-icon">\ud83d\udd90\ufe0f</span>カーソル' +
          '<span class="eb-key">N / Esc</span>' +
        '</button>' +
        '<div class="eb-sep"></div>' +
        '<button id="eb-add">' +
          '<span class="eb-icon">\ud83d\udccd</span>停留所追加' +
          '<span class="eb-key">A</span>' +
        '</button>' +
        '<button id="eb-del">' +
          '<span class="eb-icon">\u2716\ufe0f</span>停留所削除' +
          '<span class="eb-key">D</span>' +
        '</button>' +
        '<div class="eb-sep"></div>' +
        '<button id="eb-out">' +
          '<span class="eb-icon">\ud83d\udd04</span>片道フラグ' +
          '<span class="eb-key">O</span>' +
        '</button>' +
        '<button id="eb-term">' +
          '<span class="eb-icon">\ud83d\ude8f</span>始終点設定' +
          '<span class="eb-key">T</span>' +
        '</button>' +
      '</div>' +
      '<div class="eb-hint" id="eb-hint"></div>';
    map.getContainer().appendChild(p);

    /* ツールバーのクリックがマップに伝播しないよう遮断 */
    L.DomEvent.disableClickPropagation(p);
    L.DomEvent.disableScrollPropagation(p);

    /* ---- モード定義 ---- */
    var MODES = {
      'none':     { btn: 'eb-none',  cls: 'eb-on-none', cur: '',          hint: '\u901a\u5e38\u30e2\u30fc\u30c9: \u30d1\u30f3\u30fb\u30ba\u30fc\u30e0' },
      'add':      { btn: 'eb-add',   cls: 'eb-on-add',  cur: 'crosshair', hint: '\u30af\u30ea\u30c3\u30af\u3067\u505c\u7559\u6240\u3092\u8ffd\u52a0' },
      'delete':   { btn: 'eb-del',   cls: 'eb-on-del',  cur: 'cell',      hint: '\u30af\u30ea\u30c3\u30af\u3067\u6700\u5bc4\u308a\u306e\u505c\u7559\u6240\u3092\u524a\u9664' },
      'outbound': { btn: 'eb-out',   cls: 'eb-on-out',  cur: 'pointer',   hint: '\u30af\u30ea\u30c3\u30af\u3067\u6700\u5bc4\u308a\u505c\u7559\u6240\u306e\u300c\u5f80\u8def\u306e\u307f\u300d\u30d5\u30e9\u30b0\u3092\u5207\u66ff' },
      'terminal': { btn: 'eb-term',  cls: 'eb-on-term', cur: 'pointer',   hint: '\u30af\u30ea\u30c3\u30af\u3067\u6700\u5bc4\u308a\u505c\u7559\u6240\u306e\u300c\u59cb\u7d42\u70b9\u300d\u30d5\u30e9\u30b0\u3092\u5207\u66ff' }
    };
    var hi = document.getElementById('eb-hint');

    /* ---- モード切替 ---- */
    function setMode(m) {
      MODE = m;
      Object.keys(MODES).forEach(function (k) {
        var def = MODES[k];
        var el = document.getElementById(def.btn);
        el.className = (k === m) ? def.cls : '';
      });
      map.getContainer().style.cursor = MODES[m] ? MODES[m].cur : '';
      hi.textContent = MODES[m] ? MODES[m].hint : '';
    }

    document.getElementById('eb-none').addEventListener('click', function () { setMode('none'); });
    document.getElementById('eb-add').addEventListener('click', function () {
      setMode(MODE === 'add' ? 'none' : 'add');
    });
    document.getElementById('eb-del').addEventListener('click', function () {
      setMode(MODE === 'delete' ? 'none' : 'delete');
    });
    document.getElementById('eb-out').addEventListener('click', function () {
      setMode(MODE === 'outbound' ? 'none' : 'outbound');
    });
    document.getElementById('eb-term').addEventListener('click', function () {
      setMode(MODE === 'terminal' ? 'none' : 'terminal');
    });

    document.addEventListener('keydown', function (e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      var k = e.key.toUpperCase();
      if (k === 'N' || e.key === 'Escape') setMode('none');
      if (k === 'A') setMode(MODE === 'add'      ? 'none' : 'add');
      if (k === 'D') setMode(MODE === 'delete'   ? 'none' : 'delete');
      if (k === 'O') setMode(MODE === 'outbound' ? 'none' : 'outbound');
      if (k === 'T') setMode(MODE === 'terminal' ? 'none' : 'terminal');
    });

    setMode('add'); /* デフォルト: 追加モード */

    /* ---- マップイベント ---- */
    /* 右クリック → 削除ショートカット */
    map.on('contextmenu', function (e) {
      e.originalEvent.preventDefault();
      pendingRC = true;
      map.fire('click', { latlng: e.latlng });
    });

    /* クリック処理: onMapClick(streamlit-folium) が先に走り lat_lng_clicked を
       セットしたあと、このハンドラが _action を付与して上書きする。
       debouncedUpdateComponentValue は 250ms 後なので競合しない。 */
    map.on('click', function (e) {
      var action = pendingRC ? 'delete' : MODE;
      pendingRC = false;
      if (action === 'none') return;
      if (window.__GLOBAL_DATA__) {
        window.__GLOBAL_DATA__.lat_lng_clicked = {
          lat: e.latlng.lat,
          lng: e.latlng.lng,
          _action: action
        };
      }
    });

    function attachDragHandlers() {
      map.eachLayer(function (layer) {
        if (!layer || !layer.options || !layer.options.draggable) return;
        if (layer.__ebDragBound) return;
        var title = String(layer.options.title || '');
        if (title.indexOf('__stop__') !== 0) return;
        layer.__ebDragBound = true;
        layer.on('dragend', function (evt) {
          var ll = evt && evt.target && evt.target.getLatLng ? evt.target.getLatLng() : null;
          if (!ll || !window.__GLOBAL_DATA__) return;
          window.__GLOBAL_DATA__.lat_lng_clicked = {
            lat: ll.lat,
            lng: ll.lng,
            _action: 'move_stop',
            stop_id: title.slice('__stop__'.length)
          };
        });
      });
    }

    attachDragHandlers();
  }

  inject();
})();
"""


def _build_map(
    outbound: pd.DataFrame,
    inbound: pd.DataFrame,
    charger_sites_df: Optional[pd.DataFrame] = None,
) -> "folium.Map":
    """停留所データから folium.Map を構築して返す。"""
    center_lat, center_lon = _DEFAULT_CENTER
    valid = outbound.dropna(subset=["lat", "lon"])
    valid = valid[(valid["lat"].astype(float) != 0) & (valid["lon"].astype(float) != 0)]
    if len(valid) > 0:
        center_lat = float(valid["lat"].mean())
        center_lon = float(valid["lon"].mean())

    m = folium.Map(
        location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron"
    )

    # 編集ツールバー JS を注入
    # <script> で包んで確実に実行させる
    from branca.element import Element as BrancaElement

    m.get_root().script.add_child(BrancaElement(f"<script>{_EDITOR_JS}</script>"))

    # 往路マーカー + ライン
    ob_coords = []
    for _, row in outbound.iterrows():
        lat = row.get("lat", 0)
        lon = row.get("lon", 0)
        if pd.isna(lat) or pd.isna(lon) or float(lat) == 0 or float(lon) == 0:
            continue
        lat, lon = float(lat), float(lon)
        ob_coords.append([lat, lon])
        seq = int(row.get("sequence", 0))
        name = str(row.get("stop_name", ""))
        is_term = str(row.get("is_terminal", False)).lower() in ("true", "1")
        is_depot = str(row.get("is_depot", False)).lower() in ("true", "1")
        ob_only = str(row.get("outbound_only", False)).lower() in ("true", "1")

        # 色分け: 始終点=赤, 車庫=紫, 往路のみ=オレンジ, 通常=青
        if is_term or is_depot:
            color, radius = "#e74c3c", 9
        elif ob_only:
            color, radius = "#e07b39", 7
        else:
            color, radius = "#3388ff", 6

        popup_html = (
            f"<b>{seq}. {name}</b><br>"
            f"ID: {row.get('stop_id', '')}<br>"
            f"{'始終点 ' if is_term else ''}{'車庫 ' if is_depot else ''}"
            f"{'往路のみ ' if ob_only else ''}"
        )
        folium.Marker(
            location=[lat, lon],
            draggable=True,
            title=f"__stop__{row.get('stop_id', '')}",
            icon=folium.DivIcon(
                icon_size=(24, 24),
                icon_anchor=(12, 12),
                html=(
                    '<div style="'
                    f"width:{radius * 2}px;height:{radius * 2}px;"
                    "border-radius:50%;"
                    f"background:{color};"
                    "color:#fff;"
                    "font-size:10px;font-weight:700;"
                    "display:flex;align-items:center;justify-content:center;"
                    "border:2px solid #ffffffcc;"
                    'box-shadow:0 0 2px rgba(0,0,0,.35);">'
                    f"{seq}"
                    "</div>"
                ),
            ),
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{seq}. {name}",
        ).add_to(m)

    if len(ob_coords) >= 2:
        folium.PolyLine(
            ob_coords, color="#3388ff", weight=4, opacity=0.7, tooltip="往路 (outbound)"
        ).add_to(m)

    # 復路ライン (薄く表示)
    ib_coords = []
    for _, row in inbound.iterrows():
        lat = row.get("lat", 0)
        lon = row.get("lon", 0)
        if (
            not pd.isna(lat)
            and not pd.isna(lon)
            and float(lat) != 0
            and float(lon) != 0
        ):
            ib_coords.append([float(lat), float(lon)])
    if len(ib_coords) >= 2:
        folium.PolyLine(
            ib_coords,
            color="#e07b39",
            weight=3,
            opacity=0.4,
            dash_array="8",
            tooltip="復路 (inbound, 自動生成)",
        ).add_to(m)

    # 充電拠点レイヤー
    if charger_sites_df is not None and len(charger_sites_df) > 0:
        fg_cs = folium.FeatureGroup(name="⚡ 充電拠点")
        for _, row in charger_sites_df.iterrows():
            lat = row.get("lat")
            lon = row.get("lon")
            try:
                if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
                    continue
                lat, lon = float(lat), float(lon)
                if lat == 0.0 and lon == 0.0:
                    continue
            except (TypeError, ValueError):
                continue
            site_name = str(
                row.get("site_name", row.get("name", row.get("site_id", "")))
            )
            max_kw = row.get("max_power_kW", row.get("max_grid_kw", ""))
            folium.Marker(
                location=[lat, lon],
                icon=folium.Icon(color="green", icon="flash", prefix="glyphicon"),
                popup=folium.Popup(
                    f"<b>{site_name}</b><br>最大出力: {max_kw} kW",
                    max_width=200,
                ),
                tooltip=f"⚡ {site_name}",
            ).add_to(fg_cs)
        fg_cs.add_to(m)
        folium.LayerControl().add_to(m)

    return m


def _nearest_stop_index(
    outbound: pd.DataFrame, lat: float, lon: float
) -> Optional[int]:
    """往路の停留所リストから最寄りの行インデックスを返す。"""
    min_dist = float("inf")
    nearest = None
    for i, row in outbound.iterrows():
        rlat = row.get("lat", 0)
        rlon = row.get("lon", 0)
        if pd.isna(rlat) or pd.isna(rlon) or float(rlat) == 0 or float(rlon) == 0:
            continue
        d = _haversine_km(float(rlat), float(rlon), lat, lon)
        if d < min_dist:
            min_dist = d
            nearest = i
    return nearest


def _render_map_editor(
    stops_df: pd.DataFrame,
    route_id: str,
    routes_df: pd.DataFrame,
    charger_sites_df: "pd.DataFrame | None" = None,
) -> pd.DataFrame:
    """
    地図上での直接編集:
      左クリック  → 即座に停留所を追加（自動命名「停留所N」）
      右クリック  → 最寄りの停留所を削除
      地図下テーブル → 停留所名・フラグを後から編集可能
    """

    if not FOLIUM_AVAILABLE:
        st.warning(
            "地図入力には **folium** + **streamlit-folium** が必要です。\n\n"
            "```\npip install folium streamlit-folium\n```"
        )
        return _render_table_editor(stops_df, route_id)

    # --- session state keys ---
    ss_stops = _sk(f"map_stops_{route_id}")
    ss_last = _sk(f"last_click_{route_id}")  # 前回処理済みクリック座標
    ss_mode = _sk(f"map_mode_{route_id}")
    ss_pending = _sk(f"pending_stop_moves_{route_id}")

    if ss_mode not in st.session_state:
        st.session_state[ss_mode] = "add"
    if ss_pending not in st.session_state:
        st.session_state[ss_pending] = {}

    # 初回: CSVデータをセッションにコピー
    if ss_stops not in st.session_state:
        sub = (
            stops_df[stops_df["route_id"] == route_id].copy()
            if len(stops_df) > 0
            else pd.DataFrame(columns=STOPS_COLS)
        )
        st.session_state[ss_stops] = _ensure_cols(sub, STOPS_COLS)

    sub: pd.DataFrame = st.session_state[ss_stops].copy()
    outbound = (
        sub[sub["direction"] == "outbound"]
        .sort_values("sequence")
        .reset_index(drop=True)
    )
    inbound = (
        sub[sub["direction"] == "inbound"]
        .sort_values("sequence")
        .reset_index(drop=True)
    )
    n_ob = len(outbound)

    pending_moves: dict[str, dict] = st.session_state.get(ss_pending, {}) or {}
    outbound_preview = outbound.copy()
    if (
        pending_moves
        and len(outbound_preview) > 0
        and "stop_id" in outbound_preview.columns
    ):
        for sid, move in pending_moves.items():
            m = outbound_preview["stop_id"] == sid
            if m.any():
                outbound_preview.loc[m, "lat"] = float(move["lat"])
                outbound_preview.loc[m, "lon"] = float(move["lon"])
        outbound_preview = _compute_distances(outbound_preview)
    inbound_preview = _generate_inbound_stops(outbound_preview, route_id)

    # --- 操作ガイド ---
    st.caption(
        "地図下のメニューで編集モードを選択してからクリックしてください。"
        "（停留所マーカーはドラッグで一時移動できます。下の適用ボタンで確定）"
    )

    # --- 地図描画 ---
    m = _build_map(outbound_preview, inbound_preview, charger_sites_df=charger_sites_df)

    # --- 地図表示 + クリックイベント取得 ---
    map_result = st_folium(
        m,
        width="100%",
        height=520,
        key=_sk(f"fmap_{route_id}"),
        returned_objects=["last_clicked"],
    )

    # --- 地図下部メニュー（JS非依存のフォールバック） ---
    mode_labels = {
        "none": "🖐️ カーソル",
        "add": "📍 停留所追加",
        "delete": "✖️ 停留所削除",
        "outbound": "🔄 片道フラグ",
        "terminal": "🚏 始終点設定",
    }
    st.radio(
        "地図下部メニュー",
        options=list(mode_labels.keys()),
        horizontal=True,
        key=ss_mode,
        format_func=lambda x: mode_labels.get(x, x),
    )

    if pending_moves:
        st.info(f"ドラッグ移動の未適用変更: {len(pending_moves)} 件")
        ac1, ac2 = st.columns(2)
        with ac1:
            if st.button(
                "✅ ドラッグ移動を適用", key=_sk(f"apply_stop_moves_{route_id}")
            ):
                latest_sub = st.session_state[ss_stops].copy()
                latest_ob = (
                    latest_sub[latest_sub["direction"] == "outbound"]
                    .sort_values("sequence")
                    .reset_index(drop=True)
                )
                for sid, move in pending_moves.items():
                    if "stop_id" in latest_ob.columns:
                        mm = latest_ob["stop_id"] == sid
                        if mm.any():
                            latest_ob.loc[mm, "lat"] = float(move["lat"])
                            latest_ob.loc[mm, "lon"] = float(move["lon"])
                latest_ob = _compute_distances(latest_ob)
                latest_ib = _generate_inbound_stops(latest_ob, route_id)
                st.session_state[ss_stops] = pd.concat(
                    [latest_ob, latest_ib], ignore_index=True
                )
                st.session_state[ss_pending] = {}
                st.toast("ドラッグ移動を適用しました", icon="✅")
                st.rerun()
        with ac2:
            if st.button(
                "🗑️ ドラッグ移動を破棄", key=_sk(f"discard_stop_moves_{route_id}")
            ):
                st.session_state[ss_pending] = {}
                st.toast("未適用のドラッグ移動を破棄しました", icon="🧹")
                st.rerun()

    # --- クリックイベント処理 ---
    lc = None
    if map_result and isinstance(map_result, dict):
        lc = map_result.get("last_clicked")

    if lc and isinstance(lc, dict):
        c_lat = lc.get("lat")
        c_lng = lc.get("lng")
        raw_action = lc.get("_action", "none")
        action = (
            raw_action
            if raw_action
            in ("add", "delete", "outbound", "terminal", "move_stop", "none")
            else "none"
        )
        if action == "none":
            action = st.session_state.get(ss_mode, "add")

        # 'none' モード (ツールバーで未選択) は無視
        if action not in ("add", "delete", "outbound", "terminal", "move_stop"):
            pass
        else:
            # 同一クリックを二重処理しないようキャッシュと比較
            click_sig = (
                round(c_lat or 0, 7),
                round(c_lng or 0, 7),
                action,
                str(lc.get("stop_id", "")),
            )
            if click_sig != st.session_state.get(ss_last):
                st.session_state[ss_last] = click_sig

                if c_lat is not None and c_lng is not None:
                    if action == "move_stop" and n_ob > 0:
                        sid = str(lc.get("stop_id", "") or "")
                        if sid and "stop_id" in outbound.columns:
                            matches = outbound[outbound["stop_id"] == sid]
                            if len(matches) > 0:
                                stop_name = str(matches.iloc[0].get("stop_name", sid))
                                pending = dict(
                                    st.session_state.get(ss_pending, {}) or {}
                                )
                                pending[sid] = {
                                    "lat": float(c_lat),
                                    "lon": float(c_lng),
                                    "stop_name": stop_name,
                                }
                                st.session_state[ss_pending] = pending
                                st.toast(f"一時移動: {stop_name} (未適用)", icon="📍")
                                st.rerun()
                    elif action == "delete" and n_ob > 0:
                        # --- 削除モード: 最寄り停留所を削除 ---
                        nearest_idx = _nearest_stop_index(
                            outbound, float(c_lat), float(c_lng)
                        )
                        if nearest_idx is not None:
                            removed_name = outbound.loc[nearest_idx, "stop_name"]
                            updated_ob = outbound.drop(index=nearest_idx).reset_index(
                                drop=True
                            )
                            updated_ob["sequence"] = range(1, len(updated_ob) + 1)
                            updated_ob = _compute_distances(updated_ob)
                            updated_ib = _generate_inbound_stops(updated_ob, route_id)
                            combined = pd.concat(
                                [updated_ob, updated_ib], ignore_index=True
                            )
                            st.session_state[ss_stops] = combined
                            st.toast(f"削除: {removed_name}", icon="🗑️")
                            st.rerun()
                    elif action == "add":
                        # --- 追加モード: 停留所を即追加 ---
                        next_seq = n_ob + 1
                        auto_name = f"停留所{next_seq}"
                        sid = f"stop_{route_id}_{next_seq:03d}"
                        is_first = n_ob == 0
                        new_row = pd.DataFrame(
                            [
                                {
                                    "stop_id": sid,
                                    "stop_name": auto_name,
                                    "route_id": route_id,
                                    "direction": "outbound",
                                    "sequence": next_seq,
                                    "lat": float(c_lat),
                                    "lon": float(c_lng),
                                    "is_terminal": is_first,
                                    "terminal_id": "",
                                    "is_depot": False,
                                    "is_revenue_stop": True,
                                    "outbound_only": False,
                                    "inbound_only": False,
                                    "distance_from_prev_km": 0.0,
                                }
                            ]
                        )
                        new_row = _ensure_cols(new_row, STOPS_COLS)
                        updated_ob = pd.concat([outbound, new_row], ignore_index=True)
                        updated_ob = _compute_distances(updated_ob)
                        updated_ib = _generate_inbound_stops(updated_ob, route_id)
                        combined = pd.concat(
                            [updated_ob, updated_ib], ignore_index=True
                        )
                        st.session_state[ss_stops] = combined
                        st.rerun()
                    elif action == "outbound" and n_ob > 0:
                        # --- 片道フラグモード: 最寄り停留所の outbound_only を切替 ---
                        nearest_idx = _nearest_stop_index(
                            outbound, float(c_lat), float(c_lng)
                        )
                        if nearest_idx is not None:
                            cur_val = bool(outbound.loc[nearest_idx, "outbound_only"])
                            new_val = not cur_val
                            updated_ob = outbound.copy()
                            updated_ob.at[nearest_idx, "outbound_only"] = new_val
                            stop_name = updated_ob.loc[nearest_idx, "stop_name"]
                            updated_ib = _generate_inbound_stops(updated_ob, route_id)
                            combined = pd.concat(
                                [updated_ob, updated_ib], ignore_index=True
                            )
                            st.session_state[ss_stops] = combined
                            flag_str = "ON (往路のみ)" if new_val else "OFF (両方向)"
                            st.toast(f"片道フラグ: {stop_name} → {flag_str}", icon="🔄")
                            st.rerun()
                    elif action == "terminal" and n_ob > 0:
                        # --- 始終点設定モード: 最寄り停留所の is_terminal を切替 ---
                        nearest_idx = _nearest_stop_index(
                            outbound, float(c_lat), float(c_lng)
                        )
                        if nearest_idx is not None:
                            cur_val = bool(outbound.loc[nearest_idx, "is_terminal"])
                            new_val = not cur_val
                            updated_ob = outbound.copy()
                            updated_ob.at[nearest_idx, "is_terminal"] = new_val
                            stop_name = updated_ob.loc[nearest_idx, "stop_name"]
                            updated_ib = _generate_inbound_stops(updated_ob, route_id)
                            combined = pd.concat(
                                [updated_ob, updated_ib], ignore_index=True
                            )
                            st.session_state[ss_stops] = combined
                            flag_str = "ON (始終点)" if new_val else "OFF (通過停留所)"
                            st.toast(
                                f"始終点フラグ: {stop_name} → {flag_str}", icon="🚏"
                            )
                            st.rerun()

    # --- 操作ボタン ---
    bcol1, bcol2, bcol3 = st.columns(3)
    with bcol1:
        if n_ob > 0 and st.button("🔄 復路を再生成", key=_sk(f"regen_ib_{route_id}")):
            updated_ib = _generate_inbound_stops(outbound, route_id)
            combined = pd.concat([outbound, updated_ib], ignore_index=True)
            st.session_state[ss_stops] = combined
            st.rerun()
    with bcol2:
        if n_ob > 0 and st.button("↩️ 最後の停留所を削除", key=_sk(f"undo_{route_id}")):
            updated_ob = outbound.iloc[:-1].reset_index(drop=True).copy()
            updated_ob = _compute_distances(updated_ob)
            updated_ib = _generate_inbound_stops(updated_ob, route_id)
            combined = pd.concat([updated_ob, updated_ib], ignore_index=True)
            st.session_state[ss_stops] = combined
            st.rerun()
    with bcol3:
        if st.button("🗑️ 停留所をすべてクリア", key=_sk(f"clear_{route_id}")):
            st.session_state[ss_stops] = pd.DataFrame(columns=STOPS_COLS)
            st.session_state.pop(ss_last, None)
            st.rerun()

    # --- 往路テーブル (停留所名・フラグを inline 編集可能) ---
    # セッションの最新データを再取得（rerun前のサイクルでも反映）
    sub_latest = st.session_state[ss_stops].copy()
    outbound_latest = (
        sub_latest[sub_latest["direction"] == "outbound"]
        .sort_values("sequence")
        .reset_index(drop=True)
    )
    inbound_latest = (
        sub_latest[sub_latest["direction"] == "inbound"]
        .sort_values("sequence")
        .reset_index(drop=True)
    )
    n_ob_latest = len(outbound_latest)

    if n_ob_latest > 0:
        st.markdown("##### 往路の停留所（名前・フラグを直接編集できます）")
        edit_cols = [
            "sequence",
            "stop_name",
            "lat",
            "lon",
            "is_terminal",
            "is_depot",
            "outbound_only",
            "inbound_only",
            "distance_from_prev_km",
        ]
        edited_ob = st.data_editor(
            outbound_latest[[c for c in edit_cols if c in outbound_latest.columns]],
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=_sk(f"ob_table_{route_id}"),
            column_config={
                "sequence": st.column_config.NumberColumn("順序", disabled=True),
                "stop_name": st.column_config.TextColumn("停留所名"),
                "lat": st.column_config.NumberColumn(
                    "緯度", format="%.6f", disabled=True
                ),
                "lon": st.column_config.NumberColumn(
                    "経度", format="%.6f", disabled=True
                ),
                "is_terminal": st.column_config.CheckboxColumn("始終点"),
                "is_depot": st.column_config.CheckboxColumn("車庫"),
                "outbound_only": st.column_config.CheckboxColumn("往路のみ"),
                "inbound_only": st.column_config.CheckboxColumn("復路のみ"),
                "distance_from_prev_km": st.column_config.NumberColumn(
                    "前停距離[km]", format="%.3f", disabled=True
                ),
            },
        )

        # テーブル編集内容をセッションに反映（stop_idなど非表示列を補完）
        for col in outbound_latest.columns:
            if col not in edited_ob.columns:
                edited_ob[col] = outbound_latest[col].values[: len(edited_ob)]
        edited_ob["route_id"] = route_id
        edited_ob["direction"] = "outbound"

        # 変更があればセッション更新（フラグ変更 → 復路再生成）
        if not edited_ob[
            ["stop_name", "is_terminal", "is_depot", "outbound_only", "inbound_only"]
        ].equals(
            outbound_latest[
                [
                    "stop_name",
                    "is_terminal",
                    "is_depot",
                    "outbound_only",
                    "inbound_only",
                ]
            ]
        ):
            new_ib = _generate_inbound_stops(edited_ob, route_id)
            st.session_state[ss_stops] = pd.concat(
                [edited_ob, new_ib], ignore_index=True
            )

        total_dist = float(outbound_latest["distance_from_prev_km"].sum())
        st.caption(
            f"往路距離合計: **{total_dist:.2f} km** / 停留所数: **{n_ob_latest}**"
        )

    if len(inbound_latest) > 0:
        with st.expander(
            f"復路の停留所 ({len(inbound_latest)} 個, 自動生成)", expanded=False
        ):
            st.dataframe(
                inbound_latest[
                    [
                        c
                        for c in [
                            "sequence",
                            "stop_name",
                            "lat",
                            "lon",
                            "distance_from_prev_km",
                        ]
                        if c in inbound_latest.columns
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    return st.session_state[ss_stops]


# ---------------------------------------------------------------------------
# UI: テーブル編集 (フォールバック / 詳細編集)
# ---------------------------------------------------------------------------


def _render_table_editor(stops_df: pd.DataFrame, route_id: str) -> pd.DataFrame:
    sub = (
        stops_df[stops_df["route_id"] == route_id].copy()
        if len(stops_df) > 0
        else stops_df.copy()
    )
    sub = _ensure_cols(sub, STOPS_COLS)

    st.markdown(f"#### 停留所テーブル -- `{route_id}`")

    display_cols = [
        "sequence",
        "stop_id",
        "stop_name",
        "direction",
        "lat",
        "lon",
        "is_terminal",
        "is_depot",
        "outbound_only",
        "inbound_only",
        "distance_from_prev_km",
    ]
    display_cols = [c for c in display_cols if c in sub.columns]

    sorted_sub = (
        sub[display_cols].sort_values(["direction", "sequence"])
        if len(sub) > 0
        else sub[display_cols]
    )

    edited = st.data_editor(
        sorted_sub,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk(f"table_stops_{route_id}"),
        column_config={
            "sequence": st.column_config.NumberColumn("順序", min_value=1, step=1),
            "stop_id": st.column_config.TextColumn("停留所 ID"),
            "stop_name": st.column_config.TextColumn("停留所名"),
            "direction": st.column_config.SelectboxColumn(
                "方向", options=["outbound", "inbound"], default="outbound"
            ),
            "lat": st.column_config.NumberColumn("緯度", format="%.6f"),
            "lon": st.column_config.NumberColumn("経度", format="%.6f"),
            "is_terminal": st.column_config.CheckboxColumn("始終点", default=False),
            "is_depot": st.column_config.CheckboxColumn("車庫", default=False),
            "outbound_only": st.column_config.CheckboxColumn("往路のみ", default=False),
            "inbound_only": st.column_config.CheckboxColumn("復路のみ", default=False),
            "distance_from_prev_km": st.column_config.NumberColumn(
                "前停距離 [km]", min_value=0.0, step=0.1, format="%.3f"
            ),
        },
    )
    # 非表示列を補完
    for c in sub.columns:
        if c not in edited.columns:
            vals = sub[c].values
            edited[c] = vals[: len(edited)] if len(vals) >= len(edited) else ""
    edited["route_id"] = route_id
    return edited


# ---------------------------------------------------------------------------
# UI: 時刻表パネル
# ---------------------------------------------------------------------------


def _calc_passing_times(
    trip_id: str,
    dep_min: int,
    arr_min: int,
    ordered_stops_df: pd.DataFrame,
) -> pd.DataFrame:
    """停留所ごとの通過時刻を距離比例で補間して返す。

    Parameters
    ----------
    trip_id : str
    dep_min : int  — departure time in minutes from midnight
    arr_min : int  — arrival time in minutes from midnight (may exceed 1440)
    ordered_stops_df : pd.DataFrame
        停留所を sequence 順に並べたもの。
        'stop_id' と 'distance_from_prev_km' カラムが必要。

    Returns
    -------
    pd.DataFrame with TRIP_STOPS_COLS columns.
    """
    if len(ordered_stops_df) == 0:
        return pd.DataFrame(columns=TRIP_STOPS_COLS)

    stops = ordered_stops_df.reset_index(drop=True).copy()
    # 累積距離を計算
    stops["_cum_dist"] = stops["distance_from_prev_km"].fillna(0.0).cumsum()
    total_dist = float(stops["_cum_dist"].iloc[-1])
    travel_min = arr_min - dep_min

    rows = []
    for seq, row in stops.iterrows():
        if total_dist > 0:
            frac = float(row["_cum_dist"]) / total_dist
        else:
            # 距離が全部 0 の場合は等分割
            frac = seq / max(len(stops) - 1, 1)
        passing_min = dep_min + round(travel_min * frac)
        rows.append(
            {
                "trip_id": trip_id,
                "stop_id": row["stop_id"],
                "stop_sequence": int(seq) + 1,
                "passing_time": _min_to_hhmm(passing_min),
            }
        )
    return pd.DataFrame(rows, columns=TRIP_STOPS_COLS)


def _generate_trips_from_headway(
    route_id: str,
    direction: str,
    headway_min: int,
    start_time: str,
    end_time: str,
    service_type: str,
    from_stop_id: str,
    to_stop_id: str,
    travel_time_min: int,
) -> pd.DataFrame:
    """ヘッドウェイから便一覧を生成する。

    Trip IDs are auto-named as:
        trip_{route_id_no_prefix}_{dir_code}_{HHMM}
    where dir_code is 'ob' for outbound, 'ib' for inbound, 'cr' for circular.
    """
    dir_code = {"outbound": "ob", "inbound": "ib", "circular": "cr"}.get(
        direction, "ob"
    )
    rid_short = route_id.replace("route_", "")

    start_min = _parse_time_to_min(start_time)
    end_min = _parse_time_to_min(end_time)
    if end_min <= start_min:
        end_min += 24 * 60  # overnight service

    rows = []
    t = start_min
    while t <= end_min:
        dep_hhmm = _min_to_hhmm(t)
        arr_min = t + travel_time_min
        arr_hhmm = _min_to_hhmm(arr_min)
        trip_id = f"trip_{rid_short}_{dir_code}_{dep_hhmm.replace(':', '')}"
        rows.append(
            {
                "trip_id": trip_id,
                "route_id": route_id,
                "direction": direction,
                "service_type": service_type,
                "dep_time": dep_hhmm,
                "arr_time": arr_hhmm,
                "from_stop_id": from_stop_id,
                "to_stop_id": to_stop_id,
                "travel_time_min": travel_time_min,
                "notes": "",
            }
        )
        t += headway_min

    if not rows:
        return pd.DataFrame(columns=TIMETABLE_COLS)
    return pd.DataFrame(rows, columns=TIMETABLE_COLS)


def _render_direction_timetable(
    sub_df: pd.DataFrame,
    direction: str,
    route_id: str,
    route_stops_df: pd.DataFrame,
    trip_stops_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1 方向分の時刻表パネルをレンダリングし、編集後の (timetable_slice, trip_stops_df) を返す。"""
    # 方向別の停留所を抽出
    dir_stops = (
        route_stops_df[route_stops_df["direction"] == direction].sort_values("sequence")
        if len(route_stops_df) > 0
        else route_stops_df
    )
    stop_ids = dir_stops["stop_id"].tolist() if len(dir_stops) > 0 else []
    from_stop = stop_ids[0] if stop_ids else ""
    to_stop = stop_ids[-1] if len(stop_ids) > 1 else from_stop

    # セッションステートキー
    wk_key = _sk(f"working_tt_{route_id}_{direction}")
    if wk_key not in st.session_state:
        st.session_state[wk_key] = sub_df.copy()

    # ---- ヘッドウェイ一括生成 ----
    with st.expander("⚡ ヘッドウェイから一括生成", expanded=False):
        # --- バンドテーブル初期化 ---
        bands_key = _sk(f"hw_bands_{route_id}_{direction}")
        if bands_key not in st.session_state:
            st.session_state[bands_key] = pd.DataFrame(
                {
                    "start_time": ["06:00", "09:00", "17:00", "20:00"],
                    "end_time": ["09:00", "17:00", "20:00", "22:00"],
                    "headway_min": [10, 20, 10, 30],
                }
            )

        st.caption("時間帯ごとにヘッドウェイを設定できます。行の追加・削除が可能です。")
        edited_bands = st.data_editor(
            st.session_state[bands_key],
            num_rows="dynamic",
            use_container_width=True,
            key=_sk(f"hw_bands_editor_{route_id}_{direction}"),
            column_config={
                "start_time": st.column_config.TextColumn("始発", help="HH:MM"),
                "end_time": st.column_config.TextColumn("終発", help="HH:MM"),
                "headway_min": st.column_config.NumberColumn(
                    "間隔 [分]", min_value=1, step=1
                ),
            },
        )
        st.session_state[bands_key] = edited_bands

        hc = st.columns([1, 1, 1, 1])
        with hc[0]:
            hw_svc = st.selectbox(
                "運行区分",
                ["weekday", "holiday", "all"],
                key=_sk(f"hw_svc_{route_id}_{direction}"),
            )
        with hc[1]:
            hw_travel = st.number_input(
                "所要 [分]",
                min_value=1,
                value=30,
                step=1,
                key=_sk(f"hw_travel_{route_id}_{direction}"),
            )
        with hc[2]:
            hw_replace = st.checkbox(
                "既存便を置き換える",
                value=False,
                key=_sk(f"hw_replace_{route_id}_{direction}"),
            )
        with hc[3]:
            hw_gen = st.button(
                "生成", key=_sk(f"hw_gen_{route_id}_{direction}"), type="primary"
            )
        if hw_gen:
            band_results = []
            for _, band_row in edited_bands.iterrows():
                band_trips = _generate_trips_from_headway(
                    route_id=route_id,
                    direction=direction,
                    headway_min=int(band_row["headway_min"]),
                    start_time=str(band_row["start_time"]),
                    end_time=str(band_row["end_time"]),
                    service_type=hw_svc,
                    from_stop_id=from_stop,
                    to_stop_id=to_stop,
                    travel_time_min=int(hw_travel),
                )
                band_results.append(band_trips)
            if band_results:
                new_trips = pd.concat(band_results, ignore_index=True).drop_duplicates(
                    subset=["trip_id"]
                )
            else:
                new_trips = pd.DataFrame(columns=TIMETABLE_COLS)
            if hw_replace:
                st.session_state[wk_key] = new_trips
            else:
                st.session_state[wk_key] = pd.concat(
                    [st.session_state[wk_key], new_trips], ignore_index=True
                ).drop_duplicates(subset=["trip_id"])
            # Force data_editor reinit by deleting its key
            editor_key = _sk(f"tt_editor_{route_id}_{direction}")
            if editor_key in st.session_state:
                del st.session_state[editor_key]
            st.success(f"{len(new_trips)} 便を生成しました。")

    # ---- テーブル編集 ----
    working = st.session_state[wk_key]
    display_cols = [c for c in TIMETABLE_COLS if c in working.columns]
    sorted_working = (
        working[display_cols].sort_values("dep_time")
        if len(working) > 0
        else working[display_cols]
    )

    cc = {
        "trip_id": st.column_config.TextColumn("便 ID"),
        "route_id": st.column_config.TextColumn("路線 ID", disabled=True),
        "direction": st.column_config.SelectboxColumn(
            "方向", options=["outbound", "inbound", "circular"], default=direction
        ),
        "service_type": st.column_config.SelectboxColumn(
            "運行区分", options=["weekday", "holiday", "all"], default="weekday"
        ),
        "dep_time": st.column_config.TextColumn("発車", help="HH:MM"),
        "arr_time": st.column_config.TextColumn("到着", help="HH:MM"),
        "travel_time_min": st.column_config.NumberColumn("所要 [分]", min_value=0),
        "notes": st.column_config.TextColumn("備考"),
    }
    if stop_ids:
        cc["from_stop_id"] = st.column_config.SelectboxColumn(
            "出発停留所", options=stop_ids
        )
        cc["to_stop_id"] = st.column_config.SelectboxColumn(
            "終点停留所", options=stop_ids
        )

    edited = st.data_editor(
        sorted_working,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk(f"tt_editor_{route_id}_{direction}"),
        column_config=cc,
    )
    edited["route_id"] = route_id
    # Sync session state with edits
    st.session_state[wk_key] = edited

    # ---- 中間停留所 通過時刻計算 ----
    if len(dir_stops) > 2:
        with st.expander("🚏 中間停留所 通過時刻計算", expanded=False):
            trip_ids = edited["trip_id"].dropna().tolist() if len(edited) > 0 else []
            if trip_ids:
                sel_trip = st.selectbox(
                    "便を選択",
                    trip_ids,
                    key=_sk(f"calc_trip_{route_id}_{direction}"),
                )
                trip_row = edited[edited["trip_id"] == sel_trip]
                if len(trip_row) > 0:
                    tr = trip_row.iloc[0]
                    dep_m = _parse_time_to_min(str(tr["dep_time"]))
                    arr_m = _parse_time_to_min(str(tr["arr_time"]))
                    if arr_m < dep_m:
                        arr_m += 24 * 60
                    preview = _calc_passing_times(sel_trip, dep_m, arr_m, dir_stops)
                    st.dataframe(preview, use_container_width=True, hide_index=True)

                    sc1, sc2 = st.columns(2)
                    with sc1:
                        if st.button(
                            "この便を保存",
                            key=_sk(f"save_one_trip_{route_id}_{direction}_{sel_trip}"),
                        ):
                            # Remove old entries for this trip_id then append
                            trip_stops_df = trip_stops_df[
                                trip_stops_df["trip_id"] != sel_trip
                            ]
                            trip_stops_df = pd.concat(
                                [trip_stops_df, preview], ignore_index=True
                            )
                            st.success(f"便 '{sel_trip}' の通過時刻を保存しました。")
                    with sc2:
                        if st.button(
                            "全便を一括計算・保存",
                            key=_sk(f"save_all_trips_{route_id}_{direction}"),
                        ):
                            for _, trow in edited.iterrows():
                                tid = str(trow["trip_id"])
                                if not tid:
                                    continue
                                dm = _parse_time_to_min(str(trow["dep_time"]))
                                am = _parse_time_to_min(str(trow["arr_time"]))
                                if am < dm:
                                    am += 24 * 60
                                calc = _calc_passing_times(tid, dm, am, dir_stops)
                                trip_stops_df = trip_stops_df[
                                    trip_stops_df["trip_id"] != tid
                                ]
                                trip_stops_df = pd.concat(
                                    [trip_stops_df, calc], ignore_index=True
                                )
                            st.success(f"{len(edited)} 便分の通過時刻を保存しました。")
            else:
                st.info(
                    "便がありません。先にヘッドウェイ生成またはテーブルで便を追加してください。"
                )

    return edited, trip_stops_df


def _render_timetable_panel(
    timetable_df: pd.DataFrame,
    route_id: str,
    stops_df: pd.DataFrame,
    route_type: str = "bidirectional",
    trip_stops_df: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """時刻表パネルをレンダリングする。

    Returns
    -------
    (edited_timetable_for_route, updated_trip_stops_df)
    """
    if trip_stops_df is None:
        trip_stops_df = pd.DataFrame(columns=TRIP_STOPS_COLS)

    sub = (
        timetable_df[timetable_df["route_id"] == route_id].copy()
        if len(timetable_df) > 0
        else timetable_df.copy()
    )

    st.markdown(f"#### 時刻表 -- `{route_id}`")
    st.caption("行路 (便チェーン) は「営業所管理」タブで組み立てます。")

    route_stops = (
        stops_df[stops_df["route_id"] == route_id] if len(stops_df) > 0 else stops_df
    )

    if route_type == "circular":
        # 循環路線 — 単一方向セクション
        circular_sub = sub[sub["direction"].isin(["outbound", "circular"])].copy()
        edited_circ, trip_stops_df = _render_direction_timetable(
            circular_sub, "circular", route_id, route_stops, trip_stops_df
        )
        # direction を "circular" に統一
        edited_circ["direction"] = "circular"
        return edited_circ, trip_stops_df
    else:
        # 往復路線 — 往路 / 復路タブ
        ob_sub = sub[sub["direction"] == "outbound"].copy()
        ib_sub = sub[sub["direction"] == "inbound"].copy()

        tab_ob, tab_ib = st.tabs(["➡️ 往路 (outbound)", "⬅️ 復路 (inbound)"])

        with tab_ob:
            edited_ob, trip_stops_df = _render_direction_timetable(
                ob_sub, "outbound", route_id, route_stops, trip_stops_df
            )
        with tab_ib:
            edited_ib, trip_stops_df = _render_direction_timetable(
                ib_sub, "inbound", route_id, route_stops, trip_stops_df
            )

        combined = pd.concat([edited_ob, edited_ib], ignore_index=True)
        return combined, trip_stops_df


# ---------------------------------------------------------------------------
# メインエントリー
# ---------------------------------------------------------------------------


def render_route_profile_editor(data_dir: str = "data") -> None:
    st.markdown(
        """
    <div style="background:linear-gradient(135deg, #1a6fbf22, #00a99d22);
                border-radius:12px; padding:16px 20px; margin-bottom:16px;">
        <h3 style="margin:0;">🚌 路線プロフィール管理</h3>
        <p style="margin:4px 0 0; color:#666; font-size:0.9em;">
            地図から路線を選択して編集。停留所・時刻表を管理します。
        </p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    data = _load_data(data_dir)
    routes_df = data["routes"].copy()
    stops_df = data["stops"].copy()
    timetable_df = data["timetable"].copy()
    garages_df = data["garages"]
    trip_stops_df = data["trip_stops"].copy()

    # 充電サイトCSVを読み込む（存在しない場合はNone）
    charger_sites_df: "pd.DataFrame | None" = None
    _charger_path = Path(data_dir) / "infra" / "charger_sites.csv"
    if _charger_path.exists():
        try:
            charger_sites_df = pd.read_csv(_charger_path)
        except Exception:
            charger_sites_df = None

    garage_ids = (
        garages_df["depot_id"].dropna().tolist()
        if "depot_id" in garages_df.columns
        else []
    )

    route_ids = routes_df["route_id"].dropna().tolist()
    route_ids = [r for r in route_ids if r]

    # ---- セッション: 選択中の路線 ----
    sel_key = _sk("selected_route")
    if sel_key not in st.session_state:
        st.session_state[sel_key] = route_ids[0] if route_ids else None

    # ---- 2カラムレイアウト: 左＝路線リスト / 右＝概観マップ ----
    left_col, right_col = st.columns([1, 3], gap="medium")

    with left_col:
        st.markdown("#### 路線一覧")

        # 路線ボタン（色付き）
        for idx, rid in enumerate(route_ids):
            row = routes_df[routes_df["route_id"] == rid]
            rname = row.iloc[0]["route_name"] if len(row) > 0 else rid
            color = _route_color(idx)
            is_sel = st.session_state[sel_key] == rid
            border = f"3px solid {color}" if is_sel else f"1px solid {color}44"
            bg = f"{color}22" if is_sel else "transparent"
            # colored badge + button
            btn_label = f"● {rname}" if is_sel else f"○ {rname}"
            if st.button(
                btn_label,
                key=_sk(f"route_btn_{rid}"),
                use_container_width=True,
                type="primary" if is_sel else "secondary",
            ):
                st.session_state[sel_key] = rid
                st.rerun()

        st.markdown("---")
        # 新規路線追加（折りたたみ）
        with st.expander("＋ 路線を追加", expanded=False):
            routes_df = _render_add_route_form(routes_df, garage_ids)
            route_ids = routes_df["route_id"].dropna().tolist()
            route_ids = [r for r in route_ids if r]

    with right_col:
        st.markdown("#### 概観マップ（クリックで路線を選択）")
        overview_m = _build_overview_map(
            routes_df, stops_df, garages_df, st.session_state[sel_key]
        )
        overview_result = st_folium(
            overview_m,
            key=_sk("overview_map"),
            height=320,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip"],
        )
        # クリックで路線/営業所を選択
        tooltip_val = (
            overview_result.get("last_object_clicked_tooltip")
            if overview_result
            else None
        )
        if tooltip_val:
            if str(tooltip_val).startswith("__route__"):
                clicked_rid = str(tooltip_val)[len("__route__") :]
                if (
                    clicked_rid in route_ids
                    and clicked_rid != st.session_state[sel_key]
                ):
                    st.session_state[sel_key] = clicked_rid
                    st.rerun()
            elif str(tooltip_val).startswith("__garage__"):
                gid = str(tooltip_val)[len("__garage__") :]
                gname_s = garages_df.loc[garages_df["depot_id"] == gid, "depot_name"]
                gname = gname_s.iloc[0] if len(gname_s) > 0 else gid
                st.info(f"営業所: **{gname}** (ID: {gid})")

    if not route_ids:
        st.info(
            "路線が登録されていません。左の「＋ 路線を追加」から路線を追加してください。"
        )
        return

    # selected_route を確定（ボタン選択 or デフォルト）
    selected_route = st.session_state[sel_key]
    if selected_route not in route_ids:
        selected_route = route_ids[0]
        st.session_state[sel_key] = selected_route

    # ---- 選択路線のヘッダー情報 + 属性編集 ----
    st.markdown("---")
    ri = routes_df[routes_df["route_id"] == selected_route]
    if len(ri) > 0:
        r = ri.iloc[0]
        garage_label = r.get("garage_id", "")
        if garage_label and garage_label in garage_ids:
            gname = garages_df.loc[garages_df["depot_id"] == garage_label, "depot_name"]
            if len(gname) > 0:
                garage_label = f"{garage_label} ({gname.iloc[0]})"
        idx_of_sel = (
            route_ids.index(selected_route) if selected_route in route_ids else 0
        )
        badge_color = _route_color(idx_of_sel)
        st.markdown(
            f'<span style="display:inline-block;width:14px;height:14px;'
            f"border-radius:50%;background:{badge_color};margin-right:8px;"
            f'vertical-align:middle;"></span>'
            f"**編集中: {r.get('route_name', selected_route)}**"
            f"　|　事業者: {r.get('operator', '—')}"
            f"　|　営業所: {garage_label or '未設定'}",
            unsafe_allow_html=True,
        )

    # 路線属性の編集（折りたたみ）
    with st.expander("✏️ 路線属性を編集", expanded=False):
        ri_idx = routes_df[routes_df["route_id"] == selected_route].index
        if len(ri_idx) > 0:
            i0 = ri_idx[0]
            with st.form(
                key=_sk(f"route_attr_form_{selected_route}"), clear_on_submit=False
            ):
                ac = st.columns([2, 2, 2, 1, 1])
                with ac[0]:
                    new_name = st.text_input(
                        "路線名",
                        value=str(routes_df.at[i0, "route_name"] or ""),
                        key=_sk(f"attr_name_{selected_route}"),
                    )
                with ac[1]:
                    new_op = st.text_input(
                        "事業者",
                        value=str(routes_df.at[i0, "operator"] or ""),
                        key=_sk(f"attr_op_{selected_route}"),
                    )
                with ac[2]:
                    new_garage = st.selectbox(
                        "営業所",
                        options=[""] + garage_ids,
                        index=(
                            ([""] + garage_ids).index(
                                str(routes_df.at[i0, "garage_id"] or "")
                            )
                            if str(routes_df.at[i0, "garage_id"] or "")
                            in ([""] + garage_ids)
                            else 0
                        ),
                        key=_sk(f"attr_garage_{selected_route}"),
                    )
                with ac[3]:
                    _rt_options = ["bidirectional", "circular"]
                    _rt_current = str(routes_df.at[i0, "route_type"] or "bidirectional")
                    _rt_idx = (
                        _rt_options.index(_rt_current)
                        if _rt_current in _rt_options
                        else 0
                    )
                    new_route_type = st.selectbox(
                        "タイプ",
                        options=_rt_options,
                        index=_rt_idx,
                        key=_sk(f"attr_rtype_{selected_route}"),
                        help="bidirectional: 往復 / circular: 循環",
                    )
                with ac[4]:
                    new_city = st.text_input(
                        "市区町村",
                        value=str(routes_df.at[i0, "city"] or ""),
                        key=_sk(f"attr_city_{selected_route}"),
                    )
                attr_save = st.form_submit_button("属性を更新")
                if attr_save:
                    routes_df.at[i0, "route_name"] = new_name
                    routes_df.at[i0, "operator"] = new_op
                    routes_df.at[i0, "garage_id"] = new_garage
                    routes_df.at[i0, "route_type"] = new_route_type
                    routes_df.at[i0, "city"] = new_city
                    st.success(
                        "路線属性を更新しました。「💾 路線データを保存」で確定してください。"
                    )

    # ---- 編集モード ----
    edit_mode = st.radio(
        "入力モード",
        ["🗺️ 地図から入力", "📝 テーブル編集"],
        horizontal=True,
        key=_sk("edit_mode"),
    )

    # ---- サブタブ ----
    sub_tab_stops, sub_tab_tt = st.tabs(
        [
            f"🚏 停留所 ({selected_route})",
            f"🕐 時刻表 ({selected_route})",
        ]
    )

    edited_stops = None
    edited_tt = None

    with sub_tab_stops:
        if "地図" in edit_mode:
            edited_stops = _render_map_editor(
                stops_df, selected_route, routes_df, charger_sites_df=charger_sites_df
            )
        else:
            edited_stops = _render_table_editor(stops_df, selected_route)

    with sub_tab_tt:
        current_stops = edited_stops if edited_stops is not None else stops_df
        # Extract route_type for selected route
        _ri = routes_df[routes_df["route_id"] == selected_route]
        _route_type = (
            str(_ri.iloc[0].get("route_type", "bidirectional") or "bidirectional")
            if len(_ri) > 0
            else "bidirectional"
        )
        edited_tt, trip_stops_df = _render_timetable_panel(
            timetable_df,
            selected_route,
            current_stops,
            route_type=_route_type,
            trip_stops_df=trip_stops_df,
        )

    # ---- 保存 ----
    st.markdown("---")
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        save = st.button("💾 路線データを保存", type="primary", key=_sk("save_btn"))
    with c2:
        auto_seg = st.checkbox(
            "🔧 セグメント自動生成",
            value=True,
            key=_sk("auto_seg_chk"),
            help="停留所リストから segments.csv を自動生成して一緒に保存します（25 km/h 基準）",
        )
    with c3:
        if save:
            # 停留所マージ
            if edited_stops is not None:
                other = stops_df[stops_df["route_id"] != selected_route]
                merged_stops = pd.concat([other, edited_stops], ignore_index=True)
            else:
                merged_stops = stops_df

            # 時刻表マージ
            if edited_tt is not None:
                other_tt = timetable_df[timetable_df["route_id"] != selected_route]
                merged_tt = pd.concat([other_tt, edited_tt], ignore_index=True)
            else:
                merged_tt = timetable_df

            # routes_df の num_stops / total_distance_km を自動更新
            for i, row in routes_df.iterrows():
                rid = row["route_id"]
                rsub = merged_stops[
                    (merged_stops["route_id"] == rid)
                    & (merged_stops["direction"] == "outbound")
                ]
                routes_df.at[i, "num_stops"] = len(rsub)
                routes_df.at[i, "total_distance_km"] = round(
                    float(rsub["distance_from_prev_km"].sum()), 2
                )

            # セグメント自動生成
            segments_to_save = None
            if auto_seg:
                route_stops = merged_stops[merged_stops["route_id"] == selected_route]
                if len(route_stops) >= 2:
                    segments_to_save = _generate_segments(route_stops, selected_route)

            saved = _save_data(
                data_dir,
                routes_df,
                merged_stops,
                merged_tt,
                segments_to_save,
                trip_stops_df=trip_stops_df,
            )
            st.success(f"保存しました: {', '.join(saved)}")

            # セッションクリア (地図用)
            for k in list(st.session_state.keys()):
                if k.startswith(_PREFIX) and ("map_stops" in k or "click_" in k):
                    del st.session_state[k]
            st.rerun()
