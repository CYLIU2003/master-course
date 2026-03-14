"""
Build a depot-scoped Tokyu Bus SQLite catalog for emergency timetable recovery.

This builder keeps runtime lightweight by preparing a small SQLite file ahead of
time. At runtime the BFF reads the SQLite only; it never calls ODPT directly.

Default editable selection lives in `scripts/tokyu_subset_config.py`.

Example:
    python scripts/build_tokyu_subset_db.py --api-key YOUR_KEY --skip-stop-timetables
    python scripts/build_tokyu_subset_db.py --api-key YOUR_KEY --depots meguro,seta
    python scripts/build_tokyu_subset_db.py --api-key YOUR_KEY --depots meguro,seta --route-codes 黒01,園01
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tokyu_subset_config import SELECTED_DEPOTS, SELECTED_ROUTE_CODES


ODPT_BASE = "https://api.odpt.org/api/4"
OPERATOR_ID = "odpt.Operator:TokyuBus"
DEFAULT_OUT = Path("data") / "tokyu_subset.sqlite"
CACHE_DIR = Path("data") / "odpt_subset_cache"
RETRY_WAIT = 5
MAX_RETRIES = 5
THROTTLE_SEC = 0.25
DEFAULT_DISTANCE_KM = 0.0

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEPOT_MASTER_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_depots_master.json",
    _REPO_ROOT / "data" / "seed" / "tokyu" / "sources" / "tokyu_bus_depots_master.json",
)
ROUTE_TO_DEPOT_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_route_to_depot.csv",
    _REPO_ROOT / "data" / "seed" / "tokyu" / "sources" / "tokyu_bus_route_to_depot.csv",
)

SPECIAL_ROUTE_ALIASES = {
    "サンマバス": "さんまバス",
    "さんま": "さんまバス",
    "目黒区地域交通バスさんまバス": "さんまバス",
    "トランセ": "トランセ",
}

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
    depot_id          TEXT PRIMARY KEY,
    operator_id       TEXT NOT NULL,
    depot_key         TEXT NOT NULL,
    title_ja          TEXT,
    title_en          TEXT,
    address           TEXT,
    phone             TEXT,
    region            TEXT,
    route_map_pdf     TEXT,
    route_map_as_of   TEXT,
    lat               REAL,
    lon               REAL,
    raw_json          TEXT
);

CREATE TABLE IF NOT EXISTS route_patterns (
    pattern_id      TEXT PRIMARY KEY,
    operator_id     TEXT NOT NULL,
    route_family    TEXT NOT NULL,
    route_code      TEXT NOT NULL,
    title_ja        TEXT,
    title_kana      TEXT,
    direction       TEXT,
    via             TEXT,
    origin_stop_id  TEXT,
    dest_stop_id    TEXT,
    stop_count      INTEGER DEFAULT 0,
    depot_id        TEXT,
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS route_pattern_depots (
    pattern_id      TEXT NOT NULL,
    depot_id        TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'authority_csv',
    PRIMARY KEY (pattern_id, depot_id)
);

CREATE TABLE IF NOT EXISTS pattern_stops (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id      TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    stop_id         TEXT NOT NULL,
    UNIQUE(pattern_id, seq)
);

CREATE TABLE IF NOT EXISTS route_families (
    route_family    TEXT NOT NULL,
    operator_id     TEXT NOT NULL,
    route_code      TEXT NOT NULL,
    title_ja        TEXT,
    pattern_count   INTEGER DEFAULT 0,
    depot_id        TEXT,
    PRIMARY KEY (route_family, operator_id)
);

CREATE TABLE IF NOT EXISTS route_family_depots (
    route_family    TEXT NOT NULL,
    operator_id     TEXT NOT NULL,
    depot_id        TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'authority_csv',
    PRIMARY KEY (route_family, operator_id, depot_id)
);

CREATE TABLE IF NOT EXISTS route_code_depots (
    route_code      TEXT NOT NULL,
    depot_id        TEXT NOT NULL,
    source          TEXT NOT NULL,
    PRIMARY KEY (route_code, depot_id, source)
);

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

CREATE TABLE IF NOT EXISTS timetable_trips (
    trip_id         TEXT PRIMARY KEY,
    timetable_id    TEXT NOT NULL,
    pattern_id      TEXT NOT NULL,
    route_family    TEXT,
    calendar_type   TEXT NOT NULL,
    direction       TEXT,
    origin_stop_id  TEXT,
    dest_stop_id    TEXT,
    departure_hhmm  TEXT,
    arrival_hhmm    TEXT,
    dep_min         INTEGER,
    arr_min         INTEGER,
    duration_min    INTEGER,
    stop_count      INTEGER DEFAULT 0,
    is_nonstop      INTEGER DEFAULT 0
);

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

CREATE TABLE IF NOT EXISTS fetch_progress (
    resource        TEXT NOT NULL,
    key             TEXT NOT NULL,
    status          TEXT NOT NULL,
    count           INTEGER DEFAULT 0,
    updated_at      TEXT,
    PRIMARY KEY (resource, key)
);

CREATE TABLE IF NOT EXISTS pipeline_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_route_patterns_family ON route_patterns(route_family);
CREATE INDEX IF NOT EXISTS idx_route_patterns_depot ON route_patterns(depot_id);
CREATE INDEX IF NOT EXISTS idx_route_pattern_depots_depot ON route_pattern_depots(depot_id);
CREATE INDEX IF NOT EXISTS idx_route_family_depots_depot ON route_family_depots(depot_id);
CREATE INDEX IF NOT EXISTS idx_route_code_depots_depot ON route_code_depots(depot_id);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_pattern ON timetable_trips(pattern_id);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_family_cal ON timetable_trips(route_family, calendar_type);
CREATE INDEX IF NOT EXISTS idx_timetable_trips_dep_min ON timetable_trips(dep_min);
CREATE INDEX IF NOT EXISTS idx_trip_stops_trip ON trip_stops(trip_id);
CREATE INDEX IF NOT EXISTS idx_stop_timetables_stop ON stop_timetables(stop_id);
"""


