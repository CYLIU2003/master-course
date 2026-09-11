"""Solcast historical acquisition and strict interval/provenance validation.

Official schema checked 2026-09-10:
https://docs.solcast.com.au/docs/section/irradiance-weather-data
Uses historical estimated actuals, NOT historical forecasts or ground measurements.
The 2026-09-10 acquisition verified 15 months of Tsurumaki PT15M estimated actuals.
"""
from __future__ import annotations
import argparse
import calendar
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

JST = timezone(timedelta(hours=9))
UTC = timezone.utc
ENDPOINT = 'https://api.solcast.com.au/data/historic/radiation_and_weather'
PERIODS = (5, 10, 15, 20, 30, 60)


def parse_timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Naive timestamp: timezone must be explicit.')
    return result.astimezone(UTC)


def period_minutes(value: str) -> int:
    match = re.fullmatch(r'PT(\d+)([MH])', str(value))
    if not match:
        raise ValueError(f'Unsupported/missing interval duration: {value!r}')
    minutes = int(match[1]) * (60 if match[2] == 'H' else 1)
    if minutes not in PERIODS:
        raise ValueError(f'Unsupported interval duration: {minutes}')
    return minutes


def monthly_windows(start: date, end_exclusive: date):
    if start >= end_exclusive:
        raise ValueError('start must precede end-exclusive')
    current = start
    while current < end_exclusive:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = min(next_month, end_exclusive)
        yield current, end
        current = end


def request_plan(site: dict, start: date, end_exclusive: date, minutes: int = 15) -> list[dict]:
    if minutes not in PERIODS:
        raise ValueError('Unsupported cadence')
    lat, lon = float(site['latitude']), float(site['longitude'])
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid site coordinates')
    parameters = ['ghi', 'dni', 'dhi', 'air_temp', 'clearsky_ghi', 'cloud_opacity', 'precipitation_rate']
    geometry = {}
    if site.get('tilt') is not None or site.get('azimuth') is not None:
        if site.get('tilt') is None or site.get('azimuth') is None:
            raise ValueError('GTI requires both explicit tilt and azimuth.')
        tilt, azimuth = float(site['tilt']), float(site['azimuth'])
        if not math.isfinite(tilt) or not math.isfinite(azimuth) or not (0 <= tilt <= 90 and -180 <= azimuth <= 180):
            raise ValueError('Invalid Solcast geometry')
        geometry = {'tilt': tilt, 'azimuth': azimuth, 'array_type': 'fixed'}
        parameters += ['gti', 'clearsky_gti']
    plan = []
    for lower, upper in monthly_windows(start, end_exclusive):
        start_dt = datetime.combine(lower, datetime.min.time(), JST)
        end_dt = datetime.combine(upper, datetime.min.time(), JST)
        query = {'latitude': lat, 'longitude': lon,
                 'start': start_dt.isoformat(), 'duration': f'P{(upper-lower).days}D',
                 'period': f'PT{minutes}M', 'time_zone': 'utc', 'format': 'json',
                 'output_parameters': ','.join(parameters), **geometry}
        plan.append({'depot_id': site['depot_id'], 'start_jst': start_dt.isoformat(),
                     'end_exclusive_jst': end_dt.isoformat(), 'period_minutes': minutes,
                     'expected_records': (upper-lower).days * 1440 // minutes,
                     'endpoint': ENDPOINT, 'query': query})
    return plan


