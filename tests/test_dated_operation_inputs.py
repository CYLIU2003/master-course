from copy import deepcopy
from types import SimpleNamespace

import pytest

from bff.services.run_preparation import _load_scope_frames
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.next_morning import PRICE_POLICY, SCHEMA
from src.optimization.common.date_series import (
    DATE_SERIES_INPUT_MODE, consecutive_service_dates, content_hash, dated_capacity_factors,
    materialize_dated_timetable, validate_dated_timetable,
)


def _templates():
    return [{'trip_id':f'{service}_{i}', 'route_id':'r1','operator_id':'tokyu','service_id':service,
             'origin':'A','destination':'A','origin_stop_id':'A','destination_stop_id':'A',
             'departure':f'{8+i:02d}:00','arrival':f'{8+i:02d}:30','distance_km':5.0,
             'distance_source':'verified_test_distance','allowed_vehicle_types':['ICE']}
            for service,count in [('WEEKDAY',2),('SAT',1),('SUN_HOL',3)] for i in range(count)]


def _dated_scenario():
    dates=consecutive_service_dates('2025-08-08',7)
    rows,contract=materialize_dated_timetable(_templates(),service_dates=dates,
                                             holiday_dates=['2025-08-11'],source_provenance={'test_fixture':True})
    profiles=[{'date':day,'slot_minutes':60,'capacity_factor_by_slot':[.1*(i+1)]*24} for i,day in enumerate(dates)]
    contract['pv_capacity_factor_rows_sha256']=content_hash(profiles)
    return {'meta':{'id':'dated-fixture'},'simulation_config':{
                'multi_day_input_mode':DATE_SERIES_INPUT_MODE,'date_series_contract':contract,
                'service_date':dates[0],'service_dates':dates,'planning_days':7,'timestep_min':30,
                'operation_time_window_enabled':False,'start_time':'00:00','default_turnaround_min':5,
                'depot_energy_assets':[{'depot_id':'d1','pv_capacity_kw_manual_override':True,'pv_capacity_kw':10,
                                        'pv_capacity_factor_by_date':profiles,'pv_enabled':True}]},
            'scenario_overlay':{'solver_config':{},'charging_constraints':{},'cost_coefficients':{}},
            'depots':[{'id':'d1'}],'routes':[{'id':'r1','distanceKm':5}],
            'vehicles':[{'id':'v1','depotId':'d1','type':'ICE'}],'timetable_rows':rows,
            'stops':[{'id':'A','name':'A','lat':35.6,'lon':139.6}],
            'energy_price_profiles':[{'site_id':'d1','values':[10]*24}],
            'deadhead_rules':[],'turnaround_rules':[]}


def test_real_service_days_include_weekend_and_public_holiday_without_mutating_templates():
    original=_templates()
    saved=deepcopy(original)
    dates=consecutive_service_dates('2025-08-08',7)
    rows,contract=materialize_dated_timetable(original,service_dates=dates,holiday_dates=['2025-08-11'],source_provenance={})
    assert original==saved
    assert [day['trip_count'] for day in contract['days']]==[2,1,3,3,2,2,2]
    assert [day['day_type'] for day in contract['days']]==['weekday','saturday','sunday_or_holiday','sunday_or_holiday','weekday','weekday','weekday']
    assert len(rows)==15
    assert rows[-1]['departure']=='153:00'
    assert rows[-1]['source_departure']=='09:00'


@pytest.mark.parametrize('explicit',[['2025-08-01','2025-08-03'],['2025-08-01','2025-08-01'],['2025-08-02','2025-08-01'],['invalid']])
def test_continuous_dates_never_silently_skip_sort_or_deduplicate(explicit):
    with pytest.raises(ValueError):
        consecutive_service_dates('2025-08-01',2,explicit)


