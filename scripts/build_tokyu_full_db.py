"""
scripts/build_tokyu_full_db.py
==============================
東急バス 全路線・全停留所・全時刻表 → SQLite 構築スクリプト
(標準ライブラリのみ。外部依存ゼロ)

出力: data/tokyu_full.sqlite
  - operators              事業者
  - depots                 営業所（パターンIDから推定）
  - route_patterns         路線パターン（停留所順序付き）
  - route_families         route family サマリ
  - stops                  停留所（BusstopPole）
  - timetable_trips        便（BusTimetable → 1オブジェクト1便）
  - trip_stops             便の通過停留所×時刻
  - stop_timetables        停留所時刻表（BusstopPoleTimetable）
  - pipeline_meta          取得メタ情報

実行例:
    python scripts/build_tokyu_full_db.py
    python scripts/build_tokyu_full_db.py --skip-stop-timetables
    python scripts/build_tokyu_full_db.py --resume
    python scripts/build_tokyu_full_db.py --out data/tokyu_full.sqlite
    python scripts/build_tokyu_full_db.py --api-key YOUR_KEY

注意:
    停留所時刻表（BusstopPoleTimetable）は件数が多く時間がかかります（30分〜）。
    --skip-stop-timetables で省略すると大幅に高速化できます（MILP計算には不要）。
    --resume を使うと途中から再開できます。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from typing import Any, Iterator
import csv

from _odpt_runtime import resolve_odpt_api_key

# ─── 定数 ─────────────────────────────────────────────────────────────────

ODPT_BASE        = "https://api.odpt.org/api/4"
OPERATOR_ID      = "odpt.Operator:TokyuBus"
DEFAULT_OUT      = Path("data") / "tokyu_full.sqlite"
CACHE_DIR        = Path("data") / "odpt_raw_cache"
RETRY_WAIT       = 5    # 秒
MAX_RETRIES      = 5
THROTTLE_SEC     = 0.25 # リクエスト間隔

# 既知の東急バス営業所（パターンIDから推定するための辞書）
# key = パターンIDに含まれる文字列, value = 営業所ID/名称
DEPOT_HINTS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"黒|kuro|Kuro"),                 "tokyu:depot:meguro",    "目黒営業所"),
    (re.compile(r"渋|shibu|Shibu|東98"),           "tokyu:depot:meguro",    "目黒営業所"),
    (re.compile(r"さんま"),                         "tokyu:depot:meguro",    "目黒営業所"),
    (re.compile(r"東98"),                           "tokyu:depot:meguro",    "目黒営業所"),
    (re.compile(r"田|ta[0-9]|den[0-9]"),           "tokyu:depot:denenchofu","田園調布営業所"),
    (re.compile(r"二子|futako|Futako"),             "tokyu:depot:futako",    "二子玉川営業所"),
    (re.compile(r"港|minato|Minato"),               "tokyu:depot:minato",    "港北営業所"),
    (re.compile(r"鷺|sagi|Sagi"),                   "tokyu:depot:sagimiyako","鷺沼営業所"),
    (re.compile(r"虹|niji|Rainbow"),                "tokyu:depot:tsurumi",   "鶴見営業所"),
    (re.compile(r"川崎|kawasaki|Kawasaki"),         "tokyu:depot:kawasaki",  "川崎営業所"),
    (re.compile(r"綱島|tsunashima|Tsunashima"),     "tokyu:depot:tsunashima","綱島営業所"),
    (re.compile(r"青葉|aoba|Aoba"),                 "tokyu:depot:aoba",      "青葉台営業所"),
    (re.compile(r"長津田|nagatsuta|Nagatsuta"),     "tokyu:depot:nagatsuta", "長津田営業所"),
    (re.compile(r"恩田|onda|Onda"),                 "tokyu:depot:onda",      "恩田営業所"),
]

_REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DEPOTS_PATH = _REPO_ROOT / "data" / "seed" / "tokyu" / "depots.json"
ROUTE_TO_DEPOT_PATH = _REPO_ROOT / "data" / "seed" / "tokyu" / "route_to_depot.csv"
SEED_ROUTE_TO_DEPOT: dict[str, tuple[str, str]] = {}


# ─── ロギング ──────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ─── HTTP / キャッシュ ──────────────────────────────────────────────────────

def _cache_path(resource: str, extra: str = "") -> Path:
    key = re.sub(r"[^a-zA-Z0-9_]", "_", resource + extra)[:180]
    return CACHE_DIR / f"{key}.json"


def odpt_fetch(resource: str, params: dict, api_key: str,
               use_cache: bool = True) -> list[dict]:
    """
    ODPT APIからリソースを取得。
    resource 例: "odpt:BusroutePattern"
    params には operator などを渡す。acl:consumerKey は自動付与。
    """
    params = dict(params)
    params["acl:consumerKey"] = api_key
    url = f"{ODPT_BASE}/{resource}?{urlencode(params)}"

    extra = urlencode({k: v for k, v in params.items() if k != "acl:consumerKey"})
    cpath = _cache_path(resource, extra)

    if use_cache and cpath.exists():
        data = json.loads(cpath.read_text(encoding="utf-8"))
        log(f"  [cache] {resource} extra={extra[:60]} → {len(data)}件")
        return data

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"Accept": "application/json",
                                         "User-Agent": "master-course-db-builder/1.0"})
            with urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                data = [data]
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(THROTTLE_SEC)
            log(f"  [fetch] {resource} extra={extra[:60]} → {len(data)}件")
            return data
        except HTTPError as e:
            if e.code == 429:
                wait = RETRY_WAIT * attempt
                log(f"  [429] rate limit, wait {wait}s (attempt {attempt})")
                time.sleep(wait)
            elif e.code in (500, 502, 503, 504):
                log(f"  [HTTP {e.code}] retry {attempt}")
                time.sleep(RETRY_WAIT)
            else:
                log(f"  [HTTP {e.code}] {e.reason} — {url[:100]}")
                return []
        except (URLError, TimeoutError) as e:
            log(f"  [net error] {e} attempt={attempt}")
            time.sleep(RETRY_WAIT * attempt)
        except json.JSONDecodeError as e:
            log(f"  [json error] {e}")
            return []

    log(f"  [GIVE UP] {resource} {extra[:60]}")
    return []


# ─── スキーマ ──────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS operators (
    operator_id  TEXT PRIMARY KEY,
    title_ja     TEXT,
    title_en     TEXT
);

CREATE TABLE IF NOT EXISTS depots (
    depot_id     TEXT PRIMARY KEY,
    operator_id  TEXT NOT NULL,
    title_ja     TEXT,
    title_en     TEXT,
    lat          REAL,
    lon          REAL
);

-- 路線パターン（BusroutePattern 1件 = 1行）
CREATE TABLE IF NOT EXISTS route_patterns (
    pattern_id      TEXT PRIMARY KEY,
    operator_id     TEXT NOT NULL,
    route_family    TEXT NOT NULL,   -- 例: 黒01
    title_ja        TEXT,
    title_kana      TEXT,
    direction       TEXT,            -- Inbound/Outbound/Loop
    via             TEXT,
    origin_stop_id  TEXT,
    dest_stop_id    TEXT,
    stop_count      INTEGER DEFAULT 0,
    depot_id        TEXT,
    raw_json        TEXT
);

-- route_patterns の停留所順序
CREATE TABLE IF NOT EXISTS pattern_stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id      TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    stop_id         TEXT NOT NULL,
    UNIQUE(pattern_id, seq)
);

-- route family サマリ（route_patterns から集約）
CREATE TABLE IF NOT EXISTS route_families (
    route_family    TEXT NOT NULL,
    operator_id     TEXT NOT NULL,
    title_ja        TEXT,
    pattern_count   INTEGER DEFAULT 0,
    depot_id        TEXT,
    PRIMARY KEY (route_family, operator_id)
);

-- 停留所（BusstopPole）
CREATE TABLE IF NOT EXISTS stops (
    stop_id      TEXT PRIMARY KEY,
    operator_id  TEXT NOT NULL,
    title_ja     TEXT,
    title_kana   TEXT,
    lat          REAL,
    lon          REAL,
    platform_num TEXT,
    raw_json     TEXT
);

-- 便（BusTimetable → 各timetableObjectが1便）
-- BusTimetable 1オブジェクト = カレンダー×方向 の全便リスト
-- 「便」= departure_time が異なるもの1つずつ
CREATE TABLE IF NOT EXISTS timetable_trips (
    trip_id         TEXT PRIMARY KEY,  -- "{timetable_id}::{idx}"
    timetable_id    TEXT NOT NULL,     -- odpt:BusTimetable の owl:sameAs
    pattern_id      TEXT NOT NULL,
    route_family    TEXT,
    calendar_type   TEXT NOT NULL,     -- 平日/土曜/日祝
    direction       TEXT,
    origin_stop_id  TEXT,
    dest_stop_id    TEXT,
    departure_hhmm  TEXT,              -- HH:MM
    arrival_hhmm    TEXT,              -- HH:MM
    dep_min         INTEGER,           -- midnight基準の分
    arr_min         INTEGER,           -- midnight基準の分
    duration_min    INTEGER,
    stop_count      INTEGER DEFAULT 0,
    is_nonstop      INTEGER DEFAULT 0  -- 0=通常, 1=急行等
);

-- 便の通過停留所×時刻（BusTimetableObject の詳細）
CREATE TABLE IF NOT EXISTS trip_stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    stop_id         TEXT NOT NULL,
    departure_hhmm  TEXT,
    arrival_hhmm    TEXT,
    dep_min         INTEGER,
    arr_min         INTEGER,
    UNIQUE(trip_id, seq)
);

-- 停留所時刻表（BusstopPoleTimetable）
CREATE TABLE IF NOT EXISTS stop_timetables (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stop_id         TEXT NOT NULL,
    pattern_id      TEXT NOT NULL,
    calendar_type   TEXT NOT NULL,
    direction       TEXT,
    departure_hhmm  TEXT,
    dep_min         INTEGER,
    note            TEXT
);

-- 取得進捗（resume用）
CREATE TABLE IF NOT EXISTS fetch_progress (
    resource        TEXT NOT NULL,
    key             TEXT NOT NULL,
    status          TEXT NOT NULL,  -- done / error
    count           INTEGER DEFAULT 0,
    updated_at      TEXT,
    PRIMARY KEY (resource, key)
);

-- メタ情報
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_route_patterns_family
    ON route_patterns(route_family);
CREATE INDEX IF NOT EXISTS idx_route_patterns_depot
    ON route_patterns(depot_id);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_pattern
    ON timetable_trips(pattern_id);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_family_cal
    ON timetable_trips(route_family, calendar_type);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_dep_min
    ON timetable_trips(dep_min);
CREATE INDEX IF NOT EXISTS idx_trip_stops_trip
    ON trip_stops(trip_id);
CREATE INDEX IF NOT EXISTS idx_stop_timetables_stop
    ON stop_timetables(stop_id);
CREATE INDEX IF NOT EXISTS idx_stop_timetables_pattern
    ON stop_timetables(pattern_id);
"""


