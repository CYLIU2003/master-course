from __future__ import annotations
import copy
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from calendar_patch import EXPECTED_BLOB, git_blob_sha, patched_source
from solcast_year import JST, request_plan, validate_records, parse_timestamp
from seasonal_curves import build_curves, season_for, quantile

ORIGINAL = (ROOT/'evidence/service_calendar_original.py').read_text(encoding='utf-8')
old = {}; exec(compile(ORIGINAL, 'pinned_original', 'exec'), old)
new = {}; exec(compile(patched_source(ORIGINAL), 'patched', 'exec'), new)


def validate(module, rows, day='2025-08-05', config=None, strict=True):
    return module['validate_service_calendar_contract'](
        service_date_text=day, timetable_rows=rows,
        scenario_metadata={'simulation_config': config or {}}, strict=strict)


def one_day(day=date(2025, 8, 31), minutes=60, level=100):
    lower = datetime.combine(day, datetime.min.time(), JST)
    records = []
    for i in range(1440//minutes):
        records.append({'period_end': (lower+timedelta(minutes=minutes*(i+1))).isoformat(),
                        'period': f'PT{minutes}M', 'ghi': level if 9*60 <= i*minutes < 15*60 else 0})
    return lower, lower+timedelta(days=1), records


def test_source_blob_is_exact_github_source():
    assert git_blob_sha((ROOT/'evidence/service_calendar_original.py').read_bytes()) == EXPECTED_BLOB

@pytest.mark.parametrize('value, expected', [
    ('WEEKDAY', 'weekday'), ('SAT', 'saturday'), ('SUN_HOL', 'sunday_or_holiday'),
    ('SAT_HOL', 'weekend_or_holiday'), ('SUN_HOLIDAY', 'sunday_or_holiday'),
    ('SAT_HOLIDAY', 'weekend_or_holiday'), ('sunday_or_holiday', 'sunday_or_holiday'),
    ('weekend_or_holiday', 'weekend_or_holiday')])
def test_normalization(value, expected):
    assert new['_normalize_day_type'](value) == expected


def test_original_alias_bug_reproduced():
    assert old['_normalize_day_type']('SUN_HOL') is None
    assert old['_normalize_day_type']('SAT_HOL') is None
    with pytest.raises(ValueError):
        validate(old, [{'service_id':'SUN_HOL', 'trip_id':'opaque-id'}], day='2025-08-10')
    assert validate(new, [{'service_id':'SUN_HOL', 'trip_id':'opaque-id'}], day='2025-08-10')['status']=='OK'


def test_original_unknown_row_bypass_reproduced_and_blocked():
    rows = [{'service_id':'WEEKDAY','trip_id':'good'}, {'service_id':'mystery','trip_id':'opaque'}]
    assert validate(old, rows)['status']=='OK'
    with pytest.raises(ValueError, match='unverifiable'):
        validate(new, rows)
    result = validate(new, rows, strict=False)
    assert result['status']=='ERROR' and result['unverifiable_row_indices']==[1]


def test_non_object_row_no_longer_disappears():
    rows=[{'service_id':'WEEKDAY'}, None]
    assert validate(old,rows)['status']=='OK'
    with pytest.raises(ValueError, match='unverifiable'):
        validate(new,rows)


def test_counterfactual_waiver_preserved_but_does_not_waive_unknown_rows():
    cfg={'calendar_policy':'fixed_weekday_timetable_pv_counterfactual',
         'allow_fixed_weekday_timetable_pv_counterfactual':True}
    assert validate(new,[{'service_id':'WEEKDAY'}],day='2025-08-10',config=cfg)['status']=='WAIVED_BY_EXPERIMENT_POLICY'
    with pytest.raises(ValueError):
        validate(new,[{'service_id':'WEEKDAY'},{}],day='2025-08-10',config=cfg)


def test_actual_service_mismatch_rejected():
    with pytest.raises(ValueError, match='mismatch'):
        validate(new,[{'service_id':'WEEKDAY'}],day='2025-08-10')


def test_declared_holiday_not_weekday():
    assert validate(new,[{'service_id':'SUN_HOL'}],day='2025-08-11',
                    config={'holiday_dates':['2025-08-11']})['status']=='OK'


def test_pv_date_mismatch_not_waived_for_real_operation():
    with pytest.raises(ValueError, match='weather_date'):
        validate(new,[{'service_id':'WEEKDAY'}],config={'weather_observation_date':'2025-08-10'})


def test_diff_generator_fails_closed_on_changed_source():
    with pytest.raises(ValueError):
        patched_source(ORIGINAL.replace('    errors: list[str] = []', '    errors = []'))


SITE={'depot_id':'tsurumaki','latitude':35.63514694444444,'longitude':139.6462427777778}


def test_calendar_year_plan_all_365_days_and_august31():
    plan=request_plan(SITE,date(2025,1,1),date(2026,1,1),15)
    assert len(plan)==12
    assert sum(p['expected_records'] for p in plan)==35040
    assert plan[7]['query']['duration']=='P31D'
    assert plan[7]['expected_records']==2976
    assert plan[-1]['end_exclusive_jst']=='2026-01-01T00:00:00+09:00'


def test_calendar_and_fiscal_union_not_mixed():
    plan=request_plan(SITE,date(2025,1,1),date(2026,4,1),15)
    assert len(plan)==15
    assert sum(p['expected_records'] for p in plan)==43680


def test_no_secret_or_unconfirmed_gti_geometry_in_plan():
    plan=request_plan(SITE,date(2025,1,1),date(2025,2,1))
    assert 'gti' not in plan[0]['query']['output_parameters'].split(',')
    assert 'Authorization' not in json.dumps(plan)
    with pytest.raises(ValueError,match='both explicit'):
        request_plan({**SITE,'tilt':20},date(2025,1,1),date(2025,2,1))


def test_utc_and_jst_equal_boundaries_and_last_interval():
    start,end,rows=one_day()
    rows[-1]['period_end']=end.astimezone(timezone.utc).isoformat()
    assert len(validate_records(rows,start,end,60))==24
    assert (parse_timestamp(rows[-1]['period_end'])-timedelta(minutes=60)).astimezone(JST).date()==date(2025,8,31)

@pytest.mark.parametrize('fault',['missing','duplicate','nan','negative','naive','wrong_period'])
def test_invalid_raw_data_fails_instead_of_filling(fault):
    start,end,rows=one_day()
    if fault=='missing': rows.pop()
    elif fault=='duplicate': rows.append(copy.deepcopy(rows[0]))
    elif fault=='nan': rows[0]['ghi']=float('nan')
    elif fault=='negative': rows[0]['ghi']=-1
    elif fault=='naive': rows[0]['period_end']='2025-08-31T01:00:00'
    else: rows[0]['period']='PT15M'
    with pytest.raises(ValueError):
        validate_records(rows,start,end,60)


def test_all_zero_is_not_assumed_corrupt():
    start,end,rows=one_day(level=0)
    assert len(validate_records(rows,start,end,60))==24


def test_jst_march_boundary():
    stamp=parse_timestamp('2025-02-28T15:00:00Z')
    owner=(stamp-timedelta(minutes=60)).astimezone(JST).date()
    assert owner==date(2025,2,28)
    assert season_for(owner)=='winter'
    assert season_for(date(2025,3,1))=='spring'

@pytest.fixture(scope='module')
def synthetic_year():
    rows=[]; labels={}
    for i in range(365):
        day=date(2025,1,1)+timedelta(days=i)
        labels[day.isoformat()]=('sunny','cloudy','rainy')[i%3]
        rows.extend(one_day(day=day,level=100*(i%3+1))[2])
    return rows,labels


def test_twelve_cells_from_synthetic_not_user_measurements(synthetic_year):
    rows,labels=synthetic_year
    result=build_curves(rows,labels,start=date(2025,1,1),end_exclusive=date(2026,1,1),minutes=60)
    assert len(result['curves'])==12 and result['record_count']==8760
    assert sum(c['source_day_count'] for c in result['curves'])==365
    for cell in result['curves']:
        curve=cell['irradiance']['ghi']
        expected={'sunny':0.6,'cloudy':1.2,'rainy':1.8}[cell['weather_class']]
        # Test labels deliberately oppose irradiance ranking: never relabel from energy.
        assert curve['mean_daily_irradiation_kwh_m2']==pytest.approx(expected)
        assert all(a<=b<=c for a,b,c in zip(curve['p10'],curve['p50'],curve['p90']))
        assert curve['mean'][0]==0


def test_missing_weather_labels_rejected(synthetic_year):
    rows,labels=synthetic_year
    bad=dict(labels); del bad['2025-08-31']
    with pytest.raises(ValueError,match='exactly'):
        build_curves(rows,bad,start=date(2025,1,1),end_exclusive=date(2026,1,1),minutes=60)


def test_sparse_cells_not_fabricated():
    _,_,rows=one_day()
    with pytest.raises(ValueError,match='Insufficient groups'):
        build_curves(rows,{'2025-08-31':'rainy'},start=date(2025,8,31),end_exclusive=date(2025,9,1),minutes=60,min_days=1)
    result=build_curves(rows,{'2025-08-31':'rainy'},start=date(2025,8,31),end_exclusive=date(2025,9,1),minutes=60,min_days=1,diagnostic=True)
    assert result['status']=='DIAGNOSTIC_INCOMPLETE'
    assert result['curves'][0]['irradiance']['ghi'] is None


def test_standard_quantile_interpolation():
    assert quantile([0,10], .1)==1
    assert quantile([0,10], .9)==9
