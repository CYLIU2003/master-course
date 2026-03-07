"""
src.pipeline.report — KPI レポート生成パイプライン

spec_v3 §12 / agent_route_editable §5 (report の責務)

Usage:
    python -m src.pipeline.report --config config/experiment_config.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional


def generate_report(config_path: str = "config/experiment_config.json") -> str:
    """
    outputs/ の結果から KPI レポート (Markdown) を生成して返す。

    Reports (spec_v3 §5 / agent_route_editable §5):
        - KPI 表
        - powertrain 比較 (BEV vs ICE)
        - route sensitivity 比較
        - scenario robustness 比較
    """
    cfg_path = Path(config_path)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    print(f"[report] config={config_path}")

    # ---- 求解 + シミュレーション ----
    from src.data_loader import load_problem_data
    from src.model_sets import build_model_sets
    from src.parameter_builder import build_derived_params
    from src.model_factory import build_model_by_mode, generate_greedy_assignment, AVAILABLE_MODES
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

    lines: List[str] = []
    lines.append(f"# E-Bus Simulation Report")
    lines.append(f"\nmode: `{mode}` | status: `{result.status}` | time: {elapsed:.2f}s\n")

    # --- KPI 表 ---
    lines.append("## KPI サマリ\n")
    lines.append("| 指標 | 値 | 単位 |")
    lines.append("|---|---|---|")
    lines.append(f"| 目的関数値 | {result.objective_value:,.1f} | 円 |")
    lines.append(f"| 計算時間 | {elapsed:.2f} | 秒 |")
    lines.append(f"| タスク担当率 | {sim.served_task_ratio:.1%} | - |")
    lines.append(f"| 総運行コスト | {sim.total_operating_cost:,.0f} | 円 |")
    lines.append(f"| 電力量料金 | {sim.total_energy_cost:,.0f} | 円 |")
    lines.append(f"| デマンド料金 | {sim.total_demand_charge:,.0f} | 円 |")
    lines.append(f"| 電池劣化コスト | {sim.total_degradation_cost:,.0f} | 円 |")
    lines.append(f"| 系統受電量 | {sim.total_grid_kwh:.1f} | kWh |")
    lines.append(f"| PV 利用量 | {sim.total_pv_kwh:.1f} | kWh |")
    lines.append(f"| SOC 最低値 | {sim.soc_min_kwh:.1f} | kWh |")
    lines.append(f"| SOC 違反 | {len(sim.soc_violations)} | 件 |")
    lines.append(f"| 未担当タスク | {len(sim.unserved_tasks)} | 件 |")
    lines.append("")

    # --- powertrain 比較 ---
    lines.append("## パワートレイン比較\n")
    bev_count = len(ms.K_BEV) if hasattr(ms, "K_BEV") else 0
    ice_count = len(ms.K_ICE) if hasattr(ms, "K_ICE") else 0
    lines.append(f"| タイプ | 台数 |")
    lines.append(f"|---|---|")
    lines.append(f"| BEV | {bev_count} |")
    lines.append(f"| ICE | {ice_count} |")
    lines.append(f"\n- BEV 消費電力: {sim.total_grid_kwh:.1f} kWh")
    lines.append(f"- ICE 燃料消費: {sim.total_fuel_cost / 145.0:.1f} L (¥145/L 換算)")
    lines.append(f"- CO₂ 排出: {sim.total_co2_kg:.2f} kg")
    lines.append("")

    # --- route / trip KPI (spec_v3 §12) ---
    lines.append("## Route / Trip KPI\n")
    lines.append(f"| 指標 | 値 | 単位 |")
    lines.append("|---|---|---|")
    total_tasks = len(ms.R)
    served = sum(len(v) for v in result.assignment.values())
    unserved = total_tasks - served
    lines.append(f"| 総タスク数 | {total_tasks} | 件 |")
    lines.append(f"| 担当済みタスク | {served} | 件 |")
    lines.append(f"| 未担当タスク | {unserved} | 件 |")
    lines.append(f"| 低 SOC 違反 | {len(sim.soc_violations)} | 件 |")
    lines.append("")

    # --- feasibility report ---
    if sim.feasibility_report:
        lines.append("## 実行可能性診断\n")
        lines.append("```")
        lines.append(sim.feasibility_report.summary())
        lines.append("```\n")

    report_md = "\n".join(lines)

    # 出力
    out_dir = Path(cfg.get("output_dir", "outputs"))
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"[report] → {report_path}")

    return report_md


def main():
    parser = argparse.ArgumentParser(description="report — KPI レポート生成")
    parser.add_argument("--config", default="config/experiment_config.json")
    args = parser.parse_args()
    print(generate_report(args.config))


if __name__ == "__main__":
    main()
