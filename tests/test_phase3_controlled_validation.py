from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.optimization.common.initial_soc_policy import (
    InitialSocPolicy,
    apply_initial_soc_policy_to_scenario,
    initial_soc_input_metadata,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.research_phase3_policy import (
    RESEARCH_PHASE3_FRAGMENT_POLICY,
    enforce_research_phase3_single_continuous_duty,
)
from src.gurobi_runtime import is_gurobi_available
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    StartupEnergyPrecheck,
    _transition_slot_ending_at_event,
)
from src.optimization.milp.solver_adapter import _vehicle_soc_transition_kwh
from src.optimization.common.soc_helpers import (
    slot_index_ceil,
    trip_active_in_slot,
    trip_slot_energy_fraction,
)
from scripts.run_research_phase3_minimal import (
    _audit_accounting_recalculation,
    _build_experiment_identity,
    _configure_controlled_model_validation_case,
    _finite_float_or_none,
    _mip_gap_percent,
    _resolve_expected_service_date,
)
from scripts.run_research_phase3_frontend_weather import (
    DEFAULT_FORMAL_MIP_GAP,
    DEFAULT_STAGE1_STRATEGY,
    _apply_bev_availability_sensitivity,
    _calendar_service_contract,
    _configure_research_discretization,
    _git_state,
    _resolve_initial_soc_policy,
    _validate_fleet_mutation_scope,
    run,
)


def test_formal_weather_runner_defaults_to_full_network_stage1() -> None:
    assert DEFAULT_STAGE1_STRATEGY == "full_network_milp"
    assert DEFAULT_FORMAL_MIP_GAP == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("service_date", "service_id", "expected"),
    [
        ("2025-08-05", "WEEKDAY", True),
        ("2025-08-10", "WEEKDAY", False),
        ("2025-08-10", "SUN_HOL", True),
        ("2025-08-09", "SAT", True),
    ],
)
def test_calendar_service_contract_detects_day_type_mismatch(
    service_date: str,
    service_id: str,
    expected: bool,
) -> None:
    assert _calendar_service_contract(service_date, service_id)["matches"] is expected


def test_formal_weather_runner_rejects_removed_exact_fixed_path() -> None:
    with pytest.raises(ValueError, match="Unsupported stage1_strategy"):
        run(SimpleNamespace(stage1_strategy="exact_fixed_path"))


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


def test_git_state_failure_is_recorded_without_aborting(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing_git(*args: object, **kwargs: object) -> str:
        raise FileNotFoundError("git is unavailable")

    monkeypatch.setattr("scripts.run_research_phase3_frontend_weather.subprocess.check_output", _missing_git)

    state = _git_state()

    assert state["git_sha"] is None
    assert state["git_dirty"] is None
    assert state["git_state_available"] is False
    assert "FileNotFoundError" in state["git_state_error"]


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
        metadata={"bev_terminal_soc_policy": "return_to_initial"},
    )

    metadata = initial_soc_input_metadata(
        problem,
        policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
    )

    assert metadata["initial_soc_policy"] == "uniform_scenario_value"
    assert metadata["initial_soc_by_vehicle"][0]["initial_soc_kwh"] == pytest.approx(240.0)
    assert metadata["initial_soc_by_vehicle"][0]["minimum_soc_kwh"] == pytest.approx(60.0)
    assert metadata["initial_soc_by_vehicle"][0]["terminal_soc_minimum_kwh"] == pytest.approx(60.0)
    assert metadata["initial_soc_by_vehicle"][0]["terminal_soc_policy"] == "return_to_initial"
    assert metadata["initial_soc_by_vehicle"][0]["terminal_soc_target_kwh"] == pytest.approx(240.0)
    assert len(metadata["initial_soc_input_hash"]) == 64


def test_controlled_case_replaces_inherited_target_with_return_to_initial() -> None:
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
    assert simulation_config["terminal_soc_policy"] == "return_to_initial"
    assert simulation_config["bev_terminal_soc_policy"] == "return_to_initial"
    assert (
        simulation_config["experiment_case_tag"]
        == "CONTROLLED_OPERATIONAL_BASELINE_CASE"
    )
    assert simulation_config["final_soc_floor_percent"] is None
    assert simulation_config["final_soc_target_percent"] is None
    assert simulation_config["final_soc_target_tolerance_percent"] is None


