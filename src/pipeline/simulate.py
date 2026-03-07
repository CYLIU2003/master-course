"""
src.pipeline.simulate — シミュレーション評価パイプライン

solve の出力した MILPResult を受け取り、SOC / 電力 / 費用 / 実行可能性を検証する。

Usage:
    python -m src.pipeline.simulate --config config/experiment_config.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def simulate_from_outputs(config_path: str = "config/experiment_config.json") -> dict:
    """outputs/latest/summary.json を読み込んでシミュレーション評価を行う。"""
    cfg_path = Path(config_path)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    print(f"[simulate] config={config_path}")

    from src.data_loader import load_problem_data
    from src.model_sets import build_model_sets
    from src.parameter_builder import build_derived_params
    from src.model_factory import build_model_by_mode, generate_greedy_assignment
    from src.milp_model import extract_result
    from src.simulator import simulate
    import time as _time

    mode = cfg.get("mode", "thesis_mode")
    data = load_problem_data(config_path)
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    fixed = None
    if mode == "mode_A_journey_charge":
        fixed = generate_greedy_assignment(data, ms, dp)
    model, _vars = build_model_by_mode(mode, data, ms, dp, fixed_assignment=fixed)
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = cfg.get("time_limit_sec", 120.0)
    t0 = _time.perf_counter()
    model.optimize()
    elapsed = _time.perf_counter() - t0
    result = extract_result(model, data, ms, dp, _vars, elapsed)

    sim = simulate(data, ms, dp, result)

    print(f"  status          : {result.status}")
    print(f"  objective       : {result.objective_value}")
    print(f"  served_ratio    : {sim.served_task_ratio:.1%}")
    print(f"  total_cost      : ¥{sim.total_operating_cost:,.0f}")
    print(f"  soc_violations  : {len(sim.soc_violations)}")
    if sim.feasibility_report:
        print(f"  feasibility     : {sim.feasibility_report.summary()}")

    return {"result": result, "sim": sim}


def main():
    parser = argparse.ArgumentParser(description="simulate — シミュレーション評価")
    parser.add_argument("--config", default="config/experiment_config.json")
    args = parser.parse_args()
    simulate_from_outputs(args.config)


if __name__ == "__main__":
    main()
