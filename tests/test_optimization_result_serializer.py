from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    ChargingSlot,
    DailyCostLedgerEntry,
    OptimizationEngineResult,
    OptimizationMode,
    RefuelSlot,
    VehicleCostLedgerEntry,
)
from src.optimization.common.result import ResultSerializer


def _sample_trip(trip_id: str, dep: str, arr: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="r1",
        origin="A",
        destination="B",
        departure_time=dep,
        arrival_time=arr,
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
    )


def test_result_serializer_includes_objective_components_and_limits() -> None:
    duty = VehicleDuty(
        duty_id="d1",
        vehicle_type="BEV",
        legs=(
            DutyLeg(trip=_sample_trip("t1", "08:00", "08:30"), deadhead_from_prev_min=0),
            DutyLeg(trip=_sample_trip("t2", "09:00", "09:30"), deadhead_from_prev_min=5),
        ),
    )
    plan = AssignmentPlan(
        duties=(duty,),
        refuel_slots=(
            # 08:00 start + 2*30min = 09:00
            RefuelSlot(
                vehicle_id="veh-ice-1",
                slot_index=2,
                refuel_liters=12.5,
                location_id="dep-1",
            ),
        ),
        served_trip_ids=("t1", "t2"),
        unserved_trip_ids=(),
        metadata={"horizon_start": "08:00", "timestep_min": 30},
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=123.0,
        plan=plan,
        feasible=True,
        cost_breakdown={
            "energy_cost": 10.0,
            "demand_cost": 4.0,
            "vehicle_cost": 6.0,
            "unserved_penalty": 0.0,
            "switch_cost": 2.0,
            "deviation_cost": 1.0,
            "degradation_cost": 3.0,
            "co2_cost": 5.0,
        },
        solver_metadata={
            "objective_mode": "balanced",
            "objective_weights": {
                "electricity_cost": 2.0,
                "demand_charge_cost": 3.0,
                "vehicle_fixed_cost": 1.0,
                "unserved_penalty": 1.0,
                "switch_cost": 4.0,
                "deviation_cost": 5.0,
                "degradation": 6.0,
                "emission_cost": 7.0,
            },
            "termination_reason": "optimal",
            "effective_limits": {"time_limit_sec": 300, "mip_gap": 0.01},
            "strict_coverage_precheck": {
                "checked": True,
                "infeasible": False,
                "relaxed_vehicle_lower_bound": 1,
                "available_vehicle_count": 1,
                "interval_only_lower_bound": 1,
                "diagnostic_message": "strict coverage lower bound is 1 vehicle, current fleet is 1.",
            },
        },
        warnings=("warning-1",),
        infeasibility_reasons=(),
    )

    payload = ResultSerializer.serialize_result(result)

    assert payload["objective_mode"] == "balanced"
    assert payload["objective_components_raw"]["energy_cost"] == 10.0
    assert payload["objective_components_weighted"]["energy_cost"] == 20.0
    assert payload["objective_components_weighted"]["co2_cost"] == 35.0
    assert payload["termination_reason"] == "optimal"
    assert payload["effective_limits"]["time_limit_sec"] == 300
    assert payload["warnings"] == ["warning-1"]
    assert payload["strict_coverage_precheck"]["relaxed_vehicle_lower_bound"] == 1
    assert "pv_generated_kwh" in payload["pv_summary"]
    assert "grid_import_kwh" in payload["pv_summary"]
    assert payload["utilization_summary"]["fleet_size"] == 1
    assert payload["utilization_summary"]["used_vehicle_count"] == 1
    assert payload["refueling_schedule"][0]["vehicle_id"] == "veh-ice-1"
    assert payload["refueling_schedule"][0]["time_hhmm"] == "09:00"
    assert payload["refueling_schedule"][0]["refuel_liters"] == 12.5


def test_result_serializer_includes_charging_depot_coordinates() -> None:
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(
                vehicle_id="bev-1",
                slot_index=1,
                charger_id="grid:dep-1",
                charge_kw=20.0,
                charging_depot_id="dep-1",
                charging_latitude=35.621,
                charging_longitude=139.699,
            ),
        ),
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="optimal",
        objective_value=1.0,
        plan=plan,
        feasible=True,
        cost_breakdown={},
        solver_metadata={},
    )

    payload = ResultSerializer.serialize_result(result)
    row = payload["charging_schedule"][0]
    assert row["charging_depot_id"] == "dep-1"
    assert row["charging_latitude"] == 35.621
    assert row["charging_longitude"] == 139.699