def test_controlled_case_can_disable_successor_pruning_explicitly() -> None:
    configured = _configure_controlled_model_validation_case(
        {"simulation_config": {}, "scenario_overlay": {"solver_config": {}}},
        time_step_min=15,
        initial_soc_policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
        initial_soc_percent=80,
        milp_max_successors_per_trip=0,
    )

    assert configured["simulation_config"]["milp_max_successors_per_trip"] is None
    assert (
        configured["scenario_overlay"]["solver_config"][
            "milp_max_successors_per_trip"
        ]
        is None
    )


def test_minimum_only_controlled_case_is_labeled_feasibility_only() -> None:
    configured = _configure_controlled_model_validation_case(
        {"simulation_config": {}},
        time_step_min=15,
        initial_soc_policy=InitialSocPolicy.UNIFORM_SCENARIO_VALUE,
        initial_soc_percent=80,
        bev_terminal_soc_policy="minimum_only",
    )

    simulation_config = configured["simulation_config"]
    assert simulation_config["bev_terminal_soc_policy"] == "minimum_only"
    assert simulation_config["experiment_case_tag"] == "CONTROLLED_MODEL_VALIDATION_CASE"


def test_accounting_recalculation_rejects_a_cost_mismatch() -> None:
    audit = _audit_accounting_recalculation(
        {"electricity_cost": 100.0, "fuel_cost": 50.0, "total_cost": 150.0},
        {"electricity_cost": 100.0, "fuel_cost": 49.0, "total_cost": 149.0},
    )

    assert audit["passed"] is False
    assert audit["max_abs_residual_jpy"] == pytest.approx(1.0)
    assert audit["residual_jpy_by_component"]["fuel_cost"] == pytest.approx(1.0)


