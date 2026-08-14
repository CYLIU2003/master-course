"""Publishable verification for the bounded electric exact oracle.

The exact oracle is deliberately independent from the production Gurobi
formulation, but unit-test output alone is awkward to cite in a thesis audit.
This module builds a fixed set of tiny, hand-checkable boundary cases and
returns one deterministic certificate.  It does not read a saved scenario and
must never be used as a fallback for a production optimization run.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
from typing import Any, Mapping

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization import (
    ChargerDefinition,
    CostEvaluator,
    EnergyPriceSlot,
    FeasibilityChecker,
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.common.cost_components import default_cost_component_flags
from src.optimization.common.problem import CanonicalOptimizationProblem
from src.optimization.validation.small_electric_oracle import (
    SmallElectricOracleInfeasibleError,
    SmallElectricOracleResult,
    solve_small_exact_electric_oracle,
)


BEV_KWH_PER_KM = 1.316
ICE_L_PER_KM = 1.0 / 4.52
DIESEL_JPY_PER_L = 150.0
CHARGE_EFFICIENCY = 0.95
LOW_GRID_PRICE_JPY_PER_KWH = 20.0
HIGH_GRID_PRICE_JPY_PER_KWH = 30.0
TOLERANCE_JPY = 2.0e-6


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 of a JSON payload with no self-hash field."""

    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def break_even_grid_price_jpy_per_kwh() -> float:
    """Return the hand-derived grid tariff where BEV and ICE energy costs tie."""

    return (
        ICE_L_PER_KM * DIESEL_JPY_PER_L * CHARGE_EFFICIENCY
    ) / BEV_KWH_PER_KM


def build_mixed_break_even_problem(
    *,
    grid_price_jpy_per_kwh: float,
) -> CanonicalOptimizationProblem:
    """Build four sequential depot-to-depot trips served by one BEV or ICE."""

    trips = [
        Trip(
            trip_id=f"trip-{index + 1}",
            route_id="route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time=f"{8 + index:02d}:00",
            arrival_time=f"{8 + index:02d}:30",
            distance_km=10.0,
            allowed_vehicle_types=("BEV", "ICE"),
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
            operator_id="tokyu",
        )
        for index in range(4)
    ]
    context = DispatchContext(
        service_date="2025-08-05",
        trips=trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=BEV_KWH_PER_KM,
            ),
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=100.0,
                fuel_consumption_l_per_km=ICE_L_PER_KM,
            ),
        },
        default_turnaround_min=10,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id=f"electric-oracle-{grid_price_jpy_per_kwh:g}",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 1, "ICE": 1},
        chargers=(ChargerDefinition("charger-1", "DEPOT", 90.0),),
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=index,
                grid_buy_yen_per_kwh=grid_price_jpy_per_kwh,
            )
            for index in range(12)
        ),
        scenario_vehicles=(
            {
                "id": "BEV_001",
                "type": "BEV",
                "depotId": "DEPOT",
                "batteryKwh": 100.0,
                "energyConsumption": BEV_KWH_PER_KM,
                "chargePowerKw": 90.0,
                "initialSoc": 0.8,
                "minSoc": 0.2,
                "enabled": True,
            },
            {
                "id": "ICE_001",
                "type": "ICE",
                "depotId": "DEPOT",
                "fuelTankL": 100.0,
                "fuelConsumptionLPerKm": ICE_L_PER_KM,
                "initialFuelL": 100.0,
                "fuelReserveL": 10.0,
                "enabled": True,
            },
        ),
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        diesel_price_yen_per_l=DIESEL_JPY_PER_L,
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        bev_terminal_soc_policy="return_to_initial",
        charging_power_model="constant_power_v0",
        charge_setup_minutes=0,
        charge_teardown_minutes=0,
        minimum_charge_session_minutes=0,
        canonical_depot_id="DEPOT",
        timestep_min=30,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="13:00",
        enable_contract_overage_penalty=False,
        enable_vehicle_cost=False,
        enable_driver_cost=False,
        enable_other_cost=False,
        cost_component_flags=_accounting_only_cost_flags(),
        milp_max_successors_per_trip=None,
        service_coverage_mode="strict",
    )
    return replace(problem, baseline_plan=None)


