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
    ChargerDefinition,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from src.optimization.milp.solver_adapter import _vehicle_soc_transition_kwh
from src.optimization.common.soc_helpers import (
    slot_index_ceil,
    trip_active_in_slot,
    trip_slot_energy_fraction,
)
from scripts.run_research_phase3_minimal import (
    _build_experiment_identity,
    _configure_controlled_model_validation_case,
    _finite_float_or_none,
    _mip_gap_percent,
    _resolve_expected_service_date,
)
from scripts.run_research_phase3_frontend_weather import _resolve_initial_soc_policy


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


@dataclass
class _DispatchContext:
    deadhead_min: int = 0
    turnaround_min: int = 0

    def trips_by_id(self) -> dict[str, object]:
        return {}

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def get_deadhead_min(self, _from_stop: str, _to_stop: str) -> int:
        return self.deadhead_min

    def get_turnaround_min(self, _stop_id: str) -> int:
        return self.turnaround_min

    def has_location_data(self, _stop_id: str) -> bool:
        return True


def _startup_problem(
    *,
    trip_distance_km: float,
    departure_min: int,
    initial_soc: float,
    reserve_soc: float,
    deadhead_min: int = 0,
    timestep_min: int = 15,
) -> tuple[CanonicalOptimizationProblem, ProblemVehicle, ProblemTrip]:
    trip = ProblemTrip(
        trip_id="startup",
        route_id="r",
        origin="depot" if deadhead_min == 0 else "remote",
        destination="remote",
        departure_min=departure_min,
        arrival_min=departure_min + 30,
        distance_km=trip_distance_km,
        allowed_vehicle_types=("BEV",),
    )
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=initial_soc,
        battery_capacity_kwh=100.0,
        reserve_soc=reserve_soc,
        energy_consumption_kwh_per_km=1.0,
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="startup",
            timestep_min=timestep_min,
            horizon_start="05:00",
        ),
        dispatch_context=_DispatchContext(deadhead_min=deadhead_min),
        trips=(trip,),
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(
                charger_id="c",
                depot_id="depot",
                power_kw=100.0,
            ),
        ),
    )
    return problem, vehicle, trip


def test_actual_inventory_initial_soc_policy_reaches_energy_precheck() -> None:
    scenario = {
        "simulation_config": {},
        "vehicles": [{"id": "bev", "type": "BEV", "initialSoc": 0.42}],
    }

    updated = apply_initial_soc_policy_to_scenario(
        scenario,
        policy=InitialSocPolicy.ACTUAL_VEHICLE_INVENTORY,
    )
    problem, vehicle, trip = _startup_problem(
        trip_distance_km=5.0,
        departure_min=6 * 60,
        initial_soc=float(updated["vehicles"][0]["initialSoc"]),
        reserve_soc=0.2,
    )

    assert updated["vehicles"][0]["initialSoc"] == pytest.approx(0.42)
    assert GurobiMILPAdapter()._startup_energy_precheck(
        problem, vehicle, trip
    ).initial_soc_kwh == pytest.approx(42.0)


def test_soc_transition_without_charging_matches_hand_calculation() -> None:
    assert _vehicle_soc_transition_kwh(
        100.0,
        charge_power_kw=0.0,
        timestep_h=0.25,
        charge_efficiency=0.95,
        drive_energy_kwh=20.0,
    ) == pytest.approx(80.0)


def test_soc_transition_with_15_minute_charge_matches_hand_calculation() -> None:
    assert _vehicle_soc_transition_kwh(
        50.0,
        charge_power_kw=100.0,
        timestep_h=0.25,
        charge_efficiency=0.95,
        drive_energy_kwh=20.0,
    ) == pytest.approx(53.75)


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


def test_startup_energy_precheck_counts_only_complete_precharge_slots() -> None:
    adapter = GurobiMILPAdapter()
    problem, vehicle, trip = _startup_problem(
        trip_distance_km=20.0,
        departure_min=5 * 60 + 51,
        initial_soc=0.5,
        reserve_soc=0.3,
    )

    precheck = adapter._startup_energy_precheck(problem, vehicle, trip)

    assert precheck.path_feasible is True
    assert precheck.complete_precharge_slot_count == 3
    # 71.25 kWh is theoretically delivered, but the 100 kWh battery has only
    # 50 kWh of headroom at the disclosed initial SOC.
    assert precheck.maximum_precharge_energy_kwh == pytest.approx(50.0)
    assert precheck.required_departure_soc_kwh == pytest.approx(50.0)
    assert precheck.energy_margin_kwh == pytest.approx(50.0)
    assert precheck.energy_feasible is True