def validate_records(records: list[dict], start: datetime, end: datetime, minutes: int,
                     required_fields: tuple[str, ...] = ('ghi',)) -> list[dict]:
    """No filling, interpolation, clipping, deduplication, or missing-as-zero."""
    if minutes not in PERIODS or start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError('Invalid interval contract')
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    duration_seconds = (end-start).total_seconds()
    if duration_seconds % (minutes*60):
        raise ValueError('Window is not aligned to cadence')
    expected = {start + timedelta(minutes=minutes*i)
                for i in range(1, int(duration_seconds/(minutes*60))+1)}
    seen = {}
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f'Non-object row {index}')
        if period_minutes(row.get('period', '')) != minutes:
            raise ValueError(f'Cadence mismatch at row {index}')
        stamp = parse_timestamp(row['period_end'])
        if stamp in seen:
            raise ValueError(f'Duplicate period_end at row {index}')
        for name in required_fields:
            value = row.get(name)
            if isinstance(value, bool) or value is None:
                raise ValueError(f'Missing/non-numeric {name} at row {index}')
            try:
                number = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'Invalid {name} at row {index}') from exc
            if not math.isfinite(number):
                raise ValueError(f'Non-finite {name} at row {index}')
            if name in ('ghi', 'gti', 'dni', 'dhi', 'clearsky_ghi', 'clearsky_gti', 'precipitation_rate') and number < 0:
                raise ValueError(f'Negative {name} at row {index}')
        seen[stamp] = row
    actual = set(seen)
    if actual != expected:
        raise ValueError(f'Coverage failed: missing={len(expected-actual)}, unexpected={len(actual-expected)}')
    return [seen[key] for key in sorted(seen)]


def load_verified_archive(raw_dir: Path, start: date, end_exclusive: date) -> tuple[list[dict], list[dict]]:
    """Read only intersecting, hashed monthly sources; reject overlaps or gaps."""
    lower = datetime.combine(start, datetime.min.time(), JST)
    upper = datetime.combine(end_exclusive, datetime.min.time(), JST)
    records, sources, sites, cadences = [], [], set(), set()
    for sidecar in sorted(raw_dir.glob('*.manifest.json')):
        metadata = json.loads(sidecar.read_text(encoding='utf-8'))
        item = metadata['request']
        begin, end = parse_timestamp(item['start_jst']), parse_timestamp(item['end_exclusive_jst'])
        if begin >= upper or end <= lower:
            continue
        request_hash = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if request_hash != metadata.get('request_sha256') or item.get('endpoint') != ENDPOINT:
            raise ValueError(f'Invalid request provenance: {sidecar.name}')
        raw_path = sidecar.with_name(sidecar.name.replace('.manifest.json', '.json'))
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata.get('raw_sha256'):
            raise ValueError(f'Raw source hash mismatch: {raw_path.name}')
        query = item['query']
        cadence = item['period_minutes']
        payload = json.loads(raw)['estimated_actuals']
        ordered = validate_records(payload, begin, end, cadence, tuple(query['output_parameters'].split(',')))
        if len(ordered) != metadata.get('record_count'):
            raise ValueError(f'Manifest record count mismatch: {sidecar.name}')
        records.extend(row for row in ordered if lower < parse_timestamp(row['period_end']) <= upper)
        sites.add(tuple(query.get(key) for key in ('latitude', 'longitude', 'tilt', 'azimuth', 'array_type')))
        cadences.add(cadence)
        sources.append({'path': raw_path.as_posix(), 'sha256': metadata['raw_sha256'],
                        'request_sha256': request_hash, 'request': item,
                        'retrieved_at_utc': metadata['retrieved_at_utc']})
    if len(sites) != 1 or len(cadences) != 1:
        raise ValueError('Archive must contain exactly one site/geometry and one cadence')
    ordered = validate_records(records, lower, upper, cadences.pop(), ('ghi',))
    return ordered, sources


def resample_records(records: list[dict], start: date, end_exclusive: date, minutes: int) -> list[dict]:
    """Average interval intensities; keep energy and precipitation integrals."""
    if not records:
        raise ValueError('Cannot resample empty records')
    native = period_minutes(records[0]['period'])
    if minutes not in PERIODS or minutes < native or minutes % native:
        raise ValueError('Resampling requires an integer coarsening of the native cadence')
    lower = datetime.combine(start, datetime.min.time(), JST)
    upper = datetime.combine(end_exclusive, datetime.min.time(), JST)
    fields = tuple(key for key in records[0] if key not in ('period', 'period_end'))
    ordered = validate_records(records, lower, upper, native, fields)
    factor = minutes // native
    result = []
    for index in range(0, len(ordered), factor):
        group = ordered[index:index+factor]
        result.append({**{key: math.fsum(float(row[key]) for row in group)/factor for key in fields},
                       'period_end': parse_timestamp(group[-1]['period_end']).astimezone(JST).isoformat(),
                       'period': f'PT{minutes}M'})
    return validate_records(result, lower, upper, minutes, fields)


