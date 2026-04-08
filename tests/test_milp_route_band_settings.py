from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import AssignmentPlan, CanonicalOptimizationProblem, OptimizationScenario
from src.optimization.milp.model_builder import MILPModelBuilder
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


class _FakeVar:
    def __init__(self, value: float) -> None:
        self.X = value


def _minimal_dispatch_context() -> DispatchContext:
    return DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                route_family_code="FAM01",
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )


def test_builder_metadata_includes_fragment_and_band_settings() -> None:
    context = _minimal_dispatch_context()
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s1",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        max_start_fragments_per_vehicle=3,
        max_end_fragments_per_vehicle=4,
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        final_soc_target_percent=70.0,
        final_soc_target_tolerance_percent=5.0,
        initial_ice_fuel_percent=85.0,
        min_ice_fuel_percent=15.0,
        max_ice_fuel_percent=90.0,
        default_ice_tank_capacity_l=320.0,
        deadhead_speed_kmh=18.0,
    )

    assert problem.metadata.get("fixed_route_band_mode") is True
    assert problem.metadata.get("max_start_fragments_per_vehicle") == 3
    assert problem.metadata.get("max_end_fragments_per_vehicle") == 4
    assert problem.metadata.get("initial_soc_percent") == 80.0
    assert problem.metadata.get("final_soc_floor_percent") == 20.0
    assert problem.metadata.get("final_soc_target_percent") == 70.0
    assert problem.metadata.get("final_soc_target_tolerance_percent") == 5.0
    assert problem.metadata.get("initial_ice_fuel_percent") == 85.0
    assert problem.metadata.get("min_ice_fuel_percent") == 15.0
    assert problem.metadata.get("max_ice_fuel_percent") == 90.0
    assert problem.metadata.get("default_ice_tank_capacity_l") == 320.0
    assert problem.metadata.get("deadhead_speed_kmh") == 18.0
    assert problem.metadata.get("charging_window_mode") == "timetable_layover"
    assert problem.metadata.get("home_depot_charge_pre_window_min") == 60.0
    assert problem.metadata.get("home_depot_charge_post_window_min") == 60.0
    assert abs((problem.trips[0].required_soc_departure_percent or 0.0) - 24.0) < 1.0e-9


def test_solver_adapter_route_band_key_prefers_family_code() -> None:
    context = _minimal_dispatch_context()
    trip = context.trips[0]
    adapter = GurobiMILPAdapter()

    assert adapter._route_band_key(trip, "fallback_route") == "FAM01"
    trip_without_family = Trip(
        trip_id=trip.trip_id,
        route_id=trip.route_id,
        origin=trip.origin,
        destination=trip.destination,
        departure_time=trip.departure_time,
        arrival_time=trip.arrival_time,
        distance_km=trip.distance_km,
        allowed_vehicle_types=trip.allowed_vehicle_types,
        route_family_code="",
    )
    assert adapter._route_band_key(trip_without_family, "fallback_route") == "r01"


def test_solver_adapter_route_band_key_normalizes_family_variants_to_series() -> None:
    adapter = GurobiMILPAdapter()
    trip = Trip(
        trip_id="t_series",
        route_id="odpt-route-xyz",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
        route_family_code="黒07(入出庫便)",
    )

    assert adapter._route_band_key(trip, "fallback_route") == "黒07"


def test_solver_adapter_safe_positive_int_uses_default_for_invalid_values() -> None:
    adapter = GurobiMILPAdapter()

    assert adapter._safe_positive_int(5, default=1) == 5
    assert adapter._safe_positive_int(0, default=1) == 1
    assert adapter._safe_positive_int(None, default=2) == 2
    assert adapter._safe_positive_int("x", default=3) == 3


def test_solver_adapter_percent_to_ratio_supports_percent_and_ratio() -> None:
    adapter = GurobiMILPAdapter()

    assert adapter._percent_to_ratio(80.0) == 0.8
    assert adapter._percent_to_ratio(0.25) == 0.25
    assert adapter._percent_to_ratio(120.0) == 1.0
    assert adapter._percent_to_ratio(5.0) == 0.05
    assert adapter._percent_to_ratio(-1) is None


