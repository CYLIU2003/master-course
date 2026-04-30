"""Load local Solcast-derived daily PV profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.preprocess.weather.daily_weather_schema import WeatherSchemaError
from src.preprocess.weather.operation_policy import clamp


@dataclass(frozen=True)
class SolcastDailyPvProfile:
    date: str
    depot_id: str
    slot_minutes: int
    capacity_factor_by_slot: tuple[float, ...]
    source_path: str
    metadata: Mapping[str, Any]


def parse_profile_date(value: Any, field_name: str = "date") -> str:
    text = str(value or "").strip()[:10]
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise WeatherSchemaError(f"{field_name} must be YYYY-MM-DD: {value!r}") from exc
    return text


def _coerce_float_series(values: Iterable[Any], field_name: str) -> list[float]:
    series: list[float] = []
    for idx, value in enumerate(values):
        try:
            series.append(max(0.0, float(value)))
        except (TypeError, ValueError) as exc:
            raise WeatherSchemaError(f"{field_name}[{idx}] must be numeric") from exc
    if not series:
        raise WeatherSchemaError(f"{field_name} must not be empty")
    return series


def _capacity_factors_from_generation(raw: Mapping[str, Any]) -> list[float]:
    generation = _coerce_float_series(
        raw.get("pv_generation_kwh_by_slot") or (),
        "pv_generation_kwh_by_slot",
    )
    try:
        capacity_kw = float(raw.get("capacity_kw"))
        slot_minutes = float(raw.get("slot_minutes"))
    except (TypeError, ValueError) as exc:
        raise WeatherSchemaError(
            "capacity_factor_by_slot missing; capacity_kw and slot_minutes are required"
        ) from exc
    if capacity_kw <= 0.0 or slot_minutes <= 0.0:
        raise WeatherSchemaError("capacity_kw and slot_minutes must be positive")
    slot_hours = slot_minutes / 60.0
    return [clamp(kwh / (capacity_kw * slot_hours)) for kwh in generation]


def _slot_minutes(raw: Mapping[str, Any], slot_count: int) -> int:
    value = raw.get("slot_minutes")
    if value not in (None, ""):
        try:
            minutes = int(value)
        except (TypeError, ValueError) as exc:
            raise WeatherSchemaError(f"slot_minutes must be integer: {value!r}") from exc
        if minutes <= 0:
            raise WeatherSchemaError("slot_minutes must be positive")
        return minutes
    if slot_count > 0 and 1440 % slot_count == 0:
        return 1440 // slot_count
    raise WeatherSchemaError("slot_minutes is required when slot count does not divide 24h")


def load_solcast_daily_pv_profile(path: str | Path) -> SolcastDailyPvProfile:
    profile_path = Path(path)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WeatherSchemaError(f"Solcast PV profile must be an object: {profile_path}")
    values = raw.get("capacity_factor_by_slot")
    capacity_factors = (
        [clamp(value) for value in _coerce_float_series(values, "capacity_factor_by_slot")]
        if values
        else _capacity_factors_from_generation(raw)
    )
    slot_minutes = _slot_minutes(raw, len(capacity_factors))
    if len(capacity_factors) * slot_minutes != 1440:
        raise WeatherSchemaError(
            f"Solcast profile must cover exactly 24h: {profile_path} "
            f"slots={len(capacity_factors)} slot_minutes={slot_minutes}"
        )
    return SolcastDailyPvProfile(
        date=parse_profile_date(raw.get("date"), "date"),
        depot_id=str(raw.get("depot_id") or raw.get("depotId") or "depot_default"),
        slot_minutes=slot_minutes,
        capacity_factor_by_slot=tuple(capacity_factors),
        source_path=str(profile_path),
        metadata=dict(raw.get("metadata") or {}),
    )


def load_solcast_daily_pv_profiles(
    profile_paths: Sequence[str | Path] | None = None,
    *,
    profile_dir: str | Path | None = None,
    glob_pattern: str = "*_60min.json",
    depot_id: str | None = None,
) -> tuple[SolcastDailyPvProfile, ...]:
    paths: list[Path] = [Path(item) for item in (profile_paths or ())]
    if profile_dir is not None:
        paths.extend(sorted(Path(profile_dir).glob(glob_pattern)))
    if not paths:
        raise WeatherSchemaError("No Solcast PV profile JSON files were provided")
    profiles = [load_solcast_daily_pv_profile(path) for path in sorted(set(paths))]
    if depot_id:
        profiles = [profile for profile in profiles if profile.depot_id == str(depot_id)]
    if not profiles:
        raise WeatherSchemaError(f"No Solcast PV profiles matched depot_id={depot_id!r}")
    return tuple(sorted(profiles, key=lambda item: (item.depot_id, item.date, item.source_path)))
