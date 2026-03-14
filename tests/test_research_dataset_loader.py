import pandas as pd

from src.research_dataset_loader import (
    MISSING_BUILT_DATA_MESSAGE,
    _normalize_route_row,
    build_dataset_bootstrap,
    get_dataset_status,
    list_dataset_statuses,
)


def test_dataset_status_exposes_tokyu_core_seed_contract():
    status = get_dataset_status("tokyu_core")

    assert status["datasetId"] == "tokyu_core"
    assert status["includedDepots"] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert status["includedRoutes"] == "ALL"
    if status["builtAvailable"]:
        assert status["warning"] is None
        assert status["manifest"] is not None
    else:
        assert status["warning"] == MISSING_BUILT_DATA_MESSAGE


def test_dataset_bootstrap_returns_seed_only_tokyu_core_defaults():
    bootstrap = build_dataset_bootstrap("tokyu_core", scenario_id="scenario-1", random_seed=7)

    assert [item["id"] for item in bootstrap["depots"]] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert len(bootstrap["vehicle_templates"]) >= 2
    assert bootstrap["feed_context"]["source"] in {"seed_only", "built_dataset"}
    if bootstrap["feed_context"]["source"] == "seed_only":
        assert len(bootstrap["routes"]) == 46
        assert bootstrap["timetable_rows"] == []
        assert bootstrap["trips"] == []
    else:
        assert len(bootstrap["routes"]) > 0
        assert len(bootstrap["timetable_rows"]) > 0
        assert len(bootstrap["trips"]) > 0
    assert bootstrap["scenario_overlay"]["dataset_id"] == "tokyu_core"
    assert isinstance(bootstrap["scenario_overlay"]["dataset_version"], str)
    assert bootstrap["scenario_overlay"]["dataset_version"]
    assert bootstrap["scenario_overlay"]["random_seed"] == 7
    assert bootstrap["dispatch_scope"]["depotId"] == "meguro"
    assert len(bootstrap["dispatch_scope"]["routeSelection"]["includeRouteIds"]) == len(bootstrap["routes"])


def test_list_dataset_statuses_returns_core_and_full():
    dataset_ids = {item["datasetId"] for item in list_dataset_statuses()}
    assert {"tokyu_core", "tokyu_full", "tokyu_dispatch_ready"}.issubset(dataset_ids)


def test_normalize_route_row_accepts_ndarray_stop_sequence():
    row = {
        "id": "tokyu:meguro:黒01",
        "routeCode": "黒０１",
        "routeLabel": "黒０１",
        "name": "黒０１",
        "stopSequence": pd.Series(["stop-a", "stop-b"]).to_numpy(),
    }

    normalized = _normalize_route_row(row)

    assert normalized["routeCode"] == "黒01"
    assert normalized["stopSequence"] == ["stop-a", "stop-b"]
