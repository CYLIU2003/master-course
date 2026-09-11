"""Continuous daily inventories with explicitly allocated period expenses.

Daily cost attribution is a reporting allocation, not solver-native vehicle
source provenance. Period-end unreplenished inventory is valued exactly once.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .problem import DailyCostLedgerEntry, VehicleCostLedgerEntry
from .soc_helpers import horizon_start_min, is_electric_vehicle
from .vehicle_timeline import build_vehicle_timeline


ATTRIBUTION_POLICY = (
    "period_expenses_allocated_by_vehicle_charge_or_refuel_quantity; "
    "unreplenished_inventory_at_period_end; other_period_costs_equal_per_day; "
    "not_solver_native_source_provenance"
)


def _allocate(total: float, weights: list[float]) -> list[float]:
    denominator = sum(weights)
    if denominator > 0:
        return [total * weight / denominator for weight in weights]
    return [total / len(weights)] * len(weights)


def build_daily_return_ledgers(evaluator: Any, problem: Any, plan: Any, breakdown: Any) -> tuple:
    """Carry physical states across every midnight without clipping or reset."""
    days = int(problem.scenario.planning_days)
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    timelines = build_vehicle_timeline(problem, plan)
    ev = evaluator._evaluate_electricity_with_overwrite(
        problem, plan, evaluator._operating_electric_energy_kwh_by_slot(problem, plan))
    fuel = evaluator._evaluate_liquid_fuel_with_overwrite(problem, plan)
    entries = []
    daily = [{key: 0.0 for key in ("ev_prov", "ice_prov", "ev_real", "ice_real", "ev_left", "ice_left")} for _ in range(days)]
    for vehicle in problem.vehicles:
        vehicle_id = str(vehicle.vehicle_id)
        electric = is_electric_vehicle(problem, vehicle)
        events = timelines.get(vehicle_id, ())
        charges, discharges, refuels = ([0.0] * days for _ in range(3))
        energy, consumed_fuel, provisional = ([0.0] * days for _ in range(3))
        for event in events:
            duration = event.end_min - event.start_min
            if duration <= 0:
                continue
            for day in range(days):
                overlap = max(0, min(event.end_min, start + (day + 1) * 1440) - max(event.start_min, start + day * 1440))
                share = overlap / duration
                energy[day] += event.energy_kwh * share
                consumed_fuel[day] += event.fuel_l * share
                price = (evaluator._provisional_electricity_price_at_slot(problem, max(0, (event.start_min-start)//step))
                         if electric else float(problem.scenario.diesel_price_yen_per_l or 0))
                provisional[day] += (event.energy_kwh if electric else event.fuel_l) * share * price
        for slot in plan.charging_slots:
            if str(slot.vehicle_id) == vehicle_id:
                day = (int(slot.slot_index) * step) // 1440
                if not 0 <= day < days:
                    raise ValueError("Charging slot outside daily ledger horizon")
                charges[day] += float(slot.charge_kw) * step / 60
                discharges[day] += float(slot.discharge_kw) * step / 60
        for slot in plan.refuel_slots:
            if str(slot.vehicle_id) == vehicle_id:
                day = int(slot.slot_index) * step // 1440
                if not 0 <= day < days:
                    raise ValueError("Refuel slot outside daily ledger horizon")
                refuels[day] += float(slot.refuel_liters)
        component = ev if electric else fuel
        prefix = "ev" if electric else "fuel"
        # Preserve the evaluator's period totals; these weights allocate money,
        # and never change physical energy, liters, or state to fit a total.
        provisional = _allocate(float(component.get(prefix + "_provisional_by_vehicle", {}).get(vehicle_id, 0)), provisional)
        real = _allocate(float(component.get(prefix + "_realized_by_vehicle", {}).get(vehicle_id, 0)), charges if electric else refuels)
        leftover = float(component.get(prefix + "_leftover_by_vehicle", {}).get(vehicle_id, 0))
        soc = evaluator._vehicle_initial_soc_kwh(vehicle) if electric else None
        tank = None if electric else evaluator._vehicle_initial_fuel_l(vehicle)
        for day in range(days):
            # Vehicle-side efficiency is the canonical Stage 2/validator 0.95.
            end_soc = None if soc is None else soc + charges[day] * 0.95 - discharges[day] / 0.95 - energy[day]
            end_fuel = None if tank is None else tank + refuels[day] - consumed_fuel[day]
            left = leftover if day == days - 1 else 0.0
            entries.append(VehicleCostLedgerEntry(
                vehicle_id=vehicle_id, day_index=day, provisional_drive_cost_jpy=provisional[day],
                provisional_leftover_cost_jpy=left, realized_charge_cost_jpy=real[day] if electric else 0,
                realized_refuel_cost_jpy=0 if electric else real[day], start_soc_kwh=soc, end_soc_kwh=end_soc,
                start_fuel_l=tank, end_fuel_l=end_fuel))
            kind = "ev" if electric else "ice"
            daily[day][kind + "_prov"] += provisional[day]
            daily[day][kind + "_real"] += real[day]
            daily[day][kind + "_left"] += left
            soc, tank = end_soc, end_fuel

    # Depot expenses can exist without any vehicle charging (e.g. grid to BESS).
    # Keep their unallocated portion at the depot/day level.
    for kind, total in (("ev", breakdown.realized_ev_charge_cost), ("ice", breakdown.realized_ice_refuel_cost)):
        assigned = sum(row[kind + "_real"] for row in daily)
        extra = _allocate(float(total) - assigned, [row[kind + "_real"] for row in daily])
        for day, amount in enumerate(extra):
            daily[day][kind + "_real"] += amount
    known = (float(breakdown.realized_ev_charge_cost) + float(breakdown.realized_ice_refuel_cost)
             + float(breakdown.leftover_ev_provisional_cost) + float(breakdown.leftover_ice_provisional_cost)
             + float(breakdown.demand_cost))
    other = (float(breakdown.total_cost) - known) / days
    service_dates = list(problem.metadata.get("service_dates") or [])
    if not service_dates:
        first_date = next((str(trip.service_date) for trip in problem.trips if getattr(trip, "service_date", None)), None)
        service_dates = [(date.fromisoformat(first_date) + timedelta(days=day)).isoformat() for day in range(days)] if first_date else [None] * days
    ledgers = []
    for day, row in enumerate(daily):
        demand = float(breakdown.demand_cost) / days
        total = row["ev_real"] + row["ice_real"] + row["ev_left"] + row["ice_left"] + demand + other
        ledgers.append(DailyCostLedgerEntry(
            day_index=day, service_date=service_dates[day], ev_provisional_drive_cost_jpy=row["ev_prov"],
            ice_provisional_drive_cost_jpy=row["ice_prov"], ev_realized_charge_cost_jpy=row["ev_real"],
            ice_realized_refuel_cost_jpy=row["ice_real"], ev_leftover_provisional_cost_jpy=row["ev_left"],
            ice_leftover_provisional_cost_jpy=row["ice_left"], demand_charge_jpy=demand, total_cost_jpy=total,
            other_operating_cost_allocated_jpy=other, cost_attribution_policy=ATTRIBUTION_POLICY))
    return tuple(sorted(entries, key=lambda row: (row.vehicle_id, row.day_index))), tuple(ledgers)
