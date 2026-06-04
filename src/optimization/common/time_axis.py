from __future__ import annotations

from typing import Any


ALLOWED_TIMESTEP_MIN = {30, 60}


def normalize_timestep_min(raw: Any, *, default: int = 30) -> int:
    if raw is None or raw == "":
        value = default
    elif isinstance(raw, str):
        text = raw.strip().lower()
        aliases = {
            "30": 30,
            "30m": 30,
            "30min": 30,
            "pt30m": 30,
            "60": 60,
            "60m": 60,
            "60min": 60,
            "1h": 60,
            "pt1h": 60,
        }
        if text in aliases:
            value = aliases[text]
        else:
            try:
                value = int(float(text))
            except ValueError as exc:
                raise ValueError(f"timestep_min must be 30 or 60 minutes, got {raw!r}") from exc
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"timestep_min must be 30 or 60 minutes, got {raw!r}") from exc

    if value not in ALLOWED_TIMESTEP_MIN:
        raise ValueError(f"timestep_min must be 30 or 60 minutes, got {value!r}")
    return value


def slot_hours(timestep_min: Any, *, default: int = 30) -> float:
    return normalize_timestep_min(timestep_min, default=default) / 60.0
