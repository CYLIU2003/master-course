from __future__ import annotations

from typing import Any, Dict, Optional


ICE_VEHICLE_REFERENCE: Dict[str, Dict[str, Any]] = {
    "2KG-KV290N4": {
        "modelCode": "2KG-KV290N4",
        "manufacturer": "Hino",
        "fuelEfficiencyKmPerL": 5.35,
        "co2EmissionGPerKm": 483.4056,
        "curbWeightKg": 8654,
        "grossVehicleWeightKg": 12889,
        "capacityPassengers": 77,
        "engineDisplacementL": 8.86,
        "maxTorqueNm": 1275,
        "maxPowerKw": 191,
        "source": "constant/bus_hino_jh25.xlsx:3-1",
    },
    "2KG-LV290N4": {
        "modelCode": "2KG-LV290N4",
        "manufacturer": "Isuzu",
        "fuelEfficiencyKmPerL": 5.35,
        "co2EmissionGPerKm": 483.4056,
        "curbWeightKg": 8654,
        "grossVehicleWeightKg": 12889,
        "capacityPassengers": 77,
        "engineDisplacementL": 8.86,
        "maxTorqueNm": 1275,
        "maxPowerKw": 191,
        "source": "constant/bus_isuzu_jh25.xlsx:3-1",
    },
    "2KG-MP38FK": {
        "modelCode": "2KG-MP38FK",
        "manufacturer": "Mitsubishi Fuso",
        "fuelEfficiencyKmPerL": 4.16,
        "co2EmissionGPerKm": 621.6875,
        "curbWeightKg": 10203,
        "grossVehicleWeightKg": 14548,
        "capacityPassengers": 79,
        "engineDisplacementL": 10.67,
        "maxTorqueNm": 1422,
        "maxPowerKw": 257,
        "source": "constant/mitsubishifuso_bus_jh25.xlsx:3-1",
    },
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_model_code(value: str) -> str:
    return "".join(str(value or "").strip().upper().split())


def lookup_ice_reference(model_name_or_code: Any) -> Optional[Dict[str, Any]]:
    text = normalize_model_code(str(model_name_or_code or ""))
    if not text:
        return None
    if text in ICE_VEHICLE_REFERENCE:
        return dict(ICE_VEHICLE_REFERENCE[text])
    for code, row in ICE_VEHICLE_REFERENCE.items():
        if code in text or text in code:
            return dict(row)
    return None


def _is_missing_number(value: Any) -> bool:
    return value in (None, "") or _safe_float(value, 0.0) <= 0.0


def apply_ice_reference_defaults(vehicle_like: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(vehicle_like)
    vehicle_type = str(payload.get("type") or "").upper()
    if vehicle_type != "ICE":
        return payload

    ref = lookup_ice_reference(payload.get("modelCode") or payload.get("modelName"))
    if not ref:
        return payload

    payload["modelCode"] = str(payload.get("modelCode") or ref.get("modelCode") or "")

    if _safe_int(payload.get("capacityPassengers"), 0) <= 0:
        payload["capacityPassengers"] = _safe_int(ref.get("capacityPassengers"), 0)

    for field in (
        "fuelEfficiencyKmPerL",
        "co2EmissionGPerKm",
        "curbWeightKg",
        "grossVehicleWeightKg",
        "engineDisplacementL",
        "maxTorqueNm",
        "maxPowerKw",
    ):
        if _is_missing_number(payload.get(field)):
            payload[field] = ref.get(field)

    if _is_missing_number(payload.get("energyConsumption")):
        kmpl = _safe_float(payload.get("fuelEfficiencyKmPerL"), 0.0)
        if kmpl > 0:
            payload["energyConsumption"] = round(1.0 / kmpl, 6)

    if _is_missing_number(payload.get("co2EmissionKgPerL")):
        gpkm = _safe_float(payload.get("co2EmissionGPerKm"), 0.0)
        lpkm = _safe_float(payload.get("energyConsumption"), 0.0)
        if gpkm > 0 and lpkm > 0:
            payload["co2EmissionKgPerL"] = round((gpkm / 1000.0) / lpkm, 6)

    return payload
