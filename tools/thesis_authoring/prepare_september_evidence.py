"""Read frozen monthly archives and weather sources for the September deck.

This is descriptive reanalysis, never a solver, downloader, or research approval.
The destination must be new. Original archives and failed job states stay intact.
"""
from __future__ import annotations
import argparse
import base64
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research.monthly_power_evidence import case_evidence, index_proofs, read, sha
from tools.research.weekly_results import FLOWS, require_close, require_coverage, write_csv, write_json
from src.preprocess.weather.solcast_archive import load_verified_archive
from src.preprocess.weather.seasonal_irradiance import build_seasonal_curves, WeatherClassificationPolicy


def weather_evidence(directory: Path) -> dict:
    source = ROOT / 'data/derived/seasonal_irradiance/tsurumaki/cy2025'
    manifest = read(source / 'manifest.json')
    for name, item in manifest['artifacts'].items():
        if sha(source / name) != item['sha256']:
            raise ValueError('Weather artifact hash mismatch: ' + name)
    records, sources = load_verified_archive(ROOT / 'data/external/solcast_raw/tsurumaki_2025_2026', date(2025, 1, 1), date(2026, 1, 1))
    original = read(source / 'seasonal_curves.json')
    rebuilt = build_seasonal_curves(records, start=date(2025, 1, 1), end_exclusive=date(2026, 1, 1), policy=WeatherClassificationPolicy(**manifest['classification_policy']))
    if len(records) != 35040 or rebuilt['curves'] != original['curves'] or rebuilt['daily_labels'] != original['daily_labels']:
        raise ValueError('Weather classification/statistics do not reproduce')
    expected = {(s['sha256'], s['request_sha256']) for s in manifest['sources']}
    if expected != {(s['sha256'], s['request_sha256']) for s in sources}:
        raise ValueError('Weather raw source set differs')
    directory.mkdir()
    for name in ['seasonal_curves.csv', 'weather_labels.csv', 'manifest.json']:
        shutil.copyfile(source / name, directory / name)
    return rebuilt


def extract_week(row: dict, proof: dict, output: Path) -> dict:
    _, power = case_evidence(row, proof)  # Archive/Prepared hashes and receiving-power account.
    case = Path(proof['case'])
    item = read(case / 'state/batch-state.json')['tasks'][row['week']]
    prepared = read(case / 'prepared.json')
    with zipfile.ZipFile(case / 'state' / item['artifacts']) as archive:
        worker_bytes = archive.read('state.json')
        worker = json.loads(worker_bytes)
        original = verify_original_state(row, proof, item, worker)
        members = [n for n in archive.namelist() if n.endswith('/rolling_hourly_chain/executed_day_accounting.json')]
        if len(members) != 1:
            raise ValueError('Nonunique final account')
        prefix = members[0].removesuffix('executed_day_accounting.json')
        raw = {name: archive.read(prefix + name) for name in ['executed_day_accounting.json', 'executed_plan.json']}
        physical_bytes = archive.read(prefix.removesuffix('rolling_hourly_chain/') + 'physical_schedule_validation.json')
        account, plan = [json.loads(raw[n]) for n in ['executed_day_accounting.json', 'executed_plan.json']]
        physical = json.loads(physical_bytes)
        inputs = json.loads(base64.b64decode(json.loads(archive.read('bundle.json'))['prepared_base64']))
    slots = row['executed_slots_including_overnight']
    if not account['eligible'] or not physical['accepted'] or physical['failed_checks'] or account['missing_slots'] or account['duplicate_slots'] or account['executed_slot_count'] != slots:
        raise ValueError('Physical/accounting/overnight gate failed')
    trips = {t['trip_id']: t for t in inputs['trips']}
    if len(trips) != len(inputs['trips']):
        raise ValueError('Duplicate input trip')
    assignments = require_coverage(trips, plan)
    require_close(account['cost_breakdown']['total_cost'], row['total_cost'], 'published cost')
    require_close(math.fsum(d['total_cost_jpy'] for d in plan['daily_cost_ledger']), row['total_cost'], 'daily ledger')
    flows = {key: [math.fsum(float(values.get(str(s), 0)) for f in fields for values in plan[f].values()) for s in range(slots)] for key, fields in FLOWS.items()}
    for key, values in flows.items():
        require_close(math.fsum(values), row[key], key)
    charge = [0.] * slots
    for c in plan['charging_schedule']:
        s = int(c['slot_index'])
        if not 0 <= s < slots:
            raise ValueError('Charge beyond accepted period')
        charge[s] += float(c['charge_kw']) * .25
    start = datetime.fromisoformat(row['week'])
    energy = []
    for s in range(slots):
        require_close(flows['grid_import_kwh'][s] + flows['pv_to_bus_kwh'][s] + flows['bess_to_bus_kwh'][s], charge[s], 'bus balance')
        energy.append({'slot': s, 'interval_start_jst': (start + timedelta(minutes=15*s)).isoformat(), **{k: v[s] for k,v in flows.items()}, 'bus_charge_kwh': charge[s], 'bess_soc_end_kwh': plan['bess_soc_kwh_by_depot_slot']['tsurumaki'][str(s)]})
    vehicles = {v['id']: v for v in inputs['vehicles']}
    soc = [{'vehicle_id': v, 'state_index': int(s), 'soc_kwh': value, 'soc_percent': 100*float(value)/vehicles[v]['batteryKwh']} for v, values in plan['vehicle_soc_kwh_by_vehicle_slot'].items() for s,value in values.items()]
    schedule = [{'vehicle_id': assignments[t], **trip} for t,trip in trips.items()]
    output.mkdir()
    write_csv(output / 'fleet.csv', [{**v, 'used_in_week': v['id'] in set(assignments.values())} for v in inputs['vehicles']])
    for name, values in [('energy_15min', energy), ('vehicle_soc', soc), ('vehicle_schedule', schedule), ('charging_schedule', plan['charging_schedule']), ('daily_summary', plan['daily_cost_ledger'])]:
        write_csv(output / (name + '.csv'), values)
    write_json(output / 'physical_validation.json', physical)
    write_json(output / 'executed_accounting.json', account)
    daily = []
    for day in range(7):
        entries = [t for t in schedule if int(t['day_index']) == day]
        daily.append({'day': day, 'date': (start + timedelta(days=day)).date().isoformat(), 'trips': len(entries), 'calendar': sorted({t['service_id'] for t in entries}), 'used_vehicles': len({t['vehicle_id'] for t in entries})})
    soc_series = []
    used_bevs = {v for v in assignments.values() if vehicles[v]['type'] == 'BEV'}
    if {s['vehicle_id'] for s in soc} != used_bevs:
        raise ValueError('SOC evidence does not cover the dispatched BEV set')
    for v in sorted({s['vehicle_id'] for s in soc}):
        values = sorted((s for s in soc if s['vehicle_id'] == v), key=lambda s:s['state_index'])
        if [s['state_index'] for s in values] != list(range(slots+1)):
            raise ValueError('SOC boundary coverage incomplete')
        soc_series.append({'id': v, 'values': [s['soc_percent'] for s in values]})
    return {'summary': row, 'power': power, 'energy': energy, 'soc': soc_series, 'daily': daily,
            'verified': {'physical_accepted': True, 'accounting_eligible': True, 'trip_count': len(trips), 'slots': slots,
                **original,
                'worker_state_sha256': hashlib.sha256(worker_bytes).hexdigest(),
                'account_sha256': hashlib.sha256(raw['executed_day_accounting.json']).hexdigest(),
                'physical_sha256': hashlib.sha256(physical_bytes).hexdigest(), 'archive_sha256': proof['archive_sha256']}}


