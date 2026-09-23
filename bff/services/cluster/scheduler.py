"""Persistent automatic allocation with fail-closed transport recovery."""
from __future__ import annotations

import base64
import inspect
import io
import json
import logging
import os
import threading
import time
import uuid
import zipfile
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from bff.store import output_paths
from .contracts import RESERVED, ROOT, ClusterConfig, Worker, canonical, digest, git_state, read_config, runtime_versions, segment, source_digest
from .runner import MAX_ARTIFACT_BYTES, file_hashes
from .store import ControllerLock, JobStore
from .transport import invoke
from .weekly_inputs import stage_execution_inputs, horizon_summary
from .artifacts import file_digest, copy_verified_member
from .worker_registry import WorkerRegistry, JOB_ROLES, job_role_allows
from .worker_monitor import WorkerMonitor

log = logging.getLogger(__name__)


def validate_portable_paths(value: object, staged_paths: set[str] | None = None):
    """External file-backed weather inputs need explicit staging, never silent fallback."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "pv_execution_input" and isinstance(item, dict) and item.get("path") in (staged_paths or set()):
                continue
            if isinstance(item, str) and item and ("path" in key.lower() or key.lower().endswith(("_file", "filename", "_csv"))):
                raise ValueError(f"Distributed input contains unstaged file reference '{key}'; use embedded prepared data")
            validate_portable_paths(item, staged_paths)
    elif isinstance(value, list):
        for item in value:
            validate_portable_paths(item, staged_paths)


def collect_artifacts(response: dict, manifest: dict, target: Path, archive_path: Path | None = None) -> dict:
    """Publish only a completely verified directory; discard this call's partials."""
    temporary = target.with_name(target.name + ".partial-" + uuid.uuid4().hex)
    archive_target = target.parent / "artifacts.zip"
    archive_temporary = archive_target.with_name("artifacts.partial-" + uuid.uuid4().hex + ".zip")
    try:
        result = _collect_artifacts_uncommitted(response, manifest, temporary, archive_path)
        if target.exists() and file_hashes(target) != response["artifact_hashes"]:
            raise ValueError("Existing artifact attempt differs; refusing to overwrite")
        if archive_path:
            shutil.copyfile(archive_path, archive_temporary)
        else:
            archive_temporary.write_bytes(base64.b64decode(response["archive_base64"], validate=True))
        if archive_target.exists() and file_digest(archive_target) != file_digest(archive_temporary):
            raise ValueError("Existing artifact archive differs; refusing to overwrite")
        # Finish every potentially large disk write before publishing either name.
        # The API additionally requires the committed terminal SQLite receipt.
        if not target.exists():
            temporary.rename(target)
        archive_temporary.replace(archive_target)
        return result
    finally:
        # Only remove unique paths created by this call and kept under the
        # attempt directory. Never touch a published or older partial attempt.
        parent = target.parent.resolve()
        if (temporary.exists() and not temporary.is_symlink() and not temporary.is_junction()
                and temporary.resolve().parent == parent and temporary.name.startswith(target.name + ".partial-")):
            shutil.rmtree(temporary)
        if (archive_temporary.exists() and not archive_temporary.is_symlink()
                and archive_temporary.resolve().parent == parent and archive_temporary.name.startswith("artifacts.partial-")):
            archive_temporary.unlink()


