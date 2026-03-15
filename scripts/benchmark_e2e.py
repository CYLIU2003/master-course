"""
End-to-end benchmark: scenario create -> optimize (all modes, cost_min).

Usage:
    python scripts/benchmark_e2e.py [--base-url http://localhost:8766]
"""
import argparse
import json
import pathlib
import time
import httpx
from typing import Any

BASE_URL = "http://localhost:8766/api"
POLL_INTERVAL = 2.0
JOB_TIMEOUT = 300


CLIENT = httpx.Client(base_url="", timeout=60.0)


def get(path: str) -> Any:
    r = CLIENT.get(BASE_URL + path)
    r.raise_for_status()
    return r.json()


def post(path: str, body: Any = None) -> Any:
    r = CLIENT.post(BASE_URL + path, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} POST {path}: {r.text[:300]}")
    return r.json()


def poll_job(job_id: str, label: str) -> dict:
    deadline = time.time() + JOB_TIMEOUT
    while time.time() < deadline:
        job = get(f"/jobs/{job_id}")
        status = job.get("status")
        progress = job.get("progress", 0)
        msg = (job.get("message") or "")[:50]
        print(f"\r  [{label}] {status} {progress}% {msg:<50}", end="", flush=True)
        if status == "completed":
            print()
            return job
        if status == "failed":
            print()
            raise RuntimeError(f"Job {job_id} failed: {job.get('error')}")
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"Job {job_id} timed out after {JOB_TIMEOUT}s")


class Timer:
    def __init__(self):
        self.elapsed = 0.0
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = time.perf_counter() - self._start
        return False


