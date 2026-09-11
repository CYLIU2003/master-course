"""Seasonal descriptive curves with declared weather proxies and exclusion logs.

Weather labels use daylight precipitation and a clear-sky ratio. They are a
research definition based on Solcast estimated actuals, not JMA observations,
historical forecasts, or empirically calibrated forecast-error distributions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from datetime import date, datetime, timedelta
import math
from statistics import fmean, pstdev
from typing import Mapping, Sequence

from .solcast_archive import JST, parse_timestamp, period_minutes, validate_records


SEASONS = ('spring', 'summer', 'autumn', 'winter')
WEATHER = ('sunny', 'cloudy', 'rainy')
SOURCE_DEFINITIONS_URL = 'https://docs.solcast.com.au/docs/output-parameters'


@dataclass(frozen=True)
class WeatherClassificationPolicy:
    """Fixed before inspecting class counts; thresholds are modeling choices."""

    version: str = 'solcast_daylight_precip_clearsky_v1'
    daylight_clearsky_ghi_w_m2: float = 20.0
    rainy_daylight_precip_mm: float = 1.0
    sunny_clearsky_ratio: float = 0.7
    suspected_solid_precip_temp_c: float = 2.0
    minimum_days_per_cell: int = 10

    def __post_init__(self) -> None:
        values = (self.daylight_clearsky_ghi_w_m2, self.rainy_daylight_precip_mm,
                  self.sunny_clearsky_ratio, self.suspected_solid_precip_temp_c)
        if not all(math.isfinite(value) for value in values):
            raise ValueError('Classification thresholds must be finite')
        if self.daylight_clearsky_ghi_w_m2 <= 0 or self.rainy_daylight_precip_mm <= 0:
            raise ValueError('Daylight and rain thresholds must be positive')
        if not 0 < self.sunny_clearsky_ratio <= 1 or self.minimum_days_per_cell < 1:
            raise ValueError('Invalid sunny ratio or minimum sample count')


def season_for(day: date) -> str:
    if day.month in (12, 1, 2):
        return 'winter'
    if day.month in (3, 4, 5):
        return 'spring'
    return 'summer' if day.month in (6, 7, 8) else 'autumn'


def quantile(values: Sequence[float], probability: float) -> float:
    if not values or not 0 <= probability <= 1:
        raise ValueError('Invalid quantile inputs')
    ordered = sorted(values)
    position = (len(ordered)-1)*probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high]-ordered[low])*(position-low)


def classify_day(rows: Sequence[dict], policy: WeatherClassificationPolicy) -> dict:
    """Classify one complete local day without mistaking low light for rain."""
    if not rows:
        raise ValueError('Cannot classify an empty day')
    minutes = period_minutes(rows[0]['period'])
    beginning = (parse_timestamp(rows[0]['period_end']) - timedelta(minutes=minutes)).astimezone(JST)
    lower = datetime.combine(beginning.date(), datetime.min.time(), JST)
    ordered = validate_records(list(rows), lower, lower+timedelta(days=1), minutes,
                               ('ghi', 'clearsky_ghi', 'precipitation_rate', 'air_temp'))
    daylight = [row for row in ordered if float(row['clearsky_ghi']) >= policy.daylight_clearsky_ghi_w_m2]
    if not daylight:
        raise ValueError('No verifiable daylight intervals')
    delta_h = minutes / 60
    rain_mm = math.fsum(float(row['precipitation_rate'])*delta_h for row in ordered)
    daylight_rain_mm = math.fsum(float(row['precipitation_rate'])*delta_h for row in daylight)
    possible_snow_mm = math.fsum(float(row['precipitation_rate'])*delta_h for row in daylight
                               if float(row['air_temp']) <= policy.suspected_solid_precip_temp_c)
    ratio = math.fsum(float(row['ghi']) for row in daylight) / math.fsum(float(row['clearsky_ghi']) for row in daylight)
    flags = []
    if daylight_rain_mm >= policy.rainy_daylight_precip_mm:
        weather = 'rainy'
        if ratio >= policy.sunny_clearsky_ratio:
            flags.append('mixed_daylight_sun_and_precipitation')
    else:
        weather = 'sunny' if ratio >= policy.sunny_clearsky_ratio else 'cloudy'
        if rain_mm >= policy.rainy_daylight_precip_mm:
            flags.append('precipitation_predominantly_outside_daylight')
    exclusion = None
    if possible_snow_mm >= policy.rainy_daylight_precip_mm:
        exclusion = 'solid_precipitation_unresolved_from_temperature_proxy'
        weather = 'unresolved'
    return {'date': beginning.date().isoformat(), 'season': season_for(beginning.date()),
            'weather_class': weather, 'label_kind': 'research_weather_proxy_from_estimated_actuals',
            'classification_version': policy.version, 'source': SOURCE_DEFINITIONS_URL,
            'daylight_clearsky_ratio': ratio, 'precipitation_mm': rain_mm,
            'daylight_precipitation_mm': daylight_rain_mm, 'possible_solid_precipitation_mm': possible_snow_mm,
            'quality_flag': 'excluded' if exclusion else 'accepted',
            'exclusion_reason': exclusion, 'flags': flags,
            'daily_irradiation_kwh_m2': math.fsum(float(row['ghi'])*delta_h/1000 for row in ordered)}


def build_seasonal_curves(records: list[dict], *, start: date, end_exclusive: date,
                          policy: WeatherClassificationPolicy = WeatherClassificationPolicy(),
                          excluded_dates: Mapping[str, str] | None = None,
                          fit_before: date | None = None) -> dict:
    """Build 12 cells and expose withheld days, unknown weather and small samples."""
    if not records:
        raise ValueError('Missing irradiance archive')
    minutes = period_minutes(records[0]['period'])
    lower, upper = (datetime.combine(day, datetime.min.time(), JST) for day in (start, end_exclusive))
    ordered = validate_records(records, lower, upper, minutes,
                               ('ghi', 'clearsky_ghi', 'precipitation_rate', 'air_temp'))
    excluded = dict(excluded_dates or {})
    if any(not reason for reason in excluded.values()):
        raise ValueError('Every held-out day needs an exclusion reason')
    requested_dates = {(start+timedelta(days=i)).isoformat() for i in range((end_exclusive-start).days)}
    if set(excluded) - requested_dates:
        raise ValueError('Held-out dates must fall within the archive range')
    slots = 1440 // minutes
    daily, curves_by_date = [], {}
    for index in range(0, len(ordered), slots):
        rows = ordered[index:index+slots]
        label = classify_day(rows, policy)
        day = label['date']
        if day in excluded:
            label.update(quality_flag='excluded', exclusion_reason=excluded[day])
        if fit_before is not None and date.fromisoformat(day) >= fit_before:
            label.update(quality_flag='excluded', exclusion_reason='not_available_before_fit_cutoff')
        daily.append(label)
        curves_by_date[day] = [float(row['ghi']) for row in rows]
    cells = []
    for season in SEASONS:
        for weather in WEATHER:
            labels = [row for row in daily if row['season'] == season and row['weather_class'] == weather
                      and row['quality_flag'] == 'accepted']
            dates = [row['date'] for row in labels]
            count = len(dates)
            cell = {'season': season, 'weather_class': weather, 'source_dates': dates,
                    'source_day_count': count, 'unit': 'W/m2', 'period_minutes': minutes,
                    'source_year_counts': dict(sorted(Counter(day[:4] for day in dates).items())),
                    'sample_sufficiency': 'MEETS_DECLARED_MINIMUM' if count >= policy.minimum_days_per_cell else 'BELOW_DECLARED_MINIMUM',
                    'status': ('DESCRIPTIVE_ONLY' if count >= policy.minimum_days_per_cell
                               else 'SMALL_SAMPLE_DESCRIPTIVE' if count else 'NO_ELIGIBLE_DAYS'),
                    'ghi': None}
            if count:
                matrix = [curves_by_date[day] for day in dates]
                means = [fmean(column) for column in zip(*matrix)]
                representative = min(dates, key=lambda day: (math.fsum(abs(a-b) for a,b in zip(curves_by_date[day], means)), day))
                energy = [row['daily_irradiation_kwh_m2'] for row in labels]
                cell['ghi'] = {'mean': means,
                               **{name: [quantile(column, p) for column in zip(*matrix)]
                                  for name,p in (('p10',.1), ('p50',.5), ('p90',.9))},
                               'population_std': [pstdev(column) for column in zip(*matrix)],
                               'representative_real_day': representative,
                               'representative_real_day_curve': curves_by_date[representative],
                               'mean_daily_irradiation_kwh_m2': fmean(energy),
                               'daily_irradiation_distribution': [{'date': row['date'], 'kwh_m2': row['daily_irradiation_kwh_m2']} for row in labels]}
            cells.append(cell)
    return {'schema_version': 'seasonal_irradiance_v1', 'timezone': 'Asia/Tokyo',
            'status': ('DESCRIPTIVE_WITH_EMPTY_CELLS' if any(c['ghi'] is None for c in cells)
                       else 'DESCRIPTIVE_WITH_SMALL_SAMPLES' if any(c['status']=='SMALL_SAMPLE_DESCRIPTIVE' for c in cells)
                       else 'DESCRIPTIVE_COMPLETE_NOT_FORECAST_VALIDATED'),
            'start': start.isoformat(), 'end_exclusive': end_exclusive.isoformat(),
            'record_count': len(ordered), 'period_minutes': minutes, 'classification_policy': asdict(policy),
            'fit_before': fit_before.isoformat() if fit_before else None,
            'purpose': 'training_reference' if excluded or fit_before else 'all_period_descriptive_reference',
            'season_definition': {'spring':[3,4,5], 'summer':[6,7,8], 'autumn':[9,10,11], 'winter':[12,1,2]},
            'daily_labels': daily, 'curves': cells,
            'limitations': ['Research weather proxies, not official daily weather observations.',
                            'Temperature-based suspected solid precipitation is excluded; snowfall is not measured here.',
                            'Finite-period reference, not a long-term climatological normal; contributing years and counts are explicit.',
                            'Pointwise empirical quantiles are not calibrated forecast intervals.',
                            'No historical forecast archive or validated forecast-error distribution.',
                            'GHI is horizontal irradiance; a PV conversion needs a separate explicit model.']}
