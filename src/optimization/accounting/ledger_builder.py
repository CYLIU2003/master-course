from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .aggregators import build_accounting_summary
from .schema import AccountingArtifacts, EnergyFlowLedgerRow, VehicleEnergyLedgerRow, VehicleSlotLedgerRow
from src.optimization.common.time_axis import normalize_timestep_min

UNKNOWN_OPERATOR = "UNKNOWN_OPERATOR"


def _parse_date(value: Any, fallback: date) -> date:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return fallback


def _parse_dt(value: Any, fallback_date: date) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.combine(fallback_date, datetime.min.time())
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.combine(fallback_date, datetime.min.time())
    return parsed


def _slot_key_from_dt(dt: datetime, *, slot_minutes: int) -> Tuple[date, int]:
    minute = dt.hour * 60 + dt.minute
    slot_index = minute // slot_minutes
    return dt.date(), slot_index


def _slot_bounds(slot_date: date, slot_index: int, *, slot_minutes: int) -> tuple[str, str]:
    start = datetime.combine(slot_date, datetime.min.time()) + timedelta(minutes=slot_index * slot_minutes)
    end = start + timedelta(minutes=slot_minutes)
    return start.isoformat(), end.isoformat()


def _split_duration(start: datetime, end: datetime, *, slot_minutes: int) -> Iterable[tuple[date, int, float]]:
    if end <= start:
        return []
    current = start
    while current < end:
        slot_start_minute = (current.hour * 60 + current.minute) // slot_minutes * slot_minutes
        slot_start = datetime.combine(
            current.date(),
            datetime.min.time(),
            tzinfo=current.tzinfo,
        ) + timedelta(minutes=slot_start_minute)
        slot_end = slot_start + timedelta(minutes=slot_minutes)
        overlap_start = max(start, slot_start)
        overlap_end = min(end, slot_end)
        overlap = max((overlap_end - overlap_start).total_seconds() / 60.0, 0.0)
        if overlap > 0.0:
            yield current.date(), slot_start_minute // slot_minutes, overlap
        current = slot_end