def build_simultaneous_bev_problem(
    *,
    charger_ports: int,
) -> CanonicalOptimizationProblem:
    """Build two simultaneous BEV trips that must recharge in one later slot."""

    trips = [
        Trip(
            trip_id=f"parallel-{index + 1}",
            route_id="route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time="08:00",
            arrival_time="09:00",
            distance_km=40.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
            operator_id="tokyu",
        )
        for index in range(2)
    ]
    context = DispatchContext(
        service_date="2025-08-05",
        trips=trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        default_turnaround_min=10,
    )
    scenario_vehicles = tuple(
        {
            "id": f"BEV_{index + 1:03d}",
            "type": "BEV",
            "depotId": "DEPOT",
            "batteryKwh": 100.0,
            "energyConsumption": 1.0,
            "chargePowerKw": 20.0,
            "initialSoc": 0.5,
            "minSoc": 0.2,
            "enabled": True,
        }
        for index in range(2)
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id=f"electric-oracle-ports-{charger_ports}",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"BEV": 2},
        chargers=(
            ChargerDefinition(
                "charger-1",
                "DEPOT",
                20.0,
                simultaneous_ports=charger_ports,
            ),
        ),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=30.0)
            for index in range(4)
        ),
        scenario_vehicles=scenario_vehicles,
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        initial_soc_percent=50.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=50.0,
        final_soc_target_tolerance_percent=0.0,
        bev_terminal_soc_policy="return_to_initial",
        charging_power_model="constant_power_v0",
        charge_setup_minutes=0,
        charge_teardown_minutes=0,
        minimum_charge_session_minutes=0,
        canonical_depot_id="DEPOT",
        timestep_min=60,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="11:00",
        enable_contract_overage_penalty=False,
        enable_vehicle_cost=False,
        enable_driver_cost=False,
        enable_other_cost=False,
        cost_component_flags=_accounting_only_cost_flags(),
        milp_max_successors_per_trip=None,
        service_coverage_mode="strict",
    )
    return replace(problem, baseline_plan=None)


