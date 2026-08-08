from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.optimization.common.cost_components import (
    normalize_cost_component_flags,
)
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    PVSlot,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


pytestmark = pytest.mark.skipif(
    not is_gurobi_available(),
    reason="Gurobi is required for the Stage 1 recourse counterexample",
)


def _problem(
    *,
    pv_kwh_by_slot: tuple[float, ...],
    grid_prices: tuple[float, ...] = (30.0, 1.0),
    asset: DepotEnergyAsset | None = None,
    demand_rate_yen_per_kw_month: float = 0.0,
    import_limit_kw: float = 100.0,
    enable_contract_overage_penalty: bool = False,
    contract_overage_penalty_yen_per_kwh: float = 0.0,
) -> CanonicalOptimizationProblem:
    energy_asset = asset or DepotEnergyAsset(
        depot_id="tsurumaki",
        pv_enabled=any(value > 0.0 for value in pv_kwh_by_slot),
        pv_generation_kwh_by_slot=pv_kwh_by_slot,
        bess_enabled=False,
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="weather-coupled-counterexample",
            horizon_start="00:00",
            horizon_end="02:00",
            horizon_duration_min=len(grid_prices) * 60,
            timestep_min=60,
            demand_charge_on_peak_yen_per_kw=(
                demand_rate_yen_per_kw_month
            ),
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev",
                vehicle_type="BEV",
                home_depot_id="tsurumaki",
                battery_capacity_kwh=100.0,
                initial_soc=0.5,
                reserve_soc=0.1,
                charge_power_max_kw=10.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="tsurumaki",
                name="Tsurumaki",
                import_limit_kw=import_limit_kw,
            ),
        ),
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=index,
                grid_buy_yen_per_kwh=price,
                demand_charge_weight=1.0 if index == 0 else 0.0,
            )
            for index, price in enumerate(grid_prices)
        ),
        depot_energy_assets={"tsurumaki": energy_asset},
        metadata={
            "cost_component_flags": {
                "electricity_cost": True,
                "demand_charge_cost": True,
                "co2_cost": False,
            },
            "enable_contract_overage_penalty": (
                enable_contract_overage_penalty
            ),
            "contract_overage_penalty_yen_per_kwh": (
                contract_overage_penalty_yen_per_kwh
            ),
        },
    )


def _solve_counterexample(
    pv_kwh_by_slot: tuple[float, float],
    *,
    fixed_assignment: int | None = None,
) -> tuple[int, dict[str, object], dict[str, object]]:
    gp, grb = ensure_gurobi()
    model = gp.Model("weather_coupled_assignment_counterexample")
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.Seed = 42

    # assignment=1 is the duty that returns for the first (midday-PV) slot.
    # assignment=0 is the otherwise-equivalent duty whose only charging window
    # is the second, cheap-grid slot.  The five-yen term represents the fixed
    # ICE-side difference for the complementary duty, not a weather bias.
    assignment = model.addVar(vtype=grb.BINARY, name="midday_return_duty")
    charge_midday = model.addVar(
        lb=0.0, ub=10.0, vtype=grb.CONTINUOUS, name="charge_midday_kw"
    )
    charge_late = model.addVar(
        lb=0.0, ub=10.0, vtype=grb.CONTINUOUS, name="charge_late_kw"
    )
    model.addConstr(charge_midday <= 10.0 * assignment)
    model.addConstr(charge_late <= 10.0 * (1.0 - assignment))
    model.addConstr(charge_midday + charge_late == 10.0)
    if fixed_assignment is not None:
        model.addConstr(assignment == int(fixed_assignment))

    problem = _problem(pv_kwh_by_slot=pv_kwh_by_slot)
    recourse = (
        GurobiMILPAdapter()
        ._add_stage1_time_indexed_energy_recourse_relaxation(
            model,
            gp=gp,
            grb=grb,
            problem=problem,
            recourse_state={
                "slot_indices": (0, 1),
                "timestep_h": 1.0,
                "charge_power_by_vehicle_slot": {
                    ("bev", 0): charge_midday,
                    ("bev", 1): charge_late,
                },
                "electric_vehicle_by_id": {
                    "bev": problem.vehicles[0],
                },
            },
            component_flags=normalize_cost_component_flags(
                problem.metadata["cost_component_flags"]
            ),
        )
    )
    model.setObjective(
        recourse.objective_expression + 5.0 * assignment,
        grb.MINIMIZE,
    )
    model.optimize()
    assert model.Status == grb.OPTIMAL
    result = (
        GurobiMILPAdapter()
        ._stage1_time_indexed_energy_recourse_result(recourse)
    )
    return (
        int(float(assignment.X) > 0.5),
        dict(recourse.configuration),
        result,
    )


