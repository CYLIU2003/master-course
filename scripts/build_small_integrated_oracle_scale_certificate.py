"""Run and certify the 8/12/24-trip integrated-oracle scale series.

Each trip count is executed in a fresh Python process through the existing
weather-aware small-oracle audit.  The certificate is fail-closed: every
Phase-4 case must be an exact canonical-actual-cost optimum, and every Phase-3
case must be feasible and complete before a bounded comparison is accepted.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "small_integrated_oracle_scale_certificate_v1"
DEFAULT_TRIP_COUNTS = (8, 12, 24)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True
    ).strip()


def normalize_trip_counts(values: Sequence[int]) -> tuple[int, ...]:
    counts = tuple(int(value) for value in values)
    if not counts:
        raise ValueError("at least one trip count is required")
    if any(value <= 0 for value in counts):
        raise ValueError("trip counts must be positive")
    if len(set(counts)) != len(counts):
        raise ValueError("trip counts must be unique")
    return counts


def _primary_case(
    audit: Mapping[str, Any], phase: str
) -> Mapping[str, Any] | None:
    for case in audit.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        if (
            case.get("analysis_label") == "primary"
            and int(case.get("timestep_min") or 0) == 15
            and case.get("phase") == phase
        ):
            return case
    return None


def _result_row(result: Mapping[str, Any]) -> dict[str, Any]:
    trip_count = int(result["trip_count"])
    audit = result.get("audit")
    blockers: list[str] = []
    if result.get("return_code") != 0:
        blockers.append("child_audit_nonzero_exit")
    if not isinstance(audit, Mapping):
        blockers.append("audit_missing_or_invalid")
        return {
            "trip_count": trip_count,
            "verified": False,
            "blockers": blockers,
            "return_code": result.get("return_code"),
            "audit_path": result.get("audit_path"),
            "audit_sha256": result.get("audit_sha256"),
            "log_path": result.get("log_path"),
            "command": list(result.get("command") or ()),
        }

    if int(audit.get("trip_count") or 0) != trip_count:
        blockers.append("trip_count_mismatch")
    comparison = audit.get("primary_comparison")
    if not isinstance(comparison, Mapping):
        blockers.append("primary_comparison_missing")
        comparison = {}
    if comparison.get("integrated_exact_oracle_eligible") is not True:
        blockers.append("integrated_exact_oracle_not_eligible")
    if comparison.get("two_stage_comparison_available") is not True:
        blockers.append("two_stage_comparison_unavailable")
    if comparison.get("comparison_lower_bound_consistent") is not True:
        blockers.append("comparison_lower_bound_inconsistent")

    phase3 = _primary_case(audit, "phase3_two_stage")
    phase4 = _primary_case(audit, "phase4_integrated")
    if phase3 is None:
        blockers.append("phase3_primary_case_missing")
    if phase4 is None:
        blockers.append("phase4_primary_case_missing")
    for label, case in (("phase3", phase3), ("phase4", phase4)):
        if case is None:
            continue
        if not bool(case.get("feasible")) or int(
            case.get("trip_count_unserved") or 0
        ) != 0:
            blockers.append(f"{label}_not_feasible_and_complete")
    if phase4 is not None:
        for field in (
            "integrated_actual_cost_objective_requested",
            "integrated_actual_cost_contract_applied",
            "objective_is_actual_cost",
            "objective_matches_accounting",
            "ev_energy_inventory_balanced",
        ):
            if phase4.get(field) is not True:
                blockers.append(f"phase4_{field}_failed")

    return {
        "trip_count": trip_count,
        "verified": not blockers,
        "blockers": blockers,
        "return_code": result.get("return_code"),
        "audit_path": result.get("audit_path"),
        "audit_sha256": result.get("audit_sha256"),
        "log_path": result.get("log_path"),
        "command": list(result.get("command") or ()),
        "integrated_accounted_total_cost_jpy": comparison.get(
            "integrated_accounted_total_cost_jpy"
        ),
        "two_stage_accounted_total_cost_jpy": comparison.get(
            "two_stage_accounted_total_cost_jpy"
        ),
        "two_stage_minus_integrated_cost_jpy": comparison.get(
            "two_stage_minus_integrated_cost_jpy"
        ),
        "two_stage_approx_gap_identifiable": comparison.get(
            "two_stage_approx_gap_identifiable"
        ),
        "two_stage_approx_gap_ratio": comparison.get(
            "two_stage_approx_gap_ratio"
        ),
        "two_stage_approx_gap_status": comparison.get("two_stage_approx_gap_status"),
        "used_vehicle_count_delta": comparison.get(
            "used_vehicle_count_delta"
        ),
        "used_vehicle_type_mix_matches": comparison.get(
            "used_vehicle_type_mix_matches"
        ),
        "served_trip_type_mix_matches": comparison.get(
            "served_trip_type_mix_matches"
        ),
        "assignment_powertrain_hash_matches": comparison.get(
            "assignment_powertrain_hash_matches"
        ),
        "phase3_elapsed_seconds": (
            phase3.get("elapsed_seconds") if phase3 is not None else None
        ),
        "phase4_elapsed_seconds": (
            phase4.get("elapsed_seconds") if phase4 is not None else None
        ),
        "phase4_solver_status": (
            phase4.get("solver_status") if phase4 is not None else None
        ),
        "phase4_final_gap_ratio": (
            phase4.get("final_gap_ratio") if phase4 is not None else None
        ),
    }


def build_scale_certificate(
    results: Sequence[Mapping[str, Any]],
    *,
    expected_trip_counts: Sequence[int],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    expected = normalize_trip_counts(expected_trip_counts)
    rows = sorted(
        (_result_row(result) for result in results),
        key=lambda row: row["trip_count"],
    )
    observed = tuple(row["trip_count"] for row in rows)
    global_blockers: list[str] = []
    if observed != tuple(sorted(expected)):
        global_blockers.append("trip_count_series_incomplete_or_unordered")
    for row in rows:
        global_blockers.extend(
            f"trip_{row['trip_count']}:{blocker}" for blocker in row["blockers"]
        )
    identifiable_gap_ratios = [
        float(row["two_stage_approx_gap_ratio"])
        for row in rows
        if row.get("two_stage_approx_gap_identifiable") is True
        and row.get("two_stage_approx_gap_ratio") is not None
    ]
    verified = not global_blockers and len(rows) == len(expected)
    certificate: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "VERIFIED_BOUNDED_SMALL_INSTANCES" if verified else "BLOCKED",
        "research_conclusion_eligible": verified,
        "formal_full_network_optimality_substitute": False,
        "scope_warning": (
            "Deterministic day-spanning small instances only; this certificate "
            "does not establish 264-trip global optimality or runtime performance."
        ),
        "comparison_semantics": (
            "Phase 3 feasible canonical accounting cost minus exact Phase 4 "
            "integrated canonical-actual-cost optimum"
        ),
        "expected_trip_counts": list(expected),
        "verified_trip_counts": [
            row["trip_count"] for row in rows if row["verified"]
        ],
        "all_sizes_verified": verified,
        "blockers": global_blockers,
        "approx_gap_definition": (
            "(Phase 3 canonical accounting cost - Phase 4 exact canonical "
            "actual-cost optimum) / abs(Phase 4 cost); undefined when the "
            "exact reference cost is within the numerical cost tolerance"
        ),
        "approx_gap_identifiable_trip_counts": [
            row["trip_count"]
            for row in rows
            if row.get("two_stage_approx_gap_identifiable") is True
        ],
        "approx_gap_not_identifiable_trip_counts": [
            row["trip_count"]
            for row in rows
            if row.get("two_stage_approx_gap_identifiable") is not True
        ],
        "maximum_two_stage_approx_gap_ratio": (
            max(identifiable_gap_ratios) if identifiable_gap_ratios else None
        ),
        "mean_two_stage_approx_gap_ratio": (
            sum(identifiable_gap_ratios) / len(identifiable_gap_ratios)
            if identifiable_gap_ratios
            else None
        ),
        "provenance": dict(provenance),
        "sizes": rows,
    }
    certificate["payload_sha256"] = _canonical_sha256(certificate)
    return certificate


def _write_certificate(output_dir: Path, certificate: Mapping[str, Any]) -> None:
    json_path = output_dir / "scale_certificate.json"
    csv_path = output_dir / "scale_results.csv"
    markdown_path = output_dir / "scale_certificate.md"
    json_path.write_text(
        json.dumps(certificate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = list(certificate.get("sizes", []))
    csv_fields = (
        "trip_count",
        "verified",
        "integrated_accounted_total_cost_jpy",
        "two_stage_accounted_total_cost_jpy",
        "two_stage_minus_integrated_cost_jpy",
        "two_stage_approx_gap_identifiable",
        "two_stage_approx_gap_ratio",
        "two_stage_approx_gap_status",
        "used_vehicle_count_delta",
        "used_vehicle_type_mix_matches",
        "served_trip_type_mix_matches",
        "assignment_powertrain_hash_matches",
        "phase3_elapsed_seconds",
        "phase4_elapsed_seconds",
        "phase4_solver_status",
        "phase4_final_gap_ratio",
        "blockers",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["blockers"] = ";".join(row.get("blockers", []))
            writer.writerow(csv_row)
    lines = [
        "# Small integrated-oracle scale certificate",
        "",
        f"- status: `{certificate['status']}`",
        f"- all sizes verified: `{certificate['all_sizes_verified']}`",
        "- scope: bounded deterministic small instances; not a 264-trip proof",
        "",
        "| Trips | Verified | Phase 3 cost | Integrated optimum | Approx. gap | Phase 4 status |",
        "|---:|:---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {trip_count} | {verified} | {two_stage} | {integrated} | "
            "{gap} | {status} |".format(
                trip_count=row.get("trip_count"),
                verified=row.get("verified"),
                two_stage=row.get("two_stage_accounted_total_cost_jpy"),
                integrated=row.get("integrated_accounted_total_cost_jpy"),
                gap=row.get("two_stage_approx_gap_ratio"),
                status=row.get("phase4_solver_status"),
            )
        )
    if certificate.get("blockers"):
        lines.extend(("", "## Blockers", ""))
        lines.extend(f"- `{blocker}`" for blocker in certificate["blockers"])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    trip_counts = normalize_trip_counts(args.trip_counts)
    git_sha_before = _git_output("rev-parse", "HEAD")
    dirty_before = _git_output("status", "--porcelain")
    if not git_sha_before:
        raise RuntimeError("small-oracle scale run requires a non-empty Git SHA")
    if dirty_before:
        raise RuntimeError(
            "small-oracle scale run requires a clean worktree:\n" + dirty_before
        )

    prepared_path = (
        REPO_ROOT
        / "output"
        / "prepared_inputs"
        / args.scenario_id
        / f"{args.prepared_input_id}.json"
    )
    if not prepared_path.is_file():
        raise FileNotFoundError(f"canonical prepared input not found: {prepared_path}")
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    audit_script = REPO_ROOT / "scripts" / "audit_small_integrated_weather_milp.py"
    for index, trip_count in enumerate(trip_counts, start=1):
        case_dir = output_dir / f"trips_{trip_count:02d}"
        case_dir.mkdir(parents=True, exist_ok=False)
        audit_path = case_dir / "audit.json"
        log_path = case_dir / "run.log"
        command = [
            sys.executable,
            str(audit_script),
            "--scenario-id",
            args.scenario_id,
            "--prepared-input-id",
            args.prepared_input_id,
            "--output",
            str(audit_path),
            "--depot-id",
            args.depot_id,
            "--service-id",
            args.service_id,
            "--trip-count",
            str(trip_count),
            "--vehicles-per-type",
            str(args.vehicles_per_type),
            "--time-limit-sec",
            str(args.time_limit_sec),
            "--random-seed",
            str(args.random_seed),
            "--skip-five-minute",
        ]
        print(f"[{index}/{len(trip_counts)}] running {trip_count}-trip oracle", flush=True)
        with log_path.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        audit: Mapping[str, Any] | None = None
        audit_hash: str | None = None
        if audit_path.is_file():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit_hash = _file_sha256(audit_path)
        results.append(
            {
                "trip_count": trip_count,
                "return_code": completed.returncode,
                "command": command,
                "audit_path": str(audit_path),
                "audit_sha256": audit_hash,
                "log_path": str(log_path),
                "audit": audit,
            }
        )

    git_sha_after = _git_output("rev-parse", "HEAD")
    dirty_after = _git_output("status", "--porcelain")
    provenance = {
        "git_sha_before": git_sha_before,
        "git_sha_after": git_sha_after,
        "git_dirty_before": False,
        "git_dirty_after": bool(dirty_after),
        "prepared_input_path": str(prepared_path.resolve()),
        "prepared_input_sha256": _file_sha256(prepared_path),
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "depot_id": args.depot_id,
        "service_id": args.service_id,
        "vehicles_per_type": args.vehicles_per_type,
        "time_limit_sec_per_phase": args.time_limit_sec,
        "random_seed": args.random_seed,
        "python_version": sys.version,
        "python_executable": sys.executable,
    }
    if git_sha_before != git_sha_after or dirty_after:
        for result in results:
            result["return_code"] = result.get("return_code") or 90
    certificate = build_scale_certificate(
        results,
        expected_trip_counts=trip_counts,
        provenance=provenance,
    )
    _write_certificate(output_dir, certificate)
    artifact_paths = sorted(
        path for path in output_dir.rglob("*") if path.is_file()
    )
    manifest = {
        "schema_version": "small_integrated_oracle_scale_bundle_v1",
        "certificate_payload_sha256": certificate["payload_sha256"],
        "status": certificate["status"],
        "artifacts": [
            {
                "path": str(path.relative_to(output_dir)).replace("\\", "/"),
                "sha256": _file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in artifact_paths
        ],
    }
    manifest["payload_sha256"] = _canonical_sha256(manifest)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(certificate, ensure_ascii=False, indent=2), flush=True)
    return 0 if certificate["all_sizes_verified"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--trip-counts", type=int, nargs="+", default=DEFAULT_TRIP_COUNTS
    )
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--vehicles-per-type", type=int, default=5)
    parser.add_argument("--time-limit-sec", type=int, default=300)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
