"""Write the assignment of a finished run as a compact ``stage1_seed_plan`` request value."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def seed_from_result(result: dict) -> dict:
    metadata = result.get("metadata") or {}
    if not result.get("duties") or not metadata.get("duty_vehicle_map"):
        raise ValueError("Result has no complete vehicle assignment")
    if result.get("unserved_trip_ids"):
        raise ValueError("A seed must serve every trip")
    return {
        "duties": [{"duty_id": d["duty_id"], "vehicle_type": d["vehicle_type"], "legs": d["legs"]}
                   for d in result["duties"]],
        "served_trip_ids": result["served_trip_ids"], "unserved_trip_ids": [],
        "metadata": {key: metadata[key] for key in ("duty_vehicle_map", "horizon_start_min") if key in metadata},
    }


def charging_start_from_result(result: dict) -> list[dict]:
    """The anchor's day-ahead charging summed per (vehicle, slot, charger): a Stage 2 MIP start only."""
    if not result.get("feasible") or (result.get("solver_metadata") or {}).get("stage2_has_feasible_incumbent") is False:
        raise ValueError("Charging start needs a feasible anchor Stage 2")
    power: dict[tuple[str, int, str], float] = {}
    for row in result.get("charging_schedule") or []:
        if float(row.get("discharge_kw") or 0.0) != 0.0:
            raise ValueError("Charging start does not carry discharge")
        key = (str(row["vehicle_id"]), int(row["slot_index"]), str(row["charger_id"]))
        power[key] = power.get(key, 0.0) + float(row["charge_kw"])
    if not power:
        raise ValueError("Anchor has no charging schedule")
    return [{"vehicle_id": v, "slot_index": s, "charger_id": c, "charge_kw": kw}
            for (v, s, c), kw in sorted(power.items())]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="canonical_solver_result.json of the anchor run")
    parser.add_argument("output", type=Path)
    parser.add_argument("--with-charging-start", action="store_true",
                        help="also carry the anchor's day-ahead charging as a Stage 2 MIP start")
    args = parser.parse_args()
    raw = args.result.read_bytes()
    result = json.loads(raw)
    seed = seed_from_result(result)
    if args.with_charging_start:
        seed["charging_slots"] = charging_start_from_result(result)
        seed["charging_start_source"] = {"result_sha256": hashlib.sha256(raw).hexdigest(),
                                         "semantics": "day_ahead_stage2_mip_start_only"}
    args.output.write_text(json.dumps(seed, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source": str(args.result), "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "duties": len(seed["duties"]), "trips": len(seed["served_trip_ids"])}))


if __name__ == "__main__":
    main()
