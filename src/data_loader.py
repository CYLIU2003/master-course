"""
data_loader.py — CSV / JSON 入力読込 → ProblemData 変換

仕様書 §14.1 担当。
  - CSV / JSON を読み込み、data_schema の内部データクラスへ変換する
  - 欠損・型・単位整合を検証する
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pandas as pd
    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False

from .data_schema import (
    Charger,
    ElectricityPrice,
    ProblemData,
    PVProfile,
    Site,
    Task,
    TravelConnection,
    Vehicle,
    VehicleChargerCompat,
    VehicleTaskCompat,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _na(val: Any) -> Optional[float]:
    """空文字・NaN → None、それ以外は float に変換"""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "none", "na"):
        return None
    return float(s)


def _bool_col(val: Any) -> bool:
    """文字列 'true'/'false' → bool"""
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def _read_csv(path: Path) -> List[Dict[str, str]]:
    """pandas なしでも動く簡易 CSV 読み込み"""
    if _PD_AVAILABLE:
        df = pd.read_csv(path, dtype=str).fillna("")
        return df.to_dict(orient="records")
    rows: List[Dict[str, str]] = []
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    headers = [h.strip() for h in lines[0].split(",")]
    for line in lines[1:]:
        vals = [v.strip() for v in line.split(",")]
        rows.append(dict(zip(headers, vals)))
    return rows


# ---------------------------------------------------------------------------
# 個別ローダー
# ---------------------------------------------------------------------------

def load_vehicles(path: Path) -> List[Vehicle]:
    rows = _read_csv(path)
    vehicles: List[Vehicle] = []
    for r in rows:
        v = Vehicle(
            vehicle_id=r["vehicle_id"],
            vehicle_type=r["vehicle_type"].upper(),
            home_depot=r["home_depot"],
            battery_capacity=_na(r.get("battery_capacity")),
            soc_init=_na(r.get("soc_init")),
            soc_min=_na(r.get("soc_min")),
            soc_max=_na(r.get("soc_max")),
            soc_target_end=_na(r.get("soc_target_end")),
            charge_power_max=_na(r.get("charge_power_max")),
            discharge_power_max=_na(r.get("discharge_power_max")),
            fixed_use_cost=float(r.get("fixed_use_cost") or 0.0),
            max_operating_time=float(r.get("max_operating_time") or 24.0),
            max_distance=float(r.get("max_distance") or 9999.0),
            charge_efficiency=float(r.get("charge_efficiency") or 0.95),
            fuel_tank_capacity=_na(r.get("fuel_tank_capacity")),
            fuel_cost_coeff=float(r.get("fuel_cost_coeff") or 145.0),
            co2_emission_coeff=float(r.get("co2_emission_coeff") or 2.58),
        )
        vehicles.append(v)
    return vehicles


def load_tasks(path: Path) -> List[Task]:
    rows = _read_csv(path)
    tasks: List[Task] = []
    for r in rows:
        rt = r.get("required_vehicle_type", "").strip()
        t = Task(
            task_id=r["task_id"],
            start_time_idx=int(r["start_time_idx"]),
            end_time_idx=int(r["end_time_idx"]),
            origin=r["origin"],
            destination=r["destination"],
            distance_km=float(r.get("distance_km") or 0.0),
            energy_required_kwh_bev=float(r.get("energy_required_kwh_bev") or 0.0),
            fuel_required_liter_ice=float(r.get("fuel_required_liter_ice") or 0.0),
            required_vehicle_type=rt if rt else None,
            demand_cover=_bool_col(r.get("demand_cover", "true")),
            penalty_unserved=float(r.get("penalty_unserved") or 10000.0),
        )
        tasks.append(t)
    return tasks


def load_chargers(path: Path) -> List[Charger]:
    rows = _read_csv(path)
    chargers: List[Charger] = []
    for r in rows:
        c = Charger(
            charger_id=r["charger_id"],
            site_id=r["site_id"],
            power_max_kw=float(r["power_max_kw"]),
            efficiency=float(r.get("efficiency") or 0.95),
            power_min_kw=float(r.get("power_min_kw") or 0.0),
        )
        chargers.append(c)
    return chargers


def load_sites(path: Path) -> List[Site]:
    rows = _read_csv(path)
    sites: List[Site] = []
    for r in rows:
        s = Site(
            site_id=r["site_id"],
            site_type=r["site_type"],
            grid_import_limit_kw=float(r.get("grid_import_limit_kw") or 9999.0),
            contract_demand_limit_kw=float(r.get("contract_demand_limit_kw") or 9999.0),
            site_transformer_limit_kw=float(r.get("site_transformer_limit_kw") or 9999.0),
        )
        sites.append(s)
    return sites


def load_pv_profile(path: Path) -> List[PVProfile]:
    rows = _read_csv(path)
    return [
        PVProfile(
            site_id=r["site_id"],
            time_idx=int(r["time_idx"]),
            pv_generation_kw=float(r.get("pv_generation_kw") or 0.0),
        )
        for r in rows
    ]


def load_electricity_price(path: Path) -> List[ElectricityPrice]:
    rows = _read_csv(path)
    return [
        ElectricityPrice(
            site_id=r["site_id"],
            time_idx=int(r["time_idx"]),
            grid_energy_price=float(r.get("grid_energy_price") or 0.0),
            sell_back_price=float(r.get("sell_back_price") or 0.0),
            base_load_kw=float(r.get("base_load_kw") or 0.0),
        )
        for r in rows
    ]


def load_travel_connection(path: Path) -> List[TravelConnection]:
    rows = _read_csv(path)
    return [
        TravelConnection(
            from_task_id=r["from_task_id"],
            to_task_id=r["to_task_id"],
            can_follow=_bool_col(r.get("can_follow", "true")),
            deadhead_time_slot=int(r.get("deadhead_time_slot") or 0),
            deadhead_distance_km=float(r.get("deadhead_distance_km") or 0.0),
            deadhead_energy_kwh=float(r.get("deadhead_energy_kwh") or 0.0),
        )
        for r in rows
    ]


def load_vehicle_task_compat(path: Path) -> List[VehicleTaskCompat]:
    rows = _read_csv(path)
    return [
        VehicleTaskCompat(
            vehicle_id=r["vehicle_id"],
            task_id=r["task_id"],
            feasible=_bool_col(r.get("feasible", "true")),
        )
        for r in rows
    ]


def load_vehicle_charger_compat(path: Path) -> List[VehicleChargerCompat]:
    rows = _read_csv(path)
    return [
        VehicleChargerCompat(
            vehicle_id=r["vehicle_id"],
            charger_id=r["charger_id"],
            feasible=_bool_col(r.get("feasible", "true")),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# config.json ローダー
# ---------------------------------------------------------------------------

def load_config(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# メインエントリポイント: config.json から全データを読込
# ---------------------------------------------------------------------------

def load_problem_data(config_path: str | Path) -> ProblemData:
    """
    config.json を起点に全 CSV を読み込んで ProblemData を返す。

    Parameters
    ----------
    config_path : str | Path
        config/experiment_config.json へのパス

    Returns
    -------
    ProblemData
        MILP / シミュレータへの統一入力
    """
    cfg = load_config(Path(config_path))
    root = Path(config_path).parent.parent  # project root

    paths = cfg.get("paths", {})

    def abs_path(key: str) -> Optional[Path]:
        rel = paths.get(key)
        if not rel:
            return None
        p = root / rel
        return p if p.exists() else None

    # --- 必須 CSV ---
    vehicles = load_vehicles(abs_path("vehicles_csv"))
    tasks = load_tasks(abs_path("tasks_csv"))
    chargers = load_chargers(abs_path("chargers_csv"))
    sites = load_sites(abs_path("sites_csv"))

    # --- 任意 CSV ---
    pv_profiles: List[PVProfile] = []
    if abs_path("pv_profile_csv"):
        pv_profiles = load_pv_profile(abs_path("pv_profile_csv"))

    electricity_prices: List[ElectricityPrice] = []
    if abs_path("electricity_price_csv"):
        electricity_prices = load_electricity_price(abs_path("electricity_price_csv"))

    travel_connections: List[TravelConnection] = []
    if abs_path("travel_connection_csv"):
        travel_connections = load_travel_connection(abs_path("travel_connection_csv"))

    vehicle_task_compat: List[VehicleTaskCompat] = []
    if abs_path("compat_vehicle_task_csv"):
        vehicle_task_compat = load_vehicle_task_compat(abs_path("compat_vehicle_task_csv"))

    vehicle_charger_compat: List[VehicleChargerCompat] = []
    if abs_path("compat_vehicle_charger_csv"):
        vehicle_charger_compat = load_vehicle_charger_compat(abs_path("compat_vehicle_charger_csv"))

    # --- パラメータ ---
    weights = cfg.get("objective_weights", {})
    big_m = cfg.get("big_m", {})
    step_min = float(cfg.get("time_step_min", 15))
    delta_h = step_min / 60.0
    num_periods = int(cfg.get("num_periods", 64))

    data = ProblemData(
        vehicles=vehicles,
        tasks=tasks,
        chargers=chargers,
        sites=sites,
        travel_connections=travel_connections,
        vehicle_task_compat=vehicle_task_compat,
        vehicle_charger_compat=vehicle_charger_compat,
        pv_profiles=pv_profiles,
        electricity_prices=electricity_prices,
        num_periods=num_periods,
        delta_t_hour=delta_h,
        planning_horizon_hours=float(cfg.get("planning_horizon_hours", 16.0)),
        allow_partial_service=bool(cfg.get("allow_partial_service", False)),
        enable_pv=bool(cfg.get("enable_pv", False)),
        enable_v2g=bool(cfg.get("enable_v2g", False)),
        enable_battery_degradation=bool(cfg.get("enable_battery_degradation", False)),
        enable_demand_charge=bool(cfg.get("enable_demand_charge", False)),
        use_soft_soc_constraint=bool(cfg.get("use_soft_soc_constraint", False)),
        objective_weights={**ProblemData.__dataclass_fields__["objective_weights"].default_factory(), **weights},
        BIG_M_ASSIGN=float(big_m.get("BIG_M_ASSIGN", 1e6)),
        BIG_M_CHARGE=float(big_m.get("BIG_M_CHARGE", 1e6)),
        BIG_M_SOC=float(big_m.get("BIG_M_SOC", 1e6)),
        EPSILON=float(big_m.get("EPSILON", 1e-6)),
    )
    return data
