from __future__ import annotations

from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.alns.operators_repair import soc_repair
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargerDefinition,
    OptimizationScenario,
    ProblemVehicle,
    ProblemVehicleType,
)


def test_soc_repair_does_not_add_charge_to_active_trip_slot() -> None:
    trip = Trip(
        trip_id="trip-1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
    )
    duty = VehicleDuty(
        duty_id="veh-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip, deadhead_from_prev_min=0),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="soc-active-slot",
            horizon_start="05:00",
            horizon_end="23:00",
            timestep_min=60,
        ),
        dispatch_context=DispatchContext(
            service_date="WEEKDAY",
            trips=[trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=20.0,
                    energy_consumption_kwh_per_km=2.0,
                )
            },
        ),
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=6.0,
                reserve_soc=8.0,
                battery_capacity_kwh=20.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=20.0,
            ),
        ),
        chargers=(ChargerDefinition("chg-1", "dep-1", 50.0),),
    )
    object.__setattr__(
        problem,
        "_trip_by_id_cache",
        {
            "trip-1": type(
                "ProblemTripLike",
                (),
                {"trip_id": "trip-1", "energy_kwh": 20.0},
            )()
        },
    )
    plan = AssignmentPlan(
        duties=(duty,),
        served_trip_ids=("trip-1",),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )

    repaired = soc_repair(problem, plan)

    assert repaired.charging_slots == ()