def _full_phase3_counterexample(
    *,
    sunny_midday_pv_kwh: float,
) -> CanonicalOptimizationProblem:
    trip_specs = (
        (
            "midday-return",
            "06:00",
            "07:00",
            20.0,
            6 * 60,
            7 * 60,
        ),
        (
            "away-through-midday",
            "06:00",
            "13:00",
            10.0,
            6 * 60,
            13 * 60,
        ),
    )
    dispatch_trips = tuple(
        Trip(
            trip_id=trip_id,
            route_id="weather-coupled-route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time=departure,
            arrival_time=arrival,
            distance_km=distance_km,
            allowed_vehicle_types=("BEV", "ICE"),
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
        )
        for (
            trip_id,
            departure,
            arrival,
            distance_km,
            _departure_min,
            _arrival_min,
        ) in trip_specs
    )
    problem_trips = tuple(
        ProblemTrip(
            trip_id=trip_id,
            route_id="weather-coupled-route",
            origin="DEPOT",
            destination="DEPOT",
            departure_min=departure_min,
            arrival_min=arrival_min,
            distance_km=distance_km,
            energy_kwh=distance_km,
            allowed_vehicle_types=("BEV", "ICE"),
        )
        for (
            trip_id,
            _departure,
            _arrival,
            distance_km,
            departure_min,
            arrival_min,
        ) in trip_specs
    )
    pv_by_slot = (
        0.0,
        sunny_midday_pv_kwh,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="full-weather-coupled-counterexample",
            horizon_start="06:00",
            horizon_end="15:00",
            horizon_duration_min=9 * 60,
            timestep_min=60,
            service_coverage_mode="strict",
            diesel_price_yen_per_l=1.0,
        ),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=list(dispatch_trips),
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=100.0,
                    energy_consumption_kwh_per_km=1.0,
                ),
                "ICE": VehicleProfile(
                    vehicle_type="ICE",
                    fuel_consumption_l_per_km=1.0,
                ),
            },
        ),
        trips=problem_trips,
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-weather",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                initial_soc=0.30,
                battery_capacity_kwh=100.0,
                reserve_soc=0.10,
                energy_consumption_kwh_per_km=1.0,
                charge_power_max_kw=50.0,
            ),
            ProblemVehicle(
                vehicle_id="ice-weather",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
                fuel_consumption_l_per_km=1.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=100.0,
                charge_power_max_kw=50.0,
                reserve_soc=0.10,
                energy_consumption_kwh_per_km=1.0,
            ),
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=1.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="DEPOT",
                name="Counterexample depot",
                charger_ids=("weather-charger",),
                import_limit_kw=100.0,
            ),
        ),
        chargers=(
            ChargerDefinition(
                charger_id="weather-charger",
                depot_id="DEPOT",
                power_kw=50.0,
                simultaneous_ports=1,
            ),
        ),
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(9)
        ),
        depot_energy_assets={
            "DEPOT": DepotEnergyAsset(
                depot_id="DEPOT",
                pv_enabled=sunny_midday_pv_kwh > 0.0,
                pv_generation_kwh_by_slot=pv_by_slot,
                bess_enabled=False,
            )
        },
        metadata={
            "bev_terminal_soc_policy": "return_to_initial",
            "final_soc_floor_percent": 10.0,
            "milp_max_successors_per_trip": None,
            "stage2_feedback_max_iterations": 0,
            "cost_component_flags": {
                "electricity_cost": True,
                "fuel_cost": True,
                "demand_charge_cost": False,
                "vehicle_fixed_cost": True,
                "vehicle_usage_cost": True,
                "driver_cost": True,
                "battery_degradation_cost": True,
                "co2_cost": False,
                "contract_overage_penalty": False,
                "charge_session_start_penalty": False,
                "slot_concurrency_penalty": False,
                "early_charge_penalty": False,
                "soc_upper_buffer_penalty": False,
                "opportunistic_topup_penalty": False,
            },
        },
    )


