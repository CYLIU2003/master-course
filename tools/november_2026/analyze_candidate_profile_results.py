"""Compare normalized future RAIN candidate inventories without solver access."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping


PROFILE_ORDER = ("BASE", "RANGE_ONLY", "BUDGET_ONLY", "FULL_EXPANDED")


def _selectable(row: Mapping[str, Any]) -> bool:
    return all(
        row.get(key) is True
        for key in ("stage2_feasible", "canonical_evaluation_feasible", "physical_validation_feasible")
    ) and row.get("stage2_actual_canonical_cost_jpy") is not None


def _winner(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    selectable = [row for row in rows if _selectable(row)]
    return min(
        selectable,
        key=lambda row: (
            float(row["stage2_actual_canonical_cost_jpy"]),
            str(row.get("candidate_hash") or ""),
        ),
        default=None,
    )


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return len(left & right) / len(union) if union else None


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
    hashes = {
        name: {str(row.get("candidate_hash")) for row in rows if row.get("candidate_hash")}
        for name, rows in candidates.items()
    }
    winners = {name: _winner(rows) for name, rows in candidates.items()}
    base_hashes = hashes["BASE"]
    base_winner_hash = (
        str(winners["BASE"].get("candidate_hash")) if winners["BASE"] else None
    )
    all_rows_by_hash: dict[str, dict[str, Any]] = {}
    for rows in candidates.values():
        for row in rows:
            candidate_hash = str(row.get("candidate_hash") or "")
            if not candidate_hash or not _selectable(row):
                continue
            prior = all_rows_by_hash.get(candidate_hash)
            if prior is None or float(row["stage2_actual_canonical_cost_jpy"]) < float(
                prior["stage2_actual_canonical_cost_jpy"]
            ):
                all_rows_by_hash[candidate_hash] = row
    union_winner = _winner(list(all_rows_by_hash.values()))
    summaries: dict[str, Any] = {}
    for name in PROFILE_ORDER:
        rows = candidates[name]
        selectable = [row for row in rows if _selectable(row)]
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
            "selectable_candidate_count": len(selectable),
            "distinct_physical_assignment_count": len(
                {str(row.get("assignment_hash")) for row in rows if row.get("assignment_hash")}
            ),
            "candidate_hashes": sorted(hashes[name]),
            "base_candidate_retained_count": len(base_hashes & hashes[name]),
            "base_candidate_retention_rate": (
                len(base_hashes & hashes[name]) / len(base_hashes) if base_hashes else None
            ),
            "base_winner_present": base_winner_hash in hashes[name] if base_winner_hash else None,
            "winner_candidate_hash": winner.get("candidate_hash") if winner else None,
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
            str(winner.get("candidate_hash")) for winner in winners.values() if winner
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
    threshold = None
    if args.preregistration_manifest:
        threshold = json.loads(args.preregistration_manifest.read_text(encoding="utf-8")).get("advisor_approved_threshold")
    result = analyze_profiles(profiles, advisor_threshold_percent=threshold)
    write_outputs(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
