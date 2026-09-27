"""Recalculate receiving-power metrics from collected plans; never run a solver.

The published comparison supplies the archive hashes and accepted case list.
This descriptive report does not change the original research verdicts.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

SERVICE_DAYS = 7
SLOT_MINUTES = 15
SERVICE_SLOTS = SERVICE_DAYS * 24 * 60 // SLOT_MINUTES


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def close(actual: float, expected: float, label: str) -> None:
    if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual - expected) > 1e-6:
        raise ValueError(f'{label}: {actual} != {expected}')


def metrics(energy: list[float], limit_kw: float) -> dict:
    """Quarter-hour energy to full-period power, with explicit counting tolerance."""
    if not energy or not math.isfinite(limit_kw) or limit_kw < 0:
        raise ValueError('Empty series or invalid contract threshold')
    if any(not math.isfinite(v) or v < -1e-6 for v in energy):
        raise ValueError('Invalid import energy')
    powers = [v / .25 for v in energy]
    return {'slots': len(energy), 'hours': len(energy) * .25,
            'grid_import_kwh': math.fsum(energy),
            'mean_grid_kw': math.fsum(energy) / (len(energy) * .25),
            'peak_grid_kw': max(powers),
            'peak_slot': powers.index(max(powers)),
            'over_contract_kwh': math.fsum(max(v - limit_kw * .25, 0.) for v in energy),
            'over_contract_hours': sum(v > limit_kw + .001 for v in powers) * .25,
            'over_contract_counting_tolerance_kw': .001}


def case_evidence(row: dict, proof: dict) -> tuple[list[dict], dict]:
    case = Path(proof['case'])
    item = read(case / 'state/batch-state.json')['tasks'][row['week']]
    archive_path = case / 'state' / item['artifacts']
    if sha(archive_path) != proof['archive_sha256'] or item['job_id'] != row['job_id']:
        raise ValueError('Archive/attempt differs from published evidence')
    prepared_record = read(case / 'prepared.json')
    with zipfile.ZipFile(archive_path) as archive:
        prepared_bytes = base64.b64decode(json.loads(archive.read('bundle.json'))['prepared_base64'], validate=True)
        if hashlib.sha256(prepared_bytes).hexdigest() != prepared_record['prepared_sha256']:
            raise ValueError('Prepared hash differs from archive')
        inputs = json.loads(prepared_bytes)
        if (inputs['planning_days'] != SERVICE_DAYS
                or inputs['simulation_config']['timestep_min'] != SLOT_MINUTES):
            raise ValueError('Only seven service days at 15-minute resolution are supported')
        names = [n for n in archive.namelist() if n.endswith('/rolling_hourly_chain/executed_plan.json')]
        if len(names) != 1:
            raise ValueError('Expected one executed plan')
        plan_bytes = archive.read(names[0])
        plan = json.loads(plan_bytes)
        run = names[0].removesuffix('rolling_hourly_chain/executed_plan.json')
        limits = list(csv.DictReader(io.StringIO(archive.read(run + 'simulation_conditions_contract_limits.csv').decode('utf-8-sig'))))
        if len(limits) != 1 or limits[0]['site_type'] != 'depot':
            raise ValueError('Only single-depot archived contract tables are supported')
        depot = limits[0]['site_id']
        limit = float(limits[0]['contract_demand_limit_kw'])
    slots = row['executed_slots_including_overnight']
    if slots != SERVICE_SLOTS + prepared_record['overnight']['extra_slots'] or slots < SERVICE_SLOTS:
        raise ValueError('Declared overnight coverage differs')
    fields = ['grid_to_bus_kwh_by_depot_slot', 'grid_to_bess_kwh_by_depot_slot']
    if any(set(plan[f]) != {depot} for f in fields):
        raise ValueError('Energy boundary differs from contract table')
    if any(any(int(s) < 0 or int(s) >= slots for s in plan[f][depot]) for f in fields):
        raise ValueError('Energy outside evaluation period')
    energy = [math.fsum(float(plan[f][depot].get(str(s), 0.)) for f in fields) for s in range(slots)]
    full = metrics(energy, limit)
    close(full['grid_import_kwh'], row['grid_import_kwh'], 'import')
    close(full['peak_grid_kw'], row['peak_grid_kw'], 'peak')
    close(full['over_contract_kwh'], row['contract_over_limit_kwh'], 'excess energy')
    start = datetime.fromisoformat(row['week'])
    times = [{'week': row['week'], 'slot': s, 'interval_start_jst': (start + timedelta(minutes=15*s)).isoformat(),
              'period': 'service_week' if s < SERVICE_SLOTS else 'paid_final_overnight',
              'grid_import_kwh': value, 'grid_import_kw': value / .25,
              'contract_demand_limit_kw': limit} for s, value in enumerate(energy)]
    return times, {'week': row['week'], 'job_id': row['job_id'], 'source_sha': row['git_sha'],
                   'archive_sha256': proof['archive_sha256'], 'plan_sha256': hashlib.sha256(plan_bytes).hexdigest(),
                   'contract_demand_limit_kw': limit, 'full_period': full,
                   'service_week': metrics(energy[:SERVICE_SLOTS], limit),
                   'peak_interval_start_jst': times[full['peak_slot']]['interval_start_jst'],
                   'contract_overage_cost_jpy': row['contract_overage_cost'],
                   'original_research_verdict': row['original_research_verdict']}


def index_proofs(evidence: list[dict]) -> dict[str, dict]:
    proofs = {}
    for proof in evidence:
        week = Path(proof['case']).name
        if week in proofs:
            raise ValueError('Duplicate evidence for week: ' + week)
        proofs[week] = proof
    return proofs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    latest = read(args.report / 'latest.json')
    revision = Path(latest['directory']).resolve()
    if not revision.is_relative_to((args.report / 'revisions').resolve()):
        raise ValueError('Report revision escaped its root')
    manifest = read(revision / 'manifest.json')
    if sha(revision / 'comparison.json') != manifest['comparison.json']:
        raise ValueError('Published comparison changed')
    comparison = read(revision / 'comparison.json')
    rows = comparison['rows']
    if (not latest['complete'] or not comparison['complete']
            or len(rows) != latest['declared'] or len(rows) != latest['included']
            or len(comparison['cases']) != len(rows)
            or len({row['week'] for row in rows}) != len(rows)
            or any(row['git_sha'] != comparison['source_sha'] for row in rows)):
        raise ValueError('Complete declared set required')
    proofs = index_proofs(comparison['evidence'])
    if set(proofs) != {row['week'] for row in rows}:
        raise ValueError('Evidence and included weeks differ')
    periods, summaries = [], []
    for row in comparison['rows']:
        if row['evaluation_status'] != 'VERIFIED_CONDITIONAL_WEEKLY_EVALUATION':
            raise ValueError('Unverified weekly evaluation')
        times, summary = case_evidence(row, proofs[row['week']])
        periods.extend(times)
        summaries.append(summary)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / 'receiving_power_15min.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(periods[0]))
        writer.writeheader()
        writer.writerows(periods)
    payload = {'report_revision': latest['revision'], 'comparison_sha256': manifest['comparison.json'],
               'count': len(summaries), 'new_solver_run': False,
               'scope': 'descriptive_recalculation_not_research_approval', 'weeks': summaries}
    (args.output / 'receiving_power_summary.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'count': len(summaries), 'output': str(args.output), 'new_solver_run': False}))


if __name__ == '__main__':
    main()