# ─── ユーティリティ ────────────────────────────────────────────────────────

def hhmm_to_min(t: str) -> int | None:
    """'HH:MM' または 'H:MM' → 分（midnight基準）"""
    if not t:
        return None
    t = t.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def load_seed_route_map() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    if not ROUTE_TO_DEPOT_PATH.exists():
        return mapping
    with ROUTE_TO_DEPOT_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            route_code = str(row.get("route_code") or "").strip()
            depot_id = str(row.get("depot_id") or "").strip()
            depot_name = str(row.get("depot_name") or depot_id).strip()
            if route_code and depot_id:
                mapping[route_code] = (f"tokyu:depot:{depot_id}", depot_name)
    return mapping


def seed_all_depots(conn: sqlite3.Connection) -> None:
    if not SEED_DEPOTS_PATH.exists():
        return
    payload = json.loads(SEED_DEPOTS_PATH.read_text(encoding="utf-8"))
    depots = list(payload.get("depots") or [])
    for depot in depots:
        depot_key = str(depot.get("depotId") or depot.get("id") or "").strip()
        if not depot_key:
            continue
        depot_id = f"tokyu:depot:{depot_key}"
        conn.execute(
            """
            INSERT OR IGNORE INTO depots (depot_id, operator_id, title_ja, title_en, lat, lon)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                depot_id,
                OPERATOR_ID,
                depot.get("name") or depot_key,
                depot.get("name") or depot_key,
                float(depot.get("lat") or 0.0),
                float(depot.get("lon") or 0.0),
            ),
        )
    conn.commit()


def infer_depot(pattern_id: str, title: str) -> tuple[str, str] | tuple[None, None]:
    """パターンIDと標題から営業所を推定。(depot_id, title_ja) を返す。"""
    text = pattern_id + " " + title
    family = extract_route_family(pattern_id, title)
    mapped = SEED_ROUTE_TO_DEPOT.get(family)
    if mapped is not None:
        return mapped
    for pat, did, dtitle in DEPOT_HINTS:
        if pat.search(text):
            return did, dtitle
    return None, None


def extract_route_family(pattern_id: str, title: str) -> str:
    """
    パターンIDから route_family を抽出。
    odpt.BusroutePattern:TokyuBus.黒01.1.Inbound → 黒01
    """
    # 形式1: TokyuBus.FAMILY.数字.方向
    m = re.search(r"TokyuBus\.([^.]+)\.\d", pattern_id)
    if m:
        return m.group(1)
    # 形式2: タイトルの先頭（スペース・括弧前）
    m2 = re.match(r"^([^\s（(【「\[]+)", title.strip())
    if m2:
        return m2.group(1)
    return title.strip() or pattern_id


def calendar_label(raw: str) -> str:
    """ODPT calendarオブジェクトの @id または文字列から 平日/土曜/日祝 へ変換。"""
    s = raw.lower()
    if "sat" in s or "土" in s:
        return "土曜"
    if "sun" in s or "hol" in s or "日" in s or "祝" in s:
        return "日祝"
    return "平日"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── DB初期化 ──────────────────────────────────────────────────────────────

def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    log(f"DB初期化完了: {path}")
    return conn


def is_done(conn: sqlite3.Connection, resource: str, key: str) -> bool:
    row = conn.execute(
        "SELECT status FROM fetch_progress WHERE resource=? AND key=?",
        (resource, key)
    ).fetchone()
    return row is not None and row[0] == "done"


def mark_done(conn: sqlite3.Connection, resource: str, key: str, count: int) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO fetch_progress (resource, key, status, count, updated_at)
        VALUES (?, ?, 'done', ?, ?)
    """, (resource, key, count, now_iso()))
    conn.commit()