def test_solver_adapter_required_departure_soc_kwh_is_vehicle_specific() -> None:
    context = _minimal_dispatch_context()
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_required_soc",
        vehicle_counts={"BEV": 1},
        final_soc_floor_percent=15.0,
    )
    adapter = GurobiMILPAdapter()
    trip = problem.trips[0]

    required_200 = adapter._required_departure_soc_kwh(
        problem,
        problem.vehicles[0],
        trip,
        cap_kwh=200.0,
        final_soc_floor_kwh=30.0,
    )
    required_300 = adapter._required_departure_soc_kwh(
        problem,
        problem.vehicles[0],
        trip,
        cap_kwh=300.0,
        final_soc_floor_kwh=45.0,
    )

    # 200kWh 車では trip.energy(12) + floor(30) = 42kWh が必要。
    assert required_200 >= 42.0
    # 300kWh 車では trip.energy(12) + floor(45) = 57kWh が必要。
    assert required_300 >= 57.0


def test_solver_adapter_required_departure_soc_kwh_handles_small_builder_percent_values() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t_small",
                route_id="r_small",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=0.5,
                allowed_vehicle_types=("BEV",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_small_required_soc",
        vehicle_counts={"BEV": 1},
    )
    adapter = GurobiMILPAdapter()
    trip = problem.trips[0]
    vehicle = problem.vehicles[0]

    required = adapter._required_departure_soc_kwh(
        problem,
        vehicle,
        trip,
        cap_kwh=300.0,
        final_soc_floor_kwh=0.0,
    )

    assert abs(required - 0.6) < 1.0e-9


def test_solver_adapter_trip_energy_prefers_vehicle_rate() -> None:
    context = _minimal_dispatch_context()
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_energy_rate",
        vehicle_counts={"BEV": 1},
    )
    adapter = GurobiMILPAdapter()
    trip = problem.trips[0]
    vehicle = problem.vehicles[0]

    # distance=10km, profile energy rate=1.2kWh/km -> 12kWh
    assert abs(adapter._trip_energy_kwh(problem, vehicle, trip.trip_id) - 12.0) < 1.0e-9


def test_solver_adapter_collect_home_depot_window_slots_respects_trip_timetable() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t_home",
                route_id="r_home",
                origin="depot_A",
                destination="depot_A",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_charge_window",
        vehicle_counts={"BEV": 1},
        canonical_depot_id="depot_A",
        timestep_min=60,
    )
    adapter = GurobiMILPAdapter()
    slots = adapter._collect_home_depot_window_slots(
        problem,
        problem.trips[0],
        home_depot_id="depot_A",
        pre_window_min=60.0,
        post_window_min=60.0,
    )

    # horizon_start=08:00, departure=08:00, arrival=08:30, timestep=60min。
    # timetable-based window should include at least departure slot(0) and post-arrival slot(1).
    assert 0 in slots
    assert 1 in slots


def test_solver_adapter_builds_multiple_fragments_from_selected_arcs() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_time="08:40",
                arrival_time="09:00",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t3",
                route_id="r2",
                origin="D",
                destination="E",
                departure_time="12:00",
                arrival_time="12:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_fragments",
        vehicle_counts={"BEV": 1},
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
    )
    adapter = GurobiMILPAdapter()
    vehicle_id = problem.vehicles[0].vehicle_id
    y = {
        (vehicle_id, "t1"): _FakeVar(1.0),
        (vehicle_id, "t2"): _FakeVar(1.0),
        (vehicle_id, "t3"): _FakeVar(1.0),
    }
    x = {
        (vehicle_id, "t1", "t2"): _FakeVar(1.0),
    }
    start_arc = {
        (vehicle_id, "t1"): _FakeVar(1.0),
        (vehicle_id, "t2"): _FakeVar(0.0),
        (vehicle_id, "t3"): _FakeVar(1.0),
    }

    duties, served_trip_ids, duty_vehicle_map = adapter._build_vehicle_duties_from_solution(
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        dispatch_trip_by_id=problem.dispatch_context.trips_by_id(),
        y=y,
        x=x,
        start_arc=start_arc,
    )

    assert [tuple(duty.trip_ids) for duty in duties] == [("t1", "t2"), ("t3",)]
    assert served_trip_ids == ["t1", "t2", "t3"]
    assert duty_vehicle_map == {
        f"milp_{vehicle_id}": vehicle_id,
        f"milp_{vehicle_id}__frag2": vehicle_id,
    }


