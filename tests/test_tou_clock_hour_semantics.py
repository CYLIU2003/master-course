from __future__ import annotations

import pytest
from pydantic import ValidationError

from bff.mappers.scenario_to_problemdata import _slot_price_from_tou
from bff.routers.simulation import PrepareTimeOfUseBandBody
from src.optimization.common.tou_pricing import price_for_minute
from src.scenario_overlay import TimeOfUseBand, default_overlay_seed


TOU_BANDS = [
    {"start_hour": 0, "end_hour": 16, "price_per_kwh": 18.0},
    {"start_hour": 16, "end_hour": 18, "price_per_kwh": 22.0},
    {"start_hour": 18, "end_hour": 24, "price_per_kwh": 19.0},
]


@pytest.mark.parametrize(
    ("minute_of_day", "expected"),
    [
        (15 * 60 + 59, 18.0),
        (16 * 60, 22.0),
        (17 * 60 + 59, 22.0),
        (18 * 60, 19.0),
        (23 * 60 + 59, 19.0),
    ],
)
def test_tou_price_uses_clock_hours(minute_of_day: int, expected: float) -> None:
    assert price_for_minute(TOU_BANDS, minute_of_day=minute_of_day, default_price=99.0) == expected


@pytest.mark.parametrize(
    ("slot_index", "expected"),
    [
        (3, 18.0),   # 08:00, not half-hour index 16
        (11, 22.0),  # 16:00
        (13, 19.0),  # 18:00
        (19, 18.0),  # next day 00:00
    ],
)
def test_problemdata_mapper_uses_frontend_clock_hour_contract(slot_index: int, expected: float) -> None:
    assert _slot_price_from_tou(
        TOU_BANDS,
        slot_index=slot_index,
        delta_t_min=60,
        start_time="05:00",
        default_price=99.0,
    ) == expected


@pytest.mark.parametrize("model", [TimeOfUseBand, PrepareTimeOfUseBandBody])
def test_tou_schema_rejects_legacy_half_hour_index_boundaries(model: type) -> None:
    with pytest.raises(ValidationError):
        model(start_hour=16, end_hour=48, price_per_kwh=19.0)
    with pytest.raises(ValidationError):
        model(start_hour=18, end_hour=16, price_per_kwh=19.0)


def test_tou_runtime_rejects_invalid_persisted_band() -> None:
    with pytest.raises(ValueError, match="0 <= start_hour"):
        price_for_minute(
            [{"start_hour": 16, "end_hour": 48, "price_per_kwh": 19.0}],
            minute_of_day=18 * 60,
            default_price=18.0,
        )


def test_default_overlay_seed_preserves_template_clock_hours() -> None:
    bands = default_overlay_seed()["cost_coefficients"]["tou_pricing"]

    assert [(band.start_hour, band.end_hour) for band in bands] == [
        (0, 8),
        (8, 22),
        (22, 24),
    ]
