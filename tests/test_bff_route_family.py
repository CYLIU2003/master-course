from pathlib import Path

import pytest

from bff.routers import master_data
from bff.services.route_family import derive_route_family_metadata
from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    return store_dir


def test_route_family_keeps_main_pair_when_terminal_is_depot_like():
    routes = [
        {
            "id": "r-out",
            "name": "園01 (田園調布駅 -> 瀬田営業所)",
            "routeCode": "園０１",
            "startStop": "田園調布駅",
            "endStop": "瀬田営業所",
            "stopSequence": ["田園調布駅", "中間", "瀬田営業所"],
            "distanceKm": 12.0,
            "tripCount": 32,
        },
        {
            "id": "r-in",
            "name": "園01 (瀬田営業所 -> 田園調布駅)",
            "routeCode": "園01",
            "startStop": "瀬田営業所",
            "endStop": "田園調布駅",
            "stopSequence": ["瀬田営業所", "中間", "田園調布駅"],
            "distanceKm": 12.0,
            "tripCount": 31,
        },
        {
            "id": "r-depot",
            "name": "園01 入庫",
            "routeCode": "園01",
            "startStop": "中間",
            "endStop": "瀬田営業所",
            "stopSequence": ["中間", "別経路", "瀬田営業所"],
            "distanceKm": 4.0,
            "tripCount": 2,
        },
    ]

    metadata = derive_route_family_metadata(routes)

    assert metadata["r-out"].route_variant_type == "main_outbound"
    assert metadata["r-in"].route_variant_type == "main_inbound"
    assert metadata["r-out"].classification_confidence == pytest.approx(0.95)
    assert metadata["r-depot"].route_variant_type == "depot_in"
    assert metadata["r-depot"].classification_confidence >= 0.6
    assert "end contains depot-like keyword" in metadata["r-depot"].classification_reasons


def test_route_family_does_not_classify_keyword_only_route_as_depot():
    routes = [
        {
            "id": "r-main-out",
            "name": "園01 本線",
            "routeCode": "園01",
            "startStop": "A駅",
            "endStop": "B駅",
            "stopSequence": ["A駅", "中間", "B駅"],
            "distanceKm": 10.0,
            "tripCount": 20,
        },
        {
            "id": "r-main-in",
            "name": "園01 本線 逆",
            "routeCode": "園01",
            "startStop": "B駅",
            "endStop": "A駅",
            "stopSequence": ["B駅", "中間", "A駅"],
            "distanceKm": 10.0,
            "tripCount": 18,
        },
        {
            "id": "r-weak",
            "name": "園01 営業所",
            "routeCode": "園01",
            "startStop": "A駅",
            "endStop": "B営業所",
            "stopSequence": ["A駅", "別中間", "B営業所"],
            "distanceKm": 9.5,
            "tripCount": 12,
        },
    ]

    metadata = derive_route_family_metadata(routes)
    weak = metadata["r-weak"]

    assert weak.route_variant_type == "unknown"
    assert weak.classification_confidence == pytest.approx(0.1)
    assert "end contains depot-like keyword" in weak.classification_reasons
    assert any("below threshold" in reason for reason in weak.classification_reasons)


def test_route_family_router_enriches_routes_and_returns_family_detail(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Route family", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "r-out",
                "name": "園０１ (田園調布駅 -> 瀬田営業所)",
                "routeCode": "園０１",
                "routeLabel": "園０１ (田園調布駅 -> 瀬田営業所)",
                "startStop": "田園調布駅",
                "endStop": "瀬田営業所",
                "stopSequence": ["S1", "S2", "S3"],
                "tripCount": 10,
                "color": "#0f766e",
                "source": "odpt",
            },
            {
                "id": "r-in",
                "name": "園０１ (瀬田営業所 -> 田園調布駅)",
                "routeCode": "園０１",
                "routeLabel": "園０１ (瀬田営業所 -> 田園調布駅)",
                "startStop": "瀬田営業所",
                "endStop": "田園調布駅",
                "stopSequence": ["S3", "S2", "S1"],
                "tripCount": 9,
                "color": "#0f766e",
                "source": "odpt",
            },
        ],
    )

    routes_body = master_data.list_routes(
        scenario_id,
        depot_id=None,
        operator=None,
        group_by_family=True,
    )
    assert routes_body["total"] == 2
    assert all(item["routeFamilyCode"] == "園01" for item in routes_body["items"])
    assert [item["routeVariantType"] for item in routes_body["items"]] == [
        "main_outbound",
        "main_inbound",
    ]

    families_body = master_data.list_route_families(scenario_id, operator=None)
    assert families_body["total"] == 1
    family = families_body["items"][0]
    assert family["routeFamilyCode"] == "園01"
    assert family["variantCount"] == 2
    assert family["mainVariantCount"] == 2

    detail_body = master_data.get_route_family(scenario_id, family["routeFamilyId"])
    detail = detail_body["item"]
    assert detail["canonicalMainPair"]["outboundRouteId"] == "r-out"
    assert detail["canonicalMainPair"]["inboundRouteId"] == "r-in"
    assert detail["timetableDiagnostics"]["rawRouteCount"] == 2
