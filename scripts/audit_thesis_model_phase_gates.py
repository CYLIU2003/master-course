"""Compose existing frontend/BFF evidence into a Phase 0--7 ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.services.optimization_run.thesis_phase_gate_audit import (  # noqa: E402
    build_thesis_phase_gate_audit,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--sensitivity-manifest",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--ablation-comparison", type=Path)
    parser.add_argument("--equation-map-audit", type=Path)
    parser.add_argument("--expected-trip-count", type=int)
    parser.add_argument(
        "--skip-prepared-source-rehash",
        action="store_true",
        help=(
            "Use the recorded prepared-input identity without re-reading the "
            "source file. Prefer the default re-hash for formal audits."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "<run-dir>/thesis_model_phase_gate_audit.json."
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = build_thesis_phase_gate_audit(
        run_dir=args.run_dir,
        sensitivity_manifest_paths=args.sensitivity_manifest,
        ablation_comparison_path=args.ablation_comparison,
        equation_map_audit_path=args.equation_map_audit,
        expected_trip_count=args.expected_trip_count,
        verify_prepared_source=not args.skip_prepared_source_rehash,
    )
    output = args.output or (
        args.run_dir / "thesis_model_phase_gate_audit.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
