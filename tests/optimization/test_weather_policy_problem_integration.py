import json
from pathlib import Path
from types import SimpleNamespace

from bff.routers.optimization import (
    _canonical_vehicle_timeline_rows,
    _persist_rich_run_outputs,
    _prepare_weather_policy_for_scenario,
)
from bff.services.optimization_run.vehicle_timeline import vehicle_ids_with_timeline_activity
from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    PVSlot,
    ProblemDepot,
    ProblemTrip,
    ProblemVehicle,
    RefuelSlot,
)
from src.preprocess.weather.daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    WeatherProxyForecast,
)
from src.preprocess.weather.operation_policy import (
    apply_weather_policy_to_problem,
    build_operation_profile,
)


def _forecast() -> WeatherProxyForecast:
    return WeatherProxyForecast(
        version="historical_analog_v1",
        forecast_type="historical_analog_v1",
        service_date="2025-08-21",
        station_id="44132",
        station_name="東京",
        analog_date="2024-08-22",
        analog_selection_score=0.183,
        analog_selection_method="calendar_plus_previous_day_weather_v1",
        weather_label="曇り時々晴れ",
        tmax_c=33.2,
        tmin_c=25.1,
        mean_temp_c=28.4,
        sunshine_hours=5.8,
        precipitation_mm=0.0,
        sun_score=0.725,
        rain_risk=0.0,
        heat_load_score=0.82,
        midday_recovery_expectation="high",
        operation_mode="aggressive",
        no_future_leakage=True,
        metadata={"candidate_count": 3, "features_used": ["month_distance"]},
    )


def _typical_forecast() -> WeatherProxyForecast:
    factors = [0.0] * 24
    factors[5] = 0.50
    factors[6] = 0.60
    return WeatherProxyForecast(
        version=FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
        forecast_type=FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
        service_date="2025-09-01",
        station_id="44132",
        station_name="東京",
        analog_date="2025-08-31",
        analog_selection_score=0.0,
        analog_selection_method="solcast_typical_capacity_factor_curve_v1",
        weather_label="Solcast代表晴れPV",
        tmax_c=None,
        tmin_c=None,
        mean_temp_c=None,
        sunshine_hours=6.0,
        precipitation_mm=None,
        sun_score=0.75,
        rain_risk=0.10,
        heat_load_score=0.0,
        midday_recovery_expectation="high",
        operation_mode="aggressive",
        no_future_leakage=True,
        metadata={
            "typical_weather_class": "sunny",
            "requested_weather_class": "sunny",
            "weather_class_selection_reason": "manual",
            "forecast_issue_date": "2025-08-31",
            "slot_minutes": 60,
            "capacity_factor_by_slot": factors,
            "source_dates": ["2025-08-01", "2025-08-02"],
            "source_profile_count": 2,
            "representative_curve_version": "solcast_typical_pv_representative_curve_v1",
            "classification": {
                "method": "fixed_threshold_daily_cf_hours_fallback",
                "thresholds": {"rainy_daily_cf_hours_max": 4.0, "sunny_daily_cf_hours_min": 5.5},
            },
        },
    )


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario-weather"),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="BEV_001",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
            ProblemVehicle(
                vehicle_id="ICE_001",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
                initial_soc=None,
            ),
        ),
        metadata={"service_date": "2025-08-21"},
    )


def _pv_problem() -> CanonicalOptimizationProblem:
    price_slots = tuple(EnergyPriceSlot(slot_index=idx, grid_buy_yen_per_kwh=20.0) for idx in range(24))
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-weather-pv",
            horizon_start="05:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        price_slots=price_slots,
        pv_slots=tuple(PVSlot(slot_index=idx, pv_available_kw=0.0) for idx in range(24)),
        depot_energy_assets={
            "DEPOT": DepotEnergyAsset(
                depot_id="DEPOT",
                pv_enabled=True,
                pv_capacity_kw=100.0,
                depot_area_m2=1428.5714,
                pv_generation_kwh_by_slot=tuple(0.0 for _ in range(24)),
                capacity_factor_by_slot=tuple(0.0 for _ in range(24)),
            )
        },
        metadata={"service_date": "2025-09-01", "horizon_start_min": 5 * 60},
    )


