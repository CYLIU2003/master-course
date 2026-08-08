import inspect
import random
from pathlib import Path

import pytest

from tools.scenario_backup_tk import (
    App,
    _FORMAL_RESEARCH_RUN_LABEL,
    _RESEARCH_EXECUTION_OPTIONS,
    _RUN_PARAMETER_TAB_LABELS,
    _TRIAL_RUN_LABEL,
    _choose_dataset_options,
    _ordered_cost_breakdown_items,
    _expand_selected_routes_to_family_members,
    _scope_filter_routes,
    _group_scope_routes_by_family,
    _scope_summarize_routes,
    _scope_variant_mix_text,
)
from src.preprocess.weather.daily_weather_schema import WeatherProxyForecast
from src.preprocess.weather.weather_proxy_builder import write_weather_proxy_forecast_json


class DummyVar:
    def __init__(self, value) -> None:
        self._value = value

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value


@pytest.mark.parametrize(
    ("field", "default"),
    [
        ("timeLimitSeconds", 300),
        ("alnsIterations", 500),
        ("noImprovementLimit", 100),
        ("randomSeed", 42),
        ("maxStartFragmentsPerVehicle", 100),
        ("maxEndFragmentsPerVehicle", 100),
        ("unservedPenalty", 10000),
        ("gridFlatPricePerKwh", 30),
        ("gridSellPricePerKwh", 0),
        ("demandChargeCostPerKw", 1500),
        ("pvMarginalChargeCostYenPerKwh", 0),
        ("pvCurtailPenaltyYenPerKwh", 0),
        ("dieselPricePerL", 145),
        ("gridCo2KgPerKwh", 0),
        ("co2PricePerKg", 0),
        ("iceCo2KgPerL", 2.64),
        ("degradationWeight", 0),
        ("depotPowerLimitKw", 500),
        ("initialIceFuelPercent", 100.0),
        ("minIceFuelPercent", 10.0),
        ("maxIceFuelPercent", 90.0),
        ("defaultIceTankCapacityL", 300.0),
        ("deadheadSpeedKmh", 18.0),
    ],
)
def test_quick_setup_setting_text_preserves_explicit_zero(
    field: str,
    default: float,
) -> None:
    app = App.__new__(App)

    loaded = App._setting_text({field: 0.0}, field, default=default)

    assert loaded == "0.0"
    assert App._parse_float(app, loaded, default) == 0.0
    assert App._setting_text({}, field, default=default) == str(default)


def test_quick_setup_reload_has_no_falsey_numeric_fallbacks() -> None:
    source = inspect.getsource(App.load_quick_setup)
    zero_sensitive_fields = (
        "timeLimitSeconds",
        "alnsIterations",
        "noImprovementLimit",
        "randomSeed",
        "maxStartFragmentsPerVehicle",
        "maxEndFragmentsPerVehicle",
        "unservedPenalty",
        "gridFlatPricePerKwh",
        "gridSellPricePerKwh",
        "demandChargeCostPerKw",
        "pvMarginalChargeCostYenPerKwh",
        "pvCurtailPenaltyYenPerKwh",
        "dieselPricePerL",
        "gridCo2KgPerKwh",
        "co2PricePerKg",
        "iceCo2KgPerL",
        "degradationWeight",
        "depotPowerLimitKw",
        "initialIceFuelPercent",
        "minIceFuelPercent",
        "maxIceFuelPercent",
        "defaultIceTankCapacityL",
        "deadheadSpeedKmh",
    )

    for field in zero_sensitive_fields:
        assert f'get("{field}") or' not in source


def _weather_forecast() -> WeatherProxyForecast:
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


def test_run_parameter_tab_labels_keep_optimization_inputs_grouped() -> None:
    assert _RUN_PARAMETER_TAB_LABELS == (
        "よく使う",
        "営業所設備",
        "SOC/燃料",
        "料金/CO2",
        "PV/予報",
        "目的/詳細",
    )


def test_choose_dataset_options_prefers_runtime_ready_candidates() -> None:
    payload = {
        "defaultDatasetId": "tokyu_core",
        "items": [
            {"datasetId": "tokyu_dispatch_ready", "runtimeReady": False},
            {"datasetId": "tokyu_full", "runtimeReady": True},
            {"datasetId": "tokyu_core", "builtReady": True},
        ],
    }

    selected = _choose_dataset_options(payload)

    assert selected["visibleIds"] == ["tokyu_full", "tokyu_core"]
    assert selected["hiddenIds"] == ["tokyu_dispatch_ready"]
    assert selected["defaultDatasetId"] == "tokyu_full"
    assert selected["usedRuntimeReadyOnly"] is True


def test_choose_dataset_options_falls_back_to_all_when_runtime_ready_missing() -> None:
    payload = {
        "defaultDatasetId": "tokyu_core",
        "items": [
            {"datasetId": "tokyu_dispatch_ready", "runtimeReady": False},
            {"datasetId": "tokyu_core", "builtReady": False},
        ],
    }

    selected = _choose_dataset_options(payload)

    assert selected["visibleIds"] == ["tokyu_dispatch_ready", "tokyu_core"]
    assert selected["hiddenIds"] == []
    assert selected["defaultDatasetId"] == "tokyu_core"
    assert selected["usedRuntimeReadyOnly"] is False


def test_refresh_methods_are_noop_before_fleet_window_build() -> None:
    app = App.__new__(App)
    app._fleet_built = False
    app._fleet_window = None
    app.fleet_depot_var = None
    app.fleet_depot_combo = None
    app.vehicle_tree = None
    app.template_tree = None
    app._selected_scenario_id = lambda: "scenario-1"

    App.refresh_vehicles(app)
    App.refresh_templates(app)


def test_vehicle_refresh_context_extracts_ids_and_depot() -> None:
    depot_id, vehicle_ids = App._vehicle_refresh_context(
        {"item": {"id": "veh-1", "depotId": "dep-1"}},
        "",
    )

    assert depot_id == "dep-1"
    assert vehicle_ids == ["veh-1"]

    depot_id, vehicle_ids = App._vehicle_refresh_context(
        {
            "items": [
                {"id": "veh-a", "depotId": "dep-2"},
                {"id": "veh-b", "depotId": "dep-2"},
            ]
        },
        "dep-1",
    )

    assert depot_id == "dep-2"
    assert vehicle_ids == ["veh-a", "veh-b"]


