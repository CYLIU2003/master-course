import json
from pathlib import Path

import pandas as pd

from src.research_dataset_loader import (
    MISSING_BUILT_DATA_MESSAGE,
    _normalize_route_row,
    build_dataset_bootstrap,
    default_vehicle_templates,
    get_dataset_status,
    list_dataset_statuses,
)
import src.tokyu_shard_loader as tokyu_shard_loader


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_dataset_status_exposes_tokyu_core_seed_contract():
    status = get_dataset_status("tokyu_core")

    assert status["datasetId"] == "tokyu_core"
    assert status["includedDepots"] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert status["includedRoutes"] == "ALL"
    if status["builtAvailable"] or status.get("shardReady"):
        assert status["warning"] is None
        assert status["manifest"] is not None or status.get("shardManifest") is not None
    else:
        assert status["warning"] == MISSING_BUILT_DATA_MESSAGE


def test_dataset_bootstrap_returns_seed_only_tokyu_core_defaults():
    bootstrap = build_dataset_bootstrap("tokyu_core", scenario_id="scenario-1", random_seed=7)

    assert [item["id"] for item in bootstrap["depots"]] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert len(bootstrap["vehicle_templates"]) >= 2
    assert bootstrap["feed_context"]["source"] in {"seed_only", "built_dataset", "tokyu_shards"}
    if bootstrap["feed_context"]["source"] == "seed_only":
        assert len(bootstrap["routes"]) == 46
        assert bootstrap["timetable_rows"] == []
        assert bootstrap["trips"] == []
    elif bootstrap["feed_context"]["source"] == "tokyu_shards":
        assert len(bootstrap["routes"]) > 0
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


def test_default_vehicle_templates_follow_catalog_based_large_route_bus_presets():
    templates = default_vehicle_templates()
    template_ids = {item["id"] for item in templates}

    assert {
        "tokyu-template-byd-k8-2-0",
        "tokyu-template-isuzu-erga-ev-swb-urban",
        "tokyu-template-hino-blueribbon-z-ev-swb-urban",
        "tokyu-template-isuzu-erga-diesel-swb-nonstep-amt",
        "tokyu-template-hino-blueribbon-diesel-swb",
        "tokyu-template-mitsubishi-fuso-aerostar-diesel-nonstep",
    }.issubset(template_ids)

    byd = next(item for item in templates if item["id"] == "tokyu-template-byd-k8-2-0")
    assert byd["type"] == "BEV"
    assert byd["batteryKwh"] == 314.0
    assert byd["energyConsumption"] == 1.308
    assert byd["chargePowerKw"] == 90.0

    erga_diesel = next(
        item
        for item in templates
        if item["id"] == "tokyu-template-isuzu-erga-diesel-swb-nonstep-amt"
    )
    assert erga_diesel["type"] == "ICE"
    assert erga_diesel["fuelTankL"] == 150.0
    assert erga_diesel["energyConsumption"] == 0.19
    assert erga_diesel["chargePowerKw"] is None


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


def test_dataset_bootstrap_prefers_tokyu_shards_when_ready(tmp_path, monkeypatch):
    shard_root = tmp_path / "outputs" / "built" / "tokyu"
    _write_json(
        shard_root / "manifest.json",
        {
            "dataset_id": "tokyu_core",
            "operator": "Tokyu",
            "operator_id": "tokyu",
            "build_timestamp": "2026-03-14T00:00:00+00:00",
            "source_version": "20260314T000000Z",
            "shard_version": "1.0.0",
            "available_depots": ["meguro", "seta", "awashima", "tsurumaki"],
            "available_routes": ["黒01"],
            "available_day_types": ["weekday", "saturday", "holiday"],
            "output_files": [],
            "warning_count": 0,
        },
    )
    _write_json(shard_root / "depots.json", {"dataset_id": "tokyu_core", "operator_id": "tokyu", "depots": []})
    _write_json(shard_root / "routes.json", {"dataset_id": "tokyu_core", "operator_id": "tokyu", "routes": []})
    _write_json(
        shard_root / "depot_route_index.json",
        {"dataset_id": "tokyu_core", "operator_id": "tokyu", "depots": [], "routes": []},
    )
    _write_json(
        shard_root / "depot_route_summary.json",
        {"dataset_id": "tokyu_core", "operator_id": "tokyu", "items": []},
    )
    _write_json(
        shard_root / "shard_manifest.json",
        {"dataset_id": "tokyu_core", "operator_id": "tokyu", "items": []},
    )
    monkeypatch.setattr(tokyu_shard_loader, "TOKYU_SHARD_ROOT", shard_root)

    bootstrap = build_dataset_bootstrap("tokyu_core", scenario_id="scenario-shard", random_seed=11)

    assert bootstrap["feed_context"]["source"] == "tokyu_shards"
    assert bootstrap["timetable_rows"] == []
    assert bootstrap["trips"] == []
    assert bootstrap["runtime_features"]["tokyuShards"]["enabled"] is True
