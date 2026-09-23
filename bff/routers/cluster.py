"""Loopback-only cluster API. SSH hosts/commands belong exclusively to config."""
from __future__ import annotations

import ipaddress
import uuid
import time
import subprocess
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from bff.dependencies import require_built
from bff.routers.optimization import (
    RunOptimizationBody,
    _require_research_git_preflight_before_job_creation,
    enqueue_optimization,
)
from bff.services.cluster.contracts import RESERVED, segment
from bff.services.cluster.scheduler import get_scheduler
from bff.services.cluster.transport import invoke
from bff.services.cluster.seed_import import SeedInventory


def require_local_controller(request: Request):
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    host = urlparse("http://" + request.headers.get("host", "")).hostname
    origin = request.headers.get("origin")
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    if not local or host not in allowed_hosts or (origin and urlparse(origin).hostname not in allowed_hosts):
        raise HTTPException(403, "Cluster API requires a local controller connection")


router = APIRouter(prefix="/cluster", tags=["cluster"], dependencies=[Depends(require_local_controller)])


class SubmitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    idempotency_key: str | None = None
    expected_git_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    worker_id: str | None = None
    minimum_ram_gb: float = Field(default=16, gt=0, allow_inf_nan=False)
    request: RunOptimizationBody


def invalid(exc: Exception):
    return HTTPException(409, str(exc))


@router.get("/workers")
def workers():
    scheduler = get_scheduler()
    jobs = scheduler.store.rows()
    reserved = [job for job in jobs if job["state"] in RESERVED]
    leases = scheduler.licenses.snapshot()
    known = {row["id"] for row in leases}
    active = [row for row in leases if row["state"] in {"ACTIVE", "RECONCILING"}]
    cooling = [row for row in leases if row["state"] == "RELEASING" and (row["release_after"] or 0) > time.time()]
    return {"workers": scheduler.worker_views(),
            "global_gurobi_slots": scheduler.config.global_gurobi_slots,
            "external_gurobi_slots": scheduler.config.external_gurobi_slots,
            "license_reservations": leases,
            "cooling_gurobi_slots": len(cooling) + sum(job["id"] not in known for job in scheduler.cooling_license_jobs(jobs)),
            "reserved_gurobi_slots": len(active) + sum(job["manifest"]["requires_gurobi"] for job in reserved if job["id"] not in known)}


@router.post("/workers/import")
def import_workers(body: SeedInventory):
    try:
        return get_scheduler().import_workers(body.model_dump())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise invalid(exc) from exc


@router.post("/workers/{worker_id}/probe")
def probe_worker(worker_id: str):
    scheduler = get_scheduler()
    try:
        worker = scheduler.worker(worker_id)
        accepted = scheduler.monitor.request_probe(worker)
        return {"accepted": accepted, "message": "確認を開始しました" if accepted else "確認中、または他の端末を確認中です"}
    except (StopIteration, ValueError, RuntimeError, OSError) as exc:
        raise invalid(exc) from exc


@router.get("/workers/{worker_id}")
def worker_detail(worker_id: str):
    scheduler = get_scheduler()
    try:
        worker = scheduler.worker(worker_id)
        return scheduler.registry.view(worker, scheduler.store.rows(), scheduler.monitor.controller)
    except StopIteration as exc:
        raise HTTPException(404, "Unknown worker") from exc


def worker_control(worker_id: str, mode: str):
    try:
        return get_scheduler().set_worker_mode(worker_id, mode)
    except StopIteration as exc:
        raise HTTPException(404, "Unknown worker") from exc


@router.post("/workers/{worker_id}/enable")
def enable_worker(worker_id: str):
    return worker_control(worker_id, "active")


@router.post("/workers/{worker_id}/disable")
def disable_worker(worker_id: str):
    return worker_control(worker_id, "disabled")


@router.post("/workers/{worker_id}/drain")
def drain_worker(worker_id: str):
    return worker_control(worker_id, "draining")


@router.post("/workers/{worker_id}/diagnostic")
def diagnostic(worker_id: str):
    try:
        return get_scheduler().enqueue("diagnostic", {}, worker_id)
    except (StopIteration, ValueError) as exc:
        raise invalid(exc) from exc


@router.get("/jobs")
def jobs():
    return get_scheduler().store.rows()


@router.post("/workers/{worker_id}/license-test")
def license_test(worker_id: str):
    try:
        return get_scheduler().enqueue("license_test", {}, worker_id)
    except (StopIteration, ValueError) as exc:
        raise invalid(exc) from exc


