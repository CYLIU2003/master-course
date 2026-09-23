"""Match fixed job requirements to observed resources without changing solver controls."""
from __future__ import annotations

from datetime import datetime
from statistics import median
import math

from .contracts import RESERVED, Worker


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def workload_key(manifest: dict) -> tuple:
    summary = manifest.get("summary") or {}
    return (manifest.get("kind"), manifest.get("execution_profile", manifest.get("profile_id", "legacy")), summary.get("mode"),
            summary.get("planning_days"), summary.get("trip_count"),
            (manifest.get("resource_requirements") or {}).get("cpu_threads", 0),
            manifest.get("source_digest"), tuple(sorted((manifest.get("runtime_versions") or {}).items())))


def resource_fit(worker: Worker, capability: dict, manifest: dict, jobs: list[dict]) -> dict:
    """Return auditable eligibility and ranking inputs; missing telemetry stays unknown."""
    active = [j for j in jobs if j["worker_id"] == worker.id and j["state"] in RESERVED]
    reserved_ram = sum(j["manifest"].get("minimum_ram_gb", 0) for j in active)
    requirements = manifest.get("resource_requirements") or {}
    required_ram = max(manifest.get("minimum_ram_gb", 0), requirements.get("minimum_ram_gb", 0))
    total_ram = finite_number(capability.get("ram_gb"))
    free_ram = finite_number(capability.get("ram_free_gb"))
    disk = finite_number(capability.get("disk_free_gb"))
    cores = finite_number(capability.get("cpu_count"))
    # Gurobi Threads=0 is automatic, not zero CPU usage. Reserve the whole CPU
    # without changing the user's frozen solver parameter.
    threads = requirements.get("cpu_threads") or (cores if manifest.get("requires_gurobi") else 1)
    reserved_threads = sum((j["manifest"].get("resource_requirements") or {}).get("cpu_threads") or (cores if j["manifest"].get("requires_gurobi") else 1) or 1 for j in active)
    load = finite_number(capability.get("cpu_percent"))
    available_ram = None if total_ram is None or free_ram is None else max(
        0, min(total_ram, worker.ram_gb or total_ram, free_ram) - reserved_ram - worker.reserved_system_ram_gb)
    reasons = []
    if len(active) >= worker.slots:
        reasons.append("WORKER_SLOTS_RESERVED")
    if available_ram is None or available_ram < required_ram:
        reasons.append("INSUFFICIENT_OR_UNKNOWN_RAM")
    if disk is None or disk < max(worker.minimum_disk_free_gb, requirements.get("minimum_disk_free_gb", 0)):
        reasons.append("INSUFFICIENT_OR_UNKNOWN_DISK")
    if threads is None or cores is None or cores - reserved_threads < threads:
        reasons.append("INSUFFICIENT_OR_UNKNOWN_CPU_THREADS")
    if load is not None and load >= worker.maximum_cpu_load_percent:
        reasons.append("CPU_BUSY")
    if worker.require_ac_power and capability.get("ac_power") is not True:
        reasons.append("AC_POWER_REQUIRED")
    durations = []
    for job in jobs:
        if job["worker_id"] != worker.id or job["state"] != "COMPLETED" or workload_key(job["manifest"]) != workload_key(manifest):
            continue
        receipt = job.get("result") or {}
        try:
            duration = (datetime.fromisoformat(receipt["finished_at"]) - datetime.fromisoformat(receipt["started_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 < duration < 7 * 24 * 3600:
            durations.append(duration)
    return {"eligible": not reasons, "reasons": reasons, "available_ram_gb": available_ram,
            "required_ram_gb": required_ram, "required_cpu_threads": threads, "cpu_count": cores,
            "cpu_load_percent": load, "disk_free_gb": disk,
            "matching_history_count": len(durations),
            "median_worker_seconds": median(durations[-20:]) if durations else None}


def rank_workers(candidates: list[tuple[Worker, dict]]) -> list[tuple[Worker, dict]]:
    """Use measured duration only when all candidates have comparable history.

    With incomplete history, rank current load and RAM headroom; never infer
    single-thread speed from a PC name or logical-core count.
    """
    eligible = [(worker, fit) for worker, fit in candidates if fit["eligible"]]
    use_history = bool(eligible) and all(fit["matching_history_count"] for _, fit in eligible)
    for _, fit in eligible:
        fit["ranking_basis"] = "comparable_worker_runtime" if use_history else "current_load_and_memory_headroom"
    def key(item):
        worker, fit = item
        return (fit["median_worker_seconds"] if use_history else 0,
                fit["cpu_load_percent"] if fit["cpu_load_percent"] is not None else 100,
                -(fit["available_ram_gb"] or 0), worker.transport == "local", worker.id)
    return sorted(eligible, key=key)