def log(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = text.replace(" ", "").replace("\u3000", "")
    return text


def normalize_route_code(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if "さんま" in text:
        return "さんまバス"
    if "トランセ" in text:
        return "トランセ"
    return SPECIAL_ROUTE_ALIASES.get(text, text)


def canonical_depot_id(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if text.startswith("tokyu:depot:"):
        return text
    return f"tokyu:depot:{text}"


def depot_key_from_id(value: str) -> str:
    text = normalize_text(value)
    return text.split(":")[-1]


def hhmm_to_min(value: str) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})$", str(value).strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def min_to_hhmm(value: int | None, wrap: bool = False) -> str | None:
    if value is None:
        return None
    minutes = int(value)
    if wrap:
        minutes %= 1440
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def roll_forward(value: int | None, reference: int | None) -> int | None:
    if value is None:
        return None
    if reference is None:
        return value
    while value < reference:
        value += 1440
    return value


def resolve_authority_file(candidates: tuple[Path, ...], label: str) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{label} not found. Checked: {', '.join(str(path) for path in candidates)}")


def load_depot_master() -> dict[str, dict[str, Any]]:
    path = resolve_authority_file(DEPOT_MASTER_CANDIDATES, "Tokyu depot master")
    payload = json.loads(path.read_text(encoding="utf-8"))
    depots = payload.get("depots") or []
    result: dict[str, dict[str, Any]] = {}
    for depot in depots:
        depot_key = depot_key_from_id(str(depot.get("depot_id") or depot.get("depotId") or depot.get("id") or ""))
        if depot_key:
            result[depot_key] = depot
    return result


def load_route_to_depot_map() -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    path = resolve_authority_file(ROUTE_TO_DEPOT_CANDIDATES, "Tokyu route-to-depot CSV")
    route_to_depots: dict[str, list[str]] = defaultdict(list)
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            route_code = normalize_route_code(str(row.get("route_code") or ""))
            depot_key = depot_key_from_id(str(row.get("depot_id") or ""))
            if not route_code or not depot_key:
                continue
            if depot_key not in route_to_depots[route_code]:
                route_to_depots[route_code].append(depot_key)
            rows.append(
                {
                    "route_code": route_code,
                    "depot_id": depot_key,
                    "depot_name": str(row.get("depot_name") or ""),
                    "region": str(row.get("region") or ""),
                    "route_map_as_of": str(row.get("route_map_as_of") or ""),
                    "notes": str(row.get("notes") or ""),
                }
            )
    return route_to_depots, rows


def resolve_selected_route_codes(
    selected_depots: list[str],
    requested_route_codes: list[str],
    depot_master: dict[str, dict[str, Any]],
    route_to_depots: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    selected_set = {depot_key_from_id(value) for value in selected_depots}
    missing_depots = sorted(depot for depot in selected_set if depot not in depot_master)
    if missing_depots:
        raise ValueError(f"Unknown depot ids in selection: {', '.join(missing_depots)}")

    csv_route_codes = sorted(
        route_code
        for route_code, depot_keys in route_to_depots.items()
        if any(depot in selected_set for depot in depot_keys)
    )
    requested = [normalize_route_code(code) for code in requested_route_codes if normalize_route_code(code)]
    requested_set = set(requested)

    warnings: list[str] = []
    master_only: dict[str, list[str]] = {}
    for depot_key in sorted(selected_set):
        master_codes = {
            normalize_route_code(code)
            for code in depot_master[depot_key].get("route_codes") or []
            if normalize_route_code(code)
        }
        csv_codes_for_depot = {
            route_code
            for route_code, depot_keys in route_to_depots.items()
            if depot_key in depot_keys
        }
        missing_codes = sorted(master_codes - csv_codes_for_depot)
        if missing_codes:
            master_only[depot_key] = missing_codes

    if master_only:
        warnings.append(
            "master-only route codes detected and excluded because CSV is authoritative: "
            + "; ".join(f"{depot}={','.join(codes)}" for depot, codes in master_only.items())
        )

    resolved = csv_route_codes
    if requested_set:
        unknown_requested = sorted(requested_set - set(csv_route_codes))
        if unknown_requested:
            warnings.append(
                "requested route codes were ignored because they are outside selected depots: "
                + ",".join(unknown_requested)
            )
        resolved = [code for code in csv_route_codes if code in requested_set]

    return resolved, warnings


def selection_signature(selected_depots: list[str], selected_route_codes: list[str]) -> str:
    payload = {
        "depots": sorted(depot_key_from_id(value) for value in selected_depots),
        "route_codes": sorted(normalize_route_code(code) for code in selected_route_codes if normalize_route_code(code)),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _cache_path(resource: str, extra: str = "") -> Path:
    key = re.sub(r"[^a-zA-Z0-9_]", "_", resource + extra)[:180]
    return CACHE_DIR / f"{key}.json"


def odpt_fetch(resource: str, params: dict[str, Any], api_key: str, use_cache: bool = True) -> list[dict[str, Any]]:
    request_params = dict(params)
    request_params["acl:consumerKey"] = api_key
    url = f"{ODPT_BASE}/{resource}?{urlencode(request_params)}"
    extra = urlencode({key: value for key, value in request_params.items() if key != "acl:consumerKey"})
    cache_path = _cache_path(resource, extra)

    if use_cache and cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        log(f"  [cache] {resource} extra={extra[:72]} -> {len(data)}")
        return data

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "master-course-tokyu-subset-builder/1.0",
                },
            )
            with urlopen(request, timeout=90) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                data = [data]
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(THROTTLE_SEC)
            log(f"  [fetch] {resource} extra={extra[:72]} -> {len(data)}")
            return data
        except HTTPError as exc:
            if exc.code == 429:
                wait = RETRY_WAIT * attempt
                log(f"  [429] wait {wait}s attempt={attempt}")
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504):
                log(f"  [HTTP {exc.code}] retry attempt={attempt}")
                time.sleep(RETRY_WAIT)
                continue
            log(f"  [HTTP {exc.code}] {exc.reason}")
            return []
        except (URLError, TimeoutError) as exc:
            log(f"  [network] {exc} attempt={attempt}")
            time.sleep(RETRY_WAIT * attempt)
        except json.JSONDecodeError as exc:
            log(f"  [json] {exc}")
            return []

    log(f"  [give up] {resource} extra={extra[:72]}")
    return []


