from __future__ import annotations

from src.research_dataset_loader import default_vehicle_templates


def test_default_vehicle_templates_match_core_six_models() -> None:
    templates = default_vehicle_templates()
    assert len(templates) == 6

    names = {str(item.get("modelName") or "") for item in templates}
    assert "BYD K8 2.0" in names
    assert "日野 ブルーリボン Z EV" in names
    assert "いすゞ エルガ EV" in names
    assert "日野 ブルーリボン 2KG-KV290N4 AT" in names
    assert "いすゞ エルガ 2KG-LV290N4 AT" in names
    assert "三菱ふそう エアロスター 2KG-MP38FK AT" in names

    by_name = {str(item.get("modelName") or ""): item for item in templates}

    # EV templates use kWh/km values.
    assert abs(float(by_name["BYD K8 2.0"]["energyConsumption"]) - 1.316) < 1.0e-9
    assert float(by_name["BYD K8 2.0"]["batteryKwh"]) == 314.0

    # ICE templates use L/km values with 160L tank baseline.
    assert abs(float(by_name["日野 ブルーリボン 2KG-KV290N4 AT"]["energyConsumption"]) - 0.1869) < 1.0e-9
    assert float(by_name["日野 ブルーリボン 2KG-KV290N4 AT"]["fuelTankL"]) == 160.0

    assert abs(float(by_name["いすゞ エルガ 2KG-LV290N4 AT"]["energyConsumption"]) - 0.1869) < 1.0e-9
    assert float(by_name["いすゞ エルガ 2KG-LV290N4 AT"]["fuelTankL"]) == 160.0

    assert abs(float(by_name["三菱ふそう エアロスター 2KG-MP38FK AT"]["energyConsumption"]) - 0.2212) < 1.0e-9
    assert float(by_name["三菱ふそう エアロスター 2KG-MP38FK AT"]["fuelTankL"]) == 160.0
