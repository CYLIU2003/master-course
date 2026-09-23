"""One-shot fleet checks and optional solver-free dispatch; no AI or daemon."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bff.services.cluster.contracts import RESERVED, TERMINAL, read_config
from bff.services.cluster.scheduler import Scheduler
from bff.services.cluster.store import JobStore, now
from bff.services.cluster.worker_monitor import WorkerMonitor
from bff.services.cluster.worker_registry import WorkerRegistry
from bff.store.output_paths import outputs_root


def check_fleet(monitor: WorkerMonitor, workers: list) -> list[dict]:
    """Use the same readiness contracts as the UI, with one probe per PC."""
    monitor.refresh_controller()
    monitor.refresh_network()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(monitor.probe, workers))
    # Keep network observations fresh after slow/missing Python installations.
    monitor.refresh_network()
    return [monitor.registry.view(worker, [], monitor.controller) for worker in workers]


def run_diagnostics(scheduler: Scheduler, views: list[dict], timeout: float) -> list[dict]:
    """Dispatch only newly requested diagnostics; leave unrelated queued jobs alone."""
    job_ids = {
        scheduler.enqueue("diagnostic", {}, view["id"])["id"]
        for view in views if view["can_run_diagnostic"]
    }
    deadline = time.monotonic() + timeout
    while job_ids and time.monotonic() < deadline:
        scheduler.tick(job_ids=job_ids)
        rows = [scheduler.store.get(job_id) for job_id in job_ids]
        if all(row["state"] in TERMINAL | {"LOST"} for row in rows):
            break
        scheduler.stop_event.wait(1)
    scheduler.stop_event.set()
    for job_id in job_ids:
        scheduler.store.transition(job_id, "CANCELLED", expected={"QUEUED"},
                                   error="One-shot diagnostic deadline; no worker started")
        scheduler.store.transition(job_id, "LOST", expected=RESERVED - {"LOST"},
                                   error="One-shot diagnostic deadline; reconcile the existing ID")
    return [scheduler.store.get(job_id) for job_id in sorted(job_ids)]


def build_report(views: list[dict], jobs: list[dict], *, diagnostics: bool) -> dict:
    completed = {row["worker_id"] for row in jobs if row["state"] == "COMPLETED"}
    remote_completed = [view["id"] for view in views
                        if view["transport"] == "ssh" and view["id"] in completed]
    ready = all(view["can_run_diagnostic"] for view in views) and bool(views)
    passed = ready and (not diagnostics or len(completed) == len(views))
    return {"checked_at_utc": now(), "status": "PASS" if passed else "BLOCKED",
            "mode": "diagnostics" if diagnostics else "probe_only",
            "workers": views, "jobs": jobs, "ssh_diagnostics_completed": remote_completed,
            "research_approval": "NOT_GRANTED_BY_CLUSTER",
            "solver_started": False, "background_monitor_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--worker", action="append", default=[], help="Registered worker ID (repeatable)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--diagnostics", action="store_true", help="Run solver-free jobs via the exclusive existing queue")
    parser.add_argument("--timeout", type=float, default=180, help="Diagnostic completion deadline in seconds")
    args = parser.parse_args()
    if not 5 <= args.timeout <= 1800:
        parser.error("--timeout must be between 5 and 1800 seconds")
    if args.config:
        os.environ["MC_CLUSTER_CONFIG"] = str(args.config.resolve())
    config = read_config()
    unknown = set(args.worker) - {worker.id for worker in config.workers}
    if unknown:
        parser.error("Unknown worker IDs: " + ", ".join(sorted(unknown)))
    selected = [worker for worker in config.workers if not args.worker or worker.id in args.worker]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or ROOT / "output" / "cluster-checks" / stamp
    output.mkdir(parents=True, exist_ok=False)
    scheduler = None
    try:
        if args.diagnostics:
            # Never create a competing controller beside an active BFF or separate
            # queue to bypass its worker/license reservations.
            queue = Path(os.environ.get("MC_CLUSTER_DIR", outputs_root() / "cluster"))
            scheduler = Scheduler(queue, config)
            monitor = scheduler.monitor
        else:
            store = JobStore(output / "observations")
            monitor = WorkerMonitor(WorkerRegistry(store, config.workers), config.workers)
        views = check_fleet(monitor, selected)
        jobs = run_diagnostics(scheduler, views, args.timeout) if scheduler else []
        report = build_report(views, jobs, diagnostics=args.diagnostics)
        report["license_capacity"] = {
            "total": config.global_gurobi_slots, "external_reserved": config.external_gurobi_slots,
            "cluster_capacity": config.global_gurobi_slots - config.external_gurobi_slots,
        }
    except (OSError, RuntimeError, ValueError) as exc:
        report = {"checked_at_utc": now(), "status": "BLOCKED", "error": str(exc),
                  "background_monitor_started": False, "solver_started": False}
    finally:
        if scheduler:
            scheduler.stop_event.set()
            scheduler.controller_lock.close()
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for view in report.get("workers", []):
        print(f"{view['id']}: {view['status']} | {view.get('last_error') or '; '.join(view['readiness_reasons'])}")
    print(json.dumps({"status": report["status"], "report": str(output / "report.json"),
                      "ssh_diagnostics_completed": report.get("ssh_diagnostics_completed", []),
                      "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
