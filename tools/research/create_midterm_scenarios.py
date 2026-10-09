"""Create the 11/28 midterm (柱A) scenarios as copies of the 12-week parent.

Decided at the 2026-10-08 meeting: winter/spring/summer weeks x grid import
limits 90/200/400/800 kW, plus an all-engine-bus comparison.  Every scenario
is a duplicate of the parent that produced the latest 12-week results; the
parent itself is verified unchanged.  No Prepare, no solve, no data download.

    .venv/Scripts/python.exe tools/research/create_midterm_scenarios.py \
        --store output/monthly_latest_20260925/controller/scenarios --manifest <new json>
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PARENT = "771d115b-75b0-49f7-a7f0-25f259a2cd21"
GRID_LIMITS_KW = (90, 200, 400, 800)
# Middle month of each reporting season among the frozen 12 representative weeks.
WEEKS = (("winter", "冬（1月代表週）", "2025-01-06"),
         ("spring", "春（4月代表週）", "2025-04-07"),
         ("summer", "夏（7月代表週）", "2025-07-07"))
PV_PLANE = {"pv_surface_tilt_deg": 30.0, "pv_surface_azimuth_deg": 180.0}


def _apply_common(doc: dict, diesel_co2: float) -> None:
    """Settings shared by every midterm scenario."""
    for vehicle in doc["vehicles"]:
        if str(vehicle.get("type")).upper() == "ICE":
            vehicle["co2EmissionKgPerL"] = diesel_co2
    for template in doc.get("vehicle_templates") or []:
        if str(template.get("type")).upper() == "ICE":
            template["co2EmissionKgPerL"] = diesel_co2
    overlay = doc["scenario_overlay"]
    overlay["cost_coefficients"]["ice_co2_kg_per_l"] = diesel_co2
    assets = doc["simulation_config"]["depot_energy_assets"]
    for asset in assets:
        if asset.get("depot_id") == "tsurumaki":
            asset.update(PV_PLANE)
    overlay["depot_energy_assets"]["tsurumaki"].update(PV_PLANE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--grid-limit-mode", choices=("hard", "soft"), default="soft",
                        help="soft: import above the limit is allowed at the contract overage penalty; "
                             "hard: physical cap (2026-10-09 first attempt, Stage 2/rolling infeasible)")
    parser.add_argument("--skip-all-ice", action="store_true",
                        help="Create only the grid-limit variants (the all-ICE case does not depend on the mode)")
    args = parser.parse_args()
    if args.manifest.exists():
        raise SystemExit(f"refusing to overwrite {args.manifest}; scenarios may already exist")
    os.environ["SCENARIO_STORE_PATH"] = str(args.store.resolve())
    sys.path.insert(0, str(ROOT))
    from bff.services.scenario_periods import PeriodEdit, get_periods, save_periods
    from bff.store import scenario_store
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import parent_hash
    from src.fuel_emission_factors import DIESEL_CO2_KG_PER_L, DIESEL_CO2_SOURCE
    from src.optimization.common.cost_components import DEFAULT_CONTRACT_OVERAGE_PENALTY_YEN_PER_KWH

    parent = scenario_store._load(PARENT, skip_graph_arcs=True)
    before = parent_hash(parent)
    ice = [v for v in parent["vehicles"] if str(v.get("type")).upper() == "ICE" and v.get("enabled") is not False]
    bev = [v for v in parent["vehicles"] if str(v.get("type")).upper() == "BEV" and v.get("enabled") is not False]
    if (len(bev), len(ice)) != (35, 25):
        raise SystemExit(f"Unexpected parent fleet: BEV {len(bev)}, ICE {len(ice)}")

    suffix = "（超過は罰金）" if args.grid_limit_mode == "soft" else "（物理上限）"
    prefix = "soft" if args.grid_limit_mode == "soft" else "grid"
    variants = [{"key": f"{prefix}{limit:03d}", "grid_limit_kw": limit,
                 "name": f"中間発表 柱A 受電上限{limit}kW{suffix}（仮・正式用コピー）"} for limit in GRID_LIMITS_KW]
    if not args.skip_all_ice:
        variants.append({"key": "all_ice", "grid_limit_kw": None,
                         "name": "中間発表 比較 全車エンジンバス（仮・正式用コピー）"})
    created = []
    for variant in variants:
        identity = scenario_store.duplicate_scenario(PARENT, name=variant["name"])["id"]
        if variant["key"] == "all_ice":
            # Same 60-vehicle fleet: each BEV is replaced by a copy of the parent's ICE model.
            scenario_store.duplicate_vehicle_batch(identity, ice[0]["id"], len(bev))
        doc = scenario_store._load(identity, skip_graph_arcs=True)
        _apply_common(doc, DIESEL_CO2_KG_PER_L)
        charging = doc["scenario_overlay"]["charging_constraints"]
        if variant["grid_limit_kw"] is not None and args.grid_limit_mode == "hard":
            # Hard cap on grid import, and the contract threshold set to the same
            # value so the 500 JPY/kWh overage term cannot act inside the cap.
            charging["physical_grid_import_limit_kw"] = float(variant["grid_limit_kw"])
            charging["depot_power_limit_kw"] = float(variant["grid_limit_kw"])
        elif variant["grid_limit_kw"] is not None:
            # Soft limit: the contract threshold moves; import above it is allowed
            # and priced by the existing overage penalty in Stage 1 and Stage 2,
            # so the optimizer may move trips to engine buses when that is cheaper.
            charging.pop("physical_grid_import_limit_kw", None)
            charging["depot_power_limit_kw"] = float(variant["grid_limit_kw"])
            doc["simulation_config"].update(
                enable_contract_overage_penalty=True,
                contract_overage_penalty_yen_per_kwh=DEFAULT_CONTRACT_OVERAGE_PENALTY_YEN_PER_KWH)
        else:
            bev_ids = {v["id"] for v in bev}
            for vehicle in doc["vehicles"]:
                if vehicle.get("id") in bev_ids:
                    vehicle["enabled"] = False
            doc["scenario_overlay"]["fleet"].update(n_bev=0, n_ice=len(ice) + len(bev))
        doc["meta"]["description"] = (
            f"中間発表(2026-11-28)柱A。親 {PARENT}（12週の結果に使用）のコピー。"
            f"PV傾斜30°・真南、軽油CO2 {DIESEL_CO2_KG_PER_L} kg/L（環境省 算定・報告・公表制度 R5年度実績以降）。"
            + ((f"受電上限 {variant['grid_limit_kw']} kW（物理上限＝契約閾値）。" if args.grid_limit_mode == "hard" else
                f"受電上限 {variant['grid_limit_kw']} kW（契約閾値。超過分は {DEFAULT_CONTRACT_OVERAGE_PENALTY_YEN_PER_KWH:g} 円/kWh の罰金で受電可）。")
               if variant["grid_limit_kw"]
               else "BEV35台を無効化（enabled=false）し、同型ICE35台を追加。受電条件は親と同じ。"))
        scenario_store._save(doc)
        saved = scenario_store._load(identity, skip_graph_arcs=True)
        active = [v for v in saved["vehicles"] if v.get("enabled") is not False]
        plan = get_periods(identity)
        save_periods(identity, PeriodEdit.model_validate(
            {"revision": plan["revision"],
             "periods": [{"id": season, "label": label, "start": start, "days": 7}
                         for season, label, start in WEEKS]}))
        created.append({
            "key": variant["key"], "scenario_id": identity, "name": variant["name"],
            "grid_limit_kw": variant["grid_limit_kw"],
            "active_vehicles": {"BEV": sum(str(v.get("type")).upper() == "BEV" for v in active),
                                "ICE": sum(str(v.get("type")).upper() == "ICE" for v in active)},
            "ice_co2_kg_per_l": sorted({v.get("co2EmissionKgPerL") for v in active
                                        if str(v.get("type")).upper() == "ICE"}),
            "charging_constraints": {k: saved["scenario_overlay"]["charging_constraints"].get(k)
                                     for k in ("depot_power_limit_kw", "physical_grid_import_limit_kw")},
            "contract_overage": {k: saved["simulation_config"].get(k)
                                 for k in ("enable_contract_overage_penalty", "contract_overage_penalty_yen_per_kwh")},
            "pv_plane": {k: saved["scenario_overlay"]["depot_energy_assets"]["tsurumaki"].get(k) for k in PV_PLANE},
            "weeks": [start for _, _, start in WEEKS],
            "scenario_hash": parent_hash(saved),
        })
    after = parent_hash(scenario_store._load(PARENT, skip_graph_arcs=True))
    if after != before:
        raise SystemExit("Parent scenario changed while creating copies")
    manifest = {"schema_version": "midterm_scenarios_v1", "store": str(args.store),
                "parent_id": PARENT, "parent_hash_at_copy": before, "parent_unchanged": True,
                "weeks": [{"season": s, "label": l, "start": w} for s, l, w in WEEKS],
                "diesel_co2": DIESEL_CO2_SOURCE, "pv_plane": PV_PLANE,
                "grid_limit_mode": args.grid_limit_mode,
                "grid_limit_semantics": ("physical_grid_import_limit_kw = depot_power_limit_kw = limit"
                                         if args.grid_limit_mode == "hard" else
                                         "depot_power_limit_kw = limit; import above it priced by the contract overage penalty"),
                "unchanged_from_parent": {
                    "co2_price_per_kg": parent["scenario_overlay"]["cost_coefficients"].get("co2_price_per_kg"),
                    "grid_co2_kg_per_kwh": parent["scenario_overlay"]["cost_coefficients"].get("grid_co2_kg_per_kwh")},
                "scenarios": created}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