@pytest.mark.parametrize('field,value',[('departure','00:00'),('operator_id','UNKNOWN'),('distance_km',0),('service_id','WEEKDAY')])
def test_dated_input_changes_are_rejected(field,value):
    scenario=_dated_scenario()
    scenario['timetable_rows'][2][field]=value
    with pytest.raises(ValueError):
        validate_dated_timetable(scenario['timetable_rows'],scenario['simulation_config']['date_series_contract'])


def test_missing_saturday_template_does_not_fall_back_to_weekday():
    templates=[row for row in _templates() if row['service_id']!='SAT']
    with pytest.raises(ValueError,match='No declared timetable'):
        materialize_dated_timetable(templates,service_dates=['2025-08-09'],holiday_dates=[],source_provenance={})


def test_builder_uses_exact_dated_trips_and_day_specific_pv_over_168_hours():
    scenario=_dated_scenario()
    problem=ProblemBuilder().build_from_scenario(scenario,depot_id='d1',service_id='WEEKDAY',planning_days=7)
    assert len(problem.trips)==len(problem.dispatch_context.trips)==15
    assert problem.scenario.horizon_duration_min==168*60
    assert len(problem.price_slots)==336
    assert problem.metadata['service_calendar_validation']['status']=='OK'
    assert [trip.service_date for trip in problem.trips]==[row['service_date'] for row in scenario['timetable_rows']]
    assert {trip.operator_id for trip in problem.trips}=={'tokyu'}
    generation=problem.depot_energy_assets['d1'].pv_generation_kwh_by_slot
    assert [sum(generation[i*48:(i+1)*48]) for i in range(7)]==pytest.approx([24,48,72,96,120,144,168])
    friday=next(trip for trip in problem.trips if trip.day_index==0)
    saturday=next(trip for trip in problem.trips if trip.day_index==1)
    assert saturday.trip_id in problem.feasible_connections[friday.trip_id]


def test_prepared_trip_rows_preserve_verified_next_morning_energy_horizon():
    scenario = _dated_scenario()
    config = scenario['simulation_config']
    dates = config['service_dates']
    next_date = consecutive_service_dates(dates[0], 8)[-1]
    next_rows, _ = materialize_dated_timetable(
        _templates(), service_dates=[next_date], holiday_dates=[],
        source_provenance={'test_fixture': True},
    )
    # Prepared inputs carry canonical `trips` and no `timetable_rows` key.
    next_rows = [{**row, 'day_index': 7} for row in next_rows]
    from src.optimization.common.date_series import timetable_hash

    next_pv = {'date': next_date, 'slot_minutes': 30,
               'capacity_factor_by_slot': [0.0] * 48}
    config.update(
        bev_soc_deadline_mode='next_morning_operational_max',
        final_overnight_mode='include',
        soc_max=0.8,
        bev_terminal_soc_policy='fixed_target',
        final_soc_target_percent=80.0,
        terminal_overnight_contract={
            'schema_version': SCHEMA,
            'service_dates': dates,
            'next_service_date': next_date,
            'next_day_timetable_rows': next_rows,
            'next_day_timetable_rows_sha256': timetable_hash(next_rows),
            'first_departure_minute_by_next_day': [
                min(int(row['source_departure'][:2]) * 60
                    + int(row['source_departure'][3:])
                    for row in scenario['timetable_rows']
                    if row['service_date'] == day)
                for day in dates[1:]
            ] + [480],
            'next_day_pv_capacity_factor': next_pv,
            'next_day_pv_sha256': content_hash(next_pv),
            'next_day_actual_pv_capacity_factor': next_pv.copy(),
            'next_day_actual_pv_sha256': content_hash(next_pv),
            'next_day_actual_pv_source_sha256': ['a' * 64],
            'price_calendar_policy': PRICE_POLICY,
        },
    )
    canonical = deepcopy(scenario)
    canonical['trips'] = canonical.pop('timetable_rows')
    problem = ProblemBuilder().build_from_scenario(
        canonical, depot_id='d1', service_id='WEEKDAY', planning_days=7,
    )
    assert len(problem.trips) == len(canonical['trips'])
    assert len(problem.price_slots) == 336 + 16
    assert len(problem.depot_energy_assets['d1'].pv_generation_kwh_by_slot) == 336 + 16