def build_small_electric_oracle_certificate(
    *,
    require_integrated_gurobi: bool = True,
) -> dict[str, Any]:
    """Run the fixed benchmark matrix and return a deterministic certificate."""

    if require_integrated_gurobi and not is_gurobi_available():
        raise RuntimeError(
            "Gurobi is required to certify independent-oracle agreement"
        )

    break_even = break_even_grid_price_jpy_per_kwh()
    low_problem = build_mixed_break_even_problem(
        grid_price_jpy_per_kwh=LOW_GRID_PRICE_JPY_PER_KWH
    )
    high_problem = build_mixed_break_even_problem(
        grid_price_jpy_per_kwh=HIGH_GRID_PRICE_JPY_PER_KWH
    )
    low_oracle = solve_small_exact_electric_oracle(low_problem)
    high_oracle = solve_small_exact_electric_oracle(high_problem)

    low_case = _verified_feasible_case(
        "tariff_below_break_even",
        low_problem,
        low_oracle,
        expected_powertrain="BEV",
        run_integrated=require_integrated_gurobi,
    )
    high_case = _verified_feasible_case(
        "tariff_above_break_even",
        high_problem,
        high_oracle,
        expected_powertrain="ICE",
        run_integrated=require_integrated_gurobi,
    )

    no_charger_problem = _build_no_charger_bev_problem(low_problem)
    no_charger_case = _verified_infeasible_case(
        "terminal_soc_without_charger",
        no_charger_problem,
        expected_enumerated=1,
        expected_dispatch_feasible=1,
    )
    one_port_case = _verified_infeasible_case(
        "one_port_for_two_simultaneous_bevs",
        build_simultaneous_bev_problem(charger_ports=1),
        expected_enumerated=4,
        expected_dispatch_feasible=2,
    )
    two_port_problem = build_simultaneous_bev_problem(charger_ports=2)
    two_port_oracle = solve_small_exact_electric_oracle(two_port_problem)
    two_port_case = _verified_feasible_case(
        "two_ports_for_two_simultaneous_bevs",
        two_port_problem,
        two_port_oracle,
        expected_powertrain="BEV",
        run_integrated=require_integrated_gurobi,
    )
    scope_guards = _verify_scope_guards(low_problem)

    cases = [
        low_case,
        high_case,
        no_charger_case,
        one_port_case,
        two_port_case,
    ]
    checks = {
        "hand_break_even_between_test_tariffs": (
            LOW_GRID_PRICE_JPY_PER_KWH < break_even < HIGH_GRID_PRICE_JPY_PER_KWH
        ),
        "below_break_even_selects_bev": low_case["selected_powertrain"] == "BEV",
        "above_break_even_selects_ice": high_case["selected_powertrain"] == "ICE",
        "canonical_physics_and_accounting_reconcile": all(
            bool(case.get("canonical_validation_ok", False))
            for case in (low_case, high_case, two_port_case)
        ),
        "independent_oracle_matches_integrated_milp": (
            all(
                bool(case.get("integrated_milp_match", False))
                for case in (low_case, high_case, two_port_case)
            )
            if require_integrated_gurobi
            else None
        ),
        "terminal_soc_without_charger_infeasible": no_charger_case["status"]
        == "INFEASIBLE",
        "charger_port_shortage_infeasible": one_port_case["status"]
        == "INFEASIBLE",
        "sufficient_charger_ports_feasible": two_port_case["status"] == "OPTIMAL",
        "positive_pv_rejected_fail_closed": scope_guards["positive_pv"]["passed"],
        "positive_bess_rejected_fail_closed": scope_guards["positive_bess"]["passed"],
    }
    failed_checks = [name for name, passed in checks.items() if passed is False]
    certificate_status = (
        "VERIFIED" if require_integrated_gurobi else "DIAGNOSTIC_INDEPENDENT_ONLY"
    )
    payload: dict[str, Any] = {
        "schema_version": "small_electric_oracle_verification_v1",
        "status": certificate_status if not failed_checks else "FAILED",
        "claim_scope": (
            "bounded_grid_only_electric_formulation_verification_not_full_"
            "network_research_evidence"
        ),
        "research_conclusion_eligible": False,
        "formal_run_substitute": False,
        "integrated_gurobi_comparison_required": require_integrated_gurobi,
        "integrated_gurobi_comparison_status": (
            "VERIFIED" if require_integrated_gurobi else "NOT_RUN_DIAGNOSTIC"
        ),
        "method": (
            "complete_assignment_enumeration_plus_independent_scipy_highs_"
            "charging_compared_with_canonical_validation_and_integrated_gurobi"
        ),
        "scope": {
            "maximum_trips": 10,
            "depots": 1,
            "service_days": 1,
            "pv_kwh": 0.0,
            "bess_kwh": 0.0,
            "tariff": "flat",
            "charging_power_model": "constant_power_v0",
            "bev_terminal_soc_policy": "return_to_initial",
        },
        "coefficients": {
            "bev_kwh_per_km": BEV_KWH_PER_KM,
            "ice_l_per_km": ICE_L_PER_KM,
            "diesel_jpy_per_l": DIESEL_JPY_PER_L,
            "charge_efficiency": CHARGE_EFFICIENCY,
            "hand_break_even_grid_price_jpy_per_kwh": break_even,
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "scope_guards": scope_guards,
        "cases": cases,
    }
    payload["payload_sha256"] = canonical_payload_sha256(payload)
    if failed_checks:
        raise AssertionError(
            "small electric oracle verification failed: "
            + ", ".join(failed_checks)
        )
    return payload


def _accounting_only_cost_flags() -> dict[str, bool]:
    flags = {key: False for key in default_cost_component_flags()}
    flags.update({"electricity_cost": True, "fuel_cost": True})
    return flags


def _integrated_result(problem: CanonicalOptimizationProblem):
    return OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=False,
            research_run=False,
            allow_postsolve_repair=False,
        ),
    )


