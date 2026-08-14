"""Build a hashed, human-readable bounded electric-oracle certificate."""

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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.optimization.validation.small_electric_oracle_benchmark import (  # noqa: E402
    assert_certificate_integrity,
    build_small_electric_oracle_certificate,
    certificate_case_rows,
)


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _git_provenance(*, require_clean_git: bool) -> dict[str, Any]:
    sha = _git_output("rev-parse", "HEAD")
    dirty_rows = [
        row for row in _git_output("status", "--porcelain").splitlines() if row
    ]
    if require_clean_git and dirty_rows:
        raise RuntimeError(
            "bounded electric-oracle evidence requires a clean Git worktree; "
            "commit or stash changes before running"
        )
    return {
        "git_sha": sha,
        "git_dirty": bool(dirty_rows),
        "git_dirty_rows": dirty_rows,
    }


def write_certificate_bundle(
    output_dir: Path,
    certificate: Mapping[str, Any],
    *,
    git_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Write JSON, CSV, Markdown, and a file-hash manifest."""

    assert_certificate_integrity(
        certificate,
        require_integrated_gurobi=bool(
            certificate.get("integrated_gurobi_comparison_required", False)
        ),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    certificate_path = output_dir / "small_electric_oracle_certificate.json"
    cases_path = output_dir / "small_electric_oracle_cases.csv"
    markdown_path = output_dir / "small_electric_oracle_certificate.md"

    certificate_path.write_text(
        json.dumps(certificate, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    rows = certificate_case_rows(certificate)
    fieldnames = list(rows[0]) if rows else []
    with cases_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    markdown_path.write_text(
        _markdown_report(certificate, rows),
        encoding="utf-8",
    )

    artifacts = [certificate_path, cases_path, markdown_path]
    manifest: dict[str, Any] = {
        "schema_version": "small_electric_oracle_bundle_manifest_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_git": dict(git_provenance),
        "certificate_payload_sha256": certificate["payload_sha256"],
        "claim_scope": certificate["claim_scope"],
        "research_conclusion_eligible": False,
        "certificate_status": certificate["status"],
        "integrated_gurobi_comparison_status": certificate[
            "integrated_gurobi_comparison_status"
        ],
        "artifacts": [
            {
                "path": path.name,
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in artifacts
        ],
    }
    unsigned = _canonical_json_bytes(manifest)
    manifest["payload_sha256"] = sha256(unsigned).hexdigest()
    manifest_path = output_dir / "small_electric_oracle_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return {
        **manifest,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_file_sha256": _sha256_file(manifest_path),
    }


def _markdown_report(
    certificate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> str:
    coefficients = dict(certificate.get("coefficients") or {})
    lines = [
        "# Bounded electric exact-oracle verification",
        "",
        f"- Status: `{certificate['status']}`",
        f"- Claim scope: `{certificate['claim_scope']}`",
        "- Formal/full-network run substitute: `false`",
        "- Research conclusion eligible: `false`",
        (
            "- Hand break-even grid tariff: "
            f"{float(coefficients['hand_break_even_grid_price_jpy_per_kwh']):.6f} "
            "JPY/kWh"
        ),
        f"- Certificate payload SHA-256: `{certificate['payload_sha256']}`",
        "",
        "## Cases",
        "",
        "| Case | Status | Tariff | Selected | Trips | Ports | Enumerated | Dispatch feasible | Energy feasible | Cost JPY | Integrated match |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        tariff = row.get("grid_price_jpy_per_kwh")
        cost = row.get("canonical_operating_cost_jpy")
        lines.append(
            "| {case_id} | {status} | {tariff} | {powertrain} | {trips} | "
            "{ports} | {enumerated} | {dispatch} | {energy} | {cost} | "
            "{match} |".format(
                case_id=row.get("case_id", ""),
                status=row.get("status", ""),
                tariff="" if tariff is None else f"{float(tariff):.3f}",
                powertrain=row.get("selected_powertrain") or "",
                trips=row.get("trip_count", ""),
                ports=row.get("charger_port_count", ""),
                enumerated=row.get("enumerated_assignment_count", ""),
                dispatch=row.get("dispatch_feasible_assignment_count", ""),
                energy=row.get("energy_feasible_assignment_count", ""),
                cost="" if cost is None else f"{float(cost):.6f}",
                match=(
                    "N/A"
                    if row.get("integrated_milp_match") is None
                    else str(bool(row.get("integrated_milp_match"))).lower()
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            *[
                f"- `{name}`: `{str(value).lower() if value is not None else 'not_run'}`"
                for name, value in dict(certificate.get("checks") or {}).items()
            ],
            "",
            "## Interpretation",
            "",
            (
                "This bundle verifies only the documented bounded grid-only "
                "formulation. It cannot certify the 264-trip network, positive "
                "PV/BESS operation, Rolling execution, or thesis-level effect sizes."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the certificate bundle.",
    )
    parser.add_argument(
        "--allow-dirty-git",
        action="store_true",
        help="Diagnostic development only; the manifest will retain git_dirty=true.",
    )
    parser.add_argument(
        "--skip-integrated-gurobi",
        action="store_true",
        help="Unit diagnostic only; omits production integrated-MILP agreement.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    provenance = _git_provenance(require_clean_git=not args.allow_dirty_git)
    certificate = build_small_electric_oracle_certificate(
        require_integrated_gurobi=not args.skip_integrated_gurobi
    )
    manifest = write_certificate_bundle(
        args.output_dir.resolve(),
        certificate,
        git_provenance=provenance,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
