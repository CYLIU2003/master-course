from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .aggregators import build_accounting_summary
from .schema import AccountingArtifacts, EnergyFlowLedgerRow, VehicleSlotLedgerRow

SLOT_MINUTES = 5
SLOT_HOURS = SLOT_MINUTES / 60.0


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


def _slot_key_from_dt(dt: datetime) -> Tuple[date, int]:
    minute = dt.hour * 60 + dt.minute
    slot_index = minute // SLOT_MINUTES
    return dt.date(), slot_index


def _slot_bounds(slot_date: date, slot_index: int) -> tuple[str, str]:
    start = datetime.combine(slot_date, datetime.min.time()) + timedelta(minutes=slot_index * SLOT_MINUTES)
    end = start + timedelta(minutes=SLOT_MINUTES)
    return start.isoformat(), end.isoformat()


def _split_duration(start: datetime, end: datetime) -> Iterable[tuple[date, int, float]]:
    if end <= start:
        return []
    current = start
    while current < end:
        slot_start_minute = (current.hour * 60 + current.minute) // SLOT_MINUTES * SLOT_MINUTES
        slot_start = datetime.combine(current.date(), datetime.min.time()) + timedelta(minutes=slot_start_minute)
        slot_end = slot_start + timedelta(minutes=SLOT_MINUTES)
        overlap_start = max(start, slot_start)
        overlap_end = min(end, slot_end)
        overlap = max((overlap_end - overlap_start).total_seconds() / 60.0, 0.0)
        if overlap > 0.0:
            yield current.date(), slot_start_minute // SLOT_MINUTES, overlap / SLOT_MINUTES
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


