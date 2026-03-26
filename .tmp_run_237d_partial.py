import json
from pathlib import Path
from bff.services.run_preparation import materialize_scenario_from_prepared_input
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from src.pipeline.solve import solve_problem_data
from src.optimization.common.result import ResultSerializer

sid = '237d5623-aa94-4f72-9da1-17b9070264be'
prep_path = sorted((Path('output/prepared_inputs')/sid).glob('prepared-*.json'), key=lambda p:p.stat().st_mtime)[-1]
prep = json.loads(prep_path.read_text(encoding='utf-8'))
scenario = materialize_scenario_from_prepared_input({'id': sid, 'meta': {'id': sid}}, prep)
scenario.setdefault('simulation_config', {})
scenario.setdefault('scenario_overlay', {})
scenario['simulation_config']['disable_vehicle_acquisition_cost'] = True
scenario['simulation_config']['objective_mode'] = 'total_cost'
scenario['simulation_config']['allow_partial_service'] = True
solver_cfg = scenario['scenario_overlay'].setdefault('solver_config', {})
solver_cfg['objective_mode'] = 'total_cost'
solver_cfg['mode'] = 'mode_milp_only'
scope = prep.get('scope') or {}
service_id = (scope.get('service_ids') or [None])[0]
depot_id = (scope.get('depot_ids') or [None])[0]
data, report = build_problem_data_from_scenario(scenario, depot_id=depot_id, service_id=service_id, mode='mode_milp_only', use_existing_duties=False, analysis_scope=scenario.get('dispatch_scope'))
setattr(data, 'allow_partial_service', True)
res = solve_problem_data(data, mode='mode_milp_only', time_limit_seconds=300, mip_gap=0.01, random_seed=42, output_dir='output/tmp_direct_milp_237d_partial')
payload = ResultSerializer.serialize_result(res['result'])
summary = {
  'prepared': str(prep_path),
  'solver_status': payload.get('solver_status'),
  'objective_mode': payload.get('objective_mode'),
  'feasible': payload.get('feasible'),
  'unserved': len(payload.get('unserved_trip_ids') or []),
  'served': len(payload.get('served_trip_ids') or []),
  'warnings': payload.get('warnings'),
  'infeasibility_reasons': payload.get('infeasibility_reasons'),
}
Path('output/tmp_direct_milp_237d_partial/summary.json').parent.mkdir(parents=True, exist_ok=True)
Path('output/tmp_direct_milp_237d_partial/summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