def test_startup_energy_precheck_rejects_unavoidable_first_trip_shortage() -> None:
    adapter = GurobiMILPAdapter()
    problem, vehicle, trip = _startup_problem(
        trip_distance_km=50.0,
        departure_min=5 * 60 + 30,
        initial_soc=0.2,
        reserve_soc=0.2,
    )

    precheck = adapter._startup_energy_precheck(problem, vehicle, trip)

    assert precheck.complete_precharge_slot_count == 2
    assert precheck.maximum_precharge_energy_kwh == pytest.approx(47.5)
    assert precheck.energy_margin_kwh == pytest.approx(-2.5)
    assert precheck.energy_feasible is False


def test_startup_deadhead_time_and_energy_are_part_of_precheck() -> None:
    adapter = GurobiMILPAdapter()
    problem, vehicle, trip = _startup_problem(
        trip_distance_km=10.0,
        departure_min=6 * 60,
        initial_soc=0.5,
        reserve_soc=0.2,
        deadhead_min=30,
    )

    precheck = adapter._startup_energy_precheck(problem, vehicle, trip)

    assert precheck.startup_deadhead_min == 30
    assert precheck.startup_deadhead_energy_kwh == pytest.approx(9.0)
    assert precheck.complete_precharge_slot_count == 2
    assert precheck.required_departure_soc_kwh == pytest.approx(39.0)


def test_home_depot_windows_use_service_day_minutes_after_midnight() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()
    trip = ProblemTrip(
        trip_id="late",
        route_id="r",
        origin="depot",
        destination="depot",
        departure_min=4 * 60 + 20,
        arrival_min=4 * 60 + 50,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )

    slots = adapter._collect_home_depot_window_slots(
        problem,
        trip,
        home_depot_id="depot",
        pre_window_min=30,
        post_window_min=30,
    )

    assert 0 not in slots
    assert slots == (91, 92, 93, 95, 96, 97)


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


def test_after_midnight_trip_energy_fractions_sum_to_one_on_service_day() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()
    departure_min = 4 * 60 + 20
    arrival_min = 4 * 60 + 50
    fractions = [
        trip_slot_energy_fraction(problem, departure_min, arrival_min, slot)
        for slot in range(96)
    ]

    assert sum(fractions) == pytest.approx(1.0, abs=1.0e-12)
    assert fractions[93:96] == pytest.approx([1 / 3, 1 / 2, 1 / 6])
    assert sum(
        adapter._trip_slot_energy_fraction(
            problem, departure_min, arrival_min, slot
        )
        for slot in range(96)
    ) == pytest.approx(1.0, abs=1.0e-12)


def test_vehicle_cannot_charge_in_any_slot_overlapping_trip() -> None:
    adapter = GurobiMILPAdapter()
    problem = _Problem()
    departure_min = 10 * 60 + 5
    arrival_min = 10 * 60 + 40

    assert [
        trip_active_in_slot(problem, departure_min, arrival_min, slot)
        for slot in range(20, 24)
    ] == [True, True, True, False]
    assert [
        adapter._trip_active_in_slot(problem, departure_min, arrival_min, slot)
        for slot in range(20, 24)
    ] == [True, True, True, False]


def test_confirmed_home_residence_ends_before_outbound_deadhead() -> None:
    adapter = GurobiMILPAdapter()
    problem, vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=7 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
        deadhead_min=30,
    )
    previous_trip = ProblemTrip(
        trip_id="previous",
        route_id="r",
        origin="remote",
        destination="depot",
        departure_min=9 * 60,
        arrival_min=10 * 60,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )
    next_trip = ProblemTrip(
        trip_id="next",
        route_id="r",
        origin="remote",
        destination="remote2",
        departure_min=11 * 60,
        arrival_min=11 * 60 + 30,
        distance_km=1.0,
        allowed_vehicle_types=("BEV",),
    )

    assert adapter._home_depot_residence_interval(
        problem,
        vehicle,
        previous_trip,
        next_trip,
        deadhead_min=30,
    ) == (10 * 60, 10 * 60 + 30)
    assert adapter._connection_deadhead_interval(
        problem,
        vehicle,
        previous_trip,
        next_trip,
        deadhead_min=30,
    ) == (10 * 60 + 30, 11 * 60)