def _solve_full_phase3_assignment(
    *,
    sunny_midday_pv_kwh: float,
    candidate_limit: int = 1,
) -> tuple[dict[str, str], dict[str, object]]:
    result = MILPOptimizer().solve(
        _full_phase3_counterexample(
            sunny_midday_pv_kwh=sunny_midday_pv_kwh
        ),
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=30,
            stage1_time_limit_sec=20,
            stage2_time_limit_sec=10,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=candidate_limit,
            gurobi_threads=1,
        ),
    )
    assert result.feasible, result.infeasibility_reasons
    assignment = {
        str(trip_id): str(duty.vehicle_type)
        for duty in result.plan.duties
        for trip_id in duty.trip_ids
    }
    return assignment, dict(result.plan.metadata)


def _full_phase3_composition_counterexample() -> CanonicalOptimizationProblem:
    """Return two interchangeable BEVs and ICE buses for count search tests."""

    base = _full_phase3_counterexample(sunny_midday_pv_kwh=0.0)
    bev, ice = base.vehicles
    return replace(
        base,
        vehicles=(
            replace(bev, vehicle_id="bev-weather-1"),
            replace(bev, vehicle_id="bev-weather-2"),
            replace(ice, vehicle_id="ice-weather-1"),
            replace(ice, vehicle_id="ice-weather-2"),
        ),
    )


def test_full_phase3_assignment_changes_from_physical_pv_timing() -> None:
    sunny_assignment, sunny_metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=25.0
    )
    rain_assignment, rain_metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=0.0
    )

    assert sunny_assignment == {
        "midday-return": "BEV",
        "away-through-midday": "ICE",
    }
    assert rain_assignment == {
        "midday-return": "ICE",
        "away-through-midday": "BEV",
    }
    assert (
        sunny_metadata[
            "stage1_time_indexed_energy_recourse_configuration"
        ]["objective_coefficient_and_rhs_hash"]
        != rain_metadata[
            "stage1_time_indexed_energy_recourse_configuration"
        ]["objective_coefficient_and_rhs_hash"]
    )
    assert sunny_metadata["stage2_feasible"] is True
    assert rain_metadata["stage2_feasible"] is True
    assert sunny_metadata["stage1_accounting_objective_components"][
        "arbitrary_weather_assignment_bias"
    ] is False


def test_full_phase3_same_input_and_pv_reproduces_assignment() -> None:
    first_assignment, first_metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=25.0
    )
    second_assignment, second_metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=25.0
    )

    assert first_assignment == second_assignment
    assert (
        first_metadata[
            "stage1_time_indexed_energy_recourse_configuration"
        ]["objective_coefficient_and_rhs_hash"]
        == second_metadata[
            "stage1_time_indexed_energy_recourse_configuration"
        ]["objective_coefficient_and_rhs_hash"]
    )


def test_phase3_selects_lowest_canonical_cost_from_exact_stage2_candidates() -> None:
    assignment, metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=25.0,
        candidate_limit=2,
    )
    candidates = list(metadata["stage1_stage2_candidate_evaluation"])
    feasible_costs = [
        float(item["stage2_actual_canonical_cost_jpy"])
        for item in candidates
        if item["feasible"]
    ]

    assert assignment["midday-return"] == "BEV"
    assert metadata["stage1_stage2_candidate_limit_requested"] == 2
    assert metadata["stage1_distinct_candidate_count"] == 2
    assert len(candidates) == 2
    assert len(feasible_costs) == 2
    assert metadata[
        "stage1_stage2_selected_canonical_actual_cost_jpy"
    ] == pytest.approx(min(feasible_costs))
    selected_index = int(
        metadata["stage1_stage2_selected_candidate_index"]
    )
    assert metadata["stage1_objective"] == pytest.approx(
        metadata["stage1_primary_incumbent_objective_jpy"]
    )
    assert metadata[
        "stage1_selected_candidate_relaxed_objective_jpy"
    ] == pytest.approx(
        candidates[selected_index - 1][
            "stage1_relaxed_objective_jpy"
        ]
    )
    assert (
        metadata["stage1_stage2_candidate_global_optimality_claimed"]
        is False
    )