def run_benchmark(base_url: str):
    global BASE_URL
    BASE_URL = base_url.rstrip("/") + "/api"

    results: dict[str, Any] = {"timings": {}, "errors": [], "optimization_results": {}}

    print("=" * 70)
    print("EV Bus Dispatch Benchmark  --  cost_min, all solver modes")
    print("=" * 70)

    # Step 0
    print("\n[0] Health check...")
    health = get("/app/context")
    print(f"    active_scenario_id: {health.get('activeScenarioId')}")

    # Step 1: editor-bootstrap timing (existing optimized scenario)
    print("\n[1] editor-bootstrap latency (existing optimized scenario)...")
    scenarios_resp = get("/scenarios")
    optimized = [s for s in (scenarios_resp.get("items") or []) if s.get("status") == "optimized"]
    if optimized:
        sid_ex = optimized[0]["id"]
        name_ex = optimized[0]["name"]
        # warm up (first call may have cold module costs)
        get(f"/scenarios/{sid_ex}/editor-bootstrap")
        times_ms = []
        for _ in range(3):
            with Timer() as t:
                bs_ex = get(f"/scenarios/{sid_ex}/editor-bootstrap")
            times_ms.append(round(t.elapsed * 1000))
        avg_ms = round(sum(times_ms) / len(times_ms))
        results["timings"]["editor_bootstrap_existing_ms"] = avg_ms
        ndepots = len(bs_ex.get("depots") or [])
        nroutes = len(bs_ex.get("routes") or [])
        nsummary = len(bs_ex.get("depotRouteSummary") or [])
        payload_kb = round(len(json.dumps(bs_ex)) / 1024, 1)
        print(f"    {name_ex[:30]} ({sid_ex[:8]})")
        print(f"    depots={ndepots}  routes={nroutes}  depotRouteSummary={nsummary}")
        print(f"    payload={payload_kb}KB  avg_latency={avg_ms}ms  runs={times_ms}")
        if avg_ms > 200:
            results["errors"].append(f"editor-bootstrap slow: {avg_ms}ms (target <200ms)")
    else:
        print("    No optimized scenario found.")

    # Step 2: create fresh scenario
    print("\n[2] Create fresh scenario from tokyu_core dataset...")
    with Timer() as t:
        new_sc = post("/scenarios", {
            "name": "benchmark-e2e-cost-min",
            "description": "Auto benchmark: cost_min all solver modes",
            "mode": "hybrid",
            "operatorId": "tokyu",
            "datasetId": "tokyu_core",
        })
    sid = new_sc["id"]
    ms = round(t.elapsed * 1000)
    results["scenario_id"] = sid
    results["timings"]["create_scenario_ms"] = ms
    print(f"    Created: {new_sc['name']} ({sid[:8]})  {ms}ms")

    # Step 3: editor-bootstrap (new scenario)
    print("\n[3] editor-bootstrap (new scenario) -- KEY METRIC...")
    get(f"/scenarios/{sid}/editor-bootstrap")  # warm
    times_ms = []
    for _ in range(3):
        with Timer() as t:
            bootstrap = get(f"/scenarios/{sid}/editor-bootstrap")
        times_ms.append(round(t.elapsed * 1000))
    avg_ms = round(sum(times_ms) / len(times_ms))
    results["timings"]["editor_bootstrap_new_ms"] = avg_ms
    depots = bootstrap.get("depots") or []
    routes = bootstrap.get("routes") or []
    summaries = bootstrap.get("depotRouteSummary") or []
    payload_kb = round(len(json.dumps(bootstrap)) / 1024, 1)
    print(f"    depots={len(depots)}  routes={len(routes)}  depotRouteSummary={len(summaries)}")
    print(f"    payload={payload_kb}KB  avg_latency={avg_ms}ms  runs={times_ms}")

    if not depots:
        print("    ERROR: no depots.")
        results["errors"].append("no depots in bootstrap")
        _print_summary(results)
        return results

    # Pick depot with most routes
    selected_summary = max(summaries, key=lambda s: s.get("routeCount", 0)) if summaries else None
    if not selected_summary:
        selected_summary = {"depotId": depots[0]["id"], "name": depots[0]["name"]}

    depot_id = selected_summary["depotId"]
    depot_name = selected_summary.get("name", depot_id)
    route_index = bootstrap.get("depotRouteIndex") or {}
    all_depot_routes = route_index.get(depot_id) or []
    selected_routes = all_depot_routes[:15]
    avail_day_types = bootstrap.get("availableDayTypes") or []
    day_type = avail_day_types[0]["serviceId"] if avail_day_types else "WEEKDAY"
    print(f"    Depot: {depot_name} ({depot_id[:8]})  total_routes={len(all_depot_routes)}  using={len(selected_routes)}")
    print(f"    day_type: {day_type}")

    # Step 4: simulation/prepare
    print("\n[4] simulation/prepare...")
    builder_defaults = bootstrap.get("builderDefaults") or {}
    prepare_body = {
        "selectedDepotIds": [depot_id],
        "selectedRouteIds": selected_routes,
        "dayType": day_type,
        "serviceDate": None,
        "simulationSettings": {
            "vehicleTemplateId": builder_defaults.get("vehicleTemplateId"),
            "vehicleCount": builder_defaults.get("vehicleCount", 10),
            "initialSoc": builder_defaults.get("initialSoc", 0.9),
            "batteryKwh": builder_defaults.get("batteryKwh"),
            "chargerCount": builder_defaults.get("chargerCount", 5),
            "chargerPowerKw": builder_defaults.get("chargerPowerKw", 50.0),
            "solverMode": "hybrid",
            "objectiveMode": "total_cost",
            "timeLimitSeconds": 60,
            "mipGap": 0.05,
            "alnsIterations": 500,
            "includeDeadhead": builder_defaults.get("includeDeadhead", True),
        },
    }
    with Timer() as t:
        try:
            prep = post(f"/scenarios/{sid}/simulation/prepare", prepare_body)
        except RuntimeError as e:
            print(f"    ERROR: {e}")
            results["errors"].append(f"prepare failed: {e}")
            _print_summary(results)
            return results
    ms = round(t.elapsed * 1000)
    results["timings"]["prepare_ms"] = ms
    trip_count = prep.get("tripCount", 0)
    ready = prep.get("ready", False)
    block_count = prep.get("blockCount", 0)
    print(f"    tripCount={trip_count}  blockCount={block_count}  ready={ready}  {ms}ms")
    for w in (prep.get("warnings") or [])[:3]:
        print(f"    WARN: {w}")

    if not ready:
        print("    ERROR: not ready.")
        results["errors"].append(f"prepare not ready: {prep}")
        _print_summary(results)
        return results
    results["timings"]["prepare_trip_count"] = trip_count

    # Step 5: optimization -- all solver modes
    SOLVER_MODES = [
        "mode_milp_only",
        "mode_alns_only",
        "mode_alns_milp",
        "hybrid",
    ]
    print(f"\n[5] Optimization -- {len(SOLVER_MODES)} modes, objective=total_cost")

    for mode in SOLVER_MODES:
        print(f"\n  --- Mode: {mode} ---")
        opt_body = {
            "mode": mode,
            "service_id": day_type,
            "depot_id": depot_id,
            "time_limit_seconds": 60,
            "mip_gap": 0.05,
            "alns_iterations": 500,
            "rebuild_dispatch": True,
            "use_existing_duties": False,
        }
        try:
            with Timer() as t_sub:
                job_resp = post(f"/scenarios/{sid}/run-optimization", opt_body)
            job_id = job_resp.get("job_id") or job_resp.get("jobId")
            print(f"  Job {str(job_id)[:8]}  (submit: {t_sub.elapsed*1000:.0f}ms)")

            t_poll_start = time.perf_counter()
            poll_job(str(job_id), mode)
            poll_elapsed = time.perf_counter() - t_poll_start

            opt = get(f"/scenarios/{sid}/optimization")
            total_elapsed = t_sub.elapsed + poll_elapsed
            results["timings"][f"opt_{mode}_total_s"] = round(total_elapsed, 2)

            obj = opt.get("objectiveValue") or opt.get("objective_value")
            status = opt.get("solverStatus") or opt.get("solver_status")
            cost_bd = opt.get("costBreakdown") or opt.get("cost_breakdown") or {}
            duties = opt.get("duties") or []
            summary_r = opt.get("summary") or {}
            feasible = opt.get("feasible")

            metrics = {
                "solver_status": status,
                "feasible": feasible,
                "objective_value": obj,
                "total_cost": cost_bd.get("total_cost") or cost_bd.get("totalCost"),
                "energy_cost": cost_bd.get("energy_cost") or cost_bd.get("energyCost"),
                "vehicle_cost": cost_bd.get("vehicle_cost") or cost_bd.get("vehicleCost"),
                "demand_charge": cost_bd.get("peak_demand_cost") or cost_bd.get("peakDemandCost"),
                "n_duties": len(duties),
                "trips_served": summary_r.get("trip_count_served") or summary_r.get("tripCountServed"),
                "trips_unserved": summary_r.get("trip_count_unserved") or summary_r.get("tripCountUnserved"),
                "elapsed_s": round(total_elapsed, 2),
            }
            results["optimization_results"][mode] = metrics

            total_cost = metrics.get("total_cost", "?")
            trips_served = metrics.get("trips_served", "?")
            trips_unserved = metrics.get("trips_unserved", "?")
            print(f"  status={status}  feasible={feasible}")
            print(f"  total_cost={total_cost}  obj={obj}")
            print(f"  duties={len(duties)}  trips_served={trips_served}  unserved={trips_unserved}")
            print(f"  elapsed={total_elapsed:.1f}s")
            for w in (opt.get("warnings") or [])[:2]:
                print(f"  WARN: {w}")
            for r2 in (opt.get("infeasibility_reasons") or [])[:2]:
                print(f"  INFEASIBLE: {r2}")

        except RuntimeError as e:
            print(f"  ERROR [{mode}]: {e}")
            results["errors"].append(f"{mode}: {e}")
            results["optimization_results"][mode] = {"error": str(e)}

    _print_summary(results)

    out = pathlib.Path(f"outputs/benchmark_e2e_{int(time.time())}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults written to: {out}")

    return results


