from src.dispatch.models import DeadheadRule, DispatchContext, Trip, TurnaroundRule, VehicleProfile
from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder
from src.optimization.milp.model_builder import MILPModelBuilder
from src.optimization.common.result import ResultSerializer
from src.optimization.rolling.state_locking import lock_started_trips


def _trip(
    trip_id: str,
    origin: str,
    destination: str,
    departure: str,
    arrival: str,
    allowed: tuple[str, ...] = ("BEV",),
) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="R1",
        origin=origin,
        destination=destination,
        departure_time=departure,
        arrival_time=arrival,
        distance_km=10.0,
        allowed_vehicle_types=allowed,
    )


def _context() -> DispatchContext:
    trips = [
        _trip("T1", "A", "B", "07:00", "07:20", ("BEV",)),
        _trip("T2", "B", "C", "07:35", "08:00", ("BEV",)),
        _trip("T3", "C", "D", "08:20", "08:45", ("BEV",)),
    ]
    return DispatchContext(
        service_date="2026-03-08",
        trips=trips,
        turnaround_rules={"B": TurnaroundRule(stop_id="B", min_turnaround_min=5)},
        deadhead_rules={("D", "A"): DeadheadRule(from_stop="D", to_stop="A", travel_time_min=10)},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        default_turnaround_min=5,
    )


def test_problem_builder_uses_dispatch_baseline_and_feasible_connections():
    problem = ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="sc-opt-001",
        vehicle_counts={"BEV": 2},
    )

    assert problem.baseline_plan is not None
    assert set(problem.baseline_plan.served_trip_ids) == {"T1", "T2", "T3"}
    assert problem.feasible_connections["T1"] == ("T2",)
    assert problem.feasible_connections["T2"] == ("T3",)
    assert problem.routes[0].route_id == "R1"
    assert problem.vehicle_types[0].vehicle_type_id == "BEV"
    assert len(problem.price_slots) > 0
    assert len(problem.pv_slots) == len(problem.price_slots)


def test_optimization_engine_supports_all_modes():
    problem = ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="sc-opt-002",
        vehicle_counts={"BEV": 2},
    )
    engine = OptimizationEngine()

    for mode in (OptimizationMode.MILP, OptimizationMode.ALNS, OptimizationMode.HYBRID):
        result = engine.solve(problem, OptimizationConfig(mode=mode, alns_iterations=20))
        payload = ResultSerializer.serialize_result(result)

        assert result.mode == mode
        assert payload["solver_mode"] == mode.value
        assert payload["feasible"] is True
        assert set(payload["served_trip_ids"]) == {"T1", "T2", "T3"}
        assert payload["unserved_trip_ids"] == []
        assert "vehicle_paths" in payload


def test_lock_started_trips_keeps_only_started_legs():
    problem = ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="sc-opt-003",
        vehicle_counts={"BEV": 1},
    )

    locked = lock_started_trips(problem.baseline_plan, current_min=7 * 60 + 30)

    assert set(locked.served_trip_ids) == {"T1"}
    assert locked.metadata["locked_trip_ids"] == ("T1",)


def test_hybrid_result_exposes_operator_stats_and_history():
    problem = ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="sc-opt-004",
        vehicle_counts={"BEV": 1},
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.HYBRID, alns_iterations=10),
    )
    payload = ResultSerializer.serialize_result(result)

    assert "operator_stats" in payload
    assert "incumbent_history" in payload
    assert payload["incumbent_history"]


def test_problem_builder_builds_from_scenario_profiles():
    scenario = {
        "meta": {"id": "scenario-x", "updatedAt": "2026-03-08T00:00:00+00:00"},
        "depots": [{"id": "D1", "name": "Depot 1"}],
        "vehicles": [
            {
                "id": "V1",
                "depotId": "D1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.4,
                "chargePowerKw": 150.0,
            }
        ],
        "routes": [{"id": "R1"}],
        "depot_route_permissions": [{"depotId": "D1", "routeId": "R1", "allowed": True}],
        "vehicle_route_permissions": [{"vehicleId": "V1", "routeId": "R1", "allowed": True}],
        "timetable_rows": [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "A",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
            }
        ],
        "chargers": [{"id": "C1", "siteId": "D1", "powerKw": 150.0}],
        "pv_profiles": [{"site_id": "D1", "values": [0.0, 10.0]}],
        "energy_price_profiles": [{"site_id": "D1", "values": [20.0, 25.0]}],
    }

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="D1",
        service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.HYBRID),
    )

    assert len(problem.trips) == 1
    assert len(problem.chargers) == 1
    assert len(problem.price_slots) == 2
    assert len(problem.pv_slots) == 2


def test_milp_model_builder_generates_assignment_and_constraint_specs():
    problem = ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="sc-opt-005",
        vehicle_counts={"BEV": 1},
    )
    model = MILPModelBuilder().build(problem)

    assert model.variable_counts["assignment"] >= 3
    assert model.constraint_counts["cover_each_trip"] == 3
    assert any(variable.name.startswith("y[") for variable in model.variables)
    assert any(constraint.name.startswith("cover_trip[") for constraint in model.constraints)