def test_candidate_audit_enumerates_distinct_powertrain_patterns() -> None:
    _assignment, metadata = _solve_full_phase3_assignment(
        sunny_midday_pv_kwh=25.0,
        candidate_limit=3,
    )
    candidates = list(metadata["stage1_stage2_candidate_evaluation"])
    powertrain_patterns = {
        tuple(
            sorted(
                (
                    str(item["trip_id"]),
                    str(item["powertrain"]),
                )
                for item in candidate["vehicle_trip_assignments"]
            )
        )
        for candidate in candidates
    }

    # This fixture owns only one BEV and one ICE, so its two overlapping trips
    # admit exactly the two opposite powertrain patterns.
    assert len(candidates) == 2
    assert len(powertrain_patterns) == 2
    assert all(candidate["feasible"] for candidate in candidates)
    assert all(
        candidate["physical_validation_feasible"]
        for candidate in candidates
    )
    assert all(
        candidate["physical_validation_error_count"] == 0
        for candidate in candidates
    )
    assert (
        metadata[
            "stage1_candidate_powertrain_pattern_no_good_cut_count"
        ]
        >= 1
    )
    assert metadata["stage1_candidate_enumeration_events"][0][
        "partial_mip_start_applied"
    ] is True
    assert (
        metadata["stage1_candidate_enumeration_events"][0][
            "partial_mip_start_semantics"
        ]
        == "opposite_powertrain_whole_duty_swap_search_hint_"
        "validated_by_unchanged_stage1_model"
    )
    assert metadata["stage1_candidate_enumeration_events"][-1][
        "solver_status"
    ] == "infeasible"
    assert metadata["stage1_runtime_seconds"] == pytest.approx(
        metadata["stage1_primary_runtime_seconds"]
        + metadata["stage1_candidate_enumeration_runtime_seconds"]
    )


def test_phase3_composition_search_activates_unused_powertrain_inventory() -> None:
    """Adjacent used-count candidates are not limited to duty swaps."""

    result = MILPOptimizer().solve(
        _full_phase3_composition_counterexample(),
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=60,
            stage1_time_limit_sec=40,
            stage2_time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=3,
            stage1_composition_search_radius=100,
            gurobi_threads=1,
        ),
    )
    assert result.feasible, result.infeasibility_reasons
    metadata = dict(result.plan.metadata)
    certificate = dict(
        metadata["stage1_used_powertrain_composition_search"]
    )
    candidate_rows = list(metadata["stage1_stage2_candidate_evaluation"])
    feasible_compositions = {
        (int(row["used_bev"]), int(row["used_ice"]))
        for row in candidate_rows
        if row["feasible"] is True
    }

    assert certificate["enabled"] is True
    assert certificate["radius_requested"] == 100
    assert metadata[
        "stage1_composition_target_time_limit_cap_seconds"
    ] == pytest.approx(25.0)
    assert len(feasible_compositions) >= 2
    assert certificate["multiple_feasible_compositions_found"] is True
    assert certificate["accepted_for_formal_composition_evidence"] is True
    assert all(
        int(record["target_used_bev"]) >= 0
        and int(record["target_used_ice"]) >= 0
        for record in certificate["target_records"]
    )
    assert any(
        row["stage1_candidate_source"]
        == "used_powertrain_composition_neighborhood"
        for row in candidate_rows
    )
    assert any(
        row.get("final_disposition")
        == "physically_feasible_stage2_candidate"
        for row in certificate["target_records"]
    )
    assert all(
        row.get("final_disposition") != "stage1_infeasibility_certificate"
        or row.get("solver_status") == "infeasible"
        for row in certificate["target_records"]
    )