def test_milp_model_builder_limits_successor_arcs_per_trip() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_time="09:00",
                arrival_time="09:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                origin="B",
                destination="D",
                departure_time="10:00",
                arrival_time="10:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t4",
                route_id="r1",
                origin="B",
                destination="E",
                departure_time="11:00",
                arrival_time="11:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    base_problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_arc_limit",
        vehicle_counts={"BEV": 1},
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id=base_problem.scenario.scenario_id,
            horizon_start=base_problem.scenario.horizon_start,
            horizon_end=base_problem.scenario.horizon_end,
            timestep_min=base_problem.scenario.timestep_min,
            objective_mode=base_problem.scenario.objective_mode,
        ),
        dispatch_context=base_problem.dispatch_context,
        trips=base_problem.trips,
        vehicles=base_problem.vehicles,
        routes=base_problem.routes,
        depots=base_problem.depots,
        vehicle_types=base_problem.vehicle_types,
        chargers=base_problem.chargers,
        price_slots=base_problem.price_slots,
        pv_slots=base_problem.pv_slots,
        depot_energy_assets=base_problem.depot_energy_assets,
        feasible_connections={"t1": ("t2", "t3", "t4")},
        objective_weights=base_problem.objective_weights,
        baseline_plan=base_problem.baseline_plan,
        metadata={"milp_max_successors_per_trip": 2},
    )

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, problem.trip_by_id())

    assert [(vehicle_id, from_trip_id, to_trip_id) for vehicle_id, from_trip_id, to_trip_id in pairs] == [
        (problem.vehicles[0].vehicle_id, "t1", "t2"),
        (problem.vehicles[0].vehicle_id, "t1", "t3"),
    ]


def test_solver_adapter_overlap_cliques_use_exact_trip_intervals() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:20",
                distance_km=3.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_time="08:25",
                arrival_time="08:45",
                distance_km=3.0,
                allowed_vehicle_types=("BEV",),
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                origin="X",
                destination="Y",
                departure_time="08:10",
                arrival_time="08:30",
                distance_km=3.0,
                allowed_vehicle_types=("BEV",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_exact_overlap_cliques",
        vehicle_counts={"BEV": 1},
        timestep_min=60,
    )
    adapter = GurobiMILPAdapter()

    cliques = {frozenset(clique) for clique in adapter._build_trip_overlap_cliques(problem)}

    assert frozenset({"t1", "t3"}) in cliques
    assert frozenset({"t2", "t3"}) in cliques
    assert frozenset({"t1", "t2"}) not in cliques


def test_solver_adapter_trip_fuel_prefers_vehicle_rate_over_trip_constant() -> None:
    context = _minimal_dispatch_context()
    context.trips = [
        Trip(
            trip_id="t_ice",
            route_id="r_ice",
            origin="A",
            destination="B",
            departure_time="08:00",
            arrival_time="08:30",
            distance_km=10.0,
            allowed_vehicle_types=("ICE",),
        )
    ]
    context.vehicle_profiles = {
        "ICE": VehicleProfile(
            vehicle_type="ICE",
            fuel_tank_capacity_l=200.0,
            fuel_consumption_l_per_km=0.5,
        )
    }
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_fuel_rate",
        vehicle_counts={"ICE": 1},
    )
    adapter = GurobiMILPAdapter()
    trip = problem.trips[0]
    vehicle = problem.vehicles[0]

    # vehicle rate-based fuel = 10km * 0.5 = 5L
    assert abs(adapter._trip_fuel_l(problem, vehicle, trip.trip_id) - 5.0) < 1.0e-9


def test_solver_adapter_safe_nonnegative_float_uses_default_for_invalid_values() -> None:
    adapter = GurobiMILPAdapter()

    assert adapter._safe_nonnegative_float(12.5, default=1.0) == 12.5
    assert adapter._safe_nonnegative_float(-1.0, default=2.0) == 2.0
    assert adapter._safe_nonnegative_float(None, default=3.0) == 3.0


