"""Bounded, read-only inspection of one worker attempt; standard library only.

This file may be sent in memory to an already running worker. It neither imports
the solver nor changes the worker's frozen checkout or calculation artifacts.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re


def _windows_process_memory(pid: int, expected_identity: str) -> dict:
    """Read one process through one handle, checking its creation time first."""
    import ctypes
    from ctypes import wintypes
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return {"status": "UNSUPPORTED"}

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return {"status": "EXITED" if ctypes.get_last_error() == 87 else "UNKNOWN"}
    try:
        created, exited, kt, ut = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kt), ctypes.byref(ut)):
            return {"status": "UNKNOWN"}
        if f"{created.dwHighDateTime}:{created.dwLowDateTime}" != expected_identity:
            return {"status": "IDENTITY_MISMATCH"}
        if exited.dwHighDateTime or exited.dwLowDateTime:
            return {"status": "EXITED"}
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not kernel.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return {"status": "UNKNOWN"}
        return {"status": "OBSERVED", "working_set_gib": counters.WorkingSetSize / 2**30,
                "peak_working_set_gib": counters.PeakWorkingSetSize / 2**30,
                "private_commit_gib": counters.PrivateUsage / 2**30}
    finally:
        kernel.CloseHandle(handle)


def process_memory(state: dict) -> dict:
    """Unknown memory is never zero; remote PIDs are queried only on their worker."""
    pid, identity = state.get("pid"), state.get("process_identity")
    if os.name != "nt":
        return {"status": "UNSUPPORTED"}
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or not isinstance(identity, str) or not re.fullmatch(r"\d+:\d+", identity):
        return {"status": "IDENTITY_UNAVAILABLE"}
    return {"pid": pid, **_windows_process_memory(pid, identity)}


def read_object(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def native_detail(path: Path) -> dict:
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    metrics = {}
    evidence = []
    solve_started = False
    for line in lines:
        # Numeric solver rows and fixed status lines only: no license/account text.
        stripped = line.strip()
        numeric = bool(re.match(r"^[*H ]*\d", line) and re.search(r"\d+s\s*$", line))
        status = stripped.startswith(("Root relaxation:", "Barrier solved model", "Time limit reached",
                                      "Memory limit reached", "Optimal solution found", "Best objective",
                                      "Explored ", "Solution count"))
        solve_started = solve_started or numeric or status or stripped.startswith((
            "Optimize a model", "Presolve", "User MIP start", "Loaded user MIP start",
        ))
        if not (numeric or status):
            continue
        evidence.append(stripped[:260])
        seconds = re.search(r"([\d.]+)s\s*$", line)
        if seconds:
            metrics["solver_seconds"] = float(seconds[1])
        barrier = re.match(r"^\s*(\d+)\s+(?:[-+\d.eE]+\s+){5}([\d.]+)s\s*$", line)
        if barrier:
            metrics["barrier_iteration"] = int(barrier[1])
        gap = re.search(r"([\d.]+)%", line)
        if gap:
            metrics["stage_gap_percent"] = float(gap[1])
    return {"file": path.name, "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "metrics": metrics, "lines": evidence[-6:], "solve_started": solve_started}


def inspect_attempt(directory: Path) -> dict:
    root = directory.resolve(strict=True)
    manifest = read_object(root / "manifest.json")
    state = read_object(root / "state.json")
    if manifest.get("id") != root.name or state.get("id") != root.name:
        raise ValueError("ATTEMPT_ID_MISMATCH")
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    if state.get("manifest_sha256") != fingerprint:
        raise ValueError("ATTEMPT_MANIFEST_MISMATCH")
    output = root / "output"
    runs = [p for p in output.glob("*/run_*") if p.is_dir() and p.resolve().is_relative_to(root)]
    if len(runs) > 1:
        raise ValueError("AMBIGUOUS_RUN_DIRECTORY")
    logs = [p for run in runs for p in run.glob("**/*native*.log")
            if p.is_file() and p.resolve().is_relative_to(root)]
    latest = max(logs, key=lambda p: p.stat().st_mtime) if logs else None
    phase = "MODEL_BUILD"
    native = native_detail(latest) if latest else None
    if latest and native["solve_started"]:
        phase = "STAGE2" if "stage2" in latest.name else "STAGE1"
    steps = []
    chain_accepted = False
    for run in runs:
        chain = run / "rolling_hourly_chain"
        if chain.is_dir():
            phase = "ROLLING"
        for path in chain.glob("step_*/hourly_summary.json"):
            if path.resolve().is_relative_to(root):
                item = read_object(path)
                steps.append((path.parent.name, item.get("feasible") is True and
                              not item.get("chain_rejection_reason") and not item.get("pv_execution_error")))
        summary = read_object(chain / "rolling_chain_summary.json")
        chain_accepted = summary.get("chain_accepted") is True or chain_accepted
    if chain_accepted:
        phase = "FINALIZING"
    return {"job_id": root.name, "manifest_sha256": fingerprint, "phase": phase,
            "native": native, "rolling_saved": len(steps),
            "rolling_feasible": sum(passed for _, passed in steps), "chain_accepted": chain_accepted,
            "last_step": max((name for name, _ in steps), default=None),
            "memory": process_memory(state),
            "observed_at": datetime.now(timezone.utc).isoformat()}
