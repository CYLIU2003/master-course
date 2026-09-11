"""No missing-as-zero, false rain labels, integration loss or holdout leakage."""

from datetime import date, datetime, timedelta

import pytest

from src.preprocess.weather.seasonal_irradiance import WeatherClassificationPolicy, build_seasonal_curves, classify_day
from src.preprocess.weather.solcast_archive import JST, resample_records


def day_rows(day: date, *, ratio: float = .8, daylight_rain: float = 0, night_rain: float = 0, temperature: float = 15) -> list[dict]:
    start = datetime.combine(day, datetime.min.time(), JST)
    rows = []
    for slot in range(96):
        daylight = 24 <= slot < 72
        clear = 800.0 if daylight else 0.0
        rows.append({'period_end': (start+timedelta(minutes=15*(slot+1))).isoformat(), 'period':'PT15M',
                     'ghi':clear*ratio, 'clearsky_ghi':clear,
                     'precipitation_rate': daylight_rain if daylight else night_rain, 'air_temp':temperature})
    return rows


@pytest.mark.parametrize('damage', ['missing','duplicate','shift','negative','nan','null','cadence'])
def test_corrupt_daily_coverage_is_rejected(damage):
    rows = day_rows(date(2025,1,1))
    if damage == 'missing':
        rows.pop(40)
    elif damage == 'duplicate':
        rows[40] = dict(rows[39])
    elif damage == 'shift':
        rows[40]['period_end'] = '2025-01-01T10:16:00+09:00'
    elif damage == 'cadence':
        rows[40]['period'] = 'PT60M'
    else:
        rows[40]['ghi'] = {'negative': -1, 'nan': float('nan'), 'null': None}[damage]
    with pytest.raises(ValueError):
        classify_day(rows, WeatherClassificationPolicy())


def test_low_irradiance_without_precipitation_is_cloudy_not_rain():
    label = classify_day(day_rows(date(2025,1,1), ratio=.1), WeatherClassificationPolicy())
    assert label['weather_class'] == 'cloudy'
    assert label['quality_flag'] == 'accepted'


def test_night_rain_does_not_turn_sunny_day_into_rain_curve():
    label = classify_day(day_rows(date(2025,1,1), night_rain=1), WeatherClassificationPolicy())
    assert label['weather_class'] == 'sunny'
    assert 'precipitation_predominantly_outside_daylight' in label['flags']


def test_daylight_rain_and_possible_snow_remain_distinct():
    rainy = day_rows(date(2025,1,1), ratio=.1, daylight_rain=1)
    label = classify_day(rainy, WeatherClassificationPolicy())
    assert label['weather_class'] == 'rainy'
    snow = day_rows(date(2025,1,1), ratio=.1, daylight_rain=1, temperature=0)
    label = classify_day(snow, WeatherClassificationPolicy())
    assert label['quality_flag'] == 'excluded'
    assert label['weather_class'] == 'unresolved'


def test_hourly_resampling_preserves_day_energy_and_rainfall():
    rows = day_rows(date(2025,1,1), daylight_rain=.5)
    hourly = resample_records(rows, date(2025,1,1), date(2025,1,2), 60)
    assert len(hourly) == 24
    for field in ('ghi','precipitation_rate'):
        assert sum(row[field]*.25 for row in rows) == pytest.approx(sum(row[field] for row in hourly))


def test_evaluation_day_never_enters_reference_curve():
    rows = day_rows(date(2025,1,1), ratio=.8)+day_rows(date(2025,1,2), ratio=1)
    result = build_seasonal_curves(rows, start=date(2025,1,1), end_exclusive=date(2025,1,3),
                                   excluded_dates={'2025-01-02':'evaluation_week'})
    cell = next(cell for cell in result['curves'] if cell['season']=='winter' and cell['weather_class']=='sunny')
    assert cell['source_dates'] == ['2025-01-01']
    assert cell['ghi']['mean'][40] == 640
    assert cell['status'] == 'SMALL_SAMPLE_DESCRIPTIVE'
    assert cell['sample_sufficiency'] == 'BELOW_DECLARED_MINIMUM'
    assert cell['source_year_counts'] == {'2025': 1}
    assert len(result['curves']) == 12
    assert sum(cell['source_day_count'] for cell in result['curves']) == 1


def test_temporal_fit_cutoff_rejects_future_training_data():
    rows = day_rows(date(2025,1,1))+day_rows(date(2025,1,2))
    result = build_seasonal_curves(rows, start=date(2025,1,1), end_exclusive=date(2025,1,3), fit_before=date(2025,1,2))
    assert result['daily_labels'][1]['exclusion_reason'] == 'not_available_before_fit_cutoff'
    assert sum(cell['source_day_count'] for cell in result['curves']) == 1


def test_local_midnight_belongs_to_preceding_interval_day():
    rows = day_rows(date(2025,12,31))
    assert rows[-1]['period_end'].startswith('2026-01-01T00:00')
    label = classify_day(rows, WeatherClassificationPolicy())
    assert label['date'] == '2025-12-31'
