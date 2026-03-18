from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AlignmentMetrics:
    scenario_id: str
    prepared_input_path: str
    optimization_result_path: str
    timetable_rows_count: int
    served_trip_count: int
    unserved_trip_count: int
    departure_arrival_match_count: int
    departure_arrival_checked_count: int
    departure_arrival_match_rate: float
    checked_coverage_rate: float
    missing_in_prepared_count: int
    missing_in_result_dispatch_count: int
    prepared_day_tag: str
    result_day_tag: str
    day_tag_match: bool


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_prepared_input(scenario_id: str) -> Path:
    base = Path("app") / "scenarios" / scenario_id / "prepared_inputs"
    if not base.exists():
        raise FileNotFoundError(f"Prepared input directory not found: {base}")
    files = sorted(base.glob("prepared-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No prepared input file found under: {base}")
    return files[0]


def _discover_optimization_result(scenario_id: str) -> Path:
    root = Path("outputs")
    candidates = sorted(
        root.rglob(f"*{scenario_id}*/**/optimization_result.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        candidates = sorted(
            root.rglob("optimization_result.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates = [p for p in candidates if scenario_id in str(p)]

    if not candidates:
        raise FileNotFoundError(
            "No optimization_result.json found for scenario. "
            "Pass --optimization-result-path explicitly."
        )
    return candidates[0]


def _served_trip_ids(opt: dict[str, Any]) -> list[str]:
    solver_result = dict(opt.get("solver_result") or {})
    assignment = dict(solver_result.get("assignment") or {})
    served: list[str] = []
    for trip_ids in assignment.values():
        if isinstance(trip_ids, list):
            for trip_id in trip_ids:
                if isinstance(trip_id, str):
                    served.append(trip_id)
    # keep deterministic unique order
    seen: set[str] = set()
    uniq: list[str] = []
    for trip_id in served:
        if trip_id not in seen:
            seen.add(trip_id)
            uniq.append(trip_id)
    return uniq


def _unserved_trip_count(opt: dict[str, Any]) -> int:
    summary = dict(opt.get("summary") or {})
    from_summary = summary.get("trip_count_unserved")
    if isinstance(from_summary, int):
        return from_summary
    solver_result = dict(opt.get("solver_result") or {})
    unserved = solver_result.get("unserved_tasks")
    if isinstance(unserved, list):
        return len(unserved)
    return 0


def _trip_time_map(rows: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for row in rows:
        trip_id = row.get("trip_id")
        dep = row.get("departure")
        arr = row.get("arrival")
        if isinstance(trip_id, str) and isinstance(dep, str) and isinstance(arr, str):
            out[trip_id] = (dep, arr)
    return out


def _extract_day_tag_from_trip_id(trip_id: str) -> str:
    # ODPT由来trip_id末尾付近の曜日識別子を抽出する。
    for tag in ("Weekday", "Saturday", "Holiday", "Sunday"):
        if f".{tag}." in trip_id:
            return tag
    return "unknown"


def _dominant_day_tag(trip_ids: list[str]) -> str:
    counts: dict[str, int] = {}
    for trip_id in trip_ids:
        tag = _extract_day_tag_from_trip_id(trip_id)
        counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def compute_metrics(prepared: dict[str, Any], opt: dict[str, Any]) -> tuple[AlignmentMetrics, dict[str, Any]]:
    scenario_id = str(prepared.get("scenario_id") or opt.get("scenario_id") or "unknown")
    timetable_rows_count = int(prepared.get("timetable_row_count") or (prepared.get("counts") or {}).get("timetable_row_count") or 0)

    prepared_trips = list(prepared.get("trips") or [])
    prepared_map = _trip_time_map(prepared_trips)

    dispatch_report = dict(opt.get("dispatch_report") or {})
    result_trips = list(dispatch_report.get("trips") or [])
    result_map = _trip_time_map(result_trips)

    served_ids = _served_trip_ids(opt)
    served_trip_count = len(served_ids)
    unserved_trip_count = _unserved_trip_count(opt)
    prepared_day_tag = _dominant_day_tag(list(prepared_map.keys()))
    result_day_tag = _dominant_day_tag(served_ids)
    day_tag_match = prepared_day_tag == result_day_tag

    match_count = 0
    checked_count = 0
    missing_in_prepared: list[str] = []
    missing_in_result_dispatch: list[str] = []
    mismatch_samples: list[dict[str, Any]] = []

    for trip_id in served_ids:
        in_prepared = trip_id in prepared_map
        in_result = trip_id in result_map
        if not in_prepared:
            missing_in_prepared.append(trip_id)
        if not in_result:
            missing_in_result_dispatch.append(trip_id)
        if not (in_prepared and in_result):
            continue

        checked_count += 1
        p_dep, p_arr = prepared_map[trip_id]
        r_dep, r_arr = result_map[trip_id]
        if p_dep == r_dep and p_arr == r_arr:
            match_count += 1
        elif len(mismatch_samples) < 20:
            mismatch_samples.append(
                {
                    "trip_id": trip_id,
                    "prepared_departure": p_dep,
                    "prepared_arrival": p_arr,
                    "result_departure": r_dep,
                    "result_arrival": r_arr,
                }
            )

    match_rate = (match_count / checked_count) if checked_count > 0 else 0.0
    checked_coverage_rate = (checked_count / served_trip_count) if served_trip_count > 0 else 0.0

    metrics = AlignmentMetrics(
        scenario_id=scenario_id,
        prepared_input_path="",
        optimization_result_path="",
        timetable_rows_count=timetable_rows_count,
        served_trip_count=served_trip_count,
        unserved_trip_count=unserved_trip_count,
        departure_arrival_match_count=match_count,
        departure_arrival_checked_count=checked_count,
        departure_arrival_match_rate=match_rate,
        checked_coverage_rate=checked_coverage_rate,
        missing_in_prepared_count=len(missing_in_prepared),
        missing_in_result_dispatch_count=len(missing_in_result_dispatch),
        prepared_day_tag=prepared_day_tag,
        result_day_tag=result_day_tag,
        day_tag_match=day_tag_match,
    )

    evidence = {
        "served_trip_ids_sample": served_ids[:20],
        "mismatch_samples": mismatch_samples,
        "missing_in_prepared_sample": missing_in_prepared[:20],
        "missing_in_result_dispatch_sample": missing_in_result_dispatch[:20],
        "summary_from_optimization": opt.get("summary"),
        "solver_status": opt.get("solver_status"),
        "solver_mode": opt.get("solver_mode"),
        "mode": opt.get("mode"),
        "day_tag_consistency": {
            "prepared_day_tag": prepared_day_tag,
            "result_day_tag": result_day_tag,
            "day_tag_match": day_tag_match,
        },
    }
    return metrics, evidence


def write_outputs(metrics: AlignmentMetrics, evidence: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": metrics.scenario_id,
        "prepared_input_path": metrics.prepared_input_path,
        "optimization_result_path": metrics.optimization_result_path,
        "metrics": {
            "timetable_rows_count": metrics.timetable_rows_count,
            "served_trip_count": metrics.served_trip_count,
            "unserved_trip_count": metrics.unserved_trip_count,
            "departure_arrival_match_count": metrics.departure_arrival_match_count,
            "departure_arrival_checked_count": metrics.departure_arrival_checked_count,
            "departure_arrival_match_rate": metrics.departure_arrival_match_rate,
            "checked_coverage_rate": metrics.checked_coverage_rate,
            "missing_in_prepared_count": metrics.missing_in_prepared_count,
            "missing_in_result_dispatch_count": metrics.missing_in_result_dispatch_count,
            "prepared_day_tag": metrics.prepared_day_tag,
            "result_day_tag": metrics.result_day_tag,
            "day_tag_match": metrics.day_tag_match,
        },
        "evidence": evidence,
    }
    json_path = out_dir / "timetable_alignment_audit.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = out_dir / "timetable_alignment_audit.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "scenario_id",
            "timetable_rows_count",
            "served_trip_count",
            "unserved_trip_count",
            "departure_arrival_match_count",
            "departure_arrival_checked_count",
            "departure_arrival_match_rate",
            "checked_coverage_rate",
            "missing_in_prepared_count",
            "missing_in_result_dispatch_count",
            "prepared_day_tag",
            "result_day_tag",
            "day_tag_match",
        ])
        writer.writerow([
            metrics.scenario_id,
            metrics.timetable_rows_count,
            metrics.served_trip_count,
            metrics.unserved_trip_count,
            metrics.departure_arrival_match_count,
            metrics.departure_arrival_checked_count,
            f"{metrics.departure_arrival_match_rate:.6f}",
            f"{metrics.checked_coverage_rate:.6f}",
            metrics.missing_in_prepared_count,
            metrics.missing_in_result_dispatch_count,
            metrics.prepared_day_tag,
            metrics.result_day_tag,
            str(metrics.day_tag_match),
        ])

    md_path = out_dir / "timetable_alignment_audit.md"
    md_path.write_text(
        "\n".join(
            [
                "# Timetable Alignment Audit",
                "",
                f"- generated_at: {payload['generated_at']}",
                f"- scenario_id: {metrics.scenario_id}",
                f"- prepared_input_path: {metrics.prepared_input_path}",
                f"- optimization_result_path: {metrics.optimization_result_path}",
                "",
                "## KPI Summary",
                "",
                "| KPI | Value |",
                "|---|---:|",
                f"| timetable_rows_count | {metrics.timetable_rows_count} |",
                f"| served_trip_count | {metrics.served_trip_count} |",
                f"| unserved_trip_count | {metrics.unserved_trip_count} |",
                f"| departure_arrival_match_count | {metrics.departure_arrival_match_count} |",
                f"| departure_arrival_checked_count | {metrics.departure_arrival_checked_count} |",
                f"| departure_arrival_match_rate | {metrics.departure_arrival_match_rate:.4%} |",
                f"| checked_coverage_rate | {metrics.checked_coverage_rate:.4%} |",
                f"| missing_in_prepared_count | {metrics.missing_in_prepared_count} |",
                f"| missing_in_result_dispatch_count | {metrics.missing_in_result_dispatch_count} |",
                f"| prepared_day_tag | {metrics.prepared_day_tag} |",
                f"| result_day_tag | {metrics.result_day_tag} |",
                f"| day_tag_match | {metrics.day_tag_match} |",
                "",
                "## Interpretation",
                "",
                "- match_rate is computed only over served trips that are resolvable in both prepared trips and dispatch_report trips.",
                "- checked_coverage_rate = departure_arrival_checked_count / served_trip_count.",
                "- unserved_trip_count is sourced from optimization summary first, and falls back to solver_result.unserved_tasks length.",
                "- if day_tag_match is false, prepared_input and optimization_result may represent different service-day data, and match_rate should not be used for quality judgment.",
                "- evidence details are in timetable_alignment_audit.json.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit timetable alignment against optimization output.")
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-path", default="")
    parser.add_argument("--optimization-result-path", default="")
    parser.add_argument("--out-dir", default="outputs/audit")
    args = parser.parse_args()

    prepared_path = Path(args.prepared_input_path) if args.prepared_input_path else _discover_prepared_input(args.scenario_id)
    optimization_path = Path(args.optimization_result_path) if args.optimization_result_path else _discover_optimization_result(args.scenario_id)

    prepared = _load_json(prepared_path)
    optimization = _load_json(optimization_path)
    metrics, evidence = compute_metrics(prepared, optimization)
    metrics.prepared_input_path = str(prepared_path).replace("\\", "/")
    metrics.optimization_result_path = str(optimization_path).replace("\\", "/")

    write_outputs(metrics, evidence, Path(args.out_dir))


if __name__ == "__main__":
    main()