def test_result_serializer_includes_cost_ledgers_and_operating_splits() -> None:
    plan = AssignmentPlan(
        vehicle_cost_ledger=(
            VehicleCostLedgerEntry(
                vehicle_id="veh-1",
                day_index=0,
                provisional_drive_cost_jpy=1200.0,
                provisional_leftover_cost_jpy=100.0,
                realized_charge_cost_jpy=300.0,
                realized_refuel_cost_jpy=200.0,
            ),
        ),
        daily_cost_ledger=(
            DailyCostLedgerEntry(
                day_index=0,
                service_date="2026-03-27",
                ev_provisional_drive_cost_jpy=700.0,
                ev_realized_charge_cost_jpy=300.0,
                ev_leftover_provisional_cost_jpy=100.0,
                ice_provisional_drive_cost_jpy=500.0,
                ice_realized_refuel_cost_jpy=200.0,
                ice_leftover_provisional_cost_jpy=50.0,
                demand_charge_jpy=40.0,
                total_cost_jpy=1490.0,
            ),
        ),
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.ALNS,
        solver_status="feasible",
        objective_value=1490.0,
        plan=plan,
        feasible=True,
        cost_breakdown={
            "operating_cost_provisional_total": 1200.0,
            "operating_cost_realized_total": 500.0,
            "operating_cost_leftover_total": 150.0,
            "provisional_ev_drive_cost": 700.0,
            "realized_ev_charge_cost": 300.0,
            "leftover_ev_provisional_cost": 100.0,
            "provisional_ice_drive_cost": 500.0,
            "realized_ice_refuel_cost": 200.0,
            "leftover_ice_provisional_cost": 50.0,
        },
        solver_metadata={},
    )

    payload = ResultSerializer.serialize_result(result)
    assert payload["operating_cost_provisional_jpy"] == 1200.0
    assert payload["ev_realized_charge_cost_jpy"] == 300.0
    assert payload["ice_leftover_provisional_cost_jpy"] == 50.0
    assert payload["vehicle_cost_ledger"][0]["vehicle_id"] == "veh-1"
    assert payload["daily_cost_ledger"][0]["service_date"] == "2026-03-27"


def test_result_serializer_includes_depot_energy_flow_maps() -> None:
    plan = AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 10.0}},
        pv_to_bus_kwh_by_depot_slot={"dep-1": {0: 3.0}},
        bess_to_bus_kwh_by_depot_slot={"dep-1": {0: 2.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {1: 1.5}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {1: 4.0}},
        pv_curtail_kwh_by_depot_slot={"dep-1": {1: 0.5}},
        bess_soc_kwh_by_depot_slot={"dep-1": {0: 20.0, 1: 18.0}},
        contract_over_limit_kwh_by_depot_slot={"dep-1": {1: 0.75}},
    )
    result = OptimizationEngineResult(
        mode=OptimizationMode.MILP,
        solver_status="feasible",
        objective_value=100.0,
        plan=plan,
        feasible=True,
        cost_breakdown={},
        solver_metadata={},
    )

    payload = ResultSerializer.serialize_result(result)

    assert payload["grid_to_bus_kwh_by_depot_slot"]["dep-1"][0] == 10.0
    assert payload["pv_to_bus_kwh_by_depot_slot"]["dep-1"][0] == 3.0
    assert payload["bess_to_bus_kwh_by_depot_slot"]["dep-1"][0] == 2.0
    assert payload["pv_to_bess_kwh_by_depot_slot"]["dep-1"][1] == 1.5
    assert payload["grid_to_bess_kwh_by_depot_slot"]["dep-1"][1] == 4.0
    assert payload["pv_curtail_kwh_by_depot_slot"]["dep-1"][1] == 0.5
    assert payload["bess_soc_kwh_by_depot_slot"]["dep-1"][1] == 18.0
    assert payload["contract_over_limit_kwh_by_depot_slot"]["dep-1"][1] == 0.75