def test_startup_after_midnight_uses_service_day_time_axis() -> None:
    problem, vehicle, trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=4 * 60 + 20,
        initial_soc=0.8,
        reserve_soc=0.2,
    )

    precheck = GurobiMILPAdapter()._startup_energy_precheck(
        problem, vehicle, trip
    )

    assert precheck.path_feasible is True
    assert precheck.energy_feasible is True
    assert precheck.complete_precharge_slot_count == 93


def test_mip_gap_ratio_to_percent_preserves_missing_incumbent_null() -> None:
    assert _mip_gap_percent(0.1) == pytest.approx(10.0)
    assert _mip_gap_percent(0.669593) == pytest.approx(66.9593)
    assert _mip_gap_percent(None) is None


def test_solver_adapter_drops_nonfinite_gap_and_bound() -> None:
    class NonFiniteTelemetryModel:
        SolCount = 1
        MIPGap = float("inf")
        ObjBound = float("-inf")

    adapter = GurobiMILPAdapter()

    assert adapter._model_gap(NonFiniteTelemetryModel()) is None
    assert adapter._model_bound(NonFiniteTelemetryModel()) is None


def test_frontend_weather_runner_requires_explicit_soc_input_source() -> None:
    assert _resolve_initial_soc_policy(
        {"simulation_config": {"use_selected_depot_vehicle_inventory": True}}
    ) is InitialSocPolicy.ACTUAL_VEHICLE_INVENTORY
    assert _resolve_initial_soc_policy(
        {"simulation_config": {"initial_soc_policy": "uniform_scenario_value"}}
    ) is InitialSocPolicy.UNIFORM_SCENARIO_VALUE
    with pytest.raises(ValueError, match="initial_soc_policy"):
        _resolve_initial_soc_policy({"simulation_config": {}})


def test_nonfinite_objective_is_null_not_zero() -> None:
    assert _finite_float_or_none(float("inf")) is None
    assert _finite_float_or_none(float("nan")) is None
    assert _finite_float_or_none(None) is None
    assert _finite_float_or_none(0.0) == pytest.approx(0.0)


def test_expected_service_date_supports_both_comparison_cases() -> None:
    assert _resolve_expected_service_date(
        None, {"service_date": "2025-08-10"}
    ) == "2025-08-10"
    assert _resolve_expected_service_date(
        "2025-08-05", {"service_date": "2025-08-10"}
    ) == "2025-08-05"
    with pytest.raises(ValueError, match="expected service date is missing"):
        _resolve_expected_service_date(None, {})


def _experiment_identity_for(
    problem: CanonicalOptimizationProblem,
    *,
    initial_soc_input_hash: str,
) -> dict[str, object]:
    return _build_experiment_identity(
        problem,
        {"simulation_config": {}},
        initial_soc_policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
        initial_soc_input_hash=initial_soc_input_hash,
        time_limit_sec=1500,
        mip_gap=0.1,
        random_seed=42,
        git_sha="test-sha",
        warm_start_enabled=True,
    )


def test_experiment_hash_changes_with_initial_soc() -> None:
    problem_80, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
    )
    problem_60, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.6,
        reserve_soc=0.2,
    )

    assert _experiment_identity_for(
        problem_80, initial_soc_input_hash="soc-80"
    )["experiment_hash"] != _experiment_identity_for(
        problem_60, initial_soc_input_hash="soc-60"
    )["experiment_hash"]


def test_experiment_hash_changes_with_timestep() -> None:
    problem_15, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
        timestep_min=15,
    )
    problem_30, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
        timestep_min=30,
    )

    assert _experiment_identity_for(
        problem_15, initial_soc_input_hash="same-soc"
    )["experiment_hash"] != _experiment_identity_for(
        problem_30, initial_soc_input_hash="same-soc"
    )["experiment_hash"]
