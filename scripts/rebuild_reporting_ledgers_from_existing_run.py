"""Backfill CLI for canonical reporting artifacts.

This script copies existing optimization run directories and invokes the shared
reporting finalizer on the copy. It never modifies the input run directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.reporting.canonical_reporting import rebuild_reporting_artifacts_to_output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy an existing run and rebuild reporting ledgers only."
    )
    single = parser.add_argument_group("single run")
    single.add_argument("--input-run-dir", type=Path)
    single.add_argument("--output-run-dir", type=Path)

    batch = parser.add_argument_group("batch runs")
    batch.add_argument("--input-root", type=Path)
    batch.add_argument("--output-root", type=Path)
    batch.add_argument("--run-ids", nargs="+")

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace output run directories if they already exist. Never modifies input dirs.",
    )
    return parser.parse_args()


def requested_runs(args: argparse.Namespace) -> list[tuple[Path, Path]]:
    single = args.input_run_dir is not None or args.output_run_dir is not None
    batch = args.input_root is not None or args.output_root is not None or args.run_ids is not None
    if single and batch:
        raise ValueError(
            "Use either --input-run-dir/--output-run-dir or --input-root/--output-root/--run-ids, not both"
        )
    if single:
        if args.input_run_dir is None or args.output_run_dir is None:
            raise ValueError("--input-run-dir and --output-run-dir are both required for single-run mode")
        return [(args.input_run_dir, args.output_run_dir)]
    if args.input_root is None or args.output_root is None or not args.run_ids:
        raise ValueError("batch mode requires --input-root, --output-root, and --run-ids")
    return [(args.input_root / run_id, args.output_root / run_id) for run_id in args.run_ids]


def main() -> int:
    args = parse_args()
    logs = []
    for input_dir, output_dir in requested_runs(args):
        logs.append(
            rebuild_reporting_artifacts_to_output_dir(
                input_dir=input_dir,
                output_dir=output_dir,
                overwrite=args.overwrite,
            )
        )
    print(json.dumps({"rebuilt_runs": logs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