def download(plan: list[dict], out_dir: Path, api_key: str) -> None:
    if not api_key:
        raise ValueError('SOLCAST_API_KEY is not set; do not paste keys into source code.')
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in plan:
        request_hash = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        stem = f"{item['depot_id']}_{item['start_jst'][:10]}_{request_hash[:12]}"
        destination, sidecar = out_dir / (stem+'.json'), out_dir / (stem+'.manifest.json')
        if destination.exists():
            if not sidecar.exists():
                raise ValueError(f'Missing cached provenance: {destination.name}')
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            raw = destination.read_bytes()
            if metadata.get('request_sha256') != request_hash or metadata.get('raw_sha256') != hashlib.sha256(raw).hexdigest():
                raise ValueError(f'Cached provenance mismatch: {destination.name}')
        else:
            request = Request(ENDPOINT+'?'+urlencode(item['query']),
                              headers={'Authorization': 'Bearer '+api_key, 'Accept': 'application/json'})
            try:
                with urlopen(request, timeout=60) as response:
                    raw = response.read()
            except HTTPError as exc:
                # Never log header/key or retry a quota-consuming request automatically.
                raise RuntimeError(f'Solcast HTTP {exc.code}; stopped without retry. Check entitlement/quota.') from None
            except URLError:
                raise RuntimeError('Solcast connection failed; stopped without retry.') from None
        payload = json.loads(raw)
        rows = payload.get('estimated_actuals')
        if not isinstance(rows, list):
            raise ValueError('Unexpected API response: estimated_actuals must be an array')
        required = tuple(item['query']['output_parameters'].split(','))
        try:
            validate_records(rows, parse_timestamp(item['start_jst']),
                             parse_timestamp(item['end_exclusive_jst']), item['period_minutes'], required)
        except ValueError:
            invalid = out_dir / (stem+'.invalid.json')
            if not invalid.exists():
                invalid.write_bytes(raw)
            raise
        if not destination.exists():
            with destination.open('xb') as handle:
                handle.write(raw)
            metadata = {'status': 'RAW_COVERAGE_VALIDATED', 'request': item,
                        'request_sha256': request_hash, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                        'record_count': len(rows), 'retrieved_at_utc': datetime.now(UTC).isoformat(),
                        'data_kind': 'satellite_model_estimated_actuals_not_forecasts'}
            with sidecar.open('x', encoding='utf-8') as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
        print(f"Validated {destination.name}: {len(rows)} records")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument('--end-exclusive', type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument('--minutes', type=int, choices=PERIODS, default=15)
    parser.add_argument('--out', type=Path, default=Path('solcast_acquisition'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--acknowledge-quota', action='store_true')
    args = parser.parse_args()
    site = json.loads(args.site.read_text(encoding='utf-8'))
    plan = request_plan(site, args.start, args.end_exclusive, args.minutes)
    args.out.mkdir(parents=True, exist_ok=True)
    plan_path = args.out / ('request_plan_'+args.start.isoformat()+'_'+args.end_exclusive.isoformat()+'.json')
    plan_path.write_text(json.dumps({'mode': 'EXECUTE' if args.execute else 'DRY_RUN',
                                    'requests': plan, 'request_count': len(plan),
                                    'expected_records': sum(x['expected_records'] for x in plan)},
                                   ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Plan: {len(plan)} requests, {sum(x["expected_records"] for x in plan)} records; {plan_path}')
    if not args.execute:
        print('DRY RUN. No API request made and no quota consumed.')
        return
    if not args.acknowledge_quota:
        raise SystemExit('Execution requires --acknowledge-quota after checking account entitlement and possible charges.')
    if args.end_exclusive > datetime.now(JST).date()-timedelta(days=7):
        raise SystemExit('Requested history is too recent for the historical endpoint.')
    download(plan, args.out, os.environ.get('SOLCAST_API_KEY', ''))

if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)
