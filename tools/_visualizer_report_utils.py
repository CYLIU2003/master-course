from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from collections import Counter
import shutil
from typing import Any, Iterable, List, Mapping, Optional


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATE_SEGMENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_LAYOUT_SEGMENTS = {"optimization", "simulation"}


def outputs_root() -> Path:
    value = str(os.environ.get("MC_OUTPUTS_DIR") or "").strip()
    if value:
        return Path(value)
    return _REPO_ROOT / "output"


@dataclass(frozen=True)
class RunMeta:
    date: str
    scenario_id: str
    depot: str
    service: str
    run_id: str
    run_dir: Path
    status: str
    objective_value: Optional[float]
    solve_time_sec: Optional[float]
    total_cost: Optional[float]
    total_co2_kg: Optional[float]
    trip_count_served: Optional[int] = None
    trip_count_unserved: Optional[int] = None
    vehicle_count_used: Optional[int] = None
    mode: str = ""
    objective_mode: str = ""
    prepared_input_id: str = ""
    supports_exact_milp: Optional[bool] = None
    termination_reason: str = ""
    plan_source: str = ""
    source_kind: str = "run_dir"
    report_bundle_dir: Optional[Path] = None
    report_bundle_name: str = ""
    service_date: str = ""
    planning_days: Optional[int] = None
    route_count: Optional[int] = None
    vehicle_count_available: Optional[int] = None
    charger_count_available: Optional[int] = None
    simulation_result_path: Optional[Path] = None
    simulation_source: str = ""
    simulation_feasible: Optional[bool] = None
    simulation_total_distance_km: Optional[float] = None
    simulation_total_energy_kwh: Optional[float] = None
    simulation_total_cost: Optional[float] = None
    simulation_total_co2_kg: Optional[float] = None
    simulation_feasibility_violation_count: Optional[int] = None
    simulation_issue_summary: str = ""

    @property
    def exactness_label(self) -> str:
        mode = str(self.mode or "").strip().lower()
        status = str(self.status or "").strip().lower()
        plan_source = str(self.plan_source or "").strip().lower()
        if mode == "milp":
            if bool(self.supports_exact_milp) and plan_source == "milp_gurobi":
                if status == "optimal":
                    return "exact_optimal"
                return "exact_incumbent"
            return "fallback"
        if mode:
            return "metaheuristic"
        return "unknown"


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def normalize_mode_label(value: Any) -> str:
    raw = pick_text(value).lower()
    if not raw:
        return ""
    mapping = {
        "mode_milp_only": "milp",
        "mode_alns_only": "alns",
        "mode_ga_only": "ga",
        "mode_abc_only": "abc",
        "milp": "milp",
        "alns": "alns",
        "ga": "ga",
        "abc": "abc",
        "hybrid": "hybrid",
    }
    if raw in mapping:
        return mapping[raw]
    if raw.startswith("mode_") and raw.endswith("_only"):
        return raw[len("mode_") : -len("_only")]
    return raw


def read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def resolve_simulation_result_path(
    run_dir: Path,
    optimization_result: Mapping[str, Any] | None,
) -> Optional[Path]:
    local_path = run_dir / "simulation_result.json"
    if local_path.exists():
        return local_path
    return None


def load_run_payloads(run_dir: Path) -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for name, filename in {
        "summary": "summary.json",
        "optimization_result": "optimization_result.json",
        "canonical_solver_result": "canonical_solver_result.json",
        "cost_breakdown_detail": "cost_breakdown_detail.json",
        "co2_breakdown": "co2_breakdown.json",
        "kpi_summary": "kpi_summary.json",
        "run_manifest": "run_manifest.json",
    }.items():
        payloads[name] = read_json(run_dir / filename) or {}
    simulation_result_path = resolve_simulation_result_path(
        run_dir,
        payloads.get("optimization_result"),
    )
    payloads["simulation_result"] = (
        read_json(simulation_result_path) or {}
        if simulation_result_path is not None
        else {}
    )
    payloads["simulation_result_meta"] = (
        {"path": str(simulation_result_path)}
        if simulation_result_path is not None
        else {}
    )
    return payloads


