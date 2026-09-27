"""Read saved rolling evidence without importing or starting a solver.

Stage2 runtime in historical results includes model construction and extraction.
Native log termination lines are reported separately; missing logs stay unknown.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import statistics


NATIVE_END = re.compile(
    r"^(?:Explored .*? in|Solved in \d+ iterations and) ([\d.]+) seconds\b"
)


def number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def read_evidence(path: Path, root: Path, evidence: dict) -> bytes:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("Evidence escapes the supplied run directory")
    content = resolved.read_bytes()
    evidence[path.relative_to(root).as_posix()] = hashlib.sha256(content).hexdigest()
    return content


def native_timings(content: bytes) -> list[float]:
    """Count final MIP/LP solve lines, never root LP or barrier substep lines."""
    values = []
    for line in content.decode("utf-8-sig", errors="replace").splitlines():
        match = NATIVE_END.match(line.strip())
        if match:
            value = number(float(match[1]))
            if value is not None:
                values.append(value)
    return values


def inspect_run(directory: Path) -> dict:
    root = directory.resolve(strict=True)
    chain = root / "rolling_hourly_chain"
    if not chain.is_dir():
        raise ValueError("Expected a run containing rolling_hourly_chain")
    evidence: dict[str, str] = {}
    rows = []
    seen_indices: set[int] = set()
    seen_logs: set[str] = set()
    paths = sorted(chain.glob("step_*/hourly_summary.json"))
    for path in paths:
        summary = json.loads(read_evidence(path, root, evidence))
        index = summary.get("step_index")
        if type(index) is not int or index < 0 or index in seen_indices:
            raise ValueError("Missing or duplicate step index")
        directory_index = re.match(r"^step_(\d+)_", path.parent.name)
        if directory_index is None or int(directory_index[1]) != index:
            raise ValueError("Summary step index disagrees with its directory")
        seen_indices.add(index)
        row = {"step_index": index, "current_absolute_min": summary.get("current_absolute_min"),
               "feasible": summary.get("feasible"), "solver_status": summary.get("stage2_solver_status"),
               "call_elapsed_seconds": number(summary.get("elapsed_seconds")),
               "stage2_helper_elapsed_seconds": number(summary.get("stage2_runtime_seconds")),
               "native_optimize_seconds": None, "native_solve_count": None,
               "declared_time_limit_seconds": number(summary.get("time_limit_sec")),
               "native_evidence": "MISSING_SOLVER_RESULT"}
        result_path = path.parent / "hourly_solver_result.json"
        if result_path.is_file():
            result = json.loads(read_evidence(result_path, root, evidence))
            metadata = result.get("metadata") or {}
            native_path = str(metadata.get("stage2_native_log_path") or "")
            # Original Windows paths belong to another PC. Resolve only the
            # named log in this bundle's diagnostics, never open that old path.
            name = PureWindowsPath(native_path).name
            row["native_evidence"] = "MISSING_NATIVE_LOG"
            if re.fullmatch(r"stage2_native_[\w-]+\.log", name):
                log = root / "diagnostics" / name
                if log.is_file():
                    if name in seen_logs:
                        raise ValueError("Multiple rolling steps reference the same native log")
                    seen_logs.add(name)
                    times = native_timings(read_evidence(log, root, evidence))
                    row["native_evidence"] = "TERMINATION_LINES" if times else "NO_TERMINATION_LINE"
                    if times:
                        row["native_optimize_seconds"] = sum(times)
                        row["native_solve_count"] = len(times)
        rows.append(row)
    rows.sort(key=lambda r: r["step_index"])
    paired = [r for r in rows if r["call_elapsed_seconds"] is not None and r["native_optimize_seconds"] is not None]
    invalid = [r["step_index"] for r in paired
               if r["native_optimize_seconds"] > r["call_elapsed_seconds"] + 0.1]
    if invalid:
        raise ValueError(f"Native runtime exceeds containing call: steps {invalid}")
    return {"schema_version": "rolling_timing_report_v1", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_directory": str(root), "saved_steps": len(rows), "paired_steps": len(paired),
            "missing_native_steps": [r["step_index"] for r in rows if r["native_optimize_seconds"] is None],
            "multiple_native_solve_steps": [r["step_index"] for r in rows if (r["native_solve_count"] or 0) > 1],
            "status_counts": dict(Counter(str(r["solver_status"]) for r in rows)),
            "paired_call_seconds": sum(r["call_elapsed_seconds"] for r in paired),
            "paired_native_seconds": sum(r["native_optimize_seconds"] for r in paired),
            "paired_outside_native_seconds": sum(r["call_elapsed_seconds"] - r["native_optimize_seconds"] for r in paired),
            "native_median_seconds": statistics.median(r["native_optimize_seconds"] for r in paired) if paired else None,
            "slowest_steps": sorted(paired, key=lambda r: r["call_elapsed_seconds"], reverse=True)[:10],
            "limitations": ["Saved steps only; an in-flight window is not measured.",
                            "Native log runtimes are rounded and may include multiple optimize calls.",
                            "Call elapsed excludes serialization, execution replay and downstream reporting.",
                            "Outside-native time includes construction, extraction, prechecks and validation; it is not one measured phase.",
                            "This is timing analysis, not a feasibility or research-acceptance audit."],
            "steps": rows, "evidence_sha256": evidence}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Saved run containing rolling_hourly_chain")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file outside the saved run")
    args = parser.parse_args()
    root = args.run.resolve(strict=True)
    destination = args.output.resolve()
    if destination.is_relative_to(root):
        parser.error("Output must be outside the source run")
    report = inspect_run(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("saved_steps", "paired_steps", "paired_call_seconds", "paired_native_seconds", "paired_outside_native_seconds")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