def test_phase3_research_policy_restricts_the_ephemeral_model_to_one_duty() -> None:
    scenario = {
        "simulation_config": {
            "allow_same_day_depot_cycles": True,
            "max_depot_cycles_per_vehicle_per_day": 3,
            "max_start_fragments_per_vehicle": 100,
            "max_end_fragments_per_vehicle": 100,
        },
        "scenario_overlay": {
            "solver_config": {
                "max_start_fragments_per_vehicle": 100,
                "max_end_fragments_per_vehicle": 100,
            }
        },
    }

    audit = enforce_research_phase3_single_continuous_duty(scenario)

    assert audit["policy"] == RESEARCH_PHASE3_FRAGMENT_POLICY
    assert audit["persisted_to_scenario_store"] is False
    assert audit["requested_simulation_config"]["max_start_fragments_per_vehicle"] == 100
    assert audit["effective"] == {
        "allow_same_day_depot_cycles": False,
        "max_depot_cycles_per_vehicle_per_day": 1,
        "max_start_fragments_per_vehicle": 1,
        "max_end_fragments_per_vehicle": 1,
        "daily_fragment_limit": 1,
    }
    assert scenario["simulation_config"]["research_phase3_fragment_policy"] == RESEARCH_PHASE3_FRAGMENT_POLICY
    assert scenario["simulation_config"]["max_start_fragments_per_vehicle"] == 1
    assert scenario["scenario_overlay"]["solver_config"]["max_end_fragments_per_vehicle"] == 1


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


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_energy_envelope_blocks_unreplenished_bev_duty() -> None:
    """A Stage-2-impossible energy chain must be rejected before Stage 2."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.5,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    first_trip = ProblemTrip(
        trip_id="first",
        route_id="r",
        origin="remote-a",
        destination="remote-b",
        departure_min=6 * 60,
        arrival_min=6 * 60 + 30,
        distance_km=40.0,
        allowed_vehicle_types=("BEV",),
    )
    second_trip = ProblemTrip(
        trip_id="second",
        route_id="r",
        origin="remote-b",
        destination="remote-c",
        departure_min=7 * 60,
        arrival_min=7 * 60 + 30,
        distance_km=40.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="energy-envelope",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="09:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=(first_trip, second_trip),
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(
                charger_id="charger",
                depot_id="depot",
                power_kw=100.0,
            ),
        ),
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
    )
    model = gp.Model("stage1_energy_envelope")
    model.Params.OutputFlag = 0
    y = {
        ("bev", "first"): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0),
        ("bev", "second"): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0),
    }
    start_arc = {
        ("bev", "first"): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0),
        ("bev", "second"): model.addVar(vtype=gp.GRB.BINARY, lb=0.0, ub=0.0),
    }
    end_arc = {
        ("bev", "first"): model.addVar(vtype=gp.GRB.BINARY, lb=0.0, ub=0.0),
        ("bev", "second"): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0),
    }
    used_vehicle = {
        "bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0),
    }

    constraint_count = adapter._add_stage1_energy_envelope_constraints(
        model,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["first", "second"]},
        startup_energy_precheck_by_assignment={
            ("bev", "first"): StartupEnergyPrecheck(
                path_feasible=True,
                energy_feasible=True,
                initial_soc_kwh=50.0,
                minimum_soc_kwh=20.0,
                startup_deadhead_min=0,
                startup_deadhead_energy_kwh=0.0,
                required_departure_soc_kwh=60.0,
                complete_precharge_slot_count=0,
                maximum_precharge_energy_kwh=0.0,
                energy_margin_kwh=0.0,
            )
        },
        y=y,
        x={},
        start_arc=start_arc,
        end_arc=end_arc,
        used_vehicle=used_vehicle,
    )

    model.optimize()

    assert constraint_count == 1
    assert model.getConstrByName("stage1_energy_envelope__bev") is not None
    assert model.Status == gp.GRB.INFEASIBLE


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_energy_envelope_does_not_charge_every_fragment_a_startup_deadhead() -> None:
    """A necessary envelope must not overrestrict legacy multi-fragment callers."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.5,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    trips = tuple(
        ProblemTrip(
            trip_id=trip_id,
            route_id="r",
            origin="remote",
            destination="remote",
            departure_min=(index + 5) * 60,
            arrival_min=(index + 5) * 60 + 30,
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
        )
        for index, trip_id in enumerate(("first", "second"))
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="multi-fragment-envelope",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="09:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=trips,
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(charger_id="charger", depot_id="depot", power_kw=100.0),
        ),
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
    )
    model = gp.Model("stage1_multi_fragment_energy_envelope")
    model.Params.OutputFlag = 0
    y = {
        ("bev", trip.trip_id): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
        for trip in trips
    }
    start_arc = {
        ("bev", trip.trip_id): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
        for trip in trips
    }
    end_arc = {
        ("bev", trip.trip_id): model.addVar(vtype=gp.GRB.BINARY, lb=0.0, ub=0.0)
        for trip in trips
    }
    used_vehicle = {"bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)}
    startup = StartupEnergyPrecheck(
        path_feasible=True,
        energy_feasible=True,
        initial_soc_kwh=50.0,
        minimum_soc_kwh=20.0,
        startup_deadhead_min=30,
        startup_deadhead_energy_kwh=50.0,
        required_departure_soc_kwh=20.0,
        complete_precharge_slot_count=0,
        maximum_precharge_energy_kwh=0.0,
        energy_margin_kwh=0.0,
    )

    constraint_count = adapter._add_stage1_energy_envelope_constraints(
        model,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["first", "second"]},
        startup_energy_precheck_by_assignment={
            ("bev", "first"): startup,
            ("bev", "second"): startup,
        },
        y=y,
        x={},
        start_arc=start_arc,
        end_arc=end_arc,
        used_vehicle=used_vehicle,
    )
    model.optimize()

    assert constraint_count == 1
    assert model.Status == gp.GRB.OPTIMAL


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_time_indexed_soc_relaxation_blocks_early_soc_shortage() -> None:
    """Stage 1 must reject a low-SOC chain before its first idle slot."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.5,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    trips = (
        ProblemTrip(
            trip_id="first",
            route_id="r",
            origin="remote-a",
            destination="remote-b",
            departure_min=5 * 60,
            arrival_min=6 * 60,
            distance_km=20.0,
            allowed_vehicle_types=("BEV",),
        ),
        ProblemTrip(
            trip_id="second",
            route_id="r",
            origin="remote-b",
            destination="remote-c",
            departure_min=6 * 60,
            arrival_min=7 * 60,
            distance_km=20.0,
            allowed_vehicle_types=("BEV",),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="time-indexed-soc-relaxation",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="09:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=trips,
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(charger_id="charger", depot_id="depot", power_kw=100.0),
        ),
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
    )
    model = gp.Model("stage1_time_indexed_soc_relaxation")
    model.Params.OutputFlag = 0
    y = {
        ("bev", trip.trip_id): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
        for trip in trips
    }
    used_vehicle = {"bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)}

    (
        constraint_count,
        shared_charger_metadata,
    ) = adapter._add_stage1_time_indexed_soc_relaxation(
        model,
        gp=gp,
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["first", "second"]},
        startup_energy_precheck_by_assignment={},
        y=y,
        x={},
        start_arc={},
        end_arc={},
        used_vehicle=used_vehicle,
    )
    model.optimize()

    assert constraint_count > 0
    assert shared_charger_metadata["enabled"] is True
    assert (
        shared_charger_metadata["physical_charger_assignment_relaxed"]
        is True
    )
    assert (
        model.getConstrByName("stage1_soc_relax_cumulative__bev__slot_2")
        is not None
    )
    assert (
        model.getConstrByName("stage1_soc_relax_cumulative_terminal__bev")
        is not None
    )
    assert model.Status == gp.GRB.INFEASIBLE


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_time_indexed_soc_relaxation_blocks_off_depot_charge() -> None:
    """Stage 1 must not invent charging while a selected path is away."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.5,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    trips = (
        ProblemTrip(
            trip_id="first",
            route_id="r",
            origin="remote-a",
            destination="remote-b",
            departure_min=5 * 60,
            arrival_min=6 * 60,
            distance_km=20.0,
            allowed_vehicle_types=("BEV",),
        ),
        ProblemTrip(
            trip_id="second",
            route_id="r",
            origin="remote-b",
            destination="remote-c",
            departure_min=7 * 60,
            arrival_min=8 * 60,
            distance_km=20.0,
            allowed_vehicle_types=("BEV",),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="time-indexed-soc-relaxation-optimistic-charge",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="09:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=trips,
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(charger_id="charger", depot_id="depot", power_kw=100.0),
        ),
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
    )
    model = gp.Model("stage1_time_indexed_soc_relaxation_optimistic_charge")
    model.Params.OutputFlag = 0
    y = {
        ("bev", trip.trip_id): model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
        for trip in trips
    }
    used_vehicle = {"bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)}

    adapter._add_stage1_time_indexed_soc_relaxation(
        model,
        gp=gp,
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["first", "second"]},
        startup_energy_precheck_by_assignment={},
        y=y,
        x={},
        start_arc={},
        end_arc={},
        used_vehicle=used_vehicle,
    )
    model.optimize()

    assert model.Status == gp.GRB.INFEASIBLE


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_time_indexed_soc_relaxation_caps_charge_and_blocks_trip_overlap() -> None:
    """One vehicle cannot receive duplicate charge or charge while in service."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=1.0,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    trips = (
        ProblemTrip(
            trip_id="first",
            route_id="r",
            origin="remote-a",
            destination="depot",
            departure_min=5 * 60,
            arrival_min=6 * 60,
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
        ),
        ProblemTrip(
            trip_id="second",
            route_id="r",
            origin="depot",
            destination="remote-b",
            departure_min=7 * 60,
            arrival_min=8 * 60,
            distance_km=170.0,
            allowed_vehicle_types=("BEV",),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="time-indexed-soc-single-charge-cap",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="09:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=trips,
        vehicles=(vehicle,),
        chargers=(
            ChargerDefinition(
                charger_id="charger",
                depot_id="depot",
                power_kw=100.0,
            ),
        ),
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
    )
    model = gp.Model("stage1_time_indexed_soc_single_charge_cap")
    model.Params.OutputFlag = 0
    y = {
        ("bev", trip.trip_id): model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
        for trip in trips
    }
    x = {
        ("bev", "first", "second"): model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
    }
    start_arc = {
        ("bev", "first"): model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
    }
    end_arc = {
        ("bev", "second"): model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
    }
    used_vehicle = {
        "bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
    }
    startup = StartupEnergyPrecheck(
        path_feasible=True,
        energy_feasible=True,
        initial_soc_kwh=100.0,
        minimum_soc_kwh=20.0,
        startup_deadhead_min=0,
        startup_deadhead_energy_kwh=0.0,
        required_departure_soc_kwh=30.0,
        complete_precharge_slot_count=0,
        maximum_precharge_energy_kwh=0.0,
        energy_margin_kwh=70.0,
    )

    adapter._add_stage1_time_indexed_soc_relaxation(
        model,
        gp=gp,
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["first", "second"]},
        startup_energy_precheck_by_assignment={("bev", "first"): startup},
        y=y,
        x=x,
        start_arc=start_arc,
        end_arc=end_arc,
        used_vehicle=used_vehicle,
    )
    model.optimize()

    assert model.getVarByName("stage1_charge_available__bev__slot_1") is not None
    assert model.Status == gp.GRB.INFEASIBLE


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_time_indexed_soc_relaxation_shares_physical_charger_ports() -> None:
    """Two vehicles may not both consume one charger's full slot capacity."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicles = tuple(
        ProblemVehicle(
            vehicle_id=f"bev-{index}",
            vehicle_type="BEV",
            home_depot_id="depot",
            initial_soc=0.2,
            battery_capacity_kwh=100.0,
            reserve_soc=0.2,
            energy_consumption_kwh_per_km=1.0,
        )
        for index in range(2)
    )
    trips = tuple(
        ProblemTrip(
            trip_id=f"trip-{index}",
            route_id="r",
            origin="depot",
            destination=f"remote-{index}",
            departure_min=6 * 60,
            arrival_min=7 * 60,
            distance_km=90.0,
            allowed_vehicle_types=("BEV",),
        )
        for index in range(2)
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="stage1-shared-charger-relaxation",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="07:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=trips,
        vehicles=vehicles,
        depots=(
            ProblemDepot(
                depot_id="depot",
                name="Depot",
                charger_ids=("charger",),
                # Non-positive means an unspecified (not zero) grid contract.
                # Stage 1 must still apply the shared physical charger limit,
                # without creating an artificial zero-kW site cap.
                import_limit_kw=0.0,
            ),
        ),
        chargers=(
            ChargerDefinition(
                charger_id="charger",
                depot_id="depot",
                power_kw=100.0,
                simultaneous_ports=1,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0),
            EnergyPriceSlot(slot_index=1),
        ),
    )
    model = gp.Model("stage1_shared_charger_relaxation")
    model.Params.OutputFlag = 0
    y = {}
    start_arc = {}
    used_vehicle = {}
    startup_prechecks = {}
    assignment_trip_ids_by_vehicle = {}
    for vehicle, trip in zip(vehicles, trips):
        key = (vehicle.vehicle_id, trip.trip_id)
        y[key] = model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
        start_arc[key] = model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
        used_vehicle[vehicle.vehicle_id] = model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
        startup_prechecks[key] = StartupEnergyPrecheck(
            path_feasible=True,
            energy_feasible=True,
            initial_soc_kwh=20.0,
            minimum_soc_kwh=20.0,
            startup_deadhead_min=0,
            startup_deadhead_energy_kwh=0.0,
            required_departure_soc_kwh=110.0,
            complete_precharge_slot_count=1,
            maximum_precharge_energy_kwh=95.0,
            energy_margin_kwh=5.0,
        )
        assignment_trip_ids_by_vehicle[vehicle.vehicle_id] = [trip.trip_id]

    _, metadata = adapter._add_stage1_time_indexed_soc_relaxation(
        model,
        gp=gp,
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle=assignment_trip_ids_by_vehicle,
        startup_energy_precheck_by_assignment=startup_prechecks,
        y=y,
        x={},
        start_arc=start_arc,
        end_arc={},
        used_vehicle=used_vehicle,
    )
    model.optimize()

    assert metadata["physical_charger_assignment_relaxed"] is True
    assert metadata["site_supply_constraint_count"] == 0
    assert model.getConstrByName(
        "stage1_charger_relax_ports__charger__slot_0"
    ) is not None
    assert model.Status == gp.GRB.INFEASIBLE


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


