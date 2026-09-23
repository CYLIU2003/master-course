"""Portable, solver-free integrity and accounting checks for a monthly bundle.

This deliberately does not certify all timetable, SOC, or MILP constraints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections.abc import Mapping
from pathlib import Path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as member:
        for block in iter(lambda: member.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sum_flows(flow: Mapping[str, Mapping[str, float]]) -> float:
    return math.fsum(float(value) for slots in flow.values() for value in slots.values())


def _close(actual: float, expected: float, *, tolerance: float = 1e-5) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance


def verify_bundle(path: Path) -> dict:
    failures: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        report = json.loads(archive.read("monthly_report.json"))
        if _sha256(archive.read("monthly_report.json")) != manifest["report_sha256"]:
            failures.append("report SHA mismatch")
        if report.get("source_git_sha") != manifest.get("source_git_sha"):
            failures.append("source Git SHA mismatch")
        for label, entry in (
            ("frozen source", manifest["frozen_source"]),
            ("verifier", {"relative_path": "verify_monthly_evidence_bundle.py", "sha256": manifest["verifier_sha256"]}),
            ("continuity checker", {"relative_path": "check_bess_week_continuity.py", "sha256": manifest["continuity_checker_sha256"]}),
            ("fleet candidate", {"relative_path": "fleet_candidate.json", "sha256": manifest["fleet_candidate_sha256"]}),
        ):
            relative = entry["relative_path"]
            if relative not in names or _sha256_member(archive, relative) != entry["sha256"]:
                failures.append(f"{label} SHA mismatch")
        if manifest.get("independent_audit_sha256") and (
            "independent_audit.json" not in names
            or _sha256(archive.read("independent_audit.json")) != manifest["independent_audit_sha256"]
        ):
            failures.append("independent audit SHA mismatch")
        if len(manifest["weeks"]) != 12 or len(report["weeks"]) != 12:
            failures.append("expected exactly 12 weeks")
        for week_manifest in manifest["weeks"]:
            week = next(
                (row for row in report["weeks"] if row["week"] == week_manifest["week"]),
                None,
            )
            if week is None:
                failures.append(f"{week_manifest['week']}: missing report row")
                continue
            loaded: dict[str, dict] = {}
            for kind, entry in week_manifest["files"].items():
                relative = entry["relative_path"]
                if relative.startswith("/") or ".." in Path(relative).parts or relative not in names:
                    failures.append(f"{week['week']}: unsafe or missing {kind}")
                    continue
                raw = archive.read(relative)
                if _sha256(raw) != entry["sha256"]:
                    failures.append(f"{week['week']}: {kind} SHA mismatch")
                    continue
                loaded[kind] = json.loads(raw)
            if len(loaded) != 5:
                continue
            accounting = loaded["executed_day_accounting"]
            plan = loaded["executed_plan"]
            physical = loaded["physical_validation"]
            prepared = loaded["prepared_input"]
            breakdown = accounting["cost_breakdown"]
            total = float(breakdown["total_cost"])
            components = math.fsum(
                float(breakdown[key])
                for key in (
                    "electricity_cost", "fuel_cost", "vehicle_usage_cost", "co2_cost",
                    "contract_overage_cost", "driver_cost", "vehicle_cost", "demand_cost",
                    "unserved_penalty", "switch_cost", "degradation_cost", "deviation_cost",
                    "stationary_battery_degradation_cost", "pv_asset_cost", "bess_asset_cost",
                )
            )
            if not _close(total, components) or not _close(total, float(week["total_cost"])):
                failures.append(f"{week['week']}: total-cost reconciliation failed")
            if not physical.get("accepted") or physical.get("violations"):
                failures.append(f"{week['week']}: physical report not accepted")
            if not accounting.get("eligible"):
                failures.append(f"{week['week']}: accounting not eligible")
            if len(prepared.get("vehicles", [])) != 60:
                failures.append(f"{week['week']}: prepared fleet count differs from 60")
            for metric, flow in (
                ("grid_import_kwh", "grid_to_bus_kwh_by_depot_slot"),
                ("pv_to_bus_kwh", "pv_to_bus_kwh_by_depot_slot"),
                ("pv_to_bess_kwh", "pv_to_bess_kwh_by_depot_slot"),
                ("grid_to_bess_kwh", "grid_to_bess_kwh_by_depot_slot"),
            ):
                actual = _sum_flows(plan.get(flow, {}))
                if flow == "grid_to_bus_kwh_by_depot_slot":
                    actual += _sum_flows(plan.get("grid_to_bess_kwh_by_depot_slot", {}))
                if not _close(actual, float(week[metric])):
                    failures.append(f"{week['week']}: {metric} flow mismatch")
    return {
        "status": "PASS" if not failures else "FAIL",
        "scope": "file SHA, report/accounting cost, selected energy flows, recorded physical/accounting status",
        "not_checked": "full timetable/vehicle/SOC constraint reproduction, optimality, equipment approval",
        "week_count": len(manifest["weeks"]),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    result = verify_bundle(args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
