"""Places queued lab jobs on idle PCs, follows them to the end and collects results.

One job per PC at a time. A job runs detached on the PC (status.json is the source of truth there), so a
gateway restart resumes polling instead of losing the run. A job whose fate cannot be established is LOST, never
silently re-run.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .remote import Machine, RemoteError
from .store import ACTIVE, JobStore, now

MAX_RESULT_BYTES = 500 * 1024 * 1024
OUTCOME_STATE = {"EXITED": "COMPLETED", "EXITED_NONZERO": "FAILED", "TIMEOUT": "TIMEOUT"}


def memory_budget(total_gb: float) -> float:
    """Same rule as the thesis cluster: installed RAM minus 8 GiB, never below half."""
    return max(total_gb / 2, total_gb - 8)


class Dispatcher:
    def __init__(self, store: JobStore, machines: dict[str, Machine], data_dir: Path, *, per_owner_active: int = 2,
                 reserve_ram_gb: float = 1.5, max_cpu_load: float = 85, min_disk_gb: float = 5,
                 poll_seconds: float = 15, tick_seconds: float = 5, start_grace_seconds: float = 180, sleep=time.sleep):
        self.store, self.machines, self.data_dir = store, machines, data_dir
        self.per_owner_active, self.reserve_ram_gb = per_owner_active, reserve_ram_gb
        self.max_cpu_load, self.min_disk_gb = max_cpu_load, min_disk_gb
        self.poll_seconds, self.tick_seconds, self.sleep = poll_seconds, tick_seconds, sleep
        self.start_grace_seconds = start_grace_seconds
        self.threads: dict[str, threading.Thread] = {}
        self.stop_event = threading.Event()
        self.recovered = False
        self.last_probe: dict[str, dict] = {}

    # ---- scheduling
    def admits(self, job: dict, probe: dict) -> str | None:
        """Return None when the PC can take the job, else the reason."""
        if not probe.get("python_ok"):
            return "PYTHON_ENVIRONMENT_MISSING"
        if job["ram_gb"] > memory_budget(probe["total_gb"]):
            return "EXCEEDS_MACHINE_MEMORY_BUDGET"
        if probe["free_gb"] < job["ram_gb"] + self.reserve_ram_gb:
            return "INSUFFICIENT_FREE_RAM"
        if (probe.get("cpu_load") or 0) > self.max_cpu_load:
            return "CPU_BUSY"
        if probe["disk_free_gb"] < self.min_disk_gb:
            return "INSUFFICIENT_DISK"
        return None

    def recover(self) -> None:
        for job in self.store.rows(states=ACTIVE):
            machine = self.machines.get(job["machine"])
            if job["state"] == "STAGING" or machine is None:
                self.store.update(job["id"], state="LOST", finished_at=now(), message="gateway restarted before the job was confirmed running")
            else:
                self._spawn(job["id"], machine, resume=True)
        self.recovered = True

    def tick(self) -> None:
        if not self.recovered:
            self.recover()
        queued = self.store.rows(states={"QUEUED"})
        if not queued:
            return
        active = self.store.rows(states=ACTIVE)
        busy = {job["machine"] for job in active}
        per_owner: dict[str, int] = {}
        for job in active:
            per_owner[job["owner"]] = per_owner.get(job["owner"], 0) + 1
        probes: dict[str, dict | None] = {}
        for job in queued:
            if job["cancel_requested"] or per_owner.get(job["owner"], 0) >= self.per_owner_active:
                continue
            all_probed, all_too_big = True, True
            for machine_id, machine in self.machines.items():
                if machine_id in busy:
                    all_probed = False
                    continue
                if machine_id not in probes:
                    try:
                        probes[machine_id] = machine.probe()
                        self.last_probe[machine_id] = {**probes[machine_id], "probed_at": now()}
                    except (RemoteError, ValueError, KeyError):
                        probes[machine_id] = None
                probe = probes[machine_id]
                if probe is None:
                    all_probed = False
                    continue
                reason = self.admits(job, probe)
                all_too_big &= reason == "EXCEEDS_MACHINE_MEMORY_BUDGET"
                if reason is None and self.store.update(job["id"], expected={"QUEUED"}, state="STAGING", machine=machine_id,
                                                        message=f"placed on {machine_id}"):
                    busy.add(machine_id)
                    per_owner[job["owner"]] = per_owner.get(job["owner"], 0) + 1
                    self._spawn(job["id"], machine, resume=False)
                    break
            else:
                if all_probed and all_too_big:
                    self.store.update(job["id"], expected={"QUEUED"}, state="REJECTED", finished_at=now(),
                                      message=f"requested {job['ram_gb']:g} GiB exceeds the memory budget of every lab PC")

    def cancel(self, job_id: str) -> dict:
        job = self.store.get(job_id)
        if self.store.update(job_id, expected={"QUEUED"}, state="CANCELLED", finished_at=now(), message="cancelled before it started"):
            return self.store.get(job_id)
        if job["state"] in ACTIVE:
            self.store.update(job_id, cancel_requested=True, message="cancel requested")
        return self.store.get(job_id)

    # ---- one job from staging to the collected result
    def _spawn(self, job_id: str, machine: Machine, *, resume: bool) -> None:
        thread = threading.Thread(target=self._lifecycle, args=(job_id, machine, resume), daemon=True, name=f"lab-job-{job_id}")
        self.threads[job_id] = thread
        thread.start()

    def _lifecycle(self, job_id: str, machine: Machine, resume: bool) -> None:
        try:
            job = self.store.get(job_id)
            if not resume:
                machine.stage(job_id, Path(job["bundle_path"]), {"entry": job["entry"], "args": job["args"],
                                                                  "timeout_min": job["time_limit_min"], "threads": job["threads"]})
                self.store.update(job_id, expected={"STAGING"}, state="RUNNING", started_at=now(), message=f"running on {machine.id}")
            began = time.monotonic()
            deadline = began + job["time_limit_min"] * 60 + 900
            failures, pid = 0, None
            while True:
                if self.stop_event.is_set():
                    return  # leave the job RUNNING; the next gateway start resumes it
                job = self.store.get(job_id)
                try:
                    status = machine.status(job_id)
                    failures = 0
                except RemoteError:
                    status, failures = None, failures + 1
                    if failures >= 40:
                        self.store.update(job_id, state="LOST", finished_at=now(), message=f"lost contact with {machine.id}; the run may still be going there")
                        return
                if status and status.get("pid"):
                    pid = status["pid"]
                if job["cancel_requested"] and not (status and status.get("state") == "DONE"):
                    if pid:
                        machine.kill(pid)
                    self.store.update(job_id, state="CANCELLED", finished_at=now(), message="cancelled")
                    self._cleanup(machine, job_id)
                    return
                if status is None and failures == 0 and time.monotonic() - began > self.start_grace_seconds:
                    self.store.update(job_id, state="FAILED", finished_at=now(),
                                      message=f"the program did not start on {machine.id} within {self.start_grace_seconds:g} s")
                    self._cleanup(machine, job_id)
                    return
                if status and status.get("state") == "DONE":
                    break
                if time.monotonic() > deadline:
                    self.store.update(job_id, state="LOST", finished_at=now(), message=f"no completion on {machine.id} within the time limit plus 15 min")
                    return
                self.sleep(self.poll_seconds)
            self._collect(job_id, machine, status)
        except RemoteError as exc:
            self.store.update(job_id, state="FAILED", finished_at=now(), message=str(exc))
            self._cleanup(machine, job_id)
        except Exception as exc:  # never let a worker thread die silently
            self.store.update(job_id, state="LOST", finished_at=now(), message=f"gateway error: {type(exc).__name__}: {exc}")

    def _collect(self, job_id: str, machine: Machine, status: dict) -> None:
        self.store.update(job_id, state="COLLECTING")
        final = OUTCOME_STATE.get(status.get("outcome"), "FAILED")
        size = int(status.get("result_bytes") or 0)
        if size > MAX_RESULT_BYTES:
            self.store.update(job_id, state=final, exit_code=status.get("exit_code"), finished_at=now(),
                              message=f"result.zip is {size // 2**20} MiB (limit {MAX_RESULT_BYTES // 2**20} MiB); kept on {machine.id}")
            return
        destination = self.data_dir / "results" / f"{job_id}.zip"
        machine.fetch_result(job_id, destination)
        self.store.update(job_id, state=final, exit_code=status.get("exit_code"), finished_at=now(), result_path=str(destination),
                          message={"COMPLETED": "finished", "FAILED": f"the program exited with code {status.get('exit_code')}",
                                   "TIMEOUT": "stopped at the time limit"}[final])
        self._cleanup(machine, job_id)

    @staticmethod
    def _cleanup(machine: Machine, job_id: str) -> None:
        try:
            machine.cleanup(job_id)
        except (RemoteError, ValueError):
            pass  # a leftover directory is harmless; the result is already stored

    # ---- background loop
    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:  # keep scheduling after a transient failure
                pass
            self.stop_event.wait(self.tick_seconds)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, daemon=True, name="lab-dispatcher")
        thread.start()
        return thread
