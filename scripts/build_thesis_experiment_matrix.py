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
        "charging_power_model": "piecewise_soc_taper_v1",
        "charge_setup_minutes": 5,
        "charge_teardown_minutes": 5,
        "minimum_charge_session_minutes": 15,
        "pv_input_semantics": "available_surplus_after_depot_load",
        "allow_partial_service": False,
        "milp_max_successors_per_trip": None,
        "vehicle_usage_cost_jpy_per_used_bus": 0.0,
        "vehicle_usage_cost_semantics": "provisional_sensitivity",
    }
    cases: list[dict[str, Any]] = []

    def add(case_id: str, family: str, changes: dict[str, Any]) -> None:
        cases.append(
            {
                "case_id": case_id,
                "family": family,
                "prepare_settings": {**common, **changes},
                "execution_path": (
                    "POST /api/scenarios/{scenario_id}/prepare-simulation then "
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
    for pv_scale in (0.0, 0.25, 0.5, 0.75, 1.0):
        add(
            f"PV_{pv_scale:.2f}",
            "pv_supply_transition",
            {"pv_scale": pv_scale},
        )
    for route_band in (True, False):
        add(
            f"ROUTE_BAND_{'ON' if route_band else 'OFF'}",
            "route_band_ablation",
            {"fixed_route_band_mode": route_band},
        )
    for usage_cost in (0.0, 20_000.0):
        add(
            f"VEHICLE_DAY_{int(usage_cost)}",
            "vehicle_day_cost_sensitivity",
            {"vehicle_usage_cost_jpy_per_used_bus": usage_cost},
        )
    for cap in (None, 750.0, 500.0, 250.0, 100.0):
        add(
            "CO2_UNCAPPED" if cap is None else f"CO2_CAP_{int(cap)}",
            "cost_co2_epsilon_frontier",
            {"co2_emissions_cap_kg": cap},
        )

    return {
        "schema_version": "thesis_experiment_matrix_v2",
        "execution_semantics": "frontend_bff_only_no_direct_solver",
        "common_control_contract": common,
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
                "implementation_status": "SEPARATE_PHASE1_RUN_REQUIRED",
                "candidate_generation_available": False,
                "reporting_eligible": False,
                "dispatch_semantics": "canonical_rule_based_fixed_dispatch",
                "energy_semantics": "optimized_charging_and_bess",
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
        ],
        "ablation_release_condition": (
            "M0-M3 must be generated from the same fresh prepared input and "
            "frozen Git SHA; M1 is not generated by the ordinary frontend "
            "postprocessor and requires an explicit phase1 run."
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
