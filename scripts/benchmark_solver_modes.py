from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from src.optimization.common.benchmarking import solver_benchmark_eligibility


class BFFClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = ""

    def _full_url(self, path: str, query: dict[str, Any] | None = None, prefix: str | None = None) -> str:
        pfx = self.api_prefix if prefix is None else prefix
        if not path.startswith("/"):
            path = "/" + path
        if pfx and not pfx.startswith("/"):
            pfx = "/" + pfx
        base = f"{self.base_url}{pfx}{path}"
        if not query:
            return base
        filtered = {k: v for k, v in query.items() if v is not None and v != ""}
        if not filtered:
            return base
        return f"{base}?{parse.urlencode(filtered)}"

    def _request_once(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        prefix: str | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(self._full_url(path, query=query, prefix=prefix), method=method, data=data, headers=headers)
        try:
            with request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Connection failed: {exc}") from exc

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._request_once(method, path, body=body, query=query)
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            alt = "/api" if self.api_prefix == "" else ""
            result = self._request_once(method, path, body=body, query=query, prefix=alt)
            self.api_prefix = alt
            return result

    def detect_api_prefix(self) -> str:
        for pfx in [self.api_prefix, "/api", ""]:
            try:
                self._request_once("GET", "/app/context", prefix=pfx)
                self.api_prefix = pfx
                return pfx
            except Exception:
                continue
        raise RuntimeError("Unable to detect BFF API prefix.")


def pick_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def pick_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(float(value))
        except Exception:
            continue
    return None


def pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


DEFAULT_SOLVER_DISPLAY_NAMES: dict[str, str] = {
    "mode_milp_only": "MILP",
    "mode_alns_only": "ALNS",
    "mode_hybrid": "MILPSeededALNS",
    "hybrid": "MILPSeededALNS",
    "ga": "GA prototype",
    "abc": "ABC prototype",
}

DEFAULT_SOLVER_MATURITY: dict[str, str] = {
    "mode_milp_only": "core",
    "mode_alns_only": "core",
    "mode_hybrid": "prototype",
    "hybrid": "prototype",
    "ga": "prototype",
    "abc": "prototype",
}

DEFAULT_TRUE_SOLVER_FAMILY: dict[str, str] = {
    "mode_milp_only": "milp",
    "mode_alns_only": "alns",
    "mode_hybrid": "milp_seeded_alns",
    "hybrid": "milp_seeded_alns",
    "ga": "ga",
    "abc": "abc",
}

CSV_FIELDNAMES = [
    "mode",
    "job_id",
    "job_status",
    "job_message",
    "job_progress",
    "status",
    "objective_value",
    "objective_at_60s",
    "objective_at_300s",
    "objective_at_600s",
    "objective_at_1500s",
    "solve_time_seconds",
    "total_wall_clock_sec",
    "first_feasible_sec",
    "incumbent_updates",
    "evaluator_calls",
    "avg_evaluator_sec",
    "repair_calls",
    "avg_repair_sec",
    "exact_repair_calls",
    "avg_exact_repair_sec",
    "feasible_candidate_ratio",
    "rejected_candidate_ratio",
    "fallback_count",
    "true_solver_family",
    "independent_implementation",
    "delegates_to",
    "solver_display_name",
    "solver_maturity",
    "eligible_for_main_benchmark",
    "eligible_for_appendix_benchmark",
    "benchmark_tier",
    "counts_for_comparison",
    "comparison_note",
    "candidate_generation_mode",
    "evaluation_mode",
    "has_feasible_incumbent",
    "incumbent_count",
    "warm_start_applied",
    "warm_start_source",
    "fallback_applied",
    "fallback_reason",
    "uses_exact_repair",
    "best_bound",
    "final_gap",
    "nodes_explored",
    "iis_generated",
    "presolve_reduction_summary",
    "trip_count_served",
    "trip_count_unserved",
    "vehicle_count_used",
    "same_day_depot_cycles_enabled",
    "max_depot_cycles_per_vehicle_per_day",
    "vehicle_fragment_counts",
    "vehicles_with_multiple_fragments",
    "max_fragments_observed",
    "submitted_at",
    "completed_at",
    "dated_run_dir",
    "prepared_input_id",
    "per_solver_result_json",
]


def _canonical_solver_result(result: dict[str, Any]) -> dict[str, Any]:
    canonical = result.get("canonical_solver_result")
    if isinstance(canonical, dict) and canonical:
        return dict(canonical)
    legacy = result.get("solver_result")
    if isinstance(legacy, dict) and legacy:
        return dict(legacy)
    return {}


def _solver_metadata(result: dict[str, Any], solver_result: dict[str, Any]) -> dict[str, Any]:
    metadata = solver_result.get("solver_metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    top_level = result.get("solver_metadata")
    if isinstance(top_level, dict):
        return dict(top_level)
    return {}


def _objective_at_checkpoint(incumbent_history: list[dict[str, Any]], checkpoint_sec: float) -> float | None:
    best_snapshot: dict[str, Any] | None = None
    best_elapsed = float("-inf")
    for snapshot in sorted(
        (snap for snap in incumbent_history if isinstance(snap, dict)),
        key=lambda snap: float(snap.get("wall_clock_sec") or 0.0),
    ):
        elapsed = float(snapshot.get("wall_clock_sec") or 0.0)
        if elapsed <= float(checkpoint_sec) and elapsed >= best_elapsed:
            best_snapshot = snapshot
            best_elapsed = elapsed
    if best_snapshot is None:
        return None
    objective_value = best_snapshot.get("objective_value")
    if objective_value is None:
        return None
    return float(objective_value)


def _default_eligibility(
    mode_label: str,
    *,
    solver_maturity: str,
    true_solver_family: str,
    solver_display_name: str,
) -> dict[str, Any]:
    return solver_benchmark_eligibility(
        mode_label,
        solver_maturity=solver_maturity,
        true_solver_family=true_solver_family,
        solver_display_name=solver_display_name,
    )


def _build_row(
    *,
    mode_label: str,
    result_payload: dict[str, Any],
    wall_clock_seconds: float,
    job_id: str = "",
    job_status: str = "",
    job_message: str = "",
    job_progress: Any = None,
    submitted_at: str = "",
    completed_at: str = "",
    dated_run_dir: str = "",
    prepared_input_id: str = "",
    result_json_path: Path | None = None,
) -> dict[str, Any]:
    solver_result = _canonical_solver_result(result_payload)
    solver_metadata = _solver_metadata(result_payload, solver_result)
    search_profile = dict(solver_metadata.get("search_profile") or {})
    incumbent_history = [
        snap
        for snap in (
            solver_result.get("incumbent_history")
            or result_payload.get("incumbent_history")
            or []
        )
        if isinstance(snap, dict)
    ]
    summary = dict(result_payload.get("summary") or solver_result.get("summary") or {})
    served_trip_ids = solver_result.get("served_trip_ids") or result_payload.get("served_trip_ids") or []
    unserved_trip_ids = solver_result.get("unserved_trip_ids") or result_payload.get("unserved_trip_ids") or []
    solver_display_name = pick_text(
        solver_metadata.get("solver_display_name"),
        DEFAULT_SOLVER_DISPLAY_NAMES.get(mode_label, mode_label.upper()),
    )
    solver_maturity = pick_text(
        solver_metadata.get("solver_maturity"),
        DEFAULT_SOLVER_MATURITY.get(mode_label, "core"),
    )
    true_solver_family = pick_text(
        solver_metadata.get("true_solver_family"),
        DEFAULT_TRUE_SOLVER_FAMILY.get(mode_label, mode_label.replace("mode_", "")),
    )
    eligibility = _default_eligibility(
        mode_label,
        solver_maturity=solver_maturity,
        true_solver_family=true_solver_family,
        solver_display_name=solver_display_name,
    )
    eligible_for_main = bool(
        solver_metadata.get("eligible_for_main_benchmark", eligibility["eligible_for_main_benchmark"])
    )
    eligible_for_appendix = bool(
        solver_metadata.get("eligible_for_appendix_benchmark", eligibility["eligible_for_appendix_benchmark"])
    )
    status = pick_text(
        result_payload.get("solver_status"),
        result_payload.get("status"),
        solver_result.get("solver_status"),
        solver_result.get("status"),
        "unknown",
    )
    objective_value = pick_number(
        result_payload.get("objective_value"),
        solver_result.get("objective_value"),
    )
    fallback_applied = bool(solver_metadata.get("fallback_applied"))
    has_feasible_incumbent = bool(solver_metadata.get("has_feasible_incumbent"))
    main_comparison_eligible = (
        eligible_for_main
        and status == "SOLVED_FEASIBLE"
        and has_feasible_incumbent
        and not fallback_applied
    )
    benchmark_tier = "main" if main_comparison_eligible else ("appendix" if eligible_for_appendix else "excluded")
    counts_for_comparison = benchmark_tier == "main"
    result = {
        "mode": mode_label,
        "job_id": job_id,
        "job_status": pick_text(job_status),
        "job_message": pick_text(job_message),
        "job_progress": job_progress,
        "status": status,
        "objective_value": objective_value,
        "objective_at_60s": _objective_at_checkpoint(incumbent_history, 60),
        "objective_at_300s": _objective_at_checkpoint(incumbent_history, 300),
        "objective_at_600s": _objective_at_checkpoint(incumbent_history, 600),
        "objective_at_1500s": _objective_at_checkpoint(incumbent_history, 1500),
        "solve_time_seconds": pick_number(
            result_payload.get("solve_time_seconds"),
            solver_result.get("solve_time_seconds"),
            search_profile.get("total_wall_clock_sec"),
            wall_clock_seconds,
        ),
        "total_wall_clock_sec": float(search_profile.get("total_wall_clock_sec") or wall_clock_seconds),
        "first_feasible_sec": search_profile.get("first_feasible_sec"),
        "incumbent_updates": int(search_profile.get("incumbent_updates", solver_metadata.get("incumbent_count", 0)) or 0),
        "evaluator_calls": int(search_profile.get("evaluator_calls", 0) or 0),
        "avg_evaluator_sec": float(search_profile.get("avg_evaluator_sec", 0.0) or 0.0),
        "repair_calls": int(search_profile.get("repair_calls", 0) or 0),
        "avg_repair_sec": float(search_profile.get("avg_repair_sec", 0.0) or 0.0),
        "exact_repair_calls": int(search_profile.get("exact_repair_calls", 0) or 0),
        "avg_exact_repair_sec": float(search_profile.get("avg_exact_repair_sec", 0.0) or 0.0),
        "feasible_candidate_ratio": float(search_profile.get("feasible_candidate_ratio", 0.0) or 0.0),
        "rejected_candidate_ratio": float(search_profile.get("rejected_candidate_ratio", 0.0) or 0.0),
        "fallback_count": int(search_profile.get("fallback_count", 0) or 0),
        "true_solver_family": true_solver_family,
        "independent_implementation": bool(solver_metadata.get("independent_implementation", True)),
        "delegates_to": pick_text(solver_metadata.get("delegates_to"), solver_metadata.get("delegate"), "none"),
        "solver_display_name": solver_display_name,
        "solver_maturity": solver_maturity,
        "eligible_for_main_benchmark": eligible_for_main,
        "eligible_for_appendix_benchmark": eligible_for_appendix,
        "benchmark_tier": benchmark_tier,
        "counts_for_comparison": counts_for_comparison,
        "comparison_note": pick_text(
            solver_metadata.get("comparison_note"),
            eligibility["comparison_note"],
        ),
        "candidate_generation_mode": pick_text(solver_metadata.get("candidate_generation_mode")),
        "evaluation_mode": pick_text(solver_metadata.get("evaluation_mode"), result_payload.get("objective_mode")),
        "has_feasible_incumbent": has_feasible_incumbent,
        "incumbent_count": int(solver_metadata.get("incumbent_count", len(incumbent_history)) or 0),
        "warm_start_applied": bool(solver_metadata.get("warm_start_applied")),
        "warm_start_source": pick_text(solver_metadata.get("warm_start_source")),
        "fallback_applied": fallback_applied,
        "fallback_reason": pick_text(solver_metadata.get("fallback_reason")),
        "uses_exact_repair": bool(
            solver_metadata.get(
                "uses_exact_repair",
                int(search_profile.get("exact_repair_calls", 0) or 0) > 0,
            )
        ),
        "best_bound": solver_metadata.get("best_bound"),
        "final_gap": solver_metadata.get("final_gap"),
        "nodes_explored": solver_metadata.get("nodes_explored"),
        "iis_generated": bool(solver_metadata.get("iis_generated")),
        "presolve_reduction_summary": dict(solver_metadata.get("presolve_reduction_summary") or {}),
        "trip_count_served": len(served_trip_ids) or int(summary.get("trip_count_served") or 0),
        "trip_count_unserved": len(unserved_trip_ids) or int(summary.get("trip_count_unserved") or 0),
        "vehicle_count_used": sum(1 for trip_ids in (result_payload.get("vehicle_paths") or {}).values() if trip_ids)
        or int(summary.get("vehicle_count_used") or 0),
        "same_day_depot_cycles_enabled": bool(
            solver_metadata.get(
                "same_day_depot_cycles_enabled",
                summary.get("same_day_depot_cycles_enabled", False),
            )
        ),
        "max_depot_cycles_per_vehicle_per_day": int(
            solver_metadata.get(
                "max_depot_cycles_per_vehicle_per_day",
                summary.get("max_depot_cycles_per_vehicle_per_day", 1),
            )
            or 1
        ),
        "vehicle_fragment_counts": dict(
            solver_metadata.get("vehicle_fragment_counts")
            or summary.get("vehicle_fragment_counts")
            or {}
        ),
        "vehicles_with_multiple_fragments": list(
            solver_metadata.get("vehicles_with_multiple_fragments")
            or summary.get("vehicles_with_multiple_fragments")
            or []
        ),
        "max_fragments_observed": int(
            solver_metadata.get(
                "max_fragments_observed",
                summary.get("max_fragments_observed", 0),
            )
            or 0
        ),
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "dated_run_dir": dated_run_dir,
        "prepared_input_id": prepared_input_id,
        "per_solver_result_json": str(result_json_path) if result_json_path else "",
    }
    return result


def load_run_result_from_job(job: dict[str, Any]) -> dict[str, Any] | None:
    metadata = dict(job.get("metadata") or {})
    run_dir = pick_text(metadata.get("dated_run_dir"), metadata.get("output_dir"))
    if not run_dir:
        return None
    result_path = Path(run_dir) / "optimization_result.json"
    if not result_path.exists():
        return None
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def wait_for_job(client: BFFClient, job_id: str, poll_seconds: float, timeout_seconds: int) -> dict[str, Any]:
    job_path = Path(__file__).resolve().parents[1] / "output" / "jobs" / f"{job_id}.json"

    def _load_job_from_disk() -> dict[str, Any] | None:
        if not job_path.exists():
            return None
        try:
            return json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    started = time.time()
    while True:
        job: dict[str, Any] | None = None
        try:
            job = client.request("GET", f"/jobs/{job_id}")
        except Exception:
            job = _load_job_from_disk()
        if job is None:
            if time.time() - started > timeout_seconds:
                raise TimeoutError(f"Job timeout: {job_id}")
            time.sleep(poll_seconds)
            continue
        status = str(job.get("status") or "")
        if status in {"completed", "failed", "cancelled"}:
            return job
        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Job timeout: {job_id}")
        time.sleep(poll_seconds)


def run_mode(
    client: BFFClient,
    scenario_id: str,
    mode: str,
    service_id: str,
    depot_id: str | None,
    prepared_input_id: str | None,
    time_limit_seconds: int,
    mip_gap: float,
    alns_iterations: int,
    poll_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "mode": mode,
        "service_id": service_id,
        "depot_id": depot_id,
        "prepared_input_id": prepared_input_id,
        "time_limit_seconds": time_limit_seconds,
        "mip_gap": mip_gap,
        "alns_iterations": alns_iterations,
    }

    submitted_at = datetime.now(timezone.utc).isoformat()
    run_resp = client.request("POST", f"/scenarios/{scenario_id}/run-optimization", body=payload)
    job_id = str(run_resp.get("jobId") or run_resp.get("job_id") or "")
    if not job_id:
        raise RuntimeError(f"No job id returned for mode={mode}: {run_resp}")

    job = wait_for_job(client, job_id, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)
    completed_at = datetime.now(timezone.utc).isoformat()
    result = load_run_result_from_job(job) or client.request("GET", f"/scenarios/{scenario_id}/optimization")
    dated_run_dir = pick_text(dict(job.get("metadata") or {}).get("dated_run_dir"))
    row = _build_row(
        mode_label=mode,
        result_payload=result,
        wall_clock_seconds=time.perf_counter() - started,
        job_id=job_id,
        job_status=pick_text(job.get("status")),
        job_message=pick_text(job.get("message")),
        job_progress=job.get("progress"),
        submitted_at=submitted_at,
        completed_at=completed_at,
        dated_run_dir=dated_run_dir,
        prepared_input_id=pick_text(dict(job.get("metadata") or {}).get("prepared_input_id"), prepared_input_id),
        result_json_path=(Path(dated_run_dir) / "optimization_result.json") if dated_run_dir else None,
    )

    row["solver_result_keys"] = sorted(list((_canonical_solver_result(result) or {}).keys()))
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark optimization modes via BFF API (sequential runs only).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8771", help="BFF base URL")
    parser.add_argument("--scenario-id", required=True, help="Scenario ID")
    parser.add_argument("--prepared-input-id", default="", help="Optional prepared input ID to pin the comparison to a fixed prepared scope")
    parser.add_argument(
        "--modes",
        default="mode_milp_only,mode_alns_only,ga,abc",
        help="Comma-separated solver modes",
    )
    parser.add_argument("--service-id", default="WEEKDAY", help="Service/day type")
    parser.add_argument("--depot-id", default="", help="Optional depot id")
    parser.add_argument("--time-limit-seconds", type=int, default=300)
    parser.add_argument("--mip-gap", type=float, default=0.01)
    parser.add_argument("--alns-iterations", type=int, default=500)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--output-json", default="", help="Output JSON path")
    parser.add_argument("--output-csv", default="", help="Output CSV path")
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes:
        raise RuntimeError("No modes provided.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = Path(args.output_json) if args.output_json else Path(f"outputs/mode_compare_{ts}.json")
    out_csv = Path(args.output_csv) if args.output_csv else Path(f"outputs/mode_compare_{ts}.csv")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    client = BFFClient(args.base_url)
    prefix = client.detect_api_prefix()
    print(f"Detected API prefix: {prefix or '/'}")
    print("Run policy: sequential-only (no concurrent multi-solver execution).")

    rows: list[dict[str, Any]] = []
    for mode in modes:
        print(f"[RUN] mode={mode}")
        row = run_mode(
            client=client,
            scenario_id=args.scenario_id,
            mode=mode,
            service_id=args.service_id,
            depot_id=args.depot_id or None,
            prepared_input_id=args.prepared_input_id or None,
            time_limit_seconds=args.time_limit_seconds,
            mip_gap=args.mip_gap,
            alns_iterations=args.alns_iterations,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        rows.append(row)
        print(
            f"[DONE] mode={mode} tier={row.get('benchmark_tier')} status={row.get('status')} "
            f"objective={row.get('objective_value')} solve_time={row.get('solve_time_seconds')}"
        )

    main_rows = [row for row in rows if row.get("counts_for_comparison")]
    appendix_rows = [row for row in rows if row.get("benchmark_tier") == "appendix"]
    excluded_rows = [row for row in rows if row.get("benchmark_tier") == "excluded"]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "api_prefix": client.api_prefix,
        "scenario_id": args.scenario_id,
        "service_id": args.service_id,
        "depot_id": args.depot_id or None,
        "rows": rows,
        "main_rows": main_rows,
        "appendix_rows": appendix_rows,
        "excluded_rows": excluded_rows,
        "benchmark_summary": {
            "total_rows": len(rows),
            "main_rows": len(main_rows),
            "appendix_rows": len(appendix_rows),
            "excluded_rows": len(excluded_rows),
            "main_modes": [row.get("mode") for row in main_rows],
            "appendix_modes": [row.get("mode") for row in appendix_rows],
            "excluded_modes": [row.get("mode") for row in excluded_rows],
        },
    }

    out_json.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDNAMES})

    print(f"Saved JSON: {out_json}")
    print(f"Saved CSV : {out_csv}")


if __name__ == "__main__":
    main()