def parse_run_path(run_dir: Path) -> dict[str, str]:
    parts = [part for part in run_dir.as_posix().split("/") if part]
    date_index = next((idx for idx, part in enumerate(parts) if _DATE_SEGMENT_RE.match(part)), None)
    run_index = next((idx for idx in range(len(parts) - 1, -1, -1) if parts[idx].startswith("run_")), None)
    if date_index is not None and run_index is not None:
        run_id = parts[run_index]
        if run_index == date_index + 1:
            return {
                "date": parts[date_index],
                "scenario_id": "unknown",
                "mode": "",
                "depot": "unknown",
                "service": "unknown",
                "run_id": run_id,
            }

        stage_index = next(
            (
                idx
                for idx in range(date_index + 1, run_index)
                if parts[idx] in _RUN_LAYOUT_SEGMENTS
            ),
            None,
        )
        if stage_index is not None and run_index >= stage_index + 4:
            return {
                "date": parts[date_index],
                "scenario_id": parts[stage_index + 1],
                "mode": "",
                "depot": parts[stage_index + 2],
                "service": parts[stage_index + 3],
                "run_id": run_id,
            }
        if run_index >= date_index + 4:
            return {
                "date": parts[date_index],
                "scenario_id": parts[date_index + 1],
                "mode": "",
                "depot": parts[date_index + 2],
                "service": parts[date_index + 3],
                "run_id": run_id,
            }
    return {
        "date": "unknown",
        "scenario_id": "unknown",
        "mode": "",
        "depot": "unknown",
        "service": "unknown",
        "run_id": run_dir.name,
    }


def extract_total_cost(
    summary: Mapping[str, Any] | None,
    cost_detail: Mapping[str, Any] | None,
    optimization_result: Mapping[str, Any] | None,
) -> Optional[float]:
    if isinstance(optimization_result, Mapping):
        cost_breakdown = optimization_result.get("cost_breakdown")
        if isinstance(cost_breakdown, Mapping):
            for key in ("total_cost", "total_cost_with_assets", "objective_value"):
                value = safe_float(cost_breakdown.get(key))
                if value is not None:
                    return value

    if isinstance(summary, Mapping):
        cost_breakdown = summary.get("cost_breakdown")
        if isinstance(cost_breakdown, Mapping):
            value = safe_float(cost_breakdown.get("total_operating_cost"))
            if value is not None:
                return value

    if isinstance(cost_detail, Mapping):
        value = safe_float(cost_detail.get("total_operating_cost"))
        if value is not None:
            return value
        items = cost_detail.get("cost_breakdown")
        if isinstance(items, list):
            nums = [
                safe_float(item.get("yen"))
                for item in items
                if isinstance(item, Mapping)
            ]
            values = [item for item in nums if item is not None]
            if values:
                return float(sum(values))
    return None


def extract_total_co2(
    summary: Mapping[str, Any] | None,
    co2_detail: Mapping[str, Any] | None,
    optimization_result: Mapping[str, Any] | None,
) -> Optional[float]:
    if isinstance(optimization_result, Mapping):
        cost_breakdown = optimization_result.get("cost_breakdown")
        if isinstance(cost_breakdown, Mapping):
            value = safe_float(cost_breakdown.get("total_co2_kg"))
            if value is not None:
                return value
    if isinstance(co2_detail, Mapping):
        value = safe_float(co2_detail.get("total_co2_kg"))
        if value is not None:
            return value
    if isinstance(summary, Mapping):
        kpi = summary.get("kpi")
        if isinstance(kpi, Mapping):
            value = safe_float(kpi.get("total_co2_kg"))
            if value is not None:
                return value
    return None


def discover_run_dirs(base_dir: Path) -> List[Path]:
    run_dirs: List[Path] = []
    if not base_dir.exists():
        return run_dirs
    for path in base_dir.rglob("run_*"):
        if not path.is_dir():
            continue
        parsed = parse_run_path(path)
        if parsed.get("date", "unknown") == "unknown":
            continue
        has_summary = (path / "summary.json").exists()
        has_gantt = (path / "vehicle_timeline_gantt.csv").exists()
        has_optimization = (path / "optimization_result.json").exists()
        has_simulation = (path / "simulation_result.json").exists()
        if has_summary or has_gantt or has_optimization or has_simulation:
            run_dirs.append(path)
    run_dirs.sort(key=lambda item: item.as_posix())
    return run_dirs