def test_phase3_composition_infeasibility_certificate_requires_iis_and_lp_hash() -> None:
    """Count-neighborhood infeasibility is formal evidence only with an IIS."""

    base = _full_phase3_composition_counterexample()
    allowed_types_by_trip = {
        "midday-return": ("BEV",),
        "away-through-midday": ("ICE",),
    }
    problem = replace(
        base,
        trips=tuple(
            replace(
                trip,
                allowed_vehicle_types=allowed_types_by_trip[trip.trip_id],
            )
            for trip in base.trips
        ),
        dispatch_context=replace(
            base.dispatch_context,
            trips=[
                replace(
                    trip,
                    allowed_vehicle_types=allowed_types_by_trip[trip.trip_id],
                )
                for trip in base.dispatch_context.trips
            ],
        ),
    )
    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=60,
            stage1_time_limit_sec=40,
            stage2_time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=3,
            stage1_composition_search_radius=1,
            gurobi_threads=1,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    certificate = dict(
        result.plan.metadata["stage1_used_powertrain_composition_search"]
    )
    target_records = list(certificate["target_records"])
    infeasibility_certificates = [
        dict(record["infeasibility_certificate"])
        for record in target_records
        if record.get("final_disposition")
        == "stage1_infeasibility_certificate"
    ]

    assert certificate["multiple_feasible_compositions_found"] is False
    assert certificate["all_adjacent_targets_certified_infeasible"] is True
    assert certificate["accepted_for_formal_composition_evidence"] is True
    assert len(infeasibility_certificates) == 2
    assert all(item["iis_generated"] is True for item in infeasibility_certificates)
    assert all(
        item["target_count_constraint_in_iis"] is True
        for item in infeasibility_certificates
    )
    assert all(
        len(item["stage1_model_lp_sha256"]) == 64
        for item in infeasibility_certificates
    )
    assert all(
        len(item["solver_controls_hash"]) == 64
        for item in infeasibility_certificates
    )
    assert all(
        item["accepted_for_formal_composition_evidence"] is True
        for item in infeasibility_certificates
    )


def test_weather_energy_fuel_certificate_is_a_pv_sensitive_lower_bound() -> None:
    adapter = GurobiMILPAdapter()

    def _certificate_for_problem(
        problem: CanonicalOptimizationProblem,
    ) -> dict[str, object]:
        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle
            for vehicle in problem.vehicles
        }
        compatible_by_trip = {
            str(trip.trip_id): [
                str(vehicle.vehicle_id)
                for vehicle in problem.vehicles
                if str(vehicle.vehicle_type)
                in set(trip.allowed_vehicle_types)
            ]
            for trip in problem.trips
        }
        return adapter._stage1_analytical_weather_energy_fuel_lower_bound(
            problem=problem,
            assignment_vehicle_ids_by_trip=compatible_by_trip,
            vehicle_by_id=vehicle_by_id,
            component_flags=normalize_cost_component_flags(
                problem.metadata["cost_component_flags"]
            ),
        )

    def _certificate(pv_kwh: float) -> dict[str, object]:
        return _certificate_for_problem(
            _full_phase3_counterexample(
                sunny_midday_pv_kwh=pv_kwh
            )
        )

    sunny = _certificate(25.0)
    rain = _certificate(0.0)
    global_fallback = _certificate_for_problem(
        replace(
            _full_phase3_counterexample(
                sunny_midday_pv_kwh=0.0
            ),
            depot_energy_assets={},
            pv_slots=(
                PVSlot(slot_index=1, pv_available_kw=25.0),
            ),
        )
    )

    assert sunny["valid"] is True
    assert rain["valid"] is True
    assert float(sunny["lower_bound_jpy"]) >= 0.0
    assert float(rain["lower_bound_jpy"]) > float(
        sunny["lower_bound_jpy"]
    )
    assert sunny["certificate_input_hash"] != rain[
        "certificate_input_hash"
    ]
    assert global_fallback["pooled_asset_pv_kwh"] == pytest.approx(0.0)
    assert global_fallback[
        "pooled_global_pv_fallback_kwh"
    ] == pytest.approx(25.0)
    assert global_fallback["global_pv_fallback_depot_ids"] == ["DEPOT"]
    assert global_fallback["lower_bound_jpy"] == pytest.approx(
        sunny["lower_bound_jpy"]
    )


def test_total_analytical_bound_fails_closed_for_negative_fixed_cost() -> None:
    problem = _full_phase3_counterexample(
        sunny_midday_pv_kwh=25.0
    )
    problem = replace(
        problem,
        vehicles=tuple(
            replace(vehicle, fixed_use_cost_jpy=-1.0)
            if index == 0
            else vehicle
            for index, vehicle in enumerate(problem.vehicles)
        ),
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=30,
            stage1_time_limit_sec=20,
            stage2_time_limit_sec=10,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=1,
            gurobi_threads=1,
        ),
    )

    metadata = dict(result.plan.metadata or {})
    assert (
        metadata[
            "stage1_analytical_total_objective_certificate_eligible"
        ]
        is False
    )
    assert metadata[
        "stage1_analytical_total_objective_certificate_blockers"
    ] == ("negative_vehicle_fixed_use_cost",)
    assert metadata["stage1_analytical_objective_lower_bound"] is None


