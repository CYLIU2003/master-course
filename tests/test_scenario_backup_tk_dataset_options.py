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
    app.client = DummyClient()
    app.log_line = lambda _msg: None
    app.run_bg = lambda action, done=None: done(action()) if done else action()

    App.refresh_vehicles(app)

    assert app.client.calls == [("scenario-1", "dep-1")]
    assert app.fleet_depot_var.get() == "dep-1"


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