def discover_report_bundle_dirs(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        return []
    if (base_dir / "comparison.json").exists():
        return [base_dir]
    bundles = sorted({path.parent for path in base_dir.rglob("comparison.json") if path.is_file()}, key=lambda item: item.as_posix())
    return bundles


def collect_run_meta(
    run_dir: Path,
    *,
    overlay: Mapping[str, Any] | None = None,
    source_kind: str = "run_dir",
    report_bundle_dir: Optional[Path] = None,
    manifest_defaults: Mapping[str, Any] | None = None,
) -> RunMeta:
    parsed = parse_run_path(run_dir)
    payloads = load_run_payloads(run_dir)
    summary = payloads["summary"]
    optimization_result = payloads["optimization_result"]
    canonical = payloads["canonical_solver_result"]
    cost_detail = payloads["cost_breakdown_detail"]
    co2_detail = payloads["co2_breakdown"]
    run_manifest = payloads["run_manifest"]
    simulation_result = payloads["simulation_result"]
    simulation_result_meta = payloads["simulation_result_meta"]

    summary_block = optimization_result.get("summary") if isinstance(optimization_result.get("summary"), Mapping) else {}
    prepared_scope_summary = (
        optimization_result.get("prepared_scope_summary")
        if isinstance(optimization_result.get("prepared_scope_summary"), Mapping)
        else {}
    )
    build_report = (
        optimization_result.get("build_report")
        if isinstance(optimization_result.get("build_report"), Mapping)
        else {}
    )
    canonical_metadata = canonical.get("metadata") if isinstance(canonical.get("metadata"), Mapping) else {}
    solver_metadata = canonical.get("solver_metadata") if isinstance(canonical.get("solver_metadata"), Mapping) else {}
    simulation_summary = (
        simulation_result.get("simulation_summary")
        if isinstance(simulation_result.get("simulation_summary"), Mapping)
        else {}
    )
    simulation_violations = simulation_result.get("feasibility_violations")
    if not isinstance(simulation_violations, list):
        simulation_violations = simulation_summary.get("feasibility_violations")
    if not isinstance(simulation_violations, list):
        simulation_violations = []
    simulation_issue_counts = Counter(
        str(item.get("category") or "unknown")
        for item in simulation_violations
        if isinstance(item, Mapping)
    )
    simulation_issue_summary = ", ".join(
        f"{category}={count}"
        for category, count in sorted(simulation_issue_counts.items())
    )
    overlay_map = dict(overlay or {})
    manifest_map = dict(manifest_defaults or {})

    mode = normalize_mode_label(
        pick_text(
        overlay_map.get("mode"),
        optimization_result.get("mode"),
        optimization_result.get("solver_mode"),
        parsed.get("mode"),
        )
    )
    return RunMeta(
        date=pick_text(parsed.get("date")),
        scenario_id=pick_text(
            optimization_result.get("scenario_id"),
            manifest_map.get("scenario_id"),
            parsed.get("scenario_id"),
        ),
        depot=pick_text(
            (optimization_result.get("scope") or {}).get("depotId"),
            manifest_map.get("depot_id"),
            parsed.get("depot"),
        ),
        service=pick_text(
            (optimization_result.get("scope") or {}).get("serviceId"),
            manifest_map.get("service_id"),
            parsed.get("service"),
        ),
        run_id=pick_text(parsed.get("run_id"), run_dir.name),
        run_dir=run_dir,
        status=pick_text(
            overlay_map.get("solver_status"),
            canonical.get("solver_status"),
            optimization_result.get("solver_status"),
            summary.get("solver_status"),
            summary.get("status"),
            "UNKNOWN",
        ),
        objective_value=(
            safe_float(overlay_map.get("objective_value"))
            if safe_float(overlay_map.get("objective_value")) is not None
            else (
                safe_float(canonical.get("objective_value"))
                if safe_float(canonical.get("objective_value")) is not None
                else safe_float(optimization_result.get("objective_value"))
            )
        ),
        solve_time_sec=(
            safe_float(overlay_map.get("solve_time_seconds"))
            if safe_float(overlay_map.get("solve_time_seconds")) is not None
            else (
                safe_float(optimization_result.get("solve_time_seconds"))
                if safe_float(optimization_result.get("solve_time_seconds")) is not None
                else safe_float(summary.get("solve_time_seconds") or summary.get("solve_time_sec"))
            )
        ),
        total_cost=extract_total_cost(summary, cost_detail, optimization_result),
        total_co2_kg=extract_total_co2(summary, co2_detail, optimization_result),
        trip_count_served=(
            safe_int(overlay_map.get("trip_count_served"))
            if safe_int(overlay_map.get("trip_count_served")) is not None
            else safe_int(summary_block.get("trip_count_served"))
        ),
        trip_count_unserved=(
            safe_int(overlay_map.get("trip_count_unserved"))
            if safe_int(overlay_map.get("trip_count_unserved")) is not None
            else safe_int(summary_block.get("trip_count_unserved"))
        ),
        vehicle_count_used=(
            safe_int(overlay_map.get("vehicle_count_used"))
            if safe_int(overlay_map.get("vehicle_count_used")) is not None
            else safe_int(summary_block.get("vehicle_count_used"))
        ),
        mode=mode,
        objective_mode=pick_text(
            optimization_result.get("objective_mode"),
            manifest_map.get("objective_mode"),
        ),
        prepared_input_id=pick_text(
            optimization_result.get("prepared_input_id"),
            manifest_map.get("prepared_input_id"),
            run_manifest.get("prepared_input_id"),
        ),
        supports_exact_milp=(
            bool(overlay_map.get("supports_exact_milp"))
            if overlay_map.get("supports_exact_milp") is not None
            else (
                bool(solver_metadata.get("supports_exact_milp"))
                if solver_metadata.get("supports_exact_milp") is not None
                else None
            )
        ),
        termination_reason=pick_text(
            overlay_map.get("termination_reason"),
            canonical.get("termination_reason"),
            solver_metadata.get("termination_reason"),
        ),
        plan_source=pick_text(
            overlay_map.get("plan_source"),
            canonical_metadata.get("source"),
        ),
        source_kind=source_kind,
        report_bundle_dir=report_bundle_dir,
        report_bundle_name=report_bundle_dir.name if report_bundle_dir is not None else "",
        service_date=pick_text(
            prepared_scope_summary.get("service_date"),
            next(
                (
                    str(item).strip()
                    for item in list(prepared_scope_summary.get("service_dates") or [])
                    if str(item).strip()
                ),
                "",
            ),
        ),
        planning_days=safe_int(
            prepared_scope_summary.get("planning_days")
            if prepared_scope_summary.get("planning_days") is not None
            else manifest_map.get("planning_days")
        ),
        route_count=(
            len(prepared_scope_summary.get("route_ids") or [])
            if isinstance(prepared_scope_summary.get("route_ids"), list)
            else None
        ),
        vehicle_count_available=safe_int(build_report.get("vehicle_count")),
        charger_count_available=safe_int(build_report.get("charger_count")),
        simulation_result_path=(
            Path(str(simulation_result_meta.get("path")))
            if pick_text(simulation_result_meta.get("path"))
            else None
        ),
        simulation_source=pick_text(simulation_result.get("source")),
        simulation_feasible=(
            safe_bool(simulation_summary.get("feasible"))
            if safe_bool(simulation_summary.get("feasible")) is not None
            else (len(simulation_violations) == 0 if simulation_result else None)
        ),
        simulation_total_distance_km=safe_float(simulation_result.get("total_distance_km")),
        simulation_total_energy_kwh=safe_float(simulation_result.get("total_energy_kwh")),
        simulation_total_cost=safe_float(
            simulation_summary.get("total_operating_cost")
        ),
        simulation_total_co2_kg=safe_float(
            simulation_summary.get("total_co2_kg")
        ),
        simulation_feasibility_violation_count=len(simulation_violations)
        if simulation_result
        else None,
        simulation_issue_summary=simulation_issue_summary,
    )


def collect_run_metas_from_report_bundle(report_dir: Path) -> List[RunMeta]:
    comparison_path = report_dir / "comparison.json"
    manifest_path = report_dir / "run_manifest.json"
    comparison = []
    try:
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    except Exception:
        comparison = []
    manifest = read_json(manifest_path) or {}
    runs = []
    for row in comparison:
        if not isinstance(row, Mapping):
            continue
        run_dir_text = pick_text(row.get("run_dir"))
        if not run_dir_text:
            continue
        run_dir = Path(run_dir_text)
        runs.append(
            collect_run_meta(
                run_dir,
                overlay=row,
                source_kind="report_bundle",
                report_bundle_dir=report_dir,
                manifest_defaults=manifest,
            )
        )
    return runs


def collect_run_metas(base_dir: Path) -> List[RunMeta]:
    report_bundle_dirs = discover_report_bundle_dirs(base_dir)
    items: List[RunMeta] = []
    seen: set[str] = set()
    for report_dir in report_bundle_dirs:
        for meta in collect_run_metas_from_report_bundle(report_dir):
            key = str(meta.run_dir.resolve()) if meta.run_dir.exists() else str(meta.run_dir)
            if key in seen:
                continue
            seen.add(key)
            items.append(meta)
    for run_dir in discover_run_dirs(base_dir):
        key = str(run_dir.resolve()) if run_dir.exists() else str(run_dir)
        if key in seen:
            continue
        seen.add(key)
        items.append(collect_run_meta(run_dir))
    items.sort(key=lambda item: (item.date, item.scenario_id, item.depot, item.service, item.run_id))
    return items


def resolve_run_dir_input(path: Path) -> tuple[Path, dict[str, Any]]:
    if path.is_dir() and (path / "comparison.json").exists():
        report_metas = collect_run_metas_from_report_bundle(path)
        if not report_metas:
            raise ValueError("comparison.json はありますが、有効な run_dir を解決できません。")
        sorted_metas = sorted(
            report_metas,
            key=lambda item: (
                item.objective_value if item.objective_value is not None else float("inf"),
                item.run_id,
            ),
        )
        selected = sorted_metas[0]
        return selected.run_dir, {
            "input_kind": "report_bundle",
            "report_bundle_dir": str(path),
            "selected_run_id": selected.run_id,
            "selected_mode": selected.mode,
            "selection_rule": "best_objective_in_comparison_bundle",
        }
    if path.is_dir():
        return path, {"input_kind": "run_dir"}
    raise ValueError("指定パスはディレクトリではありません。")


def fmt_num(value: Optional[float], nd: int = 2) -> str:
    if value is None:
        return "NA"
    return f"{value:,.{nd}f}"


def _ordered_solver_rows(rows: Iterable[RunMeta]) -> List[RunMeta]:
    order = {"milp": 0, "alns": 1, "ga": 2, "abc": 3}
    return sorted(
        list(rows),
        key=lambda row: (
            order.get(str(row.mode or "").strip().lower(), 99),
            row.run_id,
        ),
    )


def _safe_path_token(value: Any, *, fallback: str) -> str:
    text = pick_text(value, fallback)
    chars = [
        ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
        for ch in text
    ]
    normalized = "".join(chars).strip("._")
    return normalized or fallback


def build_solver_comparison_rows(metas: Iterable[RunMeta]) -> List[dict[str, Any]]:
    rows = _ordered_solver_rows(metas)
    if not rows:
        return []

    best_objective = min(
        (row.objective_value for row in rows if row.objective_value is not None),
        default=None,
    )
    scoped_trip_count = max(
        (
            (row.trip_count_served or 0) + (row.trip_count_unserved or 0)
            for row in rows
            if row.trip_count_served is not None or row.trip_count_unserved is not None
        ),
        default=None,
    )

    items: List[dict[str, Any]] = []
    for row in rows:
        total_trips = scoped_trip_count
        if total_trips is None and row.trip_count_served is not None and row.trip_count_unserved is not None:
            total_trips = row.trip_count_served + row.trip_count_unserved
        items.append(
            {
                "solver": row.mode or "",
                "run_id": row.run_id,
                "status": row.status or "",
                "exactness": row.exactness_label,
                "objective_value": row.objective_value,
                "objective_gap_to_best": (
                    row.objective_value - best_objective
                    if row.objective_value is not None and best_objective is not None
                    else None
                ),
                "total_cost_jpy": row.total_cost,
                "total_co2_kg": row.total_co2_kg,
                "solve_time_sec": row.solve_time_sec,
                "trip_count_served": row.trip_count_served,
                "trip_count_total": total_trips,
                "trip_count_unserved": row.trip_count_unserved,
                "served_summary": (
                    f"{row.trip_count_served} / {total_trips}"
                    if row.trip_count_served is not None and total_trips is not None
                    else ""
                ),
                "vehicle_count_used": row.vehicle_count_used,
                "supports_exact_milp": row.supports_exact_milp,
                "termination_reason": row.termination_reason,
                "plan_source": row.plan_source,
                "route_band_diagram_dir": str(row.run_dir / "graph" / "route_band_diagrams"),
                "run_dir": str(row.run_dir),
            }
        )
    return items


def build_solver_comparison_markdown(
    metas: Iterable[RunMeta],
    *,
    title: str = "4 Solver Comparison",
) -> str:
    rows = build_solver_comparison_rows(metas)
    if not rows:
        return f"# {title}\n\n対象 run がありません。\n"

    lines = [
        f"# {title}",
        "",
        "| solver | run | status | exactness | solve time [s] | objective | best gap | served / total | unserved | vehicles | total cost [JPY] | route-band dir |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + f"{row['solver'] or '-'} | {row['run_id']} | {row['status'] or '-'} | {row['exactness']} | {fmt_num(safe_float(row.get('solve_time_sec')), 2)} | {fmt_num(safe_float(row.get('objective_value')), 4)} | {fmt_num(safe_float(row.get('objective_gap_to_best')), 4)} | {row.get('served_summary') or 'NA'} | {row.get('trip_count_unserved', 'NA')} | {row.get('vehicle_count_used', 'NA')} | {fmt_num(safe_float(row.get('total_cost_jpy')), 2)} | `{row.get('route_band_diagram_dir') or '-'}` |"
        )
    return "\n".join(lines) + "\n"


def write_solver_comparison_exports(
    metas: Iterable[RunMeta],
    out_root: Path,
) -> dict[str, Path]:
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    rows = build_solver_comparison_rows(metas)
    csv_path = out_root / "solver_comparison_table.csv"
    md_path = out_root / "solver_comparison_table.md"
    fieldnames = [
        "solver",
        "run_id",
        "status",
        "exactness",
        "solve_time_sec",
        "objective_value",
        "objective_gap_to_best",
        "total_cost_jpy",
        "total_co2_kg",
        "trip_count_served",
        "trip_count_total",
        "trip_count_unserved",
        "served_summary",
        "vehicle_count_used",
        "supports_exact_milp",
        "termination_reason",
        "plan_source",
        "route_band_diagram_dir",
        "run_dir",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    md_path.write_text(
        build_solver_comparison_markdown(metas, title="4 Solver Comparison"),
        encoding="utf-8",
    )
    return {
        "csv_path": csv_path,
        "markdown_path": md_path,
    }


def export_route_band_diagram_assets(
    metas: Iterable[RunMeta],
    out_root: Path,
) -> dict[str, Any]:
    rows = _ordered_solver_rows(metas)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    if not rows:
        return {
            "best_bundle_route_band_dir": None,
            "manifest_path": None,
            "copied_solver_count": 0,
            "copied_diagram_count": 0,
        }

    best_row = min(
        rows,
        key=lambda row: (
            row.objective_value if row.objective_value is not None else float("inf"),
            row.run_id,
        ),
    )
    solver_root = out_root / "solver_route_band_diagrams"
    graph_root = out_root / "graph"
    copied_solver_count = 0
    copied_diagram_count = 0
    best_bundle_route_band_dir: Optional[Path] = None
    manifest_rows: List[dict[str, Any]] = []

    for row in rows:
        source_dir = row.run_dir / "graph" / "route_band_diagrams"
        manifest_path = source_dir / "manifest.json"
        source_manifest = read_json(manifest_path)
        diagram_count = len(source_manifest.get("entries") or []) if isinstance(source_manifest, dict) else 0
        if isinstance(source_manifest, dict) and diagram_count == 0 and source_dir.exists():
            diagram_count = len([path for path in source_dir.rglob("*.svg") if path.is_file()])
        available = source_dir.exists() and source_manifest is not None
        target_dir: Optional[Path] = None
        if available:
            copied_solver_count += 1
            copied_diagram_count += diagram_count
            target_dir = solver_root / (
                f"{_safe_path_token(row.mode or 'unknown', fallback='mode')}"
                f"_{_safe_path_token(row.run_id, fallback='run')}"
            )
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, target_dir)
            if row.run_id == best_row.run_id:
                best_bundle_route_band_dir = graph_root / "route_band_diagrams"
                if best_bundle_route_band_dir.exists():
                    shutil.rmtree(best_bundle_route_band_dir)
                best_bundle_route_band_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_dir, best_bundle_route_band_dir)
        manifest_rows.append(
            {
                "solver": row.mode or "",
                "run_id": row.run_id,
                "source_run_dir": str(row.run_dir),
                "source_route_band_dir": str(source_dir),
                "available": available,
                "diagram_count": diagram_count,
                "copied_to": str(target_dir) if target_dir is not None else "",
                "best_run": row.run_id == best_row.run_id,
            }
        )

    manifest_payload = {
        "schema_version": "route_band_bundle_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "best_run_id": best_row.run_id,
        "best_mode": best_row.mode,
        "best_bundle_route_band_dir": (
            str(best_bundle_route_band_dir) if best_bundle_route_band_dir is not None else ""
        ),
        "copied_solver_count": copied_solver_count,
        "copied_diagram_count": copied_diagram_count,
        "entries": manifest_rows,
    }
    manifest_path = out_root / "solver_route_band_diagrams_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "best_bundle_route_band_dir": best_bundle_route_band_dir,
        "manifest_path": manifest_path,
        "copied_solver_count": copied_solver_count,
        "copied_diagram_count": copied_diagram_count,
    }