def test_slot_level_pv_changes_the_economic_assignment_without_weather_bias() -> None:
    sunny_assignment, sunny_config, sunny_result = _solve_counterexample(
        (10.0, 0.0)
    )
    rain_assignment, rain_config, rain_result = _solve_counterexample(
        (0.0, 0.0)
    )

    assert sunny_assignment == 1
    assert rain_assignment == 0
    assert (
        sunny_config["objective_coefficient_and_rhs_hash"]
        != rain_config["objective_coefficient_and_rhs_hash"]
    )
    assert sunny_config["arbitrary_weather_assignment_bias_used"] is False
    assert rain_config["arbitrary_weather_assignment_bias_used"] is False
    assert sunny_result["pv_to_bus_kwh"] == pytest.approx(10.0)
    assert sunny_result["grid_to_bus_kwh"] == pytest.approx(0.0)
    assert rain_result["pv_to_bus_kwh"] == pytest.approx(0.0)
    assert rain_result["grid_to_bus_kwh"] == pytest.approx(10.0)


def test_pv_cannot_be_shifted_from_its_generation_slot() -> None:
    _assignment, _config, result = _solve_counterexample(
        (0.0, 10.0),
        fixed_assignment=1,
    )

    # The selected midday-return duty would need energy in slot 0. PV that
    # exists only in slot 1 cannot offset that purchase.
    grid_by_slot = result["grid_to_bus_kwh_by_depot_slot"]["tsurumaki"]
    pv_by_slot = result["pv_to_bus_kwh_by_depot_slot"]["tsurumaki"]
    assert grid_by_slot["0"] == pytest.approx(10.0)
    assert pv_by_slot["0"] == pytest.approx(0.0)
    assert pv_by_slot["1"] == pytest.approx(0.0)


def test_bess_terminal_soc_prevents_free_initial_inventory_discharge() -> None:
    gp, grb = ensure_gurobi()
    model = gp.Model("weather_coupled_bess_terminal")
    model.Params.OutputFlag = 0
    charge = model.addVar(lb=5.0, ub=5.0, vtype=grb.CONTINUOUS)
    asset = DepotEnergyAsset(
        depot_id="tsurumaki",
        pv_enabled=False,
        pv_generation_kwh_by_slot=(0.0,),
        bess_enabled=True,
        bess_energy_kwh=10.0,
        bess_power_kw=10.0,
        bess_initial_soc_kwh=5.0,
        bess_soc_min_kwh=0.0,
        bess_soc_max_kwh=10.0,
        bess_terminal_soc_policy="return_to_initial",
        allow_grid_to_bess=False,
        allow_bess_to_bus=True,
    )
    problem = _problem(
        pv_kwh_by_slot=(0.0,),
        grid_prices=(100.0,),
        asset=asset,
    )
    recourse = (
        GurobiMILPAdapter()
        ._add_stage1_time_indexed_energy_recourse_relaxation(
            model,
            gp=gp,
            grb=grb,
            problem=problem,
            recourse_state={
                "slot_indices": (0,),
                "timestep_h": 1.0,
                "charge_power_by_vehicle_slot": {("bev", 0): charge},
                "electric_vehicle_by_id": {"bev": problem.vehicles[0]},
            },
            component_flags=normalize_cost_component_flags(
                problem.metadata["cost_component_flags"]
            ),
        )
    )
    model.setObjective(recourse.objective_expression, grb.MINIMIZE)
    model.optimize()
    assert model.Status == grb.OPTIMAL
    result = (
        GurobiMILPAdapter()
        ._stage1_time_indexed_energy_recourse_result(recourse)
    )
    assert result["bess_to_bus_kwh"] == pytest.approx(0.0)
    assert result["grid_to_bus_kwh"] == pytest.approx(5.0)
    assert result["bess_soc_kwh_by_depot_slot"]["tsurumaki"]["0"] == (
        pytest.approx(5.0)
    )


