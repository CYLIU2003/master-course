"""Run one immutable job. This module is the same on local and SSH workers."""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import io
import json
import os
import platform
import shutil
import sys
import subprocess
import time
import traceback
import zipfile
from pathlib import Path

from .contracts import ROOT, canonical, digest, git_state, runtime_versions, segment, source_digest
from .store import now
from .artifacts import archive_to_disk
from .system_metrics import memory_metrics, cpu_percent, disk_free_gb, keep_awake, hardware_identity

MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024


def process_identity(pid: int) -> str | None:
    """A PID birth token, None for exited processes, unknown for inaccessible ones."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None if ctypes.get_last_error() == 87 else "unknown"
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                return "unknown"
            if exited.dwLowDateTime or exited.dwHighDateTime:
                return None
            return f"{created.dwHighDateTime}:{created.dwLowDateTime}"
        finally:
            kernel.CloseHandle(handle)
    if sys.platform == "linux":
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
            return None if fields[0] == "Z" else fields[19]
        except FileNotFoundError:
            return None
        except (PermissionError, IndexError):
            return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return "unknown"
    return "unknown"


def file_hashes(root: Path) -> dict[str, str]:
    result = {}
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise ValueError(f"Missing dataset directory: {root}")
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Symlink is not a portable dataset: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def physical_ram_gb() -> float | None:
    """Read installed RAM without making psutil a worker dependency."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_phys", "available_phys", "total_page", "available_page",
                    "total_virtual", "available_virtual", "available_extended",
                )
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.total_phys / (1024 ** 3), 2)
        return None
    try:
        return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 ** 3), 2)
    except (AttributeError, ValueError, OSError):
        return None


def probe(workspace: Path | None = None) -> dict:
    ram_gb = physical_ram_gb()
    try:
        import gurobipy
        solver = list(gurobipy.gurobi.version())
    except ImportError:
        solver = None
    return {"hostname": platform.node(), "python": platform.python_version(), "platform": platform.platform(),
            "cpu_count": os.cpu_count(), "ram_gb": ram_gb, "gurobi_version": solver,
            "gurobi_license_checked": False, "git": git_state(), "source_digest": source_digest(),
            "runtime_versions": runtime_versions(), "cpu_percent": cpu_percent(),
            "disk_free_gb": disk_free_gb(workspace or ROOT), **memory_metrics(), **hardware_identity(),
            "python_executable": sys.executable, "protocol_version": 1}


