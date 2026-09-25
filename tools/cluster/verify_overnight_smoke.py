"""Read-only acceptance check for collected overnight_smoke diagnostic batches.

No solver or network use. Hashes, physical validation and executed accounting
are separate checks; success does not authorize a real or formal research run.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.cluster.audit_batch import audit_batch


def inspect_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as source:
        roots = [name.rsplit('/', 1)[0] for name in source.namelist()
                 if name.endswith('/effective_scenario.json')]
        if len(roots) != 1:
            raise ValueError('Expected one effective scenario run root')
        def read(suffix: str) -> dict:
            return json.loads(source.read(roots[0] + '/' + suffix))

        scenario = read('effective_scenario.json')
        config = scenario['simulation_config']
        days = config['planning_days']
        if config['date_series_contract']['source_provenance'].get('data_kind') != 'synthetic_overnight_test':
            raise ValueError('This checker only accepts the declared synthetic fixture')
        if days not in (1, 2, 7):
            raise ValueError('Unsupported fixture duration')
        chain = read('rolling_hourly_chain/rolling_chain_summary.json')
        physical = read('physical_schedule_validation.json')
        accounting = read('rolling_hourly_chain/executed_day_accounting.json')
        plan = read('rolling_hourly_chain/executed_plan.json')
        cost = accounting['cost_breakdown']
        grid_kwh = sum(float(value) for slots in plan['grid_to_bus_kwh_by_depot_slot'].values()
                       for value in slots.values())
        expected_trips = {row['trip_id'] for row in scenario['timetable_rows']}
        checks = {
            'diagnostic_class_retained': chain.get('research_run') is False,
            'physical_accepted': physical.get('accepted') is True,
            'all_hourly_steps': chain['step_count'] == chain['expected_step_count'] == 24 * days,
            'chain_accepted': chain.get('chain_accepted') is True and chain.get('all_steps_feasible') is True,
            'all_trips': set(plan['served_trip_ids']) == expected_trips and not plan['unserved_trip_ids'],
            'all_executed_slots': accounting['executed_slot_count'] == accounting['expected_slot_count'] == 48 * days,
            'accounting_eligible': accounting.get('eligible') is True,
            'no_duplicate_or_missing_slots': not accounting['missing_slots'] and not accounting['duplicate_slots'],
            'bev_terminal_restored': accounting.get('bev_terminal_energy_balanced') is True,
            'fixture_has_zero_pv_and_no_bess': all(
                not asset.get('bess_enabled') and not any(asset.get('pv_generation_kwh_by_slot', []))
                for asset in config['depot_energy_assets']) and all(
                    cost.get(key) == 0 for key in ('pv_generated_kwh', 'pv_to_bus_kwh', 'bess_to_bus_kwh')),
            'declared_price_20': all(profile['values'] == [20.0] * (48 * days)
                                    for profile in scenario['energy_price_profiles']),
            'positive_grid_energy': math.isfinite(grid_kwh) and grid_kwh > 0,
            'grid_meter_reconciled': math.isclose(cost['grid_import_kwh'], grid_kwh, abs_tol=1e-6, rel_tol=0),
            'electricity_bill_reconciled': math.isclose(cost['electricity_cost'], 20 * grid_kwh, abs_tol=1e-6, rel_tol=0),
            'total_bill_reconciled': math.isclose(cost['total_cost'], 20 * grid_kwh, abs_tol=1e-6, rel_tol=0),
        }
        return {'passed': all(checks.values()), 'checks': checks, 'days': days,
                'trip_count': len(expected_trips), 'grid_kwh': grid_kwh,
                'electricity_cost_jpy': cost['electricity_cost'], 'total_cost_jpy': cost['total_cost'],
                'research_approval': 'NOT_GRANTED_BY_TEST'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_bytes())
    state = json.loads((args.state_dir / 'batch-state.json').read_bytes())
    collection = audit_batch(spec, state, args.state_dir)
    results = []
    for task in collection['tasks']:
        try:
            if not task['collection_verified']:
                raise ValueError(task.get('error', 'Collection not verified'))
            result = inspect_archive(args.state_dir / f"{task['job_id']}.zip")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            result = {'passed': False, 'error': str(exc)}
        results.append({'task_id': task['task_id'], 'job_id': task['job_id'], **result})
    passed = bool(results) and all(row['passed'] for row in results)
    report = {'passed': passed, 'collection': collection, 'tasks': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': passed, 'tasks': results}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
