from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _json_dump(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_command(cmd: List[str], cwd: Path) -> Dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "elapsedSec": round(elapsed, 3),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _load_fast_metrics(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def benchmark_odpt(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    python_exe = args.python or sys.executable
    out_dir = Path(args.out_dir).resolve()
    results: Dict[str, Any] = {
        "mode": "benchmark-odpt",
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs": [],
    }

    if args.include_baseline:
        baseline_cmd = [
            python_exe,
            "catalog_update_app.py",
            "refresh",
            "odpt",
            "--force-refresh",
            "--ttl-sec",
            str(args.ttl_sec),
        ]
        results["runs"].append(
            {
                "label": "baseline-refresh-odpt",
                **_run_command(baseline_cmd, repo_root),
            }
        )

    fast_cmd = [
        python_exe,
        "tools/fast_catalog_ingest.py",
        "fetch-odpt",
        "--out-dir",
        str(out_dir),
        "--concurrency",
        str(args.concurrency),
        "--build-bundle",
    ]
    if args.resume:
        fast_cmd.append("--resume")
    if args.skip_stop_timetables:
        fast_cmd.append("--skip-stop-timetables")
    results["runs"].append({"label": "fast-fetch-odpt", **_run_command(fast_cmd, repo_root)})

    fast_metrics_path = out_dir / "benchmarks" / "fast_ingest_metrics.json"
    results["fastMetrics"] = _load_fast_metrics(fast_metrics_path)
    results["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _json_dump(Path(args.report_path).resolve(), results)
    print(f"[benchmark] report={Path(args.report_path).resolve()}")
    return 0


def benchmark_gtfs(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    python_exe = args.python or sys.executable
    results: Dict[str, Any] = {
        "mode": "benchmark-gtfs",
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs": [],
    }

    baseline_cmd = [
        python_exe,
        "catalog_update_app.py",
        "sync",
        "gtfs",
        "--scenario",
        args.scenario,
        "--resources",
        args.resources,
    ]
    if args.refresh:
        baseline_cmd.append("--refresh")
    if args.force_refresh:
        baseline_cmd.append("--force-refresh")
    results["runs"].append({"label": "baseline-sync-gtfs", **_run_command(baseline_cmd, repo_root)})

    fast_cmd = [
        python_exe,
        "tools/fast_catalog_ingest.py",
        "sync-gtfs",
        "--scenario",
        args.scenario,
        "--resources",
        args.resources,
    ]
    if args.refresh:
        fast_cmd.append("--refresh")
    if args.force_refresh:
        fast_cmd.append("--force-refresh")
    results["runs"].append({"label": "fast-sync-gtfs", **_run_command(fast_cmd, repo_root)})

    results["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _json_dump(Path(args.report_path).resolve(), results)
    print(f"[benchmark] report={Path(args.report_path).resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark catalog ingest routes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    odpt = subparsers.add_parser("odpt", help="Compare baseline and fast ODPT ingest")
    odpt.add_argument("--repo-root", default=".")
    odpt.add_argument("--python")
    odpt.add_argument("--out-dir", default="./data/catalog-fast")
    odpt.add_argument("--concurrency", type=int, default=32)
    odpt.add_argument("--ttl-sec", type=int, default=3600)
    odpt.add_argument("--resume", action="store_true")
    odpt.add_argument("--skip-stop-timetables", action="store_true")
    odpt.add_argument("--include-baseline", action="store_true")
    odpt.add_argument("--report-path", default="./outputs/benchmark/odpt_ingest_report.json")

    gtfs = subparsers.add_parser("gtfs", help="Compare baseline and fast GTFS sync")
    gtfs.add_argument("--repo-root", default=".")
    gtfs.add_argument("--python")
    gtfs.add_argument("--scenario", default="latest")
    gtfs.add_argument("--resources", default="all")
    gtfs.add_argument("--refresh", action="store_true")
    gtfs.add_argument("--force-refresh", action="store_true")
    gtfs.add_argument("--report-path", default="./outputs/benchmark/gtfs_sync_report.json")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "odpt":
        return benchmark_odpt(args)
    return benchmark_gtfs(args)


if __name__ == "__main__":
    raise SystemExit(main())