def init_db(path: Path, recreate: bool) -> sqlite3.Connection:
    if recreate and path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def is_done(conn: sqlite3.Connection, resource: str, key: str) -> bool:
    row = conn.execute(
        "SELECT status FROM fetch_progress WHERE resource=? AND key=?",
        (resource, key),
    ).fetchone()
    return row is not None and str(row[0]) == "done"


def mark_done(conn: sqlite3.Connection, resource: str, key: str, count: int) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO fetch_progress (resource, key, status, count, updated_at)
        VALUES (?, ?, 'done', ?, ?)
        """,
        (resource, key, count, now_iso()),
    )
    conn.commit()


def insert_operator(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO operators (operator_id, title_ja, title_en)
        VALUES (?, ?, ?)
        """,
        (OPERATOR_ID, "東急バス株式会社", "Tokyu Bus Co., Ltd."),
    )
    conn.commit()


def ensure_resume_selection(conn: sqlite3.Connection, signature: str, resume: bool) -> None:
    row = conn.execute("SELECT value FROM pipeline_meta WHERE key='selection_signature'").fetchone()
    if row is None:
        return
    existing = str(row[0] or "")
    if existing != signature:
        message = (
            "Existing DB selection differs from requested selection. "
            "Use a different --out path or rebuild without --resume."
        )
        if resume:
            raise ValueError(message)
        conn.execute("DELETE FROM pipeline_meta WHERE key='selection_signature'")
        conn.commit()


