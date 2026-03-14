"""
scripts/extract_meguro_small_case.py

tokyu_core_gtfs.sqlite から 黒01 平日ダイヤを抽出して
data/cases/meguro_small/ 配下の CSV 群を生成する。

使い方:
    python scripts/extract_meguro_small_case.py [--db data/tokyu_core_gtfs.sqlite]
                                                 [--out data/cases/meguro_small]
                                                 [--route 黒01]
                                                 [--time-step-min 15]
                                                 [--start-hour 5]
                                                 [--end-hour 25]
                                                 [--bev-count 3]
                                                 [--charger-count 2]
                                                 [--charger-kw 90]
                                                 [--energy-kwh-per-km 1.2]
                                                 [--battery-kwh 300]
                                                 [--exclude-depot-runs]

注意:
  - ODPT データでは 同じ系統番号に本線・区間便・入出庫便が混在する。
  - --exclude-depot-runs フラグを付けると title_ja に「営業所」「操車所」を
    含むパターンの便を除外する（入出庫専用便フィルタ）。
  - direction フィールドは全件 'unknown' のため使用不可。
  - パターン識別は title_ja と stop_count で行う。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from pathlib import Path


_DEPOT_STOP_KEYWORDS = ("営業所", "操車所")

_MEGURO_DEPOT_LAT = 35.628292
_MEGURO_DEPOT_LON = 139.694458
_MEGURO_DEPOT_ID  = "meguro_depot"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の大圏距離 [km]"""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_depot_run(title_ja: str) -> bool:
    return any(kw in (title_ja or "") for kw in _DEPOT_STOP_KEYWORDS)