def test_frontend_weather_runner_forces_formal_resolution_and_full_network() -> None:
    scenario = {
        "simulation_config": {
            "timestep_min": 60,
            "milp_max_successors_per_trip": 8,
        },
        "scenario_overlay": {
            "solver_config": {
                "time_step_min": 60,
                "milp_max_successors_per_trip": 8,
            }
        },
    }

    audit = _configure_research_discretization(scenario, timestep_min=15)

    assert scenario["simulation_config"]["timestep_min"] == 15
    assert scenario["simulation_config"]["milp_max_successors_per_trip"] == 0
    assert scenario["scenario_overlay"]["solver_config"]["timestep_min"] == 15
    assert scenario["scenario_overlay"]["solver_config"][
        "milp_max_successors_per_trip"
    ] == 0
    assert audit["successor_pruning_enabled"] is False


def test_frontend_weather_runner_accepts_all_shared_canonical_resolutions() -> None:
    for timestep_min in (5, 15, 30, 60):
        scenario: dict = {}
        audit = _configure_research_discretization(
            scenario,
            timestep_min=timestep_min,
        )

        assert audit["timestep_min"] == timestep_min
        assert scenario["simulation_config"]["timestep_min"] == timestep_min
        assert (
            scenario["scenario_overlay"]["solver_config"]["timestep_min"]
            == timestep_min
        )

    with pytest.raises(ValueError, match="5, 15, 30, or 60"):
        _configure_research_discretization({}, timestep_min=17)


