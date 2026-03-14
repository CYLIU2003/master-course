#!/usr/bin/env python3
"""Run the small verification scenario for all solver×objective combos and
dump more detailed results (cost breakdown, duties summary, sample duties).

This is a helper script (not a test) to reproduce the outputs shown in
tests/test_new_objectives_and_modes.py but with more fields exposed.
"""
import json
from datetime import datetime, timezone

from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder
from src.optimization.common.result import ResultSerializer


def _scenario():
    trips = []
    for idx in range(1, 85):
        ms = (idx - 1) * 10
        h, m = 7 + ms // 60, ms % 60
        if h >= 21:
            break
        trips.append({"trip_id": f"K1-{idx:03d}", "route_id": "K1", "service_id": "WEEKDAY",
                      "direction": "outbound", "origin": "Meguro", "destination": "Shimizu",
                      "departure": f"{h:02d}:{m:02d}", "arrival": f"{h:02d}:{(m+20)%60:02d}",
                      "distance_km": 12.0, "allowed_vehicle_types": ["BEV", "ICE"]})
    for idx in range(1, 57):
        ms = (idx - 1) * 15
        h, m = 7 + ms // 60, ms % 60
        if h >= 21:
            break
        trips.append({"trip_id": f"K2-{idx:03d}", "route_id": "K2", "service_id": "WEEKDAY",
                      "direction": "outbound", "origin": "Meguro", "destination": "Sangenjaya",
                      "departure": f"{h:02d}:{m:02d}", "arrival": f"{h:02d}:{(m+15)%60:02d}",
                      "distance_km": 8.0, "allowed_vehicle_types": ["BEV", "ICE"]})
    for idx in range(1, 43):
        ms = (idx - 1) * 20
        h, m = 7 + ms // 60, ms % 60
        if h >= 21:
            break
        trips.append({"trip_id": f"S41-{idx:03d}", "route_id": "S41", "service_id": "WEEKDAY",
                      "direction": "outbound", "origin": "Shibuya", "destination": "Tamagawa",
                      "departure": f"{h:02d}:{m:02d}", "arrival": f"{h:02d}:{(m+25)%60:02d}",
                      "distance_km": 15.0, "allowed_vehicle_types": ["BEV", "ICE"]})

    vehicles = (
        [{"id": f"BEV{i:02d}", "depotId": "DEP", "type": "BEV",
          "batteryKwh": 300.0, "energyConsumption": 1.2, "chargePowerKw": 150.0}
         for i in range(1, 21)]
        + [{"id": f"ICE{i:02d}", "depotId": "DEP", "type": "ICE",
            "batteryKwh": 0.0, "energyConsumption": 0.0, "chargePowerKw": 0.0}
           for i in range(1, 21)]
    )
    return {
        "meta": {"id": "verify-001", "updatedAt": datetime.now(timezone.utc).isoformat()},
        "depots": [{"id": "DEP", "name": "Meguro depot"}],
        "vehicles": vehicles,
        "routes": [{"id": r} for r in ("K1", "K2", "S41")],
        "depot_route_permissions": [{"depotId": "DEP", "routeId": r, "allowed": True}
                                    for r in ("K1", "K2", "S41")],
        "vehicle_route_permissions": [{"vehicleId": v["id"], "routeId": r, "allowed": True}
                                      for v in vehicles for r in ("K1", "K2", "S41")],
        "timetable_rows": trips,
        "chargers": [{"id": f"CHG{i}", "siteId": "DEP", "powerKw": 90.0} for i in range(1, 5)],
        "pv_profiles": [{"site_id": "DEP", "values": [0.0] * 80}],
        "energy_price_profiles": [{"site_id": "DEP", "values": [28.0] * 80}],
    }


def _build(objective_mode: str):
    sc = _scenario()
    sc["simulation_config"] = {"objective_mode": objective_mode, "objective_weights": {}}
    return ProblemBuilder().build_from_scenario(
        sc, depot_id="DEP", service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.HYBRID),
    )


_SOLVER_SPECS = [
    ("milp",   OptimizationMode.MILP,   60),
    ("hybrid", OptimizationMode.HYBRID, 60),
    ("alns",   OptimizationMode.ALNS,   60),
    ("ga",     OptimizationMode.ALNS,   60),
    ("abc",    OptimizationMode.ALNS,   60),
]
_OBJ_MODES = ["total_cost", "co2", "balanced"]


def summarize(payload: dict) -> dict:
    out = {
        "solver_mode": payload.get("solver_mode"),
        "solver_status": payload.get("solver_status"),
        "objective_value": payload.get("objective_value"),
        "feasible": payload.get("feasible"),
        "served_trip_count": len(payload.get("served_trip_ids", [])),
        "unserved_trip_count": len(payload.get("unserved_trip_ids", [])),
        "cost_breakdown": payload.get("cost_breakdown"),
        "num_duties": len(payload.get("duties", [])),
        "num_vehicle_paths": len(payload.get("vehicle_paths", {})),
        "sample_duties": [],
    }
    for d in payload.get("duties", [])[:3]:
        out["sample_duties"].append({
            "duty_id": d.get("duty_id"),
            "vehicle_type": d.get("vehicle_type"),
            "trip_count": len(d.get("trip_ids", [])),
        })
    out["unserved_sample"] = payload.get("unserved_trip_ids", [])[:10]
    return out


def main():
    engine = OptimizationEngine()
    results = []
    for label, opt_mode, tl in _SOLVER_SPECS:
        for obj_mode in _OBJ_MODES:
            problem = _build(obj_mode)
            result = engine.solve(
                problem,
                OptimizationConfig(mode=opt_mode, time_limit_sec=tl, alns_iterations=30),
            )
            payload = ResultSerializer.serialize_result(result)
            summary = summarize(payload)
            header = f"[{label.upper()} / {obj_mode}]"
            print(header)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            results.append({"label": label, "obj_mode": obj_mode, "summary": summary})


if __name__ == "__main__":
    main()
