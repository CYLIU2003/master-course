from __future__ import annotations

from bff.services.run_preparation import _scenario_hash


def _base_scenario() -> dict:
    return {
        "meta": {
            "id": "scenario-1",
            "operatorId": "tokyu",
            "createdAt": "2026-03-21T00:00:00Z",
            "updatedAt": "2026-03-21T00:00:00Z",
        },
        "feed_context": {
            "datasetId": "tokyu_core",
            "snapshotId": "2026-03-21",
        },
        "scenario_overlay": {
            "dataset_id": "tokyu_core",
            "dataset_version": "2026-03-21",
            "random_seed": 42,
        },
        "dispatch_scope": {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["tokyu:depot:1"],
                "primaryDepotId": "tokyu:depot:1",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["tokyu:route:1"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": False,
                "includeDeadhead": True,
            },
            "depotId": "tokyu:depot:1",
            "serviceId": "WEEKDAY",
        },
        "simulation_config": {
            "day_type": "WEEKDAY",
            "solver_mode": "mode_milp_only",
            "time_limit_seconds": 300,
        },
        "depots": [{"id": "tokyu:depot:1", "name": "Depot 1"}],
        "routes": [{"id": "tokyu:route:1", "name": "Route 1"}],
        "vehicles": [{"id": "veh-1", "depotId": "tokyu:depot:1", "type": "BEV"}],
        "chargers": [{"id": "charger-1", "siteId": "tokyu:depot:1", "powerKw": 90}],
    }


def test_scenario_hash_ignores_heavy_runtime_artifacts() -> None:
    shallow_doc = _base_scenario() | {
        "timetable_rows": [],
        "stop_timetables": [],
        "trips": None,
        "graph": None,
        "blocks": None,
        "duties": None,
        "dispatch_plan": None,
        "simulation_result": None,
        "optimization_result": None,
    }
    full_doc = _base_scenario() | {
        "refs": {"artifactStore": "outputs/scenarios/scenario-1/artifacts.sqlite"},
        "stats": {"tripCount": 12, "dutyCount": 4},
        "timetable_rows": [{"trip_id": "trip-1"}],
        "stop_timetables": [{"trip_id": "trip-1", "stop_sequence": 1}],
        "trips": [{"trip_id": "trip-1"}],
        "graph": {"arcs": [{"from_trip_id": "trip-1", "to_trip_id": "trip-2"}]},
        "blocks": [{"block_id": "block-1"}],
        "duties": [{"duty_id": "duty-1"}],
        "dispatch_plan": {"plans": [{"plan_id": "plan-1"}]},
        "simulation_result": {"summary": {"vehicle_count_used": 1}},
        "optimization_result": {"solver_status": "FEASIBLE"},
    }

    assert _scenario_hash(shallow_doc) == _scenario_hash(full_doc)
