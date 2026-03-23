from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    OptimizationEngineResult,
    OptimizationMode,
    RefuelSlot,
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
        },
    )

    payload = ResultSerializer.serialize_result(result)

    assert payload["objective_mode"] == "balanced"
    assert payload["objective_components_raw"]["energy_cost"] == 10.0
    assert payload["objective_components_weighted"]["energy_cost"] == 20.0
    assert payload["objective_components_weighted"]["co2_cost"] == 35.0
    assert payload["termination_reason"] == "optimal"
    assert payload["effective_limits"]["time_limit_sec"] == 300
    assert "pv_generated_kwh" in payload["pv_summary"]
    assert "grid_import_kwh" in payload["pv_summary"]
    assert payload["utilization_summary"]["fleet_size"] == 1
    assert payload["utilization_summary"]["used_vehicle_count"] == 1
    assert payload["refueling_schedule"][0]["vehicle_id"] == "veh-ice-1"
    assert payload["refueling_schedule"][0]["time_hhmm"] == "09:00"
    assert payload["refueling_schedule"][0]["refuel_liters"] == 12.5
