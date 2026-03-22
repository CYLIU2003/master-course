from tools.scenario_backup_tk import App, _choose_dataset_options


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
