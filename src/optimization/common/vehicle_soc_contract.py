"""Convert declared vehicle SOC fields to explicit, validated kWh bounds.

Source ``initialSoc/minSoc/maxSoc`` are ratios or percentages; fields ending
in ``_kwh`` are energies. Canonical vehicles carry a unit marker so e.g.
0.5 kWh is never interpreted as 50 percent during a rolling update.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


def finite_soc_value(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{field} must be numeric, not boolean')
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} must be a finite number') from exc
    if not math.isfinite(result):
        raise ValueError(f'{field} must be finite')
    return result


def strict_soc_ratio(value: Any, *, field: str) -> float:
    number = finite_soc_value(value, field=field)
    ratio = number/100.0 if number > 1 else number
    if not 0 <= ratio <= 1:
        raise ValueError(f'{field} must be a ratio [0,1] or percentage [0,100]')
    return ratio


def _resolve_declared_energy(record: Mapping[str, Any], capacity: float,
                             ratio_keys: tuple[str, ...], kwh_keys: tuple[str, ...]) -> float | None:
    values = []
    for key in ratio_keys:
        if record.get(key) is not None:
            values.append(strict_soc_ratio(record[key], field=key)*capacity)
    for key in kwh_keys:
        if record.get(key) is not None:
            values.append(finite_soc_value(record[key], field=key))
    if not values:
        return None
    if any(not math.isclose(value, values[0], rel_tol=0, abs_tol=1e-9) for value in values):
        raise ValueError(f'Conflicting SOC unit/alias fields: {ratio_keys+kwh_keys}')
    return values[0]


@dataclass(frozen=True)
class VehicleSocContract:
    initial_kwh: float
    minimum_kwh: float
    maximum_kwh: float


def resolve_vehicle_soc_contract(record: Mapping[str, Any], capacity_kwh: float,
                                 *, initial_ratio_fallback: float | None = None,
                                 reserve_ratio_floor: float | None = None) -> VehicleSocContract:
    capacity = finite_soc_value(capacity_kwh, field='battery_capacity_kwh')
    if capacity <= 0:
        raise ValueError('Electric vehicle battery capacity must be positive')
    initial = _resolve_declared_energy(record, capacity, ('initialSoc','initial_soc'), ('initial_soc_kwh',))
    if initial is None:
        initial = capacity*(1.0 if initial_ratio_fallback is None else strict_soc_ratio(initial_ratio_fallback, field='initial_soc_fallback'))
    minimum = _resolve_declared_energy(record, capacity, ('minSoc','min_soc'), ('minimum_soc_kwh',))
    reserve_raw = record.get('reserveSoc')
    reserve = None
    if reserve_raw is not None:
        reserve = finite_soc_value(reserve_raw, field='reserveSoc')
        reserve = reserve*capacity if reserve <= 1 else reserve
    if minimum is None:
        minimum = reserve if reserve is not None else .1*capacity
    elif reserve is not None:
        minimum = max(minimum, reserve)
    if reserve_ratio_floor is not None:
        minimum = max(minimum, strict_soc_ratio(reserve_ratio_floor, field='reserve_ratio_floor')*capacity)
    maximum = _resolve_declared_energy(record, capacity, ('maxSoc','max_soc'), ('maximum_soc_kwh',))
    maximum = capacity if maximum is None else maximum
    if not 0 <= minimum <= maximum <= capacity:
        raise ValueError(f'Invalid SOC bounds: minimum={minimum}, maximum={maximum}, capacity={capacity} kWh')
    if not minimum-1e-9 <= initial <= maximum+1e-9:
        raise ValueError(f'Initial SOC {initial} kWh is outside [{minimum}, {maximum}] kWh')
    return VehicleSocContract(initial, minimum, maximum)


def canonical_soc_energy(vehicle: Any, field: str, capacity: float, default_ratio: float) -> float:
    raw = getattr(vehicle, field, None)
    if raw is None:
        return default_ratio*capacity
    value = finite_soc_value(raw, field=field)
    unit = getattr(vehicle, 'soc_input_unit', 'legacy_ratio_or_kwh')
    if unit not in ('kwh','legacy_ratio_or_kwh'):
        raise ValueError(f'Unknown canonical SOC unit: {unit!r}')
    if unit != 'kwh' and value <= 1:
        value *= capacity
    if not 0 <= value <= capacity:
        raise ValueError(f'{field} {value} kWh is outside battery capacity {capacity}')
    return value
