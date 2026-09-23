"""Freeze the 12 diagnostic weeks' original files into a local review bundle.

The archive may contain nonpublic timetable and fleet data. It stays under
``output/`` and is not uploaded or emailed by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.optimization.common.fleet_contract import resolve_scenario_fleet_contract

from tools.research.verify_monthly_evidence_bundle import verify_bundle


KINDS = (
    "case_summary", "executed_day_accounting", "executed_plan",
    "physical_validation", "prepared_input",
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(report_path: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(f"Evidence bundle already exists; choose a new --output: {destination}")
    report_raw = report_path.read_bytes()
    report = json.loads(report_raw)
    weeks = report.get("weeks", [])
    if len(weeks) != 12 or report.get("completed_count") != 12:
        raise ValueError("expected one completed report row for each of 12 months")
    if sorted(row["month"] for row in weeks) != list(range(1, 13)):
        raise ValueError("month labels are missing or duplicated")
    source_sha = report["source_git_sha"]
    subprocess.run(["git", "cat-file", "-e", f"{source_sha}^{{commit}}"], cwd=ROOT, check=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "schema_version": "monthly_evidence_bundle_v1",
        "claim_status": report.get("research_status"),
        "report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "source_git_sha": source_sha,
        "weeks": [],
    }
    canonical_fleet: dict | None = None
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        archive_path = Path(temporary) / "frozen_source.tar"
        with archive_path.open("wb") as output:
            subprocess.run(["git", "archive", "--format=tar", source_sha], cwd=ROOT, stdout=output, check=True)
        manifest["frozen_source"] = {
            "relative_path": "frozen_source.tar",
            "sha256": _digest(archive_path),
        }
        pending = Path(temporary) / "bundle.zip"
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.writestr("monthly_report.json", report_raw)
            bundle.write(archive_path, "frozen_source.tar")
            verifier = ROOT / "tools/research/verify_monthly_evidence_bundle.py"
            bundle.write(verifier, "verify_monthly_evidence_bundle.py")
            manifest["verifier_sha256"] = _digest(verifier)
            continuity_checker = ROOT / "tools/research/check_bess_week_continuity.py"
            bundle.write(continuity_checker, "check_bess_week_continuity.py")
            manifest["continuity_checker_sha256"] = _digest(continuity_checker)
            audit = report.get("independent_audit") or {}
            if audit:
                audit_path = Path(audit["path"])
                if _digest(audit_path) != audit["sha256"]:
                    raise ValueError("independent audit SHA mismatch")
                bundle.write(audit_path, "independent_audit.json")
                manifest["independent_audit_sha256"] = audit["sha256"]
            for row in weeks:
                week_id = row["week"]
                week_manifest = {"month": row["month"], "week": week_id, "files": {}}
                for kind in KINDS:
                    evidence = row["source_evidence"][kind]
                    original = Path(evidence["path"])
                    digest = _digest(original)
                    if digest != evidence["sha256"]:
                        raise ValueError(f"{week_id} {kind}: original SHA mismatch")
                    relative = f"weeks/{week_id}/{kind}.json"
                    bundle.write(original, relative)
                    week_manifest["files"][kind] = {"relative_path": relative, "sha256": digest}
                    if kind == "prepared_input":
                        prepared = json.loads(original.read_text(encoding="utf-8"))
                        contract = resolve_scenario_fleet_contract(
                            prepared,
                            selected_depot_ids=tuple(prepared["depot_ids"]),
                            research_run=True,
                        )
                        if contract.validation_status != "OK":
                            raise ValueError(f"{week_id}: fleet candidate validation failed: {contract.errors}")
                        resolved = contract.to_dict()
                        if canonical_fleet is None:
                            canonical_fleet = resolved
                        elif contract.fleet_contract_hash != canonical_fleet["fleet_contract_hash"]:
                            raise ValueError(f"{week_id}: fleet contract differs from first week")
                        week_manifest["fleet_contract_hash"] = contract.fleet_contract_hash
                manifest["weeks"].append(week_manifest)
            if canonical_fleet is None:
                raise ValueError("no fleet candidate resolved")
            canonical_fleet["approval_status"] = "CANDIDATE_NOT_APPROVED"
            canonical_fleet["approval_owner"] = None
            canonical_fleet["source_prepared_input_sha256"] = manifest["weeks"][0]["files"]["prepared_input"]["sha256"]
            fleet_raw = json.dumps(canonical_fleet, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            bundle.writestr("fleet_candidate.json", fleet_raw)
            manifest["fleet_candidate_sha256"] = hashlib.sha256(fleet_raw).hexdigest()
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
            bundle.writestr(
                "README.txt",
                "Run: python verify_monthly_evidence_bundle.py bundle.zip\n"
                "BESS: python check_bess_week_continuity.py bundle.zip\n"
                "Status: historical 12-week diagnostic; formal research acceptance remains blocked.\n"
                "The verifier checks hashes and selected accounting/flow identities, not every physical constraint.\n"
                "The fleet is a candidate. No owner approval is recorded.\n"
                "The original files may contain restricted timetable and fleet data.\n",
            )
        verdict = verify_bundle(pending)
        if verdict["status"] != "PASS":
            raise ValueError(f"portable verification failed: {verdict['failures']}")
        pending.replace(destination)
        (destination.parent / "fleet_candidate.json").write_bytes(fleet_raw)
        (destination.parent / "verification.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "bundle": str(destination), "sha256": _digest(destination),
            "size_bytes": destination.stat().st_size,
            "fleet_contract_hash": canonical_fleet["fleet_contract_hash"],
            "verification": verdict,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "docs/notes/SHIBU21_23_MONTHLY_AUXILIARY_PROOF_BUDGET_RESULTS_20260922.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/research_review_bundle_20260923/monthly_evidence_bundle.zip")
    args = parser.parse_args()
    print(json.dumps(export(args.report, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
