"""Compare normalized future RAIN candidate inventories without solver access."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


PROFILE_ORDER = ("BASE", "RANGE_ONLY", "BUDGET_ONLY", "FULL_EXPANDED")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _selectable(row: Mapping[str, Any]) -> bool:
    """Apply the persisted, formal candidate-selection gate fail closed."""

    try:
        cost = float(row["stage2_actual_canonical_cost_jpy"])
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        row.get("selectable") is True
        and row.get("stage2_feasible") is True
        and row.get("canonical_evaluation_feasible") is True
        and row.get("accounting_reconciliation_passed") is True
        and row.get("physical_validation_feasible") is True
        and row.get("trip_count_served") == 264
        and row.get("trip_count_unserved") == 0
        and row.get("fallback_used") is False
        and row.get("repair_used") is False
        and math.isfinite(cost)
        and _SHA256_RE.fullmatch(str(row.get("assignment_hash") or ""))
    )


def _used_vehicle_count(row: Mapping[str, Any]) -> int:
    """Return production's secondary tiebreak and reject inconsistent rows."""

    declared = row.get("used_vehicle_count")
    bev = row.get("used_bev")
    ice = row.get("used_ice")
    derived = None if bev is None or ice is None else int(bev) + int(ice)
    if declared is None:
        if derived is None:
            raise ValueError("candidate has neither used_vehicle_count nor used_bev+used_ice")
        return derived
    count = int(declared)
    if derived is not None and count != derived:
        raise ValueError("used_vehicle_count differs from used_bev + used_ice")
    return count


def _selection_key(row: Mapping[str, Any]) -> tuple[float, int, str]:
    """Mirror the production Phase 3 candidate tiebreak exactly."""

    return (
        float(row["stage2_actual_canonical_cost_jpy"]),
        _used_vehicle_count(row),
        str(row["assignment_hash"]),
    )