# ─── データ挿入 ────────────────────────────────────────────────────────────

def insert_operator(conn: sqlite3.Connection) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO operators (operator_id, title_ja, title_en)
        VALUES (?, ?, ?)
    """, (OPERATOR_ID, "東急バス株式会社", "Tokyu Bus Co., Ltd."))
    conn.commit()


def upsert_depot(conn: sqlite3.Connection, depot_id: str, title_ja: str) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO depots (depot_id, operator_id, title_ja, title_en, lat, lon)
        VALUES (?, ?, ?, ?, 0.0, 0.0)
    """, (depot_id, OPERATOR_ID, title_ja, title_ja))


def insert_stops(conn: sqlite3.Connection, poles: list[dict]) -> int:
    rows = []
    for p in poles:
        sid = p.get("owl:sameAs") or p.get("@id", "")
        rows.append((
            sid, OPERATOR_ID,
            p.get("dc:title", ""),
            p.get("odpt:kana", ""),
            p.get("geo:lat"),
            p.get("geo:long"),
            str(p.get("odpt:platformNumber", "") or ""),
            json.dumps(p, ensure_ascii=False),
        ))
    conn.executemany("""
        INSERT OR REPLACE INTO stops
            (stop_id, operator_id, title_ja, title_kana, lat, lon, platform_num, raw_json)
        VALUES (?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    return len(rows)


def insert_patterns(conn: sqlite3.Connection, patterns: list[dict]) -> dict[str, str]:
    """路線パターンを挿入。{pattern_id: route_family} を返す。"""
    pattern_to_family: dict[str, str] = {}
    pattern_rows = []
    stop_rows = []

    for p in patterns:
        pid = p.get("owl:sameAs") or p.get("@id", "")
        title = p.get("dc:title", "")
        family = extract_route_family(pid, title)
        depot_id, depot_title = infer_depot(pid, title)

        if depot_id:
            upsert_depot(conn, depot_id, depot_title or depot_id)

        stop_order: list[dict] = p.get("odpt:busstopPoleOrder", []) or []
        origin_sid = stop_order[0].get("odpt:busstopPole", "") if stop_order else ""
        dest_sid   = stop_order[-1].get("odpt:busstopPole", "") if stop_order else ""

        pattern_rows.append((
            pid, OPERATOR_ID, family, title,
            p.get("odpt:kana", ""),
            p.get("odpt:direction", ""),
            p.get("odpt:viaStopTitle", "") or p.get("odpt:via", ""),
            origin_sid, dest_sid,
            len(stop_order),
            depot_id,
            json.dumps(p, ensure_ascii=False),
        ))
        pattern_to_family[pid] = family

        for i, s in enumerate(stop_order):
            sid = s.get("odpt:busstopPole", "")
            if sid:
                stop_rows.append((pid, i + 1, sid))

    conn.executemany("""
        INSERT OR REPLACE INTO route_patterns
            (pattern_id, operator_id, route_family, title_ja, title_kana,
             direction, via, origin_stop_id, dest_stop_id, stop_count, depot_id, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, pattern_rows)

    conn.executemany("""
        INSERT OR IGNORE INTO pattern_stops (pattern_id, seq, stop_id)
        VALUES (?,?,?)
    """, stop_rows)
    conn.commit()
    return pattern_to_family


def rebuild_route_families(conn: sqlite3.Connection) -> int:
    """route_patterns から route_families を再集計。"""
    conn.execute("DELETE FROM route_families")
    conn.execute("""
        INSERT OR REPLACE INTO route_families
            (route_family, operator_id, title_ja, pattern_count, depot_id)
        SELECT
            route_family,
            operator_id,
            MIN(title_ja),
            COUNT(*),
            MIN(depot_id)
        FROM route_patterns
        GROUP BY route_family, operator_id
    """)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM route_families").fetchone()[0]
    return count


def insert_timetable(conn: sqlite3.Connection,
                     tt_obj: dict,
                     pattern_to_family: dict[str, str]) -> int:
    """
    odpt:BusTimetable 1オブジェクト → timetable_trips + trip_stops に挿入。
    """
    tt_id   = tt_obj.get("owl:sameAs") or tt_obj.get("@id", "")
    pid     = tt_obj.get("odpt:busroutePattern", "")
    cal_raw = tt_obj.get("odpt:calendar", "")
    cal     = calendar_label(cal_raw)
    direction = tt_obj.get("odpt:direction", "")
    family  = pattern_to_family.get(pid, extract_route_family(pid, ""))

    objects: list[dict] = tt_obj.get("odpt:busTimetableObject", []) or []

    trip_rows = []
    stop_rows_all = []

    # BusTimetableObject の各要素が1便
    # ただし ODPT の設計によっては1オブジェクトが複数停留所の通過時刻リストの場合がある
    # その場合は departure_time ごとにグループ化する

    # まず全エントリを出発時刻でグループ化
    trips_by_dep: dict[str, list[dict]] = {}
    trip_idx = 0
    for obj in objects:
        dep = obj.get("odpt:departureTime", "") or obj.get("odpt:arrivalTime", "")
        if dep:
            if dep not in trips_by_dep:
                trips_by_dep[dep] = []
            trips_by_dep[dep].append(obj)
        else:
            # 時刻なし → スキップ
            pass

    # 単一停留所×複数時刻のケース（停留所時刻表形式）
    # vs 複数停留所×単一時刻のケース（行路形式）
    # 行路形式の判定: stop_id のユニーク数 > 1
    unique_stops = set()
    for obj in objects:
        sid = obj.get("odpt:busstopPole", "")
        if sid:
            unique_stops.add(sid)

    if len(unique_stops) > 1:
        # 行路形式: objects 全体が1便の通過停留所リスト
        if not objects:
            return 0
        first = objects[0]
        last  = objects[-1]
        dep_hhmm = (first.get("odpt:departureTime", "") or
                    first.get("odpt:arrivalTime", ""))
        arr_hhmm = (last.get("odpt:arrivalTime", "") or
                    last.get("odpt:departureTime", ""))
        origin = first.get("odpt:busstopPole", "")
        dest   = last.get("odpt:busstopPole", "")
        dep_min = hhmm_to_min(dep_hhmm)
        arr_min = hhmm_to_min(arr_hhmm)
        if dep_min and arr_min and arr_min < dep_min:
            arr_min += 1440  # 翌日跨ぎ

        trip_id = f"{tt_id}::0"
        trip_rows.append((
            trip_id, tt_id, pid, family, cal, direction,
            origin, dest, dep_hhmm, arr_hhmm,
            dep_min, arr_min,
            (arr_min - dep_min) if (dep_min and arr_min) else None,
            len(objects), 0,
        ))
        for seq, obj in enumerate(objects):
            sid = obj.get("odpt:busstopPole", "")
            d_hhmm = obj.get("odpt:departureTime", "")
            a_hhmm = obj.get("odpt:arrivalTime", "") or d_hhmm
            d_min = hhmm_to_min(d_hhmm)
            a_min = hhmm_to_min(a_hhmm)
            stop_rows_all.append((trip_id, seq + 1, sid, d_hhmm, a_hhmm, d_min, a_min))

    else:
        # 停留所時刻表形式: 各エントリが別々の便
        # (1停留所 or 停留所なし)
        stop_id_common = objects[0].get("odpt:busstopPole", "") if objects else ""
        for idx, obj in enumerate(objects):
            dep_hhmm = obj.get("odpt:departureTime", "") or obj.get("odpt:arrivalTime", "")
            arr_hhmm = obj.get("odpt:arrivalTime", "") or dep_hhmm
            dep_min = hhmm_to_min(dep_hhmm)
            arr_min = hhmm_to_min(arr_hhmm)
            sid = obj.get("odpt:busstopPole", "") or stop_id_common
            trip_id = f"{tt_id}::{idx}"
            trip_rows.append((
                trip_id, tt_id, pid, family, cal, direction,
                sid, sid, dep_hhmm, arr_hhmm,
                dep_min, arr_min,
                0, 1, 0,
            ))

    if trip_rows:
        conn.executemany("""
            INSERT OR REPLACE INTO timetable_trips
                (trip_id, timetable_id, pattern_id, route_family, calendar_type, direction,
                 origin_stop_id, dest_stop_id, departure_hhmm, arrival_hhmm,
                 dep_min, arr_min, duration_min, stop_count, is_nonstop)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, trip_rows)

    if stop_rows_all:
        conn.executemany("""
            INSERT OR IGNORE INTO trip_stops
                (trip_id, seq, stop_id, departure_hhmm, arrival_hhmm, dep_min, arr_min)
            VALUES (?,?,?,?,?,?,?)
        """, stop_rows_all)

    return len(trip_rows)


def insert_stop_timetable(conn: sqlite3.Connection,
                          stt_obj: dict) -> int:
    """odpt:BusstopPoleTimetable 1オブジェクト → stop_timetables に挿入。"""
    stop_id   = stt_obj.get("odpt:busstopPole", "")
    pid       = stt_obj.get("odpt:busroutePattern", "")
    cal_raw   = stt_obj.get("odpt:calendar", "")
    cal       = calendar_label(cal_raw)
    direction = stt_obj.get("odpt:direction", "")

    objects: list[dict] = stt_obj.get("odpt:busstopPoleTimetableObject", []) or []
    rows = []
    for obj in objects:
        dep_hhmm = obj.get("odpt:departureTime", "")
        dep_min  = hhmm_to_min(dep_hhmm)
        note     = obj.get("odpt:note", "")
        rows.append((stop_id, pid, cal, direction, dep_hhmm, dep_min, note))

    if rows:
        conn.executemany("""
            INSERT INTO stop_timetables
                (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note)
            VALUES (?,?,?,?,?,?,?)
        """, rows)
    return len(rows)


# ─── フェーズ別取得 ────────────────────────────────────────────────────────

def phase_stops(conn: sqlite3.Connection, api_key: str, use_cache: bool) -> None:
    log("=== Phase 1: 停留所（BusstopPole） ===")
    if is_done(conn, "BusstopPole", "all"):
        log("  [skip] 取得済み")
        return
    poles = odpt_fetch("odpt:BusstopPole",
                       {"odpt:operator": OPERATOR_ID}, api_key, use_cache)
    n = insert_stops(conn, poles)
    mark_done(conn, "BusstopPole", "all", n)
    log(f"  停留所: {n}件 → DB")


def phase_patterns(conn: sqlite3.Connection, api_key: str,
                   use_cache: bool) -> dict[str, str]:
    log("=== Phase 2: 路線パターン（BusroutePattern） ===")
    if is_done(conn, "BusroutePattern", "all"):
        log("  [skip] 取得済み")
        # キャッシュからマッピング再構築
        rows = conn.execute(
            "SELECT pattern_id, route_family FROM route_patterns"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    patterns = odpt_fetch("odpt:BusroutePattern",
                          {"odpt:operator": OPERATOR_ID}, api_key, use_cache)
    pattern_to_family = insert_patterns(conn, patterns)
    family_count = rebuild_route_families(conn)
    mark_done(conn, "BusroutePattern", "all", len(patterns))
    log(f"  パターン: {len(patterns)}件, route_family: {family_count}種 → DB")
    return pattern_to_family


def phase_timetables(conn: sqlite3.Connection, api_key: str,
                     use_cache: bool,
                     pattern_ids: list[str],
                     pattern_to_family: dict[str, str]) -> None:
    log(f"=== Phase 3: 時刻表（BusTimetable） {len(pattern_ids)}パターン ===")
    total_trips = 0
    done_count = conn.execute(
        "SELECT COUNT(*) FROM fetch_progress WHERE resource='BusTimetable' AND status='done'"
    ).fetchone()[0]
    log(f"  取得済みパターン: {done_count}/{len(pattern_ids)}")

    for i, pid in enumerate(pattern_ids):
        if is_done(conn, "BusTimetable", pid):
            continue
        log(f"  [{i+1}/{len(pattern_ids)}] {pid}")
        tt_list = odpt_fetch("odpt:BusTimetable",
                             {"odpt:busroutePattern": pid},
                             api_key, use_cache)
        trip_count = 0
        for tt in tt_list:
            trip_count += insert_timetable(conn, tt, pattern_to_family)
        conn.commit()
        mark_done(conn, "BusTimetable", pid, trip_count)
        total_trips += trip_count

    log(f"  → 便合計: {total_trips}件（このフェーズ分）")


def phase_stop_timetables(conn: sqlite3.Connection, api_key: str,
                           use_cache: bool, pattern_ids: list[str]) -> None:
    log(f"=== Phase 4: 停留所時刻表（BusstopPoleTimetable） {len(pattern_ids)}パターン ===")
    log("  ※件数が多いため時間がかかります。Ctrl+Cで中断しても --resume で再開できます。")

    done_count = conn.execute(
        "SELECT COUNT(*) FROM fetch_progress "
        "WHERE resource='BusstopPoleTimetable' AND status='done'"
    ).fetchone()[0]
    log(f"  取得済みパターン: {done_count}/{len(pattern_ids)}")

    total_entries = 0
    for i, pid in enumerate(pattern_ids):
        if is_done(conn, "BusstopPoleTimetable", pid):
            continue
        log(f"  [{i+1}/{len(pattern_ids)}] {pid}")
        stt_list = odpt_fetch("odpt:BusstopPoleTimetable",
                               {"odpt:busroutePattern": pid},
                               api_key, use_cache)
        entry_count = 0
        for stt in stt_list:
            entry_count += insert_stop_timetable(conn, stt)
        conn.commit()
        mark_done(conn, "BusstopPoleTimetable", pid, entry_count)
        total_entries += entry_count

    log(f"  → 停留所時刻表エントリ合計: {total_entries}件（このフェーズ分）")


# ─── サマリ表示 ────────────────────────────────────────────────────────────

def print_summary(conn: sqlite3.Connection) -> None:
    print()
    print("=" * 65)
    print("  東急バス全体DB 構築完了サマリ")
    print("=" * 65)
    tables = [
        ("operators",        "事業者"),
        ("depots",           "営業所（推定）"),
        ("route_families",   "route_family"),
        ("route_patterns",   "路線パターン"),
        ("stops",            "停留所"),
        ("timetable_trips",  "便（時刻表）"),
        ("trip_stops",       "便通過停留所"),
        ("stop_timetables",  "停留所時刻表エントリ"),
    ]
    for tbl, label in tables:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {label:20s}: {n:>8,} 件")
        except Exception:
            pass

    print()
    print("  route_family 別 平日便数 (上位20):")
    try:
        rows = conn.execute("""
            SELECT route_family, direction, COUNT(*) as cnt
            FROM timetable_trips
            WHERE calendar_type = '平日'
            GROUP BY route_family, direction
            ORDER BY route_family, direction
            LIMIT 40
        """).fetchall()
        prev_fam = None
        for fam, direction, cnt in rows:
            if fam != prev_fam:
                print(f"    {fam or '(不明)'}")
                prev_fam = fam
            print(f"      {direction or '(方向不明)':20s}: {cnt:4d}便")
    except Exception as e:
        print(f"  (便数集計エラー: {e})")

    print()
    print("  営業所別パターン数:")
    try:
        rows = conn.execute("""
            SELECT d.title_ja, COUNT(p.pattern_id) as cnt
            FROM depots d
            LEFT JOIN route_patterns p ON p.depot_id = d.depot_id
            GROUP BY d.depot_id
            ORDER BY cnt DESC
        """).fetchall()
        for title, cnt in rows:
            print(f"    {title or '?':20s}: {cnt:4d} パターン")
    except Exception as e:
        print(f"  (集計エラー: {e})")

    print("=" * 65)


# ─── BFF設定ファイル ────────────────────────────────────────────────────────

def write_env_hint(db_path: Path) -> None:
    """BFF が読み込む環境変数の設定例を表示する。"""
    abs_path = db_path.resolve()
    print()
    print("─" * 65)
    print("  BFF への接続設定")
    print("─" * 65)
    print()
    print("  方法A: 環境変数で指定（推奨）")
    print(f'    export TOKYU_DB_PATH="{abs_path}"')
    print()
    print("  方法B: bff/services/local_db_catalog.py の DB_PATH を直接編集")
    print(f'    DB_PATH = Path("{abs_path}")')
    print()
    print("  BFF起動時に以下でヘルスチェック:")
    print("    python -c \"from bff.services.local_db_catalog import health_check; import json; print(json.dumps(health_check(), ensure_ascii=False, indent=2))\"")
    print()
    print("  MILP入力用データ取得例 (目黒営業所 黒01 平日):")
    print("    python -c \"")
    print("    from bff.services.local_db_catalog import build_milp_trips")
    print("    trips = build_milp_trips(route_families=['黒01'], calendar_type='平日')")
    print("    print(f'{len(trips)}便取得')\"")
    print("─" * 65)


# ─── メイン ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="東急バス全路線データをODPT APIからSQLiteに構築する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--api-key",
                        help="ODPT APIキー。未指定時は .env / 環境変数の ODPT_CONSUMER_KEY / ODPT_API_KEY / ODPT_TOKEN から解決")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help=f"出力SQLiteパス (デフォルト: {DEFAULT_OUT})")
    parser.add_argument("--skip-stop-timetables", action="store_true",
                        help="停留所時刻表(Phase4)をスキップ。MILPには通常不要。")
    parser.add_argument("--resume", action="store_true",
                        help="前回の進捗を引き継いで再開（デフォルト動作も重複スキップするが明示的に指定可）")
    parser.add_argument("--no-cache", action="store_true",
                        help="HTTPキャッシュを使わず毎回APIを叩く")
    parser.add_argument("--phases", default="1,2,3,4",
                        help="実行するフェーズをカンマ区切りで指定 (デフォルト: 1,2,3,4)")
    args = parser.parse_args()
    try:
        api_key = resolve_odpt_api_key(args.api_key)
    except RuntimeError as exc:
        parser.error(str(exc))

    phases = set(int(p.strip()) for p in args.phases.split(","))
    use_cache = not args.no_cache
    db_path = Path(args.out)

    global SEED_ROUTE_TO_DEPOT
    SEED_ROUTE_TO_DEPOT = load_seed_route_map()

    log(f"出力先: {db_path}")
    log(f"キャッシュ: {'無効' if args.no_cache else f'{CACHE_DIR}'}")
    log(f"フェーズ: {sorted(phases)}")

    conn = init_db(db_path)
    insert_operator(conn)
    seed_all_depots(conn)

    # Phase 1: 停留所
    if 1 in phases:
        phase_stops(conn, api_key, use_cache)

    # Phase 2: 路線パターン
    if 2 in phases:
        pattern_to_family = phase_patterns(conn, api_key, use_cache)
    else:
        rows = conn.execute(
            "SELECT pattern_id, route_family FROM route_patterns"
        ).fetchall()
        pattern_to_family = {r[0]: r[1] for r in rows}

    pattern_ids = list(pattern_to_family.keys())
    log(f"路線パターン総数: {len(pattern_ids)}")

    if not pattern_ids:
        log("⚠ 路線パターンが0件です。")
        log("  キー指定を確認してください（--api-key または .env の ODPT_CONSUMER_KEY / ODPT_API_KEY / ODPT_TOKEN）:")
        log(f'  curl "{ODPT_BASE}/odpt:BusroutePattern?odpt:operator={OPERATOR_ID}&acl:consumerKey=YOUR_KEY"')
        conn.close()
        sys.exit(1)

    # Phase 3: 時刻表
    if 3 in phases:
        phase_timetables(conn, api_key, use_cache, pattern_ids, pattern_to_family)

    # Phase 4: 停留所時刻表
    if 4 in phases and not args.skip_stop_timetables:
        phase_stop_timetables(conn, api_key, use_cache, pattern_ids)
    elif args.skip_stop_timetables:
        log("=== Phase 4: 停留所時刻表 — スキップ ===")

    # メタ情報
    conn.executemany("INSERT OR REPLACE INTO pipeline_meta (key, value) VALUES (?,?)", [
        ("built_at", now_iso()),
        ("operator_id", OPERATOR_ID),
        ("skip_stop_timetables", str(args.skip_stop_timetables)),
        ("resume_enabled", str(args.resume)),
        ("cache_dir", str(CACHE_DIR.resolve())),
        ("source", "remote_api_with_local_cache"),
        ("schema_version", "1.1"),
    ])
    conn.commit()

    print_summary(conn)
    write_env_hint(db_path)

    conn.close()
    log(f"✅ 完了: {db_path}")


if __name__ == "__main__":
    main()
