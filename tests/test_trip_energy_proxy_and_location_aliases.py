from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.input_fingerprints import canonical_trip_input_hash
from src.optimization.common.soc_helpers import trip_energy_kwh
from src.optimization.common.trip_energy_proxy import (
    build_literature_proxy_trip_demands,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _trip(
    trip_id: str,
    departure_time: str,
    arrival_time: str,
    distance_km: float,
) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="route",
        origin="A",
        destination="B",
        departure_time=departure_time,
        arrival_time=arrival_time,
        distance_km=distance_km,
        allowed_vehicle_types=("BEV", "ICE"),
    )


def test_literature_proxy_preserves_aggregate_configured_demand() -> None:
    trips = (
        _trip("morning", "07:00", "07:40", 10.0),
        _trip("midday", "12:00", "12:20", 20.0),
    )

    proxy = build_literature_proxy_trip_demands(
        trips,
        bev_kwh_per_km=1.316,
        ice_l_per_km=1.0 / 4.52,
    )

    assert sum(proxy.energy_kwh_by_trip.values()) == pytest.approx(30.0 * 1.316)
    assert sum(proxy.fuel_l_by_trip.values()) == pytest.approx(30.0 / 4.52)
    assert proxy.energy_kwh_by_trip["morning"] != pytest.approx(10.0 * 1.316)
    assert proxy.provenance["model_role"] == (
        "deterministic_literature_proxy_not_measured_trip_data"
    )


@pytest.mark.parametrize("scale", [0.8, 0.9, 1.0, 1.1, 1.2])
def test_literature_proxy_scales_bev_and_ice_aggregate_demand_together(
    scale: float,
) -> None:
    trips = (
        _trip("morning", "07:00", "07:40", 10.0),
        _trip("midday", "12:00", "12:20", 20.0),
    )

    proxy = build_literature_proxy_trip_demands(
        trips,
        bev_kwh_per_km=1.316,
        ice_l_per_km=1.0 / 4.52,
        sensitivity_scale=scale,
    )

    assert sum(proxy.energy_kwh_by_trip.values()) == pytest.approx(
        30.0 * 1.316 * scale
    )
    assert sum(proxy.fuel_l_by_trip.values()) == pytest.approx(
        30.0 / 4.52 * scale
    )
    assert proxy.provenance["sensitivity_scale"] == pytest.approx(scale)


def test_literature_proxy_scales_bev_and_ice_demands_independently() -> None:
    trips = (
        _trip("morning", "07:00", "07:40", 10.0),
        _trip("midday", "12:00", "12:20", 20.0),
    )

    bev_high = build_literature_proxy_trip_demands(
        trips,
        bev_kwh_per_km=1.316,
        ice_l_per_km=1.0 / 4.52,
        bev_sensitivity_scale=1.2,
        ice_sensitivity_scale=1.0,
    )
    ice_high = build_literature_proxy_trip_demands(
        trips,
        bev_kwh_per_km=1.316,
        ice_l_per_km=1.0 / 4.52,
        bev_sensitivity_scale=1.0,
        ice_sensitivity_scale=1.2,
    )

    assert sum(bev_high.energy_kwh_by_trip.values()) == pytest.approx(
        30.0 * 1.316 * 1.2
    )
    assert sum(bev_high.fuel_l_by_trip.values()) == pytest.approx(30.0 / 4.52)
    assert sum(ice_high.energy_kwh_by_trip.values()) == pytest.approx(
        30.0 * 1.316
    )
    assert sum(ice_high.fuel_l_by_trip.values()) == pytest.approx(
        30.0 / 4.52 * 1.2
    )
    assert bev_high.provenance["effective_bev_trip_energy_scale"] == 1.2
    assert bev_high.provenance["effective_ice_trip_fuel_scale"] == 1.0
    assert ice_high.provenance["effective_bev_trip_energy_scale"] == 1.0
    assert ice_high.provenance["effective_ice_trip_fuel_scale"] == 1.2


def test_explicit_trip_vehicle_type_demand_overrides_vehicle_average_rate() -> None:
    problem_trip = ProblemTrip(
        trip_id="trip",
        route_id="route",
        origin="A",
        destination="B",
        departure_min=480,
        arrival_min=510,
        distance_km=10.0,
        allowed_vehicle_types=("BEV", "ICE"),
        energy_kwh=13.16,
        fuel_l=2.2,
        energy_kwh_by_vehicle_type={"BEV": 21.0},
        fuel_l_by_vehicle_type={"ICE": 3.0},
        energy_model_id="literature_proxy_v1",
    )
    bev = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        energy_consumption_kwh_per_km=1.316,
    )
    ice = ProblemVehicle(
        vehicle_id="ice",
        vehicle_type="ICE",
        home_depot_id="depot",
        fuel_consumption_l_per_km=1.0 / 4.52,
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario"),
        dispatch_context=DispatchContext(
            service_date="2025-08-05",
            trips=(),
            turnaround_rules=(),
            deadhead_rules=(),
            vehicle_profiles={},
        ),
        trips=(problem_trip,),
        vehicles=(bev, ice),
    )
    adapter = GurobiMILPAdapter()

    assert adapter._trip_energy_kwh(problem, bev, "trip") == pytest.approx(21.0)
    assert adapter._trip_fuel_l(problem, ice, "trip") == pytest.approx(3.0)
    assert trip_energy_kwh(problem, bev, problem_trip) == pytest.approx(21.0)