def test_builder_percent_normalization_and_required_soc_derivation() -> None:
    builder = ProblemBuilder()
    assert builder._normalize_percent_like_to_ratio(80.0) == 0.8
    assert builder._normalize_percent_like_to_ratio(0.25) == 0.25
    assert builder._normalize_percent_like_to_ratio(None) is None

    required = builder._derive_required_soc_departure_percent(
        trip_energy_kwh=18.0,
        bev_capacity_kwh=300.0,
        final_soc_floor_ratio=0.2,
    )
    assert required == 26.0


def test_solver_adapter_trip_and_deadhead_fuel_helpers() -> None:
    context = _minimal_dispatch_context()
    context.vehicle_profiles["ICE"] = VehicleProfile(
        vehicle_type="ICE",
        fuel_tank_capacity_l=300.0,
        fuel_consumption_l_per_km=0.4,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s2",
        vehicle_counts={"ICE": 1},
    )
    adapter = GurobiMILPAdapter()
    vehicle = problem.vehicles[0]
    trip = problem.trips[0]

    trip_fuel = adapter._trip_fuel_l(problem, vehicle, trip.trip_id)
    assert trip_fuel >= 0.0

    deadhead_fuel = adapter._deadhead_fuel_l(problem, vehicle, trip.trip_id, trip.trip_id)
    assert deadhead_fuel >= 0.0


def test_solver_adapter_deadhead_distance_uses_metadata_speed() -> None:
    context = _minimal_dispatch_context()
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s3",
        vehicle_counts={"BEV": 1},
        deadhead_speed_kmh=18.0,
    )
    adapter = GurobiMILPAdapter()
    assert abs(adapter._deadhead_distance_km(problem, 60) - 18.0) < 1.0e-9


def test_solver_adapter_vehicle_can_start_trip_when_deadhead_exists_before_horizon() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t_start",
                route_id="r_start",
                origin="Route Stop",
                destination="Terminal",
                departure_time="05:00",
                arrival_time="05:30",
                distance_km=5.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="stop-route",
                destination_stop_id="stop-terminal",
            )
        ],
        turnaround_rules={},
        deadhead_rules={
            ("stop-depot", "stop-route"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-route",
                travel_time_min=360,
            )
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        location_aliases={"dep1": ("stop-depot",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_startup_deadhead",
        vehicle_counts={"BEV": 1},
        canonical_depot_id="dep1",
    )
    adapter = GurobiMILPAdapter()

    assert adapter._vehicle_can_start_trip(problem, problem.vehicles[0], problem.trips[0]) is True


def test_dispatch_graph_blocks_cross_band_connections_when_fixed_route_band_mode_is_on() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
                route_family_code="黒07(入出庫便)",
            ),
            Trip(
                trip_id="t2",
                route_id="r2",
                origin="B",
                destination="C",
                departure_time="08:45",
                arrival_time="09:15",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
                route_family_code="渋24",
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        fixed_route_band_mode=True,
    )

    graph = ConnectionGraphBuilder().build(context, "BEV")

    assert graph["t1"] == []


def test_feasibility_checker_flags_multi_band_duty_when_fixed_route_band_mode_is_on() -> None:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
                route_family_code="黒07(入出庫便)",
            ),
            Trip(
                trip_id="t2",
                route_id="r2",
                origin="C",
                destination="D",
                departure_time="10:00",
                arrival_time="10:30",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
                route_family_code="渋24",
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
        fixed_route_band_mode=True,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_route_band_feasibility",
        vehicle_counts={"BEV": 1},
        fixed_route_band_mode=True,
        canonical_depot_id="dep1",
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(
                    DutyLeg(trip=context.trips[0], deadhead_from_prev_min=0),
                    DutyLeg(trip=context.trips[1], deadhead_from_prev_min=0),
                ),
            ),
        ),
        charging_slots=(),
        refuel_slots=(),
        served_trip_ids=("t1", "t2"),
        unserved_trip_ids=(),
        metadata={"duty_vehicle_map": {"veh-1": "veh-1"}},
    )

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert any("[ROUTE_BAND]" in message for message in report.errors)