def test_prepare_reads_sealed_dated_rows_without_loading_or_filtering_global_catalog(tmp_path):
    scenario=_dated_scenario()
    scope=SimpleNamespace(route_ids=['r1'],service_ids=['WEEKDAY','SAT','SUN_HOL'])
    trips,stops,source=_load_scope_frames(scenario,built_dir=tmp_path,scope=scope)
    assert source=='verified_dated_timetable'
    assert trips['trip_id'].tolist()==[row['trip_id'] for row in scenario['timetable_rows']]


def test_partial_pv_day_is_rejected_instead_of_tiled():
    scenario=_dated_scenario()
    asset=scenario['simulation_config']['depot_energy_assets'][0]
    asset['pv_capacity_factor_by_date'][1]['capacity_factor_by_slot'].pop()
    with pytest.raises(ValueError,match='complete local day'):
        dated_capacity_factors(asset,scenario['simulation_config']['service_dates'],30)


def test_unlabelled_multi_day_replication_is_rejected():
    scenario=_dated_scenario()
    scenario['simulation_config'].pop('multi_day_input_mode')
    with pytest.raises(ValueError,match='repeated weekdays are diagnostic only'):
        ProblemBuilder().build_from_scenario(scenario,depot_id='d1',service_id='WEEKDAY',planning_days=7)


@pytest.mark.parametrize('load,accepted', [(0.0,True),(1.0,False),(float('nan'),False)])
def test_gross_pv_requires_declared_complete_zero_building_load(load,accepted):
    scenario=_dated_scenario()
    asset=scenario['simulation_config']['depot_energy_assets'][0]
    asset.update(pv_input_semantics='gross_generation_before_depot_load',depot_load_model='explicit_zero_nontraction_load',
                 depot_load_kwh_by_slot=[load]*336)
    if accepted:
        problem=ProblemBuilder().build_from_scenario(scenario,depot_id='d1',service_id='WEEKDAY',planning_days=7)
        assert problem.depot_energy_assets['d1'].depot_load_model=='explicit_zero_nontraction_load'
    else:
        with pytest.raises(ValueError,match='depot-load series'):
            ProblemBuilder().build_from_scenario(scenario,depot_id='d1',service_id='WEEKDAY',planning_days=7)
def test_historical_holiday_selection_preserves_legacy_coverage_and_rejects_tampering(tmp_path):
    import hashlib
    import json
    from bff.services.date_series_inputs import _verified_holiday_manifest
    for source, start in (("cabinet_office_20260910", "2024-01-01"),
                          ("cabinet_office_20260910_2022_2026", "2022-01-01")):
        directory = tmp_path / "data/external/calendar" / source
        directory.mkdir(parents=True)
        raw = b"verified test source"
        (directory / "syukujitsu.csv").write_bytes(raw)
        (directory / "manifest.json").write_text(json.dumps({
            "sha256": hashlib.sha256(raw).hexdigest(), "coverage_start": start,
            "coverage_end_exclusive": "2027-01-01", "holiday_dates": ["2022-01-10"]}), encoding="utf-8")
    assert _verified_holiday_manifest(tmp_path, ["2022-01-10"])["coverage_start"] == "2022-01-01"
    assert _verified_holiday_manifest(tmp_path, ["2025-01-10"])["coverage_start"] == "2024-01-01"
    with pytest.raises(ValueError, match="outside"):
        _verified_holiday_manifest(tmp_path, ["2022-01-10"], "cabinet_office_20260910")
    with pytest.raises(ValueError, match="Unknown"):
        _verified_holiday_manifest(tmp_path, ["2022-01-10"], "../unverified")
    (directory / "syukujitsu.csv").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        _verified_holiday_manifest(tmp_path, ["2022-01-10"])
