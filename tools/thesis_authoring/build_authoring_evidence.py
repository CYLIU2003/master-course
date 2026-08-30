"""Build thesis-ready analyses from frozen bb0c005 evidence.

This tool never invokes Prepare, Gurobi, or the optimization pipeline.  It
cross-checks the Git-tracked review bundle against the two preserved local run
directories, then emits review-sized derived tables, figures, and provenance
manifests under ``docs/thesis/authoring_v1``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


EXECUTION_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
SCENARIOS = {
    "SUNNY": {
        "scenario_id": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
        "prepared_input_id": "prepared-1f1b85053b8c9ea1-453c50ff177c277b-8acc7b3a",
        "prepared_source_sha256": "99e49dd72e73d6e2e8c546d71573d3b00a7f00d23ab748da7171e1dd4b6bf05d",
        "run_dir": "output/2026-08-29/run_20260829_1445",
    },
    "RAIN": {
        "scenario_id": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
        "prepared_input_id": "prepared-a6c5e0a8cdd9b32b-f1e18f252e336f1f-8acc7b3a",
        "prepared_source_sha256": "8220f7208b7add87beeb3a30c5d8f727480423427fff5e2f5eca1ed4a8e0ed3f",
        "run_dir": "output/2026-08-29/run_20260829_1455",
    },
}

EXECUTED_SLOT_MAP_FIELDS = (
    "grid_to_bus_kwh_by_depot_slot",
    "pv_to_bus_kwh_by_depot_slot",
    "bess_to_bus_kwh_by_depot_slot",
    "pv_to_bess_kwh_by_depot_slot",
    "grid_to_bess_kwh_by_depot_slot",
    "pv_curtail_kwh_by_depot_slot",
    "bess_soc_kwh_by_depot_slot",
    "contract_over_limit_kwh_by_depot_slot",
)


class EvidenceError(RuntimeError):
    """Raised when provenance or numerical evidence fails closed."""


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceError(f"Expected JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise EvidenceError(f"{label}: expected {expected!r}, got {actual!r}")


def require_close(actual: float, expected: float, label: str, tolerance: float = 1e-6) -> None:
    if not math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=0.0):
        raise EvidenceError(f"{label}: expected {expected:.12g}, got {actual:.12g}")


def average_ranks(values: Sequence[float]) -> list[float]:
    """Return ascending average ranks with deterministic handling of ties."""

    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        for index, _ in indexed[cursor:end]:
            ranks[index] = average_rank
        cursor = end
    return ranks


def pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise EvidenceError("Correlation requires equal sequences with at least two values")
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if left_scale == 0.0 or right_scale == 0.0:
        raise EvidenceError("Correlation is undefined for a constant sequence")
    return numerator / (left_scale * right_scale)


def spearman_rank_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    return pearson_correlation(average_ranks(left), average_ranks(right))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_run_identity(repo_root: Path, scenario: str, run_dir: Path) -> dict[str, Any]:
    expected = SCENARIOS[scenario]
    manifest = load_json(run_dir / "run_input_manifest.json")
    require_equal(manifest.get("git_sha"), EXECUTION_SHA, f"{scenario} git SHA")
    require_equal(manifest.get("git_dirty"), False, f"{scenario} clean state")
    require_equal(manifest.get("git_state_available"), True, f"{scenario} Git state")
    for key in ("scenario_id", "prepared_input_id", "prepared_source_sha256"):
        require_equal(manifest.get(key), expected[key], f"{scenario} {key}")

    public_selected = load_json(
        repo_root
        / "docs/evidence/weather_dispatch_rerun_bb0c005"
        / scenario
        / "selected_candidate.json"
    )
    candidate_path = run_dir / "stage1_stage2_candidate_evaluation.json"
    candidate_sha = sha256_file(candidate_path)
    require_equal(
        candidate_sha,
        public_selected.get("source_sha256"),
        f"{scenario} candidate source SHA-256",
    )
    return {
        "run_input_manifest": manifest,
        "candidate_path": candidate_path,
        "candidate_sha256": candidate_sha,
        "public_selected": public_selected,
    }


def build_candidate_analysis(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    evidence_dir = repo_root / "docs/evidence/weather_dispatch_rerun_bb0c005"
    matrix_rows = read_csv(evidence_dir / "cross_weather_fixed_dispatch_matrix.csv")
    audit_rows = read_csv(evidence_dir / "case_a_candidate_selection_audit.csv")
    result_summary = load_json(evidence_dir / "result_summary.json")
    require_equal(len(matrix_rows), 44, "cross-weather row count")

    candidate_to_physical: dict[str, str] = {}
    for row in audit_rows:
        candidate_hash = row["candidate_hash"]
        assignment_hash = row["assignment_hash"]
        prior = candidate_to_physical.setdefault(candidate_hash, assignment_hash)
        require_equal(prior, assignment_hash, f"physical mapping for {candidate_hash}")

    composition_by_physical: dict[str, dict[str, Any]] = {}
    source_manifests: dict[str, Any] = {}
    for scenario, expected in SCENARIOS.items():
        run_dir = repo_root / expected["run_dir"]
        identity = verify_run_identity(repo_root, scenario, run_dir)
        source_manifests[scenario] = {
            "path": identity["candidate_path"].relative_to(repo_root).as_posix(),
            "sha256": identity["candidate_sha256"],
        }
        raw_candidates = load_json(identity["candidate_path"])["candidates"]
        require_equal(len(raw_candidates), 22, f"{scenario} raw candidate count")
        for candidate in raw_candidates:
            candidate_hash = str(candidate["candidate_hash"])
            physical_hash = candidate_to_physical.get(candidate_hash)
            if not physical_hash:
                raise EvidenceError(f"No physical assignment mapping for {candidate_hash}")
            composition = {
                "used_bev": int(candidate["used_bev"]),
                "used_ice": int(candidate["used_ice"]),
                "bev_trips": int(candidate["bev_trips"]),
                "ice_trips": int(candidate["ice_trips"]),
                "source_candidate_hash": candidate_hash,
            }
            prior = composition_by_physical.setdefault(physical_hash, composition)
            require_equal(prior, composition, f"composition parity for {physical_hash}")

    matrix_by_assignment: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in matrix_rows:
        if row.get("selectable") != "True" or row.get("stage2_feasible") != "True":
            raise EvidenceError("Published cross-weather matrix contains a nonselectable row")
        assignment_hash = row["assignment_hash"]
        scenario = row["scenario"]
        matrix_by_assignment[assignment_hash][scenario] = row
    require_equal(len(matrix_by_assignment), 22, "distinct physical assignment count")

    costs_by_scenario = {
        scenario: sorted(
            (
                (float(rows[scenario]["canonical_actual_cost_jpy"]), assignment_hash)
                for assignment_hash, rows in matrix_by_assignment.items()
            ),
            key=lambda pair: (pair[0], pair[1]),
        )
        for scenario in SCENARIOS
    }
    ranks = {
        scenario: {assignment_hash: rank for rank, (_, assignment_hash) in enumerate(values, 1)}
        for scenario, values in costs_by_scenario.items()
    }
    selected_hashes = {
        scenario: str(result_summary["scenarios"][scenario]["selected_physical_assignment_sha256"])
        for scenario in SCENARIOS
    }

    output_rows: list[dict[str, Any]] = []
    for assignment_hash in sorted(matrix_by_assignment):
        composition = composition_by_physical.get(assignment_hash)
        if composition is None:
            raise EvidenceError(f"Missing composition for physical assignment {assignment_hash}")
        sunny_cost = float(matrix_by_assignment[assignment_hash]["SUNNY"]["canonical_actual_cost_jpy"])
        rain_cost = float(matrix_by_assignment[assignment_hash]["RAIN"]["canonical_actual_cost_jpy"])
        output_rows.append(
            {
                "physical_assignment_sha256": assignment_hash,
                **composition,
                "sunny_cost_jpy": f"{sunny_cost:.6f}",
                "rain_cost_jpy": f"{rain_cost:.6f}",
                "rain_minus_sunny_jpy": f"{rain_cost - sunny_cost:.6f}",
                "sunny_rank": ranks["SUNNY"][assignment_hash],
                "rain_rank": ranks["RAIN"][assignment_hash],
                "selected_sunny": assignment_hash == selected_hashes["SUNNY"],
                "selected_rain": assignment_hash == selected_hashes["RAIN"],
            }
        )

    fieldnames = list(output_rows[0])
    table_path = output_dir / "tables/cross_weather_candidate_analysis.csv"
    write_csv(table_path, fieldnames, output_rows)

    sunny_costs = [float(row["sunny_cost_jpy"]) for row in output_rows]
    rain_costs = [float(row["rain_cost_jpy"]) for row in output_rows]
    used_bev = [float(row["used_bev"]) for row in output_rows]
    bev_trips = [float(row["bev_trips"]) for row in output_rows]
    summary: dict[str, Any] = {
        "schema_version": "thesis_candidate_analysis_v1",
        "scope": "finite_set_of_22_cross_weather_fixed_dispatch_candidates",
        "candidate_count": len(output_rows),
        "all_candidates_feasible_and_selectable": True,
        "spearman_sunny_rain_cost_rank": spearman_rank_correlation(sunny_costs, rain_costs),
        "pearson_used_bev_vs_sunny_cost": pearson_correlation(used_bev, sunny_costs),
        "pearson_used_bev_vs_rain_cost": pearson_correlation(used_bev, rain_costs),
        "pearson_bev_trips_vs_sunny_cost": pearson_correlation(bev_trips, sunny_costs),
        "pearson_bev_trips_vs_rain_cost": pearson_correlation(bev_trips, rain_costs),
        "used_bev_range": [int(min(used_bev)), int(max(used_bev))],
        "bev_trip_range": [int(min(bev_trips)), int(max(bev_trips))],
        "source_files": source_manifests,
        "published_matrix": {
            "path": (evidence_dir / "cross_weather_fixed_dispatch_matrix.csv").relative_to(repo_root).as_posix(),
            "sha256": sha256_file(evidence_dir / "cross_weather_fixed_dispatch_matrix.csv"),
        },
        "scenarios": {},
    }
    for scenario in SCENARIOS:
        ordered = costs_by_scenario[scenario]
        best_cost, best_hash = ordered[0]
        second_cost, second_hash = ordered[1]
        selected_hash = selected_hashes[scenario]
        require_equal(best_hash, selected_hash, f"{scenario} selected matrix winner")
        selected_composition = composition_by_physical[selected_hash]
        summary["scenarios"][scenario] = {
            "selected_physical_assignment_sha256": selected_hash,
            "selected_cost_jpy": best_cost,
            "second_physical_assignment_sha256": second_hash,
            "second_cost_jpy": second_cost,
            "selected_to_second_cost_margin_jpy": second_cost - best_cost,
            "selected_used_bev": selected_composition["used_bev"],
            "selected_used_ice": selected_composition["used_ice"],
            "selected_bev_trips": selected_composition["bev_trips"],
            "selected_ice_trips": selected_composition["ice_trips"],
            "selected_at_used_bev_range_edge": selected_composition["used_bev"]
            in {int(min(used_bev)), int(max(used_bev))},
            "minimum_cost_jpy": min(cost for cost, _ in ordered),
            "median_cost_jpy": median(cost for cost, _ in ordered),
            "maximum_cost_jpy": max(cost for cost, _ in ordered),
        }
    write_json(output_dir / "tables/cross_weather_candidate_analysis_summary.json", summary)
    render_candidate_figures(output_dir, output_rows, summary)
    return summary


def merge_slot_map(
    target: dict[str, dict[int, float]],
    source: Mapping[str, Any],
    start_slot: int,
    stop_slot: int,
    field_name: str,
) -> None:
    for owner_id, raw_values in source.items():
        owner_values = target.setdefault(str(owner_id), {})
        for raw_slot, raw_value in dict(raw_values or {}).items():
            slot = int(raw_slot)
            if slot < start_slot or slot >= stop_slot:
                continue
            value = float(raw_value or 0.0)
            if not math.isfinite(value):
                raise EvidenceError(f"Non-finite {field_name}[{owner_id}][{slot}]")
            prior = owner_values.get(slot)
            if prior is not None and not math.isclose(prior, value, abs_tol=1e-9, rel_tol=0.0):
                raise EvidenceError(f"Conflicting {field_name}[{owner_id}][{slot}]")
            owner_values[slot] = value


def build_executed_power_series(
    repo_root: Path,
    scenario: str,
    output_dir: Path,
) -> dict[str, Any]:
    expected = SCENARIOS[scenario]
    run_dir = repo_root / expected["run_dir"]
    verify_run_identity(repo_root, scenario, run_dir)
    chain_path = run_dir / "rolling_hourly_chain/rolling_chain_summary.json"
    chain = load_json(chain_path)
    require_equal(chain.get("chain_accepted"), True, f"{scenario} Rolling acceptance")
    require_equal(chain.get("step_count"), 24, f"{scenario} Rolling step count")
    require_equal(chain.get("scenario_id"), expected["scenario_id"], f"{scenario} chain scenario")
    require_equal(chain.get("prepared_input_id"), expected["prepared_input_id"], f"{scenario} chain Prepared ID")
    require_equal(chain.get("day_ahead_git_sha"), EXECUTION_SHA, f"{scenario} day-ahead SHA")
    require_equal(chain.get("rolling_runner_git_sha"), EXECUTION_SHA, f"{scenario} Rolling SHA")
    require_equal(chain.get("rolling_runner_git_dirty"), False, f"{scenario} Rolling clean state")
    require_equal(chain.get("timestep_min"), 15, f"{scenario} timestep")

    stitched: dict[str, dict[str, dict[int, float]]] = {
        name: {} for name in EXECUTED_SLOT_MAP_FIELDS
    }
    raw_sources: list[dict[str, Any]] = []
    coverage = {slot: 0 for slot in range(96)}
    for step_index in range(24):
        step_dir = run_dir / "rolling_hourly_chain" / f"step_{step_index:02d}_{step_index:02d}00"
        summary_path = step_dir / "hourly_summary.json"
        result_path = step_dir / "hourly_solver_result.json"
        step_summary = load_json(summary_path)
        result = load_json(result_path)
        require_equal(step_summary.get("step_index"), step_index, f"{scenario} step index")
        require_equal(step_summary.get("feasible"), True, f"{scenario} step feasible")
        require_equal(step_summary.get("stage2_solver_status"), "optimal", f"{scenario} step Stage 2")
        start_slot = int(step_summary["rolling_start_slot_index"])
        executed_slots = int(step_summary["execution_minutes"]) // 15
        stop_slot = min(start_slot + executed_slots, 96)
        for slot in range(start_slot, stop_slot):
            coverage[slot] += 1
        for field_name in EXECUTED_SLOT_MAP_FIELDS:
            raw_map = result.get(field_name)
            if not isinstance(raw_map, dict):
                raise EvidenceError(f"{scenario} step {step_index} missing {field_name}")
            merge_slot_map(stitched[field_name], raw_map, start_slot, stop_slot, field_name)
        raw_sources.append(
            {
                "path": result_path.relative_to(repo_root).as_posix(),
                "sha256": sha256_file(result_path),
                "executed_start_slot": start_slot,
                "executed_stop_slot_exclusive": stop_slot,
            }
        )

    missing = [slot for slot, count in coverage.items() if count == 0]
    duplicates = [slot for slot, count in coverage.items() if count > 1]
    require_equal(missing, [], f"{scenario} missing executed slots")
    require_equal(duplicates, [], f"{scenario} duplicate executed slots")
    executed_day = chain["executed_day_accounting"]
    stitched_hash = canonical_hash(stitched)
    require_equal(stitched_hash, executed_day["executed_energy_flow_hash"], f"{scenario} executed flow hash")

    depot_id = "tsurumaki"
    def value(field: str, slot: int) -> float:
        return float(stitched[field].get(depot_id, {}).get(slot, 0.0))

    rows: list[dict[str, Any]] = []
    for slot in range(96):
        grid_to_bus = value("grid_to_bus_kwh_by_depot_slot", slot)
        pv_to_bus = value("pv_to_bus_kwh_by_depot_slot", slot)
        bess_to_bus = value("bess_to_bus_kwh_by_depot_slot", slot)
        pv_to_bess = value("pv_to_bess_kwh_by_depot_slot", slot)
        grid_to_bess = value("grid_to_bess_kwh_by_depot_slot", slot)
        pv_curtail = value("pv_curtail_kwh_by_depot_slot", slot)
        rows.append(
            {
                "scenario": scenario,
                "scenario_id": expected["scenario_id"],
                "prepared_input_id": expected["prepared_input_id"],
                "slot_index": slot,
                "time": f"{slot // 4:02d}:{(slot % 4) * 15:02d}",
                "slot_minutes": 15,
                "pv_generated_kwh": pv_to_bus + pv_to_bess + pv_curtail,
                "pv_to_bus_kwh": pv_to_bus,
                "pv_to_bess_kwh": pv_to_bess,
                "pv_curtailed_kwh": pv_curtail,
                "bess_to_bus_kwh": bess_to_bus,
                "grid_to_bus_kwh": grid_to_bus,
                "grid_to_bess_kwh": grid_to_bess,
                "bess_soc_end_kwh": value("bess_soc_kwh_by_depot_slot", slot),
                "bev_charging_load_kwh": grid_to_bus + pv_to_bus + bess_to_bus,
                "grid_import_kwh": grid_to_bus + grid_to_bess,
                "grid_import_kw": (grid_to_bus + grid_to_bess) * 4.0,
            }
        )

    accounting = executed_day["cost_breakdown"]
    checks = {
        "pv_generated_kwh": sum(row["pv_generated_kwh"] for row in rows),
        "pv_to_bus_kwh": sum(row["pv_to_bus_kwh"] for row in rows),
        "pv_to_bess_kwh": sum(row["pv_to_bess_kwh"] for row in rows),
        "pv_curtailed_kwh": sum(row["pv_curtailed_kwh"] for row in rows),
        "bess_to_bus_kwh": sum(row["bess_to_bus_kwh"] for row in rows),
        "grid_to_bus_kwh": sum(row["grid_to_bus_kwh"] for row in rows),
        "grid_to_bess_kwh": sum(row["grid_to_bess_kwh"] for row in rows),
        "grid_import_kwh": sum(row["grid_import_kwh"] for row in rows),
        "peak_grid_kw": max(row["grid_import_kw"] for row in rows),
        "terminal_bess_soc_kwh": rows[-1]["bess_soc_end_kwh"],
    }
    accounting_fields = {
        "pv_generated_kwh": "pv_generated_kwh",
        "pv_to_bus_kwh": "pv_to_bus_kwh",
        "pv_to_bess_kwh": "pv_to_bess_kwh",
        "pv_curtailed_kwh": "pv_curtailed_kwh",
        "bess_to_bus_kwh": "bess_to_bus_kwh",
        "grid_to_bus_kwh": "grid_to_bus_kwh",
        "grid_to_bess_kwh": "grid_to_bess_kwh",
        "grid_import_kwh": "grid_import_kwh",
        "peak_grid_kw": "peak_grid_kw",
    }
    for check_name, accounting_name in accounting_fields.items():
        require_close(checks[check_name], float(accounting[accounting_name]), f"{scenario} {check_name}")
    terminal_expected = float(executed_day["bess_terminal_soc_by_depot"][depot_id]["terminal_soc_kwh"])
    require_close(checks["terminal_bess_soc_kwh"], terminal_expected, f"{scenario} terminal BESS SOC")

    output_path = output_dir / f"evidence_supplements/{scenario.lower()}_canonical_96_slot_power_series.csv"
    write_csv(output_path, list(rows[0]), rows)
    return {
        "scenario": scenario,
        "status": "FOUND_AND_VERIFIED",
        "output_path": output_path.relative_to(repo_root).as_posix(),
        "output_sha256": sha256_file(output_path),
        "run_dir": run_dir.relative_to(repo_root).as_posix(),
        "chain_path": chain_path.relative_to(repo_root).as_posix(),
        "chain_sha256": sha256_file(chain_path),
        "executed_energy_flow_hash": stitched_hash,
        "raw_hourly_solver_results": raw_sources,
        "checks": checks,
        "rows": rows,
    }


def render_candidate_figures(
    output_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25})
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    used_bev = [int(row["used_bev"]) for row in rows]
    sunny = [float(row["sunny_cost_jpy"]) / 1000.0 for row in rows]
    rain = [float(row["rain_cost_jpy"]) / 1000.0 for row in rows]

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.scatter(used_bev, sunny, label="SUNNY", marker="o")
    ax.scatter(used_bev, rain, label="RAIN", marker="x")
    ax.set(xlabel="Used BEV count", ylabel="Canonical candidate cost (thousand JPY)", title="Candidate cost versus used BEVs (finite 22-candidate set)")
    ax.legend()
    save_figure(fig, figures_dir / "candidate_cost_vs_used_bev")

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.scatter(sunny, rain)
    lower = min(sunny + rain)
    upper = max(sunny + rain)
    ax.plot([lower, upper], [lower, upper], linestyle="--", color="gray", label="equal cost")
    ax.set(xlabel="SUNNY cost (thousand JPY)", ylabel="RAIN cost (thousand JPY)", title="SUNNY and RAIN fixed-dispatch costs (finite 22-candidate set)")
    ax.legend()
    save_figure(fig, figures_dir / "sunny_rain_candidate_cost_scatter")

    ordered = sorted(rows, key=lambda row: int(row["sunny_rank"]))
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.plot([int(row["sunny_rank"]) for row in ordered], [int(row["rain_rank"]) for row in ordered], marker="o")
    ax.set(xlabel="SUNNY rank", ylabel="RAIN rank", title="Candidate rank comparison (finite 22-candidate set)", xticks=range(1, 23, 2), yticks=range(1, 23, 2))
    save_figure(fig, figures_dir / "candidate_cost_rank_comparison")

    counts: dict[int, int] = defaultdict(int)
    for count in used_bev:
        counts[count] += 1
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    ax.bar(sorted(counts), [counts[value] for value in sorted(counts)])
    ax.set(xlabel="Used BEV count", ylabel="Number of candidates", title="Candidate composition distribution (finite 22-candidate set)")
    save_figure(fig, figures_dir / "candidate_composition_distribution")

    labels: list[str] = []
    values: list[float] = []
    for scenario in ("SUNNY", "RAIN"):
        scenario_summary = summary["scenarios"][scenario]
        labels.extend([f"{scenario}\nselected", f"{scenario}\nsecond"])
        values.extend([scenario_summary["selected_cost_jpy"] / 1000.0, scenario_summary["second_cost_jpy"] / 1000.0])
    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    bars = ax.bar(labels, values)
    ax.bar_label(bars, fmt="%.1f")
    ax.set(ylabel="Canonical candidate cost (thousand JPY)", title="Selected and second-best candidates within the finite set")
    save_figure(fig, figures_dir / "selected_and_second_best_comparison")


def render_power_figures(output_dir: Path, scenario_results: Sequence[Mapping[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    colors = {
        "pv_to_bus_kwh": "#d4a017",
        "pv_to_bess_kwh": "#f4c542",
        "bess_to_bus_kwh": "#377eb8",
        "grid_to_bus_kwh": "#555555",
        "pv_curtailed_kwh": "#d95f02",
    }
    by_scenario = {str(result["scenario"]): result["rows"] for result in scenario_results}
    for scenario, rows in by_scenario.items():
        x = [int(row["slot_index"]) / 4.0 for row in rows]
        fig, ax = plt.subplots(figsize=(9.0, 4.8))
        for field, label in (
            ("pv_to_bus_kwh", "PV to bus"),
            ("pv_to_bess_kwh", "PV to BESS"),
            ("bess_to_bus_kwh", "BESS to bus"),
            ("grid_to_bus_kwh", "Grid to bus"),
            ("pv_curtailed_kwh", "PV curtailed"),
        ):
            ax.plot(x, [float(row[field]) * 4.0 for row in rows], label=label, color=colors[field])
        ax.set(xlabel="Hour", ylabel="Power-equivalent per 15-min slot (kW)", title=f"{scenario} executed Rolling power flows (96 canonical slots)", xlim=(0, 24))
        ax.legend(ncol=3)
        save_figure(fig, figures_dir / f"{scenario.lower()}_executed_power_flows")

    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    for scenario, rows in by_scenario.items():
        ax.plot([int(row["slot_index"]) / 4.0 for row in rows], [float(row["grid_import_kw"]) for row in rows], label=scenario)
    ax.set(xlabel="Hour", ylabel="Grid import (kW)", title="Executed Rolling grid import comparison (96 canonical slots)", xlim=(0, 24))
    ax.legend()
    save_figure(fig, figures_dir / "sunny_rain_grid_import_comparison")

    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    for scenario, rows in by_scenario.items():
        ax.plot([int(row["slot_index"]) / 4.0 for row in rows], [float(row["bess_soc_end_kwh"]) for row in rows], label=scenario)
    ax.set(xlabel="Hour", ylabel="BESS end-of-slot SOC (kWh)", title="Executed Rolling BESS SOC comparison (96 canonical slots)", xlim=(0, 24))
    ax.legend()
    save_figure(fig, figures_dir / "sunny_rain_bess_soc_comparison")

    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    for scenario, rows in by_scenario.items():
        pv_used = [float(row["pv_to_bus_kwh"]) + float(row["pv_to_bess_kwh"]) for row in rows]
        curtailed = [float(row["pv_curtailed_kwh"]) for row in rows]
        x = [int(row["slot_index"]) / 4.0 for row in rows]
        ax.plot(x, [value * 4.0 for value in pv_used], label=f"{scenario} PV used")
        ax.plot(x, [value * 4.0 for value in curtailed], linestyle="--", label=f"{scenario} PV curtailed")
    ax.set(xlabel="Hour", ylabel="Power-equivalent per 15-min slot (kW)", title="Executed Rolling PV use and curtailment (96 canonical slots)", xlim=(0, 24))
    ax.legend(ncol=2)
    save_figure(fig, figures_dir / "sunny_rain_pv_use_curtailment")


def save_figure(figure: Any, base_path: Path) -> None:
    import matplotlib as mpl

    # SVG element IDs and metadata are otherwise salted with process/time
    # values. Fix both so the same frozen inputs yield identical artifacts.
    mpl.rcParams["svg.hashsalt"] = "thesis-authoring-v1"
    figure.tight_layout()
    figure.savefig(base_path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    svg_path = base_path.with_suffix(".svg")
    figure.savefig(svg_path, bbox_inches="tight", metadata={"Date": None})
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_text.splitlines()) + "\n",
        encoding="utf-8",
    )
    import matplotlib.pyplot as plt

    plt.close(figure)


def build_source_manifest(repo_root: Path, output_dir: Path, payloads: Sequence[Mapping[str, Any]]) -> None:
    manifest_path = output_dir / "evidence_supplements/derived_evidence_manifest.json"
    authoring_manifest_path = output_dir / "evidence_supplements/authoring_bundle_manifest.json"
    generated_files = []
    for path in sorted(output_dir.rglob("*")):
        # A manifest must not hash its previous incarnation. Excluding itself
        # makes repeated read-only derivations byte-for-byte deterministic.
        if path.is_file() and path not in {manifest_path, authoring_manifest_path}:
            generated_files.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    write_json(
        manifest_path,
        {
            "schema_version": "thesis_authoring_derived_evidence_v1",
            "execution_git_sha": EXECUTION_SHA,
            "derivation": "read_only_no_prepare_no_solver_no_repair",
            "source_verification": list(payloads),
            "generated_files_before_manifest": generated_files,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, default=Path("docs/thesis/authoring_v1"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    candidate_summary = build_candidate_analysis(repo_root, output_dir)
    power_results = [
        build_executed_power_series(repo_root, scenario, output_dir)
        for scenario in ("SUNNY", "RAIN")
    ]
    render_power_figures(output_dir, power_results)
    manifest_payloads = [
        {"candidate_analysis": candidate_summary},
        *[
            {key: value for key, value in result.items() if key != "rows"}
            for result in power_results
        ],
    ]
    build_source_manifest(repo_root, output_dir, manifest_payloads)
    print("PASS_THESIS_AUTHORING_EVIDENCE_DERIVATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
