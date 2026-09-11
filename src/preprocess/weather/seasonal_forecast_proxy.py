"""Training-only climatology, with astronomical daylight at each target date.

This model is a declared baseline proxy, not an archive of issued forecasts.
Its prediction interface receives no target irradiance or realized class.
"""
from __future__ import annotations

from calendar import isleap
from collections import defaultdict
from datetime import datetime, timedelta
import math
from statistics import fmean
from typing import Mapping, Sequence

from .seasonal_irradiance import season_for
from .solcast_archive import JST, parse_timestamp, period_minutes

SOLAR_POSITION_SOURCE = 'https://gml.noaa.gov/grad/solcalc/solareqns.PDF'
CLEAR_SKY_SOURCE = 'https://pvlib-python.readthedocs.io/en/stable/_modules/pvlib/clearsky.html#haurwitz'


def astronomical_clear_ghi(stamp: datetime, latitude: float, longitude: float) -> float:
    """NOAA geometric zenith plus Haurwitz GHI; no atmospheric refraction.

    This smooth geometric envelope is used in both fitting and prediction.
    It does not use the target day's estimated atmosphere or weather.
    """
    if stamp.utcoffset() is None:
        raise ValueError('Solar geometry requires a timezone-aware timestamp')
    stamp=stamp.astimezone(JST)
    minute=stamp.hour*60+stamp.minute+stamp.second/60
    gamma=2*math.pi/(366 if isleap(stamp.year) else 365)*(stamp.timetuple().tm_yday-1+(minute/60-12)/24)
    equation=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)-.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    declination=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)-.006758*math.cos(2*gamma)
                 +.000907*math.sin(2*gamma)-.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    hour_angle=math.radians((minute+equation+4*longitude-540)/4-180)
    latitude_rad=math.radians(latitude)
    cosine=math.sin(latitude_rad)*math.sin(declination)+math.cos(latitude_rad)*math.cos(declination)*math.cos(hour_angle)
    return 1098*cosine*math.exp(-.059/cosine) if cosine>0 else 0.0


def fit_climatology_proxy(records: Sequence[Mapping], reference: Mapping, *, latitude: float, longitude: float) -> dict:
    """Fit each seasonal class from explicitly accepted training dates only."""
    cutoff=reference.get('fit_before')
    if not cutoff or reference.get('purpose')!='training_reference':
        raise ValueError('Forecast fitting requires a separate training-only reference')
    step=int(reference['period_minutes'])
    by_day=defaultdict(list)
    for row in records:
        if period_minutes(row['period'])!=step:
            raise ValueError('Training cadence mismatch')
        end=parse_timestamp(row['period_end']).astimezone(JST)
        start=end-timedelta(minutes=step)
        if start.date().isoformat() >= cutoff:
            raise ValueError('Forecast fit received data after the training cutoff')
        by_day[start.date().isoformat()].append((start+timedelta(minutes=step/2),float(row['ghi'])))
    cells=[]
    for cell in reference['curves']:
        days=cell['source_dates']
        if not days or any(len(by_day[day])!=1440//step for day in days):
            raise ValueError('Training class has no complete source days')
        matrices=[by_day[day] for day in days]
        clear=[fmean(astronomical_clear_ghi(row[i][0],latitude,longitude) for row in matrices) for i in range(1440//step)]
        actual=[fmean(row[i][1] for row in matrices) for i in range(1440//step)]
        daily_ratio=math.fsum(actual)/math.fsum(clear)
        ratios=[actual[i]/clear[i] if clear[i]>=20 else daily_ratio for i in range(len(clear))]
        if any(not math.isfinite(value) or value<0 for value in ratios):
            raise ValueError('Invalid fitted attenuation')
        cells.append({'season':cell['season'],'weather_class':cell['weather_class'],
                      'source_dates':days,'source_day_count':len(days),'attenuation_by_slot':ratios,
                      'mean_daily_attenuation':daily_ratio,'small_sample':cell['source_day_count']<10})
    return {'schema_version':'seasonal_climatology_proxy_v1','training_end_exclusive':cutoff,
            'training_source_dates':sorted({day for cell in cells for day in cell['source_dates']}),
            'latitude':latitude,'longitude':longitude,'slot_minutes':step,'cells':cells,
            'prediction':'class-frequency-weighted mean, without target-day weather labels',
            'solar_position_source':SOLAR_POSITION_SOURCE,'clear_sky_source':CLEAR_SKY_SOURCE,
            'limitations':['Climatology proxy, not a historical Solcast forecast.',
                           'Geometric solar envelope without atmospheric refraction; approximate near sunrise/sunset.',
                           'No within-day observation updates or claimed forecast skill.',
                           'Seasonal class spread is not calibrated forecast error.']}


def predict_climatology_ghi(model: Mapping, valid_starts: Sequence[datetime], *, issued_at: datetime,
                            known_weather_class: str | None = None) -> list[dict]:
    """Emit source-labeled forecasts; optional class conditioning is an oracle."""
    if issued_at.utcoffset() is None or any(stamp.utcoffset() is None for stamp in valid_starts):
        raise ValueError('Forecast issue and valid times require explicit timezones')
    cutoff=datetime.fromisoformat(model['training_end_exclusive']).replace(tzinfo=JST)
    if issued_at < cutoff or any(stamp < issued_at for stamp in valid_starts):
        raise ValueError('Forecast uses training data or valid times unavailable at issuance')
    step=int(model['slot_minutes'])
    rows=[]
    for start in valid_starts:
        local=start.astimezone(JST)
        if local.second or local.microsecond or (local.hour*60+local.minute)%step:
            raise ValueError('Forecast valid time is off the model slot grid')
        cells=[cell for cell in model['cells'] if cell['season']==season_for(local.date())
               and (known_weather_class is None or cell['weather_class']==known_weather_class)]
        if not cells:
            raise ValueError('Forecast has no matching training class')
        slot=(local.hour*60+local.minute)//step
        weight=sum(cell['source_day_count'] for cell in cells)
        attenuation=math.fsum(cell['attenuation_by_slot'][slot]*cell['source_day_count'] for cell in cells)/weight
        clear=astronomical_clear_ghi(local+timedelta(minutes=step/2),model['latitude'],model['longitude'])
        rows.append({'forecast_issued_at':issued_at.isoformat(),'valid_start':start.isoformat(),
                     'valid_end':(start+timedelta(minutes=step)).isoformat(),'lead_minutes':(start-issued_at).total_seconds()/60,
                     'ghi_w_m2':clear*attenuation,'source_kind':'known_class_oracle_reference' if known_weather_class else 'training_only_climatology_proxy',
                     'known_weather_class':known_weather_class,'training_day_count':weight,'clear_ghi_w_m2':clear})
    return rows
