"""
Verify all new additions:
  - objective_mode: total_cost / co2 / balanced
  - solver modes:  milp / hybrid / alns / ga / abc
  - vehicle_fixed_cost = 0 (no capital cost)
  - BFF objective_weights propagation
  - BFF _parse_optimization_mode aliases
"""
import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone
from typing import Dict, List

import pytest

from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder
from src.optimization.common.result import ResultSerializer
from bff.services.simulation_builder import objective_weights_for_mode
from bff.routers.optimization import _parse_optimization_mode
from bff.mappers.scenario_to_problemdata import (
    _objective_weights_from_scenario,
    _collect_trips_for_scope,
)


# ── shared small scenario (3 routes, 182 trips, 20 BEV + 20 ICE) ─────────────

def _scenario() -> Dict:
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
    sc["simulation_config"] = {
        "objective_mode": objective_mode,
        "objective_weights": {},
    }
    # vehicle_fixed_cost=0 (no capital cost) — already zero-default in builder
    return ProblemBuilder().build_from_scenario(
        sc, depot_id="DEP", service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.HYBRID),
    )


# ── 1. objective_weights_for_mode ─────────────────────────────────────────────

class TestObjectiveWeights:
    def test_total_cost_no_emission(self):
        w = objective_weights_for_mode(objective_mode="total_cost", unserved_penalty=10000)
        assert w["electricity_cost"] == 1.0
        assert w["emission_cost"] == 0.0
        assert w["vehicle_fixed_cost"] == 0.0

    def test_co2_no_cost(self):
        w = objective_weights_for_mode(objective_mode="co2", unserved_penalty=10000)
        assert w["electricity_cost"] == 0.0
        assert w["emission_cost"] == 1.0
        assert w["vehicle_fixed_cost"] == 0.0

    def test_balanced_both(self):
        w = objective_weights_for_mode(objective_mode="balanced", unserved_penalty=10000)
        assert w["electricity_cost"] == 1.0
        assert w["emission_cost"] == 1.0
        assert w["vehicle_fixed_cost"] == 0.0

    def test_alias_cost_co2_balanced(self):
        for alias in ("cost_co2_balanced", "multi_objective"):
            w = objective_weights_for_mode(objective_mode=alias, unserved_penalty=10000)
            assert w["emission_cost"] == 1.0


# ── 2. BFF scenario-level weight extraction ──────────────────────────────────

class TestScenarioObjectiveWeights:
    def _sc_with_mode(self, mode: str):
        return {"simulation_config": {"objective_mode": mode}}

    def test_total_cost(self):
        w = _objective_weights_from_scenario(self._sc_with_mode("total_cost"))
        assert w["electricity_cost"] == 1.0
        assert w["emission_cost"] == 0.0

    def test_co2(self):
        w = _objective_weights_from_scenario(self._sc_with_mode("co2"))
        assert w["electricity_cost"] == 0.0
        assert w["emission_cost"] == 1.0

    def test_balanced(self):
        w = _objective_weights_from_scenario(self._sc_with_mode("balanced"))
        assert w["electricity_cost"] == 1.0
        assert w["emission_cost"] == 1.0
        assert w["vehicle_fixed_cost"] == 0.0


# ── 3. _parse_optimization_mode aliases ──────────────────────────────────────

class TestSolverModeAliases:
    def test_milp_aliases(self):
        for alias in ("milp", "mode_milp_only", "exact", "MILP"):
            assert _parse_optimization_mode(alias) == OptimizationMode.MILP

    def test_alns_aliases(self):
        for alias in ("alns", "mode_alns_only", "heuristic", "ga", "abc",
                      "GA", "ABC", "ALNS"):
            result = _parse_optimization_mode(alias)
            assert result == OptimizationMode.ALNS, f"Expected ALNS for '{alias}', got {result}"

    def test_hybrid_default(self):
        for alias in ("hybrid", "mode_alns_milp", "anything_else"):
            assert _parse_optimization_mode(alias) == OptimizationMode.HYBRID


# ── 4. no capital cost: vehicle_fixed_cost stays 0 ───────────────────────────

class TestNoCapitalCost:
    def test_vehicle_fixed_weight_is_zero(self):
        """vehicle_fixed_cost must be 0 in all three objective modes."""
        for mode in ("total_cost", "co2", "balanced"):
            w = objective_weights_for_mode(objective_mode=mode, unserved_penalty=10000)
            assert w["vehicle_fixed_cost"] == 0.0, \
                f"vehicle_fixed_cost should be 0 for mode '{mode}', got {w['vehicle_fixed_cost']}"


# ── 5. end-to-end: all 5 solver × 3 objectives ───────────────────────────────

_SOLVER_SPECS = [
    ("milp",   OptimizationMode.MILP,   60),
    ("hybrid", OptimizationMode.HYBRID, 60),
    ("alns",   OptimizationMode.ALNS,   60),
    ("ga",     OptimizationMode.ALNS,   60),   # GA -> ALNS fallback
    ("abc",    OptimizationMode.ALNS,   60),   # ABC -> ALNS fallback
]
_OBJ_MODES = ["total_cost", "co2", "balanced"]


class TestEndToEnd:
    """
    15 combinations: 5 solvers × 3 objectives
    Each must:
      - serve all 182 trips
      - NOT raise
    """

    @pytest.mark.parametrize("obj_mode", _OBJ_MODES)
    @pytest.mark.parametrize("label,opt_mode,tl", _SOLVER_SPECS)
    def test_all_combos(self, label, opt_mode, tl, obj_mode):
        problem = _build(obj_mode)
        engine = OptimizationEngine()
        result = engine.solve(
            problem,
            OptimizationConfig(mode=opt_mode, time_limit_sec=tl, alns_iterations=30),
        )
        payload = ResultSerializer.serialize_result(result)

        served = len(payload["served_trip_ids"])
        total  = len(problem.trips)
        unserved = payload["unserved_trip_ids"]

        print(f"\n[{label.upper()} / {obj_mode}]  "
              f"served={served}/{total}  "
              f"obj={payload.get('objective_value', 'N/A'):.1f}  "
              f"feasible={payload['feasible']}  "
              f"unserved={len(unserved)}")

        assert served == total, \
            f"{label}/{obj_mode}: {served}/{total} trips served, unserved={unserved[:5]}"
