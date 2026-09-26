"""Bounded, read-only inspection of one worker attempt; standard library only.

This file may be sent in memory to an already running worker. It neither imports
the solver nor changes the worker's frozen checkout or calculation artifacts.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


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
            "observed_at": datetime.now(timezone.utc).isoformat()}
