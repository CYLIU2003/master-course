from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
VEHICLE_CATALOG_PATH = REPO_ROOT / "data" / "vehicle_catalog.json"
ENGINE_BUS_LIBRARY_PATH = (
    REPO_ROOT
    / "data"
    / "engine_bus"
    / "output"
    / "engine_bus_simulation_library.json"
)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None


def _normalize_key(value: Any) -> str:
    return "".join(str(value or "").strip().upper().split())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _candidate_keys(row: Mapping[str, Any]) -> tuple[str, ...]:
    keys = []
    for field in (
        "profile_id",
        "vehicle_id",
        "model_code",
        "modelCode",
        "model_name",
        "modelName",
        "display_name",
        "manufacturer",
    ):
        normalized = _normalize_key(row.get(field))
        if normalized:
            keys.append(normalized)
    return tuple(dict.fromkeys(keys))


def _matches(row: Mapping[str, Any], query: str) -> bool:
    needle = _normalize_key(query)
    if not needle:
        return False
    return any(needle == key or needle in key or key in needle for key in _candidate_keys(row))


def _row_to_factor(row: Mapping[str, Any]) -> dict[str, Any] | None:
    co2_kg_per_l = _safe_float(
        row.get("co2_emission_kg_per_L")
        or row.get("co2EmissionKgPerL")
        or row.get("co2_kg_per_l")
    )
    fuel_l_per_km = _safe_float(
        row.get("fuel_consumption_L_per_km")
        or row.get("diesel_consumption_L_per_km")
        or row.get("fuelConsumptionLPerKm")
        or row.get("fuel_consumption_l_per_km")
    )
    fuel_eff_km_per_l = _safe_float(
        row.get("fuel_efficiency_km_per_L")
        or row.get("fuel_economy_km_per_L")
        or row.get("fuelEfficiencyKmPerL")
        or row.get("fuel_efficiency_km_per_l")
    )
    co2_g_per_km = _safe_float(
        row.get("co2_g_per_km")
        or row.get("co2_g_per_km_catalog")
        or row.get("co2EmissionGPerKm")
    )
    if fuel_l_per_km is None and fuel_eff_km_per_l:
        fuel_l_per_km = 1.0 / fuel_eff_km_per_l
    if co2_kg_per_l is None and co2_g_per_km and fuel_l_per_km:
        co2_kg_per_l = (co2_g_per_km / 1000.0) / fuel_l_per_km
    if co2_g_per_km is None and co2_kg_per_l and fuel_l_per_km:
        co2_g_per_km = co2_kg_per_l * fuel_l_per_km * 1000.0
    if co2_kg_per_l is None and fuel_l_per_km is None and fuel_eff_km_per_l is None:
        return None
    return {
        "co2EmissionKgPerL": round(co2_kg_per_l, 6) if co2_kg_per_l else None,
        "co2EmissionGPerKm": round(co2_g_per_km, 6) if co2_g_per_km else None,
        "fuelConsumptionLPerKm": round(fuel_l_per_km, 6) if fuel_l_per_km else None,
        "fuelEfficiencyKmPerL": round(fuel_eff_km_per_l, 6) if fuel_eff_km_per_l else None,
        "source": row.get("source") or row.get("source_summary") or "emission_factor_loader",
    }


def _iter_vehicle_catalog_rows() -> list[Mapping[str, Any]]:
    payload = _load_json(VEHICLE_CATALOG_PATH)
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("engine_presets") or []
    return [row for row in rows if isinstance(row, Mapping)]


def _iter_engine_library_rows() -> list[Mapping[str, Any]]:
    payload = _load_json(ENGINE_BUS_LIBRARY_PATH)
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, Mapping)]


def lookup_ice_emission_factor(model_name_or_code: Any) -> dict[str, Any] | None:
    """Look up ICE fuel/CO2 reference values from project data sources.

    Priority is intentionally fixed: curated vehicle catalog first, generated
    engine-bus simulation library second. Manual scenario values still override
    these defaults at the caller.
    """

    query = str(model_name_or_code or "").strip()
    if not query:
        return None
    for row in _iter_vehicle_catalog_rows():
        if _matches(row, query):
            return _row_to_factor(row)
    for row in _iter_engine_library_rows():
        if _matches(row, query):
            return _row_to_factor(row)
    return None

