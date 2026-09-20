"""Independent saved-flow audit of every issued cyclic BESS reserve prefix."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

POLICY = "evaluation_target_zero_pv"
TOLERANCE_KWH = 1e-6


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(f"BESS reserve audit: {label}")


def finite(value: object) -> float:
    require(not isinstance(value, bool) and isinstance(value, (float, int)), "non-numeric energy")
    require(math.isfinite(value), "non-finite energy")
    return float(value)


def verify_prefix(rows: list[dict], forecast: dict, *, depot: str, target: float,
                  eta_charge: float, eta_discharge: float) -> dict:
    """Recompute the zero-PV lower trajectory from issued commands, not flags."""
    selected = [row for row in rows if row["depot_id"] == depot]
    require(bool(selected), "missing depot execution rows")
    lower = finite(selected[0]["initial_bess_soc_kwh"])
    minimum = lower
    actual_end = lower
    for row in selected:
        slot = str(row["slot_index"])
        # Canonical flow maps are sparse: omitted entries are serialized zeros.
        grid = finite(forecast["grid_to_bess_kwh_by_depot_slot"].get(depot, {}).get(slot, 0.0))
        discharge = finite(forecast["bess_to_bus_kwh_by_depot_slot"].get(depot, {}).get(slot, 0.0))
        require(abs(grid) <= TOLERANCE_KWH and abs(finite(row["grid_to_bess_kwh"])) <= TOLERANCE_KWH,
                "grid-to-BESS used")
        require(discharge >= -TOLERANCE_KWH, "negative discharge")
        lower += eta_charge * grid - discharge / eta_discharge
        require(lower >= target - TOLERANCE_KWH, "issued command spends terminal reserve at zero PV")
        require(abs(finite(row["initial_bess_soc_kwh"]) - actual_end) <= TOLERANCE_KWH, "state discontinuity")
        require(abs(finite(row["bess_to_bus_kwh"]) - discharge) <= TOLERANCE_KWH, "changed discharge command")
        actual_end += eta_charge * (finite(row["pv_to_bess_kwh"]) + finite(row["grid_to_bess_kwh"])) - discharge / eta_discharge
        require(abs(actual_end - finite(row["bess_soc_kwh"])) <= TOLERANCE_KWH, "energy balance")
        require(actual_end >= target - TOLERANCE_KWH, "realized state below terminal reserve")
        minimum = min(minimum, actual_end)
    return {"minimum_realized_kwh": minimum, "zero_pv_prefix_end_lower_bound_kwh": lower,
            "actual_end_kwh": actual_end}


def audit_week(case: Path, design: dict, terminal: dict, assets: dict) -> dict:
    require(design.get("bess_forecast_reserve_policy") == POLICY, "wrong design")
    hashes, depots = {}, {}
    def evidence(path):
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read(path)
    for depot, details in terminal.items():
        target = finite(details["initial_soc_kwh"])
        asset = assets[depot]
        eta_c, eta_d = finite(asset["bess_charge_efficiency"]), finite(asset["bess_discharge_efficiency"])
        require(0 < eta_c <= 1 and 0 < eta_d <= 1, "invalid efficiencies")
        require(asset["allow_grid_to_bess"] is False, "source permission changed")
        previous = target
        minimum = target
        for hour in range(168):
            folder = case / "rolling_hourly_chain" / f"hour_{hour:03d}"
            native = evidence(folder / "forecast_result.json")
            execution = evidence(folder / "pv_execution_audit.json")
            audit = native["metadata"]["rolling_pv_execution_reserve"]
            require(audit["enabled"] is True and audit["bess_reserve_policy"] == POLICY, "missing native reserve")
            slots = list(range(hour * 4, (hour + 1) * 4))
            require(audit["committed_slot_indices"] == slots, "wrong issued slots")
            require(abs(finite(audit["protected_floor_kwh_by_depot"][depot]) - target) <= TOLERANCE_KWH,
                    "reserve target changed")
            require(execution["future_observations_used"] is False and execution["bus_charging_commands_unchanged"] is True,
                    "execution information/command contract")
            rows = [row for row in execution["rows"] if row["depot_id"] == depot]
            require([row["slot_index"] for row in rows] == slots, "missing/duplicate actual slots")
            require(abs(finite(rows[0]["initial_bess_soc_kwh"]) - previous) <= TOLERANCE_KWH, "hourly handoff drift")
            result = verify_prefix(rows, native, depot=depot, target=target, eta_charge=eta_c, eta_discharge=eta_d)
            previous = result["actual_end_kwh"]
            minimum = min(minimum, result["minimum_realized_kwh"])
            end = min((hour + 24) * 4, 672) - 1
            require(abs(finite(native["bess_soc_kwh_by_depot_slot"][depot][str(end)]) - target) <= TOLERANCE_KWH,
                    "rolling terminal differs from original evaluation target")
        require(abs(previous - target) <= TOLERANCE_KWH, "weekly restoration failed")
        depots[depot] = {"target_kwh": target, "minimum_realized_kwh": minimum, "terminal_kwh": previous}
    return {"status": "ALL_168_PREFIXES_RESERVE_VERIFIED", "policy": POLICY,
            "depots": depots, "hashes": hashes, "future_actuals_used": False}