def _collect_artifacts_uncommitted(response: dict, manifest: dict, target: Path, archive_path: Path | None = None) -> dict:
    if response.get("id") != manifest["id"] or response.get("manifest_sha256") != digest(canonical(manifest)):
        raise ValueError("Returned manifest does not match submitted job")
    data = None if archive_path else base64.b64decode(response["archive_base64"], validate=True)
    if archive_path and file_digest(archive_path) != response.get("archive_sha256"):
        raise ValueError("Archive transfer hash mismatch")
    with zipfile.ZipFile(archive_path or io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if not archive_path and sum(info.file_size for info in infos) > MAX_ARTIFACT_BYTES:
            raise ValueError("Artifact size limit exceeded")
        names = [info.filename for info in infos]
        expected = response["artifact_hashes"]
        if len(set(names)) != len(names) or set(names) != set(expected):
            raise ValueError("Artifact inventory mismatch")
        verified = {}
        resolved_names = set()
        for info in infos:
            path = target / info.filename
            parts = PurePosixPath(info.filename).parts
            if (not parts or ".." in parts or "\\" in info.filename or ":" in info.filename
                    or any(part.endswith((".", " ")) for part in parts)
                    or not path.resolve().is_relative_to(target.resolve())):
                raise ValueError("Unsafe artifact path")
            resolved_name = str(path.resolve()).casefold()
            if resolved_name in resolved_names:
                raise ValueError("Artifact paths collide on the controller")
            resolved_names.add(resolved_name)
            if archive_path:
                copy_verified_member(archive, info, path, expected[info.filename])
                if info.filename in {"manifest.json", "state.json"}:
                    verified[info.filename] = path.read_bytes()
                continue
            content = archive.read(info)
            if digest(content) != expected[info.filename]:
                raise ValueError("Artifact hash mismatch")
            verified[info.filename] = content
        if verified.get("manifest.json") != canonical(manifest):
            raise ValueError("Artifact manifest mismatch")
        recorded_state = json.loads(verified["state.json"])
        if any(recorded_state.get(key) != response.get(key) for key in ("id", "state", "manifest_sha256", "result", "error")):
            raise ValueError("Result and archived state disagree")
        for name, content in verified.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return {key: value for key, value in response.items() if key != "archive_base64"}


class Scheduler:
    def __init__(self, root: Path, config: ClusterConfig):
        self.controller_lock = ControllerLock(root)
        self.store = JobStore(root)
        self.config = config
        from .license_broker import LicenseBroker
        self.licenses = LicenseBroker(self.store, total=config.global_gurobi_slots, external=config.external_gurobi_slots)
        self.licenses.reconcile_local_owners()
        from .local_resources import LocalResources
        self.local_resources = LocalResources(self.store)
        self.local_resources.reconcile()
        self.registry = WorkerRegistry(self.store, config.workers)
        self.monitor = WorkerMonitor(self.registry, config.workers)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.recovering: set[str] = set()
        self.reconcile_locks: dict[str, threading.Lock] = {}
        self.store.recover()
        for row in self.store.rows():
            if row["state"] in {"QUEUED", "LOST"}:
                self.mirror(row["id"], "pending" if row["state"] == "QUEUED" else "running",
                            "分散キューで待機中" if row["state"] == "QUEUED" else "状態不明。分散計算画面で結果を照合してください。")

    def start(self):
        self.monitor.start()
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.loop, daemon=True, name="cluster-scheduler")
            self.thread.start()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.recover_ready_jobs()
            except Exception:
                log.exception("Cluster scheduling failed")
            self.stop_event.wait(2)

    def worker(self, worker_id: str) -> Worker:
        return next(worker for worker in self.config.workers if worker.id == worker_id)

    def recover_ready_jobs(self):
        with self.lock:
            for row in self.store.rows():
                if (row["state"] != "LOST" or row["id"] in self.recovering
                        or len(self.recovering) >= 3 or not self.store.recovery_due(row["id"], time.time())):
                    continue
                self.recovering.add(row["id"])
                threading.Thread(target=self._recover_once, args=(row["id"],), daemon=True).start()

    def _recover_once(self, job_id: str):
        try:
            self.reconcile(job_id)
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
            # Communication uncertainty retains the reservation; never submit a replacement.
            self.store.defer_recovery(job_id, time.time())
        finally:
            with self.lock:
                self.recovering.discard(job_id)

    def import_workers(self, payload: dict) -> dict:
        from .seed_import import merge_private_seed
        from .contracts import write_config
        from .worker_monitor import local_tailnet_identity
        identity = local_tailnet_identity()
        with self.lock:
            merged = merge_private_seed(payload, self.config, self_node_id=identity.get("ID"),
                                        self_name=identity.get("HostName"), self_addresses=set(identity["TailscaleIPs"]))
            write_config(merged)
            for worker in merged.workers:
                self.registry.ensure(worker)
            self.config = merged
            self.monitor.workers = merged.workers
        return {"registered": len(merged.workers), "workers": self.worker_views()}

    def worker_views(self) -> list[dict]:
        rows = self.store.rows() + self.local_resources.rows()
        return [self.registry.view(worker, rows, self.monitor.controller) for worker in self.config.workers]

    @staticmethod
    def cooling_license_jobs(rows: list[dict], *, at: datetime | None = None) -> list[dict]:
        """WLS tokens outlive short jobs; retain their frozen reservation on restart."""
        current = at or datetime.now(timezone.utc)
        result = []
        for row in rows:
            delay = row["manifest"].get("gurobi_token_cooldown_seconds", 0)
            if (delay and row["manifest"]["requires_gurobi"]
                    and row["state"] in {"COMPLETED", "FAILED", "BLOCKED"}
                    and (current - datetime.fromisoformat(row["updated_at"])).total_seconds() < delay):
                result.append(row)
        return result

    def set_worker_mode(self, worker_id: str, mode: str) -> dict:
        with self.lock:
            worker = self.worker(worker_id)
            self.registry.set_mode(worker_id, mode)
            if mode == "active":
                self.monitor.request_probe(worker)
            return self.registry.view(worker, self.store.rows(), self.monitor.controller)

    def set_worker_job_role(self, worker_id: str, role: str) -> dict:
        with self.lock:
            worker = self.worker(worker_id)
            if role not in JOB_ROLES:
                raise ValueError("Invalid worker job role")
            if role in {"both", "gurobi_only"} and not worker.gurobi:
                raise ValueError("Gurobi jobs require administrator-verified Gurobi capability")
            pinned = [job["id"] for job in self.store.rows()
                      if job["state"] == "QUEUED" and job["manifest"].get("worker_id") == worker_id
                      and not job_role_allows(role, job["manifest"])]
            if pinned:
                raise ValueError("Pinned queued jobs conflict with this role: " + ", ".join(pinned[:3]))
            self.registry.set_job_role(worker_id, role)
            return self.registry.view(worker, self.store.rows(), self.monitor.controller)

    def enqueue(self, kind: str, bundle: dict, worker_id: str | None = None, *, job_id: str | None = None,
                minimum_ram_gb: float = 0, retry_of: str | None = None) -> dict:
        if kind not in {"optimization", "diagnostic", "license_test"}:
            raise ValueError("Unsupported cluster task kind")
        if worker_id is not None:
            worker = self.worker(worker_id)
            row = self.registry.get(worker.id)
            mode = row["mode"] or ("active" if worker.enabled else "disabled")
            if mode != "active":
                raise ValueError("Worker is disabled or draining")
        state = git_state()
        if kind == "optimization" and state["dirty"]:
            raise ValueError("Distributed optimization requires a clean frozen commit")
        # Conservatively reserve a license for every optimization, including rolling/hybrid paths.
        manifest = {"schema_version": 1, "id": job_id or str(uuid.uuid4()), "kind": kind, "git": state,
                    "runtime_versions": runtime_versions(),
                    "source_digest": source_digest(), "bundle_sha256": digest(canonical(bundle)),
                    "worker_id": worker_id, "requires_gurobi": kind == "license_test" or (kind == "optimization" and (bundle.get("kwargs") or {}).get("execution_profile") != "alns_no_gurobi_v1"),
                    "minimum_ram_gb": minimum_ram_gb, "retry_of": retry_of}
        prior = self.store.get(retry_of)["manifest"] if retry_of else None
        manifest["logical_job_id"] = (prior.get("logical_job_id", prior["id"]) if prior else manifest["id"])
        manifest["attempt_id"] = manifest["id"]
        manifest["attempt_number"] = int(prior.get("attempt_number", 1)) + 1 if prior else 1
        manifest["execution_profile"] = (bundle.get("kwargs") or {}).get("execution_profile", "existing_solver_v1")
        if manifest["requires_gurobi"]:
            manifest["gurobi_reservation_id"] = manifest["id"]
        manifest["gurobi_token_cooldown_seconds"] = max(330, max(
            (worker.gurobi_token_cooldown_seconds for worker in self.config.workers
             if worker_id in (None, worker.id)), default=0)) if manifest["requires_gurobi"] else 0
        if kind == "optimization":
            manifest["summary"] = horizon_summary(bundle.get("scenario", {}), json.loads(base64.b64decode(bundle.get("prepared_base64", "e30="))), bundle.get("kwargs", {}))
        manifest["resource_requirements"] = {
            "minimum_ram_gb": minimum_ram_gb,
            "minimum_disk_free_gb": 2,
            "cpu_threads": int((bundle.get("kwargs") or {}).get("gurobi_threads") or 0),
        }
        if worker_id is not None and not job_role_allows(self.registry.job_role(worker), manifest):
            raise ValueError("Worker job role does not admit this task")
        directory = self.store.root / "jobs" / segment(manifest["id"])
        directory.mkdir(parents=True, exist_ok=True)
        for name, payload in (("bundle.json", bundle), ("manifest.json", manifest)):
            path = directory / name
            content = canonical(payload)
            if path.exists():
                if path.read_bytes() != content:
                    raise ValueError("IDEMPOTENCY_CONFLICT: attempt files bind different frozen inputs")
            else:
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.replace(path)
        try:
            return self.store.get(manifest["id"])
        except KeyError:
            pass
        return self.store.add(manifest)

    def freeze_optimization(self, worker_id: str | None, app_state: dict, minimum_ram_gb: float, **submission) -> bool:
        from bff.store import scenario_store
        from bff.services.run_preparation import _scenario_hash
        kwargs = dict(inspect.signature(submission["fn"]).bind(*submission["args"]).arguments)
        if kwargs["rebuild_dispatch"] or kwargs["use_existing_duties"]:
            raise ValueError("Distributed execution requires rebuild_dispatch=false and use_existing_duties=false")
        scenario_id, prepared_id = segment(kwargs["scenario_id"]), segment(kwargs["prepared_input_id"])
        # The canonical executor reads shallow base configuration and the exact prepared
        # bytes. Avoid loading/normalizing any original timetable in this adapter.
        scenario = scenario_store.get_scenario_document_shallow(scenario_id)
        if scenario.get("meta", {}).get("id") != scenario_id:
            raise ValueError("Scenario document ID mismatch")
        scenario.pop("refs", None)
        scenario.pop("__unloaded_artifact_fields__", None)
        prepared = (output_paths.outputs_root() / "prepared_inputs" / scenario_id / f"{prepared_id}.json").read_bytes()
        # Historical result paths are not executable inputs. Preserve only the input snapshot.
        for key in ("optimization_result", "simulation_result", "optimization_audit", "simulation_audit"):
            scenario.pop(key, None)
        prepared_payload = json.loads(prepared)
        if (prepared_payload.get("scenario_id") != scenario_id
                or prepared_payload.get("prepared_input_id") != prepared_id
                or prepared_payload.get("scenario_hash") != _scenario_hash(scenario)):
            raise ValueError("Scenario changed after Prepare; distributed snapshot rejected")
        execution_inputs = stage_execution_inputs([
            scenario.get("simulation_config") or {}, prepared_payload.get("simulation_config") or {},
        ], ROOT)
        for document in (scenario, prepared_payload):
            validate_portable_paths(document.get("simulation_config", {}), set(execution_inputs))
            validate_portable_paths(document.get("scenario_overlay", {}), set(execution_inputs))
        if kwargs.get("weather_proxy_forecast_path"):
            raise ValueError("External weather files must be embedded before distribution")
        dataset = Path(app_state["built_dir"]).resolve()
        dataset_path = dataset.relative_to(ROOT.resolve()).as_posix()
        bundle = {"kwargs": kwargs, "scenario": scenario, "prepared_base64": base64.b64encode(prepared).decode("ascii"),
                  "execution_inputs": execution_inputs,
                  "dataset_path": dataset_path, "dataset_hashes": file_hashes(dataset)}
        self.enqueue("optimization", bundle, worker_id, job_id=submission["job_id"], minimum_ram_gb=minimum_ram_gb)
        return True

    def tick(self, job_ids: set[str] | None = None):
        from .resource_policy import resource_fit, rank_workers
        with self.lock:
            self.local_resources.reconcile()
            rows = self.store.rows() + self.local_resources.rows()
            self.licenses.total = self.config.global_gurobi_slots
            self.licenses.external = self.config.external_gurobi_slots
            reserved = [row for row in rows if row["state"] in RESERVED]
            cooling = self.cooling_license_jobs(rows)
            for row in rows:
                if row["state"] != "QUEUED":
                    continue
                if job_ids is not None and row["id"] not in job_ids:
                    continue
                manifest = row["manifest"]
                used_licenses = self.config.external_gurobi_slots + len(cooling) + sum(item["manifest"]["requires_gurobi"] for item in reserved)
                if manifest["requires_gurobi"] and used_licenses >= self.config.global_gurobi_slots:
                    continue
                candidates = []
                for worker in self.config.workers:
                    if manifest["worker_id"] not in (None, worker.id):
                        continue
                    if not job_role_allows(self.registry.job_role(worker), manifest):
                        continue
                    availability = self.registry.view(worker, rows, self.monitor.controller)
                    readiness = "can_run_optimization" if manifest["requires_gurobi"] else "can_run_no_gurobi" if manifest["kind"] == "optimization" else "can_run_diagnostic"
                    if not availability[readiness]:
                        continue
                    if manifest["requires_gurobi"] and not worker.gurobi:
                        continue
                    fit = resource_fit(worker, availability["capability"], manifest, reserved + [j for j in rows if j["state"] not in RESERVED])
                    candidates.append((worker, fit))
                for worker, fit in rank_workers(
                    candidates,
                    prefer_no_gurobi=manifest["kind"] == "optimization" and not manifest["requires_gurobi"],
                ):
                    if manifest["requires_gurobi"]:
                        admitted = self.licenses.acquire(row["id"], owner_kind="remote", worker_id=worker.id, worker_slots=worker.slots,
                                                         cpu_threads=fit["required_cpu_threads"], cpu_count=fit["cpu_count"])
                    else:
                        admitted = self.store.reserve_worker(row["id"], worker.id, worker.slots,
                                                             cpu_threads=fit["required_cpu_threads"], cpu_count=fit["cpu_count"])
                    if admitted:
                        self.registry.update(worker.id, {"last_allocation": {"job_id": row["id"], **fit}})
                        row["worker_id"] = worker.id
                        row["state"] = "STAGING"
                        reserved.append(row)
                        threading.Thread(target=self.execute, args=(row["id"], worker), daemon=True).start()
                    break

    def execute(self, job_id: str, worker: Worker):
        row = self.store.get(job_id)
        directory = self.store.root / "jobs" / job_id
        try:
            capability = invoke(worker, {"operation": "probe"}, directory / "preflight", timeout=45)
            if capability["git"] != row["manifest"]["git"] or capability["source_digest"] != row["manifest"]["source_digest"]:
                raise ValueError("Worker code does not match the frozen controller code")
            if (row["manifest"]["requires_gurobi"]
                    and capability.get("runtime_versions") != row["manifest"]["runtime_versions"]):
                raise ValueError("Worker runtime does not match the frozen controller environment")
            if row["manifest"]["minimum_ram_gb"] > min(capability.get("ram_gb") or 0, capability.get("ram_free_gb") or 0):
                raise ValueError("Worker RAM does not meet the requirement")
        except Exception as exc:
            self.store.transition(job_id, "BLOCKED", expected={"STAGING"}, error=f"Preflight: {exc}")
            self.licenses.finish(job_id, cooldown_seconds=0)
            self.mirror(job_id, "failed", f"Worker preflight blocked: {exc}")
            return
        try:
            bundle = json.loads((directory / "bundle.json").read_text(encoding="utf-8"))
            if digest(canonical(bundle)) != row["manifest"]["bundle_sha256"]:
                self.store.transition(job_id, "BLOCKED", expected={"STAGING"}, error="Stored bundle hash mismatch")
                self.licenses.finish(job_id, cooldown_seconds=0)
                self.mirror(job_id, "failed", "Stored bundle hash mismatch")
                return
            if self.stop_event.is_set():
                self.store.transition(job_id, "CANCELLED", expected={"STAGING"}, error="Controller stopped before submission")
                self.licenses.finish(job_id, cooldown_seconds=0)
                return
            if not self.store.transition(job_id, "RUNNING", expected={"STAGING"}):
                return
            self.mirror(job_id, "running", "別PCで実行中")
            response = invoke(worker, {"operation": "submit", "id": job_id, "manifest": row["manifest"], "bundle": bundle}, directory, timeout=30)
            while response.get("state") == "RUNNING":
                if self.stop_event.wait(3):
                    return  # The child continues; restart recovery retains its reservation as LOST.
                response = invoke(worker, {"operation": "status", "id": job_id}, directory / "status", timeout=20)
            response = invoke(worker, {"operation": "collect", "id": job_id, "stream_artifacts": True}, directory / "collect")
            self.finish(row, response)
        except Exception as exc:
            self.store.transition(job_id, "LOST", expected=RESERVED, error=str(exc))
            self.licenses.mark_uncertain(job_id)
            self.mirror(job_id, "running", "通信または結果検証に失敗。分散計算画面で照合してください。")

    def finish(self, row: dict, response: dict):
        if response.get("state") not in {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}:
            raise ValueError("Worker has not confirmed a terminal state")
        self.store.transition(row["id"], "COLLECTING", expected=RESERVED)
        directory = self.store.root / "jobs" / row["id"]
        archive_path = None
        if response.get("archive_sha256"):
            worker_id = self.store.get(row["id"])["worker_id"]
            download = invoke(self.worker(worker_id), {"operation": "archive", "id": row["id"]}, directory / "download")
            archive_path = Path(download["archive_path"])
        result = collect_artifacts(response, row["manifest"], directory / "artifacts", archive_path)
        self.store.transition(row["id"], result["state"], expected={"COLLECTING"}, result=result, error=result.get("error"))
        self.licenses.finish(row["id"], cooldown_seconds=max(330, row["manifest"].get("gurobi_token_cooldown_seconds", 0)))
        self.mirror(row["id"], "completed" if result["state"] == "COMPLETED" else "failed",
                    "分散実行終了。成果物と研究判定は分散計算画面で確認してください。")

    @staticmethod
    def mirror(job_id: str, status: str, message: str):
        from bff.store import job_store
        try:
            display_job = job_store.get_job(job_id)
        except KeyError:
            return
        if display_job.metadata.get("persistence_error"):
            log.warning("Display job mirror unavailable for %s; durable queue unchanged", job_id)
            return
        try:
            job_store.update_job(job_id, status=status, message=message,
                                 progress=100 if status in {"completed", "failed"} else 5,
                                 metadata={"cluster_job_id": job_id})
        except (OSError, ValueError, TimeoutError) as exc:
            # SQLite remains authoritative; a corrupt display mirror must not
            # prevent durable queue recovery or completion.
            log.warning("Display job mirror update failed for %s: %s", job_id, type(exc).__name__)

    def reconcile(self, job_id: str) -> dict:
        with self.lock:
            attempt_lock = self.reconcile_locks.setdefault(job_id, threading.Lock())
        with attempt_lock:
            return self._reconcile_attempt(job_id)

    def _reconcile_attempt(self, job_id: str) -> dict:
        with self.lock:
            row = self.store.get(job_id)
            if row["state"] != "LOST":
                raise ValueError("Only LOST jobs need reconciliation")
        response = invoke(self.worker(row["worker_id"]), {"operation": "collect", "id": job_id, "stream_artifacts": True},
                          self.store.root / "jobs" / job_id / "reconcile", timeout=30)
        if response.get("state") == "RUNNING":
            if response.get("id") != job_id or response.get("manifest_sha256") != digest(canonical(row["manifest"])):
                raise ValueError("Running receipt belongs to a different attempt")
            self.store.defer_recovery(job_id, time.time())
            return self.store.get(job_id)  # LOST means reconciling, not failed; poll without releasing its slot.
        self.finish(row, response)
        return self.store.get(job_id)

    def retry(self, job_id: str) -> dict:
        with self.lock:
            row = self.store.get(job_id)
            if row["state"] not in {"FAILED", "BLOCKED", "CANCELLED"}:
                raise ValueError("Retry requires a confirmed terminal failure/cancellation")
            bundle = json.loads((self.store.root / "jobs" / job_id / "bundle.json").read_text(encoding="utf-8"))
            original = row["manifest"]
            if git_state() != original["git"] or source_digest() != original["source_digest"] or digest(canonical(bundle)) != original["bundle_sha256"]:
                raise ValueError("Frozen code/input changed; submit a new job explicitly")
            return self.enqueue(original["kind"], bundle, original["worker_id"],
                                minimum_ram_gb=original["minimum_ram_gb"], retry_of=job_id)


_instance: Scheduler | None = None
_instance_lock = threading.Lock()


def get_scheduler() -> Scheduler:
    global _instance
    with _instance_lock:
        if _instance is None:
            root = Path(os.environ.get("MC_CLUSTER_DIR", output_paths.outputs_root() / "cluster"))
            _instance = Scheduler(root, read_config())
        _instance.start()
        return _instance
