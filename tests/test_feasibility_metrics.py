from __future__ import annotations

from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
)


def test_feasible_requires_energy_contract_and_charger_metrics_clean() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(vehicle_id="v1", vehicle_type="BEV", home_depot_id="dep", battery_capacity_kwh=100.0),
            ProblemVehicle(vehicle_id="v2", vehicle_type="BEV", home_depot_id="dep", battery_capacity_kwh=100.0),
        ),
        depots=(ProblemDepot(depot_id="dep", name="Depot", import_limit_kw=1.0),),
        chargers=(ChargerDefinition(charger_id="c1", depot_id="dep", power_kw=50.0, simultaneous_ports=1),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        depot_energy_assets={
            "dep": DepotEnergyAsset(
                depot_id="dep",
                bess_enabled=True,
                bess_energy_kwh=10.0,
                bess_power_kw=10.0,
                bess_initial_soc_kwh=0.0,
                bess_soc_min_kwh=0.0,
                bess_soc_max_kwh=10.0,
                bess_discharge_efficiency=1.0,
                bess_terminal_soc_min_kwh=1.0,
            )
        },
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(vehicle_id="v1", slot_index=0, charger_id="grid:dep", charge_kw=10.0, charging_depot_id="dep"),
            ChargingSlot(vehicle_id="v2", slot_index=0, charger_id="grid:dep", charge_kw=10.0, charging_depot_id="dep"),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep": {0: 10.0}},
        bess_to_bus_kwh_by_depot_slot={"dep": {0: 2.0}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert report.metrics["contract_power_violation_count"] == 1
    assert report.metrics["charger_concurrency_violation_count"] == 1
    assert report.metrics["bess_soc_violation_count"] > 0
    assert report.metrics["bess_terminal_soc_deviation_kwh"] > 0.0


def test_physical_charger_validator_rejects_power_above_selected_type() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="physical", timestep_min=15),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep",
                charge_power_max_kw=90.0,
            ),
        ),
        chargers=(
            ChargerDefinition(
                charger_id="charger-50",
                depot_id="dep",
                power_kw=50.0,
                simultaneous_ports=1,
            ),
        ),
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="bev-1",
                slot_index=0,
                charger_id="charger-50",
                energy_source="grid",
                charge_kw=90.0,
                charging_depot_id="dep",
            ),
        ),
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.metrics["charger_concurrency_violation_count"] == 1
    assert report.feasible is False


def test_assignment_diagnostics_report_the_exact_rejected_trip_connection() -> None:
    previous = Trip(
        trip_id="t1",
        route_id="r",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    following = Trip(
        trip_id="t2",
        route_id="r",
        origin="C",
        destination="D",
        departure_time="08:40",
        arrival_time="09:10",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-diagnostics", timestep_min=60),
        dispatch_context=DispatchContext(
            service_date="2026-07-11",
            trips=[previous, following],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={},
        ),
        trips=(
            ProblemTrip("t1", "r", "A", "B", 480, 510, 5.0, ("BEV",)),
            ProblemTrip("t2", "r", "C", "D", 520, 550, 5.0, ("BEV",)),
        ),
        vehicles=(ProblemVehicle(vehicle_id="bev-1", vehicle_type="BEV", home_depot_id="A"),),
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="duty-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=previous), DutyLeg(trip=following)),
            ),
        ),
        served_trip_ids=("t1", "t2"),
        metadata={"duty_vehicle_map": {"duty-1": "bev-1"}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    connection = next(item for item in report.diagnostics if item["kind"] == "trip_connection")
    assert connection["vehicle_id"] == "bev-1"
    assert connection["previous_trip_id"] == "t1"
    assert connection["next_trip_id"] == "t2"
    assert connection["rejection_reason_code"] == "missing_deadhead"


def test_required_validation_metric_missing_is_not_treated_as_zero() -> None:
    checker = FeasibilityChecker()
    metrics = {
        "unassigned_trip_count": 0,
        "duplicate_trip_count": 0,
        "vehicle_time_overlap_count": 0,
        "infeasible_transition_count": 0,
        "ev_soc_violation_count": 0,
        "bess_soc_violation_count": 0,
        "contract_power_violation_count": 0,
        # charger_concurrency_violation_count is intentionally absent.
        "bess_terminal_soc_deviation_kwh": 0.0,
        "bess_terminal_soc_tolerance_kwh": 1.0e-6,
    }

    assert checker._metrics_are_clean(metrics) is False
    assert (
        "[VALIDATION] missing required metric: "
        "charger_concurrency_violation_count"
    ) in checker._metric_errors(metrics)


def test_duplicate_trip_metric_prevents_clean_validation() -> None:
    checker = FeasibilityChecker()
    metrics = {
        "unassigned_trip_count": 0,
        "duplicate_trip_count": 1,
        "vehicle_time_overlap_count": 0,
        "infeasible_transition_count": 0,
        "ev_soc_violation_count": 0,
        "bess_soc_violation_count": 0,
        "contract_power_violation_count": 0,
        "charger_concurrency_violation_count": 0,
        "bess_terminal_soc_deviation_kwh": 0.0,
        "bess_terminal_soc_tolerance_kwh": 1.0e-6,
    }

    assert checker._metrics_are_clean(metrics) is False
    assert any(
        "duplicate trip assignments remain" in error
        for error in checker._metric_errors(metrics)
    )
