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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="canonical_solver_result.json of the anchor run")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.result.read_bytes()
    seed = seed_from_result(json.loads(raw))
    args.output.write_text(json.dumps(seed, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source": str(args.result), "source_sha256": hashlib.sha256(raw).hexdigest(),
                      "duties": len(seed["duties"]), "trips": len(seed["served_trip_ids"])}))


if __name__ == "__main__":
    main()
