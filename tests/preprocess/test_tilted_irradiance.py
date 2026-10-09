"""Plane-of-array irradiance via pvlib: explicit geometry, no silent fallbacks."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

pvlib = pytest.importorskip('pvlib')

from bff.services.date_series_inputs import _date_pv_rows
from src.preprocess.weather.seasonal_irradiance import build_seasonal_curves
from src.preprocess.weather.solcast_archive import JST
from src.preprocess.weather.tilted_irradiance import (
    SurfacePlane, plane_from_config, poa_for_solcast_rows, poa_from_ghi,
)

LAT, LON = 35.63514694444444, 139.6462427777778
ARCHIVE = Path(__file__).resolve().parents[2] / 'data/external/solcast_raw/tsurumaki_2025_2026'


def clear_day_rows(day: date) -> list[dict]:
    """Physically consistent GHI = DNI*cos(z) + DHI built from pvlib's clear-sky model."""
    import pandas as pd
    start = datetime.combine(day, datetime.min.time(), JST)
    ends = [start + timedelta(minutes=15 * (i + 1)) for i in range(96)]
    mids = pd.DatetimeIndex([e - timedelta(minutes=7.5) for e in ends]).tz_convert('UTC')
    location = pvlib.location.Location(LAT, LON)
    sky = location.get_clearsky(mids, model='ineichen')
    zenith = pvlib.solarposition.get_solarposition(mids, LAT, LON)['apparent_zenith']
    rows = []
    for end, (_, row), z in zip(ends, sky.iterrows(), zenith):
        dni, dhi = float(row['dni']), float(row['dhi'])
        cos_z = max(pvlib.tools.cosd(z), 0.0)
        ghi = dni * cos_z + dhi if cos_z > 0 else 0.0
        rows.append({'period_end': end.isoformat(), 'period': 'PT15M', 'ghi': ghi,
                     'dni': dni if cos_z > 0 else 0.0, 'dhi': dhi if cos_z > 0 else 0.0,
                     'clearsky_ghi': ghi, 'precipitation_rate': 0.0, 'air_temp': 10.0})
    return rows


def test_horizontal_plane_reproduces_ghi():
    rows = clear_day_rows(date(2025, 1, 15))
    poa = poa_for_solcast_rows(rows, latitude=LAT, longitude=LON, plane=SurfacePlane(0.0))
    assert sum(poa) == pytest.approx(sum(r['ghi'] for r in rows), rel=1e-3)


def test_south_tilt_raises_winter_and_lowers_summer_irradiation():
    plane = SurfacePlane(30.0)
    winter = clear_day_rows(date(2025, 1, 15))
    summer = clear_day_rows(date(2025, 6, 21))
    w = sum(poa_for_solcast_rows(winter, latitude=LAT, longitude=LON, plane=plane)) / sum(r['ghi'] for r in winter)
    s = sum(poa_for_solcast_rows(summer, latitude=LAT, longitude=LON, plane=plane)) / sum(r['ghi'] for r in summer)
    assert w > 1.4
    assert 0.85 < s < 1.0


def test_night_is_zero_and_values_are_nonnegative():
    rows = clear_day_rows(date(2025, 3, 3))
    poa = poa_for_solcast_rows(rows, latitude=LAT, longitude=LON, plane=SurfacePlane(30.0))
    assert all(value == 0.0 for value, row in zip(poa, rows) if row['ghi'] == 0.0)
    assert min(poa) >= 0.0


def test_ghi_only_path_uses_erbs_and_matches_components_closely():
    from src.preprocess.weather.solcast_archive import parse_timestamp
    rows = clear_day_rows(date(2025, 1, 15))
    plane = SurfacePlane(30.0)
    exact = sum(poa_for_solcast_rows(rows, latitude=LAT, longitude=LON, plane=plane))
    decomposed = sum(poa_from_ghi([parse_timestamp(r['period_end']) for r in rows], [15] * len(rows),
                                  [r['ghi'] for r in rows], latitude=LAT, longitude=LON, plane=plane))
    assert decomposed == pytest.approx(exact, rel=0.1)


def test_missing_components_are_rejected_not_treated_as_horizontal():
    rows = clear_day_rows(date(2025, 1, 15))
    del rows[40]['dni']
    with pytest.raises(ValueError, match='dni'):
        poa_for_solcast_rows(rows, latitude=LAT, longitude=LON, plane=SurfacePlane(30.0))


def test_plane_configuration_is_explicit():
    assert plane_from_config({}) is None
    with pytest.raises(ValueError):
        plane_from_config({'pv_surface_azimuth_deg': 180})
    plane = plane_from_config({'pv_surface_tilt_deg': 30})
    assert (plane.tilt_deg, plane.azimuth_deg, plane.albedo, plane.sky_model) == (30.0, 180.0, 0.2, 'haydavies')
    for bad in ({'pv_surface_tilt_deg': 95}, {'pv_surface_tilt_deg': 30, 'pv_albedo': 2},
                {'pv_surface_tilt_deg': 30, 'pv_sky_model': 'perez'}):
        with pytest.raises(ValueError):
            plane_from_config(bad)


def test_standard_curves_add_tilted_field_without_changing_ghi_classification():
    rows = clear_day_rows(date(2025, 1, 15))
    poa = poa_for_solcast_rows(rows, latitude=LAT, longitude=LON, plane=SurfacePlane(30.0))
    tilted = [dict(row, poa_global=value) for row, value in zip(rows, poa)]
    plain = build_seasonal_curves(rows, start=date(2025, 1, 15), end_exclusive=date(2025, 1, 16))
    extra = build_seasonal_curves(tilted, start=date(2025, 1, 15), end_exclusive=date(2025, 1, 16),
                                  extra_irradiance_fields=('poa_global',))
    assert extra['daily_labels'] == plain['daily_labels']
    cell = next(c for c in extra['curves'] if c['source_day_count'])
    assert cell['ghi'] == next(c for c in plain['curves'] if c['source_day_count'])['ghi']
    assert cell['poa_global']['mean'] == pytest.approx(poa)
    assert 'extra_irradiance_fields' not in plain


@pytest.mark.skipif(not any(ARCHIVE.glob('tsurumaki_2025-01-01_*.manifest.json')), reason='archive not present')
def test_dated_pv_inputs_switch_to_tilted_plane_only_when_declared():
    # A winter week: overcast days gain little, clear days gain a lot.
    dates = [f'2025-01-{day:02d}' for day in range(6, 13)]
    flat, _ = _date_pv_rows(ARCHIVE, dates, 15, 0.85)
    tilted, _ = _date_pv_rows(ARCHIVE, dates, 15, 0.85, SurfacePlane(30.0))
    assert {p['irradiance_column'] for p in flat} == {'ghi'}
    assert {p['irradiance_column'] for p in tilted} == {'poa_tilt30_az180'}
    assert {p['irradiance_decomposition'] for p in tilted} == {'solcast_dni_dhi'}
    total = lambda profiles: sum(sum(p['capacity_factor_by_slot']) for p in profiles)
    assert total(tilted) > 1.3 * total(flat)
