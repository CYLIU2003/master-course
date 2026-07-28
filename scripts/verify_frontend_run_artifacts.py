"""Verify that a completed frontend optimization run has all required outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bff.services.optimization_run.artifact_completeness import (  # noqa: E402
    persist_frontend_run_artifact_audit,
)
from bff.services.optimization_run.rolling_chain import (  # noqa: E402
    frontend_rolling_is_required,
)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return dict(loaded) if isinstance(loaded, dict) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit a frontend optimization run and write "
            "artifact_completeness.json."
        )
    )
    parser.add_argument("run_dir", type=Path)
    research = parser.add_mutually_exclusive_group()
    research.add_argument(
        "--research-run",
        action="store_true",
        help="Require research input-provenance artifacts.",
    )
    research.add_argument(
        "--non-research-run",
        action="store_true",
        help="Do not require research input-provenance artifacts.",
    )
    rolling = parser.add_mutually_exclusive_group()
    rolling.add_argument(
        "--require-rolling",
        action="store_true",
        help="Require the complete rolling chain and physical validation.",
    )
    rolling.add_argument(
        "--day-ahead-only",
        action="store_true",
        help="Audit an explicitly exploratory day-ahead-only run.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    run_dir = args.run_dir.resolve()
    manifest = _load_json_object(run_dir / "run_manifest.json")
    claim_scope = dict(manifest.get("research_claim_scope") or {})

    if args.research_run:
        research_run = True
    elif args.non_research_run:
        research_run = False
    else:
        research_run = bool(manifest.get("research_run", False))

    if args.require_rolling:
        require_rolling = True
    elif args.day_ahead_only:
        require_rolling = False
    else:
        run_profile = str(claim_scope.get("run_profile") or "").strip()
        require_rolling = (
            frontend_rolling_is_required(run_profile)
            if run_profile
            else (run_dir / "rolling_hourly_chain").is_dir()
        )

    audit = persist_frontend_run_artifact_audit(
        run_dir,
        research_run=research_run,
        require_rolling=require_rolling,
    )
    print(
        json.dumps(
            {
                "status": audit.get("status"),
                "run_dir": audit.get("run_dir"),
                "research_run": audit.get("research_run"),
                "rolling_required": audit.get("rolling_required"),
                "required_artifact_count": audit.get(
                    "required_artifact_count"
                ),
                "verified_artifact_count": audit.get(
                    "verified_artifact_count"
                ),
                "total_file_count": audit.get("total_file_count"),
                "missing_artifacts": audit.get("missing_artifacts"),
                "empty_artifacts": audit.get("empty_artifacts"),
                "invalid_json_artifacts": audit.get(
                    "invalid_json_artifacts"
                ),
                "content_errors": audit.get("content_errors"),
                "workbook_errors": audit.get("workbook_errors"),
                "run_manifest_errors": audit.get("run_manifest_errors"),
                "artifact": str(run_dir / "artifact_completeness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit.get("accepted") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