def test_apply_weather_policy_to_problem_is_non_destructive_and_reproducible():
    forecast = _forecast()
    profile = build_operation_profile(forecast)
    problem = _problem()

    updated_a = apply_weather_policy_to_problem(
        problem,
        forecast,
        profile,
        random_seed=42,
    )
    updated_b = apply_weather_policy_to_problem(
        problem,
        forecast,
        profile,
        random_seed=42,
    )

    assert problem.metadata == {"service_date": "2025-08-21"}
    assert problem.vehicles[0].initial_soc is None
    assert updated_a.metadata["weather_proxy"]["analog_date"] == "2024-08-22"
    assert updated_a.metadata["final_soc_floor_percent"] == 20.0
    assert updated_a.metadata["final_soc_target_percent"] == 35.0
    assert updated_a.metadata["final_soc_target_tolerance_percent"] == 0.0
    assert updated_a.vehicles[0].initial_soc == updated_b.vehicles[0].initial_soc
    assert 0.55 <= updated_a.vehicles[0].initial_soc <= 0.95
    assert updated_a.vehicles[1].initial_soc is None


def test_typical_solcast_curve_replaces_problem_pv_by_clock_not_position():
    forecast = _typical_forecast()
    profile = build_operation_profile(forecast)
    problem = _pv_problem()

    updated = apply_weather_policy_to_problem(problem, forecast, profile, random_seed=42)

    assert problem.pv_slots[0].pv_available_kw == 0.0
    assert updated.metadata["weather_pv_forecast_applied"] is True
    assert updated.metadata["weather_pv_representative_curve"]["typical_weather_class"] == "sunny"
    assert updated.depot_energy_assets["DEPOT"].capacity_factor_by_slot[0] == 0.50
    assert updated.depot_energy_assets["DEPOT"].pv_generation_kwh_by_slot[0] == 50.0
    assert updated.pv_slots[0].pv_available_kw == 50.0
    assert updated.pv_slots[1].pv_available_kw == 60.0


def test_conservative_weather_policy_relaxes_terminal_target_not_safety_floor():
    forecast = _forecast()
    forecast = WeatherProxyForecast(
        **{
            **forecast.__dict__,
            "operation_mode": "conservative",
            "sun_score": 0.05,
            "rain_risk": 0.85,
            "weather_label": "雨",
        }
    )
    profile = build_operation_profile(forecast)
    updated = apply_weather_policy_to_problem(_problem(), forecast, profile, random_seed=42)

    assert updated.metadata["final_soc_floor_percent"] == 45.0
    assert updated.metadata["final_soc_target_percent"] == 60.0
    assert updated.metadata["final_soc_target_tolerance_percent"] == 10.0
    assert updated.metadata["weather_operation_profile"]["final_soc_target_tolerance_percent"] == 10.0