def _soc_by_vehicle_time(rows: Sequence[Mapping[str, Any]]) -> Dict[tuple[str, date, int], Mapping[str, Any]]:
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
        out[(vehicle_id, slot_date, minute // SLOT_MINUTES)] = row
    return out


def _charge_by_vehicle_time(rows: Sequence[Mapping[str, Any]]) -> Dict[tuple[str, date, int], Mapping[str, Any]]:
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
        out[(vehicle_id, slot_date, minute // SLOT_MINUTES)] = row
    return out


def _slot_minutes_from_time_text(time_text: str) -> int:
    try:
        return int(time_text[:2]) * 60 + int(time_text[3:5])
    except Exception:
        return 0


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
) -> List[VehicleSlotLedgerRow]:
    vehicle_by_id, vehicle_type_by_id = _vehicle_maps(problem)
    price_by_slot = _price_by_slot(problem)
    soc_by_key = _soc_by_vehicle_time(vehicle_soc_timeseries_rows)
    charge_by_key = _charge_by_vehicle_time(vehicle_charging_source_rows)
    rows_by_key: Dict[tuple[str, date, int], Dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    rows_meta: Dict[tuple[str, date, int], Dict[str, Any]] = {}

    for trip in trip_assignment_rows:
        vehicle_id = str(trip.get("assigned_vehicle_id") or "")
        if not vehicle_id or str(trip.get("served_flag", True)).lower() in {"false", "0"}:
            continue
        start = _parse_dt(trip.get("actual_departure") or trip.get("scheduled_departure"), service_date)
        end = _parse_dt(trip.get("actual_arrival") or trip.get("scheduled_arrival"), service_date)
        if end <= start:
            end = start + timedelta(minutes=SLOT_MINUTES)
        for slot_date, slot_index, share in _split_duration(start, end):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            rows_meta.setdefault(key, dict(trip))
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
        for slot_date, slot_index, share in _split_duration(before_slot - timedelta(minutes=SLOT_MINUTES), before_slot):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            bucket["deadhead_before_km"] += before_km * share
            bucket["activity_type"] = bucket.get("activity_type") or "deadhead_before"
            rows_meta.setdefault(key, dict(trip))
        for slot_date, slot_index, share in _split_duration(after_slot, after_slot + timedelta(minutes=SLOT_MINUTES)):
            key = (vehicle_id, slot_date, slot_index)
            bucket = rows_by_key[key]
            bucket["deadhead_after_km"] += after_km * share
            bucket["activity_type"] = bucket.get("activity_type") or "deadhead_after"
            rows_meta.setdefault(key, dict(trip))

    for key, soc_row in soc_by_key.items():
        vehicle_id, slot_date, slot_index = key
        bucket = rows_by_key[key]
        bucket["soc_end_kwh"] = float(soc_row.get("soc_kwh", 0.0) or 0.0)
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
        service_km = float(bucket.get("service_km", 0.0) or 0.0)
        deadhead_before_km = float(bucket.get("deadhead_before_km", 0.0) or 0.0)
        deadhead_after_km = float(bucket.get("deadhead_after_km", 0.0) or 0.0)
        deadhead_total_km = deadhead_before_km + deadhead_after_km
        bev_drive_energy_kwh = float(bucket.get("bev_drive_energy_kwh", 0.0) or 0.0)
        if not bev_drive_energy_kwh and service_km > 0.0:
            bev_drive_energy_kwh = service_km * energy_rate
        soc_end_kwh = float(bucket.get("soc_end_kwh", 0.0) or 0.0)
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
        soc_start_kwh = soc_end_kwh - charge_input_kwh + bev_drive_energy_kwh
        soc_delta_charge_ratio = charge_input_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_delta_drive_ratio = bev_drive_energy_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_start_ratio = soc_start_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        soc_end_ratio = soc_end_kwh / capacity_kwh if capacity_kwh > 0.0 else 0.0
        slot_start, slot_end = _slot_bounds(slot_date, slot_index)
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
                slot_minutes=SLOT_MINUTES,
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
                ice_fuel_liter=fuel_liter,
                ice_co2_kg=ice_co2_kg,
                charge_input_kwh=charge_input_kwh,
                charger_grid_kwh=float(bucket.get("charger_grid_kwh", 0.0) or 0.0),
                charger_pv_direct_kwh=float(bucket.get("charger_pv_direct_kwh", 0.0) or 0.0),
                charger_bess_kwh=float(bucket.get("charger_bess_kwh", 0.0) or 0.0),
                charge_loss_kwh=0.0,
                soc_start_ratio=soc_start_ratio,
                soc_end_ratio=soc_end_ratio,
                soc_delta_charge_ratio=soc_delta_charge_ratio,
                soc_delta_drive_ratio=soc_delta_drive_ratio,
                soc_delta_loss_ratio=0.0,
                soc_violation_flag=bool(capacity_kwh > 0.0 and (soc_end_kwh < 0.0 or soc_end_kwh > capacity_kwh)),
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
) -> List[EnergyFlowLedgerRow]:
    rows: List[EnergyFlowLedgerRow] = []
    for row in energy_flow_rows:
        depot_id = str(row.get("depot_id") or metadata.get("depot_id") or "")
        time_text = str(row.get("time") or "")
        date_text = str(row.get("date") or service_date.isoformat())
        row_date = _parse_date(date_text, service_date)
        slot_index = _slot_minutes_from_time_text(time_text) // SLOT_MINUTES
        slot_start, slot_end = _slot_bounds(row_date, slot_index)
        pv_generation_kwh = float(row.get("pv_generation_slot_kwh", row.get("pv_generation_kwh", 0.0)) or 0.0)
        pv_to_bus_kwh = float(row.get("pv_to_bus_kwh", row.get("pv_to_bus_slot_kwh", 0.0)) or 0.0)
        pv_to_bess_kwh = float(row.get("pv_to_bess_kwh", row.get("pv_to_bess_slot_kwh", 0.0)) or 0.0)
        pv_curtailed_kwh = float(row.get("pv_curtailed_kwh", row.get("pv_curtailed_slot_kwh", 0.0)) or 0.0)
        bess_to_bus_kwh = float(row.get("bess_to_bus_kwh", row.get("bess_to_bus_slot_kwh", 0.0)) or 0.0)
        grid_to_bus_kwh = float(row.get("grid_to_bus_kwh", row.get("grid_to_bus_slot_kwh", 0.0)) or 0.0)
        grid_to_bess_kwh = float(row.get("grid_to_bess_kwh", row.get("grid_to_bess_slot_kwh", 0.0)) or 0.0)
        grid_total_kwh = float(row.get("grid_total_kwh", row.get("grid_import_slot_kwh", grid_to_bus_kwh + grid_to_bess_kwh)) or 0.0)
        if not grid_total_kwh:
            grid_total_kwh = grid_to_bus_kwh + grid_to_bess_kwh
        grid_kw = float(row.get("grid_kw", row.get("grid_import_kw", grid_total_kwh / SLOT_HOURS if SLOT_HOURS > 0 else 0.0)) or 0.0)
        price = float(row.get("energy_price_yen_per_kwh", row.get("tou_energy_price_jpy_per_kwh", 0.0)) or 0.0)
        energy_cost_jpy = grid_total_kwh * price
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
                slot_minutes=SLOT_MINUTES,
                pv_generation_kwh=pv_generation_kwh,
                pv_to_bus_kwh=pv_to_bus_kwh,
                pv_to_bess_kwh=pv_to_bess_kwh,
                pv_curtailed_kwh=pv_curtailed_kwh,
                bess_to_bus_kwh=bess_to_bus_kwh,
                bess_charge_kwh=pv_to_bess_kwh + grid_to_bess_kwh,
                bess_discharge_kwh=bess_to_bus_kwh,
                bess_soc_start_kwh=float(row.get("bess_soc_kwh", 0.0) or 0.0),
                bess_soc_end_kwh=float(row.get("bess_soc_kwh", 0.0) or 0.0),
                grid_to_bus_kwh=grid_to_bus_kwh,
                grid_to_bess_kwh=grid_to_bess_kwh,
                depot_aux_grid_kwh=0.0,
                grid_total_kwh=grid_total_kwh,
                grid_kw=grid_kw,
                tou_energy_price_jpy_per_kwh=price,
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
) -> AccountingArtifacts:
    metadata = dict(metadata or {})
    resolved_weather_date = weather_date or service_date
    vehicle_rows = _build_vehicle_slot_ledger(
        problem=problem,
        scenario_id=scenario_id,
        run_id=run_id,
        service_date=service_date,
        weather_date=resolved_weather_date,
        operator_id=operator_id,
        trip_assignment_rows=trip_assignment_rows,
        vehicle_soc_timeseries_rows=vehicle_soc_timeseries_rows,
        vehicle_charging_source_rows=vehicle_charging_source_rows,
        metadata=metadata,
    )
    energy_rows = _build_energy_flow_ledger(
        scenario_id=scenario_id,
        run_id=run_id,
        service_date=service_date,
        weather_date=resolved_weather_date,
        operator_id=operator_id,
        energy_flow_rows=energy_flow_rows,
        metadata=metadata,
    )
    summary = build_accounting_summary(
        vehicle_rows=[row.to_dict() for row in vehicle_rows],
        energy_rows=[row.to_dict() for row in energy_rows],
        trip_assignment_rows=trip_assignment_rows,
        metadata=metadata,
    )
    return AccountingArtifacts(
        vehicle_slot_ledger=vehicle_rows,
        energy_flow_ledger=energy_rows,
        summary=summary,
    )

