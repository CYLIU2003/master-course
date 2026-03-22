from tools.scenario_backup_tk import _choose_dataset_options


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