def verify_original_state(row: dict, proof: dict, item: dict, worker: dict) -> dict:
    """Verify a reporting recovery without rewriting the original worker verdict."""
    if worker['id'] != row['job_id'] or item['state'] != worker['state']:
        raise ValueError('Original attempt/state differs')
    if worker['provenance']['git']['sha'] != row['git_sha']:
        raise ValueError('Original worker source differs')
    result = {'original_state': worker['state'], 'reporting_warning': None}
    if 'recovery' not in proof:
        if worker['state'] != 'COMPLETED':
            raise ValueError('Incomplete worker without reporting recovery')
        return result
    receipt_path = Path(proof['recovery']) / 'recovery.json'
    if sha(receipt_path) != proof['recovery_receipt_sha256']:
        raise ValueError('Reporting recovery receipt changed')
    receipt = read(receipt_path)
    error = worker['result'].get('error', '')
    if (worker['state'] != 'FAILED' or proof['original_worker_state'] != 'FAILED'
            or receipt['original_worker_state'] != 'FAILED'
            or receipt['new_solver_run'] is not False
            or receipt['status'] != 'REPORTING_RECOVERED_CONDITIONAL_EVALUATION'
            or worker['result']['metadata'].get('failure_type') != 'LiteratureFigureError'
            or 'Conflicting grid CO2 factors' not in error):
        raise ValueError('Failure is not the verified CO2 reporting-only recovery')
    result['reporting_warning'] = error.strip().splitlines()[-1]
    result['recovery_receipt_sha256'] = proof['recovery_receipt_sha256']
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    latest = read(args.report / 'latest.json')
    revision = Path(latest['directory']).resolve()
    if not revision.is_relative_to((args.report / 'revisions').resolve()):
        raise ValueError('Revision outside report')
    if not latest['complete'] or latest['included'] != 12 or latest['declared'] != 12:
        raise ValueError('Twelve completed included weeks required')
    manifest = read(revision / 'manifest.json')
    if sha(revision / 'comparison.json') != manifest['comparison.json']:
        raise ValueError('Comparison hash changed')
    comparison = read(revision / 'comparison.json')
    rows = comparison['rows']
    if len(rows) != 12 or len({r['week'] for r in rows}) != 12 or any(r['git_sha'] != comparison['source_sha'] or r['evaluation_status'] != 'VERIFIED_CONDITIONAL_WEEKLY_EVALUATION' for r in rows):
        raise ValueError('Mixed or unverified cases')
    args.output.mkdir(parents=True, exist_ok=False)
    proofs = index_proofs(comparison['evidence'])
    if set(proofs) != {r['week'] for r in rows}:
        raise ValueError('Proof coverage mismatch')
    weeks = [extract_week(row, proofs[row['week']], args.output / row['week']) for row in rows]
    weather = weather_evidence(args.output / 'weather')
    payload = {'revision': latest['revision'], 'source_sha': comparison['source_sha'], 'comparison_sha256': manifest['comparison.json'], 'weeks': weeks, 'weather': weather, 'new_solver_run': False}
    write_json(args.output / 'presentation_data.json', payload)
    shutil.copyfile(revision / 'comparison.json', args.output / 'comparison.json')
    write_csv(args.output / 'weekly_summary.csv', [{k: v for k, v in row.items() if not isinstance(v, (dict, list))} for row in rows])
    write_json(args.output / 'manifest.json', {str(p.relative_to(args.output)): sha(p) for p in args.output.rglob('*') if p.is_file()})
    print(json.dumps({'weeks': len(weeks), 'weather_records': weather['record_count'], 'output': str(args.output), 'new_solver_run': False}))


if __name__ == '__main__':
    main()
