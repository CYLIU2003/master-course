"""Desktop configuration edits through the existing Tkinter/BFF contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from bff.routers.scenarios import UpdateQuickSetupBody, _builder_defaults, _normalize_depot_energy_assets_payload, update_quick_setup
from bff.store import desktop_store, scenario_store



def configuration(scenario_id: str) -> dict[str, Any]:
    meta, refs = scenario_store.get_desktop_context(scenario_id)
    doc = {"meta": meta.get("meta", {})}
    # Only master/settings collections; never hydrate trips, timetables or results.
    for name in ("simulation_config", "scenario_overlay", "dispatch_scope",
                 "depots", "vehicles", "chargers", "vehicle_templates"):
        doc[name] = desktop_store.collection(scenario_id, name)
    scope = dict(doc.get("dispatch_scope") or {})
    route_selection = scope.get("routeSelection") or {}
    selected_routes = (scope.get("effectiveRouteIds") or route_selection.get("includeRouteIds")
                       or route_selection.get("routeIds") or [])
    scope["effectiveRouteIds"] = list(selected_routes)
    values = _builder_defaults(doc, {}, scope)
    allowed = UpdateQuickSetupBody.model_fields
    values = {key: value for key, value in values.items() if key in allowed}
    trip_selection = scope.get("tripSelection") or {}
    values.update({key: trip_selection.get(key, default) for key, default in (
        ("includeShortTurn", True), ("includeDepotMoves", True), ("includeDeadhead", True))})
    values["allowIntraDepotRouteSwap"] = scope.get("allowIntraDepotRouteSwap", False)
    values["allowInterDepotSwap"] = scope.get("allowInterDepotSwap", False)
    files = {}
    for key, raw_path in refs.items():
        path = Path(raw_path)
        if path.is_file():
            stat = path.stat()
            files[key] = (stat.st_mtime_ns, stat.st_size)
    snapshot = json.dumps({"settings": doc.get("simulation_config"),
                           "overlay": doc.get("scenario_overlay"), "scope": scope,
                           "files": files, "updated_at": meta.get("meta", {}).get("updatedAt")},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"values": values, "revision": hashlib.sha256(snapshot.encode()).hexdigest()}


def save_configuration(scenario_id: str, changes: dict[str, Any], revision: str) -> dict[str, Any]:
    unknown = set(changes) - set(UpdateQuickSetupBody.model_fields)
    if unknown:
        raise HTTPException(422, "Unsupported settings: " + ", ".join(sorted(unknown)))
    with scenario_store._scenario_lock(scenario_id):
        current = configuration(scenario_id)
        if current["revision"] != revision:
            raise HTTPException(409, "設定が別の操作で更新されました。最新情報を読み込み直してください。")
        values = current["values"]
        nullable = {"co2EmissionsCapKg", "integratedActualCostUpperBoundJpy", "integratedActualCostUpperBoundDeltaRatio"}
        empty = [key for key, value in changes.items() if value is None and key not in nullable]
        if empty:
            raise HTTPException(422, "空欄では保存できない設定です: " + ", ".join(empty))
        changes = dict(changes)
        if "initialSoc" in changes:
            changes["initialSocPercent"] = float(changes["initialSoc"]) * 100.0
        if {"serviceDate", "planningDays"} & changes.keys() and "serviceDates" not in changes:
            start = date.fromisoformat(changes.get("serviceDate", values.get("serviceDate")))
            days = int(changes.get("planningDays", values.get("planningDays", 1)))
            if not 1 <= days <= 366:
                raise ValueError("planningDays must be between 1 and 366")
            changes["serviceDates"] = [(start + timedelta(days=index)).isoformat() for index in range(days)]
            if not changes.get("operationTimeWindowEnabled", values.get("operationTimeWindowEnabled", False)):
                changes["planningHorizonHours"] = days * 24
        merged = {**values, **changes}
        # Validate coupled fields together even when only one control changed.
        UpdateQuickSetupBody.model_validate(merged)
        if "depotEnergyAssets" in changes:
            _normalize_depot_energy_assets_payload(changes["depotEnergyAssets"])
        if {"socMin", "socMax"} & changes.keys() and float(merged["socMin"]) > float(merged["socMax"]):
            raise ValueError("SOC下限は上限以下にしてください。")
        # The legacy update treats omitted selections as empty; preserve them.
        payload = {key: values.get(key) for key in ("selectedDepotIds", "selectedRouteIds", "dayType")}
        payload.update(changes)
        update_quick_setup(scenario_id, UpdateQuickSetupBody.model_validate(payload))
        return configuration(scenario_id)
