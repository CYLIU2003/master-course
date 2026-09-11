"""Descriptive 4-season x 3-weather irradiance profiles from complete Solcast records.

This is an offline preprocessing prototype, not an integrated optimizer module.
Weather labels are explicit source-backed inputs; low irradiance never means rain.
Forecast-error distributions are NOT inferred or calibrated by this module.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean, pstdev
from solcast_year import JST, parse_timestamp, period_minutes, validate_records

SEASONS = ('spring', 'summer', 'autumn', 'winter')
WEATHER = ('sunny', 'cloudy', 'rainy')


def season_for(value: date) -> str:
    return ('winter' if value.month in (12, 1, 2) else
            'spring' if value.month in (3, 4, 5) else
            'summer' if value.month in (6, 7, 8) else 'autumn')


def quantile(values: list[float], probability: float) -> float:
    if not values or not 0 <= probability <= 1:
        raise ValueError('Invalid quantile inputs')
    ordered = sorted(values)
    position = (len(ordered)-1)*probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper]-ordered[lower])*(position-lower)


def build_curves(records: list[dict], labels: dict[str, str], *, start: date,
                 end_exclusive: date, minutes: int, fields: tuple[str, ...] = ('ghi',),
                 min_days: int = 10, diagnostic: bool = False) -> dict:
    if min_days < 1 or not fields or any(f not in ('ghi', 'gti') for f in fields):
        raise ValueError('Invalid curve contract')
    lower = datetime.combine(start, datetime.min.time(), JST)
    upper = datetime.combine(end_exclusive, datetime.min.time(), JST)
    ordered = validate_records(records, lower, upper, minutes, fields)
    dates = [(start+timedelta(days=i)).isoformat() for i in range((end_exclusive-start).days)]
    if set(labels) != set(dates):
        raise ValueError('Weather labels must cover exactly the requested dates, with no leakage/out-of-window labels.')
    if any(value not in WEATHER for value in labels.values()):
        raise ValueError('Unresolved weather labels: do not silently force snow/mixed/unknown into rain.')
    slots = 1440 // minutes
    days = {d: {field: [None]*slots for field in fields} for d in dates}
    for row in ordered:
        begin = (parse_timestamp(row['period_end'])-timedelta(minutes=minutes)).astimezone(JST)
        if begin.second or begin.microsecond or (begin.hour*60+begin.minute) % minutes:
            raise ValueError('Unaligned interval start')
        day, index = begin.date().isoformat(), (begin.hour*60+begin.minute)//minutes
        for field in fields:
            days[day][field][index] = float(row[field])
    cells, incomplete = [], []
    for season in SEASONS:
        for weather in WEATHER:
            source_dates = [d for d in dates if season_for(date.fromisoformat(d)) == season and labels[d] == weather]
            n = len(source_dates)
            cell = {'season': season, 'weather_class': weather, 'source_dates': source_dates,
                    'source_day_count': n, 'period_minutes': minutes, 'unit': 'W/m2',
                    'status': 'DESCRIPTIVE_ONLY' if n >= min_days else 'INSUFFICIENT_SAMPLE',
                    'irradiance': {}}
            if n < min_days:
                incomplete.append(f'{season}/{weather}: {n} < {min_days}')
            for field in fields:
                if not source_dates:
                    cell['irradiance'][field] = None
                    continue
                matrix = [days[d][field] for d in source_dates]
                means = [fmean(column) for column in zip(*matrix)]
                median = [quantile(list(column), .5) for column in zip(*matrix)]
                representative = min(source_dates, key=lambda d: (sum(abs(a-b) for a, b in zip(days[d][field], means)), d))
                energies = [sum(row)*minutes/60/1000 for row in matrix]
                cell['irradiance'][field] = {
                    'mean': means, 'p10': [quantile(list(c), .1) for c in zip(*matrix)],
                    'p50': median, 'p90': [quantile(list(c), .9) for c in zip(*matrix)],
                    'population_std': [pstdev(c) for c in zip(*matrix)],
                    'representative_real_day': representative,
                    'representative_real_day_curve': days[representative][field],
                    'mean_daily_irradiation_kwh_m2': fmean(energies),
                    'daily_irradiation_p10_kwh_m2': quantile(energies, .1),
                    'daily_irradiation_p90_kwh_m2': quantile(energies, .9),
                }
            cells.append(cell)
    if incomplete and not diagnostic:
        raise ValueError('Insufficient groups; no fake standard curves generated: '+'; '.join(incomplete))
    return {'schema_version': 'seasonal_weather_irradiance_descriptive_v1',
            'status': 'DIAGNOSTIC_INCOMPLETE' if incomplete else 'DESCRIPTIVE_COMPLETE_NOT_FORECAST_VALIDATED',
            'timezone': 'Asia/Tokyo', 'start': start.isoformat(), 'end_exclusive': end_exclusive.isoformat(),
            'record_count': len(ordered), 'source_day_count': len(dates), 'minimum_days_policy': min_days,
            'season_definition': {'spring': [3,4,5], 'summer': [6,7,8], 'autumn': [9,10,11], 'winter': [12,1,2]},
            'percentile_semantics': 'empirical_pointwise_percentiles_not_exceedance_P90_or_forecast_intervals',
            'curves': cells, 'insufficient_groups': incomplete,
            'limitations': ['single-year descriptive reference, not long-term climate normal',
                            'no forecast archive: no empirical forecast-error calibration',
                            'no PV power conversion or optimizer integration in this prototype']}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw-dir', type=Path, required=True)
    p.add_argument('--weather-labels', type=Path, required=True)
    p.add_argument('--start', type=date.fromisoformat, required=True)
    p.add_argument('--end-exclusive', type=date.fromisoformat, required=True)
    p.add_argument('--minutes', type=int, default=15)
    p.add_argument('--field', choices=('ghi', 'gti', 'both'), default='ghi')
    p.add_argument('--min-days', type=int, default=10)
    p.add_argument('--diagnostic', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    rows, sources, coordinate_geometry = [], [], set()
    for manifest_path in sorted(args.raw_dir.glob('*.manifest.json')):
        meta = json.loads(manifest_path.read_text(encoding='utf-8'))
        request = meta['request']
        request_sha = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        if request_sha != meta.get('request_sha256'):
            raise ValueError('Request provenance mismatch')
        raw_path = manifest_path.with_name(manifest_path.name.replace('.manifest.json', '.json'))
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta.get('raw_sha256'):
            raise ValueError('Raw source hash mismatch')
        q = request['query']
        coordinate_geometry.add(tuple(q.get(k) for k in ('latitude', 'longitude', 'tilt', 'azimuth', 'array_type')))
        payload_rows = json.loads(raw)['estimated_actuals']
        validate_records(payload_rows, parse_timestamp(request['start_jst']),
                         parse_timestamp(request['end_exclusive_jst']), request['period_minutes'],
                         tuple(q['output_parameters'].split(',')))
        for row in payload_rows:
            owner = (parse_timestamp(row['period_end'])-timedelta(minutes=period_minutes(row['period']))).astimezone(JST).date()
            if args.start <= owner < args.end_exclusive:
                rows.append(row)
        sources.append({'name': raw_path.name, 'sha256': meta['raw_sha256'], 'request_sha256': request_sha})
    if not rows or len(coordinate_geometry) != 1:
        raise ValueError('Missing data or multiple site/geometry configurations; stop before mixing.')
    labels, label_sources = {}, []
    with args.weather_labels.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            day = date.fromisoformat(row['date']).isoformat()
            if day in labels:
                raise ValueError(f'Duplicate weather date: {day}')
            if not row.get('source') or not row.get('classification_version') or row.get('quality_flag') != 'accepted':
                raise ValueError(f'Unreviewed weather label: {day}')
            labels[day] = row['weather_class']
            label_sources.append(row)
    fields = ('ghi', 'gti') if args.field == 'both' else (args.field,)
    result = build_curves(rows, labels, start=args.start, end_exclusive=args.end_exclusive,
                          minutes=args.minutes, fields=fields, min_days=args.min_days, diagnostic=args.diagnostic)
    result['sources'] = sources
    result['weather_label_sha256'] = hashlib.sha256(args.weather_labels.read_bytes()).hexdigest()
    result['weather_label_sources'] = label_sources
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(result['status'], args.output)

if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)