def build_professor_report_markdown(
    metas: Iterable[RunMeta],
    *,
    title: str = "教授向けシナリオ報告",
) -> str:
    rows = _ordered_solver_rows(metas)
    if not rows:
        return f"# {title}\n\n対象 run がありません。\n"

    common_scenario = {row.scenario_id for row in rows if row.scenario_id}
    common_prepared = {row.prepared_input_id for row in rows if row.prepared_input_id}
    common_depot = {row.depot for row in rows if row.depot}
    common_service = {row.service for row in rows if row.service}
    common_objective_mode = {row.objective_mode for row in rows if row.objective_mode}
    common_report_bundle = {row.report_bundle_name for row in rows if row.report_bundle_name}
    common_report_bundle_dirs = {
        row.report_bundle_dir
        for row in rows
        if row.report_bundle_dir is not None
    }
    common_service_date = {row.service_date for row in rows if row.service_date}
    common_planning_days = {row.planning_days for row in rows if row.planning_days is not None}
    common_route_count = {row.route_count for row in rows if row.route_count is not None}
    common_vehicle_count = {
        row.vehicle_count_available
        for row in rows
        if row.vehicle_count_available is not None
    }
    common_charger_count = {
        row.charger_count_available
        for row in rows
        if row.charger_count_available is not None
    }

    best_row = min(
        rows,
        key=lambda row: (row.objective_value if row.objective_value is not None else float("inf"), row.run_id),
    )

    lines = [f"# {title}", ""]
    lines.append("## 対象")
    if len(common_scenario) == 1:
        lines.append(f"- scenario_id: `{next(iter(common_scenario))}`")
    if len(common_prepared) == 1:
        lines.append(f"- prepared_input_id: `{next(iter(common_prepared))}`")
    if len(common_depot) == 1:
        lines.append(f"- depot: `{next(iter(common_depot))}`")
    if len(common_service) == 1:
        lines.append(f"- service: `{next(iter(common_service))}`")
    if len(common_objective_mode) == 1:
        lines.append(f"- objective_mode: `{next(iter(common_objective_mode))}`")
    if len(common_report_bundle) == 1:
        lines.append(f"- comparison_bundle: `{next(iter(common_report_bundle))}`")
    lines.append("")
    lines.append("## シナリオ詳細")
    if len(common_service_date) == 1:
        lines.append(f"- service_date: `{next(iter(common_service_date))}`")
    if len(common_planning_days) == 1:
        lines.append(f"- planning_days: `{next(iter(common_planning_days))}`")
    if len(common_route_count) == 1:
        lines.append(f"- route_count: `{next(iter(common_route_count))}`")
    if len(common_vehicle_count) == 1:
        lines.append(f"- candidate_vehicle_count: `{next(iter(common_vehicle_count))}`")
    if len(common_charger_count) == 1:
        lines.append(f"- candidate_charger_count: `{next(iter(common_charger_count))}`")
    scoped_trip_count = None
    if best_row.trip_count_served is not None and best_row.trip_count_unserved is not None:
        scoped_trip_count = best_row.trip_count_served + best_row.trip_count_unserved
    if scoped_trip_count is not None:
        lines.append(f"- scoped_trip_count: `{scoped_trip_count}`")
    lines.append("")
    lines.append("## 最適化結果")
    lines.append("")
    lines.append("| run | mode | status | exactness | objective | total cost [JPY] | total CO2 [kg] | solve time [s] | served | unserved | vehicles | termination | plan source |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for row in rows:
        lines.append(
            "| "
            + f"{row.run_id} | {row.mode or '-'} | {row.status or '-'} | {row.exactness_label} | {fmt_num(row.objective_value, 4)} | {fmt_num(row.total_cost, 2)} | {fmt_num(row.total_co2_kg, 3)} | {fmt_num(row.solve_time_sec, 2)} | {row.trip_count_served if row.trip_count_served is not None else 'NA'} | {row.trip_count_unserved if row.trip_count_unserved is not None else 'NA'} | {row.vehicle_count_used if row.vehicle_count_used is not None else 'NA'} | {row.termination_reason or '-'} | {row.plan_source or '-'} |"
        )
    lines.append("")
    lines.append("## 判定")
    lines.append(f"- best_objective_run: `{best_row.run_id}`")
    lines.append(f"- best_objective_mode: `{best_row.mode or '-'}`")
    lines.append(f"- best_objective_value: `{fmt_num(best_row.objective_value, 4)}`")
    lines.append(f"- best_run_status: `{best_row.status or '-'}`")
    lines.append(f"- best_run_exactness: `{best_row.exactness_label}`")
    all_served = all((row.trip_count_unserved or 0) == 0 for row in rows if row.trip_count_unserved is not None)
    lines.append(f"- all_runs_unserved_zero: `{all_served}`")
    milp_rows = [row for row in rows if str(row.mode or '').lower() == "milp"]
    if milp_rows:
        milp = milp_rows[0]
        lines.append(
            f"- milp_exactness: `{milp.exactness_label}` (status=`{milp.status}`, supports_exact_milp=`{milp.supports_exact_milp}`, plan_source=`{milp.plan_source or '-'}`)"
        )
    lines.append("")
    lines.append("## シミュレーション結果")
    simulation_rows = [row for row in rows if row.simulation_result_path is not None]
    simulation_row = next(
        (row for row in simulation_rows if row.run_id == best_row.run_id),
        simulation_rows[0] if simulation_rows else None,
    )
    if simulation_row is None:
        lines.append("- simulation_result: `not_found`")
        lines.append("- optimization run 直下に無い場合は `output/<feed>/<snapshot>/simulation/...` を参照する。未実行ならその旨を明示する。")
    else:
        lines.append(f"- linked_run: `{simulation_row.run_id}`")
        lines.append(f"- simulation_source: `{simulation_row.simulation_source or '-'}`")
        lines.append(f"- simulation_feasible: `{simulation_row.simulation_feasible}`")
        lines.append(f"- simulation_total_distance_km: `{fmt_num(simulation_row.simulation_total_distance_km, 3)}`")
        lines.append(f"- simulation_total_energy_kwh: `{fmt_num(simulation_row.simulation_total_energy_kwh, 3)}`")
        lines.append(f"- simulation_total_cost_jpy: `{fmt_num(simulation_row.simulation_total_cost, 2)}`")
        lines.append(f"- simulation_total_co2_kg: `{fmt_num(simulation_row.simulation_total_co2_kg, 3)}`")
        lines.append(
            f"- simulation_feasibility_violations: `{simulation_row.simulation_feasibility_violation_count if simulation_row.simulation_feasibility_violation_count is not None else 'NA'}`"
        )
        if simulation_row.simulation_issue_summary:
            lines.append(f"- simulation_issue_breakdown: `{simulation_row.simulation_issue_summary}`")
        lines.append(f"- simulation_result_path: `{simulation_row.simulation_result_path}`")
    lines.append("")
    lines.append("## 可視化アセット")
    bundle_route_band_dir = None
    bundle_solver_table = None
    if len(common_report_bundle_dirs) == 1:
        bundle_dir = next(iter(common_report_bundle_dirs))
        if bundle_dir is not None:
            candidate = bundle_dir / "graph" / "route_band_diagrams"
            if candidate.exists():
                bundle_route_band_dir = candidate
            candidate_table = bundle_dir / "solver_comparison_table.csv"
            if candidate_table.exists():
                bundle_solver_table = candidate_table
    best_route_band_dir = bundle_route_band_dir or (best_row.run_dir / "graph" / "route_band_diagrams")
    lines.append(
        f"- best_run_route_band_diagrams: `{best_route_band_dir if best_route_band_dir.exists() else 'not_found'}`"
    )
    if bundle_solver_table is not None:
        lines.append(f"- bundle_solver_comparison_table: `{bundle_solver_table}`")
    lines.append("")
    lines.append("## 参照ファイル")
    for row in rows:
        lines.append(f"- `{row.mode or row.run_id}`: `{row.run_dir}`")
    if simulation_row is not None and simulation_row.simulation_result_path is not None:
        lines.append(f"- simulation: `{simulation_row.simulation_result_path}`")
    if len(common_report_bundle) == 1:
        report_name = next(iter(common_report_bundle))
        report_dir = next((row.report_bundle_dir for row in rows if row.report_bundle_dir is not None), None)
        if report_dir is not None:
            verdict_path = report_dir / "verdict.md"
            if verdict_path.exists():
                lines.append(f"- verdict: `{verdict_path}`")
    lines.append("")
    return "\n".join(lines)
