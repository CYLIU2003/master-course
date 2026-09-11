"""Prepare a new scenario from verified dated timetable and irradiance inputs."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

from src.optimization.common.date_series import (
    DATE_SERIES_INPUT_MODE, consecutive_service_dates, content_hash,
    dated_capacity_factors, materialize_dated_timetable, offset_clock, validate_dated_timetable,
)
from src.optimization.common.solcast_pv_profiles import _build_daily_profile
from src.preprocess.weather.solcast_archive import JST, load_verified_archive, parse_timestamp
from src.preprocess.weather.seasonal_forecast_proxy import predict_climatology_ghi


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ID = 'tsurumaki_20260901_solcast_history_v1'
PARENT_SCENARIO_IDS = {'771d115b-75b0-49f7-a7f0-25f259a2cd21','b23fd26c-1233-4c73-bb9e-bdb8b1584760'}


def _read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_holiday_manifest(repo_root: Path, dates: list[str], source_id: str | None = None) -> dict:
    """Select verified coverage while preserving the original 2024+ input contract."""
    source = source_id or ('cabinet_office_20260910_2022_2026' if dates[0] < '2024-01-01'
                           else 'cabinet_office_20260910')
    if source not in {'cabinet_office_20260910', 'cabinet_office_20260910_2022_2026'}:
        raise ValueError('Unknown holiday source selection')
    directory = repo_root/'data/external/calendar'/source
    manifest = _read(directory/'manifest.json')
    if _digest(directory/'syukujitsu.csv') != manifest['sha256']:
        raise ValueError('Holiday source hash mismatch')
    if dates[0] < manifest['coverage_start'] or dates[-1] >= manifest['coverage_end_exclusive']:
        raise ValueError('Requested dates lie outside the verified holiday coverage')
    return manifest


def _verified_timetable(directory: Path) -> tuple[dict,dict]:
    manifest = _read(directory/'manifest.json')
    if manifest.get('status') != 'TIMETABLE_VERIFIED_DISTANCE_PROXY_DECLARED':
        raise ValueError('The fixed timetable has not passed the official source comparison')
    payload = {}
    for name in ('timetable_rows.json','stop_sequences.json','stops.json','selected_routes.json'):
        path = directory/name
        if _digest(path) != manifest['artifacts'][name]['sha256']:
            raise ValueError(f'Fixed timetable source changed: {name}')
        payload[name.removesuffix('.json')] = _read(path)
    return payload,manifest


def _date_pv_rows(raw_directory: Path, dates: list[str], timestep_min: int, performance_ratio: float) -> tuple[list[dict],list[dict]]:
    start,end = date.fromisoformat(dates[0]),date.fromisoformat(dates[-1])+timedelta(days=1)
    rows,sources = load_verified_archive(raw_directory,start,end)
    grouped = defaultdict(list)
    for row in rows:
        period_minutes = int(row['period'][2:-1])
        stamp = parse_timestamp(row['period_end']).astimezone(JST)
        day = (stamp-timedelta(minutes=period_minutes)).date().isoformat()
        grouped[day].append((stamp,float(row['ghi']),period_minutes))
    profiles = []
    for day in dates:
        profile = _build_daily_profile(grouped[day],target_date=day,slot_minutes=timestep_min,
                                      pv_capacity_kw=1,performance_ratio=performance_ratio,require_complete_day=True)
        profiles.append({'date':day,'slot_minutes':timestep_min,'capacity_factor_by_slot':profile['capacity_factor_by_slot'],
                         'irradiance_column':'ghi','performance_ratio':performance_ratio,
                         'conversion_model':'CF=min(1,GHI/1000*PR); horizontal-irradiance proxy',
                         'data_kind':'historical_estimated_actuals_not_forecasts'})
    return profiles,sources


def _date_forecast_rows(repo_root: Path, dates: list[str], timestep_min: int,
                        performance_ratio: float) -> tuple[list[dict], dict]:
    """Build predictions without accepting any evaluation-period weather."""
    directory = repo_root / 'data/derived/seasonal_irradiance/tsurumaki/forecast_holdouts'
    manifest = _read(directory / 'manifest.json')
    model_path = directory / 'training_model.json'
    if _digest(model_path) != manifest['artifacts']['training_model.json']:
        raise ValueError('Training-only forecast model hash mismatch')
    model = _read(model_path)
    model_step = int(model['slot_minutes'])
    starts = [datetime.fromisoformat(day).replace(tzinfo=JST) + timedelta(minutes=i * model_step)
              for day in dates for i in range(1440 // model_step)]
    predictions = predict_climatology_ghi(model, starts, issued_at=starts[0])
    profiles = []
    for day in dates:
        values = [(parse_timestamp(row['valid_end']).astimezone(JST), row['ghi_w_m2'], model_step)
                  for row in predictions if row['valid_start'][:10] == day]
        profile = _build_daily_profile(values, target_date=day, slot_minutes=timestep_min,
                                      pv_capacity_kw=1, performance_ratio=performance_ratio,
                                      require_complete_day=True)
        profiles.append({'date': day, 'slot_minutes': timestep_min,
                         'capacity_factor_by_slot': profile['capacity_factor_by_slot'],
                         'irradiance_column': 'ghi', 'performance_ratio': performance_ratio,
                         'data_kind': 'training_only_climatology_proxy',
                         'conversion_model': 'CF=min(1,GHI/1000*PR); horizontal-irradiance proxy'})
    return profiles, {'model_sha256': _digest(model_path),
                      'training_end_exclusive': model['training_end_exclusive'],
                      'issued_at': starts[0].isoformat(),
                      'update_policy': 'unchanged_climatology_reissued_hourly',
                      'future_weather_class_known': False}


def _persist_actual_profiles(repo_root: Path, profiles: list[dict], sources: list[dict],
                             dates: list[str], timestep_min: int) -> dict:
    """Keep actual profiles outside the canonical optimization inputs."""
    document = {'schema_version': 'historical_pv_capacity_factor_execution_v1',
                'depot_id': 'tsurumaki', 'service_dates': dates, 'timestep_minutes': timestep_min,
                'source_sha256': [source['sha256'] for source in sources],
                'profiles': profiles, 'data_kind': 'historical_estimated_actuals_not_forecasts'}
    relative = Path('data/derived/pv_execution_inputs/tsurumaki') / f'{content_hash(document)}.json'
    path = repo_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') != encoded:
        raise ValueError('An immutable actual-PV profile already exists with different bytes')
    if not path.exists():
        path.write_text(encoded, encoding='utf-8')
    return {'path': relative.as_posix(), 'sha256': _digest(path)}


def prepare_date_series_scenario(scenario: dict[str,Any], *, repo_root: Path = REPO_ROOT) -> dict[str,Any]:
    """Materialize only the explicitly selected version and all declared dates."""
    doc = deepcopy(scenario)
    cfg = doc['simulation_config']
    if cfg.get('multi_day_input_mode') != DATE_SERIES_INPUT_MODE:
        raise ValueError('Date-series preparation requires an explicit input mode')
    if (doc.get('meta') or {}).get('id') in PARENT_SCENARIO_IDS:
        raise ValueError('Preserve the SUNNY/RAIN parent: duplicate it before preparing dated operation')
    if cfg.get('date_series_source_id',SOURCE_ID) != SOURCE_ID:
        raise ValueError('Unknown date-series source selection')
    scope = doc['dispatch_scope']
    selected_depots = scope.get('depotSelection',{}).get('depotIds') or [scope.get('depotId')]
    if selected_depots != ['tsurumaki']:
        raise ValueError('This validated date-series source covers only Tsurumaki')
    if cfg.get('daily_return_depot_id') not in (None, '', 'tsurumaki'):
        raise ValueError('The daily-return depot must match this prepared fleet scope')
    if cfg.get('operation_time_window_enabled'):
        raise ValueError('Continuous dated operation requires the complete local midnight-to-midnight horizon')
    dates = consecutive_service_dates(cfg.get('service_date'),int(cfg['planning_days']),cfg.get('service_dates'))
    holiday_manifest = _verified_holiday_manifest(repo_root, dates, cfg.get('holiday_source_id'))
    directory = repo_root/'data/derived/timetables/tsurumaki_20260901'
    template,timetable_manifest = _verified_timetable(directory)
    selected_ids = scope.get('routeSelection',{}).get('includeRouteIds') or []
    known_ids = {row['id'] for row in template['selected_routes']}
    if not selected_ids or not set(selected_ids).issubset(known_ids):
        raise ValueError('Dated route selection must be within the verified 16-pattern source')
    templates = [row for row in template['timetable_rows'] if row['route_id'] in selected_ids]
    rows,contract = materialize_dated_timetable(templates,service_dates=dates,holiday_dates=list(holiday_manifest['holiday_dates']),
                                               source_provenance={'source_id':SOURCE_ID,'timetable_manifest_sha256':_digest(directory/'manifest.json'),
                                                                  'holiday_source_sha256':holiday_manifest['sha256'],
                                                                  'timetable_source_version':timetable_manifest['source_version'],
                                                                  'distance_semantics':timetable_manifest['distance_semantics']})
    doc['timetable_rows'] = rows
    doc['routes'] = [deepcopy(row) for row in template['selected_routes'] if row['id'] in selected_ids]
    for route in doc['routes']:
        distances = {row['distance_km'] for row in templates if row['route_id']==route['id']}
        if len(distances)!=1:
            raise ValueError('Route distance requires one verified stop sequence per pattern')
        route['distanceKm'] = distances.pop()
        route['distanceSource'] = 'trip_stop_sequence_polyline_haversine'
        route['operator_id'] = 'tokyu'
        route['tripCount'] = sum(row['route_id']==route['id'] for row in templates)
        route['tripCountsByDayType'] = {
            service: sum(row['route_id'] == route['id'] and row['service_id'] == service for row in templates)
            for service in sorted({row['service_id'] for row in templates})
        }
    selected_template_ids = {row['trip_id'] for row in templates}
    sequences = defaultdict(list)
    for row in template['stop_sequences']:
        if row['trip_id'] in selected_template_ids:
            sequences[row['trip_id']].append(row)
    doc['stop_timetables'] = []
    for trip in rows:
        for original in sequences[trip['template_trip_id']]:
            row = {**deepcopy(original),'trip_id':trip['trip_id'],'service_date':trip['service_date'],
                   'service_id':trip['service_id'],'route_id':trip['route_id']}
            for key in ('departure_time','arrival_time'):
                if row.get(key) is not None:
                    row[key]=offset_clock(row[key],trip['day_index']*1440)
            doc['stop_timetables'].append(row)
    used_stops = {row['stop_id'] for row in doc['stop_timetables']}
    doc['stops'] = [deepcopy(row) for row in template['stops'] if row['id'] in used_stops]
    assets = cfg.get('depot_energy_assets') or []
    if isinstance(assets,dict):
        assets = [dict(value,depot_id=key) for key,value in assets.items()]
    asset = next((deepcopy(row) for row in assets if row.get('depot_id')=='tsurumaki'),{'depot_id':'tsurumaki'})
    step = int(cfg.get('timestep_min') or cfg.get('time_step_min') or 30)
    profiles,sources = _date_pv_rows(repo_root/'data/external/solcast_raw/tsurumaki_2025_2026',dates,step,float(asset.get('performance_ratio') or .85))
    information_mode = cfg.get('pv_information_mode') or 'historical_perfect_information'
    forecast_audit = None
    execution_input = None
    if information_mode == 'training_only_forecast_proxy':
        execution_input = _persist_actual_profiles(repo_root, profiles, sources, dates, step)
        profiles, forecast_audit = _date_forecast_rows(repo_root, dates, step, float(asset.get('performance_ratio') or .85))
    elif information_mode != 'historical_perfect_information':
        raise ValueError('Unknown PV information mode')
    # Dated profiles are a new explicit source; old single-day convenience
    # fields are removed only from this newly derived materialization.
    for key in ('capacity_factor_by_slot','pv_generation_kwh_by_slot','pv_generation_kwh_by_date',
                'pv_case_id','pv_source_date'):
        asset.pop(key,None)
    asset.update(pv_capacity_factor_by_date=profiles,pv_profile_source='verified_dated_solcast_ghi',
                 pv_profile_dates=dates,pv_slot_minutes=step,pv_input_semantics='gross_generation_before_depot_load',
                 depot_load_model='explicit_zero_nontraction_load',
                 depot_load_kwh_by_slot=[0.0] * (1440 // step * len(dates)))
    if forecast_audit is not None:
        asset['pv_profile_source'] = 'training_only_climatology_proxy'
    asset['bess_balance_period'] = cfg.get('bess_balance_period') or 'daily'
    if asset['bess_balance_period'] not in ('daily','evaluation_period'):
        raise ValueError('Unsupported BESS balance period')
    # Preserve explicitly saved BESS policy; legacy dated scenarios retain the
    # previous return-to-initial default when no policy was declared.
    asset['bess_terminal_soc_policy'] = asset.get('bess_terminal_soc_policy') or 'return_to_initial'
    dated_capacity_factors(asset,dates,step)
    cfg['depot_energy_assets'] = [asset]
    doc.setdefault('scenario_overlay',{})['depot_energy_assets'] = {'tsurumaki':deepcopy(asset)}
    doc['scenario_overlay'].setdefault('cost_coefficients', {}).update(
        pv_profile_id=None, pv_input_semantics='gross_generation_before_depot_load',
        pv_resolution_minutes=step)
    doc['pv_profiles'] = []
    contract.update(pv_source_sha256=[source['sha256'] for source in sources],
                    daily_return_depot_id=cfg.get('daily_return_depot_id'),
                    rolling_window_terminal_policy=cfg.get('rolling_window_terminal_policy','return_to_evaluation_initial'),
                    rolling_bess_terminal_policy=cfg.get('rolling_bess_terminal_policy', 'scenario'),
                    selected_route_ids=list(selected_ids),
                    depot_load_model='explicit_zero_nontraction_load',
                    bess_balance_period=asset['bess_balance_period'],
                    rolling_lookahead_hours=cfg.get('rolling_lookahead_hours'),
                    pv_capacity_factor_rows_sha256=content_hash(profiles),
                    price_calendar_policy='repeat_the_declared_fixed_daily_tariff',
                    solar_semantics='date_specific_historical_estimated_actuals_not_historical_forecasts')
    contract.update(pv_information_mode=information_mode, forecast_audit=forecast_audit,
                    pv_execution_input=execution_input)
    if cfg.get('daily_return_depot_id'):
        contract['bev_terminal_soc_policy'] = cfg.get('bev_terminal_soc_policy')
        contract['final_soc_target_tolerance_percent'] = cfg.get('final_soc_target_tolerance_percent')
    if forecast_audit is not None:
        contract['solar_semantics'] = 'training_only_forecast_for_planning_separate_actuals_for_execution'
    cfg.update(service_dates=dates,service_date=dates[0],date_series_contract=contract,
               date_series_source_id=SOURCE_ID,holiday_dates=list(holiday_manifest['holiday_dates']),
               pv_input_semantics='gross_generation_before_depot_load',
               weather_observation_date=dates[0],weather_profile_source=SOURCE_ID,
               comparison_type='fixed_timetable_with_date_specific_historical_pv',
               comparison_role=None,counterfactual_pv_source_date=None,pv_profile_id=None,
               planning_horizon_hours=24*len(dates),start_time='00:00',end_time='23:59')
    cfg['pv_information_mode'] = information_mode
    services = sorted({row['service_id'] for row in rows})
    scope['serviceSelection']={'serviceIds':services,'serviceDates':dates}
    scope['serviceDates']=dates
    scope['serviceId']=rows[0]['service_id']
    cfg['day_type']=rows[0]['service_id']
    validate_dated_timetable(rows,contract)
    return doc