def _print_summary(results: dict):
    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    print("\n--- Timings ---")
    for k, v in results.get("timings", {}).items():
        if "ms" in k:
            unit = "ms"
        elif "trip_count" in k:
            unit = "trips"
        else:
            unit = "s"
        print(f"  {k:<45} {v} {unit}")

    print("\n--- Optimization Results (total_cost objective) ---")
    hdr = f"  {'Mode':<18} {'Status':<22} {'Obj':>10} {'TotalCost':>11} {'Duties':>6} {'Served':>7} {'Elapsed':>8}"
    print(hdr)
    print("  " + "-" * 85)
    for mode, r in results.get("optimization_results", {}).items():
        if "error" in r:
            print(f"  {mode:<18} ERROR: {str(r['error'])[:55]}")
        else:
            print(
                f"  {mode:<18} {str(r.get('solver_status','?')):<22} "
                f"{str(r.get('objective_value','?')):>10} "
                f"{str(r.get('total_cost','?')):>11} "
                f"{str(r.get('n_duties','?')):>6} "
                f"{str(r.get('trips_served','?')):>7} "
                f"{str(r.get('elapsed_s','?')):>7}s"
            )

    if results.get("errors"):
        print("\n--- Issues ---")
        for e in results["errors"]:
            print(f"  ! {e}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8766")
    args = parser.parse_args()
    run_benchmark(args.base_url)
