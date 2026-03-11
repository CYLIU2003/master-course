from __future__ import annotations

import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.store import scenario_store as store


SCENARIO_ID = "74aa5521-5492-495f-9421-c35d0a5fb0e6"
RAW_STOP_TIMETABLES = Path(
    r"C:\master-course\data\cache\odpt\raw\odpt-tokyu-20260310-140701\busstop_pole_timetable.json"
)
NOTE_PATTERN = re.compile(r"お問合せ先:?東急バス\s*([\u4e00-\u9fffぁ-んァ-ンー]+営業所)")


def geocode_address(address: str) -> tuple[float, float] | None:
    url = "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(address)
    request = urllib.request.Request(url, headers={"User-Agent": "master-course-opencode/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data:
        return None
    lon, lat = data[0]["geometry"]["coordinates"]
    return float(lat), float(lon)


def hhmm_to_min(value: str | None) -> int | None:
    if not value or ":" not in value:
        return None
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)


def infer_assignments(doc: dict) -> dict[str, dict]:
    routes = list(doc.get("routes") or [])
    depots = list(doc.get("depots") or [])
    name_to_depot = {str(item.get("name") or ""): item for item in depots}
    route_by_pattern = {
        str(route.get("odptPatternId")): route
        for route in routes
        if route.get("odptPatternId")
    }
    busroute_groups: dict[str, list[dict]] = defaultdict(list)
    for route in routes:
        busroute_id = str(route.get("odptBusrouteId") or "")
        if busroute_id:
            busroute_groups[busroute_id].append(route)

    pattern_note_counts: dict[str, Counter[str]] = defaultdict(Counter)
    with RAW_STOP_TIMETABLES.open("r", encoding="utf-8") as f:
        raw_stop_timetables = json.load(f)
    for timetable in raw_stop_timetables:
        note = str(timetable.get("odpt:note") or "")
        match = NOTE_PATTERN.search(note)
        if not match:
            continue
        depot_name = match.group(1)
        if depot_name not in name_to_depot:
            continue
        for obj in timetable.get("odpt:busstopPoleTimetableObject") or []:
            if not isinstance(obj, dict):
                continue
            pattern_id = str(obj.get("odpt:busroutePattern") or "")
            if pattern_id:
                pattern_note_counts[pattern_id][depot_name] += 1

    assigned: dict[str, dict] = {}
    for pattern_id, counts in pattern_note_counts.items():
        route = route_by_pattern.get(pattern_id)
        if route is None:
            continue
        depot_name, count = counts.most_common(1)[0]
        total = sum(counts.values())
        assigned[str(route["id"])] = {
            "depotName": depot_name,
            "assignmentType": "odpt_note",
            "confidence": round(count / total, 3) if total else 1.0,
            "reason": f"ODPT stop timetable note matched {depot_name}.",
            "sourceRefs": [f"note:{pattern_id}:{count}"],
        }

    for item in doc.get("route_depot_assignments") or []:
        route_id = str(item.get("routeId") or "")
        depot_id = str(item.get("depotId") or "")
        if str(item.get("assignmentType") or "") != "manual_override":
            continue
        depot = next((entry for entry in depots if str(entry.get("id")) == depot_id), None)
        if depot is None:
            continue
        assigned[route_id] = {
            "depotName": str(depot.get("name") or ""),
            "assignmentType": "manual_override",
            "confidence": float(item.get("confidence") or 1.0),
            "reason": str(item.get("reason") or "Manual override preserved."),
            "sourceRefs": list(item.get("sourceRefs") or []),
        }

    for route in routes:
        route_id = str(route.get("id") or "")
        if route_id in assigned:
            continue
        busroute_id = str(route.get("odptBusrouteId") or "")
        start_stop = str(route.get("startStop") or "")
        end_stop = str(route.get("endStop") or "")

        terminal_counts: Counter[str] = Counter()
        for peer in busroute_groups.get(busroute_id) or []:
            peer_id = str(peer.get("id") or "")
            if peer_id == route_id or peer_id not in assigned:
                continue
            peer_start = str(peer.get("startStop") or "")
            peer_end = str(peer.get("endStop") or "")
            if start_stop and (start_stop == peer_start or start_stop == peer_end):
                terminal_counts[assigned[peer_id]["depotName"]] += 2
            if end_stop and (end_stop == peer_start or end_stop == peer_end):
                terminal_counts[assigned[peer_id]["depotName"]] += 2
        if terminal_counts:
            depot_name, weight = terminal_counts.most_common(1)[0]
            total = sum(terminal_counts.values())
            assigned[route_id] = {
                "depotName": depot_name,
                "assignmentType": "same_busroute_terminal",
                "confidence": round(weight / total, 3) if total else 0.75,
                "reason": f"Same busroute terminal overlap inferred {depot_name}.",
                "sourceRefs": [f"same-busroute:{busroute_id}"],
            }
            continue

        direct_name = None
        for depot_name in name_to_depot:
            if start_stop == depot_name or end_stop == depot_name:
                direct_name = depot_name
                break
        if direct_name:
            assigned[route_id] = {
                "depotName": direct_name,
                "assignmentType": "terminal_name",
                "confidence": 0.9,
                "reason": f"Route terminal matched depot name {direct_name}.",
                "sourceRefs": [f"terminal:{route.get('odptPatternId') or route_id}"],
            }
            continue

        family_counts: Counter[str] = Counter(
            assigned[str(peer.get("id"))]["depotName"]
            for peer in busroute_groups.get(busroute_id) or []
            if str(peer.get("id") or "") in assigned
        )
        if len(family_counts) == 1:
            depot_name = family_counts.most_common(1)[0][0]
            assigned[route_id] = {
                "depotName": depot_name,
                "assignmentType": "same_busroute",
                "confidence": 0.7,
                "reason": f"All assigned patterns in {busroute_id} map to {depot_name}.",
                "sourceRefs": [f"same-busroute:{busroute_id}"],
            }

    return assigned


def estimate_parking(doc: dict, route_to_depot_name: dict[str, str]) -> dict[str, int]:
    estimates: dict[str, int] = {}
    depots = [str(item.get("name") or "") for item in doc.get("depots") or []]
    for depot_name in depots:
        route_ids = {
            route_id
            for route_id, assigned_name in route_to_depot_name.items()
            if assigned_name == depot_name
        }
        peaks = []
        for service_id in ["WEEKDAY", "SAT", "SUN_HOL", "SAT_HOL"]:
            events = []
            for row in doc.get("timetable_rows") or []:
                route_id = str(row.get("route_id") or "")
                if route_id not in route_ids or str(row.get("service_id") or "") != service_id:
                    continue
                departure = hhmm_to_min(row.get("departure"))
                arrival = hhmm_to_min(row.get("arrival"))
                if departure is None or arrival is None:
                    continue
                if arrival < departure:
                    arrival += 24 * 60
                events.append((departure, 1))
                events.append((arrival, -1))
            current = 0
            peak = 0
            for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
                current += delta
                peak = max(peak, current)
            peaks.append(peak)
        lower_bound = max(peaks) if peaks else 0
        estimates[depot_name] = max(5, int(math.ceil(lower_bound * 1.15 / 5.0) * 5)) if lower_bound else 5
    return estimates


def main() -> None:
    doc = store._load(SCENARIO_ID)
    depots = list(doc.get("depots") or [])
    name_to_depot = {str(item.get("name") or ""): item for item in depots}

    assigned = infer_assignments(doc)
    missing = [
        str(route.get("id") or "")
        for route in doc.get("routes") or []
        if str(route.get("id") or "") not in assigned
    ]
    if missing:
        raise RuntimeError(f"Unassigned routes remain: {len(missing)}")

    route_to_depot_name = {route_id: info["depotName"] for route_id, info in assigned.items()}
    parking_estimates = estimate_parking(doc, route_to_depot_name)

    for depot in depots:
        name = str(depot.get("name") or "")
        location = str(depot.get("location") or "")
        coords = geocode_address(location) if location else None
        if coords is not None:
            depot["lat"] = round(coords[0], 6)
            depot["lon"] = round(coords[1], 6)

        notes = str(depot.get("notes") or "").strip()
        note_parts = [part for part in [notes] if part]
        note_parts.append("住所座標は国土地理院アドレス検索で補完。")
        note_parts.append("parkingCapacity は担当routeの最大同時運行本数に15%余裕を加えた推定値。")
        depot["hasFuelFacility"] = True
        depot["overnightCharging"] = True
        depot["parkingCapacity"] = parking_estimates.get(name, int(depot.get("parkingCapacity") or 0) or 5)

        if name != "目黒営業所":
            depot["normalChargerCount"] = 0
            depot["normalChargerPowerKw"] = 60.0
            depot["fastChargerCount"] = 0
            depot["fastChargerPowerKw"] = 150.0
            note_parts.append("充電器台数は未確認のため 0 台、出力のみ研究既定値(普通60kW/急速150kW)を設定。")
        else:
            note_parts.append("既存の充電設備設定を維持。")

        depot["notes"] = " ".join(dict.fromkeys(note_parts))

    now = datetime.now(timezone.utc).isoformat()
    doc["route_depot_assignments"] = [
        {
            "routeId": str(route.get("id") or ""),
            "depotId": str(name_to_depot[assigned[str(route.get('id') or '')]["depotName"]].get("id") or ""),
            "assignmentType": assigned[str(route.get("id") or "")]["assignmentType"],
            "confidence": float(assigned[str(route.get("id") or "")]["confidence"]),
            "reason": assigned[str(route.get("id") or "")]["reason"],
            "sourceRefs": list(assigned[str(route.get("id") or "")]["sourceRefs"]),
            "updatedAt": now,
        }
        for route in doc.get("routes") or []
        if route.get("id")
    ]
    store._normalize_dispatch_scope(doc)
    doc["meta"]["updatedAt"] = now
    store._save(doc)

    print(
        json.dumps(
            {
                "depots": len(depots),
                "routeAssignments": len(doc.get("route_depot_assignments") or []),
                "assignmentTypes": Counter(
                    item.get("assignmentType") for item in doc.get("route_depot_assignments") or []
                ),
            },
            ensure_ascii=False,
            default=list,
        )
    )


if __name__ == "__main__":
    main()
