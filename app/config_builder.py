"""
app/config_builder.py

Settings-tab backend helpers.

Builds ProblemConfig from Streamlit session state with a timetable-first path:

1) timetable.csv -> TripSpec
2) fleet/depot/power settings -> BusSpec/ChargerSpec/energy params
3) precompute_helpers() for solver-ready config
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.model_core import (
    BusSpec,
    ChargerSpec,
    ProblemConfig,
    TripSpec,
    precompute_helpers,
)
from app.vehicle_fleet_editor import get_fleet_vehicles


@dataclass(frozen=True)
class BuildReport:
    source_mode: str
    timetable_trips_total: int
    timetable_trips_used: int
    warnings: tuple[str, ...]


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _hhmm_to_min(clock: str) -> int:
    text = str(clock).strip()
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid time format: '{clock}'")
    hour = int(parts[0])
    minute = int(parts[1])
    return hour * 60 + minute


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8")


def _load_depot_ids(data_dir: Path) -> list[str]:
    garages = _read_csv_if_exists(data_dir / "operations" / "garages.csv")
    if garages.empty or "depot_id" not in garages.columns:
        return []
    depot_ids = [str(x).strip() for x in garages["depot_id"].dropna().tolist()]
    return [d for d in depot_ids if d]


def _vehicle_type_to_category(raw: str) -> str:
    text = str(raw).strip().lower()
    if text in ("engine", "ice", "diesel", "engine_bus"):
        return "ICE"
    if "ice" in text or "diesel" in text or "engine" in text:
        return "ICE"
    return "BEV"


def _build_buses_from_fleet_and_defaults(warnings: list[str]) -> list[BusSpec]:
    ss = st.session_state
    cap_kwh = _safe_float(ss.get("cfg_cap", 300.0), 300.0)
    soc_init_ratio = _safe_float(ss.get("cfg_soc_init", 80), 80.0) / 100.0
    soc_min_ratio = _safe_float(ss.get("cfg_soc_min", 20), 20.0) / 100.0
    soc_max_ratio = _safe_float(ss.get("cfg_soc_max", 95), 95.0) / 100.0
    efficiency = _safe_float(ss.get("cfg_eff", 1.0), 1.0)

    fleet = get_fleet_vehicles()
    buses: list[BusSpec] = []

    if fleet:
        for veh in fleet:
            category = "ICE" if veh.get("vehicle_type") == "engine" else "BEV"
            if category == "BEV":
                veh_cap = _safe_float(veh.get("battery_capacity_kWh", cap_kwh), cap_kwh)
                econ = _safe_float(veh.get("energy_consumption_kWh_per_km", 1.0), 1.0)
                eff_km = (1.0 / econ) if econ > 0 else efficiency
                buses.append(
                    BusSpec(
                        bus_id=str(veh.get("vehicle_id", ""))
                        or f"bus_{len(buses) + 1}",
                        category="BEV",
                        cap_kwh=veh_cap,
                        soc_init_kwh=round(
                            veh_cap
                            * _safe_float(
                                veh.get("initial_soc", soc_init_ratio), soc_init_ratio
                            ),
                            1,
                        ),
                        soc_min_kwh=round(
                            veh_cap
                            * _safe_float(
                                veh.get("min_soc", soc_min_ratio), soc_min_ratio
                            ),
                            1,
                        ),
                        soc_max_kwh=round(
                            veh_cap
                            * _safe_float(
                                veh.get("max_soc", soc_max_ratio), soc_max_ratio
                            ),
                            1,
                        ),
                        efficiency_km_per_kwh=eff_km,
                    )
                )
            else:
                fuel_cons = _safe_float(veh.get("fuel_consumption_L_per_km", 0.2), 0.2)
                co2_kg_per_l = _safe_float(veh.get("co2_emission_kg_per_L", 2.58), 2.58)
                buses.append(
                    BusSpec(
                        bus_id=str(veh.get("vehicle_id", ""))
                        or f"bus_{len(buses) + 1}",
                        category="ICE",
                        cap_kwh=0.0,
                        soc_init_kwh=0.0,
                        soc_min_kwh=0.0,
                        soc_max_kwh=0.0,
                        fuel_efficiency_km_per_l=_safe_float(
                            veh.get("fuel_efficiency_km_per_L", 5.0), 5.0
                        ),
                        co2_g_per_km=round(fuel_cons * co2_kg_per_l * 1000.0, 2),
                    )
                )
        return buses

    # Fallback 1: data/operations/vehicles.csv
    vehicles_csv = _read_csv_if_exists(
        Path(st.session_state.get("cfg_data_dir", "data"))
        / "operations"
        / "vehicles.csv"
    )
    if not vehicles_csv.empty and "vehicle_id" in vehicles_csv.columns:
        for _, row in vehicles_csv.iterrows():
            category = _vehicle_type_to_category(row.get("vehicle_type", "BEV"))
            vehicle_id = str(row.get("vehicle_id", "")).strip()
            if not vehicle_id:
                vehicle_id = f"bus_{len(buses) + 1}"
            if category == "BEV":
                veh_cap = _safe_float(row.get("battery_capacity_kwh", cap_kwh), cap_kwh)
                eff_km = _safe_float(
                    row.get("efficiency_km_per_kwh", efficiency), efficiency
                )
                buses.append(
                    BusSpec(
                        bus_id=vehicle_id,
                        category="BEV",
                        cap_kwh=veh_cap,
                        soc_init_kwh=round(veh_cap * soc_init_ratio, 1),
                        soc_min_kwh=round(
                            veh_cap
                            * _safe_float(
                                row.get("soc_min_ratio", soc_min_ratio), soc_min_ratio
                            ),
                            1,
                        ),
                        soc_max_kwh=round(
                            veh_cap
                            * _safe_float(
                                row.get("soc_max_ratio", soc_max_ratio), soc_max_ratio
                            ),
                            1,
                        ),
                        efficiency_km_per_kwh=eff_km,
                    )
                )
            else:
                buses.append(
                    BusSpec(
                        bus_id=vehicle_id,
                        category="ICE",
                        cap_kwh=0.0,
                        soc_init_kwh=0.0,
                        soc_min_kwh=0.0,
                        soc_max_kwh=0.0,
                        fuel_efficiency_km_per_l=5.0,
                        co2_g_per_km=500.0,
                    )
                )
        warnings.append(
            "フリートエディタ未設定のため data/operations/vehicles.csv を車両入力として使用しました。"
        )
        return buses

    # Fallback 2: synthetic buses
    num_buses = _safe_int(ss.get("cfg_num_buses", 3), 3)
    for i in range(num_buses):
        buses.append(
            BusSpec(
                bus_id=f"bus_{i + 1}",
                category="BEV",
                cap_kwh=cap_kwh,
                soc_init_kwh=round(cap_kwh * soc_init_ratio, 1),
                soc_min_kwh=round(cap_kwh * soc_min_ratio, 1),
                soc_max_kwh=round(cap_kwh * soc_max_ratio, 1),
                efficiency_km_per_kwh=efficiency,
            )
        )
    warnings.append(
        "車両データが未設定のためフォールバック BEV 車両を自動生成しました。"
    )
    return buses


def _build_route_distance_lookup(
    data_dir: Path,
) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    by_route_direction: dict[tuple[str, str], float] = {}
    by_route: dict[str, float] = {}

    segments = _read_csv_if_exists(data_dir / "route_master" / "segments.csv")
    if not segments.empty and {"route_id", "direction", "distance_km"}.issubset(
        segments.columns
    ):
        grouped = segments.groupby(["route_id", "direction"], dropna=False)[
            "distance_km"
        ].sum()
        for (route_id, direction), distance in grouped.items():
            rid = str(route_id).strip()
            did = str(direction).strip()
            by_route_direction[(rid, did)] = _safe_float(distance, 0.0)

    routes = _read_csv_if_exists(data_dir / "route_master" / "routes.csv")
    if not routes.empty and "route_id" in routes.columns:
        for _, row in routes.iterrows():
            rid = str(row.get("route_id", "")).strip()
            if not rid:
                continue
            total_distance = _safe_float(row.get("total_distance_km", 0.0), 0.0)
            route_type = str(row.get("route_type", "")).strip().lower()
            if total_distance > 0:
                if route_type == "bidirectional":
                    by_route[rid] = total_distance / 2.0
                else:
                    by_route[rid] = total_distance

    return by_route_direction, by_route


def _build_trips_from_timetable(
    data_dir: Path,
    num_periods: int,
    delta_h: float,
    start_hour: int,
    end_hour: int,
    ev_eff_km_per_kwh: float,
    warnings: list[str],
) -> tuple[list[TripSpec], int, int]:
    timetable = _read_csv_if_exists(data_dir / "route_master" / "timetable.csv")
    if timetable.empty:
        return [], 0, 0

    service_filter = str(st.session_state.get("cfg_service_type", "すべて")).strip()
    if service_filter != "すべて" and "service_type" in timetable.columns:
        timetable = timetable[
            timetable["service_type"].astype(str).str.strip() == service_filter
        ]

    timetable = timetable.copy()
    total_rows = len(timetable)

    start_min = start_hour * 60
    end_min = end_hour * 60
    slot_min = max(1, int(round(delta_h * 60)))
    if end_min <= start_min:
        raise ValueError("終了時刻は開始時刻より後に設定してください。")

    distance_by_route_dir, distance_by_route = _build_route_distance_lookup(data_dir)
    default_trip_distance = _safe_float(
        st.session_state.get("cfg_default_trip_distance", 10.0), 10.0
    )
    max_trips = _safe_int(st.session_state.get("cfg_max_trips", 0), 0)

    trips: list[TripSpec] = []
    for _, row in timetable.iterrows():
        dep_raw = row.get("dep_time")
        arr_raw = row.get("arr_time")
        if pd.isna(dep_raw) or pd.isna(arr_raw):
            continue

        dep_min = _hhmm_to_min(str(dep_raw))
        arr_min = _hhmm_to_min(str(arr_raw))
        if arr_min <= dep_min:
            arr_min += 24 * 60

        # Keep trips that depart within planning horizon.
        if dep_min < start_min or dep_min >= end_min:
            continue

        start_t = int((dep_min - start_min) // slot_min)
        end_t = int(math.ceil((arr_min - start_min) / slot_min) - 1)
        if start_t < 0 or start_t >= num_periods:
            continue
        if end_t < start_t:
            end_t = start_t
        if end_t >= num_periods:
            warnings.append(
                f"Trip '{row.get('trip_id', '(unknown)')}' は計画終端を超えるため end_t を切り詰めました。"
            )
            end_t = num_periods - 1

        route_id = str(row.get("route_id", "route_unknown")).strip() or "route_unknown"
        direction = str(row.get("direction", "outbound")).strip() or "outbound"
        distance_km = distance_by_route_dir.get((route_id, direction))
        if distance_km is None or distance_km <= 0:
            distance_km = distance_by_route.get(route_id, default_trip_distance)
        if distance_km <= 0:
            distance_km = default_trip_distance

        energy_kwh = round(distance_km / max(ev_eff_km_per_kwh, 0.1), 2)
        trip_id = str(row.get("trip_id", "")).strip()
        if not trip_id:
            trip_id = f"{route_id}_{direction}_{dep_min}"

        start_node = str(row.get("from_stop_id", "")).strip() or f"{route_id}_origin"
        end_node = str(row.get("to_stop_id", "")).strip() or f"{route_id}_destination"

        trips.append(
            TripSpec(
                trip_id=trip_id,
                start_t=start_t,
                end_t=end_t,
                energy_kwh=max(0.1, energy_kwh),
                distance_km=round(distance_km, 3),
                start_node=start_node,
                end_node=end_node,
            )
        )

    trips.sort(key=lambda t: (t.start_t, t.trip_id))
    if max_trips > 0 and len(trips) > max_trips:
        warnings.append(
            f"時刻表便数が上限 {max_trips} を超えたため先頭便のみ使用しました。"
        )
        trips = trips[:max_trips]

    return trips, total_rows, len(trips)


def _build_synthetic_trips(
    num_trips: int,
    num_periods: int,
    depots: list[str],
) -> list[TripSpec]:
    import random

    random.seed(42)
    trips: list[TripSpec] = []
    for i in range(num_trips):
        slot_start = int(i * (num_periods - 3) / max(num_trips, 1))
        duration = random.randint(2, 4)
        slot_end = min(slot_start + duration, num_periods - 1)
        energy = round(random.uniform(25, 55), 1)
        start_node = depots[i % len(depots)]
        end_node = depots[(i + 1) % len(depots)]
        trips.append(
            TripSpec(
                trip_id=f"trip_{i + 1}",
                start_t=slot_start,
                end_t=slot_end,
                energy_kwh=energy,
                distance_km=energy,
                start_node=start_node,
                end_node=end_node,
            )
        )
    return trips


def _build_price_profile(
    num_periods: int, start_hour: int, delta_h: float
) -> list[float]:
    price_mode = st.session_state.get("cfg_price_mode", "デフォルト TOU")
    if price_mode == "一律 [円/kWh]":
        flat_price = _safe_float(st.session_state.get("cfg_flat_price", 25.0), 25.0)
        return [flat_price] * num_periods

    prices: list[float] = []
    for t in range(num_periods):
        hour = start_hour + t * delta_h
        if hour < 8 or hour >= 22:
            prices.append(18.0)
        elif hour < 10:
            prices.append(22.0)
        elif hour < 16:
            prices.append(30.0)
        elif hour < 20:
            prices.append(34.0)
        else:
            prices.append(25.0)
    return prices


def _build_pv_profile(num_periods: int, start_hour: int, delta_h: float) -> list[float]:
    pv_scale = _safe_float(st.session_state.get("cfg_pv_scale", 1.0), 1.0)
    profile: list[float] = []
    for t in range(num_periods):
        hour = start_hour + t * delta_h
        if 6 <= hour <= 18:
            value = 60.0 * math.exp(-0.5 * ((hour - 12.0) / 3.0) ** 2)
        else:
            value = 0.0
        profile.append(round(value * pv_scale, 2))
    return profile


def build_problem_config_from_session_state(
    data_dir: str = "data",
) -> tuple[ProblemConfig, BuildReport]:
    ss = st.session_state
    ss["cfg_data_dir"] = data_dir
    warnings: list[str] = []

    delta_h = _safe_float(ss.get("cfg_delta_h", 0.5), 0.5)
    start_hour = _safe_int(ss.get("cfg_start_hour", 6), 6)
    end_hour = _safe_int(ss.get("cfg_end_hour", 22), 22)
    if end_hour <= start_hour:
        raise ValueError("終了時刻は開始時刻より後に設定してください。")
    num_periods = int((end_hour - start_hour) / delta_h)
    if num_periods <= 0:
        raise ValueError("時間軸の設定によりスロット数が 0 になっています。")

    buses = _build_buses_from_fleet_and_defaults(warnings)
    bev_eff_list = [b.efficiency_km_per_kwh for b in buses if b.category == "BEV"]
    fallback_eff = _safe_float(ss.get("cfg_eff", 1.0), 1.0)
    avg_bev_eff = (
        sum(bev_eff_list) / len(bev_eff_list) if bev_eff_list else fallback_eff
    )

    base = Path(data_dir)
    depots = _load_depot_ids(base)
    if not depots:
        num_depots = _safe_int(ss.get("cfg_depots", 2), 2)
        depots = [f"depot_{chr(65 + i)}" for i in range(num_depots)]
        warnings.append("営業所データ未登録のため仮想デポ ID を使用しました。")

    source_mode = str(ss.get("cfg_trip_source_mode", "時刻表（推奨）"))
    timetable_total = 0
    timetable_used = 0

    if source_mode == "時刻表（推奨）":
        trips, timetable_total, timetable_used = _build_trips_from_timetable(
            data_dir=base,
            num_periods=num_periods,
            delta_h=delta_h,
            start_hour=start_hour,
            end_hour=end_hour,
            ev_eff_km_per_kwh=max(avg_bev_eff, 0.1),
            warnings=warnings,
        )
        if not trips:
            raise ValueError(
                "時刻表から有効な便を構築できませんでした。路線管理タブで時刻表を確認してください。"
            )
    else:
        num_trips = _safe_int(ss.get("cfg_num_trips", 6), 6)
        trips = _build_synthetic_trips(
            num_trips=num_trips, num_periods=num_periods, depots=depots
        )
        warnings.append(
            "簡易サンプルモード: 便データを時刻表ではなく自動生成しています。"
        )

    slow_power = _safe_float(ss.get("cfg_slow_pw", 50.0), 50.0)
    slow_count = _safe_int(ss.get("cfg_slow_cnt", 2), 2)
    fast_power = _safe_float(ss.get("cfg_fast_pw", 150.0), 150.0)
    fast_count = _safe_int(ss.get("cfg_fast_cnt", 1), 1)
    charge_eff = _safe_float(ss.get("cfg_ch_eff", 0.95), 0.95)

    chargers: list[ChargerSpec] = []
    for depot in depots:
        if slow_count > 0:
            chargers.append(
                ChargerSpec(
                    depot=depot,
                    charger_type="slow",
                    power_kw=slow_power,
                    count=slow_count,
                    efficiency=charge_eff,
                )
            )
        if fast_count > 0:
            chargers.append(
                ChargerSpec(
                    depot=depot,
                    charger_type="fast",
                    power_kw=fast_power,
                    count=fast_count,
                    efficiency=charge_eff,
                )
            )

    enable_terminal_soc = bool(ss.get("cfg_term_soc", False))
    terminal_soc_ratio = _safe_float(ss.get("cfg_term_ratio", 50), 50.0) / 100.0
    cap_ref = _safe_float(ss.get("cfg_cap", 300.0), 300.0)
    enable_demand_charge = bool(ss.get("cfg_demand", False))
    contract_power = (
        _safe_float(ss.get("cfg_contract", 200.0), 200.0)
        if enable_demand_charge
        else None
    )

    cfg = ProblemConfig(
        num_buses=len(buses),
        num_trips=len(trips),
        num_periods=num_periods,
        delta_h=delta_h,
        start_time=f"{start_hour:02d}:00",
        end_time=f"{end_hour:02d}:00",
        buses=buses,
        trips=trips,
        depots=depots,
        charger_types=sorted(set(c.charger_type for c in chargers)) or ["slow", "fast"],
        chargers=chargers,
        charge_efficiency=charge_eff,
        pv_gen_kwh=_build_pv_profile(num_periods, start_hour, delta_h),
        grid_price_yen_per_kwh=_build_price_profile(num_periods, start_hour, delta_h),
        diesel_yen_per_l=_safe_float(ss.get("cfg_diesel", 145.0), 145.0),
        enable_pv=bool(ss.get("cfg_enable_pv", True)),
        enable_terminal_soc=enable_terminal_soc,
        terminal_soc_kwh=round(cap_ref * terminal_soc_ratio, 1)
        if enable_terminal_soc
        else None,
        enable_demand_charge=enable_demand_charge,
        contract_power_kw=contract_power,
    )

    ready = precompute_helpers(cfg)
    report = BuildReport(
        source_mode=source_mode,
        timetable_trips_total=timetable_total,
        timetable_trips_used=timetable_used,
        warnings=tuple(warnings),
    )
    return ready, report