def test_normalize_depot_choice_extracts_canonical_id() -> None:
    assert App._normalize_depot_choice("tsurumaki | 鶴巻営業所") == "tsurumaki"
    assert App._normalize_depot_choice("dep-1") == "dep-1"
    assert App._normalize_depot_choice("seta") == "seta"
    assert App._normalize_depot_choice("  ") == ""


def test_main_initial_soc_ratio_prefers_percent_field() -> None:
    class DummyVar:
        def __init__(self, value: str) -> None:
            self._value = value

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value

    app = App.__new__(App)
    app.initial_soc_var = DummyVar("0.25")
    app.initial_soc_percent_var = DummyVar("0.75")

    assert App._main_initial_soc_ratio(app) == 0.75

    app.initial_soc_percent_var.set("")
    assert App._main_initial_soc_ratio(app) == 0.25


def test_final_soc_ui_normalizes_ratio_inputs_to_percent() -> None:
    app = App.__new__(App)

    assert App._soc_percent_for_ui(0.2, 20.0) == "20"
    assert App._soc_percent_for_ui(20.0, 20.0) == "20"
    assert App._soc_percent_for_ui(80.0, 20.0) == "80"
    assert App._parse_soc_percent_for_payload(app, "0.8", 80.0) == 80.0
    assert App._parse_soc_percent_for_payload(app, "80", 80.0) == 80.0


def test_sync_prepared_state_from_response_keeps_soc_fields_unchanged() -> None:
    app = App.__new__(App)
    app.prepared_var = DummyVar("")
    app.workflow_status_var = DummyVar("")
    app.workflow_hint_var = DummyVar("")
    app.prepared_input_id = ""
    app.prepared_ready = False
    app.prepared_trip_count = 0
    app.prepared_dirty_reason = ""
    app.prepared_profile_name = ""
    app.final_soc_floor_percent_var = DummyVar("20")
    app.final_soc_target_percent_var = DummyVar("80")
    app.final_soc_target_tolerance_percent_var = DummyVar("0")

    App._sync_prepared_state_from_response(
        app,
        {
            "preparedInputId": "prepared-123",
            "ready": True,
            "tripCount": 456,
            "prepareProfile": {"profile": "solver-ready"},
        },
    )

    assert app.prepared_input_id == "prepared-123"
    assert app.prepared_ready is True
    assert app.prepared_trip_count == 456
    assert app.prepared_profile_name == "solver-ready"
    assert app.final_soc_floor_percent_var.get() == "20"
    assert app.final_soc_target_percent_var.get() == "80"
    assert app.final_soc_target_tolerance_percent_var.get() == "0"


def test_workflow_status_reflects_prepared_ready_and_stale() -> None:
    app = App.__new__(App)
    app.workflow_status_var = DummyVar("")
    app.workflow_hint_var = DummyVar("")
    app.prepared_input_id = "prepared-123"
    app.prepared_ready = True
    app.prepared_trip_count = 1234
    app.prepared_profile_name = "hybrid_seeded"
    app.prepared_dirty_reason = ""

    App._update_workflow_status(app)

    assert app.workflow_status_var.get() == "準備済み: 1,234便 / hybrid_seeded"
    assert "すぐジョブ投入" in app.workflow_hint_var.get()

    app.prepared_ready = False
    app.prepared_dirty_reason = "料金を変更"

    App._update_workflow_status(app)

    assert app.workflow_status_var.get() == "再Prepare必要: 料金を変更"
    assert "先にPrepare" in app.workflow_hint_var.get()


