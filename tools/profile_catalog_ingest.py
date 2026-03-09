from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import sys
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _json_dump(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_catalog(argv: List[str]) -> int:
    import catalog_update_app

    return catalog_update_app.main(argv)


def _run_fast(argv: List[str]) -> int:
    from tools import fast_catalog_ingest

    return fast_catalog_ingest.main(argv)


def profile_command(args: argparse.Namespace) -> int:
    if args.target == "catalog":
        runner = _run_catalog
    else:
        runner = _run_fast

    tracemalloc.start()
    profiler = cProfile.Profile()
    profiler.enable()
    rc = runner(args.argv)
    profiler.disable()
    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats_buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_buffer).sort_stats("cumulative")
    stats.print_stats(args.limit)

    top_allocs = []
    for stat in snapshot.statistics("lineno")[:20]:
        top_allocs.append(
            {
                "location": str(stat.traceback[0]),
                "sizeKb": round(stat.size / 1024.0, 2),
                "count": stat.count,
            }
        )

    report = {
        "target": args.target,
        "argv": args.argv,
        "returnCode": rc,
        "memory": {
            "currentKb": round(current / 1024.0, 2),
            "peakKb": round(peak / 1024.0, 2),
        },
        "topAllocations": top_allocs,
        "profileTextPath": str(Path(args.profile_text_path).resolve()),
    }

    Path(args.profile_text_path).write_text(stats_buffer.getvalue(), encoding="utf-8")
    _json_dump(Path(args.report_path).resolve(), report)
    print(f"[profile] report={Path(args.report_path).resolve()}")
    print(f"[profile] text={Path(args.profile_text_path).resolve()}")
    return rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile catalog ingest routes with cProfile + tracemalloc.")
    parser.add_argument("target", choices=["catalog", "fast"])
    parser.add_argument("argv", nargs=argparse.REMAINDER, help="Arguments forwarded to the target CLI")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--report-path", default="./outputs/profile/catalog_ingest_profile.json")
    parser.add_argument("--profile-text-path", default="./outputs/profile/catalog_ingest_profile.txt")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    forwarded = list(args.argv)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    args.argv = forwarded
    return profile_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
