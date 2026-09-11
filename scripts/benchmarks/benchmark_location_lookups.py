"""Compare uncached/cached lookups on a read-only dispatch rule snapshot."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.dispatch.lookup_snapshot import snapshot_location_lookups
from src.dispatch.models import DeadheadRule, DispatchContext, TurnaroundRule


def build_lookup_context(payload: dict) -> DispatchContext:
    context = DispatchContext(
        service_date="lookup-profile",
        trips=[],
        vehicle_profiles={},
        turnaround_rules={
            row["stop_id"]: TurnaroundRule(**row) for row in payload["turnaround_rules"]
        },
        deadhead_rules={
            (row["from_stop"], row["to_stop"]): DeadheadRule(**row)
            for row in payload["deadhead_rules"]
        },
        default_turnaround_min=payload["default_turnaround_min"],
        turnaround_buffer_min=payload["turnaround_buffer_min"],
    )
    context.location_aliases = {
        key: tuple(value) for key, value in payload["location_aliases"].items()
    }
    return context


def pair_values(
    context: DispatchContext, left: str, right: str
) -> tuple[int, int, bool, bool]:
    return (
        context.get_deadhead_min(left, right),
        context.get_turnaround_min(left),
        context.locations_equivalent(left, right),
        context.has_location_data(left),
    )


def measure(
    context: DispatchContext, pairs: list[tuple[str, str]], repetitions: int
) -> dict:
    started = time.perf_counter()
    checksum = 0
    for _ in range(repetitions):
        for left, right in pairs:
            checksum += sum(pair_values(context, left, right))
    return {"seconds": time.perf_counter() - started, "checksum": checksum}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.repetitions <= 10000:
        parser.error("Use a new output file and between 1 and 10000 repetitions")
    encoded = args.input.read_bytes()
    payload = json.loads(encoded)
    context = build_lookup_context(payload)
    snapshot = snapshot_location_lookups(context)
    locations = sorted(set(payload["query_locations"]))
    pairs = list(itertools.product(locations, repeat=2))
    expected = [pair_values(context, *pair) for pair in pairs]
    actual = [pair_values(snapshot, *pair) for pair in pairs]
    if actual != expected or any(
        context.resolve_location_ids(key) != snapshot.resolve_location_ids(key)
        for key in context.location_aliases
    ):
        raise AssertionError("Cached location results differ from original rules")
    baseline = measure(context, pairs, args.repetitions)
    cached = measure(snapshot, pairs, args.repetitions)
    if baseline["checksum"] != cached["checksum"]:
        raise AssertionError("Repeated lookup checksums differ")
    result = {
        "status": "EXACT_LOOKUP_EQUIVALENCE_PASSED",
        "kind": "lookup_microbenchmark_not_solver_result",
        "input_sha256": hashlib.sha256(encoded).hexdigest(),
        "profile_source_sha": payload.get("source_sha"),
        "benchmark_git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "benchmark_worktree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            )
        ),
        "location_count": len(locations),
        "distinct_pairs": len(pairs),
        "repetitions": args.repetitions,
        "pairs_evaluated_per_mode": len(pairs) * args.repetitions,
        "baseline": baseline,
        "cached": cached,
        "speedup_ratio": baseline["seconds"] / cached["seconds"],
        "limitations": [
            "Warm repeated queries only; excludes context/graph construction and solver time",
            "Original rule calculations and complete query pair set are preserved",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