def _winner(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    selectable = [row for row in rows if _selectable(row)]
    return min(selectable, key=_selection_key, default=None)


def _normalized_selectable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate physical assignments, retaining production's winning row."""

    by_assignment: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _selectable(row):
            continue
        assignment_hash = str(row["assignment_hash"])
        prior = by_assignment.get(assignment_hash)
        if prior is None or _selection_key(row) < _selection_key(prior):
            by_assignment[assignment_hash] = row
    return sorted(by_assignment.values(), key=_selection_key)


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return len(left & right) / len(union) if union else None


def validate_profile_results(profiles: Mapping[str, Mapping[str, Any]]) -> None:
    """Reject hand-written or formally rejected analyzer inputs."""

    if set(profiles) != set(PROFILE_ORDER):
        raise ValueError("all four preregistered profiles are required")
    baseline_identity: dict[str, Any] | None = None
    for name in PROFILE_ORDER:
        payload = profiles[name]
        if payload.get("schema_version") != "rain_profile_result_v1":
            raise ValueError(f"{name} is not a rain_profile_result_v1 artifact")
        if payload.get("profile_name") != name:
            raise ValueError(f"{name} profile_result identity mismatch")
        if payload.get("status") != "ACCEPTED":
            raise ValueError(f"{name} profile_result did not pass formal gates")
        source_hashes = payload.get("source_artifact_hashes")
        if not isinstance(source_hashes, Mapping) or not source_hashes:
            raise ValueError(f"{name} profile_result has no source artifact hashes")
        if any(not _SHA256_RE.fullmatch(str(value)) for value in source_hashes.values()):
            raise ValueError(f"{name} profile_result has invalid source artifact hashes")
        identity = {
            "scenario_id": payload.get("scenario_id"),
            "prepared_input_id": payload.get("prepared_input_id"),
            "code_sha": payload.get("code_sha"),
            "canonical_fixed_input_hashes": payload.get("canonical_fixed_input_hashes"),
        }
        if baseline_identity is None:
            baseline_identity = identity
        elif identity != baseline_identity:
            raise ValueError(f"{name} profile_result fixed identity drift")


def analyze_profiles(
    profiles: Mapping[str, Mapping[str, Any]],
    *, advisor_threshold_percent: float | None = None,
) -> dict[str, Any]:
    if set(profiles) != set(PROFILE_ORDER):
        raise ValueError("all four preregistered profiles are required")
    candidates = {
        name: [dict(row) for row in profiles[name].get("candidates") or ()]
        for name in PROFILE_ORDER
    }
    generated_hashes = {
        name: {str(row.get("assignment_hash")) for row in rows if row.get("assignment_hash")}
        for name, rows in candidates.items()
    }
    evaluated_hashes = {
        name: {
            str(row.get("assignment_hash")) for row in rows
            if row.get("assignment_hash") and row.get("canonical_evaluation_feasible") is not None
        }
        for name, rows in candidates.items()
    }
    normalized = {
        name: _normalized_selectable_rows(rows) for name, rows in candidates.items()
    }
    selectable_hashes = {
        name: {str(row["assignment_hash"]) for row in rows}
        for name, rows in normalized.items()
    }
    winners = {name: _winner(normalized[name]) for name in PROFILE_ORDER}
    hashes = selectable_hashes
    base_hashes = hashes["BASE"]
    base_winner_hash = (
        str(winners["BASE"].get("assignment_hash")) if winners["BASE"] else None
    )
    all_rows_by_hash: dict[str, dict[str, Any]] = {}
    for rows in candidates.values():
        for row in rows:
            assignment_hash = str(row.get("assignment_hash") or "")
            if not assignment_hash or not _selectable(row):
                continue
            prior = all_rows_by_hash.get(assignment_hash)
            if prior is None or _selection_key(row) < _selection_key(prior):
                all_rows_by_hash[assignment_hash] = row
    union_winner = _winner(list(all_rows_by_hash.values()))
    summaries: dict[str, Any] = {}
    for name in PROFILE_ORDER:
        rows = candidates[name]
        selectable = normalized[name]
        winner = winners[name]
        ordered_costs = sorted(float(row["stage2_actual_canonical_cost_jpy"]) for row in selectable)
        base_cost = (
            float(winners["BASE"]["stage2_actual_canonical_cost_jpy"])
            if winners["BASE"] else None
        )
        winner_cost = float(winner["stage2_actual_canonical_cost_jpy"]) if winner else None
        delta = winner_cost - base_cost if winner_cost is not None and base_cost is not None else None
        summaries[name] = {
            "candidate_count": len(rows),
            "generated_assignment_count": len(generated_hashes[name]),
            "evaluated_assignment_count": len(evaluated_hashes[name]),
            "selectable_candidate_count": len(selectable),
            "distinct_physical_assignment_count": len(generated_hashes[name]),
            "selectable_assignment_hashes": sorted(hashes[name]),
            "base_candidate_retained_count": len(base_hashes & hashes[name]),
            "base_candidate_retention_rate": (
                len(base_hashes & hashes[name]) / len(base_hashes) if base_hashes else None
            ),
            "base_winner_present": base_winner_hash in hashes[name] if base_winner_hash else None,
            "winner_candidate_hash": winner.get("candidate_hash") if winner else None,
            "winner_assignment_hash": winner.get("assignment_hash") if winner else None,
            "winner_assignment_powertrain_hash": (
                winner.get("assignment_powertrain_hash") if winner else None
            ),
            "winner_cost_jpy": winner_cost,
            "selected_to_second_margin_jpy": (
                ordered_costs[1] - ordered_costs[0] if len(ordered_costs) >= 2 else None
            ),
            "base_cost_difference_jpy": delta,
            "base_cost_improvement_percent": (
                -100.0 * delta / abs(base_cost)
                if delta is not None and abs(base_cost) > 1.0e-9 else None
            ),
            "used_bev_difference_from_base": (
                int(winner.get("used_bev") or 0) - int(winners["BASE"].get("used_bev") or 0)
                if winner and winners["BASE"] else None
            ),
            "used_ice_difference_from_base": (
                int(winner.get("used_ice") or 0) - int(winners["BASE"].get("used_ice") or 0)
                if winner and winners["BASE"] else None
            ),
            "bev_trip_difference_from_base": (
                int(winner.get("bev_trips") or 0) - int(winners["BASE"].get("bev_trips") or 0)
                if winner and winners["BASE"] else None
            ),
            "ice_trip_difference_from_base": (
                int(winner.get("ice_trips") or 0) - int(winners["BASE"].get("ice_trips") or 0)
                if winner and winners["BASE"] else None
            ),
            "stage1_gap": profiles[name].get("stage1_gap"),
            "termination_reason": profiles[name].get("termination_reason"),
            "runtime_seconds": profiles[name].get("runtime_seconds"),
        }
    overlaps = [
        {
            "left_profile": left,
            "right_profile": right,
            "intersection_count": len(hashes[left] & hashes[right]),
            "union_count": len(hashes[left] | hashes[right]),
            "jaccard": _jaccard(hashes[left], hashes[right]),
        }
        for index, left in enumerate(PROFILE_ORDER)
        for right in PROFILE_ORDER[index + 1:]
    ]
    stability_verdict = None
    status = "AWAITING_ADVISOR_THRESHOLD"
    if advisor_threshold_percent is not None:
        if advisor_threshold_percent < 0.0:
            raise ValueError("advisor threshold must be nonnegative")
        winner_hashes = {
            str(winner.get("assignment_hash")) for winner in winners.values() if winner
        }
        complete_winners = all(winner is not None for winner in winners.values())
        improvements = [
            abs(float(row["base_cost_improvement_percent"]))
            for row in summaries.values()
            if row["base_cost_improvement_percent"] is not None
        ]
        maximum_improvement = max(improvements, default=float("inf"))
        composition_unchanged = all(
            row[key] == 0
            for row in summaries.values()
            for key in (
                "used_bev_difference_from_base", "used_ice_difference_from_base",
                "bev_trip_difference_from_base", "ice_trip_difference_from_base",
            )
            if row[key] is not None
        )
        stable = complete_winners and (
            len(winner_hashes) == 1
            or (maximum_improvement <= advisor_threshold_percent and composition_unchanged)
        )
        stability_verdict = (
            "SELECTION_STABLE_WITHIN_TESTED_PROFILES"
            if stable else "SELECTION_UNSTABLE_WITHIN_TESTED_PROFILES"
        )
        status = "STABILITY_EVALUATED_WITH_PREREGISTERED_THRESHOLD"
    return {
        "schema_version": "candidate_profile_comparison_v1",
        "status": status,
        "advisor_approved_threshold_percent": advisor_threshold_percent,
        "profile_summaries": summaries,
        "pairwise_overlaps": overlaps,
        "union_winner": union_winner,
        "stability_verdict": stability_verdict,
    }


def write_outputs(result: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    summaries = dict(result["profile_summaries"])
    with (output_dir / "candidate_profile_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["profile", *next(iter(summaries.values())).keys()])
        writer.writeheader()
        for profile in PROFILE_ORDER:
            writer.writerow({"profile": profile, **summaries[profile]})
    with (output_dir / "candidate_set_overlap.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["pairwise_overlaps"][0].keys()))
        writer.writeheader()
        writer.writerows(result["pairwise_overlaps"])
    (output_dir / "candidate_profile_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Candidate profile comparison", "", f"Status: `{result['status']}`", ""]
    for name in PROFILE_ORDER:
        row = summaries[name]
        lines.append(f"- {name}: candidates={row['candidate_count']}, winner={row['winner_candidate_hash']}")
    (output_dir / "candidate_profile_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-result", action="append", nargs=2, metavar=("PROFILE", "JSON"), required=True)
    parser.add_argument("--preregistration-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    profiles = {name: json.loads(Path(path).read_text(encoding="utf-8")) for name, path in args.profile_result}
    validate_profile_results(profiles)
    threshold = None
    if args.preregistration_manifest:
        manifest = json.loads(args.preregistration_manifest.read_text(encoding="utf-8"))
        if manifest.get("advisor_approved_threshold_unit") != "percent":
            raise ValueError("advisor threshold unit must be percent")
        threshold = manifest.get("advisor_approved_threshold")
    result = analyze_profiles(profiles, advisor_threshold_percent=threshold)
    write_outputs(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
