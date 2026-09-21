"""Independently reconstruct the bus-first storage rule from saved evidence."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

POLICY = "pv_bus_first_surplus_storage_v1"
TOL = 1e-6
FLOW_NAMES = ("grid_to_bus", "pv_to_bus", "bess_to_bus", "pv_to_bess", "grid_to_bess", "pv_curtail", "bess_soc")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Auxiliary BESS audit: {message}")


def finite(value: object) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), "non-finite energy")
    return float(value)


def close(left: float, right: float, label: str) -> None:
    require(abs(finite(left) - finite(right)) <= TOL, label)


def verify_flows(asset: dict, *, start: float, pv: float, flows: dict, duration: float) -> float:
    """Check independently of both the optimizer and execution controller."""
    values = {name: finite(flows[name]) for name in FLOW_NAMES}
    require(all(value >= -TOL for value in values.values()), "negative source flow")
    pv, start = finite(pv), finite(start)
    require(pv >= -TOL, "negative PV")
    lower, upper = finite(asset["bess_soc_min_kwh"]), finite(asset["bess_soc_max_kwh"])
    ec, ed = finite(asset["bess_charge_efficiency"]), finite(asset["bess_discharge_efficiency"])
    require(0 < ec <= 1 and 0 < ed <= 1 and duration > 0, "efficiency or duration")
    require(lower-TOL <= start <= upper+TOL, "start SOC bounds")
    demand = sum(values[name] for name in ("grid_to_bus", "pv_to_bus", "bess_to_bus"))
    direct = min(pv, demand)
    power = finite(asset["bess_power_kw"]) * duration
    discharge = min(demand-direct, power, max(start-lower, 0)*ed) if asset["allow_bess_to_bus"] else 0
    charge = min(pv-direct, power, max(upper-start, 0)/ec) if asset["allow_pv_to_bess"] else 0
    expected = dict(pv_to_bus=direct, bess_to_bus=discharge, pv_to_bess=charge,
                    grid_to_bus=demand-direct-discharge, grid_to_bess=0,
                    pv_curtail=pv-direct-charge, bess_soc=start+ec*charge-discharge/ed)
    for name in FLOW_NAMES:
        close(values[name], expected[name], f"{name} violates rule or energy balance")
    require(lower-TOL <= values["bess_soc"] <= upper+TOL, "end SOC bounds")
    return values["bess_soc"]


def audit_week(case: Path, design: dict, terminal: dict, assets: dict) -> dict:
    require(design["bess_priority_mode"] == "pv_self_consumption"
            and design["bess_forecast_reserve_policy"] == "physical_floor_only"
            and design["bess_terminal_soc_policy"] == "minimum_only", "wrong declared policy")
    hashes, depots = {}, {}

    def evidence(path: Path) -> dict:
        raw = path.read_bytes()
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    executed = evidence(case / "rolling_hourly_chain" / "executed_plan.json")
    for depot, asset in assets.items():
        require(asset["bess_enabled"] and asset["bess_priority_mode"] == "pv_self_consumption",
                "equipment policy differs")
        require(asset["allow_grid_to_bess"] is False and asset["bess_terminal_soc_target_kwh"] == 0,
                "grid charge or restoration enabled")
        duration = design["timestep_minutes"] / 60
        initial = finite(asset["bess_initial_soc_kwh"])
        previous = initial
        forecast_count = 0
        minimum = maximum = initial
        for hour in range(-1, 168):
            folder = case if hour < 0 else case / "rolling_hourly_chain" / f"hour_{hour:03d}"
            native = evidence(folder / ("canonical_solver_result.json" if hour < 0 else "forecast_result.json"))
            starts = native["metadata"]["bess_soc_start_kwh_by_depot_slot"][depot]
            forecast_slots = list(range(672)) if hour < 0 else list(range(hour*4, min((hour+24)*4, 672)))
            require(sorted(map(int, starts)) == forecast_slots, "forecast slot coverage")
            for slot in forecast_slots:
                flow = {name: native[f"{name}_kwh_by_depot_slot"].get(depot, {}).get(str(slot), 0)
                        for name in FLOW_NAMES}
                pv = sum(flow[name] for name in ("pv_to_bus", "pv_to_bess", "pv_curtail"))
                verify_flows(asset, start=starts[str(slot)], pv=pv, flows=flow, duration=duration)
                if slot != forecast_slots[0]:
                    close(starts[str(slot)], native["bess_soc_kwh_by_depot_slot"][depot][str(slot-1)],
                          "forecast handoff")
                forecast_count += 1
            if hour < 0:
                close(starts["0"], initial, "day-ahead initial SOC")
                continue
            close(starts[str(hour*4)], previous, "rolling observed initial SOC")
            execution = evidence(folder / "pv_execution_audit.json")
            require(execution["policy_by_depot"][depot] == POLICY
                    and execution["future_observations_used"] is False
                    and execution["bus_charging_commands_unchanged"] is True, "execution policy contract")
            rows = [row for row in execution["rows"] if row["depot_id"] == depot]
            require([row["slot_index"] for row in rows] == list(range(hour*4, (hour+1)*4)), "execution slot coverage")
            for row in rows:
                slot = str(row["slot_index"])
                close(row["initial_bess_soc_kwh"], previous, "actual SOC handoff")
                flow = {name: row[f"{name}_kwh"] for name in FLOW_NAMES}
                for name in FLOW_NAMES:
                    close(flow[name], executed[f"{name}_kwh_by_depot_slot"].get(depot, {}).get(slot, 0),
                          f"{name} differs from accounted executed plan")
                planned_demand = sum(native[f"{name}_kwh_by_depot_slot"].get(depot, {}).get(slot, 0)
                                     for name in ("grid_to_bus", "pv_to_bus", "bess_to_bus"))
                close(sum(flow[name] for name in ("grid_to_bus", "pv_to_bus", "bess_to_bus")),
                      planned_demand, "changed bus demand")
                previous = verify_flows(asset, start=previous, pv=row["actual_pv_kwh"], flows=flow, duration=duration)
                minimum, maximum = min(minimum, previous), max(maximum, previous)
        close(previous, terminal[depot]["terminal_soc_kwh"], "accounted terminal SOC")
        depots[depot] = {"initial_kwh": initial, "terminal_kwh": previous,
                         "inventory_drawdown_kwh": initial-previous, "minimum_kwh": minimum,
                         "maximum_kwh": maximum, "forecast_slots_verified": forecast_count,
                         "executed_slots_verified": 672}
    return {"status": "ALL_FORECASTS_AND_168_PREFIXES_AUXILIARY_VERIFIED", "policy": POLICY,
            "hashes": hashes, "depots": depots, "future_actuals_used": False}
