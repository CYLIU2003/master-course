"""
app/route_detail_editor.py — 路線詳細エディタ（単純編集 + 地図入力）

2 つの編集モード:
  1. 単純編集: テーブル/フォームで路線長、バス停の数・距離、車庫を編集
  2. 地図から入力: folium 地図上でクリックして配置

共通機能:
  - バス停の追加・削除・並び替え・距離設定
  - 車庫（デポ）は路線上 or 路線外どちらでも配置可能
  - 車庫が営業運転停留所かどうかを選択可能
  - セグメント自動生成
  - CSV 保存
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

try:
    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
_PREFIX = "_rde_"  # session_state プレフィックス
_DEFAULT_CENTER = (35.6895, 139.6917)
COLOR_STOP = "#3388ff"
COLOR_DEPOT_ON = "#e74c3c"   # 路線上デポ
COLOR_DEPOT_OFF = "#9b59b6"  # 路線外デポ
COLOR_CHARGER = "#27ae60"
COLOR_SEG = "#3388ff"
COLOR_STOP_MARKER = "#2980b9"

# バス停テーブルの必須列
STOPS_COLS = [
    "stop_id", "stop_name", "route_id", "direction", "sequence",
    "lat", "lon", "is_terminal", "terminal_id",
    "is_depot", "is_revenue_stop", "distance_from_prev_km",
]

DEPOTS_COLS = [
    "depot_id", "depot_name", "lat", "lon",
    "on_route", "nearest_stop_id", "is_revenue_stop",
    "parking_capacity", "overnight_charging",
    "grid_connection_kw", "notes",
]

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _sk(name: str) -> str:
    """session_state キーを生成。"""
    return f"{_PREFIX}{name}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2 点間のハーバーサイン距離 [km]。"""
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


def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """不足列をデフォルト値で追加する。"""
    for c in cols:
        if c not in df.columns:
            if c in ("is_depot", "is_revenue_stop", "is_terminal", "on_route", "overnight_charging"):
                df[c] = False
            elif c in ("distance_from_prev_km", "lat", "lon", "parking_capacity", "grid_connection_kw"):
                df[c] = 0.0
            elif c == "sequence":
                df[c] = 0
            else:
                df[c] = ""
    return df


def _load_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path, encoding="utf-8")
    return None


def _compute_distance_from_prev(stops_df: pd.DataFrame) -> pd.DataFrame:
    """lat/lon から distance_from_prev_km を計算（0 or NaN の行のみ上書き）。"""
    df = stops_df.copy()
    for i in range(len(df)):
        if i == 0:
            df.loc[df.index[i], "distance_from_prev_km"] = 0.0
            continue
        cur_val = df.loc[df.index[i], "distance_from_prev_km"]
        if pd.isna(cur_val) or cur_val == 0.0:
            lat1 = df.loc[df.index[i - 1], "lat"]
            lon1 = df.loc[df.index[i - 1], "lon"]
            lat2 = df.loc[df.index[i], "lat"]
            lon2 = df.loc[df.index[i], "lon"]
            if not any(pd.isna(v) for v in [lat1, lon1, lat2, lon2]):
                df.loc[df.index[i], "distance_from_prev_km"] = round(
                    _haversine_km(lat1, lon1, lat2, lon2), 3
                )
    return df