def test_odpt_platform_variants_are_registered_as_same_location_aliases() -> None:
    origin_id = "odpt.StopPlace:TokyuBus.Soshigaya.00240324."
    destination_id = "odpt.StopPlace:TokyuBus.Soshigaya.00240324.1"
    trips = (
        Trip(
            trip_id="a",
            route_id="route",
            origin="祖師ヶ谷大蔵駅",
            destination="祖師ヶ谷大蔵駅",
            departure_time="08:00",
            arrival_time="08:20",
            distance_km=5.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id=origin_id,
            destination_stop_id=origin_id,
        ),
        Trip(
            trip_id="b",
            route_id="route",
            origin="祖師ヶ谷大蔵駅",
            destination="祖師ヶ谷大蔵駅",
            departure_time="08:30",
            arrival_time="08:50",
            distance_km=5.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id=destination_id,
            destination_stop_id=destination_id,
        ),
    )

    aliases = ProblemBuilder()._build_dispatch_location_aliases(
        scenario={"stops": []},
        trips=trips,
    )

    assert destination_id in aliases[origin_id]
    assert origin_id in aliases[destination_id]


def test_trip_input_fingerprint_includes_type_specific_energy_model() -> None:
    base_trip = ProblemTrip(
        trip_id="trip",
        route_id="route",
        origin="A",
        destination="B",
        departure_min=480,
        arrival_min=510,
        distance_km=10.0,
        allowed_vehicle_types=("BEV", "ICE"),
        energy_kwh=13.16,
        fuel_l=2.2,
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=(),
        turnaround_rules=(),
        deadhead_rules=(),
        vehicle_profiles={},
    )
    base_problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario"),
        dispatch_context=context,
        trips=(base_trip,),
        vehicles=(),
    )
    proxy_problem = CanonicalOptimizationProblem(
        scenario=base_problem.scenario,
        dispatch_context=context,
        trips=(
            ProblemTrip(
                **{
                    **base_trip.__dict__,
                    "energy_kwh_by_vehicle_type": {"BEV": 14.0},
                    "energy_model_id": "literature_proxy_v1",
                }
            ),
        ),
        vehicles=(),
    )

    assert canonical_trip_input_hash(base_problem) != canonical_trip_input_hash(
        proxy_problem
    )


@pytest.mark.parametrize(
    ("soc_kwh", "expected_max_kw"),
    (
        (75.0, 90.0),
        (80.0, 60.0),
        (85.0, 60.0),
        (90.0, 30.0),
        (95.0, 30.0),
    ),
)
def test_piecewise_charge_taper_limits_power_by_start_soc(
    soc_kwh: float,
    expected_max_kw: float,
) -> None:
    gp = pytest.importorskip("gurobipy")
    model = gp.Model()
    model.Params.OutputFlag = 0
    on = model.addVar(vtype=gp.GRB.BINARY)
    charge = model.addVar(lb=0.0, ub=90.0)
    soc = model.addVar(lb=soc_kwh, ub=soc_kwh)
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario"),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "charging_power_model": "piecewise_soc_taper_v1",
            "charge_setup_minutes": 0,
            "charge_teardown_minutes": 0,
            "minimum_charge_session_minutes": 15,
        },
    )
    model.addConstr(on == 1)
    GurobiMILPAdapter()._add_piecewise_charge_power_constraints(
        model=model,
        gp=gp,
        GRB=gp.GRB,
        problem=problem,
        vehicle_id="bev",
        slot_indices=(0,),
        soc_var={("bev", 0): soc},
        charge_power_var={("bev", 0): charge},
        charge_on_var={("bev", 0): on},
        capacity_kwh=100.0,
        charge_max_kw=90.0,
        timestep_h=1.0,
        name_prefix="test_charge",
    )
    model.setObjective(charge, gp.GRB.MAXIMIZE)
    model.optimize()

    assert model.Status == gp.GRB.OPTIMAL
    assert charge.X == pytest.approx(expected_max_kw)
