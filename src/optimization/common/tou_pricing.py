from __future__ import annotations

from typing import Any, Mapping, Sequence


def price_for_minute(
    tou_bands: Sequence[Mapping[str, Any]],
    *,
    minute_of_day: int,
    default_price: float,
) -> float:
    """Return the TOU price for a local clock minute.

    ``start_hour`` and ``end_hour`` are clock-hour boundaries in the range
    0..24.  They are not half-hour slot indices.  Invalid persisted bands are
    rejected so a research run cannot silently apply a tariff at the wrong
    time of day.
    """

    normalized_minute = int(minute_of_day) % (24 * 60)
    fallback = float(default_price)
    for index, band in enumerate(tou_bands):
        try:
            raw_start = band["start_hour"]
            raw_end = band["end_hour"]
            start_hour = int(raw_start)
            end_hour = int(raw_end)
            price = float(band["price_per_kwh"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid TOU band at index {index}: {band!r}") from exc
        if isinstance(raw_start, bool) or isinstance(raw_end, bool):
            raise ValueError(f"TOU boundaries must be integer clock hours; got {band!r}")
        if float(raw_start) != start_hour or float(raw_end) != end_hour:
            raise ValueError(f"TOU boundaries must be integer clock hours; got {band!r}")
        if not 0 <= start_hour < end_hour <= 24:
            raise ValueError(
                "TOU band boundaries must satisfy "
                f"0 <= start_hour < end_hour <= 24; got {start_hour}..{end_hour}"
            )
        if price < 0.0:
            raise ValueError(f"TOU price must be non-negative; got {price}")
        if start_hour * 60 <= normalized_minute < end_hour * 60:
            return price
    return fallback
