from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.common.result import ResultSerializer
from src.optimization.validation.fixed_solution_stress import (
    FixedSolutionStress,
    apply_fixed_solution_stress,
    evaluate_fixed_solution_stress,
    standard_fixed_solution_stresses,
)


def _problem_and_canonical_result() -> tuple[CanonicalOptimizationProblem, dict]:
    dispatch_trip = Trip(
        trip_id="trip-1",
        route_id="route-1",
        origin="depot-1",
        destination="depot-1",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        operator_id="operator-1",
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="fixed-stress",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-08-22",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={},
        ),
        trips=(
            ProblemTrip(
                trip_id="trip-1",
                route_id="route-1",
                origin="depot-1",
                destination="depot-1",
                departure_min=480,
                arrival_min=540,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=10.0,
                energy_kwh_by_vehicle_type={"BEV": 10.0},
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="depot-1",
                initial_soc=15.0,
                battery_capacity_kwh=20.0,
                reserve_soc=5.0,
            ),
        ),
        depots=(ProblemDepot(depot_id="depot-1", name="Depot", charger_ids=("charger-1",)),),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=20.0,
            ),
        ),
        chargers=(ChargerDefinition(charger_id="charger-1", depot_id="depot-1", power_kw=50.0),),
        price_slots=tuple(EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=20.0) for index in range(24)),
        depot_energy_assets={
            "depot-1": DepotEnergyAsset(
                depot_id="depot-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=tuple(10.0 if index == 0 else 0.0 for index in range(24)),
            )
        },
        metadata={"charging_efficiency": 1.0},
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="bev-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=dispatch_trip),),
            ),
        ),
        pv_to_bus_kwh_by_depot_slot={"depot-1": {0: 10.0}},
        served_trip_ids=("trip-1",),
        metadata={"duty_vehicle_map": {"bev-1": "bev-1"}},
    )
    return problem, ResultSerializer.serialize_plan(plan)


def test_standard_fixed_solution_stresses_cover_requested_cases() -> None:
    _problem, canonical = _problem_and_canonical_result()
    canonical["charging_schedule"] = [{"charger_id": "charger-1"}]

    stresses = standard_fixed_solution_stresses(canonical)

    assert [stress.name for stress in stresses] == [
        "bev_energy_plus_10pct",
        "bev_energy_plus_20pct",
        "travel_time_plus_10pct",
        "pv_minus_20pct",
        "one_charger_outage",
        "initial_soc_minus_5pp",
        "combined_energy20_time10_pv20_charger_soc5",
    ]


def test_standard_fixed_solution_stresses_rejects_an_unexercised_outage() -> None:
    _problem, canonical = _problem_and_canonical_result()

    with pytest.raises(ValueError, match="used physical charger"):
        standard_fixed_solution_stresses(canonical)


def test_apply_fixed_solution_stress_changes_only_declared_inputs() -> None:
    problem, _canonical = _problem_and_canonical_result()
    stress = FixedSolutionStress(
        name="combined",
        energy_scale=1.2,
        travel_time_scale=1.1,
        pv_scale=0.8,
        charger_outage_id="charger-1",
        initial_soc_delta_percentage_points=-5.0,
    )

    stressed = apply_fixed_solution_stress(problem, stress)

    assert stressed.trips[0].energy_kwh == 12.0
    assert stressed.trips[0].energy_kwh_by_vehicle_type == {"BEV": 12.0}
    assert stressed.trips[0].arrival_min == 546
    assert stressed.dispatch_context.trips[0].arrival_time == "09:06"
    assert stressed.vehicles[0].initial_soc == 14.0
    assert stressed.chargers == ()
    assert stressed.depot_energy_assets["depot-1"].pv_generation_kwh_by_slot[0] == 8.0
    assert problem.trips[0].arrival_min == 540
    assert problem.vehicles[0].initial_soc == 15.0


def test_fixed_solution_stress_fails_closed_without_reoptimization() -> None:
    problem, canonical = _problem_and_canonical_result()

    result = evaluate_fixed_solution_stress(
        problem=problem,
        canonical_result=canonical,
        stress=FixedSolutionStress(name="energy20", energy_scale=1.2),
    )

    assert result["reoptimization_performed"] is False
    assert result["physical_accepted"] is False
    assert result["completion_rate"] == 1.0
    assert result["minimum_soc_kwh"] == 3.0
    assert result["fixed_decision_cost_jpy"] is None
    assert result["additional_cost_jpy"] is None
    assert result["cost_status"] == "unavailable_due_to_fixed_decision_physical_failure"


def test_fixed_solution_stress_rejects_pv_flow_above_reduced_supply() -> None:
    problem, canonical = _problem_and_canonical_result()

    result = evaluate_fixed_solution_stress(
        problem=problem,
        canonical_result=canonical,
        stress=FixedSolutionStress(name="pv20", pv_scale=0.8),
    )

    assert result["physical_accepted"] is False
    assert result["pv_supply_violations"] == [
        {
            "code": "pv_supply_exceeded",
            "depot_id": "depot-1",
            "slot_index": 0,
            "used_kwh": 10.0,
            "available_kwh": 8.0,
        }
    ]
    assert result["additional_cost_jpy"] is None
