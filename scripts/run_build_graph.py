"""Run build_graph for a scenario as a standalone background script.

Usage:
  python scripts/run_build_graph.py --scenario <scenario_id>

The script will create a job entry and run the internal graph build synchronously.
It prints the created job id to stdout so callers can track it.
"""
import argparse
import traceback

from bff.store import job_store
from bff.routers import graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args()
    scenario_id = args.scenario

    job = job_store.create_job()
    print(job.job_id, flush=True)
    try:
        graph._run_build_graph(scenario_id, job.job_id, service_id=None, depot_id=None)
    except Exception:
        # ensure job updated
        job_store.update_job(job.job_id, status="failed", message="build_graph raised exception", error=traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