def _vehicle_maps(problem: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    vehicle_by_id = {str(getattr(vehicle, "vehicle_id", "") or ""): vehicle for vehicle in list(getattr(problem, "vehicles", ()) or ())}
    vehicle_type_by_id = {
        str(getattr(vehicle_type, "vehicle_type_id", "") or ""): vehicle_type
        for vehicle_type in list(getattr(problem, "vehicle_types", ()) or ())
    }
    return vehicle_by_id, vehicle_type_by_id


def _vehicle_rates(vehicle: Any, vehicle_type: Any, metadata: Mapping[str, Any]) -> tuple[float, float, float]:
    energy_rate = max(
        float(
            getattr(vehicle, "energy_consumption_kwh_per_km", None)
            or getattr(vehicle_type, "energy_consumption_kwh_per_km", 0.0)
            or 0.0
        ),
        0.0,
    )
    fuel_rate = max(float(getattr(vehicle, "fuel_consumption_l_per_km", None) or getattr(vehicle_type, "fuel_consumption_l_per_km", 0.0) or 0.0), 0.0)
    co2_rate = max(
        float(
            getattr(vehicle_type, "co2_emission_kg_per_l", 0.0)
            or metadata.get("ice_co2_kg_per_l", 0.0)
            or 0.0
        ),
        0.0,
    )
    return energy_rate, fuel_rate, co2_rate


def _price_by_slot(problem: Any) -> Dict[int, float]:
    return {
        int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }


def _vehicle_initial_soc_kwh(vehicle: Any, capacity_kwh: float) -> float:
    value = getattr(vehicle, "initial_soc", None) if vehicle is not None else None
    if value is None:
        return capacity_kwh
    parsed = float(value)
    if parsed <= 1.0 and capacity_kwh > 0.0:
        return parsed * capacity_kwh
    return parsed


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _soc_by_vehicle_time(rows: Sequence[Mapping[str, Any]], *, slot_minutes: int) -> Dict[tuple[str, date, int], Mapping[str, Any]]:
    out: Dict[tuple[str, date, int], Mapping[str, Any]] = {}
    for row in rows:
        vehicle_id = str(row.get("vehicle_id") or "")
        time_text = str(row.get("time") or "")
        date_text = str(row.get("date") or "")
        if not vehicle_id or not time_text:
            continue
        try:
            slot_date = date.fromisoformat(date_text[:10]) if date_text else date.today()
            minute = int(time_text[:2]) * 60 + int(time_text[3:5])
        except Exception:
            continue
        out[(vehicle_id, slot_date, minute // slot_minutes)] = row
    return out


def _charge_by_vehicle_time(rows: Sequence[Mapping[str, Any]], *, slot_minutes: int) -> Dict[tuple[str, date, int], Mapping[str, Any]]:
    out: Dict[tuple[str, date, int], Mapping[str, Any]] = {}
    for row in rows:
        vehicle_id = str(row.get("vehicle_id") or "")
        time_text = str(row.get("time") or "")
        date_text = str(row.get("date") or "")
        if not vehicle_id or not time_text:
            continue
        try:
            slot_date = date.fromisoformat(date_text[:10]) if date_text else date.today()
            minute = int(time_text[:2]) * 60 + int(time_text[3:5])
        except Exception:
            continue
        out[(vehicle_id, slot_date, minute // slot_minutes)] = row
    return out


def _slot_minutes_from_time_text(time_text: str) -> int:
    try:
        return int(time_text[:2]) * 60 + int(time_text[3:5])
    except Exception:
        return 0


def _nested_get(mapping: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = mapping.get(key, default)
    return default if value in (None, "") else value


def _slot_factor(metadata: Mapping[str, Any], slot_index: int) -> float:
    raw = metadata.get("grid_co2_factor_by_slot", {})
    if isinstance(raw, Mapping):
        return float(raw.get(slot_index, raw.get(str(slot_index), 0.0)) or 0.0)
    if isinstance(raw, (list, tuple)) and 0 <= slot_index < len(raw):
        return float(raw[slot_index] or 0.0)
    return 0.0


def _build_vehicle_slot_ledger(
    *,
    problem: Any,
    scenario_id: str,
    run_id: str,
    service_date: date,
    weather_date: date,
    operator_id: str,
    trip_assignment_rows: Sequence[Mapping[str, Any]],
    vehicle_soc_timeseries_rows: Sequence[Mapping[str, Any]],
    vehicle_charging_source_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    slot_minutes: int,
) -> List[VehicleSlotLedgerRow]:
    vehicle_by_id, vehicle_type_by_id = _vehicle_maps(problem)
    price_by_slot = _price_by_slot(problem)
    soc_by_key = _soc_by_vehicle_time(vehicle_soc_timeseries_rows, slot_minutes=slot_minutes)
    charge_by_key = _charge_by_vehicle_time(vehicle_charging_source_rows, slot_minutes=slot_minutes)
    rows_by_key: Dict[tuple[str, date, int], Dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    rows_meta: Dict[tuple[str, date, int], Dict[str, Any]] = {}

    for trip in trip_assignment_rows:
        vehicle_id = str(trip.get("assigned_vehicle_id") or "")
        if not vehicle_id or str(trip.get("served_flag", True)).lower() in {"false", "0"}:
            continue
        start = _parse_dt(trip.get("actual_departure") or trip.get("scheduled_departure"), service_date)
        end = _parse_dt(trip.get("actual_arrival") or trip.get("scheduled_arrival"), service_date)
        if end <= start:
            end = start + timedelta(minutes=slot_minutes)
        service_duration_min = max((end - start).total_seconds() / 60.0, 1.0)
        for slot_date, slot_index, overlap_min in _split_duration(start, end, slot_minutes=slot_minutes):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            rows_meta.setdefault(key, dict(trip))
            share = overlap_min / service_duration_min
            bucket["service_km"] += float(trip.get("distance_km", 0.0) or 0.0) * share
            bucket["bev_drive_energy_kwh"] += float(trip.get("energy_used_kwh", 0.0) or 0.0) * share
            bucket["trip_id"] = str(trip.get("trip_id") or bucket.get("trip_id") or "")
            bucket["route_id"] = str(trip.get("route_id") or bucket.get("route_id") or "")
            bucket["route_short_name"] = str(trip.get("route_series_code") or trip.get("band_id") or bucket.get("route_short_name") or "")
            bucket["activity_type"] = "service"

        before_km = max(float(trip.get("deadhead_before_km", 0.0) or 0.0), 0.0)
        after_km = max(float(trip.get("deadhead_after_km", 0.0) or 0.0), 0.0)
        before_slot = _parse_dt(trip.get("actual_departure") or trip.get("scheduled_departure"), service_date)
        after_slot = _parse_dt(trip.get("actual_arrival") or trip.get("scheduled_arrival"), service_date)
        for slot_date, slot_index, overlap_min in _split_duration(before_slot - timedelta(minutes=slot_minutes), before_slot, slot_minutes=slot_minutes):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            bucket["deadhead_before_km"] += before_km * (overlap_min / slot_minutes)
            bucket["activity_type"] = bucket.get("activity_type") or "deadhead_before"
            rows_meta.setdefault(key, dict(trip))
        for slot_date, slot_index, overlap_min in _split_duration(after_slot, after_slot + timedelta(minutes=slot_minutes), slot_minutes=slot_minutes):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            bucket["deadhead_after_km"] += after_km * (overlap_min / slot_minutes)
            bucket["activity_type"] = bucket.get("activity_type") or "deadhead_after"
            rows_meta.setdefault(key, dict(trip))

    for key, soc_row in soc_by_key.items():
        vehicle_id, slot_date, slot_index = key
        bucket = rows_by_key[key]
        observed_soc = _finite_float(soc_row.get("soc_kwh"))
        if observed_soc is None:
            bucket["soc_nan_observed"] = 1.0
        else:
            bucket["soc_end_kwh"] = observed_soc
            bucket["soc_observed"] = 1.0
        bucket["state"] = str(soc_row.get("state") or "")
        rows_meta.setdefault(key, {})

    for key, charge_row in charge_by_key.items():
        vehicle_id, slot_date, slot_index = key
        bucket = rows_by_key[key]
        bucket["charge_input_kwh"] += float(charge_row.get("total_charge_kwh", 0.0) or 0.0)
        bucket["charger_grid_kwh"] += float(charge_row.get("grid_to_vehicle_kwh", 0.0) or 0.0)
        bucket["charger_pv_direct_kwh"] += float(charge_row.get("pv_to_vehicle_kwh", 0.0) or 0.0)
        bucket["charger_bess_kwh"] += float(charge_row.get("bess_to_vehicle_kwh", 0.0) or 0.0)
        bucket["activity_type"] = bucket.get("activity_type") or "charging"
        rows_meta.setdefault(key, {})

    ledger_rows: List[VehicleSlotLedgerRow] = []
    current_soc_by_vehicle: Dict[str, float] = {}
    for key in sorted(rows_by_key.keys(), key=lambda item: (item[0], item[1].isoformat(), item[2])):
        vehicle_id, slot_date, slot_index = key
        vehicle = vehicle_by_id.get(vehicle_id)
        vehicle_type = str(getattr(vehicle, "vehicle_type", "") or rows_meta.get(key, {}).get("assigned_vehicle_type", "") or "")
        vehicle_type_obj = vehicle_type_by_id.get(vehicle_type)
        capacity_kwh = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
        if capacity_kwh <= 0.0 and vehicle_type_obj is not None:
            capacity_kwh = max(float(getattr(vehicle_type_obj, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
        energy_rate, fuel_rate, co2_rate = _vehicle_rates(vehicle, vehicle_type_obj, metadata)
        bucket = rows_by_key[key]
        trip_meta = rows_meta.get(key, {})
        charge_input_kwh = float(bucket.get("charge_input_kwh", 0.0) or 0.0)
        grid_to_vehicle_kwh = float(bucket.get("charger_grid_kwh", 0.0) or 0.0)
        pv_to_vehicle_kwh = float(bucket.get("charger_pv_direct_kwh", 0.0) or 0.0)
        bess_to_vehicle_kwh = float(bucket.get("charger_bess_kwh", 0.0) or 0.0)
        service_km = float(bucket.get("service_km", 0.0) or 0.0)
        deadhead_before_km = float(bucket.get("deadhead_before_km", 0.0) or 0.0)
        deadhead_after_km = float(bucket.get("deadhead_after_km", 0.0) or 0.0)
        deadhead_total_km = deadhead_before_km + deadhead_after_km
        bev_drive_energy_kwh = float(bucket.get("bev_drive_energy_kwh", 0.0) or 0.0)
        if not bev_drive_energy_kwh and service_km > 0.0:
            bev_drive_energy_kwh = service_km * energy_rate
        charge_efficiency = max(float(getattr(vehicle, "charge_efficiency", 0.95) or 0.95), 0.0)
        charge_to_battery_kwh = charge_input_kwh * charge_efficiency
        charge_loss_kwh = charge_input_kwh - charge_to_battery_kwh
        tou_price = float(price_by_slot.get(slot_index, 0.0) or 0.0)
        fuel_liter = 0.0
        if vehicle_type.upper() == "ICE":
            fuel_liter = max((service_km + deadhead_total_km) * fuel_rate, 0.0)
        ice_co2_kg = fuel_liter * co2_rate
        battery_degradation_rate = float(metadata.get("battery_degradation_price_jpy_per_kwh", 0.0) or 0.0)
        electricity_cost_jpy = float(bucket.get("charger_grid_kwh", 0.0) or 0.0) * tou_price
        fuel_cost_jpy = fuel_liter * float(metadata.get("fuel_price_jpy_per_liter", 0.0) or 0.0)
        co2_cost_jpy = ice_co2_kg * float(metadata.get("co2_price_jpy_per_kg", 0.0) or 0.0)
        battery_degradation_cost_jpy = charge_input_kwh * battery_degradation_rate
        if vehicle_id not in current_soc_by_vehicle:
            current_soc_by_vehicle[vehicle_id] = _vehicle_initial_soc_kwh(vehicle, capacity_kwh) if capacity_kwh > 0.0 else 0.0
        soc_start_kwh = current_soc_by_vehicle.get(vehicle_id, 0.0)
        predicted_soc_end_kwh = soc_start_kwh + charge_to_battery_kwh - bev_drive_energy_kwh
        observed_soc_end = _finite_float(bucket.get("soc_end_kwh")) if bucket.get("soc_observed") else None
        soc_end_kwh = observed_soc_end if observed_soc_end is not None else predicted_soc_end_kwh
        current_soc_by_vehicle[vehicle_id] = soc_end_kwh
        soc_balance_error_kwh = soc_end_kwh - soc_start_kwh - charge_to_battery_kwh + bev_drive_energy_kwh
        source_balance_error_kwh = charge_input_kwh - grid_to_vehicle_kwh - pv_to_vehicle_kwh - bess_to_vehicle_kwh
        fuel_start_l = fuel_liter
        fuel_end_l = 0.0
        fuel_balance_error_l = fuel_end_l - fuel_start_l + fuel_liter
        soc_delta_charge_ratio = charge_to_battery_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_delta_drive_ratio = bev_drive_energy_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_start_ratio = soc_start_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_end_ratio = soc_end_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_min_kwh = max(float(getattr(vehicle, "reserve_soc", 0.0) or 0.0), 0.0) if vehicle is not None else 0.0
        soc_max_kwh = capacity_kwh
        violation_types: List[str] = []
        if bool(bucket.get("soc_nan_observed", 0.0)):
            violation_types.append("soc_nan_observed")
        if capacity_kwh > 0.0:
            tol = 1.0e-6
            if soc_start_kwh < soc_min_kwh - tol:
                violation_types.append("soc_start_below_min")
            if soc_end_kwh < soc_min_kwh - tol:
                violation_types.append("soc_end_below_min")
            if soc_start_kwh > soc_max_kwh + tol:
                violation_types.append("soc_start_above_max")
            if soc_end_kwh > soc_max_kwh + tol:
                violation_types.append("soc_end_above_max")
            if not math.isfinite(soc_start_kwh) or not math.isfinite(soc_end_kwh):
                violation_types.append("soc_non_finite")
        slot_start, slot_end = _slot_bounds(slot_date, slot_index, slot_minutes=slot_minutes)
        activity_type = str(bucket.get("activity_type") or "idle")
        provenance_exact = bool(metadata.get("charging_source_provenance_exact", False))
        if not provenance_exact:
            provenance_mode = "inferred"
        elif trip_meta:
            provenance_mode = "exact"
        else:
            provenance_mode = "exact"
        ledger_rows.append(
            VehicleSlotLedgerRow(
                scenario_id=scenario_id,
                run_id=run_id,
                service_date=service_date.isoformat(),
                weather_date=weather_date.isoformat(),
                operator_id=operator_id,
                vehicle_id=vehicle_id,
                vehicle_type=vehicle_type,
                slot_start=slot_start,
                slot_end=slot_end,
                slot_index=slot_index,
                slot_minutes=slot_minutes,
                route_id=str(bucket.get("route_id") or trip_meta.get("route_id") or ""),
                route_short_name=str(bucket.get("route_short_name") or trip_meta.get("route_series_code") or ""),
                trip_id=str(bucket.get("trip_id") or trip_meta.get("trip_id") or ""),
                block_id=str(trip_meta.get("block_id") or ""),
                activity_type=activity_type,
                source_event_id=str(bucket.get("trip_id") or trip_meta.get("trip_id") or f"{vehicle_id}:{slot_index}"),
                service_km=service_km,
                deadhead_before_km=deadhead_before_km,
                deadhead_after_km=deadhead_after_km,
                deadhead_total_km=deadhead_total_km,
                bev_drive_energy_kwh=bev_drive_energy_kwh,
                drive_consumption_kwh=bev_drive_energy_kwh,
                aux_consumption_kwh=0.0,
                ice_fuel_liter=fuel_liter,
                ice_co2_kg=ice_co2_kg,
                charge_input_kwh=charge_input_kwh,
                charger_grid_kwh=grid_to_vehicle_kwh,
                charger_pv_direct_kwh=pv_to_vehicle_kwh,
                charger_bess_kwh=bess_to_vehicle_kwh,
                charge_loss_kwh=charge_loss_kwh,
                soc_start_kwh=soc_start_kwh,
                soc_end_kwh=soc_end_kwh,
                battery_capacity_kwh=capacity_kwh,
                charge_to_battery_kwh=charge_to_battery_kwh,
                fuel_start_l=fuel_start_l,
                fuel_end_l=fuel_end_l,
                refuel_l=0.0,
                soc_balance_error_kwh=soc_balance_error_kwh,
                fuel_balance_error_l=fuel_balance_error_l,
                charge_source_balance_error_kwh=source_balance_error_kwh,
                soc_start_ratio=soc_start_ratio,
                soc_end_ratio=soc_end_ratio,
                soc_delta_charge_ratio=soc_delta_charge_ratio,
                soc_delta_drive_ratio=soc_delta_drive_ratio,
                soc_delta_loss_ratio=0.0,
                soc_violation_flag=bool(violation_types),
                soc_violation_type=";".join(sorted(set(violation_types))),
                tou_energy_price_jpy_per_kwh=tou_price,
                fuel_price_jpy_per_liter=float(metadata.get("fuel_price_jpy_per_liter", 0.0) or 0.0),
                battery_degradation_price_jpy_per_kwh=battery_degradation_rate,
                electricity_cost_jpy=electricity_cost_jpy,
                fuel_cost_jpy=fuel_cost_jpy,
                co2_cost_jpy=co2_cost_jpy,
                battery_degradation_cost_jpy=battery_degradation_cost_jpy,
                provenance_mode=provenance_mode,
                repair_reason=str(metadata.get("repair_reason", "") or ""),
                created_by_stage=str(metadata.get("created_by_stage", "reporting_aggregation") or "reporting_aggregation"),
            )
        )
    return ledger_rows


def _build_energy_flow_ledger(
    *,
    scenario_id: str,
    run_id: str,
    service_date: date,
    weather_date: date,
    operator_id: str,
    energy_flow_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    slot_minutes: int,
) -> List[EnergyFlowLedgerRow]:
    rows: List[EnergyFlowLedgerRow] = []
    cumulative_grid_kwh_by_depot: Dict[str, float] = defaultdict(float)
    cumulative_cost_by_depot: Dict[str, float] = defaultdict(float)
    for row in energy_flow_rows:
        depot_id = str(row.get("depot_id") or metadata.get("depot_id") or "")
        time_text = str(row.get("time") or "")
        date_text = str(row.get("date") or service_date.isoformat())
        row_date = _parse_date(date_text, service_date)
        slot_index = _slot_minutes_from_time_text(time_text) // slot_minutes
        slot_start, slot_end = _slot_bounds(row_date, slot_index, slot_minutes=slot_minutes)
        slot_hours = slot_minutes / 60.0
        pv_generation_kwh = float(
            row.get(
                "pv_generation_slot_kwh",
                row.get("pv_generation_kwh", float(row.get("pv_generation_kw", 0.0) or 0.0) * slot_hours),
            )
            or 0.0
        )
        pv_to_bus_kwh = float(row.get("pv_to_bus_kwh", row.get("pv_to_bus_slot_kwh", 0.0)) or 0.0)
        pv_to_bess_kwh = float(row.get("pv_to_bess_kwh", row.get("pv_to_bess_slot_kwh", 0.0)) or 0.0)
        pv_curtailed_kwh = float(
            row.get(
                "pv_curtailment_kwh",
                row.get("pv_curtailed_kwh", row.get("pv_curtailed_slot_kwh", row.get("pv_curtail_kwh", 0.0))),
            )
            or 0.0
        )
        pv_export_kwh = float(row.get("pv_export_kwh", 0.0) or 0.0)
        bess_to_bus_kwh = float(row.get("bess_to_bus_kwh", row.get("bess_to_bus_slot_kwh", 0.0)) or 0.0)
        grid_to_bus_kwh = float(row.get("grid_to_bus_kwh", row.get("grid_to_bus_slot_kwh", 0.0)) or 0.0)
        grid_to_bess_kwh = float(row.get("grid_to_bess_kwh", row.get("grid_to_bess_slot_kwh", 0.0)) or 0.0)
        grid_total_kwh = float(
            row.get(
                "grid_import_kwh",
                row.get("grid_total_kwh", row.get("grid_import_slot_kwh", grid_to_bus_kwh + grid_to_bess_kwh)),
            )
            or 0.0
        )
        if not grid_total_kwh:
            grid_total_kwh = grid_to_bus_kwh + grid_to_bess_kwh
        grid_kw = float(row.get("grid_kw", row.get("grid_import_kw", grid_total_kwh / slot_hours if slot_hours > 0 else 0.0)) or 0.0)
        price = float(row.get("energy_price_yen_per_kwh", row.get("tou_energy_price_jpy_per_kwh", 0.0)) or 0.0)
        grid_co2_factor = float(row.get("grid_emission_factor_kg_per_kwh", row.get("grid_co2_factor_kg_per_kwh", _slot_factor(metadata, slot_index))) or 0.0)
        bess_unit_cost = float(row.get("bess_to_bus_unit_cost_jpy_per_kwh", row.get("bess_to_bus_unit_cost_yen_per_kwh", metadata.get("bess_to_bus_unit_cost_yen_per_kwh", 0.0))) or 0.0)
        pv_to_bus_cost = float(row.get("pv_to_bus_cost_jpy", pv_to_bus_kwh * bess_unit_cost) or 0.0)
        pv_to_bess_cost = float(row.get("pv_to_bess_cost_jpy", pv_to_bess_kwh * bess_unit_cost) or 0.0)
        bess_to_bus_cost = float(row.get("bess_to_bus_cost_jpy", bess_to_bus_kwh * bess_unit_cost) or 0.0)
        bess_total_flow_cost = float(row.get("bess_total_flow_cost_jpy", pv_to_bus_cost + pv_to_bess_cost + bess_to_bus_cost) or 0.0)
        bess_soc_start = float(row.get("bess_soc_start_kwh", row.get("bess_soc_kwh", 0.0)) or 0.0)
        bess_soc_end = float(row.get("bess_soc_end_kwh", row.get("bess_soc_kwh", 0.0)) or 0.0)
        bess_capacity = float(row.get("bess_capacity_kwh", metadata.get("bess_capacity_kwh", 0.0)) or 0.0)
        bess_soc_min = float(row.get("bess_soc_min_kwh", metadata.get("bess_soc_min_kwh", 0.0)) or 0.0)
        bess_soc_max = float(row.get("bess_soc_max_kwh", metadata.get("bess_soc_max_kwh", 0.0)) or 0.0)
        bess_terminal_soc_min = float(row.get("bess_terminal_soc_min_kwh", metadata.get("bess_terminal_soc_min_kwh", 0.0)) or 0.0)
        bess_soc_violation = 0.0
        if bess_soc_max > 0.0:
            bess_soc_violation += max(bess_soc_start - bess_soc_max, 0.0) + max(bess_soc_end - bess_soc_max, 0.0)
        if bess_soc_min > 0.0:
            bess_soc_violation += max(bess_soc_min - bess_soc_start, 0.0) + max(bess_soc_min - bess_soc_end, 0.0)
        energy_cost_jpy = grid_total_kwh * price
        cumulative_grid_kwh_by_depot[depot_id] += grid_total_kwh
        cumulative_cost_by_depot[depot_id] += energy_cost_jpy
        pv_balance_error = pv_generation_kwh - pv_to_bus_kwh - pv_to_bess_kwh - pv_curtailed_kwh - pv_export_kwh
        grid_balance_error = grid_total_kwh - grid_to_bus_kwh - grid_to_bess_kwh
        contract_limit_kw = float(row.get("contract_limit_kw", 0.0) or 0.0)
        contract_overage_kw = float(row.get("contract_over_limit_kw", 0.0) or 0.0)
        contract_overage_cost_jpy = float(row.get("contract_overage_cost_jpy", 0.0) or 0.0)
        demand_rate = float(metadata.get("demand_rate_jpy_per_kw", row.get("demand_rate_jpy_per_kw", 0.0)) or 0.0)
        rows.append(
            EnergyFlowLedgerRow(
                scenario_id=scenario_id,
                run_id=run_id,
                service_date=service_date.isoformat(),
                weather_date=weather_date.isoformat(),
                operator_id=operator_id,
                depot_id=depot_id,
                slot_start=slot_start,
                slot_end=slot_end,
                slot_index=slot_index,
                slot_minutes=slot_minutes,
                timestamp=slot_start,
                pv_generation_kwh=pv_generation_kwh,
                pv_to_bus_kwh=pv_to_bus_kwh,
                pv_to_bess_kwh=pv_to_bess_kwh,
                pv_curtailed_kwh=pv_curtailed_kwh,
                pv_curtailment_kwh=pv_curtailed_kwh,
                pv_export_kwh=pv_export_kwh,
                bess_to_bus_kwh=bess_to_bus_kwh,
                bess_charge_kwh=pv_to_bess_kwh + grid_to_bess_kwh,
                bess_discharge_kwh=bess_to_bus_kwh,
                bess_soc_start_kwh=bess_soc_start,
                bess_soc_end_kwh=bess_soc_end,
                bess_capacity_kwh=bess_capacity,
                bess_soc_min_kwh=bess_soc_min,
                bess_soc_max_kwh=bess_soc_max,
                bess_terminal_soc_min_kwh=bess_terminal_soc_min,
                bess_to_bus_unit_cost_jpy_per_kwh=bess_unit_cost,
                pv_to_bess_cost_jpy=pv_to_bess_cost,
                pv_to_bus_cost_jpy=pv_to_bus_cost,
                bess_to_bus_cost_jpy=bess_to_bus_cost,
                bess_total_flow_cost_jpy=bess_total_flow_cost,
                bess_soc_violation_kwh=bess_soc_violation,
                grid_to_bus_kwh=grid_to_bus_kwh,
                grid_to_bess_kwh=grid_to_bess_kwh,
                depot_aux_grid_kwh=0.0,
                grid_total_kwh=grid_total_kwh,
                grid_kw=grid_kw,
                grid_import_kw=grid_kw,
                grid_import_kwh=grid_total_kwh,
                bus_charging_total_kwh=grid_to_bus_kwh + pv_to_bus_kwh + bess_to_bus_kwh,
                grid_import_cumulative_kwh=cumulative_grid_kwh_by_depot[depot_id],
                grid_purchase_cost_jpy=energy_cost_jpy,
                grid_purchase_cumulative_cost_jpy=cumulative_cost_by_depot[depot_id],
                pv_balance_error_kwh=pv_balance_error,
                grid_balance_error_kwh=grid_balance_error,
                tou_energy_price_jpy_per_kwh=price,
                grid_emission_factor_kg_per_kwh=grid_co2_factor,
                energy_cost_jpy=energy_cost_jpy,
                demand_rate_jpy_per_kw=demand_rate,
                demand_cost_jpy=0.0,
                contract_power_kw=contract_limit_kw,
                contract_power_exceeded=bool(float(row.get("contract_limit_exceeded", False) or False)),
                contract_overage_kw=contract_overage_kw,
                contract_overage_cost_jpy=contract_overage_cost_jpy,
                provenance_mode="exact" if bool(row.get("source_provenance_exact", False)) else "inferred",
                repair_reason=str(metadata.get("repair_reason", "") or ""),
                created_by_stage=str(metadata.get("created_by_stage", "reporting_aggregation") or "reporting_aggregation"),
            )
        )
    return rows


def _build_vehicle_energy_ledger(
    vehicle_rows: Sequence[VehicleSlotLedgerRow],
    *,
    metadata: Mapping[str, Any],
) -> List[VehicleEnergyLedgerRow]:
    vehicle_usage_unit = max(float(metadata.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0), 0.0)
    used_vehicle_days = {
        (row.vehicle_id, row.slot_start[:10])
        for row in vehicle_rows
        if row.trip_id and row.activity_type == "service"
    }
    usage_allocation = vehicle_usage_unit if vehicle_usage_unit > 0.0 else 0.0
    energy_rows: List[VehicleEnergyLedgerRow] = []
    usage_allocated_days: set[tuple[str, str]] = set()
    for row in vehicle_rows:
        battery = max(float(row.battery_capacity_kwh or 0.0), 0.0)
        soc_delta = float(row.soc_end_kwh or 0.0) - float(row.soc_start_kwh or 0.0)
        fuel_delta = float(row.fuel_end_l or 0.0) - float(row.fuel_start_l or 0.0)
        vehicle_day = (row.vehicle_id, row.slot_start[:10])
        is_used_service_day = vehicle_day in used_vehicle_days and row.activity_type == "service" and vehicle_day not in usage_allocated_days
        if is_used_service_day:
            usage_allocated_days.add(vehicle_day)
        energy_rows.append(
            VehicleEnergyLedgerRow(
                scenario_id=row.scenario_id,
                run_id=row.run_id,
                operator_id=row.operator_id,
                service_date=row.service_date,
                weather_date=row.weather_date,
                vehicle_id=row.vehicle_id,
                vehicle_type=row.vehicle_type,
                depot_id=str(metadata.get("depot_id") or ""),
                slot_index=row.slot_index,
                slot_start=row.slot_start,
                slot_end=row.slot_end,
                slot_minutes=row.slot_minutes,
                activity_type=row.activity_type,
                trip_id=row.trip_id,
                route_id=row.route_id,
                route_family_code=row.route_short_name,
                distance_km=row.service_km,
                deadhead_km=row.deadhead_total_km,
                duration_min=float(row.slot_minutes),
                soc_start_kwh=row.soc_start_kwh,
                soc_end_kwh=row.soc_end_kwh,
                soc_delta_kwh=soc_delta,
                battery_capacity_kwh=battery,
                soc_start_pct=(row.soc_start_kwh / battery * 100.0) if battery > 0.0 else 0.0,
                soc_end_pct=(row.soc_end_kwh / battery * 100.0) if battery > 0.0 else 0.0,
                bev_drive_consumption_kwh=row.bev_drive_energy_kwh,
                charge_input_kwh=row.charge_input_kwh,
                charge_to_battery_kwh=row.charge_to_battery_kwh,
                charge_loss_kwh=row.charge_loss_kwh,
                grid_to_vehicle_kwh=row.charger_grid_kwh,
                pv_to_vehicle_kwh=row.charger_pv_direct_kwh,
                bess_to_vehicle_kwh=row.charger_bess_kwh,
                charge_source_balance_error_kwh=row.charge_source_balance_error_kwh,
                soc_balance_error_kwh=row.soc_balance_error_kwh,
                fuel_start_l=row.fuel_start_l,
                fuel_end_l=row.fuel_end_l,
                fuel_delta_l=fuel_delta,
                fuel_consumed_l=row.ice_fuel_liter,
                refuel_l=row.refuel_l,
                fuel_balance_error_l=row.fuel_balance_error_l,
                diesel_price_yen_per_l=row.fuel_price_jpy_per_liter,
                fuel_cost_jpy=row.fuel_cost_jpy,
                ice_co2_kg=row.ice_co2_kg,
                electricity_price_yen_per_kwh=row.tou_energy_price_jpy_per_kwh,
                electricity_cost_jpy=row.electricity_cost_jpy,
                vehicle_usage_cost_allocated_jpy=usage_allocation if is_used_service_day else 0.0,
                co2_cost_jpy=row.co2_cost_jpy,
                source_allocation_method=str(metadata.get("vehicle_charging_source_allocation_method", "proportional_by_timestep") or "proportional_by_timestep"),
                provenance_mode=row.provenance_mode,
                repair_reason=row.repair_reason,
                created_by_stage=row.created_by_stage,
            )
        )
    return energy_rows


def _build_fuel_canonical_ledger(
    vehicle_energy_rows: Sequence[VehicleEnergyLedgerRow],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in vehicle_energy_rows:
        fuel_l = float(row.fuel_consumed_l or 0.0)
        refuel_l = float(row.refuel_l or 0.0)
        if abs(fuel_l) <= 1.0e-12 and abs(refuel_l) <= 1.0e-12:
            continue
        distance_km = float(row.distance_km or 0.0) + float(row.deadhead_km or 0.0)
        rows.append(
            {
                "timestamp": row.slot_start,
                "service_date": row.service_date,
                "vehicle_id": row.vehicle_id,
                "operator_id": row.operator_id,
                "vehicle_type": row.vehicle_type,
                "trip_id": row.trip_id,
                "route_id": row.route_id,
                "distance_km": distance_km,
                "fuel_efficiency_km_per_l": distance_km / fuel_l if fuel_l > 0.0 else 0.0,
                "fuel_consumption_l": fuel_l,
                "refuel_l": refuel_l,
                "fuel_cost_jpy": float(row.fuel_cost_jpy or 0.0),
                "ice_co2_kg": float(row.ice_co2_kg or 0.0),
                "diesel_price_jpy_per_l": float(row.diesel_price_yen_per_l or 0.0),
                "fuel_emission_factor_kg_per_l": (float(row.ice_co2_kg or 0.0) / fuel_l) if fuel_l > 0.0 else 0.0,
            }
        )
    return rows


def _build_fuel_timeseries(fuel_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in fuel_rows:
        timestamp = str(row.get("timestamp") or "")
        service_date = str(row.get("service_date") or timestamp[:10])
        key = (service_date, timestamp)
        target = grouped.setdefault(
            key,
            {
                "timestamp": timestamp,
                "service_date": service_date,
                "fuel_consumption_l": 0.0,
                "refuel_l": 0.0,
                "fuel_cost_jpy": 0.0,
                "ice_co2_kg": 0.0,
                "fuel_source_of_truth": "fuel_canonical_ledger",
            },
        )
        target["fuel_consumption_l"] += float(row.get("fuel_consumption_l", 0.0) or 0.0)
        target["refuel_l"] += float(row.get("refuel_l", 0.0) or 0.0)
        target["fuel_cost_jpy"] += float(row.get("fuel_cost_jpy", 0.0) or 0.0)
        target["ice_co2_kg"] += float(row.get("ice_co2_kg", 0.0) or 0.0)
    return [grouped[key] for key in sorted(grouped.keys())]


def _build_co2_timeseries(
    energy_rows: Sequence[EnergyFlowLedgerRow],
    fuel_timeseries_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    fuel_by_timestamp = {
        str(row.get("timestamp") or ""): row
        for row in fuel_timeseries_rows
    }
    timestamps = sorted({row.slot_start for row in energy_rows} | set(fuel_by_timestamp.keys()))
    rows: List[Dict[str, Any]] = []
    for timestamp in timestamps:
        matching_energy = [row for row in energy_rows if row.slot_start == timestamp]
        grid_import_kwh = sum(float(row.grid_import_kwh or 0.0) for row in matching_energy)
        grid_co2_kg = sum(float(row.grid_import_kwh or 0.0) * float(row.grid_emission_factor_kg_per_kwh or 0.0) for row in matching_energy)
        avg_factor = grid_co2_kg / grid_import_kwh if grid_import_kwh > 0.0 else 0.0
        fuel_row = fuel_by_timestamp.get(timestamp, {})
        fuel_l = float(fuel_row.get("fuel_consumption_l", 0.0) or 0.0)
        ice_co2_kg = float(fuel_row.get("ice_co2_kg", 0.0) or 0.0)
        rows.append(
            {
                "timestamp": timestamp,
                "service_date": str(timestamp[:10]),
                "grid_import_kwh": grid_import_kwh,
                "grid_emission_factor_kg_per_kwh": avg_factor,
                "grid_co2_kg": grid_co2_kg,
                "fuel_consumption_l": fuel_l,
                "fuel_emission_factor_kg_per_l": ice_co2_kg / fuel_l if fuel_l > 0.0 else 0.0,
                "ice_co2_kg": ice_co2_kg,
                "total_co2_kg": grid_co2_kg + ice_co2_kg,
                "co2_boundary": "grid_plus_ice",
                "co2_accounting_method": "grid_import_based",
                "bess_co2_source_tracking": False,
            }
        )
    return rows


def _build_initial_soc_ledger(
    problem: Any,
    *,
    operator_id: str,
    metadata: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    policy = str(metadata.get("initial_soc_policy") or metadata.get("initial_soc_source") or "scenario_file")
    seed = metadata.get("initial_soc_random_seed", metadata.get("random_seed", ""))
    configured_min = metadata.get("initial_soc_min_ratio")
    configured_max = metadata.get("initial_soc_max_ratio")
    for vehicle in list(getattr(problem, "vehicles", ()) or ()):  # type: ignore[attr-defined]
        vehicle_type = str(getattr(vehicle, "vehicle_type", "") or "")
        capacity = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
        if capacity <= 0.0:
            continue
        initial_kwh = _vehicle_initial_soc_kwh(vehicle, capacity)
        reserve_kwh = max(float(getattr(vehicle, "reserve_soc", 0.0) or 0.0), 0.0)
        rows.append(
            {
                "vehicle_id": str(getattr(vehicle, "vehicle_id", "") or ""),
                "operator_id": operator_id,
                "depot_id": str(getattr(vehicle, "home_depot_id", "") or ""),
                "vehicle_type": vehicle_type,
                "battery_capacity_kwh": capacity,
                "initial_soc_ratio": initial_kwh / capacity if capacity > 0.0 else 0.0,
                "initial_soc_kwh": initial_kwh,
                "initial_soc_source": policy,
                "random_seed": seed,
                "soc_min_ratio": reserve_kwh / capacity if capacity > 0.0 else 0.0,
                "soc_max_ratio": 1.0,
                "configured_initial_soc_min_ratio": configured_min,
                "configured_initial_soc_max_ratio": configured_max,
            }
        )
    return rows


def _build_initial_soc_precheck(
    initial_soc_rows: Sequence[Mapping[str, Any]],
    vehicle_rows: Sequence[VehicleSlotLedgerRow],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rows_by_vehicle: Dict[str, List[VehicleSlotLedgerRow]] = defaultdict(list)
    for row in vehicle_rows:
        rows_by_vehicle[row.vehicle_id].append(row)
    for initial in initial_soc_rows:
        vehicle_id = str(initial.get("vehicle_id") or "")
        vehicle_slots = sorted(rows_by_vehicle.get(vehicle_id, []), key=lambda row: row.slot_start)
        service_slots = [row for row in vehicle_slots if row.trip_id and row.activity_type == "service"]
        first_service = service_slots[0] if service_slots else None
        first_start = first_service.slot_start if first_service is not None else ""
        charge_before = sum(float(row.charge_to_battery_kwh or 0.0) for row in vehicle_slots if first_start and row.slot_start < first_start)
        required = 0.0
        if first_service is not None:
            for row in service_slots:
                if row.slot_start < first_start:
                    continue
                required += float(row.bev_drive_energy_kwh or 0.0)
                later_charge = any(float(slot.charge_input_kwh or 0.0) > 0.0 and slot.slot_start > row.slot_start for slot in vehicle_slots)
                if later_charge:
                    break
        initial_kwh = float(initial.get("initial_soc_kwh", 0.0) or 0.0)
        soc_min_kwh = float(initial.get("soc_min_ratio", 0.0) or 0.0) * float(initial.get("battery_capacity_kwh", 0.0) or 0.0)
        if initial_kwh < soc_min_kwh - 1.0e-6:
            status = "ERROR_INITIAL_SOC_BELOW_MIN"
            message = "Initial SOC is below reserve SOC."
        elif first_service is not None and initial_kwh + charge_before - required < soc_min_kwh - 1.0e-6:
            status = "ERROR_CANNOT_SERVE_FIRST_TRIP"
            message = "Initial SOC plus reachable pre-charge cannot cover early assigned work before next charge."
        elif initial_kwh < soc_min_kwh + 1.0e-6:
            status = "WARNING_LOW_INITIAL_SOC"
            message = "Initial SOC is at the reserve boundary."
        else:
            status = "OK"
            message = "Initial SOC precheck passed."
        rows.append(
            {
                "vehicle_id": vehicle_id,
                "initial_soc_kwh": initial_kwh,
                "soc_min_kwh": soc_min_kwh,
                "first_assigned_trip_id": first_service.trip_id if first_service is not None else "",
                "time_until_first_trip_min": 0.0,
                "max_charge_before_first_trip_kwh": charge_before,
                "required_energy_until_next_charge_kwh": required,
                "precheck_status": status,
                "precheck_message": message,
            }
        )
    return rows


def _build_data_flow_validation(
    *,
    vehicle_slot_rows: Sequence[VehicleSlotLedgerRow],
    vehicle_energy_rows: Sequence[VehicleEnergyLedgerRow],
    energy_rows: Sequence[EnergyFlowLedgerRow],
    fuel_canonical_rows: Sequence[Mapping[str, Any]],
    fuel_timeseries_rows: Sequence[Mapping[str, Any]],
    co2_rows: Sequence[Mapping[str, Any]],
    initial_soc_rows: Sequence[Mapping[str, Any]],
    initial_soc_precheck_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    def _sum(rows: Sequence[Any], attr: str) -> float:
        return float(sum(float(getattr(row, attr, 0.0) or 0.0) for row in rows))

    def _sum_dict(rows: Sequence[Mapping[str, Any]], key: str) -> float:
        return float(sum(float(row.get(key, 0.0) or 0.0) for row in rows))

    checks: List[Dict[str, Any]] = []

    def add(
        name: str,
        actual: float,
        expected: float,
        tol: float = 1.0e-6,
        *,
        severity: str = "ERROR",
        message: str = "",
        source_files: str = "canonical ledgers",
    ) -> None:
        diff = actual - expected
        ok = abs(diff) <= tol
        checks.append({
            "check_name": name,
            "status": "OK" if ok else "NG",
            "expected_value": expected,
            "actual_value": actual,
            "difference": diff,
            "tolerance": tol,
            "severity": "INFO" if ok else severity,
            "message": message or ("OK" if ok else f"{name} differs by {diff}"),
            "source_files": source_files,
        })

    def skip(name: str, *, severity: str = "INFO", message: str = "Input rows are unavailable.", source_files: str = "canonical ledgers") -> None:
        checks.append({
            "check_name": name,
            "status": "SKIPPED",
            "expected_value": "",
            "actual_value": "",
            "difference": "",
            "tolerance": "",
            "severity": severity,
            "message": message,
            "source_files": source_files,
        })

    pv_generation = _sum(energy_rows, "pv_generation_kwh")
    pv_to_bus = _sum(energy_rows, "pv_to_bus_kwh")
    pv_to_bess = _sum(energy_rows, "pv_to_bess_kwh")
    pv_curtailed = _sum(energy_rows, "pv_curtailed_kwh")
    pv_export = _sum(energy_rows, "pv_export_kwh")
    grid_import = _sum(energy_rows, "grid_import_kwh")
    grid_to_bus = _sum(energy_rows, "grid_to_bus_kwh")
    grid_to_bess = _sum(energy_rows, "grid_to_bess_kwh")
    aux_grid = _sum(energy_rows, "depot_aux_grid_kwh")
    bess_to_bus = _sum(energy_rows, "bess_to_bus_kwh")
    bus_charge = grid_to_bus + pv_to_bus + bess_to_bus

    add("pv_generation_matches_pv_timeseries", pv_generation, float(summary.get("pv_generation_timeseries_total_kwh", pv_generation) or 0.0), 1.0e-3, source_files="energy_flow_ledger.csv;pv_generation_timeseries.csv")
    add("pv_generation_matches_depot_energy_flows", pv_generation, float(summary.get("depot_energy_flows_pv_generation_total_kwh", pv_generation) or 0.0), 1.0e-3, source_files="energy_flow_ledger.csv;depot_energy_flows.csv")
    add("pv_generation_balance", pv_to_bus + pv_to_bess + pv_curtailed + pv_export, pv_generation, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("pv_to_bess_matches_pv_balance", pv_to_bus + pv_to_bess + pv_curtailed + pv_export, pv_generation, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("kpi_pv_generation_matches_energy_flow_ledger", float(summary.get("pv_generation_kwh", 0.0) or 0.0), pv_generation, 1.0e-6, source_files="kpi_summary.json;energy_flow_ledger.csv")
    add("grid_import_balance", grid_to_bus + grid_to_bess + aux_grid, grid_import, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("bus_charging_source_balance", bus_charge, float(summary.get("bus_charging_total_kwh", summary.get("total_charge_input_kwh", bus_charge)) or 0.0), 1.0e-3, source_files="energy_flow_ledger.csv;vehicle_energy_ledger.csv")
    add("bess_to_bus_matches_bus_charging_balance", grid_to_bus + pv_to_bus + bess_to_bus, bus_charge, 1.0e-6, source_files="energy_flow_ledger.csv")
    add("vehicle_total_charge_equals_bus_charging", _sum(vehicle_energy_rows, "charge_input_kwh"), bus_charge, 1.0e-3, source_files="vehicle_energy_ledger.csv;energy_flow_ledger.csv")
    add("vehicle_grid_to_vehicle_equals_grid_to_bus", _sum(vehicle_energy_rows, "grid_to_vehicle_kwh"), grid_to_bus, 1.0e-3, source_files="vehicle_energy_ledger.csv;energy_flow_ledger.csv")
    add("vehicle_pv_to_vehicle_equals_pv_to_bus", _sum(vehicle_energy_rows, "pv_to_vehicle_kwh"), pv_to_bus, 1.0e-3, source_files="vehicle_energy_ledger.csv;energy_flow_ledger.csv")
    add("vehicle_bess_to_vehicle_equals_bess_to_bus", _sum(vehicle_energy_rows, "bess_to_vehicle_kwh"), bess_to_bus, 1.0e-3, source_files="vehicle_energy_ledger.csv;energy_flow_ledger.csv")
    add("bess_charge_balance", _sum(energy_rows, "bess_charge_kwh"), pv_to_bess + grid_to_bess, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("bess_charge_equals_pv_to_bess_plus_grid_to_bess", _sum(energy_rows, "bess_charge_kwh"), pv_to_bess + grid_to_bess, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("bess_discharge_balance", _sum(energy_rows, "bess_discharge_kwh"), bess_to_bus, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("bess_discharge_equals_bess_to_bus", _sum(energy_rows, "bess_discharge_kwh"), bess_to_bus, 1.0e-3, source_files="energy_flow_ledger.csv")
    add("bess_soc_within_buffer", _sum(energy_rows, "bess_soc_violation_kwh"), 0.0, 1.0e-6, source_files="energy_flow_ledger.csv")
    if any(abs(float(getattr(row, "bess_soc_end_kwh", 0.0) or 0.0) - float(getattr(row, "bess_soc_start_kwh", 0.0) or 0.0)) > 1.0e-9 for row in energy_rows):
        transition_error = 0.0
        for row in energy_rows:
            expected_end = (
                float(getattr(row, "bess_soc_start_kwh", 0.0) or 0.0)
                + float(getattr(row, "bess_charge_kwh", 0.0) or 0.0)
                - float(getattr(row, "bess_discharge_kwh", 0.0) or 0.0)
            )
            transition_error += abs(float(getattr(row, "bess_soc_end_kwh", 0.0) or 0.0) - expected_end)
        add("bess_soc_transition_balance", transition_error, 0.0, 1.0e-6, source_files="energy_flow_ledger.csv")
    else:
        skip("bess_soc_transition_balance", message="BESS SOC start/end transition values are not explicit in these rows.", source_files="energy_flow_ledger.csv")
    terminal_violations = 0.0
    for row in energy_rows:
        terminal_min = float(getattr(row, "bess_terminal_soc_min_kwh", 0.0) or 0.0)
        if terminal_min > 0.0 and float(getattr(row, "slot_index", -1) or -1) == max((float(getattr(r, "slot_index", -1) or -1) for r in energy_rows), default=-1.0):
            terminal_violations += max(terminal_min - float(getattr(row, "bess_soc_end_kwh", 0.0) or 0.0), 0.0)
    add("bess_terminal_soc_satisfied", terminal_violations, 0.0, 1.0e-6, source_files="energy_flow_ledger.csv")
    add("pv_to_bus_cost_applied", _sum(energy_rows, "pv_to_bus_cost_jpy"), sum(float(getattr(row, "pv_to_bus_kwh", 0.0) or 0.0) * float(getattr(row, "bess_to_bus_unit_cost_jpy_per_kwh", 0.0) or 0.0) for row in energy_rows), 1.0e-6, source_files="energy_flow_ledger.csv")
    add("pv_to_bess_cost_applied", _sum(energy_rows, "pv_to_bess_cost_jpy"), sum(float(getattr(row, "pv_to_bess_kwh", 0.0) or 0.0) * float(getattr(row, "bess_to_bus_unit_cost_jpy_per_kwh", 0.0) or 0.0) for row in energy_rows), 1.0e-6, source_files="energy_flow_ledger.csv")
    add("bess_to_bus_cost_applied", _sum(energy_rows, "bess_to_bus_cost_jpy"), sum(float(getattr(row, "bess_to_bus_kwh", 0.0) or 0.0) * float(getattr(row, "bess_to_bus_unit_cost_jpy_per_kwh", 0.0) or 0.0) for row in energy_rows), 1.0e-6, source_files="energy_flow_ledger.csv")
    add("bess_flow_cost_matches_unit_cost", _sum(energy_rows, "bess_total_flow_cost_jpy"), _sum(energy_rows, "pv_to_bus_cost_jpy") + _sum(energy_rows, "pv_to_bess_cost_jpy") + _sum(energy_rows, "bess_to_bus_cost_jpy"), 1.0e-6, source_files="energy_flow_ledger.csv")
    add("fuel_consumption_balance", _sum(vehicle_energy_rows, "fuel_consumed_l"), float(summary.get("ice_fuel_consumed_l", 0.0) or 0.0), 1.0e-6, source_files="vehicle_energy_ledger.csv;kpi_summary.json")
    add("fuel_timeseries_matches_vehicle_fuel_ledger", _sum_dict(fuel_timeseries_rows, "fuel_consumption_l"), _sum(vehicle_energy_rows, "fuel_consumed_l"), 1.0e-6, source_files="fuel_timeseries.csv;vehicle_energy_ledger.csv")
    add("fuel_canonical_matches_vehicle_ledger", _sum_dict(fuel_canonical_rows, "fuel_consumption_l"), _sum(vehicle_energy_rows, "fuel_consumed_l"), 1.0e-6, source_files="fuel_canonical_ledger.csv;vehicle_energy_ledger.csv")
    add("fuel_cost_matches_fuel_consumption", _sum_dict(fuel_canonical_rows, "fuel_cost_jpy"), sum(float(row.get("fuel_consumption_l", 0.0) or 0.0) * float(row.get("diesel_price_jpy_per_l", 0.0) or 0.0) for row in fuel_canonical_rows), 1.0e-6, source_files="fuel_canonical_ledger.csv")
    add("ice_co2_matches_fuel_consumption", _sum_dict(fuel_canonical_rows, "ice_co2_kg"), sum(float(row.get("fuel_consumption_l", 0.0) or 0.0) * float(row.get("fuel_emission_factor_kg_per_l", 0.0) or 0.0) for row in fuel_canonical_rows), 1.0e-6, source_files="fuel_canonical_ledger.csv")
    add("co2_total_equals_grid_plus_ice", _sum_dict(co2_rows, "total_co2_kg"), _sum_dict(co2_rows, "grid_co2_kg") + _sum_dict(co2_rows, "ice_co2_kg"), 1.0e-6, source_files="co2_timeseries.csv")
    add("kpi_total_co2_matches_co2_ledger", float(summary.get("total_co2_kg", 0.0) or 0.0), _sum_dict(co2_rows, "total_co2_kg"), 1.0e-6, source_files="kpi_summary.json;co2_timeseries.csv")
    add("co2_balance", _sum_dict(co2_rows, "total_co2_kg"), float(summary.get("total_co2_kg", _sum_dict(co2_rows, "total_co2_kg")) or 0.0), 1.0e-6, source_files="co2_timeseries.csv;kpi_summary.json")
    gross_cost = (
        float(summary.get("grid_purchase_cost_jpy", 0.0) or 0.0)
        + float(summary.get("bess_total_flow_cost_jpy", 0.0) or 0.0)
        + float(summary.get("demand_charge_cost_jpy", 0.0) or 0.0)
        + float(summary.get("fuel_cost_jpy", 0.0) or 0.0)
        + float(summary.get("co2_cost_jpy", 0.0) or 0.0)
        + float(summary.get("battery_degradation_cost_jpy", 0.0) or 0.0)
        + float(summary.get("contract_overage_cost_jpy", 0.0) or 0.0)
        + float(summary.get("vehicle_usage_cost_jpy", 0.0) or 0.0)
    )
    add("cost_breakdown_balance", float(summary.get("gross_operating_cost_jpy", summary.get("total_cost_jpy", 0.0)) or 0.0), gross_cost, 1.0e-6, source_files="vehicle_energy_ledger.csv;energy_flow_ledger.csv;kpi_summary.json")
    add("kpi_grid_purchase_cost_matches_cost_ledger", float(summary.get("grid_purchase_cost_jpy", 0.0) or 0.0), _sum(energy_rows, "grid_purchase_cost_jpy"), 1.0e-6, source_files="kpi_summary.json;energy_flow_ledger.csv")
    add("kpi_demand_charge_cost_matches_cost_ledger", float(summary.get("demand_charge_cost_jpy", 0.0) or 0.0), float(summary.get("demand_charge_cost_jpy", 0.0) or 0.0), 1.0e-6, source_files="kpi_summary.json;cost ledger")
    add("kpi_summary_matches_canonical_ledger", float(summary.get("pv_generation_kwh", 0.0) or 0.0), pv_generation, 1.0e-6, source_files="kpi_summary.json;energy_flow_ledger.csv")
    distinct_service_dates = {str(getattr(row, "service_date", "") or "") for row in list(vehicle_slot_rows) + list(vehicle_energy_rows) + list(energy_rows)}
    add("service_date_consistency", float(len(distinct_service_dates)), 1.0 if distinct_service_dates else 0.0, 0.0, source_files="all canonical ledgers")
    soc_nan_count = sum(
        1
        for row in vehicle_slot_rows
        for value in (row.soc_start_kwh, row.soc_end_kwh, row.soc_start_ratio, row.soc_end_ratio)
        if not math.isfinite(float(value))
    )
    add("soc_no_nan", float(soc_nan_count), 0.0, 0.0, source_files="vehicle_slot_ledger.csv")
    soc_bounds_count = sum(1 for row in vehicle_slot_rows if bool(row.soc_violation_flag))
    add("soc_within_bounds", float(soc_bounds_count), 0.0, 0.0, source_files="vehicle_slot_ledger.csv")
    if initial_soc_rows:
        range_violations = 0
        for row in initial_soc_rows:
            ratio = float(row.get("initial_soc_ratio", 0.0) or 0.0)
            min_ratio = row.get("configured_initial_soc_min_ratio")
            max_ratio = row.get("configured_initial_soc_max_ratio")
            if min_ratio not in (None, "") and ratio < float(min_ratio) - 1.0e-9:
                range_violations += 1
            if max_ratio not in (None, "") and ratio > float(max_ratio) + 1.0e-9:
                range_violations += 1
        add("initial_soc_within_configured_range", float(range_violations), 0.0, 0.0, source_files="initial_soc_ledger.csv")
        below_min_count = sum(1 for row in initial_soc_precheck_rows if str(row.get("precheck_status") or "").startswith("ERROR_INITIAL_SOC_BELOW_MIN"))
        add("initial_soc_above_soc_min_or_flagged", float(below_min_count), 0.0, 0.0, severity="WARNING", source_files="initial_soc_precheck.csv")
    else:
        skip("initial_soc_within_configured_range", source_files="initial_soc_ledger.csv")
        skip("initial_soc_above_soc_min_or_flagged", source_files="initial_soc_precheck.csv")
    fallback = str(summary.get("solver_status", "") or "").upper() in {"BASELINE_FALLBACK", "PARTIAL_BASELINE_FALLBACK"}
    add("solver_status_consistency", 0.0 if (not fallback or not bool(summary.get("is_optimization_result", True))) else 1.0, 0.0, 0.0, source_files="kpi_summary.json")
    phys_status = str(summary.get("physical_feasibility_status", "UNKNOWN") or "UNKNOWN")
    phys_expected_ng = soc_bounds_count > 0 or any(abs(float(getattr(row, "pv_balance_error_kwh", 0.0) or 0.0)) > 1.0e-3 for row in energy_rows)
    add("physical_feasibility_status_consistency", 0.0 if (not phys_expected_ng or phys_status != "PHYSICALLY_FEASIBLE") else 1.0, 0.0, 0.0, source_files="kpi_summary.json;data_flow_validation.csv")
    unit = float(summary.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0)
    add("vehicle_usage_cost_formula", float(summary.get("vehicle_usage_cost_jpy", 0.0) or 0.0), float(summary.get("used_vehicle_day_count", 0) or 0) * unit, 1.0e-6, source_files="kpi_summary.json")
    empty_operator_count = sum(1 for row in list(vehicle_energy_rows) + list(energy_rows) if not str(getattr(row, "operator_id", "") or "").strip())
    add("operator_id_empty_count", float(empty_operator_count), 0.0, 0.0, source_files="all canonical ledgers")
    return checks


def _enrich_summary_from_canonical_ledgers(
    summary: Dict[str, Any],
    *,
    co2_rows: Sequence[Mapping[str, Any]],
    fuel_rows: Sequence[Mapping[str, Any]],
    initial_soc_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> None:
    grid_co2 = sum(float(row.get("grid_co2_kg", 0.0) or 0.0) for row in co2_rows)
    ice_co2 = sum(float(row.get("ice_co2_kg", 0.0) or 0.0) for row in co2_rows)
    total_co2 = grid_co2 + ice_co2
    summary["grid_co2_kg"] = grid_co2
    summary["electricity_co2_kg"] = grid_co2
    summary["ice_co2_kg"] = ice_co2
    summary["fuel_co2_kg"] = ice_co2
    summary["total_co2_kg"] = total_co2
    summary["co2_boundary"] = "grid_plus_ice"
    summary["co2_accounting_method"] = "grid_import_based"
    summary["bess_co2_source_tracking"] = False
    summary["fuel_consumption_l"] = sum(float(row.get("fuel_consumption_l", 0.0) or 0.0) for row in fuel_rows)
    summary["refuel_l"] = sum(float(row.get("refuel_l", 0.0) or 0.0) for row in fuel_rows)
    summary["fuel_source_of_truth"] = "fuel_canonical_ledger"
    summary["pv_generation_timeseries_total_kwh"] = float(metadata.get("pv_generation_timeseries_total_kwh", summary.get("pv_generation_kwh", 0.0)) or 0.0)
    summary["depot_energy_flows_pv_generation_total_kwh"] = float(metadata.get("depot_energy_flows_pv_generation_total_kwh", summary.get("pv_generation_kwh", 0.0)) or 0.0)
    summary["optimization_status"] = _normalize_optimization_status(summary.get("solver_status"))
    summary["initial_soc_policy"] = str(metadata.get("initial_soc_policy", metadata.get("initial_soc_source", "scenario_file")) or "scenario_file")
    summary["initial_soc_min_ratio"] = metadata.get("initial_soc_min_ratio")
    summary["initial_soc_max_ratio"] = metadata.get("initial_soc_max_ratio")
    summary["initial_soc_random_seed"] = metadata.get("initial_soc_random_seed", metadata.get("random_seed", ""))
    summary["initial_soc_vehicle_count"] = len(initial_soc_rows)
    summary["objective_value_definition"] = "solver objective including penalties and bonuses"
    summary["gross_operating_cost_definition"] = "real operating cost terms only"


def _normalize_optimization_status(raw_status: Any) -> str:
    status = str(raw_status or "").strip().upper()
    if status in {"OPTIMAL", "SOLVED_OPTIMAL"}:
        return "OPTIMAL"
    if status in {"SOLVED_FEASIBLE", "FEASIBLE"}:
        return "FEASIBLE"
    if "INFEASIBLE" in status:
        return "INFEASIBLE"
    if "TIME_LIMIT" in status or status == "TIME_LIMIT":
        return "TIME_LIMIT"
    if status in {"BASELINE_FALLBACK", "PARTIAL_BASELINE_FALLBACK"} or "BASELINE" in status:
        return "BASELINE_FALLBACK"
    return status or "UNKNOWN"


def _apply_validation_summary(summary: Dict[str, Any], validation_rows: Sequence[Mapping[str, Any]]) -> None:
    error_count = sum(1 for row in validation_rows if row.get("status") == "NG" and row.get("severity") == "ERROR")
    warning_count = sum(1 for row in validation_rows if row.get("status") == "NG" and row.get("severity") == "WARNING")
    soc_violation_count = int(next((float(row.get("actual_value", 0.0) or 0.0) for row in validation_rows if row.get("check_name") == "soc_within_bounds"), 0.0))
    energy_balance_error = any(
        row.get("status") == "NG"
        and row.get("severity") == "ERROR"
        and str(row.get("check_name") or "")
        in {
            "pv_generation_matches_pv_timeseries",
            "pv_generation_matches_depot_energy_flows",
            "pv_generation_balance",
            "grid_import_balance",
            "bus_charging_source_balance",
            "vehicle_total_charge_equals_bus_charging",
            "vehicle_grid_to_vehicle_equals_grid_to_bus",
            "vehicle_pv_to_vehicle_equals_pv_to_bus",
            "vehicle_bess_to_vehicle_equals_bess_to_bus",
        }
        for row in validation_rows
    )
    if soc_violation_count > 0:
        physical_status = "SOC_VIOLATION"
    elif energy_balance_error:
        physical_status = "ENERGY_BALANCE_ERROR"
    elif error_count == 0:
        physical_status = "PHYSICALLY_FEASIBLE"
    else:
        physical_status = "UNKNOWN"
    summary["data_flow_validation_status"] = "ERROR" if error_count else ("WARNING" if warning_count else "OK")
    summary["data_flow_error_count"] = error_count
    summary["data_flow_warning_count"] = warning_count
    summary["validation_status"] = summary["data_flow_validation_status"]
    summary["soc_violation_count"] = soc_violation_count
    summary["physical_feasibility_status"] = physical_status
    summary["is_physically_feasible"] = physical_status == "PHYSICALLY_FEASIBLE"
    summary["has_soc_violation"] = soc_violation_count > 0
    summary["has_energy_balance_error"] = energy_balance_error


def _attach_nested_kpi_summary(summary: Dict[str, Any]) -> None:
    summary["metadata"] = {
        "service_date": summary.get("service_date", ""),
        "weather_reference_date": summary.get("weather_reference_date", summary.get("weather_date", "")),
        "run_created_at": summary.get("run_created_at", ""),
        "output_generated_at": summary.get("output_generated_at", ""),
        "weather_profile": summary.get("weather_profile", ""),
        "operation_mode": summary.get("operation_mode", ""),
        "solver_status": summary.get("solver_status", ""),
        "optimization_status": summary.get("optimization_status", "UNKNOWN"),
        "is_optimization_result": bool(summary.get("is_optimization_result", False)),
        "physical_feasibility_status": summary.get("physical_feasibility_status", "UNKNOWN"),
        "is_physically_feasible": bool(summary.get("is_physically_feasible", False)),
        "has_soc_violation": bool(summary.get("has_soc_violation", False)),
        "has_energy_balance_error": bool(summary.get("has_energy_balance_error", False)),
        "initial_soc_policy": summary.get("initial_soc_policy", ""),
        "initial_soc_min_ratio": summary.get("initial_soc_min_ratio"),
        "initial_soc_max_ratio": summary.get("initial_soc_max_ratio"),
        "initial_soc_random_seed": summary.get("initial_soc_random_seed"),
    }
    summary["energy"] = {
        "bus_charging_total_kwh": float(summary.get("bus_charging_total_kwh", 0.0) or 0.0),
        "grid_to_bus_kwh": float(summary.get("grid_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bus_kwh": float(summary.get("pv_to_bus_kwh", 0.0) or 0.0),
        "bess_to_bus_kwh": float(summary.get("bess_to_bus_kwh", 0.0) or 0.0),
        "pv_generation_kwh": float(summary.get("pv_generation_kwh", 0.0) or 0.0),
        "pv_to_bess_kwh": float(summary.get("pv_to_bess_kwh", 0.0) or 0.0),
        "pv_curtailment_kwh": float(summary.get("pv_curtailment_kwh", 0.0) or 0.0),
        "pv_export_kwh": float(summary.get("pv_export_kwh", 0.0) or 0.0),
        "grid_import_kwh": float(summary.get("grid_import_kwh", 0.0) or 0.0),
        "peak_grid_import_kw": float(summary.get("peak_grid_import_kw", 0.0) or 0.0),
        "bess_charge_kwh": float(summary.get("bess_charge_kwh", 0.0) or 0.0),
        "bess_discharge_kwh": float(summary.get("bess_discharge_kwh", 0.0) or 0.0),
    }
    summary["fuel"] = {
        "fuel_consumption_l": float(summary.get("fuel_consumption_l", summary.get("ice_fuel_consumed_l", 0.0)) or 0.0),
        "refuel_l": float(summary.get("refuel_l", summary.get("ice_refueled_l", 0.0)) or 0.0),
        "fuel_source_of_truth": "vehicle_fuel_ledger",
    }
    summary["co2"] = {
        "total_co2_kg": float(summary.get("total_co2_kg", 0.0) or 0.0),
        "grid_co2_kg": float(summary.get("grid_co2_kg", 0.0) or 0.0),
        "ice_co2_kg": float(summary.get("ice_co2_kg", 0.0) or 0.0),
        "co2_boundary": "grid_plus_ice",
        "co2_accounting_method": "grid_import_based",
        "bess_co2_source_tracking": False,
    }
    summary["cost"] = {
        "grid_purchase_cost_jpy": float(summary.get("grid_purchase_cost_jpy", 0.0) or 0.0),
        "demand_charge_cost_jpy": float(summary.get("demand_charge_cost_jpy", 0.0) or 0.0),
        "fuel_cost_jpy": float(summary.get("fuel_cost_jpy", 0.0) or 0.0),
        "co2_cost_jpy": float(summary.get("co2_cost_jpy", 0.0) or 0.0),
        "battery_degradation_cost_jpy": float(summary.get("battery_degradation_cost_jpy", 0.0) or 0.0),
        "gross_operating_cost_jpy": float(summary.get("gross_operating_cost_jpy", 0.0) or 0.0),
        "objective_value": float(summary.get("objective_value", summary.get("objective_value_jpy", 0.0)) or 0.0),
        "objective_is_actual_cost": False,
        "objective_value_definition": summary.get("objective_value_definition", "solver objective including penalties and bonuses"),
        "gross_operating_cost_definition": summary.get("gross_operating_cost_definition", "real operating cost terms only"),
    }
    summary["validation"] = {
        "data_flow_validation_status": summary.get("data_flow_validation_status", "UNKNOWN"),
        "error_count": int(summary.get("data_flow_error_count", 0) or 0),
        "warning_count": int(summary.get("data_flow_warning_count", 0) or 0),
        "soc_violation_count": int(summary.get("soc_violation_count", 0) or 0),
    }


def build_accounting_artifacts(
    *,
    problem: Any,
    scenario_id: str,
    run_id: str,
    service_date: date,
    weather_date: date | None,
    operator_id: str,
    trip_assignment_rows: Sequence[Mapping[str, Any]],
    vehicle_soc_timeseries_rows: Sequence[Mapping[str, Any]],
    vehicle_charging_source_rows: Sequence[Mapping[str, Any]],
    energy_flow_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any] | None = None,
    slot_minutes: int | None = None,
) -> AccountingArtifacts:
    metadata = dict(metadata or {})
    slot_minutes = normalize_timestep_min(
        slot_minutes or metadata.get("slot_minutes") or getattr(getattr(problem, "scenario", None), "timestep_min", None) or getattr(problem, "timestep_min", None),
        default=30,
    )
    resolved_weather_date = weather_date or service_date
    resolved_operator_id = str(operator_id or metadata.get("operator_id") or "").strip() or UNKNOWN_OPERATOR
    metadata["operator_id"] = resolved_operator_id
    metadata["slot_minutes"] = slot_minutes
    vehicle_rows = _build_vehicle_slot_ledger(
        problem=problem,
        scenario_id=scenario_id,
        run_id=run_id,
        service_date=service_date,
        weather_date=resolved_weather_date,
        operator_id=resolved_operator_id,
        trip_assignment_rows=trip_assignment_rows,
        vehicle_soc_timeseries_rows=vehicle_soc_timeseries_rows,
        vehicle_charging_source_rows=vehicle_charging_source_rows,
        metadata=metadata,
        slot_minutes=slot_minutes,
    )
    energy_rows = _build_energy_flow_ledger(
        scenario_id=scenario_id,
        run_id=run_id,
        service_date=service_date,
        weather_date=resolved_weather_date,
        operator_id=resolved_operator_id,
        energy_flow_rows=energy_flow_rows,
        metadata=metadata,
        slot_minutes=slot_minutes,
    )
    vehicle_energy_rows = _build_vehicle_energy_ledger(vehicle_rows, metadata=metadata)
    fuel_canonical_rows = _build_fuel_canonical_ledger(vehicle_energy_rows)
    fuel_timeseries_rows = _build_fuel_timeseries(fuel_canonical_rows)
    co2_rows = _build_co2_timeseries(energy_rows, fuel_timeseries_rows)
    initial_soc_rows = _build_initial_soc_ledger(
        problem,
        operator_id=resolved_operator_id,
        metadata=metadata,
    )
    initial_soc_precheck_rows = _build_initial_soc_precheck(initial_soc_rows, vehicle_rows)
    summary = build_accounting_summary(
        vehicle_rows=[row.to_dict() for row in vehicle_rows],
        vehicle_energy_rows=[row.to_dict() for row in vehicle_energy_rows],
        energy_rows=[row.to_dict() for row in energy_rows],
        trip_assignment_rows=trip_assignment_rows,
        metadata=metadata,
    )
    _enrich_summary_from_canonical_ledgers(
        summary,
        co2_rows=co2_rows,
        fuel_rows=fuel_canonical_rows,
        initial_soc_rows=initial_soc_rows,
        metadata=metadata,
    )
    validation_rows = _build_data_flow_validation(
        vehicle_slot_rows=vehicle_rows,
        vehicle_energy_rows=vehicle_energy_rows,
        energy_rows=energy_rows,
        fuel_canonical_rows=fuel_canonical_rows,
        fuel_timeseries_rows=fuel_timeseries_rows,
        co2_rows=co2_rows,
        initial_soc_rows=initial_soc_rows,
        initial_soc_precheck_rows=initial_soc_precheck_rows,
        summary=summary,
    )
    _apply_validation_summary(summary, validation_rows)
    _attach_nested_kpi_summary(summary)
    return AccountingArtifacts(
        vehicle_slot_ledger=vehicle_rows,
        vehicle_energy_ledger=vehicle_energy_rows,
        energy_flow_ledger=energy_rows,
        fuel_canonical_ledger=fuel_canonical_rows,
        fuel_timeseries=fuel_timeseries_rows,
        co2_timeseries=co2_rows,
        initial_soc_ledger=initial_soc_rows,
        initial_soc_precheck=initial_soc_precheck_rows,
        data_flow_validation=validation_rows,
        summary=summary,
    )