def _assignment_by_trip(plan) -> dict[str, str]:
    return {
        str(trip_id): str(plan.vehicle_id_for_duty(duty.duty_id))
        for duty in plan.duties
        for trip_id in duty.trip_ids
    }


def _powertrain_assignment_by_trip(
    problem: CanonicalOptimizationProblem,
    assignment_by_trip: Mapping[str, str],
) -> dict[str, str]:
    type_by_vehicle = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type).upper()
        for vehicle in problem.vehicles
    }
    return {
        str(trip_id): type_by_vehicle[str(vehicle_id)]
        for trip_id, vehicle_id in assignment_by_trip.items()
    }


def _selected_powertrain(
    problem: CanonicalOptimizationProblem,
    assignment_by_trip: Mapping[str, str],
) -> str:
    type_by_vehicle = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type).upper()
        for vehicle in problem.vehicles
    }
    selected = {
        type_by_vehicle[str(vehicle_id)]
        for vehicle_id in assignment_by_trip.values()
    }
    return next(iter(selected)) if len(selected) == 1 else "MIXED"


def _verified_feasible_case(
    case_id: str,
    problem: CanonicalOptimizationProblem,
    oracle: SmallElectricOracleResult,
    *,
    expected_powertrain: str,
    run_integrated: bool,
) -> dict[str, Any]:
    assignment = dict(oracle.assignment_by_trip)
    selected_powertrain = _selected_powertrain(problem, assignment)
    if selected_powertrain != expected_powertrain:
        raise AssertionError(
            f"{case_id}: selected {selected_powertrain}, expected {expected_powertrain}"
        )

    feasibility = FeasibilityChecker().evaluate(problem, oracle.plan)
    accounting = CostEvaluator().evaluate(problem, oracle.plan)
    accounting_residual = (
        float(accounting.total_cost) - float(oracle.canonical_operating_cost_jpy)
    )
    canonical_ok = bool(feasibility.feasible) and abs(accounting_residual) <= TOLERANCE_JPY
    if not canonical_ok:
        raise AssertionError(
            f"{case_id}: canonical validation failed: "
            f"{feasibility.errors}, residual={accounting_residual}"
        )

    integrated_summary: dict[str, Any] | None = None
    integrated_match: bool | None = None
    if run_integrated:
        integrated = _integrated_result(problem)
        integrated_assignment = _assignment_by_trip(integrated.plan)
        oracle_powertrains = _powertrain_assignment_by_trip(problem, assignment)
        integrated_powertrains = _powertrain_assignment_by_trip(
            problem, integrated_assignment
        )
        total_cost = float(integrated.cost_breakdown.get("total_cost", 0.0))
        integrated_residual = total_cost - float(oracle.canonical_operating_cost_jpy)
        integrated_grid_import = float(
            integrated.cost_breakdown.get("grid_import_kwh", 0.0)
        )
        integrated_fuel_l = float(
            integrated.cost_breakdown.get("ice_fuel_consumed_l", 0.0)
        )
        grid_import_residual = integrated_grid_import - float(oracle.grid_import_kwh)
        fuel_residual = integrated_fuel_l - float(oracle.fuel_l)
        used_vehicle_count = len(integrated.plan.vehicle_paths())
        exact_vehicle_assignment_match = integrated_assignment == assignment
        integrated_match = bool(
            integrated.feasible
            and not integrated.plan.unserved_trip_ids
            and integrated_powertrains == oracle_powertrains
            and abs(integrated_residual) <= TOLERANCE_JPY
            and abs(grid_import_residual) <= 1.0e-6
            and abs(fuel_residual) <= 1.0e-6
            and used_vehicle_count == oracle.used_vehicle_day_count
        )
        integrated_summary = {
            "solver_status": str(integrated.solver_status),
            "feasible": bool(integrated.feasible),
            "assignment_by_trip": integrated_assignment,
            "powertrain_assignment_by_trip": integrated_powertrains,
            "exact_vehicle_assignment_match": exact_vehicle_assignment_match,
            "assignment_equivalence_semantics": (
                "exact_trip_powertrain_and_cost_match; symmetric_vehicle_id_"
                "permutations_are_recorded_but_not_treated_as_model_disagreement"
            ),
            "canonical_operating_cost_jpy": total_cost,
            "cost_residual_vs_oracle_jpy": integrated_residual,
            "grid_import_kwh": integrated_grid_import,
            "grid_import_residual_vs_oracle_kwh": grid_import_residual,
            "fuel_l": integrated_fuel_l,
            "fuel_residual_vs_oracle_l": fuel_residual,
            "used_vehicle_count": used_vehicle_count,
            "mip_gap_ratio": dict(integrated.solver_metadata or {}).get(
                "final_gap"
            ),
        }
        if not integrated_match:
            raise AssertionError(
                f"{case_id}: integrated MILP did not match independent oracle"
            )

    grid_price = float(problem.price_slots[0].grid_buy_yen_per_kwh)
    return {
        "case_id": case_id,
        "status": "OPTIMAL",
        "grid_price_jpy_per_kwh": grid_price,
        "selected_powertrain": selected_powertrain,
        "trip_count": len(problem.trips),
        "charger_port_count": sum(
            int(charger.simultaneous_ports or 1) for charger in problem.chargers
        ),
        "assignment_by_trip": assignment,
        "enumerated_assignment_count": oracle.enumerated_assignment_count,
        "dispatch_feasible_assignment_count": (
            oracle.dispatch_feasible_assignment_count
        ),
        "energy_feasible_assignment_count": oracle.energy_feasible_assignment_count,
        "used_vehicle_day_count": oracle.used_vehicle_day_count,
        "grid_import_kwh": oracle.grid_import_kwh,
        "fuel_l": oracle.fuel_l,
        "electricity_cost_jpy": oracle.electricity_cost_jpy,
        "fuel_cost_jpy": oracle.fuel_cost_jpy,
        "canonical_operating_cost_jpy": oracle.canonical_operating_cost_jpy,
        "canonical_accounting_residual_jpy": accounting_residual,
        "canonical_validation_ok": canonical_ok,
        "terminal_soc_kwh_by_vehicle": dict(oracle.terminal_soc_kwh_by_vehicle),
        "integrated_milp_match": integrated_match,
        "integrated_milp": integrated_summary,
    }


