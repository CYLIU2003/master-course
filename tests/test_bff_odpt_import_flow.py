from pathlib import Path

import pytest

from bff.routers import master_data, scenarios
from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    return store_dir


def test_build_explorer_overview_counts_linked_timetable_rows(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Explorer overview", "", "thesis_mode")
    scenario_id = meta["id"]

    route = scenario_store.create_route(
        scenario_id,
        {
            "id": "R1",
            "name": "A -> B",
            "routeCode": "A01",
            "startStop": "Stop A",
            "endStop": "Stop B",
            "stopSequence": ["S1", "S2"],
            "tripCount": 0,
            "source": "odpt",
        },
    )
    scenario_store.set_field(
        scenario_id,
        "stops",
        [
            {"id": "S1", "name": "Stop A"},
            {"id": "S2", "name": "Stop B"},
        ],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": route["id"],
                "service_id": "WEEKDAY",
                "origin": "Stop A",
                "destination": "Stop B",
                "departure": "08:00",
                "arrival": "08:20",
            }
        ],
    )

    overview = master_data._build_explorer_overview(scenario_id, operator="tokyu")

    assert overview["routeCount"] == 1
    assert overview["routeWithStopsCount"] == 1
    assert overview["routeWithTimetableCount"] == 1


def test_import_timetable_odpt_syncs_calendar_entries(
    temp_store_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    meta = scenario_store.create_scenario("ODPT calendar sync", "", "thesis_mode")
    scenario_id = meta["id"]

    bundle = {
        "timetable_rows": [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "SAT_HOL",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:20",
                "source": "odpt",
            }
        ],
        "stop_timetables": [],
        "calendar_entries": [
            {
                "service_id": "SAT_HOL",
                "name": "土曜・休日",
                "mon": 0,
                "tue": 0,
                "wed": 0,
                "thu": 0,
                "fri": 0,
                "sat": 1,
                "sun": 1,
                "source": "odpt",
            }
        ],
        "meta": {},
    }

    monkeypatch.setattr(scenarios, "_load_odpt_bundle", lambda **_: bundle)

    scenarios._import_odpt_timetable_data(
        scenario_id,
        scenarios.ImportOdptTimetableBody(),
    )

    calendar_entries = scenario_store.get_calendar(scenario_id)
    assert any(entry.get("service_id") == "SAT_HOL" for entry in calendar_entries)
