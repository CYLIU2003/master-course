from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Dict, Literal, Mapping, Optional, Sequence, Tuple


SCENARIO_FLEET_CONTRACT_SCHEMA_VERSION = "scenario_fleet_contract_v2"
SUPPORTED_RESEARCH_POWERTRAINS = frozenset({"BEV", "ICE"})

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})
_BEV_ALIASES = frozenset({"BEV", "EV", "ELECTRIC", "BATTERY_ELECTRIC"})
_ICE_ALIASES = frozenset(
    {"ICE", "DIESEL", "GASOLINE", "PETROL", "INTERNAL_COMBUSTION"}
)


class FleetContractError(ValueError):
    """Raised when a scenario cannot produce an auditable formal fleet."""


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) is not None:
            return record.get(key)
    return None


def parse_vehicle_available(value: Any, *, research_run: bool) -> bool:
    """Parse vehicle availability without Python's truthy-string ambiguity."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    if research_run:
        raise FleetContractError(
            f"vehicle availability must be an explicit boolean token, got {value!r}"
        )
    return bool(value)


def _vehicle_catalog_records(
    scenario_or_catalog: Optional[Mapping[str, Any] | Sequence[Mapping[str, Any]]],
) -> Tuple[Mapping[str, Any], ...]:
    if scenario_or_catalog is None:
        return ()
    if isinstance(scenario_or_catalog, Mapping):
        candidates: list[Any] = []
        for key in (
            "vehicle_type_catalog",
            "vehicleTypeCatalog",
            "vehicle_types",
            "vehicleTypes",
            "vehicle_catalog",
            "vehicleCatalog",
        ):
            raw = scenario_or_catalog.get(key)
            if isinstance(raw, Mapping):
                candidates.extend(
                    dict(value, id=value.get("id") or item_key)
                    if isinstance(value, Mapping)
                    else {"id": item_key, "powertrain": value}
                    for item_key, value in raw.items()
                )
            elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                candidates.extend(raw)
        return tuple(item for item in candidates if isinstance(item, Mapping))
    return tuple(item for item in scenario_or_catalog if isinstance(item, Mapping))


def _catalog_index(
    scenario_or_catalog: Optional[Mapping[str, Any] | Sequence[Mapping[str, Any]]],
) -> Dict[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    for item in _vehicle_catalog_records(scenario_or_catalog):
        for value in (
            item.get("id"),
            item.get("type"),
            item.get("vehicleType"),
            item.get("vehicle_type"),
            item.get("modelCode"),
            item.get("model_code"),
            item.get("modelName"),
            item.get("model_name"),
            item.get("name"),
        ):
            normalized = str(value or "").strip().casefold()
            if normalized:
                index.setdefault(normalized, item)
    return index


def canonical_vehicle_type(
    record: Mapping[str, Any],
    vehicle_type_catalog: Optional[
        Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ] = None,
    *,
    research_run: bool = False,
) -> str:
    """Return the explicit vehicle type, rejecting hidden defaults in formal runs."""

    raw_type = _first_present(
        record,
        "type",
        "vehicleType",
        "vehicle_type",
        "modelCode",
        "model_code",
        "modelName",
        "model_name",
    )
    normalized = str(raw_type or "").strip()
    if normalized:
        return normalized.upper()
    if research_run:
        raise FleetContractError("vehicle type is required for a formal run")
    return "BEV"


def canonical_powertrain(
    record: Mapping[str, Any],
    vehicle_type_catalog: Optional[
        Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ] = None,
    *,
    research_run: bool = False,
) -> str:
    """Resolve one canonical powertrain using record data and the type catalog."""

    raw_explicit = _first_present(
        record,
        "powertrain",
        "powertrainType",
        "powertrain_type",
        "fuelType",
        "fuel_type",
    )
    raw_type = _first_present(
        record,
        "type",
        "vehicleType",
        "vehicle_type",
        "modelCode",
        "model_code",
        "modelName",
        "model_name",
    )

    def _normalize(value: Any) -> str:
        token = str(value or "").strip().upper()
        if token in _BEV_ALIASES:
            return "BEV"
        if token in _ICE_ALIASES:
            return "ICE"
        if token in {"PHEV", "FCEV"}:
            return token
        return ""

    explicit = _normalize(raw_explicit)
    if explicit:
        return explicit
    type_alias = _normalize(raw_type)
    if type_alias:
        return type_alias

    catalog = _catalog_index(vehicle_type_catalog)
    catalog_record = catalog.get(str(raw_type or "").strip().casefold())
    if catalog_record is not None:
        for value in (
            catalog_record.get("powertrain"),
            catalog_record.get("powertrainType"),
            catalog_record.get("powertrain_type"),
            catalog_record.get("fuelType"),
            catalog_record.get("fuel_type"),
            catalog_record.get("type"),
        ):
            resolved = _normalize(value)
            if resolved:
                return resolved

    if not research_run:
        if (_finite_float(_first_present(record, "batteryKwh", "battery_capacity_kwh")) or 0.0) > 0:
            return "BEV"
        if (
            (_finite_float(_first_present(record, "fuelConsumptionLPerKm", "fuel_consumption_l_per_km")) or 0.0)
            > 0
            or (_finite_float(_first_present(record, "fuelEfficiencyKmPerL", "fuel_efficiency_km_per_l")) or 0.0)
            > 0
        ):
            return "ICE"
    raise FleetContractError(
        f"unsupported or unknown vehicle powertrain for type {raw_type!r}"
    )


def _vehicle_id(record: Mapping[str, Any]) -> str:
    return str(
        _first_present(record, "id", "vehicleId", "vehicle_id") or ""
    ).strip()


def _vehicle_depot_id(record: Mapping[str, Any]) -> str:
    return str(
        _first_present(
            record,
            "depotId",
            "depot_id",
            "homeDepotId",
            "home_depot_id",
        )
        or ""
    ).strip()


def vehicle_record_available(
    record: Mapping[str, Any],
    *,
    research_run: bool,
) -> tuple[bool, str]:
    """Resolve availability fields and reject contradictory formal records."""

    parsed: list[tuple[str, bool]] = []
    for key in ("available", "availability", "enabled"):
        if key not in record:
            continue
        parsed.append(
            (
                key,
                parse_vehicle_available(
                    record.get(key),
                    research_run=research_run,
                ),
            )
        )
    if not parsed:
        if research_run:
            raise FleetContractError(
                "vehicle availability is required for a formal run"
            )
        return True, "missing_default_true"
    distinct_values = {value for _key, value in parsed}
    if len(distinct_values) > 1:
        if research_run:
            raise FleetContractError(
                "conflicting vehicle availability fields: "
                + ", ".join(f"{key}={value}" for key, value in parsed)
            )
        return all(value for _key, value in parsed), "conflict_fail_closed"
    false_sources = [key for key, value in parsed if not value]
    source = false_sources[0] if false_sources else parsed[0][0]
    return parsed[0][1], source


def _fuel_consumption_l_per_km(record: Mapping[str, Any]) -> Optional[float]:
    direct = _finite_float(
        _first_present(
            record,
            "fuelConsumptionLPerKm",
            "fuel_consumption_l_per_km",
        )
    )
    if direct is not None:
        return direct
    efficiency = _finite_float(
        _first_present(
            record,
            "fuelEfficiencyKmPerL",
            "fuel_efficiency_km_per_l",
        )
    )
    if efficiency is not None and efficiency > 0:
        return 1.0 / efficiency
    # Existing scenario records use energyConsumption for ICE litres/km.
    return _finite_float(
        _first_present(
            record,
            "energyConsumption",
            "energy_consumption_l_per_km",
        )
    )


def _catalog_record_for_vehicle(
    record: Mapping[str, Any],
    scenario_or_catalog: Optional[
        Mapping[str, Any] | Sequence[Mapping[str, Any]]
    ],
) -> Mapping[str, Any]:
    raw_type = _first_present(
        record,
        "type",
        "vehicleType",
        "vehicle_type",
        "modelCode",
        "model_code",
        "modelName",
        "model_name",
    )
    return _catalog_index(scenario_or_catalog).get(
        str(raw_type or "").strip().casefold(),
        {},
    )


def _record_or_catalog_value(
    record: Mapping[str, Any],
    catalog_record: Mapping[str, Any],
    *keys: str,
) -> Any:
    value = _first_present(record, *keys)
    return value if value is not None else _first_present(catalog_record, *keys)


def _canonical_record_payload(
    record: Mapping[str, Any],
    *,
    catalog_record: Mapping[str, Any],
    vehicle_id: str,
    vehicle_type: str,
    powertrain: str,
    depot_id: str,
    available: bool,
) -> Dict[str, Any]:
    compatible_raw = _record_or_catalog_value(
        record,
        catalog_record,
        "compatibleChargerIds",
        "compatible_charger_ids",
    )
    if isinstance(compatible_raw, str):
        compatible_raw = [compatible_raw]
    compatible = sorted(
        {
            str(value).strip()
            for value in list(compatible_raw or [])
            if str(value).strip()
        }
    )
    battery_capacity_kwh = _finite_float(
        _record_or_catalog_value(
            record,
            catalog_record,
            "batteryKwh",
            "battery_capacity_kwh",
        )
    )
    raw_initial_soc = _finite_float(
        _first_present(record, "initialSoc", "initial_soc", "initial_soc_kwh")
    )
    initial_soc_kwh = None
    if raw_initial_soc is not None and battery_capacity_kwh is not None:
        initial_soc_ratio = (
            raw_initial_soc / 100.0
            if raw_initial_soc > 1.0
            else raw_initial_soc
        )
        initial_soc_kwh = initial_soc_ratio * battery_capacity_kwh
    merged_fuel_record = {**dict(catalog_record), **dict(record)}
    return {
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
        "powertrain": powertrain,
        "depot_id": depot_id,
        "available": available,
        "initial_soc_raw": raw_initial_soc,
        "initial_soc": initial_soc_kwh,
        "initial_soc_declared": any(
            key in record for key in ("initialSoc", "initial_soc", "initial_soc_kwh")
        ),
        "initial_fuel_l": _finite_float(
            _first_present(record, "initialFuelL", "initial_fuel_l")
        ),
        "initial_fuel_declared": any(
            key in record for key in ("initialFuelL", "initial_fuel_l")
        ),
        "battery_capacity_kwh": battery_capacity_kwh,
        "fuel_tank_capacity_l": _finite_float(
            _record_or_catalog_value(
                record,
                catalog_record,
                "fuelTankL",
                "fuel_tank_capacity_l",
            )
        ),
        "energy_consumption_kwh_per_km": _finite_float(
            _record_or_catalog_value(
                record,
                catalog_record,
                "energyConsumption",
                "energy_consumption_kwh_per_km",
            )
        )
        if powertrain == "BEV"
        else None,
        "fuel_consumption_l_per_km": _fuel_consumption_l_per_km(
            merged_fuel_record
        )
        if powertrain == "ICE"
        else None,
        "charge_power_max_kw": _finite_float(
            _record_or_catalog_value(
                record,
                catalog_record,
                "chargePowerKw",
                "charge_power_max_kw",
            )
        ),
        "compatible_charger_ids": compatible,
        "charger_compatibility_declared": any(
            key in record or key in catalog_record
            for key in ("compatibleChargerIds", "compatible_charger_ids")
        ),
        # Preserve every input field so an unlisted vehicle parameter change
        # cannot pass a formal pair comparison merely because counts match.
        "source_record": dict(record),
        "source_vehicle_type_catalog_record": dict(catalog_record),
    }


def _validate_research_parameters(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    vehicle_id = str(payload["vehicle_id"])
    powertrain = str(payload["powertrain"])
    if powertrain == "BEV":
        if float(payload.get("battery_capacity_kwh") or 0.0) <= 0.0:
            errors.append(f"{vehicle_id}:missing_or_invalid_battery_capacity_kwh")
        if float(payload.get("energy_consumption_kwh_per_km") or 0.0) <= 0.0:
            errors.append(
                f"{vehicle_id}:missing_or_invalid_energy_consumption_kwh_per_km"
            )
        raw_initial_soc = payload.get("initial_soc_raw")
        if not payload.get("initial_soc_declared"):
            errors.append(f"{vehicle_id}:missing_initial_soc")
        elif (
            raw_initial_soc is None
            or float(raw_initial_soc) < 0.0
            or float(raw_initial_soc) > 100.0
        ):
            errors.append(f"{vehicle_id}:invalid_initial_soc")
        if float(payload.get("charge_power_max_kw") or 0.0) <= 0.0:
            errors.append(f"{vehicle_id}:missing_or_invalid_charge_power_max_kw")
        if not payload.get("charger_compatibility_declared"):
            errors.append(f"{vehicle_id}:missing_charger_compatibility_declaration")
    elif powertrain == "ICE":
        if float(payload.get("fuel_consumption_l_per_km") or 0.0) <= 0.0:
            errors.append(f"{vehicle_id}:missing_or_invalid_fuel_consumption_l_per_km")
        if float(payload.get("fuel_tank_capacity_l") or 0.0) <= 0.0:
            errors.append(f"{vehicle_id}:missing_or_invalid_fuel_tank_capacity_l")
        if not payload.get("initial_fuel_declared"):
            errors.append(f"{vehicle_id}:missing_initial_fuel_l")
        initial_fuel_l = payload.get("initial_fuel_l")
        fuel_tank_l = payload.get("fuel_tank_capacity_l")
        if (
            initial_fuel_l is None
            or float(initial_fuel_l) < 0.0
            or (
                fuel_tank_l is not None
                and float(initial_fuel_l) > float(fuel_tank_l)
            )
        ):
            errors.append(f"{vehicle_id}:invalid_initial_fuel_l")
    return errors


@dataclass(frozen=True)
class ScenarioFleetContract:
    schema_version: str
    source: str
    selected_depot_ids: Tuple[str, ...]
    all_persisted_vehicle_ids: Tuple[str, ...]
    active_vehicle_ids: Tuple[str, ...]
    excluded_vehicle_records: Tuple[Dict[str, Any], ...]
    inventory_by_powertrain: Dict[str, int]
    inventory_by_vehicle_type: Dict[str, int]
    active_vehicle_id_hash: str
    initial_state_hash: str
    vehicle_parameter_hash: str
    fleet_contract_hash: str
    active_vehicle_parameters: Tuple[Dict[str, Any], ...]
    active_vehicle_records: Tuple[Dict[str, Any], ...]
    validation_status: Literal["OK", "ERROR"]
    errors: Tuple[str, ...]

    def to_dict(self, *, include_source_records: bool = False) -> Dict[str, Any]:
        parameters = []
        for item in self.active_vehicle_parameters:
            row = dict(item)
            if not include_source_records:
                row.pop("source_record", None)
            parameters.append(row)
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "selected_depot_ids": list(self.selected_depot_ids),
            "all_persisted_vehicle_ids": list(self.all_persisted_vehicle_ids),
            "active_vehicle_ids": list(self.active_vehicle_ids),
            "excluded_vehicle_records": [
                dict(item) for item in self.excluded_vehicle_records
            ],
            "active_inventory_by_powertrain": dict(self.inventory_by_powertrain),
            "active_inventory_by_vehicle_type": dict(self.inventory_by_vehicle_type),
            "active_vehicle_id_hash": self.active_vehicle_id_hash,
            "initial_state_hash": self.initial_state_hash,
            "vehicle_parameter_hash": self.vehicle_parameter_hash,
            "fleet_contract_hash": self.fleet_contract_hash,
            "active_vehicle_parameters": parameters,
            "validation_status": self.validation_status,
            "errors": list(self.errors),
        }


def resolve_scenario_fleet_contract(
    scenario: Mapping[str, Any],
    *,
    selected_depot_ids: Sequence[str],
    research_run: bool,
) -> ScenarioFleetContract:
    """Resolve the exact active fleet from a materialized prepared scenario."""

    records = tuple(
        dict(item)
        for item in list(scenario.get("vehicles") or [])
        if isinstance(item, Mapping)
    )
    requested_depots = tuple(
        sorted({str(item).strip() for item in selected_depot_ids if str(item).strip()})
    )
    record_depots = tuple(
        sorted({_vehicle_depot_id(item) for item in records if _vehicle_depot_id(item)})
    )
    errors: list[str] = []
    if not requested_depots:
        if len(record_depots) == 1:
            requested_depots = record_depots
        elif research_run:
            errors.append(
                "selected_depot_ids_required_for_zero_or_multiple_depot_scenario"
            )

    scoped_records = tuple(
        item
        for item in records
        if not requested_depots or _vehicle_depot_id(item) in requested_depots
    )
    active_records: list[Dict[str, Any]] = []
    active_parameters: list[Dict[str, Any]] = []
    excluded: list[Dict[str, Any]] = []
    persisted_ids: list[str] = []
    seen_ids: set[str] = set()

    for index, record in enumerate(scoped_records):
        vehicle_id = _vehicle_id(record)
        if not vehicle_id:
            if research_run:
                errors.append(f"record_{index}:missing_vehicle_id")
                continue
            vehicle_id = f"veh_{index + 1:03d}"
        normalized_id = vehicle_id.casefold()
        if normalized_id in seen_ids:
            errors.append(f"duplicate_vehicle_id:{vehicle_id}")
            continue
        seen_ids.add(normalized_id)
        persisted_ids.append(vehicle_id)

        depot_id = _vehicle_depot_id(record)
        if research_run and not depot_id:
            errors.append(f"{vehicle_id}:missing_depot_id")
            continue

        try:
            available, availability_source = vehicle_record_available(
                record,
                research_run=research_run,
            )
        except FleetContractError as exc:
            errors.append(f"{vehicle_id}:{exc}")
            continue
        if not available:
            excluded.append(
                {
                    "vehicle_id": vehicle_id,
                    "reason": (
                        "available_false"
                        if availability_source == "available"
                        else (
                            "availability_false"
                            if availability_source == "availability"
                            else (
                                "enabled_false"
                                if availability_source == "enabled"
                                else "availability_conflict_false"
                            )
                        )
                    ),
                    "depot_id": depot_id or None,
                }
            )
            continue

        try:
            vehicle_type = canonical_vehicle_type(
                record, scenario, research_run=research_run
            )
            powertrain = canonical_powertrain(
                record, scenario, research_run=research_run
            )
        except FleetContractError as exc:
            errors.append(f"{vehicle_id}:{exc}")
            continue
        if research_run and powertrain not in SUPPORTED_RESEARCH_POWERTRAINS:
            errors.append(f"{vehicle_id}:unsupported_research_powertrain:{powertrain}")
            continue

        catalog_record = _catalog_record_for_vehicle(record, scenario)
        payload = _canonical_record_payload(
            record,
            catalog_record=catalog_record,
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            powertrain=powertrain,
            depot_id=depot_id,
            available=available,
        )
        if research_run:
            errors.extend(_validate_research_parameters(payload))
        normalized_record = dict(record)
        normalized_record.update(
            {
                "id": vehicle_id,
                "type": vehicle_type,
                "powertrain": powertrain,
                "depotId": depot_id,
                "available": True,
            }
        )
        normalized_physical_fields = {
            "batteryKwh": payload.get("battery_capacity_kwh"),
            "energyConsumption": (
                payload.get("energy_consumption_kwh_per_km")
                if powertrain == "BEV"
                else payload.get("fuel_consumption_l_per_km")
            ),
            "fuelTankL": payload.get("fuel_tank_capacity_l"),
            "fuelConsumptionLPerKm": payload.get(
                "fuel_consumption_l_per_km"
            ),
            "chargePowerKw": payload.get("charge_power_max_kw"),
            "compatibleChargerIds": list(
                payload.get("compatible_charger_ids") or ()
            ),
        }
        normalized_record.update(
            {
                key: value
                for key, value in normalized_physical_fields.items()
                if value is not None
            }
        )
        active_records.append(normalized_record)
        active_parameters.append(payload)

    active_parameters.sort(key=lambda item: str(item["vehicle_id"]))
    active_records.sort(key=lambda item: _vehicle_id(item))
    active_ids = tuple(str(item["vehicle_id"]) for item in active_parameters)
    if research_run and not active_ids:
        errors.append("active_vehicle_set_is_empty")

    inventory_by_powertrain = dict(
        sorted(Counter(str(item["powertrain"]) for item in active_parameters).items())
    )
    inventory_by_vehicle_type = dict(
        sorted(Counter(str(item["vehicle_type"]) for item in active_parameters).items())
    )
    parameter_payload = [
        {key: value for key, value in item.items() if key != "source_record"}
        | {"source_record": item["source_record"]}
        for item in active_parameters
    ]
    initial_state_payload = [
        {
            "vehicle_id": item["vehicle_id"],
            "initial_soc": item["initial_soc"],
            "initial_fuel_l": item["initial_fuel_l"],
        }
        for item in active_parameters
    ]
    active_vehicle_id_hash = _canonical_json_sha256(list(active_ids))
    initial_state_hash = _canonical_json_sha256(initial_state_payload)
    vehicle_parameter_hash = _canonical_json_sha256(parameter_payload)
    contract_core = {
        "schema_version": SCENARIO_FLEET_CONTRACT_SCHEMA_VERSION,
        "selected_depot_ids": list(requested_depots),
        "active_vehicle_ids": list(active_ids),
        "excluded_vehicle_records": excluded,
        "inventory_by_powertrain": inventory_by_powertrain,
        "inventory_by_vehicle_type": inventory_by_vehicle_type,
        "active_vehicle_id_hash": active_vehicle_id_hash,
        "initial_state_hash": initial_state_hash,
        "vehicle_parameter_hash": vehicle_parameter_hash,
    }
    fleet_contract_hash = _canonical_json_sha256(contract_core)
    contract = ScenarioFleetContract(
        schema_version=SCENARIO_FLEET_CONTRACT_SCHEMA_VERSION,
        source="materialized_prepared_scenario_selected_scope",
        selected_depot_ids=requested_depots,
        all_persisted_vehicle_ids=tuple(sorted(persisted_ids)),
        active_vehicle_ids=active_ids,
        excluded_vehicle_records=tuple(excluded),
        inventory_by_powertrain=inventory_by_powertrain,
        inventory_by_vehicle_type=inventory_by_vehicle_type,
        active_vehicle_id_hash=active_vehicle_id_hash,
        initial_state_hash=initial_state_hash,
        vehicle_parameter_hash=vehicle_parameter_hash,
        fleet_contract_hash=fleet_contract_hash,
        active_vehicle_parameters=tuple(active_parameters),
        active_vehicle_records=tuple(active_records),
        validation_status="ERROR" if errors else "OK",
        errors=tuple(errors),
    )
    if research_run and errors:
        raise FleetContractError(
            "scenario fleet contract failed: " + "; ".join(errors)
        )
    return contract
