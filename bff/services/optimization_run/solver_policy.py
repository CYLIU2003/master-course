"""Bind execution policy to prepared inputs and persist usage through reporting."""
from __future__ import annotations

from dataclasses import asdict
from functools import wraps
from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import json
import os
from pathlib import Path
import time

from src.solver_policy import (
    DEFAULT_PROFILE, NO_GUROBI_PROFILE, SolverPolicyViolation,
    solver_policy_scope, validate_no_gurobi_inputs,
)

_remote_admission: ContextVar[str | None] = ContextVar("remote_license_admission", default=None)


@contextmanager
def admitted_cluster_attempt(manifest: dict):
    if manifest.get("requires_gurobi") and manifest.get("gurobi_reservation_id") != manifest["id"]:
        raise SolverPolicyViolation("MISSING_CLUSTER_LICENSE_ADMISSION")
    token = _remote_admission.set(manifest["id"])
    try:
        yield
    finally:
        _remote_admission.reset(token)


def local_license_callbacks(job_id: str):
    from bff.store import output_paths, job_store
    from bff.services.cluster.contracts import read_config
    from bff.services.cluster.store import JobStore
    from bff.services.cluster.license_broker import LicenseBroker
    from bff.services.cluster.runner import process_identity
    config = read_config()
    root = Path(os.environ.get("MC_CLUSTER_DIR", output_paths.outputs_root() / "cluster"))
    broker = LicenseBroker(JobStore(root), total=config.global_gurobi_slots, external=config.external_gurobi_slots)
    reservation_id = "local-" + job_id
    identity = f"{os.getpid()}:{process_identity(os.getpid())}"

    def acquire():
        broker.reconcile_local_owners()
        while not broker.acquire(reservation_id, owner_kind="local", owner_identity=identity):
            from src.execution_control import check_cancelled
            check_cancelled()
            job_store.update_job(job_id, status="pending", message="Gurobi共有枠を待機中", metadata={"license_state": "WAITING"})
            time.sleep(2)
        job_store.update_job(job_id, metadata={"license_state": "ACTIVE"})

    def release(started: bool):
        broker.finish(reservation_id, cooldown_seconds=330 if started else 0)
        job_store.update_job(job_id, metadata={"license_state": "RELEASING" if started else "RELEASED"})
    return acquire, release


@contextmanager
def local_resource_scope(job_id: str, cpu_threads: int):
    from bff.store import output_paths, job_store
    from bff.services.cluster.contracts import read_config, Worker
    from bff.services.cluster.store import JobStore
    from bff.services.cluster.local_resources import LocalResources
    root = Path(os.environ.get("MC_CLUSTER_DIR", output_paths.outputs_root() / "cluster"))
    resources = LocalResources(JobStore(root))
    resources.reconcile()
    worker = next((w for w in read_config().workers if w.transport == "local"), Worker(id="local", name="local"))
    while not resources.acquire(job_id, worker, cpu_threads):
        from src.execution_control import check_cancelled
        check_cancelled()
        job_store.update_job(job_id, status="pending", message="このPCの実行枠を待機中")
        time.sleep(2)
        resources.reconcile()
    try:
        yield
    finally:
        resources.release(job_id)


def validate_execution_request(request, scenario: dict) -> None:
    config = scenario.get("simulation_config") or {}
    profile = request.execution_profile
    if profile != config.get("execution_profile", DEFAULT_PROFILE):
        raise SolverPolicyViolation("EXECUTION_PROFILE_CHANGED: save the profile and Prepare again")
    validate_no_gurobi_inputs(
        profile, mode=request.mode, research_run=request.research_run,
        planning_days=int(config.get("planning_days") or 1),
        bess_enabled=bool(config.get("bess_enabled")) or any(
            asset.get("bess_enabled") for asset in config.get("depot_energy_assets", [])),
        daily_return=bool(config.get("daily_return_depot_id")),
        hourly_rolling=request.run_hourly_rolling or request.run_profile != "day_ahead_exploratory",
    )


def guarded_execution(function):
    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        from contextlib import nullcontext
        from bff.store import job_store
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        profile = bound.arguments.get("execution_profile", DEFAULT_PROFILE)
        job_id = bound.arguments["job_id"]
        threads = 1 if profile == NO_GUROBI_PROFILE else int(bound.arguments.get("gurobi_threads") or 0)
        resources = nullcontext() if _remote_admission.get() else local_resource_scope(job_id, threads)
        with resources:
            return execute_bound(bound, profile, job_id, args, kwargs)

    def execute_bound(bound, profile, job_id, args, kwargs):
        from bff.store import job_store
        with solver_policy_scope(profile) as usage:
            from src.gurobi_session import managed_gurobi_session
            if profile == NO_GUROBI_PROFILE or _remote_admission.get() is not None:
                acquire, release = lambda: None, lambda started: None
            else:
                acquire, release = local_license_callbacks(job_id)
                # Admission wait precedes the fixed research/solver wall budget.
                acquire()
                acquire = lambda: None
            try:
                with managed_gurobi_session(acquire, release) as session:
                    if profile != NO_GUROBI_PROFILE and _remote_admission.get() is None:
                        session.admitted = True
                    return function(*args, **kwargs)
            finally:
                record = asdict(usage)
                record["license_failed"] = session.license_failed
                job = job_store.get_job(job_id)
                if session.license_failed:
                    job_store.update_job(job_id, status="failed", error="GUROBI_LICENSE_UNAVAILABLE",
                                         message="ライセンス取得に失敗しました。実行不可能性の判定ではありません。")
                if profile == NO_GUROBI_PROFILE and usage.forbidden_calls:
                    job_store.update_job(job_id, status="failed", error="GUROBI_FORBIDDEN")
                job_store.update_job(job_id, metadata={"solver_usage": record})
                if job.metadata.get("run_dir"):
                    path = Path(job.metadata["run_dir"]) / "solver_usage.json"
                    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return wrapped
