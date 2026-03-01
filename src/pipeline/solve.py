"""
src.pipeline.solve — 最適化ソルバー実行パイプライン

Usage:
    python -m src.pipeline.solve --config config/experiment_config.json
    python -m src.pipeline.solve --config config/experiment_config.json --mode thesis_mode
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def solve(config_path: str = "config/experiment_config.json", mode: str = None) -> dict:
    """
    config に基づいてソルバーを実行し、raw solution を outputs/ に保存する。
    """
    cfg_path = Path(config_path)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    run_mode = mode or cfg.get("mode", "thesis_mode")
    print(f"[solve] mode={run_mode}")

    from src.data_loader import load_problem_data
    from src.model_sets import build_model_sets
    from src.parameter_builder import build_derived_params

    data = load_problem_data(config_path)
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    # mode ディスパッチ
    if run_mode in ("thesis_mode", "mode_B_resource_assignment", "mode_A_journey_charge"):
        from src.model_factory import build_model_by_mode, generate_greedy_assignment
        import time as _time

        fixed = None
        if run_mode == "mode_A_journey_charge":
            fixed = generate_greedy_assignment(data, ms, dp)

        model, _vars = build_model_by_mode(run_mode, data, ms, dp, fixed_assignment=fixed)
        model.Params.OutputFlag = 0
        model.Params.TimeLimit = cfg.get("time_limit_sec", 300.0)
        t0 = _time.perf_counter()
        model.optimize()
        elapsed = _time.perf_counter() - t0

        from src.milp_model import extract_result
        result = extract_result(model, data, ms, dp, _vars, elapsed)
        print(f"  status={result.status}, obj={result.objective_value}, time={elapsed:.2f}s")

    elif run_mode in ("mode_simple_reproduction", "mode_route_sensitivity"):
        # 旧互換モード: toy CSV がない場合は thesis_mode にフォールバック
        from src.model_factory import build_model_by_mode
        import time as _time
        model, _vars = build_model_by_mode("thesis_mode", data, ms, dp)
        model.Params.OutputFlag = 0
        model.Params.TimeLimit = cfg.get("time_limit_sec", 300.0)
        t0 = _time.perf_counter()
        model.optimize()
        elapsed = _time.perf_counter() - t0
        from src.milp_model import extract_result
        result = extract_result(model, data, ms, dp, _vars, elapsed)
        print(f"  status={result.status}, obj={result.objective_value}, time={elapsed:.2f}s")

    elif run_mode == "mode_uncertainty_eval":
        # ALNS で複数 scenario を求解（簡易実装）
        from src.solver_alns import solve_alns, ALNSParams
        n_scenarios = cfg.get("n_scenarios", 5)
        results = []
        for i in range(n_scenarios):
            res = solve_alns(data, ms, dp, params=ALNSParams(max_iterations=100))
            results.append(res)
        # 最良を result に
        result = min(results, key=lambda r: r.objective_value or float("inf"))
        print(f"  uncertainty: {n_scenarios} scenarios, best obj={result.objective_value}")

    else:
        raise ValueError(f"Unknown mode: {run_mode}")

    # outputs/ に保存
    from src.result_exporter import export_all
    out_root = Path(cfg.get("output_dir", "outputs"))
    export_all(result, data, ms, dp, out_root)
    print(f"[solve] 完了 → {out_root}")
    return {"result": result}


def main():
    parser = argparse.ArgumentParser(description="solve — 最適化パイプライン")
    parser.add_argument("--config", default="config/experiment_config.json")
    parser.add_argument("--mode", default=None)
    args = parser.parse_args()
    solve(args.config, args.mode)


if __name__ == "__main__":
    main()
