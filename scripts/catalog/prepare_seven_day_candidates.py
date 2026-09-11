"""Derive two reviewable input cases, preserving both original scenarios.

This command prepares inputs only. It never starts an optimization experiment
or upgrades the multiday research-acceptance gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from bff.services.date_series_inputs import prepare_date_series_scenario
from bff.services.run_preparation import get_or_build_run_preparation
from bff.store import scenario_store as store, output_paths
from src.optimization.common.date_series import DATE_SERIES_INPUT_MODE


CASES = (
    ('SUNNY_parent', '771d115b-75b0-49f7-a7f0-25f259a2cd21', 'historical_perfect_information'),
    ('RAIN_parent', 'b23fd26c-1233-4c73-bb9e-bdb8b1584760', 'training_only_forecast_proxy'),
)


def _parent_document_hash(document: dict) -> str:
    # Historical solver audits may contain infinity for a missing MIP bound.
    # Preserve that value when fingerprinting the untouched parent; stale
    # solver artifacts are invalidated before preparing its new child.
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _apply_daily_return_controls(document: dict, depot_id: str) -> None:
    """Replace inherited terminal tolerances only in the explicitly new case."""
    terminal = {'bev_terminal_soc_policy': 'return_to_initial',
                'final_soc_target_percent': None, 'final_soc_target_tolerance_percent': 0.0}
    document['simulation_config'].update(terminal, daily_return_depot_id=depot_id,
                                        rolling_window_terminal_policy='day_ahead_boundary_state')
    document.setdefault('scenario_overlay', {}).setdefault('charging_constraints', {}).update(terminal)


def prepare_candidates(start_date: str, output: Path, *, cases: tuple = CASES,
                       route_code: str | None = None, daily_return_depot_id: str | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'derived_scenarios.json'
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if previous and previous.get('start_date') != start_date:
        raise ValueError('Use a new output directory for another evaluation week')
    manifest = {'status': 'INPUT_PREPARATION_IN_PROGRESS', 'start_date': start_date,
                'research_status': 'BLOCKED', 'formal_solve_executed': False,
                'cases': list(previous.get('cases') or [])}

    def persist() -> None:
        manifest['updated_at_utc'] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    for label, parent_id, information_mode in cases:
        print(f'Preparing {label}: {information_mode}', flush=True)
        parent = store._load(parent_id, skip_graph_arcs=True)
        parent_hash = _parent_document_hash(parent)
        record = next((row for row in manifest['cases'] if row['parent_scenario_id'] == parent_id), None)
        if record is None:
            meta = store.duplicate_scenario(parent_id, name=f'7日入力候補 {start_date} {label} {information_mode}')
            record = {'parent_scenario_id': parent_id, 'scenario_id': meta['id'],
                      'parent_document_sha256_before': parent_hash}
            manifest['cases'].append(record)
            persist()
        elif record['parent_document_sha256_before'] != parent_hash:
            raise ValueError('Parent scenario changed since this derived input was created')
        doc = store._load(record['scenario_id'], skip_graph_arcs=True)
        cfg = doc['simulation_config']
        cfg.update(multi_day_input_mode=DATE_SERIES_INPUT_MODE, service_date=start_date,
                   service_dates=[], planning_days=7, planning_horizon_hours=168,
                   time_step_min=15, timestep_min=15, start_time='00:00', end_time='23:59',
                   operation_time_window_enabled=False, rolling_lookahead_hours=24,
                   bess_balance_period='daily', pv_information_mode=information_mode)
        cfg.pop('calendar_policy', None)
        cfg['allow_fixed_weekday_timetable_pv_counterfactual'] = False
        if daily_return_depot_id:
            _apply_daily_return_controls(doc, daily_return_depot_id)
        if route_code:
            routes = json.loads((REPO_ROOT/'data/derived/timetables/tsurumaki_20260901/selected_routes.json').read_text(encoding='utf-8'))
            selected = [row['id'] for row in routes if unicodedata.normalize('NFKC',str(row.get('routeCode') or '')) == route_code]
            if not selected:
                raise ValueError(f'No verified route patterns for {route_code}')
            doc['dispatch_scope']['routeSelection']['includeRouteIds'] = selected
            doc['dispatch_scope']['routeSelection']['excludeRouteIds'] = []
        doc['meta']['derivation_provenance'] = {
            'parent_scenario_id': parent_id, 'parent_document_sha256': parent_hash,
            'purpose': 'seven_day_input_candidate_not_formal_research_result',
            'changed_controls': ['dated_timetable_and_calendar', 'dated_or_training_proxy_PV',
                                 'planning_days=7', 'timestep=15min', 'lookahead=24h',
                                 'daily_BESS_balance', 'explicit_zero_nontraction_load'],
        }
        if route_code:
            doc['meta']['derivation_provenance']['selected_route_code'] = route_code
        if daily_return_depot_id:
            doc['meta']['derivation_provenance']['daily_return_depot_id'] = daily_return_depot_id
            doc['meta']['derivation_provenance']['changed_controls'].extend(
                ['daily_depot_return', 'BEV_terminal_return_to_vehicle_initial', 'terminal_tolerance=0'])
        store._invalidate_dispatch_artifacts(doc)
        doc = prepare_date_series_scenario(doc)
        store._normalize_dispatch_scope(doc)
        store._save(doc)
        doc = store._load(record['scenario_id'], skip_graph_arcs=True)
        if doc['meta'].get('derivation_provenance', {}).get('parent_document_sha256') != parent_hash:
            raise ValueError('Scenario persistence lost its derivation provenance')
        prepared = get_or_build_run_preparation(
            scenario=doc, built_dir=REPO_ROOT/'data/built/tokyu_core',
            scenarios_dir=output_paths.outputs_root() / 'prepared_inputs', routes_df=None,
        )
        after_hash = _parent_document_hash(store._load(parent_id, skip_graph_arcs=True))
        if after_hash != parent_hash:
            raise ValueError('Parent changed during input derivation; inspect concurrent activity')
        contract = doc['simulation_config']['date_series_contract']
        record.update(parent_document_sha256_after=after_hash, parent_unchanged=True,
                       pv_information_mode=information_mode, prepared_input_id=prepared.prepared_input_id,
                       selected_route_code=route_code, daily_return_depot_id=daily_return_depot_id,
                      input_preparation_valid=prepared.is_valid, error_code=prepared.error_code,
                      error=prepared.error, warnings=list(prepared.warnings),
                      vehicle_count=len(doc.get('vehicles') or []),
                      timetable_row_count=len(doc['timetable_rows']),
                      service_dates=contract['service_dates'],
                      days=[{key: day[key] for key in ('service_date','day_type','trip_count')}
                            for day in contract['days']],
                      scope_summary=prepared.scope_summary)
        persist()
        print(json.dumps({key: record[key] for key in ('scenario_id','input_preparation_valid',
              'prepared_input_id','vehicle_count','timetable_row_count','error_code','error')}, ensure_ascii=False), flush=True)
    manifest['status'] = ('INPUTS_PREPARED_RESEARCH_BLOCKED' if all(
        row['input_preparation_valid'] for row in manifest['cases']) else 'INPUT_PREPARATION_BLOCKED')
    persist()
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-date', default='2025-08-04')
    parser.add_argument('--output', type=Path, default=Path('output/seven_day_extension_20260910/derived_inputs'))
    parser.add_argument('--shibu21-seasonal-test', action='store_true',
                        help='Create four dated Shibu21 forecast-proxy inputs with mandatory Tsurumaki returns')
    args = parser.parse_args()
    if args.shibu21_seasonal_test:
        results = []
        for week in ('2025-02-03','2025-05-05','2025-08-04','2025-11-03'):
            result = prepare_candidates(week,args.output/week,
                cases=(('Shibu21_test','771d115b-75b0-49f7-a7f0-25f259a2cd21','training_only_forecast_proxy'),),
                route_code='渋21',daily_return_depot_id='tsurumaki')
            results.append({'week':week,'status':result['status']})
        print(json.dumps(results))
    else:
        result = prepare_candidates(args.start_date, args.output)
        print(json.dumps({'status': result['status'], 'case_count': len(result['cases'])}))
