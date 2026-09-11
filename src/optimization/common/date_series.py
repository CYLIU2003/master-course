"""Explicit dated timetable materialization and independent input contracts.

Template rows remain source records. Dated occurrences carry the original ID
and clocks, with absolute minutes measured from the first local midnight.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .service_calendar import _calendar_day_type, _trip_day_type_evidence


DATE_SERIES_INPUT_MODE = 'dated_timetable_and_pv_v1'
DATE_SERIES_SCHEMA = 'dated_timetable_contract_v1'
_TRIP_FIELDS = ('trip_id','template_trip_id','route_id','operator_id','service_id','service_date',
                'day_index','origin','destination','origin_stop_id','destination_stop_id',
                'departure','arrival','source_departure','source_arrival','distance_km',
                'distance_source','allowed_vehicle_types','source_provenance')


def content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def consecutive_service_dates(start: str | None, planning_days: int,
                              explicit_dates: Sequence[str] | None = None) -> list[str]:
    if isinstance(planning_days,bool) or int(planning_days) != planning_days or planning_days < 1:
        raise ValueError('planning_days must be a positive integer')
    dates = [date.fromisoformat(str(value)).isoformat() for value in (explicit_dates or ())]
    first = date.fromisoformat(str(start)) if start else date.fromisoformat(dates[0]) if dates else None
    if first is None:
        raise ValueError('Date-specific operation requires an explicit service start date')
    expected = [(first+timedelta(days=i)).isoformat() for i in range(planning_days)]
    if dates and dates != expected:
        raise ValueError('service_dates must be consecutive, ordered, unique, and match planning_days/start')
    return expected


def clock_minutes(value: Any) -> int:
    match = re.fullmatch(r'(\d+):(\d{2})',str(value))
    if not match or int(match[2]) >= 60:
        raise ValueError(f'Invalid explicit service clock: {value!r}')
    return int(match[1])*60+int(match[2])


def offset_clock(value: str, offset: int) -> str:
    minute = clock_minutes(value)+offset
    return f'{minute//60:02d}:{minute%60:02d}'


def timetable_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return content_hash([{key:row.get(key) for key in _TRIP_FIELDS} for row in rows])


def materialize_dated_timetable(template_rows: Sequence[Mapping[str, Any]], *,
                                service_dates: Sequence[str], holiday_dates: Sequence[str],
                                source_provenance: Mapping[str, Any]) -> tuple[list[dict],dict]:
    dates = consecutive_service_dates(None,len(service_dates),service_dates)
    templates = [deepcopy(dict(row)) for row in template_rows]
    ids = [str(row.get('trip_id') or '') for row in templates]
    if not templates or not all(ids) or len(ids)!=len(set(ids)):
        raise ValueError('Source timetable needs unique, nonempty trip IDs')
    grouped = {}
    for row in templates:
        types,unknown = _trip_day_type_evidence(row)
        if unknown or len(types)!=1:
            raise ValueError('Template calendar fields are missing, unknown, or conflicting')
        grouped.setdefault(next(iter(types)),[]).append(row)
    rows,days = [],[]
    for day_index,text in enumerate(dates):
        day_type = _calendar_day_type(date.fromisoformat(text),declared_holiday_dates=set(holiday_dates))
        selected = list(grouped.get(day_type,()))
        if day_type in ('saturday','sunday_or_holiday'):
            selected += grouped.get('weekend_or_holiday',[])
        if not selected:
            raise ValueError(f'No declared timetable for {text} ({day_type}); no weekday fallback')
        start_index = len(rows)
        for template in selected:
            departure,arrival = template['departure'],template['arrival']
            if not 0<=clock_minutes(departure)<1440 or clock_minutes(arrival)<clock_minutes(departure):
                raise ValueError('Source trip clocks require explicit midnight resolution')
            row = {**deepcopy(template),'template_trip_id':template['trip_id'],
                   'trip_id':f'{text}::{template["trip_id"]}','service_date':text,'day_index':day_index,
                   'source_departure':departure,'source_arrival':arrival,
                   'departure':offset_clock(departure,day_index*1440),
                   'arrival':offset_clock(arrival,day_index*1440)}
            rows.append(row)
        days.append({'service_date':text,'day_index':day_index,'day_type':day_type,'trip_count':len(selected),
                     'timetable_rows_sha256':timetable_hash(rows[start_index:]),
                     'template_trip_ids':[row['trip_id'] for row in selected]})
    contract = {'schema_version':DATE_SERIES_SCHEMA,'mode':DATE_SERIES_INPUT_MODE,'timezone':'Asia/Tokyo',
                'service_dates':dates,'planning_days':len(dates),'holiday_dates':sorted(set(holiday_dates)),
                'template_rows_sha256':content_hash(templates),'timetable_rows_sha256':timetable_hash(rows),
                'source_provenance':deepcopy(dict(source_provenance)),'days':days,
                'comparison_type':'fixed_timetable_with_date_specific_historical_pv',
                'historical_actual_operations_claim':False,'time_axis':'absolute_minutes_from_first_local_midnight'}
    validate_dated_timetable(rows,contract)
    return rows,contract


def validate_dated_timetable(rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> dict:
    if contract.get('schema_version') != DATE_SERIES_SCHEMA or contract.get('mode') != DATE_SERIES_INPUT_MODE:
        raise ValueError('Unsupported dated timetable contract')
    dates = consecutive_service_dates(None,contract['planning_days'],contract['service_dates'])
    if len(contract.get('days', ())) != len(dates):
        raise ValueError('Dated contract must describe every requested service date')
    if timetable_hash(rows) != contract.get('timetable_rows_sha256'):
        raise ValueError('Prepared dated timetable changed after materialization')
    ids = [row.get('trip_id') for row in rows]
    if not all(ids) or len(ids)!=len(set(ids)):
        raise ValueError('Dated trip IDs must be unique and nonempty')
    for day_index,day in enumerate(contract['days']):
        text = dates[day_index]
        expected_type = _calendar_day_type(date.fromisoformat(text),declared_holiday_dates=set(contract['holiday_dates']))
        selected = [row for row in rows if row.get('service_date') == text]
        if day['service_date']!=text or day['day_index']!=day_index or day['day_type']!=expected_type:
            raise ValueError('Date/calendar materialization mismatch')
        if len(selected)!=day['trip_count'] or timetable_hash(selected)!=day['timetable_rows_sha256']:
            raise ValueError('Dated trip count or daily source hash mismatch')
        if [row['template_trip_id'] for row in selected] != day['template_trip_ids']:
            raise ValueError('Dated service set differs from the declared source template')
        for row in selected:
            types,unknown = _trip_day_type_evidence(row)
            allowed_types = {expected_type,'weekend_or_holiday'} if expected_type!='weekday' else {expected_type}
            if unknown or len(types)!=1 or not types.issubset(allowed_types):
                raise ValueError('Dated timetable service calendar mismatch')
            if row.get('day_index')!=day_index or row['trip_id']!=f'{text}::{row["template_trip_id"]}':
                raise ValueError('Dated trip identity/offset mismatch')
            for clock_key in ('departure','arrival'):
                if row[clock_key]!=offset_clock(row['source_'+clock_key],day_index*1440):
                    raise ValueError('Dated trip clock differs from its source')
            if not str(row.get('operator_id') or '').strip() or str(row['operator_id']).upper()=='UNKNOWN':
                raise ValueError('Dated timetable requires a verified operator for every trip')
            distance = float(row.get('distance_km') or 0)
            if not math.isfinite(distance) or distance<=0 or not row.get('distance_source'):
                raise ValueError('Dated timetable requires positive distance with source provenance')
    if len(contract['days'])!=len(dates) or sum(day['trip_count'] for day in contract['days'])!=len(rows):
        raise ValueError('Dated timetable contains extra or missing service dates')
    return {'schema_version':'service_calendar_validation_v2','status':'OK','strict':True,
            'service_date':dates[0],'service_dates':dates,'days':list(contract['days']),
            'timetable_row_count':len(rows),'unknown_timetable_row_count':0,'errors':[],
            'calendar_validation_status':'matched','calendar_policy':'fixed_version_date_specific_calendar',
            'comparison_type':contract['comparison_type'],'weather_observation_date':dates[0],
            'service_date_forecast_claim':False,'historical_actual_operations_claim':False,
            'timetable_rows_sha256':contract['timetable_rows_sha256']}


def dated_capacity_factors(raw: Mapping[str, Any], service_dates: Sequence[str], timestep_min: int) -> tuple[float,...]:
    rows = raw.get('pv_capacity_factor_by_date') or []
    if [row.get('date') for row in rows] != list(service_dates):
        raise ValueError('PV dates must exactly match the consecutive service dates, in order')
    factors = []
    for row in rows:
        source_step = int(row.get('slot_minutes') or 0)
        values = row.get('capacity_factor_by_slot') or []
        if source_step<=0 or 1440%source_step or len(values)*source_step!=1440:
            raise ValueError('Every PV date must contain exactly one complete local day')
        if timestep_min%source_step and source_step%timestep_min:
            raise ValueError('PV cadence must divide the solver cadence or vice versa')
        if any(isinstance(value,bool) or not math.isfinite(float(value)) or not 0<=float(value)<=1 for value in values):
            raise ValueError('PV capacity factors must be finite values in [0,1]')
        if source_step <= timestep_min:
            factor=timestep_min//source_step
            factors.extend(math.fsum(float(v) for v in values[i:i+factor])/factor for i in range(0,len(values),factor))
        else:
            factor=source_step//timestep_min
            factors.extend(float(value) for value in values for _ in range(factor))
    return tuple(factors)