def test_bev_availability_sensitivity_keeps_highest_soc_without_mutating_inventory_size() -> None:
    scenario = {
        "vehicles": [
            {"id": "bev-low", "type": "BEV", "enabled": True, "initialSoc": 0.3},
            {"id": "bev-high", "type": "BEV", "enabled": True, "initialSoc": 0.8},
            {"id": "bev-mid", "type": "BEV", "enabled": True, "initialSoc": 0.5},
            {"id": "ice", "type": "ICE", "enabled": True},
        ]
    }

    audit = _apply_bev_availability_sensitivity(scenario, 2)

    vehicles = {vehicle["id"]: vehicle for vehicle in scenario["vehicles"]}
    assert len(vehicles) == 4
    assert vehicles["bev-high"]["available"] is True
    assert vehicles["bev-mid"]["available"] is True
    assert vehicles["bev-low"]["available"] is False
    assert vehicles["ice"]["enabled"] is True
    assert audit["effective_available_bev_count"] == 2
    assert audit["selected_available_bev_ids"] == ["bev-high", "bev-mid"]
    assert audit["persisted_scenario_modified"] is False


def test_bev_availability_sensitivity_rejects_count_above_persisted_availability() -> None:
    scenario = {
        "vehicles": [
            {"id": "bev", "type": "BEV", "enabled": True, "initialSoc": 0.8},
            {"id": "bev-disabled", "type": "BEV", "enabled": False, "initialSoc": 0.9},
        ]
    }

    with pytest.raises(ValueError, match=r"persisted available BEV count \(1\)"):
        _apply_bev_availability_sensitivity(scenario, 2)


