"""F1: the planning forecast conditioned on each day's 2025 weather class (2026-11-21)."""
from pathlib import Path

import pytest

from bff.services.date_series_inputs import _date_forecast_rows
from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import planning_pv_profiles, weather_classes_2025

ROOT = Path(__file__).resolve().parents[1]
HOLDOUTS = ROOT / "output/monthly_fair_weeks_20260914/forecast_holdouts"
DATES = [f"2025-01-{d:02d}" for d in range(6, 13)]


@pytest.mark.skipif(not HOLDOUTS.exists(), reason="frozen forecast holdouts not present")
def test_known_class_forecast_uses_the_same_model_and_orders_days_by_class():
    f0, audit0 = _date_forecast_rows(ROOT, DATES, 15, 0.85, forecast_directory=HOLDOUTS)
    classes, _ = weather_classes_2025(DATES)
    f1, audit1 = _date_forecast_rows(ROOT, DATES, 15, 0.85, forecast_directory=HOLDOUTS,
                                     known_weather_classes=classes)
    assert audit1["model_sha256"] == audit0["model_sha256"]
    assert audit0["future_weather_class_known"] is False and audit1["future_weather_class_known"] is True
    assert classes["2025-01-06"] == "rainy" and classes["2025-01-09"] == "sunny"
    total = lambda rows, day: sum(next(r for r in rows if r["date"] == day)["capacity_factor_by_slot"])  # noqa: E731
    assert total(f1, "2025-01-09") > total(f0, "2025-01-09") > total(f1, "2025-01-06")
    assert all(row["data_kind"] == "known_class_oracle_reference" for row in f1)


def test_known_class_next_morning_keeps_the_service_days_unchanged():
    """The next-morning check rebuilds F1 over the week plus one day; the week must be identical."""
    extended = DATES + ["2025-01-13"]
    week, _ = _date_forecast_rows(ROOT, DATES, 15, 0.85, known_weather_classes=weather_classes_2025(DATES)[0])
    longer, _ = _date_forecast_rows(ROOT, extended, 15, 0.85,
                                    known_weather_classes=weather_classes_2025(extended)[0])
    unconditioned, _ = _date_forecast_rows(ROOT, extended, 15, 0.85)
    assert longer[:len(DATES)] == week
    assert unconditioned[:len(DATES)] != week


def test_weather_class_source_plans_on_the_forecast_rows():
    assert planning_pv_profiles({"f": 1}, {"a": 1}, "weather_class_known") == {"f": 1}
    with pytest.raises(ValueError):
        weather_classes_2025(["2026-01-01"])
