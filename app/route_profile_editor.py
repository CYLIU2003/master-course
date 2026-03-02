"""
app/route_profile_editor.py — 路線プロフィール管理エディタ

機能:
  1. 複数路線を横断的に管理（routes.csv + 路線ごとのタブ切替）
  2. 各路線の停留所・セグメントを編集
  3. 時刻表（timetable.csv）の作成・編集（便単位: dep_time / arr_time）
  4. folium 地図からバス停を配置・追加（地図入力モード）
  5. CSV 保存

設計方針:
  - 行路は営業所側（depot_profile_editor.py）に委ねる
  - 路線プロフィールは「停留所リスト」と「時刻表（発着時刻の一覧）」のみ管理
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


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _sk(name: str) -> str:
    return f"{_PREFIX}{name}"


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
                "on_route",
                "overnight_charging",
            ):
                df[c] = False
            elif c in ("distance_from_prev_km", "lat", "lon", "total_distance_km"):
                df[c] = 0.0
            elif c in ("sequence", "num_stops", "travel_time_min"):
                df[c] = 0
            else:
                df[c] = ""
    return df


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8")
    return None


def _compute_dist_from_prev(df: pd.DataFrame) -> pd.DataFrame:
    """lat/lon から distance_from_prev_km を計算（0 or NaN の行のみ上書き）。"""
    df = df.copy()
    for i in range(len(df)):
        if i == 0:
            df.loc[df.index[i], "distance_from_prev_km"] = 0.0
            continue
        cur = df.loc[df.index[i], "distance_from_prev_km"]
        if pd.isna(cur) or float(cur) == 0.0:
            la1 = df.loc[df.index[i - 1], "lat"]
            lo1 = df.loc[df.index[i - 1], "lon"]
            la2 = df.loc[df.index[i], "lat"]
            lo2 = df.loc[df.index[i], "lon"]
            if not any(pd.isna(v) for v in [la1, lo1, la2, lo2]):
                df.loc[df.index[i], "distance_from_prev_km"] = round(
                    _haversine_km(float(la1), float(lo1), float(la2), float(lo2)), 3
                )
    return df


def _parse_time_to_min(t: str) -> int:
    """HH:MM -> 分 (深夜跨ぎ対応)"""
    m = re.match(r"(\d+):(\d+)", str(t))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------


def _load_data(data_dir: str) -> dict:
    base = Path(data_dir)
    route_dir = base / "route_master"
    ops_dir = base / "operations"

    routes_df = _load_csv(route_dir / "routes.csv")
    stops_df = _load_csv(route_dir / "stops.csv")
    timetable_df = _load_csv(route_dir / "timetable.csv")

    if routes_df is None:
        routes_df = pd.DataFrame(columns=ROUTES_COLS)
    routes_df = _ensure_cols(routes_df, ROUTES_COLS)

    if stops_df is None:
        stops_df = pd.DataFrame(columns=STOPS_COLS)
    stops_df = _ensure_cols(stops_df, STOPS_COLS)

    if timetable_df is None:
        timetable_df = pd.DataFrame(columns=TIMETABLE_COLS)
    timetable_df = _ensure_cols(timetable_df, TIMETABLE_COLS)

    return {
        "routes": routes_df,
        "stops": stops_df,
        "timetable": timetable_df,
        "route_dir": route_dir,
    }


def _save_data(
    data_dir: str,
    routes_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    timetable_df: pd.DataFrame,
) -> list[str]:
    base = Path(data_dir)
    route_dir = base / "route_master"
    route_dir.mkdir(parents=True, exist_ok=True)

    routes_df.to_csv(route_dir / "routes.csv", index=False, encoding="utf-8")
    stops_df.to_csv(route_dir / "stops.csv", index=False, encoding="utf-8")
    timetable_df.to_csv(route_dir / "timetable.csv", index=False, encoding="utf-8")
    return ["routes.csv", "stops.csv", "timetable.csv"]


# ---------------------------------------------------------------------------
# 路線一覧パネル
# ---------------------------------------------------------------------------


def _render_routes_panel(routes_df: pd.DataFrame) -> pd.DataFrame:
    st.markdown("### 🛤️ 路線一覧")
    st.markdown(
        '<div style="background:#f0f7ff;border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.83em;">'
        "<b>route_id</b>=路線の一意ID &nbsp;│&nbsp; "
        "<b>route_name</b>=路線の表示名 &nbsp;│&nbsp; "
        "<b>operator</b>=運行事業者 &nbsp;│&nbsp; "
        "<b>total_distance_km</b>=総距離[km]"
        "</div>",
        unsafe_allow_html=True,
    )

    edited = st.data_editor(
        routes_df,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk("routes_editor"),
        column_config={
            "route_id": st.column_config.TextColumn("路線 ID", help="例: route_101"),
            "route_name": st.column_config.TextColumn(
                "路線名", help="例: 中央幹線101号"
            ),
            "operator": st.column_config.TextColumn("事業者"),
            "city": st.column_config.TextColumn("市区町村"),
            "total_distance_km": st.column_config.NumberColumn(
                "総距離 [km]",
                format="%.1f",
                min_value=0.0,
            ),
            "num_stops": st.column_config.NumberColumn("停留所数", min_value=0),
            "description": st.column_config.TextColumn("説明"),
        },
    )

    # 新規路線クイック追加
    st.markdown("#### ➕ 路線をすばやく追加")
    with st.form(key=_sk("add_route_form"), clear_on_submit=True):
        rc = st.columns([1, 2, 2, 1])
        with rc[0]:
            r_id = st.text_input("路線 ID", placeholder="route_102")
        with rc[1]:
            r_name = st.text_input("路線名", placeholder="東西幹線102号")
        with rc[2]:
            r_op = st.text_input("事業者", placeholder="市交通局")
        with rc[3]:
            r_add = st.form_submit_button("追加")
        if r_add and r_id:
            new_row = pd.DataFrame(
                [
                    {
                        "route_id": r_id,
                        "route_name": r_name,
                        "operator": r_op,
                        "city": "",
                        "total_distance_km": 0.0,
                        "num_stops": 0,
                        "description": "",
                    }
                ]
            )
            edited = pd.concat([edited, new_row], ignore_index=True)
            st.success(f"路線 '{r_id}' を追加しました。")
    return edited


# ---------------------------------------------------------------------------
# 停留所編集パネル（単路線）
# ---------------------------------------------------------------------------


def _render_stops_panel(stops_df: pd.DataFrame, route_id: str) -> pd.DataFrame:
    sub = (
        stops_df[stops_df["route_id"] == route_id].copy()
        if len(stops_df) > 0
        else stops_df.copy()
    )

    st.markdown(f"### 🚏 停留所一覧 — `{route_id}`")
    st.markdown(
        '<div style="background:#f0f7ff;border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.83em;">'
        "<b>sequence</b>=並び順 │ <b>direction</b>=outbound(往路)/inbound(復路) │ "
        "<b>distance_from_prev_km</b>=前停距離[km] │ <b>is_depot</b>=車庫兼用 │ <b>is_terminal</b>=起終点"
        "</div>",
        unsafe_allow_html=True,
    )

    display_cols = [
        c
        for c in [
            "sequence",
            "stop_id",
            "stop_name",
            "direction",
            "distance_from_prev_km",
            "lat",
            "lon",
            "is_depot",
            "is_revenue_stop",
            "is_terminal",
        ]
        if c in sub.columns
    ]

    edited = st.data_editor(
        sub[display_cols].sort_values(["direction", "sequence"])
        if len(sub) > 0
        else sub,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk(f"stops_{route_id}"),
        column_config={
            "sequence": st.column_config.NumberColumn("順序", min_value=1, step=1),
            "stop_id": st.column_config.TextColumn("停留所 ID"),
            "stop_name": st.column_config.TextColumn("停留所名"),
            "direction": st.column_config.SelectboxColumn(
                "方向",
                options=["outbound", "inbound"],
                default="outbound",
            ),
            "distance_from_prev_km": st.column_config.NumberColumn(
                "前停距離 [km]",
                min_value=0.0,
                step=0.1,
                format="%.3f",
            ),
            "lat": st.column_config.NumberColumn("緯度", format="%.6f"),
            "lon": st.column_config.NumberColumn("経度", format="%.6f"),
            "is_depot": st.column_config.CheckboxColumn("車庫", default=False),
            "is_revenue_stop": st.column_config.CheckboxColumn(
                "営業停車", default=True
            ),
            "is_terminal": st.column_config.CheckboxColumn("ターミナル", default=False),
        },
    )

    # 非表示列を補完
    for c in sub.columns:
        if c not in edited.columns:
            edited[c] = sub[c].values[: len(edited)] if len(sub) >= len(edited) else ""
    if "route_id" not in edited.columns or (edited["route_id"] == "").all():
        edited["route_id"] = route_id

    # 停留所クイック追加
    st.markdown("#### ➕ 停留所をすばやく追加")
    with st.form(key=_sk(f"add_stop_{route_id}"), clear_on_submit=True):
        sc = st.columns([1, 2, 1, 1, 1])
        with sc[0]:
            s_seq = st.number_input("順序", min_value=1, value=len(edited) + 1)
        with sc[1]:
            s_name = st.text_input("停留所名")
        with sc[2]:
            s_dir = st.selectbox("方向", ["outbound", "inbound"])
        with sc[3]:
            s_dist = st.number_input("距離 [km]", min_value=0.0, value=1.0, step=0.1)
        with sc[4]:
            s_add = st.form_submit_button("追加")
        if s_add and s_name:
            new_stop = pd.DataFrame(
                [
                    {
                        "stop_id": f"stop_{s_name.replace(' ', '_')}",
                        "stop_name": s_name,
                        "route_id": route_id,
                        "direction": s_dir,
                        "sequence": s_seq,
                        "lat": 0.0,
                        "lon": 0.0,
                        "is_terminal": False,
                        "terminal_id": "",
                        "is_depot": False,
                        "is_revenue_stop": True,
                        "distance_from_prev_km": s_dist,
                    }
                ]
            )
            edited = pd.concat([edited, new_stop], ignore_index=True)
            st.success(f"停留所 '{s_name}' を追加しました。")

    return edited


# ---------------------------------------------------------------------------
# 時刻表編集パネル（単路線）
# ---------------------------------------------------------------------------


def _render_timetable_panel(
    timetable_df: pd.DataFrame, route_id: str, stops_df: pd.DataFrame
) -> pd.DataFrame:
    sub = (
        timetable_df[timetable_df["route_id"] == route_id].copy()
        if len(timetable_df) > 0
        else timetable_df.copy()
    )

    st.markdown(f"### 🕐 時刻表 — `{route_id}`")
    st.markdown(
        '<div style="background:#fff8e1;border-radius:8px;padding:8px 14px;margin-bottom:8px;font-size:0.83em;">'
        "時刻表は「便（trip）」単位で管理します。<br>"
        "<b>trip_id</b>=便ID(一意) │ <b>dep_time</b>=発車時刻(HH:MM) │ <b>arr_time</b>=到着時刻 │ "
        "<b>from_stop_id</b>=出発停留所 │ <b>to_stop_id</b>=終点停留所 │ <b>service_type</b>=weekday/holiday<br>"
        "行路(複数便の組合せ)は「営業所管理」タブで設定します。"
        "</div>",
        unsafe_allow_html=True,
    )

    # 停留所IDリスト (セレクトボックス用)
    route_stops = (
        stops_df[stops_df["route_id"] == route_id] if len(stops_df) > 0 else stops_df
    )
    stop_ids = route_stops["stop_id"].tolist() if len(route_stops) > 0 else []

    display_cols = [c for c in TIMETABLE_COLS if c in sub.columns]
    edited = st.data_editor(
        sub[display_cols].sort_values(["direction", "dep_time"])
        if len(sub) > 0
        else sub,
        num_rows="dynamic",
        use_container_width=True,
        key=_sk(f"timetable_{route_id}"),
        column_config={
            "trip_id": st.column_config.TextColumn(
                "便 ID", help="例: trip_101_ob_0600"
            ),
            "route_id": st.column_config.TextColumn("路線 ID"),
            "direction": st.column_config.SelectboxColumn(
                "方向",
                options=["outbound", "inbound"],
                default="outbound",
            ),
            "service_type": st.column_config.SelectboxColumn(
                "運行日区分",
                options=["weekday", "holiday", "all"],
                default="weekday",
            ),
            "dep_time": st.column_config.TextColumn(
                "発車時刻",
                help="HH:MM 形式（例: 06:00）",
            ),
            "arr_time": st.column_config.TextColumn(
                "到着時刻",
                help="HH:MM 形式（例: 06:35）",
            ),
            "from_stop_id": st.column_config.SelectboxColumn(
                "出発停留所",
                options=stop_ids if stop_ids else [""],
            )
            if stop_ids
            else st.column_config.TextColumn("出発停留所"),
            "to_stop_id": st.column_config.SelectboxColumn(
                "終点停留所",
                options=stop_ids if stop_ids else [""],
            )
            if stop_ids
            else st.column_config.TextColumn("終点停留所"),
            "travel_time_min": st.column_config.NumberColumn(
                "所要時間 [分]",
                min_value=0,
                step=1,
            ),
            "notes": st.column_config.TextColumn("備考"),
        },
    )
    if "route_id" not in edited.columns or (edited["route_id"] == "").all():
        edited["route_id"] = route_id

    # 便クイック追加
    st.markdown("#### ➕ 便をすばやく追加")
    with st.form(key=_sk(f"add_trip_{route_id}"), clear_on_submit=True):
        tc = st.columns([2, 1, 1, 1, 1, 1])
        with tc[0]:
            t_id = st.text_input("便 ID", placeholder="trip_101_ob_0600")
        with tc[1]:
            t_dir = st.selectbox("方向", ["outbound", "inbound"])
        with tc[2]:
            t_dep = st.text_input("発車", value="06:00")
        with tc[3]:
            t_arr = st.text_input("到着", value="06:35")
        with tc[4]:
            t_svc = st.selectbox("区分", ["weekday", "holiday", "all"])
        with tc[5]:
            t_add = st.form_submit_button("追加")

        if t_add and t_id and t_dep and t_arr:
            dep_min = _parse_time_to_min(t_dep)
            arr_min = _parse_time_to_min(t_arr)
            # 深夜跨ぎ対応
            if arr_min < dep_min:
                arr_min += 24 * 60
            travel_min = arr_min - dep_min

            from_stop = stop_ids[0] if stop_ids else ""
            to_stop = stop_ids[-1] if len(stop_ids) > 1 else from_stop
            if t_dir == "inbound" and stop_ids:
                from_stop, to_stop = to_stop, from_stop

            new_trip = pd.DataFrame(
                [
                    {
                        "trip_id": t_id,
                        "route_id": route_id,
                        "direction": t_dir,
                        "service_type": t_svc,
                        "dep_time": t_dep,
                        "arr_time": t_arr,
                        "from_stop_id": from_stop,
                        "to_stop_id": to_stop,
                        "travel_time_min": travel_min,
                        "notes": "",
                    }
                ]
            )
            edited = pd.concat([edited, new_trip], ignore_index=True)
            st.success(f"便 '{t_id}' を追加しました ({t_dep} → {t_arr})")

    # 時刻表サマリー
    if len(sub) > 0:
        with st.expander("📊 便数サマリー", expanded=False):
            summary_rows = []
            for direction in sub["direction"].unique():
                for svc in sub["service_type"].unique():
                    cnt = len(
                        sub[
                            (sub["direction"] == direction)
                            & (sub["service_type"] == svc)
                        ]
                    )
                    if cnt > 0:
                        sub_s = sub[
                            (sub["direction"] == direction)
                            & (sub["service_type"] == svc)
                        ]
                        dep_min = sub_s["dep_time"].apply(_parse_time_to_min).min()
                        arr_max = sub_s["arr_time"].apply(_parse_time_to_min).max()
                        summary_rows.append(
                            {
                                "方向": direction,
                                "運行区分": svc,
                                "便数": cnt,
                                "始発": sub_s["dep_time"].iloc[
                                    sub_s["dep_time"].apply(_parse_time_to_min).argmin()
                                ],
                                "終発": sub_s["dep_time"].iloc[
                                    sub_s["dep_time"].apply(_parse_time_to_min).argmax()
                                ],
                            }
                        )
            if summary_rows:
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    return edited


# ---------------------------------------------------------------------------
# 地図入力モード
# ---------------------------------------------------------------------------


def _render_map_input(stops_df: pd.DataFrame, route_id: str) -> pd.DataFrame:
    """folium 地図上でクリックしてバス停を追加するパネル。"""
    if not FOLIUM_AVAILABLE:
        st.error(
            "地図入力には **folium** と **streamlit-folium** が必要です。\n\n"
            "```bash\npip install folium streamlit-folium\n```"
        )
        return stops_df

    sub = (
        stops_df[stops_df["route_id"] == route_id].copy()
        if len(stops_df) > 0
        else stops_df.copy()
    )

    # セッション初期化
    click_key = _sk(f"click_{route_id}")
    if click_key not in st.session_state:
        st.session_state[click_key] = {"lat": None, "lng": None}

    # 地図中心
    center_lat, center_lon = _DEFAULT_CENTER
    if len(sub) > 0:
        valid = sub.dropna(subset=["lat", "lon"])
        valid = valid[(valid["lat"] != 0) & (valid["lon"] != 0)]
        if len(valid) > 0:
            center_lat = float(valid["lat"].mean())
            center_lon = float(valid["lon"].mean())

    # 地図構築
    m = folium.Map(
        location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron"
    )

    # 既存バス停をプロット
    fg_stops = folium.FeatureGroup(name="🚏 バス停")
    for _, row in sub.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon) or float(lat) == 0 or float(lon) == 0:
            continue
        is_dep = str(row.get("is_depot", False)).lower() in ("true", "1")
        folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=7 if is_dep else 5,
            color="#e74c3c" if is_dep else "#3388ff",
            fill=True,
            fill_opacity=0.85,
            popup=folium.Popup(
                f"<b>{row.get('stop_name', '')}</b><br>"
                f"ID: {row.get('stop_id', '')}<br>"
                f"seq: {row.get('sequence', '')}<br>"
                f"方向: {row.get('direction', '')}<br>"
                f"車庫: {'✅' if is_dep else '—'}",
                max_width=220,
            ),
            tooltip=f"{row.get('sequence', '')}. {row.get('stop_name', '')}",
        ).add_to(fg_stops)
    fg_stops.add_to(m)

    # 路線ライン
    for direction in sub["direction"].unique() if len(sub) > 0 else []:
        dir_sub = sub[sub["direction"] == direction].sort_values("sequence")
        coords = []
        for _, row in dir_sub.iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            if (
                not pd.isna(lat)
                and not pd.isna(lon)
                and float(lat) != 0
                and float(lon) != 0
            ):
                coords.append([float(lat), float(lon)])
        if len(coords) >= 2:
            folium.PolyLine(
                locations=coords,
                color="#3388ff" if direction == "outbound" else "#e07b39",
                weight=3,
                opacity=0.7,
                tooltip=f"{route_id} ({direction})",
            ).add_to(m)

    folium.LayerControl().add_to(m)

    st.markdown("**地図をクリック → 座標を取得 → 下フォームで停留所を追加**")
    map_result = st_folium(
        m,
        width=900,
        height=480,
        key=_sk(f"map_{route_id}"),
        returned_objects=["last_clicked"],
    )

    # クリック座標保存
    if map_result and isinstance(map_result, dict):
        lc = map_result.get("last_clicked")
        if lc and isinstance(lc, dict):
            clat = lc.get("lat")
            clng = lc.get("lng")
            if clat is not None and clng is not None:
                st.session_state[click_key] = {"lat": clat, "lng": clng}

    clat = st.session_state[click_key].get("lat")
    clng = st.session_state[click_key].get("lng")

    if clat is not None and clng is not None:
        st.info(f"📍 選択座標: **{clat:.6f}, {clng:.6f}**")
    else:
        st.caption("地図をクリックすると座標が表示されます。")

    # 追加フォーム
    st.markdown("---")
    st.markdown("### ➕ クリック位置に停留所を追加")
    with st.form(key=_sk(f"map_add_{route_id}"), clear_on_submit=True):
        mc = st.columns([2, 1, 1, 1, 1, 1])
        with mc[0]:
            m_name = st.text_input("停留所名")
        with mc[1]:
            m_lat = st.number_input("緯度", value=clat if clat else 0.0, format="%.6f")
        with mc[2]:
            m_lng = st.number_input("経度", value=clng if clng else 0.0, format="%.6f")
        with mc[3]:
            m_dir = st.selectbox("方向", ["outbound", "inbound"])
        with mc[4]:
            m_depot = st.checkbox("車庫兼用")
        with mc[5]:
            m_add = st.form_submit_button("📌 追加", type="primary")

        if m_add and m_name and m_lat != 0.0 and m_lng != 0.0:
            dir_sub = sub[sub["direction"] == m_dir]
            next_seq = int(dir_sub["sequence"].max()) + 1 if len(dir_sub) > 0 else 1
            new_stop = pd.DataFrame(
                [
                    {
                        "stop_id": f"stop_{m_name.replace(' ', '_')}",
                        "stop_name": m_name,
                        "route_id": route_id,
                        "direction": m_dir,
                        "sequence": next_seq,
                        "lat": m_lat,
                        "lon": m_lng,
                        "is_terminal": False,
                        "terminal_id": "",
                        "is_depot": m_depot,
                        "is_revenue_stop": True,
                        "distance_from_prev_km": 0.0,
                    }
                ]
            )
            sub = pd.concat([sub, new_stop], ignore_index=True)
            sub = _compute_dist_from_prev(
                sub.sort_values(["direction", "sequence"]).reset_index(drop=True)
            )
            st.session_state[_sk(f"map_stops_{route_id}")] = sub
            st.success(f"停留所 '{m_name}' を追加しました ({m_lat:.4f}, {m_lng:.4f})")

    # session_state の更新を反映
    updated = st.session_state.get(_sk(f"map_stops_{route_id}"), sub)
    return updated


# ---------------------------------------------------------------------------
# メインエントリー
# ---------------------------------------------------------------------------


def render_route_profile_editor(data_dir: str = "data") -> None:
    """
    路線プロフィール管理エディタのメイン関数。

    - 路線一覧の管理
    - 各路線の停留所・時刻表の編集
    - 地図入力モード対応
    """
    st.markdown(
        """
    <div style="
        background: linear-gradient(135deg, #1a6fbf22, #00a99d22);
        border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
    ">
        <h3 style="margin:0;">🗺️ 路線プロフィール管理</h3>
        <p style="margin:4px 0 0; color:#666; font-size:0.9em;">
            複数路線の停留所・時刻表を管理します。行路の編成は「営業所管理」タブで行います。
        </p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    data = _load_data(data_dir)
    routes_df = data["routes"].copy()
    stops_df = data["stops"].copy()
    timetable_df = data["timetable"].copy()

    # ---- 路線一覧 ----
    with st.expander("🛤️ 路線一覧・追加", expanded=True):
        routes_df = _render_routes_panel(routes_df)

    route_ids = routes_df["route_id"].dropna().tolist()
    route_ids = [r for r in route_ids if r]

    if not route_ids:
        st.info(
            "路線が登録されていません。上の「路線一覧」から路線を追加してください。"
        )
        return

    # ---- 路線選択 ----
    st.markdown("---")
    selected_route = st.selectbox(
        "編集する路線を選択",
        route_ids,
        key=_sk("selected_route"),
    )

    route_info = routes_df[routes_df["route_id"] == selected_route]
    if len(route_info) > 0:
        rinfo = route_info.iloc[0]
        st.caption(
            f"**{rinfo.get('route_name', '')}** | "
            f"事業者: {rinfo.get('operator', '—')} | "
            f"総距離: {rinfo.get('total_distance_km', 0):.1f} km"
        )

    # ---- 編集モード ----
    edit_mode = st.radio(
        "入力モード",
        ["📝 テーブル編集", "🗺️ 地図から入力"],
        horizontal=True,
        key=_sk("edit_mode"),
    )

    # 路線ごとのタブ
    sub_tab_stops, sub_tab_timetable = st.tabs(
        [
            f"🚏 停留所 ({selected_route})",
            f"🕐 時刻表 ({selected_route})",
        ]
    )

    # 停留所の編集結果を保持
    edited_stops_for_route = None
    edited_timetable_for_route = None

    with sub_tab_stops:
        if "地図" in edit_mode:
            edited_stops_for_route = _render_map_input(stops_df, selected_route)
        else:
            edited_stops_for_route = _render_stops_panel(stops_df, selected_route)

    with sub_tab_timetable:
        edited_timetable_for_route = _render_timetable_panel(
            timetable_df, selected_route, stops_df
        )

    # ---- 保存ボタン ----
    st.markdown("---")
    col_save, col_info = st.columns([1, 3])
    with col_save:
        save_clicked = st.button(
            "💾 路線データを保存",
            type="primary",
            key=_sk("save_btn"),
        )
    with col_info:
        if save_clicked:
            # 停留所: 当該路線の編集結果を全体に反映
            if edited_stops_for_route is not None:
                other_stops = stops_df[stops_df["route_id"] != selected_route]
                merged_stops = pd.concat(
                    [other_stops, edited_stops_for_route], ignore_index=True
                )
            else:
                merged_stops = stops_df

            # 時刻表: 当該路線の編集結果を全体に反映
            if edited_timetable_for_route is not None:
                other_tt = timetable_df[timetable_df["route_id"] != selected_route]
                merged_tt = pd.concat(
                    [other_tt, edited_timetable_for_route], ignore_index=True
                )
            else:
                merged_tt = timetable_df

            saved = _save_data(data_dir, routes_df, merged_stops, merged_tt)
            st.success(f"保存しました: {', '.join(saved)}")
            # session state をクリアして再読込を促す
            for k in list(st.session_state.keys()):
                if k.startswith(_PREFIX):
                    if "map_stops" in k or "updated" in k:
                        del st.session_state[k]