def test_demand_charge_is_applied_to_peak_kw_not_slot_energy_sum() -> None:
    gp, grb = ensure_gurobi()
    model = gp.Model("weather_coupled_demand_charge")
    model.Params.OutputFlag = 0
    charge_on_peak = model.addVar(
        lb=10.0, ub=10.0, vtype=grb.CONTINUOUS
    )
    charge_off_peak = model.addVar(
        lb=0.0, ub=0.0, vtype=grb.CONTINUOUS
    )
    # For a two-hour horizon, 3600 JPY/kW/month converts to 10 JPY/kW.
    problem = _problem(
        pv_kwh_by_slot=(0.0, 0.0),
        grid_prices=(0.0, 0.0),
        demand_rate_yen_per_kw_month=3600.0,
    )
    recourse = (
        GurobiMILPAdapter()
        ._add_stage1_time_indexed_energy_recourse_relaxation(
            model,
            gp=gp,
            grb=grb,
            problem=problem,
            recourse_state={
                "slot_indices": (0, 1),
                "timestep_h": 1.0,
                "charge_power_by_vehicle_slot": {
                    ("bev", 0): charge_on_peak,
                    ("bev", 1): charge_off_peak,
                },
                "electric_vehicle_by_id": {"bev": problem.vehicles[0]},
            },
            component_flags=normalize_cost_component_flags(
                problem.metadata["cost_component_flags"]
            ),
        )
    )
    model.setObjective(recourse.objective_expression, grb.MINIMIZE)
    model.optimize()
    assert model.Status == grb.OPTIMAL
    result = (
        GurobiMILPAdapter()
        ._stage1_time_indexed_energy_recourse_result(recourse)
    )
    assert result["peak_on_kw_by_depot"]["tsurumaki"] == pytest.approx(10.0)
    assert result["objective_jpy"] == pytest.approx(100.0)


def test_stage1_contract_overage_uses_penalized_soft_limit() -> None:
    gp, grb = ensure_gurobi()
    model = gp.Model("weather_coupled_contract_overage")
    model.Params.OutputFlag = 0
    charge = model.addVar(
        lb=10.0,
        ub=10.0,
        vtype=grb.CONTINUOUS,
    )
    problem = _problem(
        pv_kwh_by_slot=(0.0,),
        grid_prices=(0.0,),
        import_limit_kw=5.0,
        enable_contract_overage_penalty=True,
        contract_overage_penalty_yen_per_kwh=20.0,
    )
    recourse = (
        GurobiMILPAdapter()
        ._add_stage1_time_indexed_energy_recourse_relaxation(
            model,
            gp=gp,
            grb=grb,
            problem=problem,
            recourse_state={
                "slot_indices": (0,),
                "timestep_h": 1.0,
                "charge_power_by_vehicle_slot": {("bev", 0): charge},
                "electric_vehicle_by_id": {"bev": problem.vehicles[0]},
            },
            component_flags=normalize_cost_component_flags(
                problem.metadata["cost_component_flags"]
            ),
        )
    )
    model.setObjective(recourse.objective_expression, grb.MINIMIZE)
    model.optimize()

    assert model.Status == grb.OPTIMAL
    result = (
        GurobiMILPAdapter()
        ._stage1_time_indexed_energy_recourse_result(recourse)
    )
    assert result["grid_import_kwh"] == pytest.approx(10.0)
    assert result["contract_overage_kwh"] == pytest.approx(5.0)
    assert result["objective_jpy"] == pytest.approx(100.0)


def test_stage2_contract_overage_matches_stage1_soft_limit() -> None:
    problem = _full_phase3_counterexample(sunny_midday_pv_kwh=0.0)
    problem = replace(
        problem,
        depots=(
            replace(problem.depots[0], import_limit_kw=0.5),
        ),
        metadata={
            **dict(problem.metadata),
            "cost_component_flags": {
                **dict(problem.metadata["cost_component_flags"]),
                "contract_overage_penalty": True,
            },
            "enable_contract_overage_penalty": True,
            "contract_overage_penalty_yen_per_kwh": 20.0,
            "stage2_feedback_max_iterations": 0,
        },
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            thesis_mode=True,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=30,
            stage1_time_limit_sec=20,
            stage2_time_limit_sec=10,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=1,
            gurobi_threads=1,
        ),
    )

    # Stage 2 mirrors the soft contract-overage model. The independent engine
    # validator still rejects the resulting over-contract physical schedule,
    # which is the required formal-run gate.
    assert result.plan.metadata["stage2_feasible"] is True
    assert result.feasible is False
    assert any(
        "contract power violations" in reason
        for reason in result.infeasibility_reasons
    )
    assert result.plan.metadata["stage2_contract_overage_enabled"] is True
    assert result.plan.metadata["stage2_contract_overage_kwh"] > 0.0
    assert (
        CostEvaluator()
        .evaluate(problem, result.plan)
        .contract_overage_cost
        > 0.0
    )