def _generate_segments(stops_df: pd.DataFrame, route_id: str = "route_101") -> pd.DataFrame:
    """停留所リストからセグメント DataFrame を自動生成する。"""
    rows = []
    for direction in stops_df["direction"].unique():
        sub = stops_df[stops_df["direction"] == direction].sort_values("sequence")
        ids = sub["stop_id"].tolist()
        for i in range(len(ids) - 1):
            from_row = sub.iloc[i]
            to_row = sub.iloc[i + 1]
            dist = to_row.get("distance_from_prev_km", 0.0)
            if pd.isna(dist) or dist == 0:
                la1, lo1 = from_row["lat"], from_row["lon"]
                la2, lo2 = to_row["lat"], to_row["lon"]
                if all(not pd.isna(v) for v in [la1, lo1, la2, lo2]):
                    dist = round(_haversine_km(la1, lo1, la2, lo2), 3)
            avg_speed = 25.0  # 仮定: 25 km/h
            runtime = round(dist / avg_speed * 60, 1) if dist > 0 else 0.0
            rows.append({
                "segment_id": f"seg_{direction[:3]}_{i + 1:02d}",
                "route_id": route_id,
                "direction": direction,
                "from_stop_id": ids[i],
                "to_stop_id": ids[i + 1],
                "distance_km": round(dist, 3),
                "runtime_min": runtime,
                "grade_avg_pct": 0.0,
                "signal_count": 0,
                "traffic_level": "medium",
                "congestion_index": 1.0,
                "speed_limit_kmh": 40,
                "road_type": "urban",
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# ロード / セーブ
# ---------------------------------------------------------------------------

def _load_all(data_dir: str) -> dict:
    base = Path(data_dir)
    route_dir = base / "route_master"
    infra_dir = base / "infra"

    route_df = _load_csv(route_dir / "routes.csv")
    stops_df = _load_csv(route_dir / "stops.csv")
    segments_df = _load_csv(route_dir / "segments.csv")
    depots_df = _load_csv(infra_dir / "depots.csv")
    charger_sites_df = _load_csv(infra_dir / "charger_sites.csv")
    terminals_df = _load_csv(route_dir / "terminals.csv")

    # 必須列を補完
    if stops_df is not None:
        stops_df = _ensure_columns(stops_df, STOPS_COLS)
        # distance_from_prev_km がなければ計算
        if stops_df["distance_from_prev_km"].isna().all() or (stops_df["distance_from_prev_km"] == 0).all():
            stops_df = _compute_distance_from_prev(stops_df)
    else:
        stops_df = pd.DataFrame(columns=STOPS_COLS)

    if depots_df is not None:
        depots_df = _ensure_columns(depots_df, DEPOTS_COLS)
    else:
        depots_df = pd.DataFrame(columns=DEPOTS_COLS)

    return {
        "route": route_df,
        "stops": stops_df,
        "segments": segments_df,
        "depots": depots_df,
        "charger_sites": charger_sites_df,
        "terminals": terminals_df,
    }


def _save_all(data_dir: str, stops_df: pd.DataFrame, depots_df: pd.DataFrame,
              segments_df: Optional[pd.DataFrame] = None,
              route_df: Optional[pd.DataFrame] = None) -> list[str]:
    """変更されたデータを CSV に保存する。"""
    base = Path(data_dir)
    route_dir = base / "route_master"
    infra_dir = base / "infra"
    route_dir.mkdir(parents=True, exist_ok=True)
    infra_dir.mkdir(parents=True, exist_ok=True)

    saved = []

    # Stops
    stops_df.to_csv(route_dir / "stops.csv", index=False, encoding="utf-8")
    saved.append("stops.csv")

    # Depots
    depots_df.to_csv(infra_dir / "depots.csv", index=False, encoding="utf-8")
    saved.append("depots.csv")

    # Segments (自動生成)
    if segments_df is not None and len(segments_df) > 0:
        segments_df.to_csv(route_dir / "segments.csv", index=False, encoding="utf-8")
        saved.append("segments.csv")

    # Routes
    if route_df is not None:
        route_df.to_csv(route_dir / "routes.csv", index=False, encoding="utf-8")
        saved.append("routes.csv")

    return saved


# ---------------------------------------------------------------------------
# 統計サマリー
# ---------------------------------------------------------------------------

def _render_stats(stops_df: pd.DataFrame, depots_df: pd.DataFrame) -> None:
    """路線の統計情報を表示する。"""
    if stops_df is None or len(stops_df) == 0:
        return

    for direction in stops_df["direction"].unique():
        sub = stops_df[stops_df["direction"] == direction].sort_values("sequence")
        total_dist = sub["distance_from_prev_km"].sum()
        n_stops = len(sub)
        n_depot_stops = sub["is_depot"].sum() if "is_depot" in sub.columns else 0

        st.markdown(f"**{direction}** 方向")
        cols = st.columns(5)
        with cols[0]:
            st.metric("バス停数", n_stops)
        with cols[1]:
            st.metric("総距離", f"{total_dist:.2f} km")
        with cols[2]:
            avg_spacing = total_dist / max(n_stops - 1, 1)
            st.metric("平均停間距離", f"{avg_spacing:.2f} km")
        with cols[3]:
            st.metric("路線上デポ数", int(n_depot_stops))
        with cols[4]:
            off_route = len(depots_df[depots_df.get("on_route", pd.Series(dtype=bool)) == False]) if "on_route" in depots_df.columns else 0
            st.metric("路線外デポ数", off_route)


# ---------------------------------------------------------------------------
# 単純編集モード
# ---------------------------------------------------------------------------

def _render_simple_editor(data: dict, data_dir: str) -> None:
    """テーブル/フォームベースの路線エディタ。"""
    stops_df = data["stops"].copy()
    depots_df = data["depots"].copy()
    route_df = data["route"]

    st.markdown("### 🛤️ 路線概要")
    st.markdown(
        '<div style="background:#f5f5dc; border-radius:8px; padding:8px 12px; margin-bottom:8px; font-size:0.82em; line-height:1.6;">'
        '<b>route_id</b>=路線の一意ID &nbsp;│&nbsp; '
        '<b>route_name</b>=路線の表示名 &nbsp;│&nbsp; '
        '<b>direction</b>=outbound(往路)/inbound(復路)'
        '</div>',
        unsafe_allow_html=True,
    )
    if route_df is not None and len(route_df) > 0:
        route_col_config = {
            "route_id": st.column_config.TextColumn(
                "路線 ID", help="路線の一意識別子（例: route_101）",
            ),
            "route_name": st.column_config.TextColumn(
                "路線名", help="路線の表示名",
            ),
            "direction": st.column_config.TextColumn(
                "方向", help="outbound=往路、inbound=復路",
            ),
        }
        edited_route = st.data_editor(
            route_df,
            width='stretch',
            num_rows="dynamic",
            key=_sk("simple_route"),
            column_config=route_col_config,
        )
    else:
        edited_route = route_df

    # === 統計 ===
    with st.expander("📊 路線統計", expanded=True):
        _render_stats(stops_df, depots_df)

    # === バス停編集 ===
    st.markdown("---")
    st.markdown("### 🚏 バス停一覧")
    st.markdown(
        '<div style="background:#f0f7ff; border-radius:8px; padding:10px 14px; margin-bottom:10px; font-size:0.85em; line-height:1.7;">'
        '<b>📖 列の説明</b><br>'
        '<b>順序</b> … 路線内でのバス停の並び順（1から連番） &nbsp;│&nbsp; '
        '<b>停留所 ID</b> … 一意の識別子（例: stop_A） &nbsp;│&nbsp; '
        '<b>停留所名</b> … 表示名（例: 中央公園前）<br>'
        '<b>方向</b> … outbound=往路 / inbound=復路 &nbsp;│&nbsp; '
        '<b>前停距離 [km]</b> … ひとつ前のバス停からの距離（最初は 0）<br>'
        '<b>緯度・経度</b> … バス停の位置（地図モードで自動入力可） &nbsp;│&nbsp; '
        '<b>車庫</b> … ✅ ならこの停留所が車庫を兼ねる<br>'
        '<b>営業停車</b> … ✅ なら旅客の乗降がある停留所（回送専用なら外す） &nbsp;│&nbsp; '
        '<b>ターミナル</b> … ✅ なら路線の起終点'
        '</div>',
        unsafe_allow_html=True,
    )

    # 表示用にカラムを選択・並び替え
    display_cols = [
        "sequence", "stop_id", "stop_name", "direction",
        "distance_from_prev_km", "lat", "lon",
        "is_depot", "is_revenue_stop", "is_terminal",
    ]
    # 存在するカラムのみ
    display_cols = [c for c in display_cols if c in stops_df.columns]

    column_config = {
        "sequence": st.column_config.NumberColumn(
            "順序", min_value=1, step=1,
            help="路線内でのバス停の並び順（1 から連番）",
        ),
        "stop_id": st.column_config.TextColumn(
            "停留所 ID",
            help="一意の識別子（例: stop_A）。CSV内のキーとして使用",
        ),
        "stop_name": st.column_config.TextColumn(
            "停留所名",
            help="バス停の表示名（例: 中央公園前）",
        ),
        "direction": st.column_config.SelectboxColumn(
            "方向", options=["outbound", "inbound"], default="outbound",
            help="outbound = 往路（デポ→終点）、inbound = 復路（終点→デポ）",
        ),
        "distance_from_prev_km": st.column_config.NumberColumn(
            "前停距離 [km]", min_value=0.0, step=0.1, format="%.3f",
            help="ひとつ前のバス停からの距離 [km]。最初のバス停は 0",
        ),
        "lat": st.column_config.NumberColumn(
            "緯度", format="%.6f",
            help="バス停の緯度（北緯）。地図モードではクリックで自動入力",
        ),
        "lon": st.column_config.NumberColumn(
            "経度", format="%.6f",
            help="バス停の経度（東経）。地図モードではクリックで自動入力",
        ),
        "is_depot": st.column_config.CheckboxColumn(
            "車庫", default=False,
            help="✅ = この停留所が車庫（デポ）を兼ねる。バスが出庫・入庫する地点",
        ),
        "is_revenue_stop": st.column_config.CheckboxColumn(
            "営業停車", default=True,
            help="✅ = 旅客の乗降がある停留所。回送専用なら外す",
        ),
        "is_terminal": st.column_config.CheckboxColumn(
            "ターミナル", default=False,
            help="✅ = 路線の起点または終点となるターミナル駅",
        ),
    }

    edited_stops = st.data_editor(
        stops_df[display_cols] if display_cols else stops_df,
        width='stretch',
        num_rows="dynamic",
        column_config=column_config,
        key=_sk("simple_stops"),
    )

    # 元の stops_df の非表示列を復元
    hidden_cols = [c for c in stops_df.columns if c not in display_cols]
    for c in hidden_cols:
        if c not in edited_stops.columns:
            edited_stops[c] = stops_df[c].values[:len(edited_stops)] if len(stops_df) >= len(edited_stops) else ""

    # === 新規バス停クイック追加 ===
    st.markdown("---")
    st.markdown("#### ➕ バス停をすばやく追加")
    with st.form(key=_sk("quick_add_stop"), clear_on_submit=True):
        qc = st.columns([1, 2, 1, 1, 1, 1, 1])
        with qc[0]:
            q_seq = st.number_input("順序", min_value=1, value=len(edited_stops) + 1, step=1)
        with qc[1]:
            q_name = st.text_input("停留所名")
        with qc[2]:
            q_dir = st.selectbox("方向", ["outbound", "inbound"])
        with qc[3]:
            q_dist = st.number_input("距離 [km]", min_value=0.0, value=1.0, step=0.1)
        with qc[4]:
            q_depot = st.checkbox("車庫")
        with qc[5]:
            q_rev = st.checkbox("営業停車", value=True)
        with qc[6]:
            add_btn = st.form_submit_button("追加")

        if add_btn and q_name:
            new_stop_id = f"stop_{q_name.replace(' ', '_')}"
            new_row = pd.DataFrame([{
                "stop_id": new_stop_id,
                "stop_name": q_name,
                "route_id": "route_101",
                "direction": q_dir,
                "sequence": q_seq,
                "lat": 0.0,
                "lon": 0.0,
                "is_terminal": False,
                "terminal_id": "",
                "is_depot": q_depot,
                "is_revenue_stop": q_rev,
                "distance_from_prev_km": q_dist,
            }])
            edited_stops = pd.concat([edited_stops, new_row], ignore_index=True)
            st.success(f"バス停 '{q_name}' を追加しました (seq={q_seq})")

    # === 車庫（デポ）編集 ===
    st.markdown("---")
    st.markdown("### 🅿️ 車庫（デポ）一覧")
    st.markdown(
        '<div style="background:#fff5f5; border-radius:8px; padding:10px 14px; margin-bottom:10px; font-size:0.85em; line-height:1.7;">'
        '<b>📖 列の説明</b><br>'
        '<b>車庫 ID</b> … 一意の識別子（例: depot_main） &nbsp;│&nbsp; '
        '<b>車庫名</b> … 表示名（例: メインデポ）<br>'
        '<b>緯度・経度</b> … 車庫の位置 &nbsp;│&nbsp; '
        '<b>路線上</b> … ✅ = 路線ルート上にある車庫。❌ = 路線外（回送が必要）<br>'
        '<b>最寄りバス停</b> … 路線外デポの場合、最も近いバス停 ID &nbsp;│&nbsp; '
        '<b>営業停車</b> … ✅ = 旅客の乗降もある（営業運転で停まる）<br>'
        '<b>駐車容量</b> … 同時に駐車できるバスの台数 &nbsp;│&nbsp; '
        '<b>夜間充電</b> … ✅ = 夜間にバスを充電する機能あり<br>'
        '<b>系統接続 [kW]</b> … 電力系統の最大接続容量 &nbsp;│&nbsp; '
        '<b>備考</b> … 自由記入'
        '</div>',
        unsafe_allow_html=True,
    )

    depot_column_config = {
        "depot_id": st.column_config.TextColumn(
            "車庫 ID",
            help="車庫の一意識別子（例: depot_main）。CSV内のキー",
        ),
        "depot_name": st.column_config.TextColumn(
            "車庫名",
            help="車庫の表示名（例: メインデポ）",
        ),
        "lat": st.column_config.NumberColumn(
            "緯度", format="%.6f",
            help="車庫の緯度（北緯）",
        ),
        "lon": st.column_config.NumberColumn(
            "経度", format="%.6f",
            help="車庫の経度（東経）",
        ),
        "on_route": st.column_config.CheckboxColumn(
            "路線上", default=True,
            help="✅ = 路線ルート上にある車庫。❌ = 路線外にあり、出入庫にデッドヘッド（回送）が必要",
        ),
        "nearest_stop_id": st.column_config.TextColumn(
            "最寄りバス停",
            help="路線外デポの場合、最も近い路線上のバス停 ID を指定",
        ),
        "is_revenue_stop": st.column_config.CheckboxColumn(
            "営業停車", default=False,
            help="✅ = 営業運転でも旅客の乗降がある停車地として扱う",
        ),
        "parking_capacity": st.column_config.NumberColumn(
            "駐車容量", min_value=0, step=1,
            help="同時に駐車できるバスの最大台数",
        ),
        "overnight_charging": st.column_config.CheckboxColumn(
            "夜間充電", default=True,
            help="✅ = この車庫で夜間にバスを充電できる",
        ),
        "grid_connection_kw": st.column_config.NumberColumn(
            "系統接続 [kW]", min_value=0.0, step=10.0,
            help="電力系統への最大接続容量 [kW]。充電器の合計出力上限",
        ),
        "notes": st.column_config.TextColumn(
            "備考",
            help="自由記入の補足メモ",
        ),
    }

    depot_display_cols = [c for c in DEPOTS_COLS if c in depots_df.columns]

    edited_depots = st.data_editor(
        depots_df[depot_display_cols] if depot_display_cols else depots_df,
        width='stretch',
        num_rows="dynamic",
        column_config=depot_column_config,
        key=_sk("simple_depots"),
    )

    # === 新規デポ追加 ===
    st.markdown("#### ➕ 車庫をすばやく追加")
    with st.form(key=_sk("quick_add_depot"), clear_on_submit=True):
        dc = st.columns([2, 1, 1, 1, 1, 1])
        with dc[0]:
            d_name = st.text_input("車庫名")
        with dc[1]:
            d_on = st.checkbox("路線上", value=True)
        with dc[2]:
            d_rev = st.checkbox("営業停車", value=False)
        with dc[3]:
            d_cap = st.number_input("駐車容量", min_value=1, value=10, step=1)
        with dc[4]:
            d_grid = st.number_input("系統 [kW]", min_value=0.0, value=150.0, step=10.0)
        with dc[5]:
            d_add = st.form_submit_button("追加")

        if d_add and d_name:
            d_id = f"depot_{d_name.replace(' ', '_')}"
            new_depot = pd.DataFrame([{
                "depot_id": d_id,
                "depot_name": d_name,
                "lat": 0.0,
                "lon": 0.0,
                "on_route": d_on,
                "nearest_stop_id": "",
                "is_revenue_stop": d_rev,
                "parking_capacity": d_cap,
                "overnight_charging": True,
                "grid_connection_kw": d_grid,
                "notes": "",
            }])
            edited_depots = pd.concat([edited_depots, new_depot], ignore_index=True)
            st.success(f"車庫 '{d_name}' を追加しました")

    # === セグメント自動生成プレビュー ===
    st.markdown("---")
    st.markdown("### 📏 セグメント（自動生成プレビュー）")
    st.caption("バス停リストからセグメントが自動生成されます。保存時に segments.csv に反映されます。")

    route_id = "route_101"
    if route_df is not None and len(route_df) > 0:
        route_id = route_df.iloc[0].get("route_id", "route_101")

    auto_segments = _generate_segments(edited_stops, route_id)
    if len(auto_segments) > 0:
        st.dataframe(auto_segments, width='stretch')
    else:
        st.info("バス停が 2 つ以上必要です。")

    # === 保存 ===
    st.markdown("---")
    col_save, col_info = st.columns([1, 3])
    with col_save:
        if st.button("💾 路線データを保存", type="primary", key=_sk("save_simple")):
            saved_files = _save_all(
                data_dir, edited_stops, edited_depots,
                segments_df=auto_segments,
                route_df=edited_route,
            )
            st.session_state[_sk("last_save")] = saved_files
    with col_info:
        if _sk("last_save") in st.session_state:
            st.success(f"保存しました: {', '.join(st.session_state[_sk('last_save')])}")


# ---------------------------------------------------------------------------
# 地図入力モード
# ---------------------------------------------------------------------------

def _render_map_editor(data: dict, data_dir: str) -> None:
    """folium 地図ベースの路線エディタ。"""
    if not FOLIUM_AVAILABLE:
        st.error(
            "このモードには **folium** と **streamlit-folium** が必要です。\n\n"
            "```bash\npip install folium streamlit-folium\n```"
        )
        return

    stops_df = data["stops"].copy()
    depots_df = data["depots"].copy()
    charger_sites_df = data.get("charger_sites")
    route_df = data["route"]

    # --- session state 初期化 ---
    if _sk("click_lat") not in st.session_state:
        st.session_state[_sk("click_lat")] = None
        st.session_state[_sk("click_lng")] = None

    # --- 統計 ---
    with st.expander("📊 路線統計", expanded=False):
        _render_stats(stops_df, depots_df)

    # --- 地図の中心を決定 ---
    center_lat, center_lon = _DEFAULT_CENTER
    all_lats, all_lons = [], []
    for df in [stops_df, depots_df]:
        if df is not None and len(df) > 0 and "lat" in df.columns and "lon" in df.columns:
            valid = df.dropna(subset=["lat", "lon"])
            valid = valid[(valid["lat"] != 0) & (valid["lon"] != 0)]
            if len(valid) > 0:
                all_lats.extend(valid["lat"].tolist())
                all_lons.extend(valid["lon"].tolist())
    if all_lats:
        center_lat = sum(all_lats) / len(all_lats)
        center_lon = sum(all_lons) / len(all_lons)

    # --- 地図の構築 ---
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=14,
        tiles="cartodbpositron",
    )

    # バス停レイヤー
    fg_stops = folium.FeatureGroup(name="🚏 バス停")
    for _, row in stops_df.iterrows():
        lat, lon = row.get("lat"), row.get("lon")
        if pd.isna(lat) or pd.isna(lon) or lat == 0 or lon == 0:
            continue
        is_dep = str(row.get("is_depot", False)).lower() in ("true", "1")
        is_rev = str(row.get("is_revenue_stop", True)).lower() in ("true", "1")
        color = COLOR_DEPOT_ON if is_dep else COLOR_STOP_MARKER
        folium.CircleMarker(
            location=[lat, lon],
            radius=7 if is_dep else 5,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(
                f"<b>{row.get('stop_name', '')}</b><br>"
                f"ID: {row.get('stop_id', '')}<br>"
                f"seq: {row.get('sequence', '')}<br>"
                f"車庫: {'✅' if is_dep else '—'}<br>"
                f"営業停車: {'✅' if is_rev else '—'}",
                max_width=220,
            ),
            tooltip=f"{row.get('sequence', '')}. {row.get('stop_name', '')}",
        ).add_to(fg_stops)
    fg_stops.add_to(m)

    # セグメント（バス停間）をライン表示
    fg_seg = folium.FeatureGroup(name="📏 セグメント")
    for direction in stops_df["direction"].unique():
        sub = stops_df[stops_df["direction"] == direction].sort_values("sequence")
        coords = []
        for _, row in sub.iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            if not pd.isna(lat) and not pd.isna(lon) and lat != 0 and lon != 0:
                coords.append([lat, lon])
        if len(coords) >= 2:
            folium.PolyLine(
                locations=coords,
                color=COLOR_SEG,
                weight=3,
                opacity=0.7,
                tooltip=f"路線 ({direction})",
            ).add_to(fg_seg)
    fg_seg.add_to(m)

    # デポレイヤー
    fg_depot = folium.FeatureGroup(name="🅿️ 車庫")
    for _, row in depots_df.iterrows():
        lat, lon = row.get("lat"), row.get("lon")
        if pd.isna(lat) or pd.isna(lon) or lat == 0 or lon == 0:
            continue
        is_on = str(row.get("on_route", True)).lower() in ("true", "1")
        folium.Marker(
            location=[lat, lon],
            icon=folium.Icon(
                color="red" if is_on else "purple",
                icon="home",
                prefix="glyphicon",
            ),
            popup=folium.Popup(
                f"<b>{row.get('depot_name', '')}</b><br>"
                f"路線上: {'✅' if is_on else '❌'}<br>"
                f"駐車: {row.get('parking_capacity', '')}<br>"
                f"系統: {row.get('grid_connection_kw', '')} kW",
                max_width=220,
            ),
            tooltip=str(row.get("depot_name", "")),
        ).add_to(fg_depot)
    fg_depot.add_to(m)

    # 充電拠点レイヤー
    if charger_sites_df is not None:
        fg_cs = folium.FeatureGroup(name="⚡ 充電拠点")
        for _, row in charger_sites_df.iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            if pd.isna(lat) or pd.isna(lon) or lat == 0 or lon == 0:
                continue
            folium.Marker(
                location=[lat, lon],
                icon=folium.Icon(color="green", icon="flash", prefix="glyphicon"),
                popup=folium.Popup(
                    f"<b>{row.get('site_name', '')}</b><br>"
                    f"系統上限: {row.get('max_grid_kw', '')} kW",
                    max_width=200,
                ),
                tooltip=str(row.get("site_name", "")),
            ).add_to(fg_cs)
        fg_cs.add_to(m)

    folium.LayerControl().add_to(m)

    # --- 地図表示 ---
    st.markdown("**地図をクリックして座標を取得 → 下のフォームで追加**")
    map_result = st_folium(
        m,
        width=900,
        height=500,
        key=_sk("folium_main"),
        returned_objects=["last_clicked"],
    )

    # --- クリック座標の取得 (session_state に保存) ---
    if map_result and isinstance(map_result, dict):
        last_clicked = map_result.get("last_clicked")
        if last_clicked and isinstance(last_clicked, dict):
            new_lat = last_clicked.get("lat")
            new_lng = last_clicked.get("lng")
            if new_lat is not None and new_lng is not None:
                st.session_state[_sk("click_lat")] = new_lat
                st.session_state[_sk("click_lng")] = new_lng

    # クリック座標の表示
    clat = st.session_state.get(_sk("click_lat"))
    clng = st.session_state.get(_sk("click_lng"))

    if clat is not None and clng is not None:
        st.info(f"📍 選択座標: **{clat:.6f}, {clng:.6f}**")
    else:
        st.caption("地図をクリックすると座標が表示されます。")

    # === 新規ポイント追加フォーム ===
    st.markdown("---")
    st.markdown("### ➕ 地図クリック位置にポイントを追加")

    add_type = st.radio(
        "追加タイプ",
        ["🚏 バス停", "🅿️ 車庫 (路線上)", "🅿️ 車庫 (路線外)"],
        horizontal=True,
        key=_sk("add_type"),
    )

    with st.form(key=_sk("map_add_form"), clear_on_submit=True):
        fc = st.columns([2, 1, 1, 1, 1])
        with fc[0]:
            f_name = st.text_input("名称")
        with fc[1]:
            f_lat = st.number_input(
                "緯度", value=clat if clat else 0.0, format="%.6f",
            )
        with fc[2]:
            f_lng = st.number_input(
                "経度", value=clng if clng else 0.0, format="%.6f",
            )

        if "バス停" in add_type:
            with fc[3]:
                f_dir = st.selectbox("方向", ["outbound", "inbound"])
            with fc[4]:
                f_depot = st.checkbox("車庫でもある")
            f_rev = st.checkbox("営業停車（旅客乗降あり）", value=True)
        else:
            with fc[3]:
                f_cap = st.number_input("駐車容量", min_value=1, value=10)
            with fc[4]:
                f_grid = st.number_input("系統接続 [kW]", min_value=0.0, value=150.0, step=10.0)
            f_rev = st.checkbox("営業停車（旅客乗降あり）", value=False)

        submitted = st.form_submit_button("📌 追加", type="primary")

        if submitted and f_name and f_lat != 0.0 and f_lng != 0.0:
            if "バス停" in add_type:
                # バス停として追加
                sub_dir = stops_df[stops_df["direction"] == f_dir]
                next_seq = int(sub_dir["sequence"].max()) + 1 if len(sub_dir) > 0 else 1
                new_stop_id = f"stop_{f_name.replace(' ', '_')}"
                new_row = pd.DataFrame([{
                    "stop_id": new_stop_id,
                    "stop_name": f_name,
                    "route_id": "route_101",
                    "direction": f_dir,
                    "sequence": next_seq,
                    "lat": f_lat,
                    "lon": f_lng,
                    "is_terminal": False,
                    "terminal_id": "",
                    "is_depot": f_depot,
                    "is_revenue_stop": f_rev,
                    "distance_from_prev_km": 0.0,
                }])
                stops_df = pd.concat([stops_df, new_row], ignore_index=True)
                stops_df = _compute_distance_from_prev(
                    stops_df.sort_values(["direction", "sequence"]).reset_index(drop=True)
                )
                st.session_state[_sk("updated_stops")] = stops_df
                st.success(f"バス停 '{f_name}' を追加しました ({f_lat:.4f}, {f_lng:.4f})")
            else:
                on_route = "路線上" in add_type
                d_id = f"depot_{f_name.replace(' ', '_')}"
                new_depot = pd.DataFrame([{
                    "depot_id": d_id,
                    "depot_name": f_name,
                    "lat": f_lat,
                    "lon": f_lng,
                    "on_route": on_route,
                    "nearest_stop_id": "",
                    "is_revenue_stop": f_rev,
                    "parking_capacity": f_cap,
                    "overnight_charging": True,
                    "grid_connection_kw": f_grid,
                    "notes": "",
                }])
                depots_df = pd.concat([depots_df, new_depot], ignore_index=True)
                st.session_state[_sk("updated_depots")] = depots_df
                loc_str = "路線上" if on_route else "路線外"
                st.success(f"車庫 '{f_name}' ({loc_str}) を追加しました ({f_lat:.4f}, {f_lng:.4f})")

    # session_state に更新があれば反映
    if _sk("updated_stops") in st.session_state:
        stops_df = st.session_state[_sk("updated_stops")]
    if _sk("updated_depots") in st.session_state:
        depots_df = st.session_state[_sk("updated_depots")]

    # === データテーブル編集 ===
    st.markdown("---")
    st.markdown("### 📋 データ表（微調整用）")

    map_tabs = st.tabs(["🚏 バス停", "🅿️ 車庫"])

    with map_tabs[0]:
        st.markdown(
            '<div style="background:#f0f7ff; border-radius:8px; padding:8px 12px; margin-bottom:8px; font-size:0.82em; line-height:1.6;">'
            '<b>順序</b>=並び順 │ <b>停留所ID</b>=一意キー │ <b>停留所名</b>=表示名 │ '
            '<b>方向</b>=outbound(往路)/inbound(復路) │ '
            '<b>前停距離</b>=前バス停からの距離[km]<br>'
            '<b>緯度/経度</b>=地理座標 │ '
            '<b>車庫</b>=✅で車庫兼用 │ <b>営業停車</b>=✅で旅客乗降あり │ '
            '<b>ターミナル</b>=✅で路線起終点'
            '</div>',
            unsafe_allow_html=True,
        )
        map_stop_cols = [
            "sequence", "stop_id", "stop_name", "direction",
            "distance_from_prev_km", "lat", "lon",
            "is_depot", "is_revenue_stop", "is_terminal",
        ]
        map_stop_cols = [c for c in map_stop_cols if c in stops_df.columns]
        edited_stops_map = st.data_editor(
            stops_df[map_stop_cols].sort_values(["direction", "sequence"]),
            width='stretch',
            num_rows="dynamic",
            key=_sk("map_edit_stops"),
            column_config={
                "sequence": st.column_config.NumberColumn(
                    "順序", help="路線内でのバス停の並び順",
                ),
                "stop_id": st.column_config.TextColumn(
                    "停留所 ID", help="一意の識別子（例: stop_A）",
                ),
                "stop_name": st.column_config.TextColumn(
                    "停留所名", help="バス停の表示名",
                ),
                "direction": st.column_config.TextColumn(
                    "方向", help="outbound=往路、inbound=復路",
                ),
                "distance_from_prev_km": st.column_config.NumberColumn(
                    "前停距離[km]", format="%.3f",
                    help="ひとつ前のバス停からの距離 [km]",
                ),
                "lat": st.column_config.NumberColumn(
                    "緯度", format="%.6f", help="北緯",
                ),
                "lon": st.column_config.NumberColumn(
                    "経度", format="%.6f", help="東経",
                ),
                "is_depot": st.column_config.CheckboxColumn(
                    "車庫", default=False,
                    help="✅ = この停留所が車庫を兼ねる",
                ),
                "is_revenue_stop": st.column_config.CheckboxColumn(
                    "営業停車", default=True,
                    help="✅ = 旅客の乗降がある停留所",
                ),
                "is_terminal": st.column_config.CheckboxColumn(
                    "ターミナル", default=False,
                    help="✅ = 路線の起点または終点",
                ),
            },
        )
        # 非表示列を復元
        for c in stops_df.columns:
            if c not in edited_stops_map.columns:
                edited_stops_map[c] = stops_df[c].values[:len(edited_stops_map)] if len(stops_df) >= len(edited_stops_map) else ""

    with map_tabs[1]:
        st.markdown(
            '<div style="background:#fff5f5; border-radius:8px; padding:8px 12px; margin-bottom:8px; font-size:0.82em; line-height:1.6;">'
            '<b>車庫ID</b>=一意キー │ <b>車庫名</b>=表示名 │ '
            '<b>緯度/経度</b>=位置 │ '
            '<b>路線上</b>=✅で路線上の車庫(❌は路線外→回送必要)<br>'
            '<b>最寄りバス停</b>=路線外の場合の最寄り │ '
            '<b>営業停車</b>=✅で旅客乗降あり │ '
            '<b>駐車容量</b>=最大駐車台数 │ <b>夜間充電</b>=✅で充電可 │ '
            '<b>系統接続[kW]</b>=電力上限'
            '</div>',
            unsafe_allow_html=True,
        )
        depot_disp = [c for c in DEPOTS_COLS if c in depots_df.columns]
        edited_depots_map = st.data_editor(
            depots_df[depot_disp] if depot_disp else depots_df,
            width='stretch',
            num_rows="dynamic",
            key=_sk("map_edit_depots"),
            column_config={
                "depot_id": st.column_config.TextColumn(
                    "車庫 ID", help="車庫の一意識別子",
                ),
                "depot_name": st.column_config.TextColumn(
                    "車庫名", help="車庫の表示名",
                ),
                "lat": st.column_config.NumberColumn(
                    "緯度", format="%.6f", help="北緯",
                ),
                "lon": st.column_config.NumberColumn(
                    "経度", format="%.6f", help="東経",
                ),
                "on_route": st.column_config.CheckboxColumn(
                    "路線上", default=True,
                    help="✅=路線上の車庫。❌=路線外（回送が必要）",
                ),
                "nearest_stop_id": st.column_config.TextColumn(
                    "最寄りバス停",
                    help="路線外デポの場合、最も近いバス停ID",
                ),
                "is_revenue_stop": st.column_config.CheckboxColumn(
                    "営業停車", default=False,
                    help="✅=営業運転で旅客が乗降する",
                ),
                "parking_capacity": st.column_config.NumberColumn(
                    "駐車容量", help="同時駐車できる最大台数",
                ),
                "overnight_charging": st.column_config.CheckboxColumn(
                    "夜間充電", help="✅=夜間にバスを充電可能",
                ),
                "grid_connection_kw": st.column_config.NumberColumn(
                    "系統接続[kW]", help="電力系統の最大接続容量",
                ),
                "notes": st.column_config.TextColumn(
                    "備考", help="自由記入",
                ),
            },
        )

    # === セグメント自動生成 ===
    st.markdown("---")
    with st.expander("📏 セグメント（自動生成プレビュー）", expanded=False):
        route_id = "route_101"
        if route_df is not None and len(route_df) > 0:
            route_id = route_df.iloc[0].get("route_id", "route_101")
        auto_seg = _generate_segments(edited_stops_map, route_id)
        if len(auto_seg) > 0:
            st.dataframe(auto_seg, width='stretch')
        else:
            st.info("バス停が 2 つ以上必要です。")

    # === 保存 ===
    st.markdown("---")
    sc1, sc2 = st.columns([1, 3])
    with sc1:
        if st.button("💾 路線データを保存", type="primary", key=_sk("save_map")):
            auto_seg2 = _generate_segments(edited_stops_map, route_id)
            saved = _save_all(
                data_dir, edited_stops_map, edited_depots_map,
                segments_df=auto_seg2,
                route_df=route_df,
            )
            # session state をクリア
            for k in [_sk("updated_stops"), _sk("updated_depots")]:
                st.session_state.pop(k, None)
            st.session_state[_sk("last_save_map")] = saved
    with sc2:
        if _sk("last_save_map") in st.session_state:
            st.success(f"保存しました: {', '.join(st.session_state[_sk('last_save_map')])}")


# ---------------------------------------------------------------------------
# メインエントリー
# ---------------------------------------------------------------------------

def render_route_detail_editor(data_dir: str = "data") -> None:
    """
    路線詳細エディタのメイン関数。
    「単純編集」と「地図から入力」をラジオボタンで切り替えられる。
    """
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1a6fbf22, #00a99d22);
        border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
    ">
        <h3 style="margin:0;">🛤️ 路線詳細エディタ</h3>
        <p style="margin:4px 0 0; color:#666; font-size:0.9em;">
            路線の長さ、バス停の配置・距離、車庫の位置を編集します。<br>
            車庫は路線上・路線外どちらにも配置でき、営業停車の有無を設定できます。
        </p>
    </div>
    """, unsafe_allow_html=True)

    # --- モード選択 ---
    mode = st.radio(
        "入力モード",
        ["📝 単純編集（テーブル入力）", "🗺️ 地図から入力"],
        horizontal=True,
        key=_sk("input_mode"),
        help="「単純編集」ではテーブルで距離・名称を直接入力。「地図から入力」では地図クリックで座標を取得します。",
    )

    # --- データ読み込み ---
    data = _load_all(data_dir)

    if "単純" in mode:
        _render_simple_editor(data, data_dir)
    else:
        _render_map_editor(data, data_dir)
