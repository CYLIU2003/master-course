"""Build the thesis experiment contract without invoking a solver.

The output is consumed by the frontend/BFF workflow.  It never calls the
optimization engine directly and therefore cannot bypass Prepare, provenance,
rolling, physical validation, or accounting gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_experiment_matrix() -> dict[str, Any]:
    common = {
        "solver_mode": "phase4_integrated",
        "objective_mode": "total_cost",
        "objective_preset": "research_lexicographic_v1",
        "trip_energy_model": "literature_proxy_v1",
        "trip_energy_sensitivity_scale": 1.0,
        "bev_trip_energy_sensitivity_scale": 1.0,
        "ice_trip_fuel_sensitivity_scale": 1.0,
        "charging_power_model": "piecewise_soc_taper_v1",
        "charge_setup_minutes": 5,
        "charge_teardown_minutes": 5,
        "minimum_charge_session_minutes": 15,
        # Preserve the current zero-buffer model for every unrelated
        # sensitivity.  The dedicated family below is the only place where
        # this physical connection margin is varied.
        "turnaround_buffer_min": 0,
        "pv_input_semantics": "available_surplus_after_depot_load",
        "allow_partial_service": False,
        "milp_max_successors_per_trip": None,
        # The thesis sensitivity baseline is a declared flat-price case. A
        # price family below changes exactly one of these economic inputs.
        "grid_flat_price_per_kwh": 30.0,
        "diesel_price_per_l": 145.0,
        "vehicle_usage_cost_jpy_per_used_bus": 0.0,
        "vehicle_usage_cost_semantics": "provisional_sensitivity",
    }
    cases: list[dict[str, Any]] = []

    def add(
        case_id: str,
        family: str,
        changes: dict[str, Any],
        *,
        request_overrides: dict[str, Any] | None = None,
    ) -> None:
        prepare_settings = {**common, **changes}
        timestep_min = int(prepare_settings.get("timestep_min") or 60)
        optimization_overrides: dict[str, Any] = {
            "mode": "phase4_integrated",
            "research_run": True,
            "integrated_actual_cost_objective": True,
            "stage1_best_obj_stop_enabled": False,
            "run_profile": "day_ahead_and_hourly_rolling",
            "run_hourly_rolling": True,
            "time_step_min": timestep_min,
            "timestep_min": timestep_min,
            # The frontend formal-run contract advances the fixed-assignment
            # rolling controller every 60 minutes.  The time-discretization
            # family varies only the MILP's internal energy-slot resolution;
            # changing both controls would confound two different effects.
            "rolling_execution_minutes": 60,
        }
        if "co2_emissions_cap_kg" in prepare_settings:
            optimization_overrides["co2_emissions_cap_kg"] = (
                prepare_settings["co2_emissions_cap_kg"]
            )
        cases.append(
            {
                "case_id": case_id,
                "family": family,
                "prepare_settings": prepare_settings,
                "prepare_request_overrides": dict(request_overrides or {}),
                "optimization_request_overrides": optimization_overrides,
                "execution_path": (
                    "POST /api/scenarios/{scenario_id}/simulation/prepare then "
                    "POST /api/scenarios/{scenario_id}/run-optimization"
                ),
                "research_run_required": True,
            }
        )

    for timestep_min in (60, 30, 15):
        add(
            f"TIME_{timestep_min}",
            "time_discretization",
            {"time_step_min": timestep_min, "timestep_min": timestep_min},
        )
    for scale in (0.8, 0.9, 1.0, 1.1, 1.2):
        add(
            f"ENERGY_{scale:.1f}",
            "trip_energy_sensitivity",
            {"trip_energy_sensitivity_scale": scale},
        )
        add(
            f"BEV_ENERGY_{scale:.1f}",
            "bev_trip_energy_sensitivity",
            {"bev_trip_energy_sensitivity_scale": scale},
        )
        add(
            f"ICE_FUEL_{scale:.1f}",
            "ice_trip_fuel_sensitivity",
            {"ice_trip_fuel_sensitivity_scale": scale},
        )
    for pv_scale in (0.0, 0.25, 0.5, 0.75, 1.0):
        add(
            f"PV_{pv_scale:.2f}",
            "pv_supply_transition",
            {"pv_scale": pv_scale},
        )
    for grid_price in (24.0, 30.0, 36.0):
        add(
            f"ELECTRICITY_PRICE_{int(grid_price)}",
            "electricity_price_sensitivity",
            {"grid_flat_price_per_kwh": grid_price},
        )
    for diesel_price in (116.0, 145.0, 174.0):
        add(
            f"DIESEL_PRICE_{int(diesel_price)}",
            "diesel_price_sensitivity",
            {"diesel_price_per_l": diesel_price},
        )
    for charger_count in (6, 8, 10):
        add(
            f"CHARGER_COUNT_{charger_count}",
            "charger_capacity_sensitivity",
            {
                # The selected inventory ignores charger_count. Fix the
                # generated-inventory source for every family member and vary
                # only the number of 90-kW single-port chargers.
                "use_selected_depot_charger_inventory": False,
                "charger_count": charger_count,
                "charger_power_kw": 90.0,
            },
        )
    for route_band in (True, False):
        add(
            f"ROUTE_BAND_{'ON' if route_band else 'OFF'}",
            "route_band_ablation",
            {"fixed_route_band_mode": route_band},
            request_overrides={
                # The canonical builder forces route-band ON while intra-depot
                # route swapping is prohibited. OFF must lift that scope lock.
                "allow_intra_depot_route_swap": not route_band,
            },
        )
    for turnaround_buffer_min in (5, 10, 15):
        add(
            f"TURNAROUND_BUFFER_{turnaround_buffer_min}",
            "turnaround_buffer_sensitivity",
            {"turnaround_buffer_min": turnaround_buffer_min},
        )
    for usage_cost in (0.0, 20_000.0):
        add(
            f"VEHICLE_DAY_{int(usage_cost)}",
            "vehicle_day_cost_sensitivity",
            {
                # This family deliberately tests the scalar total-cost model.
                # Under research_lexicographic_v1 the number of vehicle-days
                # is a higher-priority objective, so changing its yen
                # coefficient cannot reveal the coefficient's dispatch effect.
                "objective_preset": "scalar_total_cost_v1",
                "vehicle_usage_cost_jpy_per_used_bus": usage_cost,
                "vehicle_usage_cost_semantics": "fixed_vehicle_day_cost",
            },
        )
    for cap in (None, 750.0, 500.0, 250.0, 100.0):
        add(
            "CO2_UNCAPPED" if cap is None else f"CO2_CAP_{int(cap)}",
            "cost_co2_epsilon_frontier",
            {"co2_emissions_cap_kg": cap},
        )

    return {
        "schema_version": (
            "thesis_experiment_matrix_v7_charger_capacity_sensitivity"
        ),
        "execution_semantics": "frontend_bff_only_no_direct_solver",
        "common_control_contract": common,
        "parameter_semantics": {
            "time_discretization": (
                "Varies the internal day-ahead and rolling energy-slot "
                "resolution (15/30/60 minutes) while holding the frontend "
                "rolling execution interval fixed at 60 minutes."
            ),
            "pv_scale": (
                "Multiplicative alpha applied to the available PV energy "
                "series after rated-capacity generation is constructed; it "
                "does not change pv_capacity_kw."
            ),
            "electricity_price_sensitivity": (
                "Sets a flat grid purchase price of 24, 30, or 36 JPY/kWh "
                "through Prepare while holding diesel price, tariff shape, "
                "PV/BESS, timetable, fleet, and solver controls fixed."
            ),
            "diesel_price_sensitivity": (
                "Sets the ICE fuel price to 116, 145, or 174 JPY/L through "
                "Prepare while holding grid price, trip fuel quantities, "
                "PV/BESS, timetable, fleet, and solver controls fixed."
            ),
            "charger_capacity_sensitivity": (
                "Uses the deterministic 90-kW generated charger inventory "
                "for every family member and varies only its port count "
                "across 6, 8, and 10. It does not compare persisted charger IDs."
            ),
            "trip_energy_sensitivity": (
                "Backward-compatible common demand multiplier. It moves BEV "
                "kWh and ICE fuel liters together and is interpreted as a "
                "shared trip-demand or distance calibration sensitivity, not "
                "as evidence for either powertrain coefficient in isolation."
            ),
            "bev_trip_energy_sensitivity": (
                "Multiplies only aggregate BEV trip kWh after deterministic "
                "distance/duration/time weights are normalized. ICE liters, "
                "trip times, distances, PV, tariff, fleet and charging "
                "controls remain fixed."
            ),
            "ice_trip_fuel_sensitivity": (
                "Multiplies only aggregate ICE trip fuel liters after the "
                "deterministic time-band weights are normalized. BEV kWh, "
                "trip times, distances, PV, tariff, fleet and charging "
                "controls remain fixed."
            ),
            "route_band_off": (
                "fixed_route_band_mode=false together with "
                "allow_intra_depot_route_swap=true; otherwise the canonical "
                "scope lock forces route-band ON."
            ),
            "turnaround_buffer_sensitivity": (
                "Adds a declared 5/10/15-minute operational margin to each "
                "base turnaround before deadhead time. It does not replace "
                "the stop-specific base turnaround or alter timetable rows."
            ),
            "vehicle_day_cost_sensitivity": (
                "Uses scalar_total_cost_v1 for both 0 and 20000 JPY cases. "
                "The main research_lexicographic_v1 objective minimizes "
                "vehicle-days at a higher priority and would make the yen "
                "coefficient irrelevant to dispatch."
            ),
        },
        "cases": cases,
        "ablation_contract": [
            {
                "case_id": "M0_rule_based_dispatch_arrival_charge",
                "implementation_status": "ADAPTER_AVAILABLE_IN_FRONTEND_RUN",
                "candidate_generation_available": True,
                "reporting_eligible": False,
                "dispatch_semantics": "canonical_rule_based_fixed_dispatch",
                "energy_semantics": "arrival_immediate_charge_without_optimization",
                "adapter": "build_m0_rule_baseline",
                "artifact": "thesis_ablation/day_ahead_method_candidates.json",
            },
            {
                "case_id": "M1_fixed_dispatch_optimized_energy",
                "implementation_status": "EXPLICIT_PHASE1_FRONTEND_RUN_AVAILABLE",
                "candidate_generation_available": True,
                "reporting_eligible": False,
                "dispatch_semantics": "canonical_rule_based_fixed_dispatch",
                "energy_semantics": "optimized_charging_and_bess",
                "solver_mode": "phase1_charging_only",
                "artifact": "thesis_ablation/day_ahead_method_candidates.json",
            },
            {
                "case_id": "M2_optimized_dispatch_simple_charge",
                "implementation_status": "ADAPTER_AVAILABLE_IN_FRONTEND_RUN",
                "candidate_generation_available": True,
                "reporting_eligible": False,
                "dispatch_semantics": "optimized_dispatch",
                "energy_semantics": "arrival_immediate_charge_without_optimization",
                "adapter": "build_m2_simple_charge_baseline",
                "artifact": "thesis_ablation/day_ahead_method_candidates.json",
            },
            {
                "case_id": "M3_integrated_dispatch_energy_bess",
                "implementation_status": "AVAILABLE",
                "candidate_generation_available": True,
                "reporting_eligible": False,
                "dispatch_semantics": "optimized_dispatch",
                "energy_semantics": "optimized_charging_and_bess",
            },
        ],
        "component_ablation_contract": [
            {
                "case_id": "A0_integrated_without_pv_bess",
                "implementation_status": "AVAILABLE",
                "reporting_eligible": True,
            },
            {
                "case_id": "A1_integrated_with_pv_without_bess",
                "implementation_status": "AVAILABLE",
                "reporting_eligible": True,
            },
            {
                "case_id": "A2_integrated_with_pv_and_bess",
                "implementation_status": "AVAILABLE",
                "reporting_eligible": True,
            },
        ],
        "required_outputs": [
            "prepared_scope_audit.json",
            "assignment_economic_audit.json",
            "physical_schedule_validation.json",
            "rolling_hourly_chain/executed_day_accounting.json",
            "solver_settings.json",
            "comparison_case_manifest.json",
            "thesis_ablation/day_ahead_method_candidates.json",
            "thesis_ablation_comparison/day_ahead_method_comparison.json",
        ],
        "ablation_release_condition": (
            "M0-M3 must be generated from the same fresh prepared input and "
            "frozen Git SHA. Run phase1_charging_only and phase4_integrated "
            "explicitly, then use build_thesis_ablation_comparison.py; the "
            "comparison fails closed unless canonical inputs and gates match."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/thesis_experiment_matrix.json"),
    )
    args = parser.parse_args()
    payload = build_experiment_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
