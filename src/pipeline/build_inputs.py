"""
src.pipeline.build_inputs — 入力データ構築パイプライン

route master を読み込み、trip を生成し、energy/fuel を推定して
derived データを書き出す。

Usage:
    python -m src.pipeline.build_inputs --config config/experiment_config.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional

from src.schemas.route_entities import (
    Route, Terminal, Stop, Segment, RouteVariant,
    TimetablePattern, ServiceCalendarRow, GeneratedTrip, DeadheadArc,
)
from src.schemas.fleet_entities import VehicleType, VehicleInstance
from src.preprocess.route_builder import validate_route_network, build_variant_segments
from src.preprocess.trip_generator import generate_all_trips
from src.preprocess.deadhead_builder import build_deadhead_arcs
from src.preprocess.duty_loader import load_vehicle_duties, validate_duties, build_duty_trip_mapping, identify_charging_opportunities
from src.preprocess.passenger_load import load_passenger_load_profile, build_load_factor_map, apply_load_factor_to_trips
from src.preprocess.tariff_loader import load_tariff_csv, build_electricity_prices_from_tariff


def _load_csv(path: Path) -> List[Dict[str, str]]:
    """CSV を辞書リストとして読む。"""
    if not path.exists():
        print(f"  [warn] {path} が存在しません。スキップ。")
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_float(v, default=None):
    try:
        return float(v) if v not in (None, "", "null") else default
    except (ValueError, TypeError):
        return default


def _parse_int(v, default=None):
    try:
        return int(v) if v not in (None, "", "null") else default
    except (ValueError, TypeError):
        return default


def _parse_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return default


# ---------------------------------------------------------------------------
# ローダー: route_master
# ---------------------------------------------------------------------------

def load_routes(data_dir: Path) -> List[Route]:
    rows = _load_csv(data_dir / "route_master" / "routes.csv")
    return [
        Route(
            route_id=r["route_id"],
            route_name=r.get("route_name", r["route_id"]),
            operator_id=r.get("operator_id", ""),
            mode=r.get("mode", "urban_bus"),
            route_type=r.get("route_type", "bidirectional"),
        )
        for r in rows
    ]


def load_terminals(data_dir: Path) -> List[Terminal]:
    rows = _load_csv(data_dir / "route_master" / "terminals.csv")
    return [
        Terminal(
            terminal_id=r["terminal_id"],
            terminal_name=r.get("terminal_name", r["terminal_id"]),
            lat=_parse_float(r.get("lat")),
            lon=_parse_float(r.get("lon")),
            is_depot=_parse_bool(r.get("is_depot", "false")),
            has_charger_site=_parse_bool(r.get("has_charger_site", "false")),
            charger_site_id=r.get("charger_site_id") or None,
        )
        for r in rows
    ]


def load_stops(data_dir: Path) -> List[Stop]:
    rows = _load_csv(data_dir / "route_master" / "stops.csv")
    return [
        Stop(
            stop_id=r["stop_id"],
            route_id=r["route_id"],
            direction_id=r.get("direction_id", "outbound"),
            stop_sequence=_parse_int(r.get("stop_sequence", "0"), 0),
            stop_name=r.get("stop_name", r["stop_id"]),
            elevation_m=_parse_float(r.get("elevation_m")),
            is_terminal=_parse_bool(r.get("is_terminal", "false")),
            dwell_time_mean_min=_parse_float(r.get("dwell_time_mean_min", "0.5"), 0.5),
        )
        for r in rows
    ]


def load_segments(data_dir: Path) -> List[Segment]:
    rows = _load_csv(data_dir / "route_master" / "segments.csv")
    segs = []
    for r in rows:
        seg = Segment(
            segment_id=r["segment_id"],
            route_id=r["route_id"],
            direction_id=r.get("direction_id", "outbound"),
            from_stop_id=r["from_stop_id"],
            to_stop_id=r["to_stop_id"],
            sequence=_parse_int(r.get("sequence", "0"), 0),
            distance_km=_parse_float(r.get("distance_km", "0"), 0.0),
            scheduled_run_time_min=_parse_float(r.get("scheduled_run_time_min", "0"), 0.0),
            grade_avg_pct=_parse_float(r.get("grade_avg_pct")),
            signal_count=_parse_int(r.get("signal_count")),
            traffic_level=_parse_float(r.get("traffic_level")),
            congestion_index=_parse_float(r.get("congestion_index")),
        )
        segs.append(seg)
    return segs


def load_route_variants(data_dir: Path) -> List[RouteVariant]:
    data = _load_json(data_dir / "route_master" / "route_variants.json")
    if not data:
        return []
    variants = []
    for item in data:
        variants.append(RouteVariant(
            variant_id=item["variant_id"],
            route_id=item["route_id"],
            direction_id=item.get("direction_id", "outbound"),
            variant_name=item.get("variant_name", item["variant_id"]),
            segment_id_list=item.get("segment_id_list", []),
            is_default=_parse_bool(item.get("is_default", True)),
        ))
    return variants


def load_timetable_patterns(data_dir: Path) -> List[TimetablePattern]:
    rows = _load_csv(data_dir / "route_master" / "timetable_patterns.csv")
    return [
        TimetablePattern(
            pattern_id=r["pattern_id"],
            route_id=r["route_id"],
            direction_id=r.get("direction_id", "outbound"),
            variant_id=r["variant_id"],
            service_day_type=r.get("service_day_type", "weekday"),
            start_time=r.get("start_time", "06:00"),
            end_time=r.get("end_time", "22:00"),
            headway_min=_parse_float(r.get("headway_min", "30"), 30.0),
            dispatch_rule=r.get("dispatch_rule", "fixed_headway"),
        )
        for r in rows
    ]


def load_vehicle_types(data_dir: Path) -> List[VehicleType]:
    rows = _load_csv(data_dir / "fleet" / "vehicle_types.csv")
    return [
        VehicleType(
            vehicle_type_id=r["vehicle_type_id"],
            powertrain=r.get("powertrain", "BEV"),
            battery_capacity_kwh=_parse_float(r.get("battery_capacity_kwh")),
            fuel_tank_l=_parse_float(r.get("fuel_tank_l")),
            base_energy_rate_kwh_per_km=_parse_float(r.get("base_energy_rate_kwh_per_km")),
            base_fuel_rate_l_per_km=_parse_float(r.get("base_fuel_rate_l_per_km")),
            charging_power_max_kw=_parse_float(r.get("charging_power_max_kw")),
            hvac_power_kw_cooling=_parse_float(r.get("hvac_power_kw_cooling")),
            hvac_power_kw_heating=_parse_float(r.get("hvac_power_kw_heating")),
            regen_efficiency=_parse_float(r.get("regen_efficiency", "0.0"), 0.0),
            charge_efficiency=_parse_float(r.get("charge_efficiency", "0.95"), 0.95),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# CSV 出力
# ---------------------------------------------------------------------------

def _write_generated_trips_csv(trips: List[GeneratedTrip], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trip_id", "route_id", "direction_id", "variant_id", "service_day_type",
        "departure_time", "arrival_time", "origin_terminal_id", "destination_terminal_id",
        "distance_km", "scheduled_runtime_min",
        "estimated_energy_kwh_bev", "estimated_fuel_l_ice",
        "estimated_energy_rate_kwh_per_km", "estimated_fuel_rate_l_per_km",
        "trip_category",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in trips:
            writer.writerow({k: getattr(t, k, "") for k in fields})
    print(f"  → {len(trips)} trips 書き出し: {out_path}")


def _write_deadhead_arcs_csv(arcs: List[DeadheadArc], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # feasible のみ書き出す
    feasible = [a for a in arcs if a.is_feasible_connection]
    fields = [
        "arc_id", "from_trip_id", "to_trip_id",
        "from_terminal_id", "to_terminal_id",
        "deadhead_time_min", "deadhead_distance_km",
        "deadhead_energy_kwh_bev", "deadhead_fuel_l_ice",
        "is_feasible_connection",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for a in feasible:
            writer.writerow({k: getattr(a, k, "") for k in fields})
    print(f"  → {len(feasible)} feasible arcs 書き出し: {out_path}")


# ---------------------------------------------------------------------------
# メインエントリポイント
# ---------------------------------------------------------------------------

def build_inputs(config_path: str = "config/experiment_config.json") -> dict:
    """
    全入力データを構築して derived/ に書き出す。

    Returns
    -------
    dict with 'trips', 'deadhead_arcs', 'errors'
    """
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"config が見つかりません: {cfg_path}")

    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    data_dir = Path(cfg.get("data_dir", "data/toy"))
    service_day = cfg.get("service_day_type", "weekday")
    energy_level = cfg.get("energy_model_level", 1)
    derived_dir = data_dir.parent / "derived"
    derived_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build_inputs] data_dir={data_dir}, mode={cfg.get('mode','?')}")

    # --- ロード ---
    routes = load_routes(data_dir)
    terminals = load_terminals(data_dir)
    stops = load_stops(data_dir)
    segments = load_segments(data_dir)
    variants = load_route_variants(data_dir)
    patterns = load_timetable_patterns(data_dir)
    vehicle_types = load_vehicle_types(data_dir)

    print(f"  routes={len(routes)}, terminals={len(terminals)}, stops={len(stops)}, "
          f"segments={len(segments)}, variants={len(variants)}, patterns={len(patterns)}")

    # --- 整合性検査 ---
    errors = validate_route_network(routes, stops, segments, variants, terminals)
    if errors:
        print(f"  [warn] {len(errors)} つの整合性エラー:")
        for e in errors[:10]:
            print(f"    {e}")

    # --- seg_index ---
    seg_index = {s.segment_id: s for s in segments}
    vt_index = {vt.vehicle_type_id: vt for vt in vehicle_types}

    # BEV の代表 VehicleType (最初の BEV)
    default_vt = next((vt for vt in vehicle_types if vt.powertrain == "BEV"), None)
    if default_vt is None and vehicle_types:
        default_vt = vehicle_types[0]

    # --- Trip 生成 ---
    trips = generate_all_trips(
        variants=variants,
        seg_index=seg_index,
        patterns=patterns,
        service_day_type=service_day,
        energy_model_level=energy_level,
        vehicle_type=default_vt,
    )
    print(f"  generated {len(trips)} trips")

    # --- Deadhead Arcs ---
    if cfg.get("allow_deadhead", True):
        arcs = build_deadhead_arcs(trips, terminals)
        feasible_count = sum(1 for a in arcs if a.is_feasible_connection)
        print(f"  deadhead arcs: {len(arcs)} total, {feasible_count} feasible")
    else:
        arcs = []

    # --- CSV 出力 ---
    _write_generated_trips_csv(trips, derived_dir / "generated_trips.csv")
    if arcs:
        _write_deadhead_arcs_csv(arcs, derived_dir / "deadhead_arcs.csv")

    # --- 行路データ読込 (spec_v3 §6) ---
    duty_cfg = cfg.get("duty_assignment", {})
    duties = []
    if duty_cfg.get("enabled", False):
        duties_csv = duty_cfg.get("duties_csv_path", "data/fleet/vehicle_duties.csv")
        legs_csv = duty_cfg.get("duty_legs_csv_path", "data/fleet/duty_legs.csv")
        try:
            duties = load_vehicle_duties(duties_csv, legs_csv)
            duty_errors = validate_duties(duties, {t.trip_id for t in trips})
            if duty_errors:
                print(f"  [warn] 行路整合性: {len(duty_errors)} 件")
                for e in duty_errors[:5]:
                    print(f"    {e}")
            # 充電機会の識別
            identify_charging_opportunities(duties)
            print(f"  duties loaded: {len(duties)}")
        except Exception as e:
            print(f"  [warn] 行路データ読込失敗: {e}")

    # --- 乗客負荷プロファイル (spec_v3 §7) ---
    load_cfg = cfg.get("passenger_load", {})
    load_factor_map = {}
    if load_cfg.get("enabled", False):
        load_csv_path = load_cfg.get("csv_path", "data/external/passenger_load_profile.csv")
        try:
            profiles = load_passenger_load_profile(load_csv_path)
            load_factor_map = build_load_factor_map(profiles)
            trips = apply_load_factor_to_trips(trips, load_factor_map,
                                                default_factor=load_cfg.get("default_load_factor", 0.5))
            print(f"  passenger load profiles: {len(profiles)} entries applied")
        except Exception as e:
            print(f"  [warn] 乗客負荷プロファイル読込失敗: {e}")

    # --- TOU 電力料金 (spec_v3 §9) ---
    tariff_cfg = cfg.get("tariff", {})
    tariff_prices = []
    if tariff_cfg.get("enabled", False):
        tariff_csv_path = tariff_cfg.get("csv_path", "data/external/tariff.csv")
        try:
            tariff_rows = load_tariff_csv(tariff_csv_path)
            tariff_prices = build_electricity_prices_from_tariff(
                tariff_rows,
                num_periods=cfg.get("num_periods", 64),
                delta_t_min=cfg.get("time_step_min", 15),
                start_time=cfg.get("start_time", "05:00"),
            )
            print(f"  TOU tariff loaded: {len(tariff_rows)} bands → {len(tariff_prices)} price slots")
        except Exception as e:
            print(f"  [warn] 電力料金データ読込失敗: {e}")

    print(f"[build_inputs] 完了")
    return {
        "trips": trips,
        "deadhead_arcs": arcs,
        "errors": errors,
        "duties": duties,
        "load_factor_map": load_factor_map,
        "tariff_prices": tariff_prices,
    }


def main():
    parser = argparse.ArgumentParser(description="build_inputs — route master から trip・deadhead を生成")
    parser.add_argument(
        "--config", default="config/experiment_config.json",
        help="設定ファイルパス",
    )
    args = parser.parse_args()
    build_inputs(args.config)


if __name__ == "__main__":
    main()
