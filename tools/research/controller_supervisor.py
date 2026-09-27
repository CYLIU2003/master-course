"""Opt-in, bounded recovery of one frozen controller; never submits a job.

Run ``enable`` once, then ``watch`` (or periodic ``tick``). ``disable`` must
precede an intentional controller shutdown. Disabling never kills a process.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bff.services.cluster.runner import process_identity
from bff.services.cluster.store import ControllerLock
from tools.cluster.atomic_file import replace_bytes
from tools.research.weekly_operator import load_operation
from tools.research.weekly_results import sha

MAX_STARTS = 3
BACKOFF_SECONDS = (60, 180, 600)


def save(path: Path, state: dict) -> None:
    replace_bytes(path, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))


def binding(operation: dict, settings: dict) -> dict:
    return {"settings": operation["settings"], "settings_sha256": sha(Path(operation["settings"])),
            "queue": settings["queue"], "solver_git_sha": settings["git_sha"],
            "supervisor_sha256": sha(Path(__file__))}


def command(operation: dict, settings: dict) -> list[str]:
    return [settings["python"], "-X", "utf8", str(Path(settings["release"]) /
            "tools/cluster/serve_controller.py"), "--settings", operation["settings"]]


def windows_argv(value: str) -> list[str]:
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(value, ctypes.byref(count))
    if not pointer:
        raise OSError("Cannot inspect controller command line")
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(pointer)


def matches(argv: list[str], expected: list[str]) -> bool:
    """Accept the legacy launcher without -X utf8, but no alternative program."""
    if len(argv) > 2 and argv[1:3] == ["-X", "utf8"]:
        argv = [argv[0], *argv[3:]]
    expected = [expected[0], *expected[3:]]
    if len(argv) != len(expected) or argv[2] != "--settings":
        return False
    return all(Path(argv[i]).resolve() == Path(expected[i]).resolve() for i in (0, 1, 3))


def inspect_processes(expected: list[str]) -> tuple[list[dict], bool]:
    if os.name != "nt":
        raise ValueError("This supervisor currently supports Windows only")
    # Static read-only CIM query: no user-controlled command interpolation.
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
              "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
              "Select-Object ProcessId,ParentProcessId,CommandLine) | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", timeout=30, check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    rows = json.loads(result.stdout or "[]")
    if isinstance(rows, dict):
        rows = [rows]
    found, unknown = [], False
    for row in rows:
        pid = int(row["ProcessId"])
        identity = process_identity(pid)
        if identity is None:
            continue
        if not row.get("CommandLine"):
            unknown = True
        elif matches(windows_argv(row["CommandLine"]), expected):
            if identity == "unknown":
                unknown = True
            else:
                found.append({"pid": pid, "identity": identity, "parent": int(row["ParentProcessId"])})
    # Windows venv launches a base interpreter with the same argv. This parent /
    # child pair is one controller; unrelated matching processes still block.
    parents = {p["parent"] for p in found}
    return [{"pid": p["pid"], "identity": p["identity"]} for p in found if p["pid"] not in parents], unknown


def observe(settings: dict, expected: list[str], state: dict) -> dict:
    found, unknown = inspect_processes(expected)
    if len(found) > 1:
        return {"status": "HOLD_MULTIPLE_PROCESSES"}
    if found:
        return {"status": "PROCESS_PRESENT", "process": found[0]}
    # Retain the last birth token across HOLD observations. Discarding it on a
    # permission failure would weaken the next absence check.
    saved = state.get("process") or {}
    if saved:
        current = process_identity(saved["pid"])
        if current == "unknown" or (current is not None and current == saved["identity"]):
            return {"status": "HOLD_PROCESS_UNKNOWN"}
    if unknown:
        return {"status": "HOLD_PROCESS_UNKNOWN"}
    with socket.socket() as sock:
        sock.settimeout(2)
        if sock.connect_ex(("127.0.0.1", int(settings["port"]))) == 0:
            return {"status": "HOLD_PORT_OCCUPIED"}
    try:
        lock = ControllerLock(Path(settings["queue"]))
    except RuntimeError:
        return {"status": "HOLD_QUEUE_OWNED"}
    lock.close()
    return {"status": "ABSENT"}


def has_pending_work(settings: dict) -> bool:
    database = Path(settings["queue"]) / "cluster.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return connection.execute("SELECT 1 FROM jobs WHERE state NOT IN "
                                  "('COMPLETED','FAILED','BLOCKED','CANCELLED') LIMIT 1").fetchone() is not None


def tick(state: dict, operation: dict, settings: dict, state_path: Path, *,
         observation=None, run=subprocess.run, launch=subprocess.Popen, now=time.time,
         pending=has_pending_work, reobserve=observe) -> dict:
    """Persist a launch reservation before creating a child (crash-safe budget)."""
    state["observed_at_utc"] = datetime.now(timezone.utc).isoformat()
    if state["binding"] != binding(operation, settings):
        state.update(enabled=False, status="BLOCKED_BINDING_CHANGED")
    elif not state["enabled"]:
        return state
    elif state.get("status") == "STARTING":
        # A crash between Popen and receipt persistence is not proof of absence.
        state.update(enabled=False, status="BLOCKED_START_OUTCOME_UNKNOWN")
    else:
        expected = command(operation, settings)
        seen = observation if observation is not None else observe(settings, expected, state)
        state.update(seen)
        if seen["status"] != "ABSENT":
            save(state_path, state)
            return state
        state.pop("process", None)
        if not pending(settings):
            state.update(enabled=False, status="IDLE_NO_PENDING_WORK")
        elif state["starts"] >= MAX_STARTS:
            state.update(enabled=False, status="BLOCKED_RESTART_BUDGET")
        elif now() < state.get("next_start_at", 0):
            state["status"] = "BACKOFF"
        else:
            log = state_path.parent / "controller.log"
            with log.open("ab", buffering=0) as stream:
                check = run(expected + ["--check"], cwd=settings["release"], stdout=stream,
                            stderr=stream, timeout=120, check=False)
                if check.returncode:
                    state.update(enabled=False, status="BLOCKED_PREFLIGHT", exit_code=check.returncode)
                else:
                    # Preflight can take time. A human may have started the same
                    # controller meanwhile. The child must itself acquire the
                    # queue lock; holding that lock across Popen would block it.
                    fresh = reobserve(settings, expected, state)
                    if fresh["status"] != "ABSENT":
                        state.update(fresh)
                        save(state_path, state)
                        return state
                    state.update(status="STARTING", starts=state["starts"] + 1,
                                 next_start_at=now() + BACKOFF_SECONDS[state["starts"]])
                    save(state_path, state)
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    child = launch(expected, cwd=settings["release"], stdout=stream,
                                   stderr=stream, creationflags=flags)
                    identity = process_identity(child.pid)
                    state.update(status="STARTED" if identity not in (None, "unknown") else "BLOCKED_START_OUTCOME_UNKNOWN",
                                 enabled=identity not in (None, "unknown"),
                                 process={"pid": child.pid, "identity": identity})
    save(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("enable", "disable", "status", "tick", "watch"))
    parser.add_argument("--operation", required=True, type=Path)
    args = parser.parse_args()
    operation, settings, _ = load_operation(args.operation)
    if not (Path(settings["queue"]) / "cluster.sqlite3").is_file():
        raise ValueError("Existing controller database is required; supervision cannot create a queue")
    root = Path(settings["queue"]) / "controller-supervision"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "state.json"
    while True:
        lock = ControllerLock(root)
        try:
            state = json.loads(path.read_bytes()) if path.exists() else {
                "binding": binding(operation, settings), "enabled": False,
                "status": "DISABLED", "starts": 0}
            if args.action == "enable":
                if state.get("status", "").startswith("BLOCKED") or state.get("status") == "STARTING":
                    raise ValueError("Resolve the recorded failure and archive the supervision state before re-enabling")
                if state["binding"] != binding(operation, settings):
                    raise ValueError("Existing supervisor is bound to different settings")
                state.update(enabled=True, status="ARMED")
                save(path, state)
            elif args.action == "disable":
                state.update(enabled=False, status="DISABLED")
                save(path, state)
            elif args.action in {"tick", "watch"}:
                state = tick(state, operation, settings, path)
            print(json.dumps(state, ensure_ascii=False), flush=True)
        finally:
            lock.close()
        if args.action != "watch" or not state["enabled"]:
            return 2 if state["status"].startswith("BLOCKED") else 3 if state["status"].startswith("HOLD") else 0
        time.sleep(30)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "SUPERVISOR_ERROR", "error_type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2)