def _verified_infeasible_case(
    case_id: str,
    problem: CanonicalOptimizationProblem,
    *,
    expected_enumerated: int,
    expected_dispatch_feasible: int,
) -> dict[str, Any]:
    try:
        solve_small_exact_electric_oracle(problem)
    except SmallElectricOracleInfeasibleError as exc:
        if (
            exc.enumerated_assignment_count != expected_enumerated
            or exc.dispatch_feasible_assignment_count != expected_dispatch_feasible
            or exc.energy_feasible_assignment_count != 0
        ):
            raise AssertionError(
                f"{case_id}: unexpected enumeration counts"
            ) from exc
        return {
            "case_id": case_id,
            "status": "INFEASIBLE",
            "trip_count": len(problem.trips),
            "charger_port_count": sum(
                int(charger.simultaneous_ports or 1)
                for charger in problem.chargers
            ),
            **exc.to_metadata(),
        }
    raise AssertionError(f"{case_id}: expected exact infeasibility")


def _build_no_charger_bev_problem(
    problem: CanonicalOptimizationProblem,
) -> CanonicalOptimizationProblem:
    selected_trip = replace(
        problem.trips[0],
        allowed_vehicle_types=("BEV",),
    )
    selected_dispatch_trip = replace(
        problem.dispatch_context.trips[0],
        allowed_vehicle_types=("BEV",),
    )
    return replace(
        problem,
        trips=(selected_trip,),
        dispatch_context=replace(
            problem.dispatch_context,
            trips=[selected_dispatch_trip],
        ),
        feasible_connections={},
        chargers=(),
    )