def test_weather_strategy_term_changes_objective_not_accounting_cost():
    forecast = _forecast()
    profile = build_operation_profile(forecast)
    trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV", "ICE"),
    )
    duty = VehicleDuty(
        duty_id="duty-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip),),
    )
    base_problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="scenario-weather", objective_mode="total_cost"),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=5.0,
                allowed_vehicle_types=("BEV", "ICE"),
                energy_kwh=5.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="BEV_001",
                vehicle_type="BEV",
                home_depot_id="DEPOT",
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
        ),
        metadata={
            "service_date": "2025-08-21",
            "cost_component_flags": {"driver_cost": False, "vehicle_fixed_cost": False},
        },
    )
    problem = apply_weather_policy_to_problem(base_problem, forecast, profile, random_seed=42)
    plan = AssignmentPlan(
        duties=(duty,),
        served_trip_ids=("t1",),
        metadata={"duty_vehicle_map": {"duty-1": "BEV_001"}},
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.weather_strategy_objective_term_jpy_equivalent == -45.0
    assert breakdown.total_cost == 0.0
    assert breakdown.objective_value == -45.0


def test_vehicle_timeline_activity_includes_charge_and_refuel_only_vehicles():
    ids = vehicle_ids_with_timeline_activity(
        {},
        (ChargingSlot(vehicle_id="BEV_002", slot_index=1, charger_id="C1", charge_kw=50.0),),
        (RefuelSlot(vehicle_id="ICE_003", slot_index=2, refuel_liters=20.0),),
    )

    assert ids == ("BEV_002", "ICE_003")


def test_canonical_vehicle_timeline_rows_emit_charge_refuel_only_vehicles():
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-timeline",
            horizon_start="05:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(vehicle_id="BEV_002", vehicle_type="BEV", home_depot_id="DEPOT"),
            ProblemVehicle(vehicle_id="ICE_003", vehicle_type="ICE", home_depot_id="DEPOT"),
        ),
        depots=(ProblemDepot(depot_id="DEPOT", name="営業所"),),
        price_slots=tuple(EnergyPriceSlot(slot_index=idx) for idx in range(4)),
        metadata={"service_date": "2025-09-01"},
    )
    plan = AssignmentPlan(
        charging_slots=(ChargingSlot(vehicle_id="BEV_002", slot_index=1, charger_id="C1", charge_kw=50.0),),
        refuel_slots=(RefuelSlot(vehicle_id="ICE_003", slot_index=2, refuel_liters=20.0, location_id="DEPOT"),),
    )
    engine_result = SimpleNamespace(plan=plan)

    rows = _canonical_vehicle_timeline_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id="scenario-timeline",
        graph_context=None,
    )

    assert {(row["vehicle_id"], row["state"]) for row in rows} == {
        ("BEV_002", "charge"),
        ("ICE_003", "refuel"),
    }


def test_persist_rich_outputs_writes_weather_artifacts_and_manifest(tmp_path: Path):
    forecast = _forecast()
    profile = build_operation_profile(forecast)
    updated = apply_weather_policy_to_problem(_problem(), forecast, profile, random_seed=42)
    weather_policy = {
        "enabled": True,
        "forecast": dict(updated.metadata["weather_proxy"]),
        "operation_profile": dict(updated.metadata["weather_operation_profile"]),
        "audit": {
            "enabled": True,
            "forecast_type": "historical_analog_v1",
            "service_date": "2025-08-21",
            "analog_date": "2024-08-22",
            "no_future_leakage": True,
            "operation_mode": "aggressive",
            "initial_soc_randomized": True,
            "vehicle_initial_soc_ratio": {"BEV_001": updated.vehicles[0].initial_soc},
            "optimizer_metadata_keys": [
                "weather_proxy",
                "weather_operation_profile",
                "final_soc_floor_percent",
                "final_soc_target_percent",
            ],
        },
    }

    _persist_rich_run_outputs(
        run_dir=tmp_path,
        scenario={"simulation_config": {}},
        optimization_result={
            "scenario_id": "scenario-weather",
            "mode": "mode_milp_only",
            "solver_status": "SOLVED_FEASIBLE",
            "objective_value": 0.0,
            "solve_time_seconds": 0.1,
            "summary": {},
            "cost_breakdown": {},
            "weather_policy": weather_policy,
            "graph_artifacts": {},
        },
        optimization_audit={},
        result_payload={"assignment": {}, "unserved_tasks": [], "obj_breakdown": {}},
        sim_payload=None,
        canonical_solver_result={"charging_schedule": [], "refueling_schedule": []},
    )

    assert (tmp_path / "weather_proxy_forecast.json").exists()
    assert (tmp_path / "weather_operation_policy.json").exists()
    assert (tmp_path / "weather_policy_audit.json").exists()
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["weather_proxy_enabled"] is True
    assert manifest["weather_proxy_version"] == "historical_analog_v1"
    assert manifest["weather_operation_mode"] == "aggressive"


def test_weather_policy_disabled_ignores_stale_forecast_path():
    scenario = {
        "simulation_config": {
            "enable_weather_operation_policy": False,
            "weather_proxy_forecast_path": "missing/path.json",
        }
    }

    updated, forecast, profile = _prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=None,
        weather_proxy_forecast_path=None,
    )

    assert updated is scenario
    assert forecast is None
    assert profile is None