def write_json(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def verify_bundle(manifest: dict, bundle: dict):
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported cluster protocol")
    segment(manifest["id"])
    if manifest.get("kind") not in {"optimization", "diagnostic", "license_test"}:
        raise ValueError("Unsupported task kind")
    if digest(canonical(bundle)) != manifest["bundle_sha256"]:
        raise ValueError("Input bundle hash mismatch")
    if source_digest() != manifest["source_digest"] or git_state() != manifest["git"]:
        raise ValueError("Worker code does not match the frozen controller code")
    if manifest["kind"] == "license_test" and (manifest.get("requires_gurobi") is not True or manifest.get("gurobi_reservation_id") != manifest["id"]):
        raise ValueError("MISSING_CLUSTER_LICENSE_ADMISSION")
    if manifest["kind"] == "optimization":
        expected = (bundle.get("kwargs") or {}).get("execution_profile") != "alns_no_gurobi_v1"
        if manifest.get("requires_gurobi") is not expected:
            raise ValueError("SOLVER_POLICY_MANIFEST_MISMATCH")
        from .contracts import comparable_runtime
        if comparable_runtime(manifest["runtime_versions"], requires_gurobi=expected) != comparable_runtime(runtime_versions(), requires_gurobi=expected):
            raise ValueError("BLOCKED_RUNTIME_VERSION_MISMATCH")
        if manifest["git"]["dirty"]:
            raise ValueError("Optimization requires a clean frozen commit")
        dataset = ROOT / bundle["dataset_path"]
        if not dataset.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Dataset must be repository relative")
        if file_hashes(dataset) != bundle["dataset_hashes"]:
            raise ValueError("BLOCKED_DATASET_MISMATCH")


@contextlib.contextmanager
def solver_logs(directory: Path):
    """Capture both Python and native solver output, keeping stdout a JSON protocol."""
    sys.stdout.flush()
    sys.stderr.flush()
    old_out, old_err = os.dup(1), os.dup(2)
    with (directory / "stdout.log").open("w", encoding="utf-8") as out, (directory / "stderr.log").open("w", encoding="utf-8") as err:
        try:
            os.dup2(out.fileno(), 1)
            os.dup2(err.fileno(), 2)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                yield
        finally:
            out.flush()
            err.flush()
            os.dup2(old_out, 1)
            os.dup2(old_err, 2)
            os.close(old_out)
            os.close(old_err)


def execute_optimization(manifest: dict, bundle: dict, directory: Path) -> dict:
    output = directory / "output"
    # Set isolation before importing any stores: their paths are module-level constants.
    os.environ["MC_OUTPUTS_DIR"] = str(output)
    os.environ["SCENARIO_STORE_PATH"] = str(output / "scenarios")
    os.environ["BUILT_ROOT"] = str((ROOT / bundle["dataset_path"]).parent)
    os.environ["DEFAULT_DATASET_ID"] = Path(bundle["dataset_path"]).name
    from .weekly_inputs import install_execution_inputs
    install_execution_inputs(bundle, directory / "execution_inputs")
    os.environ["MC_EXECUTION_INPUTS_ROOT"] = str(directory / "execution_inputs")
    from bff.store import job_store, scenario_store
    from bff.routers.optimization import _run_optimization

    kwargs = copy.deepcopy(bundle["kwargs"])
    scenario_id = segment(kwargs["scenario_id"])
    prepared_id = segment(kwargs["prepared_input_id"])
    scenario = copy.deepcopy(bundle["scenario"])
    if kwargs.get("execution_profile", "existing_solver_v1") != (scenario.get("simulation_config") or {}).get("execution_profile", "existing_solver_v1"):
        raise ValueError("EXECUTION_PROFILE_CHANGED")
    if scenario.get("meta", {}).get("id") != scenario_id or "refs" in scenario:
        raise ValueError("Frozen scenario ID or storage references are invalid")
    scenario_store._save(scenario)
    prepared_path = output / "prepared_inputs" / scenario_id / f"{prepared_id}.json"
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    prepared_path.write_bytes(base64.b64decode(bundle["prepared_base64"], validate=True))
    job = job_store.create_job(execution_model="thread")
    kwargs["job_id"] = job.job_id
    from bff.services.optimization_run.solver_policy import admitted_cluster_attempt
    with admitted_cluster_attempt(manifest):
        _run_optimization(**kwargs)
    return job_store.job_to_dict(job_store.get_job(job.job_id))


def execute_license_test(manifest: dict, directory: Path) -> dict:
    os.environ["MC_OUTPUTS_DIR"] = str(directory / "output")
    os.environ["SCENARIO_STORE_PATH"] = str(directory / "output" / "scenarios")
    from bff.store import job_store
    from bff.services.optimization_run.solver_policy import admitted_cluster_attempt
    from tools.cluster.license_smoke import run_license_test
    job = job_store.create_job(execution_model="thread")
    with admitted_cluster_attempt(manifest):
        return run_license_test(job.job_id)


def archive_result(directory: Path, response: dict) -> dict:
    data = io.BytesIO()
    hashes = {}
    total = 0
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Refusing linked artifact")
            if not path.is_file() or path.name == "state.tmp":
                continue
            size = path.stat().st_size
            total += size
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError("Artifacts exceed 1 GiB transfer limit; retained on worker")
            name = path.relative_to(directory).as_posix()
            content = path.read_bytes()
            hashes[name] = digest(content)
            archive.writestr(name, content)
    return {**response, "artifact_hashes": hashes, "archive_base64": base64.b64encode(data.getvalue()).decode("ascii")}


def submit_detached(request: dict, workspace: Path) -> dict:
    """Hand off to a separate OS process so SSH/controller exit does not end a solve."""
    job_id = segment(request["id"])
    launch = workspace / ".launch" / job_id
    # Exclusive ownership also covers the interval before the child writes state.json.
    try:
        launch.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # A duplicate request may arrive before the first submit writes its receipt.
        # Never launch again while ownership is uncertain.
        request_path = launch / "request.json"
        for _ in range(20):
            if request_path.exists():
                break
            time.sleep(0.05)
        if not request_path.exists():
            raise ValueError("SUBMISSION_UNCERTAIN: launch ownership exists without an input receipt")
        original = json.loads(request_path.read_bytes())
        if (canonical(original["manifest"]) != canonical(request["manifest"])
                or digest(canonical(original["bundle"])) != digest(canonical(request["bundle"]))):
            raise ValueError("IDEMPOTENCY_CONFLICT: same attempt has different input")
        try:
            return worker_state(workspace, job_id)
        except FileNotFoundError:
            return {"id": job_id, "state": "RUNNING", "launch_id": job_id,
                    "manifest_sha256": digest(canonical(request["manifest"]))}
    payload = {**request, "operation": "run", "defer_archive": True}
    request_file = launch / "request.json"
    write_json(request_file, payload)
    command = [sys.executable, "-m", "bff.services.cluster.runner", "--workspace", str(workspace), "--request-file", str(request_file)]
    # Windows OpenSSH owns a kill-on-close Job Object. DETACHED_PROCESS alone
    # removes the console but does not escape that lifetime. Fail closed if the
    # host's policy does not permit breakaway; never pretend submission worked.
    options = {"creationflags": (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                 | subprocess.CREATE_BREAKAWAY_FROM_JOB)} if os.name == "nt" else {"start_new_session": True}
    state = {"id": job_id, "state": "RUNNING", "launch_id": job_id,
             "attempt_id": request["manifest"].get("attempt_id", job_id),
             "manifest_sha256": digest(canonical(request["manifest"]))}
    try:
        with (launch / "stdout.log").open("wb") as stdout, (launch / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **options)
        state.update(pid=process.pid, process_identity=process_identity(process.pid))
    except OSError as exc:
        state.update(state="FAILED", error=f"Unable to start detached worker: {exc}")
    write_json(launch / "state.json", state)
    return state


def worker_state(workspace: Path, job_id: str) -> dict:
    directory = workspace / job_id
    state_file = directory / "state.json"
    if not state_file.exists():
        state_file = workspace / ".launch" / job_id / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    if state["state"] == "RUNNING" and state.get("pid"):
        current = process_identity(state["pid"])
        previous = state.get("process_identity", "unknown")
        if current is None or (previous not in {None, "unknown"} and current != "unknown" and previous != current):
            state.update(state="FAILED", error="Worker process exited without a terminal result", finished_at=now())
            write_json(state_file, state)
    return state


def handle(request: dict, workspace: Path) -> dict:
    operation = request["operation"]
    if operation == "cancel":
        job_id = segment(request["id"])
        launch_request = workspace / ".launch" / job_id / "request.json"
        original = json.loads(launch_request.read_bytes())
        if request.get("manifest_sha256") != digest(canonical(original["manifest"])):
            raise ValueError("Cancel receipt does not match the owned attempt")
        state = worker_state(workspace, job_id)
        if state["state"] == "RUNNING":
            write_json(workspace / ".launch" / job_id / "cancel.json", {"id": job_id, "requested_at": now()})
        return {**state, "cancel_requested": state["state"] == "RUNNING"}
    archive = archive_to_disk if request.get("stream_artifacts") else archive_result
    if operation == "probe":
        return probe(workspace)
    if operation == "dataset-hashes":
        path = ROOT / request["path"]
        if not path.resolve().is_relative_to((ROOT / "data/built").resolve()):
            raise ValueError("Dataset inspection is restricted to data/built")
        return file_hashes(path)
    if operation == "submit":
        return submit_detached(request, workspace)
    job_id = segment(request["id"])
    directory = workspace / job_id
    if operation in {"collect", "status"}:
        state = worker_state(workspace, job_id)
        if operation == "status":
            return state
        if state["state"] not in {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}:
            return state
        if not (directory / "manifest.json").exists():
            # A detached child can fail before reaching handle(run). Preserve a
            # verifiable failure receipt so the controller can release its slot.
            launch = workspace / ".launch" / job_id
            request_file = launch / "request.json"
            if not request_file.is_file():
                raise ValueError("Worker manifest and launch receipt are missing; retain the reservation")
            original = json.loads(request_file.read_bytes())
            directory.mkdir(parents=True, exist_ok=True)
            write_json(directory / "manifest.json", original["manifest"])
            write_json(directory / "bundle.json", original["bundle"])
            write_json(directory / "state.json", state)
            if (launch / "stderr.log").exists():
                shutil.copyfile(launch / "stderr.log", directory / "launch-error.log")
        return archive(directory, state)
    if operation != "run":
        raise ValueError("Unknown worker operation")
    # An existing ID is never executed again, including after an interrupted transfer.
    directory.mkdir(parents=True, exist_ok=False)
    manifest, bundle = request["manifest"], request["bundle"]
    if manifest["id"] != job_id:
        raise ValueError("Job ID mismatch")
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "bundle.json", bundle)
    state = {"id": job_id, "state": "RUNNING", "started_at": now(), "manifest_sha256": digest(canonical(manifest)),
             "pid": os.getpid(), "process_identity": process_identity(os.getpid())}
    write_json(directory / "state.json", state)
    started = False
    try:
        verify_bundle(manifest, bundle)
        from src.execution_control import cancellation_scope, check_cancelled
        with solver_logs(directory), keep_awake() as sleep_inhibited, cancellation_scope(
            lambda: (workspace / ".launch" / job_id / "cancel.json").is_file()
        ):
            check_cancelled()
            provenance = probe()
            if manifest.get("minimum_ram_gb", 0) > (provenance["ram_gb"] or 0):
                raise ValueError("Worker RAM does not satisfy the frozen requirement")
            if manifest.get("requires_gurobi") and not provenance["gurobi_version"]:
                raise ValueError("Worker has no Gurobi installation")
            started = True
            if manifest["kind"] == "optimization":
                result = execute_optimization(manifest, bundle, directory)
            elif manifest["kind"] == "license_test":
                result = execute_license_test(manifest, directory)
            else:
                result = provenance
            check_cancelled()
            state["idle_sleep_inhibited"] = sleep_inhibited
        verify_bundle(manifest, bundle)
        failed = manifest["kind"] == "optimization" and result.get("status") != "completed"
        state.update(state="FAILED" if failed else "COMPLETED", result=result,
                     provenance=provenance, finished_at=now(), research_approval="NOT_GRANTED_BY_CLUSTER")
    except Exception as exc:
        from src.execution_control import ExecutionCancelled
        state.update(state="CANCELLED" if isinstance(exc, ExecutionCancelled) else "FAILED" if started else "BLOCKED", error=str(exc), finished_at=now())
        (directory / "exception.log").write_text(traceback.format_exc(), encoding="utf-8")
    write_json(directory / "state.json", state)
    return state if request.get("defer_archive") else archive(directory, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--license-file", type=Path)
    parser.add_argument("--request-file", type=Path)
    args = parser.parse_args()
    if args.license_file:
        os.environ["GRB_LICENSE_FILE"] = str(args.license_file)
    request = json.loads(args.request_file.read_bytes() if args.request_file else sys.stdin.buffer.read())
    if request.get("operation") == "archive":
        path = args.workspace.resolve() / (segment(request["id"]) + ".zip")
        with path.open("rb") as source:
            shutil.copyfileobj(source, sys.stdout.buffer, length=1024 * 1024)
        return
    response = handle(request, args.workspace.resolve())
    sys.stdout.buffer.write(canonical(response))


if __name__ == "__main__":
    main()
