from src.research_dataset_loader import (
    MISSING_BUILT_DATA_MESSAGE,
    build_dataset_bootstrap,
    get_dataset_status,
    list_dataset_statuses,
)


def test_dataset_status_exposes_tokyu_core_seed_contract():
    status = get_dataset_status("tokyu_core")

    assert status["datasetId"] == "tokyu_core"
    assert status["includedDepots"] == ["meguro"]
    assert status["includedRoutes"] == [
        "渋41",
        "渋42",
        "渋71",
        "渋72",
        "黒01",
        "黒02",
        "東98",
        "井50",
        "反51",
        "黒52",
        "さんまバス",
    ]
    if status["builtAvailable"]:
        assert status["warning"] is None
        assert status["manifest"] is not None
    else:
        assert status["warning"] == MISSING_BUILT_DATA_MESSAGE


def test_dataset_bootstrap_returns_seed_only_tokyu_core_defaults():
    bootstrap = build_dataset_bootstrap("tokyu_core", scenario_id="scenario-1", random_seed=7)

    assert [item["id"] for item in bootstrap["depots"]] == ["meguro"]
    assert len(bootstrap["routes"]) == 11
    assert bootstrap["feed_context"]["source"] in {"seed_only", "built_dataset"}
    if bootstrap["feed_context"]["source"] == "seed_only":
        assert bootstrap["timetable_rows"] == []
        assert bootstrap["trips"] == []
    else:
        assert len(bootstrap["timetable_rows"]) > 0
        assert len(bootstrap["trips"]) > 0
    assert bootstrap["scenario_overlay"]["dataset_id"] == "tokyu_core"
    assert isinstance(bootstrap["scenario_overlay"]["dataset_version"], str)
    assert bootstrap["scenario_overlay"]["dataset_version"]
    assert bootstrap["scenario_overlay"]["random_seed"] == 7
    assert bootstrap["dispatch_scope"]["depotId"] == "meguro"
    assert len(bootstrap["dispatch_scope"]["routeSelection"]["includeRouteIds"]) == 11


def test_list_dataset_statuses_returns_core_and_full():
    dataset_ids = {item["datasetId"] for item in list_dataset_statuses()}
    assert {"tokyu_core", "tokyu_full"}.issubset(dataset_ids)
