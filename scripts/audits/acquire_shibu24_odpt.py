"""Manually capture a new immutable ODPT Shibu24 timetable source.

Only this explicit CLI invocation may request ODPT. Prepare and job submission
consume a separately audited, frozen optimization database instead.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.audits.acquire_tsurumaki_odpt import capture_resource
from scripts.catalog._odpt_runtime import resolve_odpt_api_key
from scripts.catalog.build_tokyu_subset_db import OPERATOR_ID
from scripts.audits.audit_shibu24_source import normalize_route_code


def acquire(output: Path) -> dict:
    manifest_path = output / "shibu24_capture_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"ODPT capture is immutable; choose a new output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    key = resolve_odpt_api_key(None)
    patterns, pattern_source = capture_resource(
        output, "odpt:BusroutePattern", {"odpt:operator": OPERATOR_ID}, key
    )
    selected = sorted(
        (row for row in patterns
         if normalize_route_code(row.get("dc:title")) == "渋24"
         and ".Shibu24." in str(row.get("owl:sameAs") or "")),
        key=lambda row: row["owl:sameAs"],
    )
    identifiers = [row["owl:sameAs"] for row in selected]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("Shibu24 ODPT patterns are missing or duplicated")
    if any(row.get("odpt:operator") != OPERATOR_ID for row in selected):
        raise ValueError("Shibu24 ODPT pattern has an unexpected operator")
    sources = [pattern_source]
    timetable_count = 0
    for pattern_id in identifiers:
        rows, source = capture_resource(
            output, "odpt:BusTimetable", {"odpt:busroutePattern": pattern_id}, key
        )
        if not rows or any(
            row.get("odpt:operator") != OPERATOR_ID
            or row.get("odpt:busroutePattern") != pattern_id
            or not row.get("owl:sameAs")
            for row in rows
        ):
            raise ValueError(f"Invalid Shibu24 ODPT timetable for {pattern_id}")
        sources.append(source)
        timetable_count += len(rows)
    stops, stop_source = capture_resource(
        output, "odpt:BusstopPole", {"odpt:operator": OPERATOR_ID}, key
    )
    stop_ids = [row.get("owl:sameAs") for row in stops]
    if (not stop_ids or any(not stop_id for stop_id in stop_ids)
            or len(stop_ids) != len(set(stop_ids))
            or any(row.get("odpt:operator") != OPERATOR_ID for row in stops)):
        raise ValueError("Invalid Shibu24 ODPT stop source")
    sources.append(stop_source)
    manifest = {
        "schema_version": "shibu24_odpt_source_capture_v1",
        "route_code": "渋24",
        "status": "SOURCES_CAPTURED_COMPARISON_PENDING",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "pattern_ids": identifiers,
        "pattern_count": len(identifiers),
        "timetable_count": timetable_count,
        "stop_source_path": stop_source["path"],
        "sources": sources,
        "claim": "Current published timetable, not historical actual operations",
    }
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = acquire(args.output.resolve())
    print(json.dumps({key: result[key] for key in
                      ("status", "pattern_count", "timetable_count", "stop_source_path")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