@router.post("/jobs")
def submit(body: SubmitBody, app_state: dict = Depends(require_built)):
    scheduler = get_scheduler()
    # Serialize same-process preflight too. SQLite binds identity before any
    # scenario mutation; the scheduler controller lock excludes another BFF.
    with scheduler.lock:
        return _submit_once(scheduler, body, app_state)


def _submit_once(scheduler, body: SubmitBody, app_state: dict):
    try:
        submission_job_id = None
        if body.idempotency_key:
            from bff.services.cluster.submissions import claim_submission
            submission_job_id = claim_submission(scheduler.store, body.idempotency_key, body.model_dump())
            try:
                existing = scheduler.store.get(submission_job_id)
                return {"job_id": existing["id"], "cluster_job_id": existing["id"], "status": existing["state"], "reused": True}
            except KeyError:
                pass  # No queued execution exists; resume the same durable identity.
        segment(body.scenario_id)
        if body.worker_id:
            worker = scheduler.worker(body.worker_id)
            control = scheduler.registry.get(worker.id)["mode"] or ("active" if worker.enabled else "disabled")
            if control != "active":
                raise ValueError("Worker is disabled or draining")
        if not body.request.prepared_input_id or body.request.force_reprepare:
            raise ValueError("An existing prepared_input_id is required; reprepare on workers is forbidden")
        if body.request.rebuild_dispatch or body.request.use_existing_duties:
            raise ValueError("Use rebuild_dispatch=false and use_existing_duties=false for frozen prepared execution")
        # Fail before the shared preflight creates a parent job or changes scenario scope.
        from bff.services.cluster.contracts import git_state
        current_git = git_state()
        if body.expected_git_sha and current_git["sha"] != body.expected_git_sha:
            raise ValueError("BATCH_CODE_CHANGED: expected frozen Git SHA differs")
        if current_git["dirty"]:
            raise ValueError("Distributed optimization requires a clean frozen commit")
        # Even diagnostic optimization must not freeze arguments from stale loaded code.
        _require_research_git_preflight_before_job_creation(research_run=True)
        captured_id = []

        def freeze(**submission):
            from bff.store import job_store
            try:
                accepted = scheduler.freeze_optimization(body.worker_id, app_state, body.minimum_ram_gb, **submission)
                captured_id.append(submission["job_id"])
                job_store.update_job(submission["job_id"], metadata={"cluster_job_id": submission["job_id"]},
                                     message="分散キューで待機中")
                return accepted
            except Exception as exc:
                job_store.update_job(submission["job_id"], status="failed", error=str(exc), message="Distributed staging rejected")
                raise

        options = {"submission_job_id": submission_job_id} if submission_job_id else {}
        result = enqueue_optimization(body.scenario_id, body.request, app_state, submit=freeze, **options)
        return {**result, "cluster_job_id": captured_id[0]}
    except (StopIteration, ValueError, OSError) as exc:
        raise invalid(exc) from exc


@router.get("/jobs/{job_id}")
def job(job_id: str):
    try:
        return get_scheduler().store.get(segment(job_id))
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "Unknown cluster job") from exc


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    scheduler = get_scheduler()
    row = job(job_id)
    if not scheduler.store.transition(job_id, "CANCELLED", expected={"QUEUED"}):
        if row["state"] not in RESERVED or not row["worker_id"]:
            raise HTTPException(409, "Job already has a terminal state")
        from bff.services.cluster.contracts import canonical, digest
        try:
            response = invoke(scheduler.worker(row["worker_id"]), {
                "operation": "cancel", "id": job_id, "manifest_sha256": digest(canonical(row["manifest"]))},
                scheduler.store.root / "jobs" / job_id / "cancel", timeout=20)
            return {**scheduler.store.get(job_id), "cancel_requested": response.get("cancel_requested", False)}
        except (OSError, RuntimeError, ValueError) as exc:
            raise invalid(exc) from exc
    scheduler.mirror(job_id, "failed", "分散キューへの登録を取り消しました")
    return scheduler.store.get(job_id)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str):
    job(job_id)
    try:
        return get_scheduler().retry(job_id)
    except ValueError as exc:
        raise invalid(exc) from exc


@router.post("/jobs/{job_id}/reconcile")
def reconcile(job_id: str):
    job(job_id)
    try:
        return get_scheduler().reconcile(job_id)
    except (ValueError, RuntimeError, OSError) as exc:
        raise invalid(exc) from exc


@router.get("/jobs/{job_id}/artifacts")
def artifacts(job_id: str):
    row = job(job_id)
    path = get_scheduler().store.root / "jobs" / job_id / "artifacts.zip"
    if not row["result"] or not path.is_file():
        raise HTTPException(404, "Verified artifacts are not available")
    return FileResponse(path, media_type="application/zip", filename=f"cluster-{job_id}.zip")
