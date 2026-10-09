"""Plane-of-array (tilted) irradiance from stored Solcast intervals via pvlib.

The previous PV inputs used horizontal GHI directly (CF = GHI/1000*PR).  This
module converts the same stored intervals to the irradiance on a fixed tilted
module plane so that the PV capacity factor reflects the installation angle.

Method (all from pvlib, https://pvlib-python.readthedocs.io/en/stable/):
- Sun position at each interval midpoint: ``pvlib.solarposition.get_solarposition``
  (Solcast values are averages over the interval that ends at ``period_end``).
- Transposition: ``pvlib.irradiance.get_total_irradiance`` with the Hay-Davies
  sky-diffuse model and isotropic ground reflection (albedo).
- When only GHI is available (the training-only climatology forecast),
  DNI/DHI are first estimated with ``pvlib.irradiance.erbs``.  Measured
  Solcast DNI/DHI are used whenever they exist; the two paths are labelled.

Fixed-tilt geometry is an explicit input.  No orientation is inferred.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from typing import Sequence

PVLIB_DOCS = 'https://pvlib-python.readthedocs.io/en/stable/'
TRANSPOSITION_SOURCE = ('https://pvlib-python.readthedocs.io/en/stable/reference/generated/'
                        'pvlib.irradiance.get_total_irradiance.html')
DECOMPOSITION_SOURCE = ('https://pvlib-python.readthedocs.io/en/stable/reference/generated/'
                        'pvlib.irradiance.erbs.html')
SUPPORTED_SKY_MODELS = ('isotropic', 'haydavies')


@dataclass(frozen=True)
class SurfacePlane:
    """Fixed module plane. Azimuth follows pvlib: 180 = south, 90 = east."""

    tilt_deg: float
    azimuth_deg: float = 180.0
    albedo: float = 0.2
    sky_model: str = 'haydavies'

    def __post_init__(self) -> None:
        for name, value in (('tilt_deg', self.tilt_deg), ('azimuth_deg', self.azimuth_deg),
                            ('albedo', self.albedo)):
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f'{name} must be finite')
        if not 0.0 <= float(self.tilt_deg) <= 90.0:
            raise ValueError('tilt_deg must be within [0, 90]')
        if not 0.0 <= float(self.azimuth_deg) < 360.0:
            raise ValueError('azimuth_deg must be within [0, 360)')
        if not 0.0 <= float(self.albedo) <= 1.0:
            raise ValueError('albedo must be within [0, 1]')
        if self.sky_model not in SUPPORTED_SKY_MODELS:
            raise ValueError(f'sky_model must be one of {SUPPORTED_SKY_MODELS}')

    def label(self) -> str:
        return f'poa_tilt{self.tilt_deg:g}_az{self.azimuth_deg:g}'

    def describe(self) -> dict:
        return {**asdict(self), 'irradiance_column': self.label(),
                'solar_position': 'pvlib.solarposition.get_solarposition at interval midpoint',
                'transposition': f'pvlib.irradiance.get_total_irradiance(model={self.sky_model!r})',
                'source': TRANSPOSITION_SOURCE}


def plane_from_config(asset: dict) -> SurfacePlane | None:
    """Read an explicit plane from a PV asset; ``None`` keeps the horizontal proxy."""
    tilt = asset.get('pv_surface_tilt_deg')
    if tilt is None:
        if any(asset.get(key) is not None for key in ('pv_surface_azimuth_deg', 'pv_albedo', 'pv_sky_model')):
            raise ValueError('PV plane settings require an explicit pv_surface_tilt_deg')
        return None
    return SurfacePlane(tilt_deg=float(tilt),
                        azimuth_deg=float(asset.get('pv_surface_azimuth_deg', 180.0)),
                        albedo=float(asset.get('pv_albedo', 0.2)),
                        sky_model=str(asset.get('pv_sky_model', 'haydavies')))


def _transpose(times_mid_utc, ghi, dni, dhi, latitude: float, longitude: float, plane: SurfacePlane):
    import numpy as np
    import pandas as pd
    import pvlib

    index = pd.DatetimeIndex(times_mid_utc)
    position = pvlib.solarposition.get_solarposition(index, latitude, longitude)
    irradiance = pvlib.irradiance.get_total_irradiance(
        surface_tilt=float(plane.tilt_deg), surface_azimuth=float(plane.azimuth_deg),
        solar_zenith=position['apparent_zenith'], solar_azimuth=position['azimuth'],
        dni=pd.Series(dni, index=index), ghi=pd.Series(ghi, index=index), dhi=pd.Series(dhi, index=index),
        dni_extra=pvlib.irradiance.get_extra_radiation(index),
        albedo=float(plane.albedo), model=plane.sky_model)
    poa = np.nan_to_num(irradiance['poa_global'].to_numpy(dtype=float), nan=0.0)
    # No irradiance when the horizontal input is zero (night or no light).
    poa = np.where(np.asarray(ghi, dtype=float) <= 0.0, 0.0, np.clip(poa, 0.0, None))
    return [float(value) for value in poa]


def _midpoints(period_ends: Sequence[datetime], period_minutes: Sequence[int]):
    stamps = []
    for end, minutes in zip(period_ends, period_minutes):
        if end.utcoffset() is None:
            raise ValueError('Tilted irradiance requires timezone-aware timestamps')
        stamps.append(end - timedelta(minutes=minutes / 2))
    import pandas as pd
    return pd.DatetimeIndex(stamps).tz_convert('UTC')


def poa_from_components(period_ends: Sequence[datetime], period_minutes: Sequence[int],
                        ghi: Sequence[float], dni: Sequence[float], dhi: Sequence[float], *,
                        latitude: float, longitude: float, plane: SurfacePlane) -> list[float]:
    """POA global [W/m2] from measured/estimated GHI, DNI and DHI interval means."""
    if not (len(period_ends) == len(period_minutes) == len(ghi) == len(dni) == len(dhi)):
        raise ValueError('Irradiance component lengths differ')
    for name, values in (('ghi', ghi), ('dni', dni), ('dhi', dhi)):
        if any(not math.isfinite(float(v)) or float(v) < 0.0 for v in values):
            raise ValueError(f'{name} must be finite and non-negative')
    return _transpose(_midpoints(period_ends, period_minutes), ghi, dni, dhi, latitude, longitude, plane)


def poa_from_ghi(period_ends: Sequence[datetime], period_minutes: Sequence[int], ghi: Sequence[float], *,
                 latitude: float, longitude: float, plane: SurfacePlane) -> list[float]:
    """POA global [W/m2] when only GHI exists: Erbs decomposition, then transposition."""
    import pvlib

    if len(period_ends) != len(period_minutes) or len(period_ends) != len(ghi):
        raise ValueError('Irradiance component lengths differ')
    if any(not math.isfinite(float(v)) or float(v) < 0.0 for v in ghi):
        raise ValueError('ghi must be finite and non-negative')
    times = _midpoints(period_ends, period_minutes)
    position = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    import pandas as pd
    split = pvlib.irradiance.erbs(pd.Series(ghi, index=times), position['zenith'], times)
    dni = split['dni'].fillna(0.0).clip(lower=0.0).to_numpy()
    dhi = split['dhi'].fillna(0.0).clip(lower=0.0).to_numpy()
    return _transpose(times, ghi, dni, dhi, latitude, longitude, plane)


def poa_for_solcast_rows(rows: Sequence[dict], *, latitude: float, longitude: float,
                         plane: SurfacePlane) -> list[float]:
    """POA for stored Solcast rows, using their DNI/DHI (no decomposition)."""
    from .solcast_archive import parse_timestamp, period_minutes

    missing = [name for name in ('ghi', 'dni', 'dhi') if any(row.get(name) is None for row in rows)]
    if missing:
        raise ValueError(f'Tilted irradiance needs Solcast {missing}; GHI-only rows are not transposed silently')
    return poa_from_components([parse_timestamp(row['period_end']) for row in rows],
                               [period_minutes(row['period']) for row in rows],
                               [float(row['ghi']) for row in rows], [float(row['dni']) for row in rows],
                               [float(row['dhi']) for row in rows],
                               latitude=latitude, longitude=longitude, plane=plane)