def test_bev_availability_mutation_is_exploratory_only() -> None:
    with pytest.raises(ValueError, match="exact prepared scenario fleet"):
        _validate_fleet_mutation_scope(
            available_bev_count=2,
            day_ahead_only_exploratory=False,
        )

    _validate_fleet_mutation_scope(
        available_bev_count=2,
        day_ahead_only_exploratory=True,
    )
    _validate_fleet_mutation_scope(
        available_bev_count=None,
        day_ahead_only_exploratory=False,
    )


def test_return_deadhead_is_posted_to_transition_ending_at_return_slot() -> None:
    assert _transition_slot_ending_at_event((0, 1, 2, 3), 3) == 2
    assert _transition_slot_ending_at_event((0, 1, 2, 3), 0) is None
    assert _transition_slot_ending_at_event((0, 1, 2, 3), 4) is None


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
@pytest.mark.parametrize(
    ("pv_available_kwh", "expected_grid_kwh", "expected_objective_jpy"),
    (
        (100.0, 0.0, 0.0),
        (10.0, (30.0 / 0.95) - 10.0, ((30.0 / 0.95) - 10.0) * 18.0),
    ),
)
def test_stage1_energy_cost_proxy_prices_zero_cost_pv_before_grid(
    pv_available_kwh: float,
    expected_grid_kwh: float,
    expected_objective_jpy: float,
) -> None:
    """The Stage-1 assignment proxy must react to configured PV availability."""
    import gurobipy as gp

    adapter = GurobiMILPAdapter()
    vehicle = ProblemVehicle(
        vehicle_id="bev",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.5,
        battery_capacity_kwh=100.0,
        reserve_soc=0.2,
        energy_consumption_kwh_per_km=1.0,
    )
    trip = ProblemTrip(
        trip_id="trip",
        route_id="r",
        origin="depot",
        destination="remote",
        departure_min=6 * 60,
        arrival_min=7 * 60,
        distance_km=60.0,
        allowed_vehicle_types=("BEV",),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="stage1-energy-cost-proxy",
            timestep_min=60,
            horizon_start="05:00",
            horizon_end="08:00",
        ),
        dispatch_context=_DispatchContext(),
        trips=(trip,),
        vehicles=(vehicle,),
        price_slots=tuple(
            EnergyPriceSlot(slot_index=index, grid_buy_yen_per_kwh=18.0)
            for index in range(3)
        ),
        depot_energy_assets={
            "depot": DepotEnergyAsset(
                depot_id="depot",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(pv_available_kwh, 0.0, 0.0),
            )
        },
    )
    model = gp.Model("stage1_energy_cost_proxy")
    model.Params.OutputFlag = 0
    y = {
        ("bev", "trip"): model.addVar(
            vtype=gp.GRB.BINARY,
            lb=1.0,
            ub=1.0,
        )
    }
    used_vehicle = {
        "bev": model.addVar(vtype=gp.GRB.BINARY, lb=1.0, ub=1.0)
    }

    proxy = adapter._add_stage1_energy_cost_proxy(
        model,
        gp=gp,
        grb=gp.GRB,
        problem=problem,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={"bev": ["trip"]},
        startup_energy_precheck_by_assignment={},
        y=y,
        x={},
        start_arc={},
        end_arc={},
        used_vehicle=used_vehicle,
        component_flags={"electricity_cost": True, "co2_cost": False},
    )
    model.setObjective(proxy.objective_expression, gp.GRB.MINIMIZE)
    model.optimize()
    result = adapter._stage1_energy_cost_proxy_result(proxy)

    assert model.Status == gp.GRB.OPTIMAL
    assert result["external_charge_input_kwh"] == pytest.approx(30.0 / 0.95)
    assert result["pv_to_bus_kwh"] == pytest.approx(
        min(pv_available_kwh, 30.0 / 0.95)
    )
    assert result["grid_to_bus_kwh"] == pytest.approx(expected_grid_kwh)
    assert result["objective_jpy"] == pytest.approx(expected_objective_jpy)


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


def test_experiment_hash_changes_with_successor_limit() -> None:
    problem_8, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
    )
    problem_16, _vehicle, _trip = _startup_problem(
        trip_distance_km=1.0,
        departure_min=6 * 60,
        initial_soc=0.8,
        reserve_soc=0.2,
    )
    problem_8.metadata["milp_max_successors_per_trip"] = 8
    problem_16.metadata["milp_max_successors_per_trip"] = 16

    identity_8 = _experiment_identity_for(
        problem_8, initial_soc_input_hash="same-soc"
    )
    identity_16 = _experiment_identity_for(
        problem_16, initial_soc_input_hash="same-soc"
    )

    assert identity_8["milp_max_successors_per_trip"] == 8
    assert identity_16["milp_max_successors_per_trip"] == 16
    assert identity_8["experiment_hash"] != identity_16["experiment_hash"]
