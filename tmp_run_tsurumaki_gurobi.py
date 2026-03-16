import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("MC_API_BASE", "http://127.0.0.1:8000/api")


def req(method: str, path: str, body=None, query=None):
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {path}: {detail}")


def main():
    # 1) create scenario
    ts = int(time.time())
    scenario_name = f"tsurumaki_gurobi_check_{ts}"
    scenario = req(
        "POST",
        "/scenarios",
        {
            "name": scenario_name,
            "description": "auto check for tsurumaki depot",
            "mode": "thesis_mode",
            "operatorId": "tokyu",
            "datasetId": "tokyu_core",
            "randomSeed": 42,
        },
    )
    scenario_id = str(scenario.get("id") or "").strip()
    if not scenario_id:
        raise RuntimeError("scenario id not returned")

    # 2) find depot and routes in quick-setup
    quick = req("GET", f"/scenarios/{scenario_id}/quick-setup", query={"routeLimit": 1000})
    depots = list(quick.get("depots") or [])
    routes = list(quick.get("routes") or [])

    target_depot = None
    for d in depots:
        name = str(d.get("name") or "")
        if "弦巻" in name:
            target_depot = d
            break
    if target_depot is None:
        raise RuntimeError("弦巻営業所 not found in quick-setup depots")

    depot_id = str(target_depot.get("id") or target_depot.get("depotId") or "").strip()
    if not depot_id:
        raise RuntimeError("target depot id is empty")

    route_ids = [
        str(r.get("id") or "").strip()
        for r in routes
        if str(r.get("depotId") or "").strip() == depot_id
    ]
    route_ids = [r for r in route_ids if r]
    if not route_ids:
        raise RuntimeError("No routes found for target depot")

    # 3) apply quick-setup (no inter-route swap / no inter-depot swap)
    req(
        "PUT",
        f"/scenarios/{scenario_id}/quick-setup",
        {
            "selectedDepotIds": [depot_id],
            "selectedRouteIds": route_ids,
            "dayType": "WEEKDAY",
            "includeShortTurn": True,
            "includeDepotMoves": True,
            "includeDeadhead": True,
            "allowIntraDepotRouteSwap": False,
            "allowInterDepotSwap": False,
            "solverMode": "mode_milp_only",
            "objectiveMode": "total_cost",
            "timeLimitSeconds": 600,
            "mipGap": 0.01,
            "alnsIterations": 200,
        },
    )

    # 4) reset depot fleet to exact requested composition
    existing = req("GET", f"/scenarios/{scenario_id}/vehicles", query={"depotId": depot_id})
    existing_items = list(existing.get("items") or [])
    for v in existing_items:
        vid = str(v.get("id") or "").strip()
        if vid:
            req("DELETE", f"/scenarios/{scenario_id}/vehicles/{vid}")

    # BYD K8 2.0 BEV x80
    req(
        "POST",
        f"/scenarios/{scenario_id}/vehicles/bulk",
        {
            "depotId": depot_id,
            "type": "BEV",
            "modelName": "BYD K8 2.0",
            "capacityPassengers": 70,
            "batteryKwh": 320.0,
            "energyConsumption": 1.25,
            "chargePowerKw": 90.0,
            "minSoc": 0.15,
            "maxSoc": 0.95,
            "acquisitionCost": 3500.0,
            "enabled": True,
            "quantity": 80,
        },
    )

    # Mitsubishi ICE x40
    req(
        "POST",
        f"/scenarios/{scenario_id}/vehicles/bulk",
        {
            "depotId": depot_id,
            "type": "ICE",
            "modelName": "三菱ふそう エアロスター",
            "capacityPassengers": 75,
            "fuelTankL": 300.0,
            "energyConsumption": 0.38,
            "acquisitionCost": 1200.0,
            "enabled": True,
            "quantity": 40,
        },
    )

    # Isuzu Erga ICE x40
    req(
        "POST",
        f"/scenarios/{scenario_id}/vehicles/bulk",
        {
            "depotId": depot_id,
            "type": "ICE",
            "modelName": "いすゞ エルガ",
            "capacityPassengers": 75,
            "fuelTankL": 300.0,
            "energyConsumption": 0.37,
            "acquisitionCost": 1200.0,
            "enabled": True,
            "quantity": 40,
        },
    )

    # 5) launch optimization (Gurobi via mode_milp_only)
    job = req(
        "POST",
        f"/scenarios/{scenario_id}/run-optimization",
        {
            "mode": "mode_milp_only",
            "time_limit_seconds": 600,
            "mip_gap": 0.01,
            "random_seed": 42,
            "service_id": "WEEKDAY",
            "depot_id": depot_id,
            "rebuild_dispatch": True,
            "use_existing_duties": False,
            "alns_iterations": 200,
        },
    )
    job_id = str(job.get("job_id") or job.get("jobId") or "").strip()
    if not job_id:
        raise RuntimeError(f"job id missing: {job}")

    # 6) poll job
    start = time.time()
    timeout_sec = 900
    last = {}
    while True:
        state = req("GET", f"/jobs/{job_id}")
        status = str(state.get("status") or "")
        last = state
        if status in {"completed", "failed", "cancelled"}:
            break
        if time.time() - start > timeout_sec:
            raise RuntimeError(f"Job timeout after {timeout_sec}s: {state}")
        time.sleep(2)

    result = {
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "depot_id": depot_id,
        "route_count": len(route_ids),
        "job_id": job_id,
        "job_status": last.get("status"),
        "job_progress": last.get("progress"),
        "job_message": last.get("message"),
        "job_error": last.get("error"),
    }

    if str(last.get("status")) == "completed":
        opt = req("GET", f"/scenarios/{scenario_id}/optimization")
        result["optimization_result"] = {
            "status": opt.get("status"),
            "objective": opt.get("objective") or (opt.get("summary") or {}).get("objective"),
            "kpi": opt.get("kpi") or opt.get("summary") or {},
        }

    with open("tmp_tsurumaki_gurobi_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("wrote tmp_tsurumaki_gurobi_result.json")


if __name__ == "__main__":
    main()
