"""Capture the full November Stage 2, then change only its solve-time budget."""
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import pickle
import subprocess
import sys

FROZEN = Path('C:/master-course-worktrees/shibu21-23-monthly-budget-20260914')
OUT = Path('C:/master-course/output/monthly_fair_weeks_20260914/november_budget_diagnosis_20260915')
EXPECTED_SHA = 'fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8'
sys.path.insert(0, str(FROZEN))
import gurobipy as gp
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import solve_week, validate_physical_event_schedule
from src.optimization.engine import OptimizationEngine
from src.optimization.common.result import ResultSerializer
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def save(name, value):
    (OUT / name).write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_state():
    return {key: subprocess.check_output(['git', *args], cwd=FROZEN, text=True).strip()
            for key, args in [('sha', ['rev-parse', 'HEAD']), ('dirty', ['status', '--porcelain'])]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(model):
    def attr(key):
        try:
            return float(getattr(model, key))
        except (AttributeError, gp.GurobiError):
            return None
    return clean_json({
        'status': int(model.Status), 'sol_count': int(model.SolCount),
        'runtime_seconds': attr('Runtime'), 'objective': attr('ObjVal'),
        'bound': attr('ObjBound'), 'gap': attr('MIPGap'),
        'ConstrVio': attr('ConstrVio'), 'BoundVio': attr('BoundVio'), 'IntVio': attr('IntVio'),
        'constraints': int(model.NumConstrs), 'variables': int(model.NumVars), 'binaries': int(model.NumBinVars),
        'params': {key: getattr(model.Params, key) for key in
                   ['TimeLimit', 'MIPGap', 'Seed', 'Threads', 'Aggregate', 'Presolve', 'FeasibilityTol', 'IntFeasTol']},
    })


class DayAheadCaptured(Exception):
    pass


def main():
    OUT.mkdir(exist_ok=False)
    before = source_state()
    assert before == {'sha': EXPECTED_SHA, 'dirty': ''}
    original_stage2 = GurobiMILPAdapter._solve_thesis_stage2_charging_dispatch
    original_optimize = gp.Model.optimize
    original_solve = OptimizationEngine.solve
    calls, captured = [], {}
    active = {'prefix': None}

    def optimize(model, *args, **kwargs):
        prefix = active['prefix']
        if prefix is None or model.ModelName != 'thesis_stage2_charging_dispatch':
            return original_optimize(model, *args, **kwargs)
        assert not args and not kwargs, 'Unexpected production callback'
        model.update()
        model.write(str(OUT / (prefix + '.mps')))
        model.write(str(OUT / (prefix + '.prm')))
        first_incumbent = []

        def callback(m, where):
            if where == gp.GRB.Callback.MIPSOL and not first_incumbent:
                first_incumbent.append(float(m.cbGet(gp.GRB.Callback.RUNTIME)))

        result = original_optimize(model, callback)
        info = snapshot(model)
        info['first_incumbent_seconds'] = first_incumbent[0] if first_incumbent else None
        info['mps_sha256'] = digest(OUT / (prefix + '.mps'))
        captured[prefix] = info
        save(prefix + '.json', info)
        print(json.dumps({'event': prefix, **info}), flush=True)
        return result

    def stage2(self, problem, config, stage1_plan, **kwargs):
        info = {'call': len(calls), 'stage1_status': kwargs['stage1_status'],
                'phase': str(config.phase), 'limit': config.stage2_time_limit_sec,
                'duties': len(stage1_plan.duties)}
        calls.append(info)
        save('stage2_calls.json', calls)
        target = config.stage2_time_limit_sec == 120 and kwargs['stage1_status'] != 'pre_solve_vehicle_local_seed_screen'
        if not target:
            return original_stage2(self, problem, config, stage1_plan, **kwargs)
        assert 'inputs' not in captured, 'Unexpected multiple full Stage 2 calls'
        assert len(stage1_plan.served_trip_ids) == 1704
        import csv
        from collections import defaultdict
        failed_dir = FROZEN / 'output/monthly_budget_campaign_20260914/cases/2025-11-10/diagnostic/2025-11-10/day_ahead_failure_diagnostics'
        rows = list(csv.DictReader((failed_dir / 'stage1_candidate_assignment.csv').open(encoding='utf-8-sig', newline='')))
        expected_paths = defaultdict(list)
        for row in sorted(rows, key=lambda r: (r['vehicle_id'], int(r['fragment_index']), int(r['sequence']))):
            expected_paths[row['vehicle_id']].append(row['trip_id'])
        serialized = ResultSerializer.serialize_plan(stage1_plan)
        actual_paths = {key: list(value) for key, value in serialized['vehicle_paths'].items() if value}
        matches = actual_paths == dict(expected_paths)
        save('failed_assignment_comparison.json', {'identical_vehicle_trip_order': matches,
             'failed_assignment_sha256': digest(failed_dir / 'stage1_candidate_assignment.csv'),
             'expected_vehicles': len(expected_paths), 'actual_vehicles': len(actual_paths)})
        assert matches, 'Fresh Stage 1 differs from failed candidate; do not infer a time-budget cause from a different assignment'
        captured['inputs'] = (problem, config, stage1_plan, kwargs)
        with (OUT / 'stage2_inputs.pkl').open('wb') as stream:
            pickle.dump(captured['inputs'], stream)
        save('stage1_fixed_assignment.json', ResultSerializer.serialize_plan(stage1_plan))
        active['prefix'] = 'full_stage2_120s'
        try:
            return original_stage2(self, problem, config, stage1_plan, **kwargs)
        finally:
            active['prefix'] = None

    def solve(self, problem, config):
        result = original_solve(self, problem, config)
        save('day_ahead_result.json', ResultSerializer.serialize_result(result))
        save('day_ahead_summary.json', {'feasible': result.feasible, 'status': result.solver_status,
                                      'reasons': list(result.infeasibility_reasons)})
        raise DayAheadCaptured()

    design_path = FROZEN / 'output/monthly_budget_campaign_20260914/cases/2025-11-10/design.json'
    design = json.loads(design_path.read_text(encoding='utf-8'))
    GurobiMILPAdapter._solve_thesis_stage2_charging_dispatch = stage2
    gp.Model.optimize = optimize
    OptimizationEngine.solve = solve
    try:
        case = OUT / 'reconstruction'
        case.mkdir()
        solve_week('2025-11-10', case, design)
    except DayAheadCaptured:
        pass
    finally:
        GurobiMILPAdapter._solve_thesis_stage2_charging_dispatch = original_stage2
        OptimizationEngine.solve = original_solve
        gp.Model.optimize = original_optimize
    assert 'inputs' in captured and 'full_stage2_120s' in captured
    assert captured['full_stage2_120s']['constraints'] == 563616, 'Different full assignment/model: review before replay'
    problem, config, plan, kwargs = captured['inputs']
    metadata = {k: v for k, v in problem.metadata.items()
                if k not in {'_stage2_feedback_global_deadline_monotonic', '_stage2_feedback_global_started_monotonic'}}
    metadata['phase3_diagnostics_dir'] = str(OUT / 'replay_failure_diagnostics')
    replay_problem = replace(problem, metadata=metadata)
    replay_config = replace(config, stage2_time_limit_sec=600)
    gp.Model.optimize = optimize
    active['prefix'] = 'full_stage2_600s'
    try:
        outcome, replay_plan = original_stage2(GurobiMILPAdapter(), replay_problem, replay_config, plan, **kwargs)
    finally:
        gp.Model.optimize = original_optimize
        active['prefix'] = None
    save('replay_plan.json', ResultSerializer.serialize_plan(replay_plan))
    report = FeasibilityChecker().evaluate(replay_problem, replay_plan)
    physical = validate_physical_event_schedule(problem=replay_problem, serialized_result=ResultSerializer.serialize_plan(replay_plan)) if outcome.has_feasible_incumbent else None
    after = source_state()
    summary = {'purpose': 'DIAGNOSTIC_BUDGET_CALIBRATION_NOT_WEEKLY_RESULT',
               'source_before': before, 'source_after': after,
               'week': '2025-11-10', 'stage1_duties': len(plan.duties), 'stage1_served_trips': len(plan.served_trip_ids),
               'stage1_objective': kwargs['stage1_objective_value'], 'stage1_status': kwargs['stage1_status'],
               'full_stage2_120s': captured['full_stage2_120s'], 'full_stage2_600s': captured['full_stage2_600s'],
               'identical_native_model_sha256': captured['full_stage2_120s']['mps_sha256'] == captured['full_stage2_600s']['mps_sha256'],
               'replay_feasible': report.feasible, 'replay_errors': list(report.errors),
               'physical_accepted': physical['accepted'] if physical else None}
    save('summary.json', summary)
    if physical:
        save('physical_validation.json', physical)
    assert before == after
    assert summary['identical_native_model_sha256'], 'Model changed beyond parameters'
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
