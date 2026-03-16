"""
src.preprocess.trip_converter — GeneratedTrip → ProblemData 変換ブリッジ

route-detail layer (GeneratedTrip, DeadheadArc) から
MILP/ALNS が使用する ProblemData (Task, TravelConnection) への変換を行う。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.data_schema import (
    Charger,
    ElectricityPrice,
    PVProfile,
    ProblemData,
    Site,
    Task,
    TravelConnection,
    Vehicle,
    VehicleChargerCompat,
    VehicleTaskCompat,
)
from src.schemas.route_entities import DeadheadArc, GeneratedTrip
from src.schemas.fleet_entities import VehicleType, VehicleInstance


def _time_to_idx(time_str: str, start_time: str = "05:00", delta_t_min: float = 15.0) -> int:
    """HH:MM 文字列 → time_idx に変換。"""
    fmt = "%H:%M"
    try:
        t = datetime.strptime(time_str, fmt)
        t0 = datetime.strptime(start_time, fmt)
    except ValueError:
        return 0
    diff_min = (t - t0).total_seconds() / 60.0
    if diff_min < 0:
        diff_min += 24 * 60
    return max(0, int(diff_min / delta_t_min))


def convert_trips_to_tasks(
    trips: List[GeneratedTrip],
    start_time: str = "05:00",
    delta_t_min: float = 15.0,
    default_penalty: float = 10000.0,
) -> List[Task]:
    """GeneratedTrip リストを Task リストに変換する。

    Parameters
    ----------
    trips : List[GeneratedTrip]
    start_time : str  計画期間の開始時刻 "HH:MM"
    delta_t_min : float  タイムステップ [min]
    default_penalty : float  未割当ペナルティ [円]

    Returns
    -------
    List[Task]
    """
    tasks: List[Task] = []
    for trip in trips:
        if trip.trip_category != "revenue":
            continue

        start_idx = _time_to_idx(trip.departure_time, start_time, delta_t_min)
        end_idx = _time_to_idx(trip.arrival_time, start_time, delta_t_min)
        if end_idx <= start_idx:
            end_idx = start_idx + max(1, int(trip.scheduled_runtime_min / delta_t_min))

        task = Task(
            task_id=trip.trip_id,
            start_time_idx=start_idx,
            end_time_idx=end_idx,
            origin=trip.origin_terminal_id,
            destination=trip.destination_terminal_id,
            distance_km=trip.distance_km,
            energy_required_kwh_bev=trip.estimated_energy_kwh_bev or 0.0,
            fuel_required_liter_ice=trip.estimated_fuel_l_ice or 0.0,
            required_vehicle_type=None,
            demand_cover=True,
            penalty_unserved=default_penalty,
            route_id=trip.route_id,
            direction=trip.canonical_direction,
            route_variant_type=trip.route_variant_type,
            service_id=trip.service_id,
        )
        tasks.append(task)
    return tasks


def convert_deadhead_arcs_to_connections(
    arcs: List[DeadheadArc],
    delta_t_min: float = 15.0,
) -> List[TravelConnection]:
    """DeadheadArc リストを TravelConnection リストに変換する。

    Parameters
    ----------
    arcs : List[DeadheadArc]
    delta_t_min : float  タイムステップ [min]

    Returns
    -------
    List[TravelConnection]
    """
    connections: List[TravelConnection] = []
    for arc in arcs:
        conn = TravelConnection(
            from_task_id=arc.from_trip_id,
            to_task_id=arc.to_trip_id,
            can_follow=arc.is_feasible_connection,
            deadhead_time_slot=max(0, int(math.ceil(arc.deadhead_time_min / delta_t_min))),
            deadhead_distance_km=arc.deadhead_distance_km,
            deadhead_energy_kwh=arc.deadhead_energy_kwh_bev or 0.0,
        )
        connections.append(conn)
    return connections


def convert_vehicle_types_to_vehicles(
    vehicle_types: List[VehicleType],
    vehicle_instances: List[VehicleInstance],
    num_periods: int = 64,
    delta_t_hour: float = 0.25,
) -> List[Vehicle]:
    """VehicleType + VehicleInstance → Vehicle リストに変換する。

    Parameters
    ----------
    vehicle_types : List[VehicleType]
    vehicle_instances : List[VehicleInstance]
    num_periods : int
    delta_t_hour : float

    Returns
    -------
    List[Vehicle]
    """
    vt_index = {vt.vehicle_type_id: vt for vt in vehicle_types}
    vehicles: List[Vehicle] = []

    for vi in vehicle_instances:
        vt = vt_index.get(vi.vehicle_type_id)
        if vt is None:
            print(f"  [warn] VehicleInstance '{vi.vehicle_id}' の vehicle_type '{vi.vehicle_type_id}' が不明")
            continue

        v = Vehicle(
            vehicle_id=vi.vehicle_id,
            vehicle_type=vt.powertrain,
            home_depot=vi.depot_id,
        )

        if vt.powertrain in ("BEV", "PHEV"):
            cap = vt.battery_capacity_kwh or 200.0
            usable = vt.usable_battery_ratio or 0.9
            v.battery_capacity = cap
            v.soc_init = vi.initial_soc_kwh if vi.initial_soc_kwh is not None else cap * usable * 0.9
            v.soc_min = cap * (1.0 - usable)
            v.soc_max = cap * usable
            v.soc_target_end = cap * usable * 0.7
            v.charge_power_max = vt.charging_power_max_kw or 50.0
            v.charge_efficiency = vt.charge_efficiency
            v.discharge_power_max = vt.discharging_power_max_kw
            v.battery_degradation_cost_coeff = vt.battery_degradation_cost_coeff

        if vt.powertrain in ("ICE", "HEV", "PHEV"):
            v.fuel_tank_capacity = vt.fuel_tank_l
            v.fuel_cost_coeff = vt.fuel_cost_jpy_per_l
            v.co2_emission_coeff = vt.co2_emission_factor_kg_per_l

        v.fixed_use_cost = vt.fixed_om_cost_jpy_per_day or 0.0
        v.max_operating_time = 18.0  # 18h上限
        v.max_distance = 500.0       # 500km/日上限

        vehicles.append(v)
    return vehicles


def build_vehicle_task_compat(
    vehicles: List[Vehicle],
    tasks: List[Task],
) -> List[VehicleTaskCompat]:
    """車両とタスクの互換性テーブルを自動生成する。"""
    compat: List[VehicleTaskCompat] = []
    for v in vehicles:
        for t in tasks:
            feasible = True
            if t.required_vehicle_type is not None:
                if v.vehicle_type != t.required_vehicle_type:
                    feasible = False
            compat.append(VehicleTaskCompat(
                vehicle_id=v.vehicle_id,
                task_id=t.task_id,
                feasible=feasible,
            ))
    return compat


def build_vehicle_charger_compat(
    vehicles: List[Vehicle],
    chargers: List[Charger],
) -> List[VehicleChargerCompat]:
    """車両と充電器の互換性テーブルを自動生成する。
    BEV/PHEV のみ充電可能。"""
    compat: List[VehicleChargerCompat] = []
    for v in vehicles:
        for c in chargers:
            feasible = v.vehicle_type in ("BEV", "PHEV")
            compat.append(VehicleChargerCompat(
                vehicle_id=v.vehicle_id,
                charger_id=c.charger_id,
                feasible=feasible,
            ))
    return compat


def build_problem_data_from_generated(
    trips: List[GeneratedTrip],
    arcs: List[DeadheadArc],
    vehicle_types: List[VehicleType],
    vehicle_instances: List[VehicleInstance],
    chargers: List[Charger],
    sites: List[Site],
    pv_profiles: List[PVProfile],
    electricity_prices: List[ElectricityPrice],
    config: dict,
) -> ProblemData:
    """GeneratedTrip 群から MILP/ALNS 用 ProblemData を構築する。

    Parameters
    ----------
    trips, arcs, vehicle_types, vehicle_instances, chargers, sites,
    pv_profiles, electricity_prices : 各入力データ
    config : dict  experiment_config.json の内容

    Returns
    -------
    ProblemData
    """
    delta_t_min = config.get("time_step_min", 15)
    num_periods = config.get("num_periods", 64)
    start_time = config.get("start_time", "05:00")
    delta_t_hour = delta_t_min / 60.0
    planning_h = config.get("planning_horizon_hours", 16.0)

    tasks = convert_trips_to_tasks(trips, start_time, delta_t_min)
    connections = convert_deadhead_arcs_to_connections(arcs, delta_t_min)
    vehicles = convert_vehicle_types_to_vehicles(
        vehicle_types, vehicle_instances, num_periods, delta_t_hour
    )
    vt_compat = build_vehicle_task_compat(vehicles, tasks)
    vc_compat = build_vehicle_charger_compat(vehicles, chargers)

    weights = config.get("objective_weights", {})
    big_m = config.get("big_m", {})

    data = ProblemData(
        vehicles=vehicles,
        tasks=tasks,
        chargers=chargers,
        sites=sites,
        travel_connections=connections,
        vehicle_task_compat=vt_compat,
        vehicle_charger_compat=vc_compat,
        pv_profiles=pv_profiles,
        electricity_prices=electricity_prices,
        num_periods=num_periods,
        delta_t_hour=delta_t_hour,
        planning_horizon_hours=planning_h,
        allow_partial_service=config.get("allow_partial_service", False),
        enable_pv=config.get("enable_pv", False),
        enable_v2g=config.get("enable_v2g", False),
        enable_battery_degradation=config.get("enable_battery_degradation", False),
        enable_demand_charge=config.get("enable_demand_charge", False),
        use_soft_soc_constraint=config.get("use_soft_soc_constraint", False),
        objective_weights=weights if weights else ProblemData().objective_weights,
        BIG_M_ASSIGN=big_m.get("BIG_M_ASSIGN", 1e6),
        BIG_M_CHARGE=big_m.get("BIG_M_CHARGE", 1e6),
        BIG_M_SOC=big_m.get("BIG_M_SOC", 1e6),
        EPSILON=big_m.get("EPSILON", 1e-6),
    )
    return data
