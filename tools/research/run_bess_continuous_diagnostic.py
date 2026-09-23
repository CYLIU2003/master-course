"""Run a separate two-week BESS carryover diagnostic on the existing three-route scope.

Without --run this only prints the frozen design preview.  The run path uses
fresh Prepare for both weeks, then transfers accepted executed BESS inventory.
It is not a monthly-result rerun or evidence of a real depot import rating.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_exact_seasonal_campaign import (
    run_campaign,
    validate_carryover_weeks,
)
from bff.services.cluster.contracts import read_config, Worker
from bff.services.cluster.license_broker import LicenseBroker
from bff.services.cluster.local_resources import LocalResources
from bff.services.cluster.runner import process_identity
from bff.services.cluster.store import JobStore
from bff.store import output_paths
from src.gurobi_session import managed_gurobi_session
from src.solver_policy import solver_policy_scope, DEFAULT_PROFILE

SOURCE_DESIGN = ROOT / "config/shibu21_23_monthly_auxiliary_proof_budget_20260922.json"
WEEKS = ("2025-01-20", "2025-01-27")


@contextmanager
def shared_solver_capacity(*, threads: int):
    """Use the same durable local and WLS reservations as BFF execution."""
    config = read_config()
    root = Path(os.environ.get("MC_CLUSTER_DIR", output_paths.outputs_root() / "cluster"))
    store = JobStore(root)
    resources = LocalResources(store)
    broker = LicenseBroker(
        store, total=config.global_gurobi_slots, external=config.external_gurobi_slots
    )
    broker.reconcile_local_owners()
    resources.reconcile()
    worker = next((row for row in config.workers if row.transport == "local"),
                  Worker(id="local", name="local"))
    reservation = "local-bess-continuous-" + uuid4().hex
    if not resources.acquire(reservation, worker, threads):
        raise RuntimeError("Local solver capacity is occupied; diagnostic not started")
    admitted = False
    try:
        identity = f"{os.getpid()}:{process_identity(os.getpid())}"
        admitted = broker.acquire(reservation, owner_kind="local", owner_identity=identity)
        if not admitted:
            raise RuntimeError("Shared Gurobi capacity is occupied; diagnostic not started")
        yield reservation
    finally:
        if admitted:
            broker.finish(reservation, cooldown_seconds=330)
        resources.release(reservation)


def diagnostic_design(source: dict) -> dict:
    design = deepcopy(source)
    design.update(
        evaluation_weeks=list(WEEKS),
        require_balanced_monthly_weeks=False,
        week_selection_rule="Two adjacent Monday-Sunday weeks fixed before solving; 2025-01-20 through 2025-02-02",
        research_status="DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        design_status="TWO_WEEK_BESS_CARRYOVER_DIAGNOSTIC",
        continuity_scope="BESS executed terminal inventory only; BEV terminal remains return_to_initial",
        physical_import_limit_status="UNVERIFIED_PROVISIONAL_INPUT_NOT_REAL_EQUIPMENT_RATING",
    )
    if design.get("bess_terminal_soc_policy") != "minimum_only":
        raise ValueError("This diagnostic retains the declared minimum-only BESS policy")
    if design.get("diagnostic_stop_after_day_ahead") is True:
        raise ValueError("Carryover requires full rolling execution")
    validate_carryover_weeks(WEEKS, design)
    return design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="Start the fresh two-week diagnostic from a clean commit")
    args = parser.parse_args()
    design = diagnostic_design(json.loads(SOURCE_DESIGN.read_text(encoding="utf-8")))
    if not args.run:
        print(json.dumps({
            "status": "PREVIEW_ONLY", "weeks": list(WEEKS),
            "bess_carryover": True, "new_output": str(args.output.resolve()),
            "research_status": design["research_status"],
            "physical_import_limit_status": design["physical_import_limit_status"],
        }, ensure_ascii=False))
        return 0
    with shared_solver_capacity(threads=int(design["threads"])):
        with solver_policy_scope(DEFAULT_PROFILE):
            # One Env remains admitted across both weeks; each completed model
            # is disposed by solve_week before the next hourly model is built.
            with managed_gurobi_session(lambda: None, lambda _started: None):
                result = run_campaign(design, args.output, carry_bess=True)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
