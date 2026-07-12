from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.optimization.common.initial_soc_policy import (
    InitialSocPolicy,
    apply_initial_soc_policy_to_scenario,
    initial_soc_input_metadata,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from src.optimization.common.soc_helpers import slot_index_ceil
from scripts.run_research_phase3_minimal import _configure_controlled_model_validation_case


def test_uniform_initial_soc_policy_overrides_only_electric_vehicles() -> None:
    scenario = {
        "simulation_config": {},
        "vehicles": [
            {"id": "bev", "type": "BEV", "initialSoc": 0.2},
            {"id": "ice", "type": "ICE", "initialSoc": 0.1},
        ],
    }

    updated = apply_initial_soc_policy_to_scenario(
        scenario,
        policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
        uniform_percent=80,
    )

    assert updated["vehicles"][0]["initialSoc"] == pytest.approx(0.8)
    assert updated["vehicles"][1]["initialSoc"] == pytest.approx(0.1)
    assert updated["simulation_config"]["initial_soc_policy"] == "uniform_scenario_value"


def test_initial_soc_metadata_hashes_the_solver_inputs() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="soc", timestep_min=15),
        dispatch_context=object(),
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="depot",
                initial_soc=0.8,
                battery_capacity_kwh=300.0,
                reserve_soc=0.2,
            ),
        ),
    )

    metadata = initial_soc_input_metadata(
        problem,
        policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
    )

    assert metadata["initial_soc_policy"] == "uniform_scenario_value"
    assert metadata["initial_soc_by_vehicle"][0]["initial_soc_kwh"] == pytest.approx(240.0)
    assert metadata["initial_soc_by_vehicle"][0]["minimum_soc_kwh"] == pytest.approx(60.0)
    assert metadata["initial_soc_by_vehicle"][0]["terminal_soc_minimum_kwh"] == pytest.approx(60.0)
    assert len(metadata["initial_soc_input_hash"]) == 64


def test_controlled_case_clears_all_inherited_terminal_soc_requirements() -> None:
    scenario = {
        "simulation_config": {
            "final_soc_floor_percent": 80,
            "final_soc_target_percent": 90,
            "final_soc_target_tolerance_percent": 2,
        },
        "vehicles": [],
    }

    configured = _configure_controlled_model_validation_case(
        scenario,
        time_step_min=15,
        initial_soc_policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
        initial_soc_percent=80,
    )

    simulation_config = configured["simulation_config"]
    assert simulation_config["terminal_soc_policy"] == "minimum_soc"
    assert simulation_config["final_soc_floor_percent"] is None
    assert simulation_config["final_soc_target_percent"] is None
    assert simulation_config["final_soc_target_tolerance_percent"] is None


@dataclass
class _Scenario:
    timestep_min: int = 15
    horizon_start: str = "05:00"
    allow_overnight_depot_moves: str = "forbid"
    overnight_window_start: str = "23:00"
    overnight_window_end: str = "05:00"


@dataclass
class _Problem:
    scenario: _Scenario = field(default_factory=_Scenario)


def test_first_trip_gets_all_complete_predeparture_slots_at_15_minutes() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()

    slots = adapter._slot_indices_for_interval(problem, 5 * 60, 5 * 60 + 51)
    chargeable = [
        slot
        for slot in slots
        if not adapter._trip_active_in_slot(problem, 5 * 60 + 51, 6 * 60 + 20, slot)
    ]

    assert slots == (0, 1, 2, 3)
    assert chargeable == [0, 1, 2]
    assert adapter._is_replenishment_slot_allowed(problem, 72) is True


def test_overnight_slots_start_only_after_verified_home_arrival() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()

    slots = adapter._collect_overnight_home_depot_slots(
        problem,
        day_idx=0,
        operation_start_min=5 * 60,
        operation_end_min=23 * 60,
        earliest_home_arrival_min=23 * 60 + 22,
    )

    assert slots == tuple(range(74, 96))


def test_overnight_slots_are_empty_when_home_arrival_is_after_next_day_start() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()

    slots = adapter._collect_overnight_home_depot_slots(
        problem,
        day_idx=0,
        operation_start_min=5 * 60,
        operation_end_min=23 * 60,
        earliest_home_arrival_min=5 * 60 + 24 * 60,
    )

    assert slots == ()


def test_return_after_horizon_boundary_is_charged_to_next_service_day_slot() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()
    trip = ProblemTrip(
        trip_id="overnight",
        route_id="r",
        origin="a",
        destination="b",
        departure_min=4 * 60 + 20,
        arrival_min=4 * 60 + 50,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )

    home_arrival = adapter._trip_service_arrival_min(problem, trip) + 20

    assert home_arrival == 5 * 60 + 24 * 60 + 10
    assert slot_index_ceil(problem, home_arrival) == 97
    assert adapter._collect_overnight_home_depot_slots(
        problem,
        day_idx=0,
        operation_start_min=5 * 60,
        operation_end_min=23 * 60,
        earliest_home_arrival_min=home_arrival,
    ) == ()


def test_service_time_sort_keeps_evening_fragment_before_after_midnight_fragment() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()
    evening = ProblemTrip(
        trip_id="evening",
        route_id="r",
        origin="a",
        destination="b",
        departure_min=23 * 60,
        arrival_min=23 * 60 + 30,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )
    after_midnight = ProblemTrip(
        trip_id="after-midnight",
        route_id="r",
        origin="a",
        destination="b",
        departure_min=4 * 60 + 20,
        arrival_min=4 * 60 + 50,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )

    first = min(
        (after_midnight, evening),
        key=lambda trip: adapter._trip_service_sort_key(problem, trip),
    )

    assert first.trip_id == "evening"