def test_build_optimization_run_payload_centralizes_fast_and_manual_execution() -> None:
    app = App.__new__(App)
    app.solver_mode_var = DummyVar("mode_alns_only")
    app.mip_gap_var = DummyVar("0.02")
    app.stage1_candidate_limit_var = DummyVar("7")
    app.stage1_composition_radius_var = DummyVar("2")
    app.stage1_bev_frontier_enabled_var = DummyVar(True)
    app.stage1_bev_frontier_min_var = DummyVar("10")
    app.stage1_bev_frontier_max_var = DummyVar("20")
    app.stage1_bev_frontier_time_limit_var = DummyVar("90")
    app.integrated_actual_cost_objective_var = DummyVar(True)
    app.integrated_ev_utilization_mode_var = DummyVar(
        "minimum_ice_fuel_lexicographic"
    )
    app.integrated_actual_cost_upper_bound_var = DummyVar("100000")
    app.integrated_actual_cost_upper_bound_delta_var = DummyVar("0.01")
    app.alns_iter_var = DummyVar("750")
    app.no_improvement_limit_var = DummyVar("120")
    app.destroy_fraction_var = DummyVar("0.3")
    app.day_type_var = DummyVar("WEEKDAY")
    app.rebuild_dispatch_before_opt_var = DummyVar(False)
    app.require_all_available_bevs_var = DummyVar(True)
    app.research_execution_mode_var = DummyVar(_FORMAL_RESEARCH_RUN_LABEL)
    app.prepared_input_id = "prepared-old"
    app._selected_depot_ids = lambda: ["dep-1"]
    app._timestep_min_value = lambda: 30
    app._effective_optimization_time_limit_seconds = lambda: 180
    app._weather_proxy_optimization_payload = lambda: {"enableWeatherOperationPolicy": False}

    payload = App._build_optimization_run_payload(app, "prepared-new")

    assert payload == {
        "mode": "mode_alns_only",
        "research_run": True,
        "prepared_input_id": "prepared-new",
        "time_step_min": 30,
        "timestep_min": 30,
        "time_limit_seconds": 180,
        "stage1_best_obj_stop_enabled": False,
        "stage1_stage2_candidate_limit": 7,
        "stage1_composition_search_radius": 2,
        "stage1_bev_frontier_enabled": False,
        "stage1_bev_frontier_min_count": 10,
        "stage1_bev_frontier_max_count": 20,
        "stage1_bev_frontier_target_time_limit_seconds": 90,
        "integrated_actual_cost_objective": False,
        "integrated_ev_utilization_mode": "disabled",
        "integrated_actual_cost_upper_bound_jpy": None,
        "integrated_actual_cost_upper_bound_delta_ratio": None,
        "gurobi_threads": 8,
        "run_profile": "day_ahead_and_hourly_rolling",
        "run_hourly_rolling": True,
        "rolling_execution_minutes": 60,
        "require_all_available_bevs": True,
        "mip_gap": 0.02,
        "alns_iterations": 750,
        "no_improvement_limit": 120,
        "destroy_fraction": 0.3,
        "service_id": "WEEKDAY",
        "depot_id": "dep-1",
        "rebuild_dispatch": False,
        "enableWeatherOperationPolicy": False,
    }

    app.research_execution_mode_var.set(_TRIAL_RUN_LABEL)
    assert App._build_optimization_run_payload(
        app, "prepared-trial"
    )["research_run"] is False

    app.solver_mode_var.set("phase4_integrated")
    phase4_payload = App._build_optimization_run_payload(app, "prepared-phase4")
    assert phase4_payload["integrated_actual_cost_objective"] is True
    assert phase4_payload["integrated_ev_utilization_mode"] == "disabled"
    assert phase4_payload["integrated_actual_cost_upper_bound_jpy"] is None

    app.integrated_actual_cost_objective_var.set(False)
    phase4_utilization_payload = App._build_optimization_run_payload(
        app,
        "prepared-phase4-utilization",
    )
    assert phase4_utilization_payload["integrated_ev_utilization_mode"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert phase4_utilization_payload[
        "integrated_actual_cost_upper_bound_jpy"
    ] == 100000.0


def test_run_panel_exposes_separate_trial_and_formal_execution_choices() -> None:
    source = inspect.getsource(App._build_run_panel)

    assert "_TRIAL_RUN_LABEL" in source
    assert "_RESEARCH_EXECUTION_OPTIONS" in source
    assert _RESEARCH_EXECUTION_OPTIONS == (
        _TRIAL_RUN_LABEL,
        _FORMAL_RESEARCH_RUN_LABEL,
    )
    assert "DIAGNOSTIC / teacher release BLOCKED" in source


def test_formal_git_preflight_rejects_dirty_worktree_before_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def get_research_git_preflight(self):
            return {
                "formal_research_ready": False,
                "git_dirty": True,
                "uncommitted_changes": [
                    " M src/optimization/model.py",
                    "?? tests/test_model.py",
                ],
            }

    app = App.__new__(App)
    app.client = Client()
    app.research_execution_mode_var = DummyVar(_FORMAL_RESEARCH_RUN_LABEL)
    logged: list[str] = []
    shown: list[tuple[str, str]] = []
    app.log_line = logged.append
    monkeypatch.setattr(
        "tools.scenario_backup_tk.messagebox.showerror",
        lambda title, message: shown.append((title, message)),
    )

    assert App._preflight_research_run_selection(app) is False
    assert shown
    assert "正式研究実行を開始できません" in shown[0][1]
    assert " M src/optimization/model.py" in shown[0][1]
    assert "?? tests/test_model.py" in shown[0][1]
    assert logged


def test_trial_run_skips_formal_git_preflight_and_payload_log_keeps_flag() -> None:
    class Client:
        def get_research_git_preflight(self):
            raise AssertionError("trial runs must not invoke formal Git preflight")

    app = App.__new__(App)
    app.client = Client()
    app.research_execution_mode_var = DummyVar(_TRIAL_RUN_LABEL)

    assert App._preflight_research_run_selection(app) is True
    assert App._compact_execution_payload(
        {"mode": "mode_milp_only", "research_run": False}
    ) == '{"mode": "mode_milp_only", "research_run": false}'


def test_job_snapshot_exposes_final_artifact_bundle_status() -> None:
    snapshot = App._compact_job_snapshot(
        {
            "job_id": "job-1",
            "status": "completed",
            "metadata": {
                "run_dir": "C:/master-course/output/2026-07-28/run_1",
                "reporting_finalizer_status": "completed",
                "artifact_completeness_status": "OK",
                "artifact_completeness_artifact": (
                    "artifact_completeness.json"
                ),
                "required_artifact_count": 190,
                "verified_artifact_count": 190,
            },
        }
    )

    metadata = snapshot["metadata"]
    assert metadata["run_dir"].endswith("run_1")
    assert metadata["reporting_finalizer_status"] == "completed"
    assert metadata["artifact_completeness_status"] == "OK"
    assert metadata["artifact_completeness_artifact"] == (
        "artifact_completeness.json"
    )
    assert metadata["required_artifact_count"] == 190
    assert metadata["verified_artifact_count"] == 190


def test_operation_time_window_payload_is_explicit_and_defaults_to_full_day() -> None:
    app = App.__new__(App)
    app.operation_time_window_enabled_var = DummyVar(False)
    app.operation_start_time_var = DummyVar("05:00")
    app.operation_end_time_var = DummyVar("23:00")

    disabled_payload = App._operation_time_window_payload(app)

    assert disabled_payload == {
        "operationTimeWindowEnabled": False,
        "startTime": "05:00",
        "endTime": "23:00",
    }
    assert App._planning_horizon_hours_value(app, 1) == 24.0

    app.operation_time_window_enabled_var.set(True)
    assert App._planning_horizon_hours_value(app, 1) == 18.0


def test_prepare_weather_proxy_validation_does_not_overwrite_soc_fields() -> None:
    app = App.__new__(App)
    app.enable_weather_operation_policy_var = DummyVar(True)
    app.weather_proxy_summary_var = DummyVar("Weather proxy: disabled")
    app.final_soc_floor_percent_var = DummyVar("20")
    app.final_soc_target_percent_var = DummyVar("80")
    app.final_soc_target_tolerance_percent_var = DummyVar("0")
    app._load_weather_proxy_forecast_from_ui = lambda: _weather_forecast()

    seen: dict[str, object] = {}

    def _fake_apply(forecast, *, update_soc_fields: bool, mark_stale: bool):
        seen["update_soc_fields"] = update_soc_fields
        seen["mark_stale"] = mark_stale
        app.weather_proxy_summary_var.set(f"reflected:{forecast.forecast_type}")
        return forecast

    app._apply_weather_proxy_forecast_to_ui = _fake_apply

    assert App._ensure_weather_proxy_ready_for_optimization(app) is True
    assert seen == {"update_soc_fields": False, "mark_stale": False}
    assert app.final_soc_floor_percent_var.get() == "20"
    assert app.final_soc_target_percent_var.get() == "80"
    assert app.final_soc_target_tolerance_percent_var.get() == "0"


def test_weather_proxy_forecast_application_does_not_update_visible_soc_policy() -> None:
    app = App.__new__(App)
    app.final_soc_floor_percent_var = DummyVar("0.2")
    app.final_soc_target_percent_var = DummyVar("0.8")
    app.weather_proxy_summary_var = DummyVar("")
    app._suspend_prepare_watchers = False

    profile = App._apply_weather_proxy_forecast_to_ui(
        app,
        _weather_forecast(),
        update_soc_fields=True,
        mark_stale=False,
    )

    assert profile.operation_mode == "aggressive"
    assert app.final_soc_floor_percent_var.get() == "0.2"
    assert app.final_soc_target_percent_var.get() == "0.8"
    assert "analog=2024-08-22" in app.weather_proxy_summary_var.get()
    assert "SOC方針=変更なし" in app.weather_proxy_summary_var.get()


def test_weather_proxy_optimization_payload_disables_stale_path_when_unchecked() -> None:
    app = App.__new__(App)
    app.enable_weather_operation_policy_var = DummyVar(False)
    app.weather_proxy_forecast_path_var = DummyVar("missing/path.json")

    payload = App._weather_proxy_optimization_payload(app)

    assert payload == {"enableWeatherOperationPolicy": False}


def test_weather_proxy_optimization_payload_includes_path_only_when_enabled() -> None:
    app = App.__new__(App)
    app.enable_weather_operation_policy_var = DummyVar(True)
    app.weather_proxy_forecast_path_var = DummyVar("data/weather/proxy_forecasts/sample.json")

    payload = App._weather_proxy_optimization_payload(app)

    assert payload == {
        "enableWeatherOperationPolicy": True,
        "weatherProxyForecastPath": "data/weather/proxy_forecasts/sample.json",
    }


def test_weather_proxy_milp_warns_but_keeps_long_time_limit_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MC_ALLOW_LONG_WEATHER_MILP", raising=False)
    app = App.__new__(App)
    app.time_limit_var = DummyVar("3000")
    app.solver_mode_var = DummyVar("mode_milp_only")
    app.enable_weather_operation_policy_var = DummyVar(True)
    logs: list[str] = []
    app.log_line = logs.append

    assert App._effective_optimization_time_limit_seconds(app) == 3000
    assert "Weather proxy" in logs[0]
    assert "3000s" in logs[0]


def test_weather_proxy_milp_long_time_limit_can_be_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MC_ALLOW_LONG_WEATHER_MILP", "1")
    app = App.__new__(App)
    app.time_limit_var = DummyVar("3000")
    app.solver_mode_var = DummyVar("mode_milp_only")
    app.enable_weather_operation_policy_var = DummyVar(True)
    app.log_line = lambda message: None

    assert App._effective_optimization_time_limit_seconds(app) == 3000


def test_weather_proxy_time_limit_guard_does_not_affect_alns(monkeypatch) -> None:
    monkeypatch.delenv("MC_ALLOW_LONG_WEATHER_MILP", raising=False)
    app = App.__new__(App)
    app.time_limit_var = DummyVar("3000")
    app.solver_mode_var = DummyVar("mode_alns_only")
    app.enable_weather_operation_policy_var = DummyVar(True)
    app.log_line = lambda message: None

    assert App._effective_optimization_time_limit_seconds(app) == 3000


def test_solver_settings_window_labels_mip_gap_as_ratio() -> None:
    source = inspect.getsource(App.open_solver_settings_window)

    assert "MILPギャップ（比率: 0.01 = 1%）" in source
    assert "0.001 = 0.1%" in source


def test_solver_settings_window_exposes_timestep_selector() -> None:
    source = inspect.getsource(App.open_solver_settings_window)

    assert "計算ステップ" in source
    assert 'values=["5", "15", "30", "60"]' in source
    assert "Prepareをやり直してください" in source


def test_timestep_payload_uses_supported_discretization() -> None:
    app = App.__new__(App)
    app.timestep_min_var = DummyVar("30")

    for raw, expected in (
        ("5", 5),
        ("15", 15),
        ("30", 30),
        ("60", 60),
        ("17", 30),
    ):
        app.timestep_min_var.set(raw)
        assert App._timestep_min_value(app) == expected


def test_timestep_payload_fields_are_wired() -> None:
    prepare_source = inspect.getsource(App._prepare_payload)
    execute_source = inspect.getsource(App.run_selected_execution)
    quick_setup_source = inspect.getsource(App.save_quick_setup)

    assert '"time_step_min": self._timestep_min_value()' in prepare_source
    assert '"timestep_min": self._timestep_min_value()' in prepare_source
    assert '"time_step_min": self._timestep_min_value()' in execute_source
    assert '"timestep_min": self._timestep_min_value()' in execute_source
    assert '"timeStepMin": self._timestep_min_value()' in quick_setup_source
    assert '"timestepMin": self._timestep_min_value()' in quick_setup_source


def test_depot_charger_manager_exposes_bess_buffer_fields() -> None:
    manager_source = inspect.getsource(App.open_vehicle_depot_manager)
    sync_source = inspect.getsource(App._sync_depot_manager_energy_asset_row)

    assert "BESSバッファ下限 [%]" in manager_source
    assert "BESSバッファ上限 [%]" in manager_source
    assert "dm_bess_soc_min_percent_var" in manager_source
    assert "dm_bess_soc_max_percent_var" in manager_source
    assert "BESS終端方針" in manager_source
    assert "BESS終端SOC目標 [%]（目標指定時のみ）" in manager_source
    assert 'row["bess_soc_min_ratio"]' in sync_source
    assert 'row["bess_soc_max_ratio"]' in sync_source
    assert 'row["bess_terminal_soc_policy"]' in sync_source
    assert 'row["bess_terminal_soc_target_ratio"]' in sync_source


def test_weather_proxy_json_loader_rejects_service_date_mismatch(tmp_path: Path) -> None:
    forecast_path = tmp_path / "forecast.json"
    write_weather_proxy_forecast_json(forecast_path, _weather_forecast())
    app = App.__new__(App)
    app.weather_proxy_forecast_path_var = DummyVar(str(forecast_path))
    app.service_date_var = DummyVar("2025-08-22")
    app._selected_service_dates = lambda announce=False: ["2025-08-22"]

    with pytest.raises(ValueError, match="WEATHER_PROXY_SERVICE_DATE_MISMATCH"):
        App._load_weather_proxy_forecast_from_ui(app)


def test_initial_soc_values_for_mode_supports_fixed_and_random() -> None:
    fixed = App._initial_soc_values_for_mode(
        mode="固定値",
        quantity=3,
        fixed_soc=0.8,
        random_min=None,
        random_max=None,
    )
    assert fixed == [0.8, 0.8, 0.8]

    randomized = App._initial_soc_values_for_mode(
        mode="ランダム",
        quantity=4,
        fixed_soc=None,
        random_min=0.5,
        random_max=0.6,
        rng=random.Random(42),
    )
    assert len(randomized) == 4
    assert all(0.5 <= value <= 0.6 for value in randomized)
    assert randomized == [0.563943, 0.502501, 0.527503, 0.522321]


def test_apply_initial_soc_to_bev_vehicles_updates_only_selected_depot_bevs() -> None:
    class DummyClient:
        def __init__(self) -> None:
            self.list_calls: list[tuple[str, str]] = []
            self.update_calls: list[tuple[str, str, dict[str, float]]] = []

        def list_vehicles(self, scenario_id: str, depot_id: str | None = None) -> dict[str, object]:
            self.list_calls.append((scenario_id, str(depot_id)))
            items_by_depot = {
                "dep-1": [
                    {"id": "bev-1", "type": "BEV", "depotId": "dep-1"},
                    {"id": "ice-1", "type": "ICE", "depotId": "dep-1"},
                ],
                "dep-2": [
                    {"id": "bev-2", "type": "BEV", "depotId": "dep-2"},
                ],
            }
            return {"items": list(items_by_depot.get(str(depot_id), []))}

        def update_vehicle(self, scenario_id: str, vehicle_id: str, payload: dict[str, float]) -> dict[str, object]:
            self.update_calls.append((scenario_id, vehicle_id, payload))
            return {"id": vehicle_id, "initialSoc": payload["initialSoc"]}

    app = App.__new__(App)
    app.client = DummyClient()

    result = App._apply_initial_soc_to_bev_vehicles(
        app,
        "scenario-1",
        ["dep-1", "dep-2"],
        0.66,
    )

    assert app.client.list_calls == [("scenario-1", "dep-1"), ("scenario-1", "dep-2")]
    assert app.client.update_calls == [
        ("scenario-1", "bev-1", {"initialSoc": 0.66}),
        ("scenario-1", "bev-2", {"initialSoc": 0.66}),
    ]
    assert result["depotIds"] == ["dep-1", "dep-2"]
    assert len(result["items"]) == 2


def test_finalize_main_initial_soc_bulk_apply_clears_checkbox_and_refreshes_visible_depot() -> None:
    class DummyVar:
        def __init__(self, value):
            self._value = value

        def get(self):
            return self._value

        def set(self, value) -> None:
            self._value = value

    app = App.__new__(App)
    app.apply_initial_soc_percent_to_selected_bevs_var = DummyVar(True)
    app.fleet_depot_var = DummyVar("dep-2")
    logs: list[str] = []
    refreshes: list[str | None] = []
    stale_flags: list[bool] = []
    app.log_line = logs.append
    app.refresh_vehicles = lambda depot_id=None, focus_vehicle_id=None: refreshes.append(depot_id)
    app._mark_vehicle_change_stale = lambda: stale_flags.append(True)
    app._vehicle_panel_ready = lambda: True

    App._finalize_main_initial_soc_bulk_apply(
        app,
        {
            "applied": True,
            "depotIds": ["dep-1", "dep-2"],
            "items": [{"id": "bev-1"}, {"id": "bev-2"}],
            "initialSoc": 0.7,
        },
    )

    assert app.apply_initial_soc_percent_to_selected_bevs_var.get() is False
    assert stale_flags == [True]
    assert refreshes == ["dep-2"]
    assert logs and "初期SOC比一斉反映" in logs[0]


def test_mutation_guard_disables_quick_setup_save_while_vehicle_add_runs() -> None:
    class DummyButton:
        def __init__(self) -> None:
            self.state = "normal"

        def winfo_exists(self) -> bool:
            return True

        def configure(self, *, state: str) -> None:
            self.state = state

    app = App.__new__(App)
    app._quick_setup_save_buttons = [DummyButton()]
    app._vehicle_add_buttons = [DummyButton()]
    app._quick_setup_save_inflight = 0
    app._vehicle_add_inflight = 1

    App._update_mutation_guard_button_states(app)

    assert app._quick_setup_save_buttons[0].state == "disabled"
    assert app._vehicle_add_buttons[0].state == "normal"


def test_mutation_guard_disables_vehicle_add_while_quick_setup_save_runs() -> None:
    class DummyButton:
        def __init__(self) -> None:
            self.state = "normal"

        def winfo_exists(self) -> bool:
            return True

        def configure(self, *, state: str) -> None:
            self.state = state

    app = App.__new__(App)
    app._quick_setup_save_buttons = [DummyButton()]
    app._vehicle_add_buttons = [DummyButton()]
    app._quick_setup_save_inflight = 1
    app._vehicle_add_inflight = 0

    App._update_mutation_guard_button_states(app)

    assert app._quick_setup_save_buttons[0].state == "normal"
    assert app._vehicle_add_buttons[0].state == "disabled"


def test_refresh_vehicles_focuses_new_row_and_syncs_depot() -> None:
    class DummyVar:
        def __init__(self, value: str = "") -> None:
            self._value = value

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value

    class DummyTree:
        def __init__(self) -> None:
            self.rows: list[tuple[str, tuple[object, ...]]] = []
            self.selected: list[str] = []
            self.focused: str | None = None
            self.seen: str | None = None

        def winfo_exists(self) -> bool:
            return True

        def selection(self) -> tuple[str, ...]:
            return tuple(self.selected)

        def delete(self, *items: str) -> None:
            self.rows = [row for row in self.rows if row[0] not in items]
            self.selected = [item for item in self.selected if item not in items]

        def get_children(self) -> tuple[str, ...]:
            return tuple(row[0] for row in self.rows)

        def insert(self, _parent: str, _index: str, *, iid: str, values: tuple[object, ...]) -> None:
            self.rows.append((iid, values))

        def set(self, _iid: str, _column: str, _value: object) -> None:
            return None

        def selection_set(self, iid: str) -> None:
            self.selected = [iid]

        def focus(self, iid: str) -> None:
            self.focused = iid

        def see(self, iid: str) -> None:
            self.seen = iid

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def list_vehicles(self, scenario_id: str, depot_id: str | None = None) -> dict[str, object]:
            self.calls.append((scenario_id, depot_id))
            return {
                "items": [
                    {"id": "veh-1", "depotId": depot_id, "type": "BEV", "modelName": "A", "acquisitionCost": 0, "energyConsumption": 1.2, "chargePowerKw": 90, "enabled": True},
                    {"id": "veh-2", "depotId": depot_id, "type": "BEV", "modelName": "B", "acquisitionCost": 0, "energyConsumption": 1.2, "chargePowerKw": 90, "enabled": True},
                ],
                "total": 2,
            }

    app = App.__new__(App)
    app._selected_scenario_id = lambda: "scenario-1"
    app._vehicle_panel_ready = lambda: True
    app.fleet_depot_var = DummyVar("")
    app.vehicle_tree = DummyTree()
    app.vehicle_checked_ids = set()
    app.vehicle_batch_summary_var = DummyVar("")
    app.vehicle_select_all_var = DummyVar(False)
    app._vehicle_refresh_token = 0
    app.vehicle_row_by_id = {}
    app.client = DummyClient()
    app.log_line = lambda _msg: None
    app.run_bg = lambda action, done=None: done(action()) if done else action()
    app.on_vehicle_select_called = 0
    app.on_vehicle_select = lambda _event=None: setattr(
        app,
        "on_vehicle_select_called",
        app.on_vehicle_select_called + 1,
    )

    App.refresh_vehicles(app, depot_id="dep-1", focus_vehicle_id="veh-2")

    assert app.client.calls == [("scenario-1", "dep-1")]
    assert app.fleet_depot_var.get() == "dep-1"
    assert [row[0] for row in app.vehicle_tree.rows] == ["veh-1", "veh-2"]
    assert app.vehicle_tree.selected == ["veh-2"]
    assert app.vehicle_tree.focused == "veh-2"
    assert app.vehicle_tree.seen == "veh-2"
    assert app.on_vehicle_select_called == 1


def test_refresh_vehicles_normalizes_labeled_depot_before_fetch() -> None:
    class DummyVar:
        def __init__(self, value: str = "") -> None:
            self._value = value

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value

    class DummyTree:
        def __init__(self) -> None:
            self.rows: list[tuple[str, tuple[object, ...]]] = []

        def winfo_exists(self) -> bool:
            return True

        def selection(self) -> tuple[str, ...]:
            return ()

        def delete(self, *items: str) -> None:
            self.rows = [row for row in self.rows if row[0] not in items]

        def get_children(self) -> tuple[str, ...]:
            return tuple(row[0] for row in self.rows)

        def insert(self, _parent: str, _index: str, *, iid: str, values: tuple[object, ...]) -> None:
            self.rows.append((iid, values))

        def set(self, _iid: str, _column: str, _value: object) -> None:
            return None

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def list_vehicles(self, scenario_id: str, depot_id: str | None = None) -> dict[str, object]:
            self.calls.append((scenario_id, depot_id))
            return {"items": [], "total": 0}

    app = App.__new__(App)
    app._selected_scenario_id = lambda: "scenario-1"
    app._vehicle_panel_ready = lambda: True
    app.fleet_depot_var = DummyVar("dep-1 | 営業所A")
    app.vehicle_tree = DummyTree()
    app.vehicle_checked_ids = set()
    app.vehicle_batch_summary_var = DummyVar("")
    app.vehicle_select_all_var = DummyVar(False)
    app._vehicle_refresh_token = 0
    app.vehicle_row_by_id = {}
    app.client = DummyClient()
    app.log_line = lambda _msg: None
    app.run_bg = lambda action, done=None: done(action()) if done else action()

    App.refresh_vehicles(app)

    assert app.client.calls == [("scenario-1", "dep-1")]
    assert app.fleet_depot_var.get() == "dep-1"


def test_on_vehicle_select_prefers_cached_vehicle_row() -> None:
    class DummyTree:
        def selection(self) -> tuple[str, ...]:
            return ("veh-1",)

    app = App.__new__(App)
    app._selected_scenario_id = lambda: "scenario-1"
    app.vehicle_tree = DummyTree()
    app.vehicle_row_by_id = {"veh-1": {"id": "veh-1", "modelName": "Cached"}}
    populated: list[dict[str, object]] = []
    app._populate_vehicle_form = lambda row: populated.append(dict(row))

    class DummyClient:
        def get_vehicle(self, scenario_id: str, vehicle_id: str) -> dict[str, object]:
            raise AssertionError("cached row should avoid get_vehicle call")

    app.client = DummyClient()
    app.run_bg = lambda action, done=None: done(action()) if done else action()

    App.on_vehicle_select(app)

    assert populated == [{"id": "veh-1", "modelName": "Cached"}]


def test_set_all_visible_vehicle_checked_updates_summary_and_all_toggle() -> None:
    class DummyVar:
        def __init__(self, value):
            self._value = value

        def get(self):
            return self._value

        def set(self, value) -> None:
            self._value = value

    class DummyTree:
        def winfo_exists(self) -> bool:
            return True

        def set(self, _iid: str, _column: str, _value: object) -> None:
            return None

    app = App.__new__(App)
    app.vehicle_rows = [
        {"id": "veh-1"},
        {"id": "veh-2"},
    ]
    app.vehicle_checked_ids = set()
    app.vehicle_tree = DummyTree()
    app.vehicle_batch_summary_var = DummyVar("")
    app.vehicle_select_all_var = DummyVar(False)

    App._set_all_visible_vehicle_checked(app, True)

    assert app.vehicle_checked_ids == {"veh-1", "veh-2"}
    assert app.vehicle_batch_summary_var.get() == "選択: 2/2件"
    assert app.vehicle_select_all_var.get() is True


def test_batch_target_vehicle_rows_falls_back_to_visible_bevs_when_nothing_checked() -> None:
    app = App.__new__(App)
    app.vehicle_rows = [
        {"id": "bev-1", "type": "BEV"},
        {"id": "ice-1", "type": "ICE"},
        {"id": "bev-2", "type": "BEV"},
    ]
    app.vehicle_checked_ids = set()

    rows = App._batch_target_vehicle_rows(
        app,
        bev_only=True,
        fallback_to_visible=True,
    )

    assert [row["id"] for row in rows] == ["bev-1", "bev-2"]


def test_on_vehicle_tree_click_heading_toggles_all_visible() -> None:
    class DummyVar:
        def __init__(self, value):
            self._value = value

        def get(self):
            return self._value

        def set(self, value) -> None:
            self._value = value

    class DummyTree:
        def winfo_exists(self) -> bool:
            return True

        def identify_region(self, _x: int, _y: int) -> str:
            return "heading"

        def identify_column(self, _x: int) -> str:
            return "#1"

        def identify_row(self, _y: int) -> str:
            return ""

        def set(self, _iid: str, _column: str, _value: object) -> None:
            return None

    class Event:
        x = 1
        y = 1

    app = App.__new__(App)
    app.vehicle_rows = [{"id": "veh-1"}, {"id": "veh-2"}]
    app.vehicle_checked_ids = set()
    app.vehicle_tree = DummyTree()
    app.vehicle_batch_summary_var = DummyVar("")
    app.vehicle_select_all_var = DummyVar(False)

    result = App._on_vehicle_tree_click(app, Event())

    assert result == "break"
    assert app.vehicle_checked_ids == {"veh-1", "veh-2"}
    assert app.vehicle_select_all_var.get() is True


def test_open_fleet_window_syncs_existing_scope_depots(monkeypatch) -> None:
    class DummyWidget:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def pack(self, *args, **kwargs):
            return self

    class DummyRoot:
        def winfo_screenwidth(self) -> int:
            return 1200

        def winfo_screenheight(self) -> int:
            return 900

    class DummyWindow:
        def winfo_exists(self) -> bool:
            return True

        def lift(self) -> None:
            return None

        def focus_force(self) -> None:
            return None

        def title(self, _title: str) -> None:
            return None

        def geometry(self, _geometry: str) -> None:
            return None

        def minsize(self, _width: int, _height: int) -> None:
            return None

        def protocol(self, _name: str, _callback) -> None:
            return None

        def destroy(self) -> None:
            return None

    app = App.__new__(App)
    app.root = DummyRoot()
    app._fleet_window = None
    app._fleet_built = False
    app.scope_depots = [{"id": "tsurumaki"}, {"id": "seta"}]
    app.fleet_depot_var = None
    app.vehicle_tree = None
    app.template_tree = None
    app.fleet_depot_combo = None
    app.dup_target_depot_combo = None
    app._build_fleet_panel = lambda _parent: None

    captured: list[list[dict[str, object]]] = []
    app._refresh_depot_dropdowns = lambda depots: captured.append(list(depots))

    monkeypatch.setattr("tools.scenario_backup_tk.ttk.Frame", DummyWidget)
    monkeypatch.setattr("tools.scenario_backup_tk.ttk.Label", DummyWidget)
    monkeypatch.setattr("tools.scenario_backup_tk.tk.Toplevel", lambda _root: DummyWindow())

    App.open_fleet_window(app)

    assert captured == [[{"id": "tsurumaki"}, {"id": "seta"}]]


def test_on_scenario_changed_skips_fleet_refresh_when_window_not_built() -> None:
    app = App.__new__(App)
    app._fleet_built = False
    app._fleet_window = None
    app.load_quick_setup_called = False
    app.refresh_templates_called = False
    app.refresh_vehicles_called = False
    app._selected_scenario_id = lambda: "scenario-1"
    app.load_quick_setup = lambda: setattr(app, "load_quick_setup_called", True)
    app.refresh_templates = lambda: setattr(app, "refresh_templates_called", True)
    app.refresh_vehicles = lambda: setattr(app, "refresh_vehicles_called", True)
    app.log_line = lambda _msg: None

    App.on_scenario_changed(app, None)

    assert app.load_quick_setup_called is True
    assert app.refresh_templates_called is False
    assert app.refresh_vehicles_called is False


def test_queue_on_ui_thread_returns_false_when_root_is_closed() -> None:
    class ClosedRoot:
        def winfo_exists(self) -> bool:
            return False

    app = App.__new__(App)
    app.root = ClosedRoot()

    assert App._queue_on_ui_thread(app, lambda: None) is False


def test_queue_on_ui_thread_swallows_after_runtime_error() -> None:
    class BrokenRoot:
        def winfo_exists(self) -> bool:
            return True

        def after(self, _delay: int, _callback) -> None:
            raise RuntimeError("main thread is not in main loop")

    app = App.__new__(App)
    app.root = BrokenRoot()

    assert App._queue_on_ui_thread(app, lambda: None) is False


def test_expand_selected_routes_to_family_members_uses_half_width_family_code() -> None:
    routes = [
        {"id": "route-a", "depotId": "dep1", "routeFamilyCode": "黒０１"},
        {"id": "route-b", "depotId": "dep1", "routeFamilyCode": "黒01"},
        {"id": "route-c", "depotId": "dep2", "routeFamilyCode": "黒01"},
    ]

    expanded = _expand_selected_routes_to_family_members(routes, {"route-a"})

    assert expanded == {"route-a", "route-b"}


def test_group_scope_routes_by_family_groups_routes_under_family_per_depot() -> None:
    routes = [
        {"id": "route-b", "depotId": "dep1", "routeFamilyCode": "黒01", "routeFamilyLabel": "目黒駅-東京駅", "familySortOrder": 20},
        {"id": "route-a", "depotId": "dep1", "routeFamilyCode": "黒０１", "routeFamilyLabel": "目黒駅-東京駅", "familySortOrder": 10},
        {"id": "route-c", "depotId": "dep1", "routeFamilyCode": "東98", "routeFamilyLabel": "東京駅南口-清水", "familySortOrder": 10},
    ]

    family_keys_by_depot, family_route_ids, family_labels = _group_scope_routes_by_family(routes)

    assert family_keys_by_depot["dep1"] == ["dep1::東98", "dep1::黒01"]
    assert family_route_ids["dep1::黒01"] == ["route-a", "route-b"]
    assert family_labels["dep1::黒01"] == "黒01 | 目黒駅-東京駅"


def test_scope_filter_routes_matches_family_code_label_and_variant_text() -> None:
    routes = [
        {
            "id": "route-main",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "routeFamilyLabel": "東京駅南口-清水",
            "routeLabel": "東京駅南口 -> 清水",
            "routeVariantType": "main_outbound",
        },
        {
            "id": "route-depot",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "routeFamilyLabel": "東京駅南口-清水",
            "routeLabel": "目黒郵便局 -> 等々力操車所",
            "routeVariantType": "depot_in",
        },
    ]

    assert [item["id"] for item in _scope_filter_routes(routes, "東98")] == ["route-main", "route-depot"]
    assert [item["id"] for item in _scope_filter_routes(routes, "清水")] == ["route-main", "route-depot"]
    assert [item["id"] for item in _scope_filter_routes(routes, "入庫便")] == ["route-depot"]


def test_scope_summarize_routes_counts_family_and_variant_mix() -> None:
    routes = [
        {
            "id": "route-main",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "tripCountsByDayType": {"WEEKDAY": 32},
            "routeVariantType": "main_outbound",
        },
        {
            "id": "route-depot",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "tripCountsByDayType": {"WEEKDAY": 6},
            "routeVariantType": "depot_in",
        },
    ]

    summary = _scope_summarize_routes(routes, day_type="WEEKDAY")

    assert summary["familyCount"] == 1
    assert summary["routeCount"] == 2
    assert summary["tripCount"] == 38
    assert summary["mainRouteCount"] == 1
    assert summary["mainTripCount"] == 32
    assert summary["depotRouteCount"] == 1
    assert summary["depotTripCount"] == 6
    assert _scope_variant_mix_text(summary, metric="trips") == "本線32便 / 入出庫6便"


def test_apply_day_type_scope_filter_keeps_all_routes_visible_and_only_updates_counts() -> None:
    class DummyVar:
        def __init__(self, value: str) -> None:
            self._value = value

        def get(self) -> str:
            return self._value

    app = App.__new__(App)
    app.day_type_var = DummyVar("SAT")
    app.scope_all_routes = [
        {
            "id": "route-a",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "tripCountsByDayType": {"WEEKDAY": 10, "SAT": 0},
        },
        {
            "id": "route-b",
            "depotId": "dep1",
            "routeFamilyCode": "東98",
            "tripCountsByDayType": {"WEEKDAY": 3, "SAT": 2},
        },
    ]
    app.scope_depots = [{"id": "dep1", "name": "Depot 1"}]
    app.scope_depot_by_id = {"dep1": {"id": "dep1", "name": "Depot 1"}}
    app.scope_selected_route_ids = {"route-a", "route-b"}
    app.scope_selected_depot_ids = {"dep1"}
    app.scope_routes = []
    app.scope_route_by_id = {}
    app.scope_routes_by_depot = {}
    app.scope_family_keys_by_depot = {}
    app.scope_family_route_ids = {}
    app.scope_family_label_by_key = {}
    app._sync_depot_selection_from_routes = lambda: None
    app._render_scope_checklist = lambda: None

    App._refresh_scope_route_cache(app, app.scope_all_routes)
    App._apply_day_type_scope_filter(app)

    assert sorted(app.scope_route_by_id.keys()) == ["route-a", "route-b"]
    assert app.scope_route_by_id["route-a"]["tripCountsByDayType"]["SAT"] == 0
    assert app.scope_route_by_id["route-b"]["tripCountsByDayType"]["SAT"] == 2


def test_extract_result_summary_includes_non_zero_cost_breakdown_and_served_counts() -> None:
    app = App.__new__(App)

    summary = App._extract_result_summary(
        app,
        {
            "mode": "mode_abc_only",
            "objective_value": 6052927.3224609075,
            "solve_time_seconds": 63.23714519990608,
            "summary": {
                "vehicle_count_used": 55,
                "trip_count_served": 638,
                "trip_count_unserved": 336,
            },
            "solver_result": {
                "status": "feasible",
                "objective_value": 6052927.3224609075,
                "solve_time_seconds": 63.23714519990608,
            },
            "cost_breakdown": {
                "energy_cost": 202796.50054309692,
                "electricity_cost_final": 202796.50054309692,
                "vehicle_cost": 483447.4885844756,
                "driver_cost": 2006683.333333335,
                "penalty_unserved": 3360000.0,
                "total_cost": 6052927.3224609075,
            },
        },
    )

    assert summary["status"] == "feasible"
    assert summary["mode"] == "mode_abc_only"
    assert summary["total_cost"] == 6052927.3224609075
    assert summary["served_trips"] == 638.0
    assert summary["unserved_trips"] == 336.0
    assert summary["vehicle_count_used"] == 55.0
    assert summary["vehicle_cost"] == 483447.4885844756
    assert summary["driver_cost"] == 2006683.333333335
    assert summary["penalty_unserved"] == 3360000.0


def test_extract_result_summary_separates_total_cost_objective_and_validity_badge() -> None:
    app = App.__new__(App)

    summary = App._extract_result_summary(
        app,
        {
            "mode": "mode_milp_only",
            "objective_value": -49718.03699606294,
            "summary": {
                "vehicle_count_used": 32,
                "trip_count_served": 264,
                "trip_count_unserved": 0,
                "solution_validity": {
                    "validated_feasible": False,
                    "status_reason": "baseline_fallback_or_postsolve_infeasible",
                },
            },
            "solver_result": {
                "status": "BASELINE_FALLBACK",
                "objective_value": -49718.03699606294,
            },
            "cost_breakdown": {
                "total_cost": 61781.96300393706,
                "return_leg_bonus": 111500.0,
            },
        },
    )

    assert summary["status"] == "BASELINE_FALLBACK"
    assert summary["solution_validity_badge"] == "暫定/無効 (baseline_fallback_or_postsolve_infeasible)"
    assert summary["total_cost"] == 61781.96300393706
    assert summary["objective"] == -49718.03699606294
    assert summary["return_leg_bonus"] == 111500.0


def test_ordered_cost_breakdown_items_prioritizes_total_and_non_zero_costs() -> None:
    rows = _ordered_cost_breakdown_items(
        {
            "fuel_cost": 0.0,
            "driver_cost": 2006683.333333335,
            "vehicle_cost": 483447.4885844756,
            "energy_cost": 202796.50054309692,
            "penalty_unserved": 3360000.0,
            "return_leg_bonus": 111500.0,
            "total_cost": 6052927.3224609075,
        }
    )

    assert [row["key"] for row in rows[:6]] == [
        "total_cost",
        "return_leg_bonus",
        "energy_cost",
        "vehicle_cost",
        "driver_cost",
        "penalty_unserved",
    ]
    assert next(row for row in rows if row["key"] == "return_leg_bonus")["share"] is None
    assert rows[-1]["key"] == "fuel_cost"
    assert rows[-1]["non_zero"] is False
