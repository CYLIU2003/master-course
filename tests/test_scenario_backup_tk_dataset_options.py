from tools.scenario_backup_tk import (
    App,
    _choose_dataset_options,
    _ordered_cost_breakdown_items,
    _expand_selected_routes_to_family_members,
    _scope_filter_routes,
    _group_scope_routes_by_family,
    _scope_summarize_routes,
    _scope_variant_mix_text,
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


def test_ordered_cost_breakdown_items_prioritizes_total_and_non_zero_costs() -> None:
    rows = _ordered_cost_breakdown_items(
        {
            "fuel_cost": 0.0,
            "driver_cost": 2006683.333333335,
            "vehicle_cost": 483447.4885844756,
            "energy_cost": 202796.50054309692,
            "penalty_unserved": 3360000.0,
            "total_cost": 6052927.3224609075,
        }
    )

    assert [row["key"] for row in rows[:5]] == [
        "total_cost",
        "energy_cost",
        "vehicle_cost",
        "driver_cost",
        "penalty_unserved",
    ]
    assert rows[-1]["key"] == "fuel_cost"
    assert rows[-1]["non_zero"] is False
