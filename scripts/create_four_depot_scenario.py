"""Create a scenario with four depots and initial fleets per user request.

Creates depots:
 - 目黒営業所
 - 瀬田営業所
 - 淡島営業所
 - 弦巻営業所

For each depot creates:
 - 20 x BYD K8 (BEV)
 - 40 x Mitsubishi (ICE)
 - 40 x エルガ (ICE)

Resulting in ~100 vehicles per depot.

Run: python -m scripts.create_four_depot_scenario
"""

from pathlib import Path
from pprint import pprint

from bff.store import scenario_store


def main() -> int:
    name = "四営業所 初期車両セット"
    meta = scenario_store.create_scenario(name, "自動作成シナリオ", "thesis_mode")
    scenario_id = meta["id"]
    print(f"created scenario: {scenario_id} ({name})")

    depot_names = ["目黒営業所", "瀬田営業所", "淡島営業所", "弦巻営業所"]

    depots = []
    for dname in depot_names:
        dep = scenario_store.create_depot(scenario_id, {"name": dname})
        depots.append(dep)
        print(f" created depot: {dep['id']} - {dname}")

    # Create vehicle templates (optional helpful metadata)
    bev_template = scenario_store.create_vehicle_template(
        scenario_id,
        {
            "name": "BYD K8",
            "type": "BEV",
            "modelName": "BYD K8",
            "capacityPassengers": 60,
            "batteryKwh": 300.0,
            "chargePowerKw": 150.0,
            "energyConsumption": 1.2,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 30_000_000.0,
            "enabled": True,
        },
    )
    ice_mitsubishi_template = scenario_store.create_vehicle_template(
        scenario_id,
        {
            "name": "Mitsubishi Diesel",
            "type": "ICE",
            "modelName": "Mitsubishi Diesel",
            "capacityPassengers": 75,
            "fuelTankL": 220.0,
            "energyConsumption": 0.42,
            "acquisitionCost": 22_000_000.0,
            "enabled": True,
        },
    )
    ice_elga_template = scenario_store.create_vehicle_template(
        scenario_id,
        {
            "name": "エルガ",
            "type": "ICE",
            "modelName": "エルガ",
            "capacityPassengers": 75,
            "fuelTankL": 220.0,
            "energyConsumption": 0.42,
            "acquisitionCost": 22_000_000.0,
            "enabled": True,
        },
    )

    print("created vehicle templates:")
    pprint([bev_template.get("id"), ice_mitsubishi_template.get("id"), ice_elga_template.get("id")])

    # For each depot, create the vehicle fleet
    for depot in depots:
        depot_id = depot["id"]
        # 20 BEV BYD K8
        scenario_store.create_vehicle_batch(
            scenario_id,
            {
                "depotId": depot_id,
                "modelName": "BYD K8",
                "vehicleTemplateId": bev_template.get("id"),
                "type": "BEV",
                "batteryKwh": 300.0,
                "chargePowerKw": 150.0,
                "initialSoc": 0.8,
            },
            quantity=20,
        )

        # 40 x Mitsubishi (ICE)
        scenario_store.create_vehicle_batch(
            scenario_id,
            {
                "depotId": depot_id,
                "modelName": "Mitsubishi Diesel",
                "vehicleTemplateId": ice_mitsubishi_template.get("id"),
                "type": "ICE",
                "fuelTankL": 220.0,
            },
            quantity=40,
        )

        # 40 x エルガ (ICE)
        scenario_store.create_vehicle_batch(
            scenario_id,
            {
                "depotId": depot_id,
                "modelName": "エルガ",
                "vehicleTemplateId": ice_elga_template.get("id"),
                "type": "ICE",
                "fuelTankL": 220.0,
            },
            quantity=40,
        )

        count = len(scenario_store.list_vehicles(scenario_id, depot_id))
        print(f" depot {depot_id} now has {count} vehicles")

    # Summary
    total_vehicles = len(scenario_store.list_vehicles(scenario_id))
    print(f"scenario {scenario_id} total vehicles: {total_vehicles}")

    # Show path to stored scenario file
    store_dir = Path(scenario_store._STORE_DIR)
    scenario_path = store_dir / f"{scenario_id}.json"
    print(f"scenario stored at: {scenario_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
