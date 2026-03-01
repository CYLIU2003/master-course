"""
src.preprocess.duty_loader — 行路設定表の読込・検証

data/fleet/vehicle_duties.csv + duty_legs.csv から VehicleDuty を構築する。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.schemas.duty_entities import (
    DutyAssignmentConfig,
    DutyChargingSlot,
    DutyLeg,
    VehicleDuty,
)
from src.schemas.route_entities import GeneratedTrip


def _parse_float(v, default=0.0):
    try:
        return float(v) if v not in (None, "", "null") else default
    except (ValueError, TypeError):
        return default


def _parse_int(v, default=0):
    try:
        return int(v) if v not in (None, "", "null") else default
    except (ValueError, TypeError):
        return default


def load_vehicle_duties(
    duties_csv,
    duty_legs_csv,
) -> List[VehicleDuty]:
    """行路設定表 CSV を読み込んで VehicleDuty リストを返す。

    Parameters
    ----------
    duties_csv : str or Path
        行路マスタ CSV (duty_id, duty_name, depot_id, ...)
    duty_legs_csv : str or Path
        行路レグ CSV (duty_id, leg_index, leg_type, trip_id, ...)

    Returns
    -------
    List[VehicleDuty]
    """
    duties_csv = Path(duties_csv)
    duty_legs_csv = Path(duty_legs_csv)
    # --- 行路マスタ読込 ---
    duties: Dict[str, VehicleDuty] = {}
    if duties_csv.exists():
        with open(duties_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                duty = VehicleDuty(
                    duty_id=row["duty_id"],
                    duty_name=row.get("duty_name", row["duty_id"]),
                    route_id=row.get("route_id") or None,
                    depot_id=row.get("depot_id", ""),
                    service_day_type=row.get("service_day_type", "weekday"),
                    pull_out_time=row.get("pull_out_time") or None,
                    pull_in_time=row.get("pull_in_time") or None,
                    pull_out_terminal_id=row.get("pull_out_terminal_id") or None,
                    pull_in_terminal_id=row.get("pull_in_terminal_id") or None,
                    driver_group=row.get("driver_group") or None,
                    max_work_time_min=_parse_float(row.get("max_work_time_min"), 960.0),
                    max_continuous_drive_min=_parse_float(row.get("max_continuous_drive_min"), 240.0),
                    required_break_min=_parse_float(row.get("required_break_min"), 30.0),
                    required_vehicle_type=row.get("required_vehicle_type") or None,
                    required_vehicle_id=row.get("required_vehicle_id") or None,
                )
                duties[duty.duty_id] = duty

    # --- レグ読込 ---
    if duty_legs_csv.exists():
        with open(duty_legs_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                duty_id = row["duty_id"]
                if duty_id not in duties:
                    print(f"  [warn] duty_legs: duty_id '{duty_id}' が duties CSV にない → スキップ")
                    continue
                leg = DutyLeg(
                    leg_index=_parse_int(row.get("leg_index", "0"), 0),
                    leg_type=row.get("leg_type", "revenue"),
                    trip_id=row.get("trip_id") or None,
                    from_location_id=row.get("from_location_id") or None,
                    to_location_id=row.get("to_location_id") or None,
                    start_time=row.get("start_time") or None,
                    end_time=row.get("end_time") or None,
                    duration_min=_parse_float(row.get("duration_min"), 0.0),
                    distance_km=_parse_float(row.get("distance_km"), 0.0),
                    notes=row.get("notes") or None,
                )
                duties[duty_id].legs.append(leg)

    # legs を leg_index 順に並べ、サマリ計算
    result: List[VehicleDuty] = []
    for duty in duties.values():
        duty.legs.sort(key=lambda l: l.leg_index)
        duty.compute_summary()
        result.append(duty)

    return result


def validate_duties(
    duties: List[VehicleDuty],
    trip_ids: set,
) -> List[str]:
    """行路設定表の整合性を検査する。

    Parameters
    ----------
    duties : List[VehicleDuty]
    trip_ids : set  有効な trip_id の集合

    Returns
    -------
    List[str]  エラーメッセージ一覧（空=OK）
    """
    errors: List[str] = []
    assigned_trips: Dict[str, str] = {}  # trip_id → duty_id (重複検出)

    for duty in duties:
        for tid in duty.trip_ids:
            if tid not in trip_ids:
                errors.append(f"Duty {duty.duty_id}: trip_id '{tid}' が generated trips に存在しない")
            if tid in assigned_trips:
                errors.append(
                    f"Duty {duty.duty_id}: trip_id '{tid}' が "
                    f"duty '{assigned_trips[tid]}' にも割り当て済み（重複）"
                )
            else:
                assigned_trips[tid] = duty.duty_id

        # 時間整合性
        for i in range(len(duty.legs) - 1):
            leg_a = duty.legs[i]
            leg_b = duty.legs[i + 1]
            if leg_a.end_time and leg_b.start_time:
                if leg_a.end_time > leg_b.start_time:
                    errors.append(
                        f"Duty {duty.duty_id}: leg {i} end={leg_a.end_time} > "
                        f"leg {i+1} start={leg_b.start_time}（時間重複）"
                    )

    return errors


def build_duty_trip_mapping(
    duties: List[VehicleDuty],
) -> Dict[str, List[str]]:
    """duty_id → [trip_id, ...] マッピングを返す。"""
    return {duty.duty_id: duty.trip_ids for duty in duties}


def build_trip_duty_mapping(
    duties: List[VehicleDuty],
) -> Dict[str, str]:
    """trip_id → duty_id マッピングを返す。"""
    mapping: Dict[str, str] = {}
    for duty in duties:
        for tid in duty.trip_ids:
            mapping[tid] = duty.duty_id
    return mapping


def identify_charging_opportunities(
    duty_or_duties,
    min_charging_time_min: float = 10.0,
    charger_site_map: Optional[Dict[str, str]] = None,
) -> List[DutyChargingSlot]:
    """行路レグ間の gap から充電機会を自動識別する。

    duty_or_duties に List[VehicleDuty] が渡された場合は各行路に対して実行し、
    結果を各 duty.charging_opportunities に格納する。

    Parameters
    ----------
    duty_or_duties : VehicleDuty or List[VehicleDuty]
    min_charging_time_min : 充電が可能と判定する最小時間 [min]
    charger_site_map : location_id → charger_site_id マッピング

    Returns
    -------
    List[DutyChargingSlot]  (単一 duty の場合のみ意味がある)
    """
    if isinstance(duty_or_duties, list):
        all_slots = []
        for d in duty_or_duties:
            slots = _identify_charging_opportunities_single(d, min_charging_time_min, charger_site_map)
            d.charging_opportunities = slots
            all_slots.extend(slots)
        return all_slots
    else:
        slots = _identify_charging_opportunities_single(duty_or_duties, min_charging_time_min, charger_site_map)
        duty_or_duties.charging_opportunities = slots
        return slots


def _identify_charging_opportunities_single(
    duty: VehicleDuty,
    min_charging_time_min: float = 10.0,
    charger_site_map: Optional[Dict[str, str]] = None,
) -> List[DutyChargingSlot]:
    """単一行路の充電機会を識別する（内部関数）。"""
    slots: List[DutyChargingSlot] = []

    for i, leg in enumerate(duty.legs):
        if i + 1 >= len(duty.legs):
            break
        next_leg = duty.legs[i + 1]

        # break レグはそのまま充電機会
        if next_leg.leg_type == "break" and next_leg.duration_min >= min_charging_time_min:
            loc = next_leg.from_location_id or leg.to_location_id or ""
            charger_id = (charger_site_map or {}).get(loc)
            slot = DutyChargingSlot(
                slot_index=len(slots),
                after_leg_index=i,
                location_id=loc,
                available_time_min=next_leg.duration_min,
                charger_site_id=charger_id,
            )
            slots.append(slot)
        # 折返し待ち (gap between legs)
        elif leg.end_time and next_leg.start_time:
            from datetime import datetime
            try:
                t_end = datetime.strptime(leg.end_time, "%H:%M")
                t_start = datetime.strptime(next_leg.start_time, "%H:%M")
                gap_min = (t_start - t_end).total_seconds() / 60.0
                if gap_min < 0:
                    gap_min += 24 * 60
                if gap_min >= min_charging_time_min:
                    loc = leg.to_location_id or ""
                    charger_id = (charger_site_map or {}).get(loc)
                    slot = DutyChargingSlot(
                        slot_index=len(slots),
                        after_leg_index=i,
                        location_id=loc,
                        available_time_min=gap_min,
                        charger_site_id=charger_id,
                    )
                    slots.append(slot)
            except ValueError:
                pass

    duty.charging_opportunities = slots
    return slots