def hhmm_to_min(hhmm: str) -> int:
    """'HHMM' または 'HH:MM' を分に変換。25:xx など翌日跨ぎも対応。"""
    hhmm = str(hhmm or "").strip().replace(":", "")
    if len(hhmm) < 3:
        return 0
    h, m = int(hhmm[:-2]), int(hhmm[-2:])
    return h * 60 + m


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract GTFS trips to case CSVs")
    parser.add_argument("--db",                default="data/tokyu_core_gtfs.sqlite")
    parser.add_argument("--out",               default="data/cases/meguro_small")
    parser.add_argument("--route",             default="黒01")
    parser.add_argument("--time-step-min",     type=int, default=15)
    parser.add_argument("--start-hour",        type=int, default=5,   help="計画開始時刻 (時)")
    parser.add_argument("--end-hour",          type=int, default=25,  help="計画終了時刻 (時、25=翌1時)")
    parser.add_argument("--bev-count",         type=int, default=3)
    parser.add_argument("--charger-count",     type=int, default=2)
    parser.add_argument("--charger-kw",        type=float, default=90.0)
    parser.add_argument("--energy-kwh-per-km", type=float, default=1.2)
    parser.add_argument("--battery-kwh",       type=float, default=300.0)
    parser.add_argument("--urban-detour-factor", type=float, default=1.3,
                        help="直線距離→実走行距離の係数 (市街地は 1.3 推奨)")
    parser.add_argument("--exclude-depot-runs", action="store_true",
                        help="営業所/操車所を含むパターンの便を除外")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    cur  = conn.cursor()

    # ── 1. 対象パターンを取得 ──────────────────────────────────────────────
    cur.execute("""
        SELECT rp.pattern_id, rp.title_ja, rp.stop_count,
               rp.origin_stop_id, rp.dest_stop_id,
               s1.title_ja AS orig_name, s2.title_ja AS dest_name,
               s1.lat AS orig_lat, s1.lon AS orig_lon,
               s2.lat AS dest_lat, s2.lon AS dest_lon
        FROM route_patterns rp
        LEFT JOIN stops s1 ON rp.origin_stop_id = s1.stop_id
        LEFT JOIN stops s2 ON rp.dest_stop_id   = s2.stop_id
        WHERE rp.route_code = ?
        ORDER BY rp.stop_count
    """, (args.route,))
    patterns = {r[0]: dict(zip(
        ["pattern_id","title_ja","stop_count",
         "origin_stop_id","dest_stop_id",
         "orig_name","dest_name",
         "orig_lat","orig_lon","dest_lat","dest_lon"], r))
        for r in cur.fetchall()}

    if not patterns:
        print(f"[ERROR] route_code={args.route!r} が DB に見つかりません", file=sys.stderr)
        conn.close(); return

    # ── 2. 平日トリップを取得 ──────────────────────────────────────────────
    cur.execute("""
        SELECT tt.trip_id, tt.pattern_id, tt.calendar_type,
               tt.departure_hhmm, tt.arrival_hhmm,
               tt.dep_min, tt.arr_min, tt.duration_min, tt.stop_count
        FROM timetable_trips tt
        WHERE tt.pattern_id IN ({})
          AND tt.calendar_type LIKE '%平日%'
        ORDER BY tt.dep_min
    """.format(",".join("?" * len(patterns))), list(patterns.keys()))
    trips_raw = cur.fetchall()
    conn.close()

    trip_cols = ["trip_id","pattern_id","calendar_type",
                 "departure_hhmm","arrival_hhmm",
                 "dep_min","arr_min","duration_min","stop_count"]
    trips_raw = [dict(zip(trip_cols, r)) for r in trips_raw]

    start_min = args.start_hour * 60
    end_min   = args.end_hour   * 60
    step      = args.time_step_min
    num_periods = (end_min - start_min) // step

    # ── 3. タスク生成 ─────────────────────────────────────────────────────
    tasks = []
    excluded = []
    for t in trips_raw:
        pat = patterns.get(t["pattern_id"], {})
        if args.exclude_depot_runs and is_depot_run(pat.get("title_ja", "")):
            excluded.append(t["trip_id"])
            continue

        dep_min = int(t["dep_min"] or 0)
        arr_min = int(t["arr_min"] or dep_min + int(t["duration_min"] or 0))

        # 計画ウィンドウ外は除外
        if dep_min < start_min or arr_min > end_min:
            continue

        start_idx = (dep_min - start_min) // step
        end_idx   = (arr_min - start_min) // step
        if end_idx <= start_idx:
            end_idx = start_idx + 1  # 最低1スロット

        # 直線距離 → 推定走行距離
        orig_lat = pat.get("orig_lat") or _MEGURO_DEPOT_LAT
        orig_lon = pat.get("orig_lon") or _MEGURO_DEPOT_LON
        dest_lat = pat.get("dest_lat") or _MEGURO_DEPOT_LAT
        dest_lon = pat.get("dest_lon") or _MEGURO_DEPOT_LON
        straight_km  = haversine_km(orig_lat, orig_lon, dest_lat, dest_lon)
        distance_km  = round(straight_km * args.urban_detour_factor, 3)
        energy_kwh   = round(distance_km * args.energy_kwh_per_km, 3)
        fuel_liter   = round(distance_km * 0.4, 3)

        orig_id = (pat.get("orig_name") or "unknown").replace(" ", "_")
        dest_id = (pat.get("dest_name") or "unknown").replace(" ", "_")

        tasks.append({
            "task_id":                  f"T_{t['trip_id'][-12:]}",
            "start_time_idx":           start_idx,
            "end_time_idx":             end_idx,
            "origin":                   orig_id,
            "destination":              dest_id,
            "distance_km":              distance_km,
            "energy_required_kwh_bev":  energy_kwh,
            "fuel_required_liter_ice":  fuel_liter,
            "required_vehicle_type":    "",
            "demand_cover":             True,
            "penalty_unserved":         10000.0,
            "_pattern_title":           pat.get("title_ja", ""),
            "_dep_hhmm":                t["departure_hhmm"],
            "_arr_hhmm":                t["arrival_hhmm"],
        })

    print(f"[extract] route={args.route} | 平日トリップ={len(trips_raw)} | "
          f"除外(入出庫)={len(excluded)} | 計画ウィンドウ内タスク={len(tasks)}")
    print(f"[extract] start_hour={args.start_hour}, end_hour={args.end_hour}, "
          f"num_periods={num_periods}, time_step={step}min")
    print(f"[extract] パターン内訳:")
    from collections import Counter
    pat_counts = Counter(t["_pattern_title"] for t in tasks)
    for title, cnt in sorted(pat_counts.items(), key=lambda x: -x[1]):
        print(f"  {title}: {cnt}本")

    if args.dry_run:
        print("[dry-run] ファイル書き出しをスキップしました。")
        return

    # ── 4. tasks.csv ──────────────────────────────────────────────────────
    task_fields = ["task_id","start_time_idx","end_time_idx","origin","destination",
                   "distance_km","energy_required_kwh_bev","fuel_required_liter_ice",
                   "required_vehicle_type","demand_cover","penalty_unserved"]
    _write_csv(out_dir / "tasks.csv", task_fields,
               [{k: t[k] for k in task_fields} for t in tasks])

    # ── 5. vehicles.csv ───────────────────────────────────────────────────
    soc_init = round(args.battery_kwh * 0.90, 1)
    soc_min  = round(args.battery_kwh * 0.15, 1)
    vehicle_rows = [
        {
            "vehicle_id": f"BEV_{i+1:02d}",
            "vehicle_type": "BEV",
            "home_depot": _MEGURO_DEPOT_ID,
            "battery_capacity": args.battery_kwh,
            "soc_init": soc_init,
            "soc_min": soc_min,
            "soc_max": args.battery_kwh,
            "soc_target_end": soc_min,
            "charge_power_max": args.charger_kw,
            "discharge_power_max": "",
            "fixed_use_cost": 5000.0,
            "max_operating_time": 20.0,
            "max_distance": 9999.0,
            "charge_efficiency": 0.95,
            "fuel_tank_capacity": "",
            "fuel_cost_coeff": "",
            "co2_emission_coeff": "",
        }
        for i in range(args.bev_count)
    ]
    veh_fields = ["vehicle_id","vehicle_type","home_depot","battery_capacity",
                  "soc_init","soc_min","soc_max","soc_target_end","charge_power_max",
                  "discharge_power_max","fixed_use_cost","max_operating_time",
                  "max_distance","charge_efficiency","fuel_tank_capacity",
                  "fuel_cost_coeff","co2_emission_coeff"]
    _write_csv(out_dir / "vehicles.csv", veh_fields, vehicle_rows)

    # ── 6. chargers.csv ───────────────────────────────────────────────────
    charger_rows = [
        {"charger_id": f"CHG_{i+1:02d}", "site_id": _MEGURO_DEPOT_ID,
         "power_max_kw": args.charger_kw, "efficiency": 0.95, "power_min_kw": 0.0}
        for i in range(args.charger_count)
    ]
    _write_csv(out_dir / "chargers.csv",
               ["charger_id","site_id","power_max_kw","efficiency","power_min_kw"],
               charger_rows)

    # ── 7. sites.csv ──────────────────────────────────────────────────────
    all_stops = sorted({t["origin"] for t in tasks} | {t["destination"] for t in tasks})
    site_rows = [{"site_id": _MEGURO_DEPOT_ID, "site_type": "depot",
                  "grid_import_limit_kw": 500.0,
                  "contract_demand_limit_kw": 500.0,
                  "site_transformer_limit_kw": 500.0}]
    for s in all_stops:
        if s != _MEGURO_DEPOT_ID:
            site_rows.append({"site_id": s, "site_type": "terminal",
                               "grid_import_limit_kw": 9999.0,
                               "contract_demand_limit_kw": 9999.0,
                               "site_transformer_limit_kw": 9999.0})
    _write_csv(out_dir / "sites.csv",
               ["site_id","site_type","grid_import_limit_kw",
                "contract_demand_limit_kw","site_transformer_limit_kw"],
               site_rows)

    # ── 8. electricity_price.csv (TOU 電気料金) ───────────────────────────
    # [夜間 0-8h: 15円, 昼間 8-13h: 30円, ピーク 13-16h: 40円, 昼間 16-22h: 30円, 夜間 22-24h: 15円]
    _TOU = [
        (0,   8,  15.0),
        (8,  13,  30.0),
        (13, 16,  40.0),
        (16, 22,  30.0),
        (22, 24,  15.0),
        (24, 25,  15.0),  # 翌日早朝
    ]

    def _tou_rate(absolute_min: int) -> float:
        h = (absolute_min % (24 * 60)) // 60
        for start_h, end_h, rate in _TOU:
            if start_h <= h < end_h:
                return rate
        return 15.0

    price_rows = []
    for idx in range(num_periods):
        abs_min = start_min + idx * step
        price_rows.append({
            "site_id": _MEGURO_DEPOT_ID,
            "time_idx": idx,
            "grid_energy_price": _tou_rate(abs_min),
            "sell_back_price": 0.0,
            "base_load_kw": 0.0,
        })
    _write_csv(out_dir / "electricity_price.csv",
               ["site_id","time_idx","grid_energy_price","sell_back_price","base_load_kw"],
               price_rows)

    # ── 9. pv_profile.csv (PV なし) ─────────────────────────────────────
    pv_rows = [{"site_id": _MEGURO_DEPOT_ID, "time_idx": idx, "pv_generation_kw": 0.0}
               for idx in range(num_periods)]
    _write_csv(out_dir / "pv_profile.csv",
               ["site_id","time_idx","pv_generation_kw"], pv_rows)

    # ── 10. travel_connection.csv ─────────────────────────────────────────
    # 同一停留所で時間が接続できるタスクペアを列挙
    # 簡易版: 全タスクペアで dest==origin かつ end_idx <= start_idx を接続可能とする
    conn_rows = []
    for i, t1 in enumerate(tasks):
        for t2 in tasks:
            if t1["task_id"] == t2["task_id"]:
                continue
            if t1["destination"] == t2["origin"] and t1["end_time_idx"] <= t2["start_time_idx"]:
                conn_rows.append({
                    "from_task_id": t1["task_id"],
                    "to_task_id":   t2["task_id"],
                    "can_follow":   True,
                    "deadhead_time_slot": 0,
                    "deadhead_distance_km": 0.0,
                    "deadhead_energy_kwh": 0.0,
                })
    # 営業所 → 最初のタスクへの接続
    for t in tasks:
        conn_rows.append({
            "from_task_id": "DEPOT_START",
            "to_task_id":   t["task_id"],
            "can_follow":   True,
            "deadhead_time_slot": 0,
            "deadhead_distance_km": 0.0,
            "deadhead_energy_kwh": 0.0,
        })
    _write_csv(out_dir / "travel_connection.csv",
               ["from_task_id","to_task_id","can_follow",
                "deadhead_time_slot","deadhead_distance_km","deadhead_energy_kwh"],
               conn_rows)

    # ── 11. compatibility_vehicle_task.csv ────────────────────────────────
    compat_vt = [{"vehicle_id": v["vehicle_id"], "task_id": t["task_id"], "feasible": True}
                 for v in vehicle_rows for t in tasks]
    _write_csv(out_dir / "compatibility_vehicle_task.csv",
               ["vehicle_id","task_id","feasible"], compat_vt)

    # ── 12. compatibility_vehicle_charger.csv ─────────────────────────────
    compat_vc = [{"vehicle_id": v["vehicle_id"], "charger_id": c["charger_id"], "feasible": True}
                 for v in vehicle_rows for c in charger_rows]
    _write_csv(out_dir / "compatibility_vehicle_charger.csv",
               ["vehicle_id","charger_id","feasible"], compat_vc)

    # ── 13. fixed_assignment.json (空) ────────────────────────────────────
    (out_dir / "fixed_assignment.json").write_text(
        json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 14. metadata.json ─────────────────────────────────────────────────
    metadata = {
        "generated_by": "scripts/extract_meguro_small_case.py",
        "route": args.route,
        "db": args.db,
        "calendar": "平日",
        "exclude_depot_runs": args.exclude_depot_runs,
        "task_count": len(tasks),
        "excluded_depot_runs": len(excluded),
        "bev_count": args.bev_count,
        "charger_count": args.charger_count,
        "num_periods": num_periods,
        "time_step_min": step,
        "start_hour": args.start_hour,
        "end_hour": args.end_hour,
        "odpt_caveats": [
            "directionフィールドは全件'unknown'",
            "区間便・入出庫便が同一route_codeに混在",
            f"入出庫便除外フラグ: {args.exclude_depot_runs}",
            "距離は直線距離×detour係数で推定。実走行距離ではない",
        ],
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[extract] 出力先: {out_dir.resolve()}")
    print(f"  tasks.csv              : {len(tasks)} rows")
    print(f"  vehicles.csv           : {len(vehicle_rows)} rows")
    print(f"  chargers.csv           : {len(charger_rows)} rows")
    print(f"  sites.csv              : {len(site_rows)} rows")
    print(f"  electricity_price.csv  : {len(price_rows)} rows")
    print(f"  travel_connection.csv  : {len(conn_rows)} rows")
    print(f"  compat vehicle×task    : {len(compat_vt)} rows")
    print(f"  compat vehicle×charger : {len(compat_vc)} rows")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