def seed_selected_depots(conn: sqlite3.Connection, depot_master: dict[str, dict[str, Any]], selected_depots: list[str]) -> None:
    rows = []
    for depot_key in selected_depots:
        depot = depot_master[depot_key]
        rows.append(
            (
                canonical_depot_id(depot_key),
                OPERATOR_ID,
                depot_key,
                str(depot.get("name") or depot_key),
                str(depot.get("name") or depot_key),
                str(depot.get("address") or ""),
                str(depot.get("phone") or ""),
                str(depot.get("region") or ""),
                str(depot.get("route_map_pdf") or ""),
                str(depot.get("route_map_as_of") or ""),
                None,
                None,
                json.dumps(depot, ensure_ascii=False),
            )
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO depots
            (depot_id, operator_id, depot_key, title_ja, title_en, address, phone,
             region, route_map_pdf, route_map_as_of, lat, lon, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def seed_route_code_depots(
    conn: sqlite3.Connection,
    selected_route_codes: list[str],
    selected_depots: list[str],
    route_to_depots: dict[str, list[str]],
) -> None:
    selected_depot_set = set(selected_depots)
    rows = []
    for route_code in selected_route_codes:
        for depot_key in route_to_depots.get(route_code, []):
            if depot_key in selected_depot_set:
                rows.append((route_code, canonical_depot_id(depot_key), "authority_csv"))
    conn.executemany(
        """
        INSERT OR REPLACE INTO route_code_depots (route_code, depot_id, source)
        VALUES (?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def extract_title_route_code(title: str) -> str:
    normalized = normalize_text(title)
    if not normalized:
        return ""
    if "さんま" in normalized:
        return "さんまバス"
    if "トランセ" in normalized:
        return "トランセ"
    match = re.match(r"^([^\s（(【\[]+)", normalized)
    if match:
        return normalize_route_code(match.group(1))
    return normalized


def extract_pattern_route_code(pattern: dict[str, Any]) -> str:
    title = str(pattern.get("dc:title") or "")
    title_code = extract_title_route_code(title)
    if title_code and title_code not in {"直行", "空港", "循環"}:
        return title_code
    note = normalize_text(str(pattern.get("odpt:note") or ""))
    if "さんま" in note:
        return "さんまバス"
    if "トランセ" in note:
        return "トランセ"
    return title_code


def insert_patterns_subset(
    conn: sqlite3.Connection,
    patterns: list[dict[str, Any]],
    selected_route_codes: list[str],
    route_to_depots: dict[str, list[str]],
    selected_depots: list[str],
) -> dict[str, str]:
    selected_codes = set(selected_route_codes)
    selected_depot_set = set(selected_depots)
    pattern_rows = []
    pattern_depot_rows = []
    pattern_stop_rows = []
    pattern_to_family: dict[str, str] = {}

    for pattern in patterns:
        route_code = extract_pattern_route_code(pattern)
        if route_code not in selected_codes:
            continue
        pattern_id = str(pattern.get("owl:sameAs") or pattern.get("@id") or "")
        if not pattern_id:
            continue
        depot_keys = [
            depot_key
            for depot_key in route_to_depots.get(route_code, [])
            if depot_key in selected_depot_set
        ]
        if not depot_keys:
            continue

        stop_order = pattern.get("odpt:busstopPoleOrder", []) or []
        origin_stop = str(stop_order[0].get("odpt:busstopPole") or "") if stop_order else ""
        dest_stop = str(stop_order[-1].get("odpt:busstopPole") or "") if stop_order else ""
        primary_depot = canonical_depot_id(sorted(depot_keys)[0])

        pattern_rows.append(
            (
                pattern_id,
                OPERATOR_ID,
                route_code,
                route_code,
                str(pattern.get("dc:title") or route_code),
                str(pattern.get("odpt:kana") or ""),
                str(pattern.get("odpt:direction") or ""),
                str(pattern.get("odpt:viaStopTitle") or pattern.get("odpt:via") or ""),
                origin_stop,
                dest_stop,
                len(stop_order),
                primary_depot,
                json.dumps(pattern, ensure_ascii=False),
            )
        )
        pattern_to_family[pattern_id] = route_code

        for depot_key in sorted(depot_keys):
            pattern_depot_rows.append((pattern_id, canonical_depot_id(depot_key), "authority_csv"))

        for index, stop in enumerate(stop_order, start=1):
            stop_id = str(stop.get("odpt:busstopPole") or "")
            if stop_id:
                pattern_stop_rows.append((pattern_id, index, stop_id))

    conn.executemany(
        """
        INSERT OR REPLACE INTO route_patterns
            (pattern_id, operator_id, route_family, route_code, title_ja, title_kana,
             direction, via, origin_stop_id, dest_stop_id, stop_count, depot_id, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        pattern_rows,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO route_pattern_depots (pattern_id, depot_id, source)
        VALUES (?, ?, ?)
        """,
        pattern_depot_rows,
    )
    conn.executemany(
        """
        INSERT OR IGNORE INTO pattern_stops (pattern_id, seq, stop_id)
        VALUES (?, ?, ?)
        """,
        pattern_stop_rows,
    )
    conn.commit()
    return pattern_to_family


def rebuild_route_families(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT route_family, operator_id, route_code, MIN(title_ja) AS title_ja,
               COUNT(*) AS pattern_count
        FROM route_patterns
        GROUP BY route_family, operator_id, route_code
        ORDER BY route_family
        """
    ).fetchall()
    conn.execute("DELETE FROM route_families")
    conn.execute("DELETE FROM route_family_depots")

    family_rows = []
    family_depot_rows = []
    for row in rows:
        depot_rows = conn.execute(
            """
            SELECT DISTINCT rpd.depot_id
            FROM route_pattern_depots rpd
            INNER JOIN route_patterns rp ON rp.pattern_id = rpd.pattern_id
            WHERE rp.route_family=?
            ORDER BY rpd.depot_id
            """,
            (row["route_family"],),
        ).fetchall()
        depot_ids = [str(item[0]) for item in depot_rows]
        primary_depot = depot_ids[0] if depot_ids else None
        family_rows.append(
            (
                str(row["route_family"]),
                str(row["operator_id"]),
                str(row["route_code"]),
                str(row["title_ja"] or row["route_family"]),
                int(row["pattern_count"] or 0),
                primary_depot,
            )
        )
        for depot_id in depot_ids:
            family_depot_rows.append((str(row["route_family"]), str(row["operator_id"]), depot_id, "authority_csv"))

    conn.executemany(
        """
        INSERT OR REPLACE INTO route_families
            (route_family, operator_id, route_code, title_ja, pattern_count, depot_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        family_rows,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO route_family_depots (route_family, operator_id, depot_id, source)
        VALUES (?, ?, ?, ?)
        """,
        family_depot_rows,
    )
    conn.commit()


def calendar_label(raw: str) -> str:
    text = normalize_text(raw).lower()
    if "sat" in text or "土" in text:
        return "土曜"
    if "sun" in text or "hol" in text or "日" in text or "祝" in text:
        return "日祝"
    return "平日"


def insert_timetable(conn: sqlite3.Connection, tt_obj: dict[str, Any], pattern_to_family: dict[str, str]) -> tuple[int, set[str]]:
    tt_id = str(tt_obj.get("owl:sameAs") or tt_obj.get("@id") or "")
    pattern_id = str(tt_obj.get("odpt:busroutePattern") or "")
    family = pattern_to_family.get(pattern_id)
    if not tt_id or not pattern_id or not family:
        return 0, set()

    calendar_type = calendar_label(str(tt_obj.get("odpt:calendar") or ""))
    direction = str(tt_obj.get("odpt:direction") or "")
    objects = tt_obj.get("odpt:busTimetableObject", []) or []
    stop_ids: set[str] = set()

    unique_stops = {
        str(obj.get("odpt:busstopPole") or "")
        for obj in objects
        if str(obj.get("odpt:busstopPole") or "")
    }

    trip_rows = []
    stop_rows = []
    if len(unique_stops) > 1:
        dep_min_effective: int | None = None
        arr_min_effective: int | None = None
        last_effective: int | None = None
        first_obj = objects[0] if objects else {}
        last_obj = objects[-1] if objects else {}
        for seq, obj in enumerate(objects, start=1):
            stop_id = str(obj.get("odpt:busstopPole") or "")
            dep_hhmm = str(obj.get("odpt:departureTime") or "")
            arr_hhmm = str(obj.get("odpt:arrivalTime") or dep_hhmm)
            raw_dep = hhmm_to_min(dep_hhmm)
            raw_arr = hhmm_to_min(arr_hhmm) if arr_hhmm else raw_dep
            effective_dep = roll_forward(raw_dep, last_effective)
            effective_arr = roll_forward(raw_arr, effective_dep if effective_dep is not None else last_effective)
            reference = effective_arr if effective_arr is not None else effective_dep
            if reference is not None:
                last_effective = reference
            if dep_min_effective is None:
                dep_min_effective = effective_dep if effective_dep is not None else effective_arr
            arr_min_effective = effective_arr if effective_arr is not None else effective_dep
            stop_rows.append((f"{tt_id}::0", seq, stop_id, dep_hhmm, arr_hhmm, effective_dep, effective_arr))
            if stop_id:
                stop_ids.add(stop_id)

        trip_rows.append(
            (
                f"{tt_id}::0",
                tt_id,
                pattern_id,
                family,
                calendar_type,
                direction,
                str(first_obj.get("odpt:busstopPole") or ""),
                str(last_obj.get("odpt:busstopPole") or ""),
                str(first_obj.get("odpt:departureTime") or first_obj.get("odpt:arrivalTime") or ""),
                str(last_obj.get("odpt:arrivalTime") or last_obj.get("odpt:departureTime") or ""),
                dep_min_effective,
                arr_min_effective,
                (arr_min_effective - dep_min_effective)
                if dep_min_effective is not None and arr_min_effective is not None
                else None,
                len(objects),
                0,
            )
        )
    else:
        for index, obj in enumerate(objects):
            stop_id = str(obj.get("odpt:busstopPole") or "")
            dep_hhmm = str(obj.get("odpt:departureTime") or obj.get("odpt:arrivalTime") or "")
            arr_hhmm = str(obj.get("odpt:arrivalTime") or dep_hhmm)
            dep_min = hhmm_to_min(dep_hhmm)
            arr_min = hhmm_to_min(arr_hhmm)
            if dep_min is not None and arr_min is not None and arr_min < dep_min:
                arr_min += 1440
            trip_rows.append(
                (
                    f"{tt_id}::{index}",
                    tt_id,
                    pattern_id,
                    family,
                    calendar_type,
                    direction,
                    stop_id,
                    stop_id,
                    dep_hhmm,
                    arr_hhmm,
                    dep_min,
                    arr_min,
                    (arr_min - dep_min) if dep_min is not None and arr_min is not None else 0,
                    1,
                    0,
                )
            )
            if stop_id:
                stop_ids.add(stop_id)

    if trip_rows:
        conn.executemany(
            """
            INSERT OR REPLACE INTO timetable_trips
                (trip_id, timetable_id, pattern_id, route_family, calendar_type, direction,
                 origin_stop_id, dest_stop_id, departure_hhmm, arrival_hhmm,
                 dep_min, arr_min, duration_min, stop_count, is_nonstop)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trip_rows,
        )
    if stop_rows:
        conn.executemany(
            """
            INSERT OR REPLACE INTO trip_stops
                (trip_id, seq, stop_id, departure_hhmm, arrival_hhmm, dep_min, arr_min)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            stop_rows,
        )
    return len(trip_rows), stop_ids


def insert_stops(conn: sqlite3.Connection, stops: list[dict[str, Any]], selected_stop_ids: set[str]) -> int:
    rows = []
    for stop in stops:
        stop_id = str(stop.get("owl:sameAs") or stop.get("@id") or "")
        if not stop_id or stop_id not in selected_stop_ids:
            continue
        rows.append(
            (
                stop_id,
                OPERATOR_ID,
                str(stop.get("dc:title") or ""),
                str(stop.get("odpt:kana") or ""),
                stop.get("geo:lat"),
                stop.get("geo:long"),
                str(stop.get("odpt:platformNumber") or ""),
                json.dumps(stop, ensure_ascii=False),
            )
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO stops
            (stop_id, operator_id, title_ja, title_kana, lat, lon, platform_num, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def insert_stop_timetable(conn: sqlite3.Connection, stt_obj: dict[str, Any]) -> int:
    stop_id = str(stt_obj.get("odpt:busstopPole") or "")
    pattern_id = str(stt_obj.get("odpt:busroutePattern") or "")
    calendar_type = calendar_label(str(stt_obj.get("odpt:calendar") or ""))
    direction = str(stt_obj.get("odpt:direction") or "")
    objects = stt_obj.get("odpt:busstopPoleTimetableObject", []) or []
    rows = []
    for obj in objects:
        departure_hhmm = str(obj.get("odpt:departureTime") or "")
        rows.append(
            (
                stop_id,
                pattern_id,
                calendar_type,
                direction,
                departure_hhmm,
                hhmm_to_min(departure_hhmm),
                str(obj.get("odpt:note") or ""),
            )
        )
    if rows:
        conn.executemany(
            """
            INSERT INTO stop_timetables
                (stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def print_summary(
    conn: sqlite3.Connection,
    selected_depots: list[str],
    selected_route_codes: list[str],
    missing_route_codes: list[str],
    zero_trip_route_codes: list[str],
) -> None:
    print()
    print("=" * 72)
    print("  Tokyu subset SQLite build summary")
    print("=" * 72)
    print(f"  selected_depots     : {', '.join(selected_depots)}")
    print(f"  selected_route_codes: {', '.join(selected_route_codes)}")
    if missing_route_codes:
        print(f"  no_pattern_routes   : {', '.join(missing_route_codes)}")
    if zero_trip_route_codes:
        print(f"  zero_trip_routes    : {', '.join(zero_trip_route_codes)}")
    for table_name in (
        "depots",
        "route_families",
        "route_patterns",
        "stops",
        "timetable_trips",
        "trip_stops",
        "stop_timetables",
    ):
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"  {table_name:18s}: {count:>8,}")
    print("=" * 72)


def write_pipeline_meta(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    selected_depots: list[str],
    selected_route_codes: list[str],
    warnings: list[str],
    missing_route_codes: list[str],
    zero_trip_route_codes: list[str],
) -> None:
    meta_rows = [
        ("built_at", now_iso()),
        ("operator_id", OPERATOR_ID),
        ("build_mode", "subset"),
        ("selected_depots", json.dumps(selected_depots, ensure_ascii=False)),
        ("selected_route_codes", json.dumps(selected_route_codes, ensure_ascii=False)),
        ("skip_stop_timetables", str(args.skip_stop_timetables)),
        ("resume_enabled", str(args.resume)),
        ("cache_dir", str(CACHE_DIR.resolve())),
        ("source", "remote_api_with_local_cache"),
        ("schema_version", "2.0-subset"),
        ("selection_signature", selection_signature(selected_depots, selected_route_codes)),
        ("warnings", json.dumps(warnings, ensure_ascii=False)),
        ("missing_route_codes", json.dumps(missing_route_codes, ensure_ascii=False)),
        ("zero_trip_route_codes", json.dumps(zero_trip_route_codes, ensure_ascii=False)),
        ("default_distance_km", str(DEFAULT_DISTANCE_KM)),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO pipeline_meta (key, value) VALUES (?, ?)",
        meta_rows,
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Tokyu Bus depot-scoped subset SQLite catalog.")
    parser.add_argument("--api-key", required=True, help="ODPT API key")
    parser.add_argument(
        "--depots",
        default=",".join(SELECTED_DEPOTS),
        help="comma-separated depot keys. Default comes from scripts/tokyu_subset_config.py",
    )
    parser.add_argument(
        "--route-codes",
        default=",".join(SELECTED_ROUTE_CODES),
        help="optional comma-separated route codes. Empty means all selected depot routes.",
    )
    parser.add_argument("--skip-stop-timetables", action="store_true", help="Skip BusstopPoleTimetable fetch")
    parser.add_argument("--resume", action="store_true", help="Resume an existing build for the same selection")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"output SQLite path (default: {DEFAULT_OUT})")
    parser.add_argument("--no-cache", action="store_true", help="Disable local ODPT response cache")
    args = parser.parse_args()

    selected_depots = [depot_key_from_id(value) for value in args.depots.split(",") if depot_key_from_id(value)]
    requested_route_codes = [normalize_route_code(value) for value in args.route_codes.split(",") if normalize_route_code(value)]
    db_path = Path(args.out)
    use_cache = not args.no_cache

    depot_master = load_depot_master()
    route_to_depots, _ = load_route_to_depot_map()
    selected_route_codes, selection_warnings = resolve_selected_route_codes(
        selected_depots,
        requested_route_codes,
        depot_master,
        route_to_depots,
    )
    if not selected_route_codes:
        raise ValueError("No route codes resolved for the requested depot selection.")

    log(f"output db: {db_path}")
    log(f"selected depots: {', '.join(selected_depots)}")
    log(f"resolved route codes: {', '.join(selected_route_codes)}")

    conn = init_db(db_path, recreate=not args.resume)
    insert_operator(conn)
    ensure_resume_selection(conn, selection_signature(selected_depots, selected_route_codes), args.resume)
    seed_selected_depots(conn, depot_master, selected_depots)
    seed_route_code_depots(conn, selected_route_codes, selected_depots, route_to_depots)

    if not is_done(conn, "BusroutePattern", "selected"):
        patterns = odpt_fetch("odpt:BusroutePattern", {"odpt:operator": OPERATOR_ID}, args.api_key, use_cache)
        pattern_to_family = insert_patterns_subset(
            conn,
            patterns,
            selected_route_codes,
            route_to_depots,
            selected_depots,
        )
        rebuild_route_families(conn)
        mark_done(conn, "BusroutePattern", "selected", len(pattern_to_family))
    else:
        rows = conn.execute("SELECT pattern_id, route_family FROM route_patterns").fetchall()
        pattern_to_family = {str(row["pattern_id"]): str(row["route_family"]) for row in rows}

    if not pattern_to_family:
        raise RuntimeError("No route patterns matched the selected depot/route configuration.")

    selected_pattern_ids = sorted(pattern_to_family)
    log(f"selected patterns: {len(selected_pattern_ids)}")

    all_stop_ids: set[str] = set(
        str(row[0]) for row in conn.execute("SELECT DISTINCT stop_id FROM pattern_stops").fetchall() if str(row[0] or "")
    )
    for index, pattern_id in enumerate(selected_pattern_ids, start=1):
        if is_done(conn, "BusTimetable", pattern_id):
            continue
        log(f"  timetable [{index}/{len(selected_pattern_ids)}] {pattern_id}")
        timetable_objects = odpt_fetch(
            "odpt:BusTimetable",
            {"odpt:busroutePattern": pattern_id},
            args.api_key,
            use_cache,
        )
        trip_count_for_pattern = 0
        for timetable in timetable_objects:
            inserted, stop_ids = insert_timetable(conn, timetable, pattern_to_family)
            trip_count_for_pattern += inserted
            all_stop_ids.update(stop_ids)
        conn.commit()
        mark_done(conn, "BusTimetable", pattern_id, trip_count_for_pattern)

    if not is_done(conn, "BusstopPole", "selected"):
        stop_objects = odpt_fetch("odpt:BusstopPole", {"odpt:operator": OPERATOR_ID}, args.api_key, use_cache)
        inserted_stops = insert_stops(conn, stop_objects, all_stop_ids)
        mark_done(conn, "BusstopPole", "selected", inserted_stops)

    if args.skip_stop_timetables:
        log("skip stop_timetables phase")
    else:
        for index, pattern_id in enumerate(selected_pattern_ids, start=1):
            if is_done(conn, "BusstopPoleTimetable", pattern_id):
                continue
            log(f"  stop_timetable [{index}/{len(selected_pattern_ids)}] {pattern_id}")
            stop_timetable_objects = odpt_fetch(
                "odpt:BusstopPoleTimetable",
                {"odpt:busroutePattern": pattern_id},
                args.api_key,
                use_cache,
            )
            inserted_entries = 0
            for stop_timetable in stop_timetable_objects:
                inserted_entries += insert_stop_timetable(conn, stop_timetable)
            conn.commit()
            mark_done(conn, "BusstopPoleTimetable", pattern_id, inserted_entries)

    missing_route_codes = sorted(set(selected_route_codes) - set(pattern_to_family.values()))
    trip_rows = conn.execute(
        """
        SELECT route_family, COUNT(*) AS trip_count
        FROM timetable_trips
        GROUP BY route_family
        """
    ).fetchall()
    trip_count_by_family = {str(row["route_family"]): int(row["trip_count"] or 0) for row in trip_rows}
    zero_trip_route_codes = sorted(
        route_code for route_code in selected_route_codes if trip_count_by_family.get(route_code, 0) == 0
    )
    if zero_trip_route_codes:
        log("zero-trip routes: " + ", ".join(zero_trip_route_codes))

    write_pipeline_meta(
        conn,
        args,
        selected_depots,
        selected_route_codes,
        selection_warnings,
        missing_route_codes,
        zero_trip_route_codes,
    )

    print_summary(conn, selected_depots, selected_route_codes, missing_route_codes, zero_trip_route_codes)
    conn.close()
    log(f"done: {db_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
