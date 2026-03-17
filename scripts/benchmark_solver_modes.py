from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


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


def pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def extract_result_metrics(result: dict[str, Any]) -> dict[str, Any]:
    solver_result = dict(result.get("solver_result") or {})
    kpi = dict(result.get("kpi") or {})
    costs = dict(result.get("cost_breakdown") or {})
    return {
        "status": pick_text(result.get("status"), solver_result.get("status"), "unknown"),
        "objective_value": pick_number(result.get("objective_value"), solver_result.get("objective_value")),
        "solve_time_seconds": pick_number(
            solver_result.get("solve_time_seconds"),
            kpi.get("solve_time_sec"),
            result.get("solve_time_seconds"),
        ),
        "total_energy_cost": pick_number(costs.get("total_energy_cost"), costs.get("energy_cost")),
        "total_fuel_cost": pick_number(costs.get("total_fuel_cost"), costs.get("fuel_cost")),
        "total_demand_charge": pick_number(costs.get("total_demand_charge"), costs.get("demand_charge")),
        "unmet_trips": pick_number(kpi.get("unmet_trips"), result.get("unmet_trips")),
    }


def wait_for_job(client: BFFClient, job_id: str, poll_seconds: float, timeout_seconds: int) -> dict[str, Any]:
    started = time.time()
    while True:
        job = client.request("GET", f"/jobs/{job_id}")
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
    time_limit_seconds: int,
    mip_gap: float,
    alns_iterations: int,
    poll_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "service_id": service_id,
        "depot_id": depot_id,
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
    result = client.request("GET", f"/scenarios/{scenario_id}/optimization")
    metrics = extract_result_metrics(result)

    return {
        "mode": mode,
        "job_id": job_id,
        "job_status": job.get("status"),
        "job_message": job.get("message"),
        "job_progress": job.get("progress"),
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "metrics": metrics,
        "solver_result_keys": sorted(list((result.get("solver_result") or {}).keys())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark optimization modes via BFF API (sequential runs only).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8771", help="BFF base URL")
    parser.add_argument("--scenario-id", required=True, help="Scenario ID")
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
            time_limit_seconds=args.time_limit_seconds,
            mip_gap=args.mip_gap,
            alns_iterations=args.alns_iterations,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        rows.append(row)
        metrics = row.get("metrics") or {}
        print(
            f"[DONE] mode={mode} status={metrics.get('status')} objective={metrics.get('objective_value')} "
            f"solve_time={metrics.get('solve_time_seconds')}"
        )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "api_prefix": client.api_prefix,
        "scenario_id": args.scenario_id,
        "service_id": args.service_id,
        "depot_id": args.depot_id or None,
        "rows": rows,
    }

    out_json.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "mode",
                "job_id",
                "job_status",
                "status",
                "objective_value",
                "solve_time_seconds",
                "total_energy_cost",
                "total_fuel_cost",
                "total_demand_charge",
                "unmet_trips",
                "submitted_at",
                "completed_at",
            ]
        )
        for row in rows:
            metrics = row.get("metrics") or {}
            writer.writerow(
                [
                    row.get("mode"),
                    row.get("job_id"),
                    row.get("job_status"),
                    metrics.get("status"),
                    metrics.get("objective_value"),
                    metrics.get("solve_time_seconds"),
                    metrics.get("total_energy_cost"),
                    metrics.get("total_fuel_cost"),
                    metrics.get("total_demand_charge"),
                    metrics.get("unmet_trips"),
                    row.get("submitted_at"),
                    row.get("completed_at"),
                ]
            )

    print(f"Saved JSON: {out_json}")
    print(f"Saved CSV : {out_csv}")


if __name__ == "__main__":
    main()
