import json
from pathlib import Path

from bff.routers.optimization import (
    _persist_rich_run_outputs,
    _prepare_weather_policy_for_scenario,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)
from src.preprocess.weather.daily_weather_schema import WeatherProxyForecast
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
    assert updated_a.vehicles[0].initial_soc == updated_b.vehicles[0].initial_soc
    assert 0.55 <= updated_a.vehicles[0].initial_soc <= 0.95
    assert updated_a.vehicles[1].initial_soc is None


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
