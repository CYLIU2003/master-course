import json
from pathlib import Path
from bff.services.run_preparation import materialize_scenario_from_prepared_input
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from src.pipeline.solve import solve_problem_data
from src.optimization.common.result import ResultSerializer

sid = '237d5623-aa94-4f72-9da1-17b9070264be'
prep_dir = Path('output/prepared_inputs')/sid
files = sorted(prep_dir.glob('prepared-*.json'), key=lambda p: p.stat().st_mtime)
if not files:
    raise SystemExit('prepared input not found')
prep_path = files[-1]
prep = json.loads(prep_path.read_text(encoding='utf-8'))

base = {'id': sid, 'meta': {'id': sid}}
scenario = materialize_scenario_from_prepared_input(base, prep)
scenario.setdefault('simulation_config', {})
scenario.setdefault('scenario_overlay', {})
scenario['simulation_config']['disable_vehicle_acquisition_cost'] = True
scenario['simulation_config']['objective_mode'] = 'total_cost'
solver_cfg = scenario['scenario_overlay'].setdefault('solver_config', {})
solver_cfg['objective_mode'] = 'total_cost'
solver_cfg['mode'] = 'mode_milp_only'

scope = prep.get('scope') or {}
service_ids = scope.get('service_ids') or []
depot_ids = scope.get('depot_ids') or []
service_id = service_ids[0] if service_ids else None
depot_id = depot_ids[0] if depot_ids else None

data, report = build_problem_data_from_scenario(
    scenario,
    depot_id=depot_id,
    service_id=service_id,
    mode='mode_milp_only',
    use_existing_duties=False,
    analysis_scope=scenario.get('dispatch_scope')
)
res = solve_problem_data(
    data,
    mode='mode_milp_only',
    time_limit_seconds=300,
    mip_gap=0.01,
    random_seed=42,
    output_dir='output/tmp_direct_milp_237d'
)
payload = ResultSerializer.serialize_result(res['result'])
print('prepared=', prep_path)
print('solver_status=', payload.get('solver_status'))
print('objective_mode=', payload.get('objective_mode'))
print('feasible=', payload.get('feasible'))
print('unserved=', len(payload.get('unserved_trip_ids') or []))
print('served=', len(payload.get('served_trip_ids') or []))
print('warnings=', payload.get('warnings'))
print('infeasibility_reasons=', payload.get('infeasibility_reasons'))
print('build_report=', report.to_dict())