def _verify_scope_guards(
    problem: CanonicalOptimizationProblem,
) -> dict[str, dict[str, Any]]:
    depot_id, asset = next(iter(problem.depot_energy_assets.items()))
    nonzero_pv = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                pv_enabled=True,
                pv_generation_kwh_by_slot=(1.0,)
                + (0.0,) * (len(problem.price_slots) - 1),
                available_pv_surplus_kwh_by_slot=(1.0,)
                + (0.0,) * (len(problem.price_slots) - 1),
            )
        },
    )
    hidden_bess = replace(
        problem,
        depot_energy_assets={
            depot_id: replace(
                asset,
                bess_enabled=False,
                bess_energy_kwh=1.0,
                bess_soc_max_kwh=1.0,
            )
        },
    )
    return {
        "positive_pv": _expect_scope_rejection(nonzero_pv, "requires PV=0"),
        "positive_bess": _expect_scope_rejection(hidden_bess, "requires BESS=0"),
    }


def _expect_scope_rejection(
    problem: CanonicalOptimizationProblem,
    expected_message: str,
) -> dict[str, Any]:
    try:
        solve_small_exact_electric_oracle(problem)
    except ValueError as exc:
        message = str(exc)
        passed = expected_message in message
        if not passed:
            raise AssertionError(
                f"unexpected scope rejection: {message!r}"
            ) from exc
        return {
            "passed": True,
            "expected_message": expected_message,
            "observed_message": message,
        }
    raise AssertionError(f"expected fail-closed scope rejection: {expected_message}")


def certificate_case_rows(certificate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten case evidence for a compact CSV table."""

    rows: list[dict[str, Any]] = []
    for case in certificate.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        rows.append(
            {
                "case_id": case.get("case_id"),
                "status": case.get("status"),
                "grid_price_jpy_per_kwh": case.get("grid_price_jpy_per_kwh"),
                "selected_powertrain": case.get("selected_powertrain"),
                "trip_count": case.get("trip_count"),
                "charger_port_count": case.get("charger_port_count"),
                "enumerated_assignment_count": case.get(
                    "enumerated_assignment_count"
                ),
                "dispatch_feasible_assignment_count": case.get(
                    "dispatch_feasible_assignment_count"
                ),
                "energy_feasible_assignment_count": case.get(
                    "energy_feasible_assignment_count"
                ),
                "grid_import_kwh": case.get("grid_import_kwh"),
                "fuel_l": case.get("fuel_l"),
                "canonical_operating_cost_jpy": case.get(
                    "canonical_operating_cost_jpy"
                ),
                "canonical_validation_ok": case.get("canonical_validation_ok"),
                "integrated_milp_match": case.get("integrated_milp_match"),
            }
        )
    return rows


def assert_certificate_integrity(
    certificate: Mapping[str, Any],
    *,
    require_integrated_gurobi: bool = False,
) -> None:
    """Validate the self-hash and all mandatory successful checks."""

    declared = str(certificate.get("payload_sha256") or "")
    actual = canonical_payload_sha256(certificate)
    if declared != actual:
        raise ValueError(f"certificate payload_sha256 mismatch: {declared} != {actual}")
    status = str(certificate.get("status"))
    allowed_statuses = {"VERIFIED", "DIAGNOSTIC_INDEPENDENT_ONLY"}
    if status not in allowed_statuses:
        raise ValueError(f"certificate status is not accepted: {status}")
    checks = certificate.get("checks")
    if not isinstance(checks, Mapping):
        raise ValueError("certificate checks must be an object")
    failed = [name for name, passed in checks.items() if passed is False]
    if failed:
        raise ValueError("certificate contains failed checks: " + ", ".join(failed))
    integrated_check = checks.get("independent_oracle_matches_integrated_milp")
    if require_integrated_gurobi and integrated_check is not True:
        raise ValueError("certificate lacks verified integrated Gurobi agreement")
    declared_integrated = bool(
        certificate.get("integrated_gurobi_comparison_required", False)
    )
    if declared_integrated != (integrated_check is True):
        raise ValueError("certificate integrated-Gurobi status is inconsistent")
    break_even = float(
        dict(certificate.get("coefficients") or {}).get(
            "hand_break_even_grid_price_jpy_per_kwh", math.nan
        )
    )
    if not math.isfinite(break_even):
        raise ValueError("certificate break-even tariff is not finite")
