"""
src.pipeline.solve — 最適化ソルバー実行パイプライン

Usage:
    python -m src.pipeline.solve --config config/experiment_config.json
    python -m src.pipeline.solve --config config/experiment_config.json --mode thesis_mode
    python -m src.pipeline.solve --config config/experiment_config.json --mode mode_milp_only
    python -m src.pipeline.solve --config config/experiment_config.json --mode mode_alns_only
    python -m src.pipeline.solve --config config/experiment_config.json --mode mode_alns_milp

解法モード:
  mode_milp_only  — MILP を直接解く。flags は外部設定で変更可能。
  mode_alns_only  — ALNS で便割当 + 簡易充電を求解。
  mode_alns_milp  — ALNS で割当 → MILP で充電/SOC/電力料金を厳密最適化。
"""

from __future__ import annotations

import argparse
import json
import time as _time
from pathlib import Path
from typing import Any, Dict, Optional


def _load_duty_data(cfg: dict, data: Any, run_mode: str) -> None:
    """行路データを data に注入する (必要な場合)。"""
    duty_cfg = cfg.get("duty_assignment", {})
    if duty_cfg.get("enabled", False) or run_mode == "mode_duty_constrained":
        try:
            from src.preprocess.duty_loader import (
                load_vehicle_duties,
                build_duty_trip_mapping,
            )

            duties_csv = duty_cfg.get(
                "duties_csv_path", "data/fleet/vehicle_duties.csv"
            )
            legs_csv = duty_cfg.get("duty_legs_csv_path", "data/fleet/duty_legs.csv")
            duties = load_vehicle_duties(duties_csv, legs_csv)
            data.duty_assignment_enabled = True
            data.duty_list = duties
            data.duty_trip_mapping = build_duty_trip_mapping(duties)
            data.duty_enforce_depot_match = duty_cfg.get("enforce_depot_match", True)
            data.duty_enforce_vehicle_type_match = duty_cfg.get(
                "enforce_vehicle_type_match", True
            )
            print(f"  duties loaded: {len(duties)}")
        except Exception as e:
            print(f"  [warn] 行路読込スキップ: {e}")


def _report_field(report: Any, key: str, default: Any = None) -> Any:
    if report is None:
        return default
    if isinstance(report, dict):
        return report.get(key, default)
    return getattr(report, key, default)


def _solve_milp_core(
    cfg, data, ms, dp, run_mode, fixed_assignment=None, flag_overrides=None
):
    """MILP モデルを構築して Gurobi で求解する共通ロジック。"""
    from src.model_factory import build_model_by_mode, generate_greedy_assignment
    from src.milp_model import extract_result

    fixed = fixed_assignment
    if run_mode == "mode_A_journey_charge" and fixed is None:
        fixed = generate_greedy_assignment(data, ms, dp)

    model, _vars = build_model_by_mode(
        run_mode,
        data,
        ms,
        dp,
        fixed_assignment=fixed,
        flag_overrides=flag_overrides,
    )
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = cfg.get(
        "time_limit_sec", cfg.get("solver", {}).get("time_limit_sec", 300.0)
    )
    mip_gap = cfg.get("mip_gap", cfg.get("solver", {}).get("mip_gap", 0.01))
    model.Params.MIPGap = mip_gap

    t0 = _time.perf_counter()
    model.optimize()
    elapsed = _time.perf_counter() - t0

    result = extract_result(model, data, ms, dp, _vars, elapsed)
    return result, elapsed


def _solve_alns_core(cfg, data, ms, dp, alns_params=None, callback=None):
    """ALNS メインループを実行する共通ロジック。"""
    from src.solver_alns import solve_alns, ALNSParams

    if alns_params is None:
        alns_cfg = cfg.get("alns", {})
        alns_params = ALNSParams(
            max_iterations=alns_cfg.get("max_iterations", 500),
            max_no_improve=alns_cfg.get("max_no_improve", 100),
            init_temp=alns_cfg.get("init_temp", 1000.0),
            cooling_rate=alns_cfg.get("cooling_rate", 0.995),
            destroy_ratio_min=alns_cfg.get("destroy_ratio_min", 0.1),
            destroy_ratio_max=alns_cfg.get("destroy_ratio_max", 0.4),
            seed=alns_cfg.get("seed", 42),
        )

    result = solve_alns(data, ms, dp, params=alns_params, callback=callback)
    return result, alns_params


def _solve_alns_milp(cfg, data, ms, dp, flag_overrides=None):
    """
    ALNS+MILP ハイブリッド: ALNS で割当 → MILP で充電/SOC を厳密最適化。

    Returns
    -------
    (result, alns_result, milp_result, alns_time, milp_time, alns_params)
    """
    from src.solver_alns import solve_alns, ALNSParams

    # ---- Phase 1: ALNS ----
    alns_cfg = cfg.get("alns", {})
    alns_params = ALNSParams(
        max_iterations=alns_cfg.get("max_iterations", 500),
        max_no_improve=alns_cfg.get("max_no_improve", 100),
        init_temp=alns_cfg.get("init_temp", 1000.0),
        cooling_rate=alns_cfg.get("cooling_rate", 0.995),
        destroy_ratio_min=alns_cfg.get("destroy_ratio_min", 0.1),
        destroy_ratio_max=alns_cfg.get("destroy_ratio_max", 0.4),
        seed=alns_cfg.get("seed", 42),
    )

    t0 = _time.perf_counter()
    alns_result = solve_alns(data, ms, dp, params=alns_params)
    alns_time = _time.perf_counter() - t0

    print(
        f"  [ALNS] status={alns_result.status}, obj={alns_result.objective_value}, "
        f"time={alns_time:.2f}s"
    )

    # ---- Phase 2: MILP (割当固定) ----
    fixed_assignment = alns_result.assignment  # {vehicle_id: [task_id, ...]}

    try:
        from src.model_factory import build_model_by_mode
        from src.milp_model import extract_result

        milp_flags = flag_overrides or {
            "assignment": False,  # x は固定
            "soc": True,
            "charging": True,
            "charger_capacity": True,
            "energy_balance": True,
            "pv_grid": data.enable_pv,
            "battery_degradation": data.enable_battery_degradation,
            "v2g": data.enable_v2g,
            "demand_charge": data.enable_demand_charge,
        }

        model, _vars = build_model_by_mode(
            "mode_A_journey_charge",
            data,
            ms,
            dp,
            fixed_assignment=fixed_assignment,
            flag_overrides=milp_flags,
        )
        model.Params.OutputFlag = 0
        model.Params.TimeLimit = cfg.get(
            "time_limit_sec", cfg.get("solver", {}).get("time_limit_sec", 300.0)
        )
        mip_gap = cfg.get("mip_gap", cfg.get("solver", {}).get("mip_gap", 0.01))
        model.Params.MIPGap = mip_gap

        t1 = _time.perf_counter()
        model.optimize()
        milp_time = _time.perf_counter() - t1

        milp_result = extract_result(model, data, ms, dp, _vars, milp_time)
        print(
            f"  [MILP] status={milp_result.status}, obj={milp_result.objective_value}, "
            f"time={milp_time:.2f}s"
        )

        # コストが改善した場合のみ MILP 解を採用
        alns_obj = alns_result.objective_value or float("inf")
        milp_obj = milp_result.objective_value or float("inf")

        if milp_obj < alns_obj and milp_result.status in (
            "OPTIMAL",
            "TIME_LIMIT",
            "FEASIBLE",
        ):
            print(f"  [ALNS+MILP] MILP 解を採用: {milp_obj:.2f} < {alns_obj:.2f}")
            final_result = milp_result
        else:
            print(
                f"  [ALNS+MILP] ALNS 解を維持: ALNS={alns_obj:.2f}, MILP={milp_obj:.2f}"
            )
            final_result = alns_result
            milp_time = 0.0

    except Exception as e:
        print(f"  [ALNS+MILP] MILP フェーズ失敗、ALNS 解を採用: {e}")
        milp_result = None
        milp_time = 0.0
        final_result = alns_result

    return final_result, alns_result, milp_result, alns_time, milp_time, alns_params


def solve(
    config_path: str = "config/experiment_config.json",
    mode: Optional[str] = None,
) -> dict:
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

    dispatch_report = getattr(data, "_dispatch_preprocess_report", None)
    if dispatch_report is not None:
        vehicle_types = _report_field(dispatch_report, "vehicle_types", tuple())
        print(
            "  [dispatch] "
            f"source={_report_field(dispatch_report, 'source', 'dispatch_graph')}, "
            f"trips={_report_field(dispatch_report, 'trip_count', 0)}, "
            f"edges={_report_field(dispatch_report, 'edge_count', 0)}, "
            f"connections={_report_field(dispatch_report, 'generated_connections', 0)}, "
            f"vehicle_types={list(vehicle_types) if vehicle_types else []}"
        )

    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    t_total_start = _time.perf_counter()
    alns_time = 0.0
    milp_time = 0.0
    method = "MILP"
    alns_params_used = None

    # ================================================================
    # mode_milp_only — MILP を直接解く
    # ================================================================
    if run_mode == "mode_milp_only":
        method = "MILP"
        _load_duty_data(cfg, data, run_mode)
        flag_overrides = cfg.get("milp_flag_overrides", None)
        result, milp_time = _solve_milp_core(
            cfg,
            data,
            ms,
            dp,
            "thesis_mode",
            flag_overrides=flag_overrides,
        )
        print(
            f"  status={result.status}, obj={result.objective_value}, time={milp_time:.2f}s"
        )

    # ================================================================
    # mode_alns_only — ALNS のみ
    # ================================================================
    elif run_mode == "mode_alns_only":
        method = "ALNS"
        result, alns_params_used = _solve_alns_core(cfg, data, ms, dp)
        alns_time = result.solve_time_sec
        print(
            f"  status={result.status}, obj={result.objective_value}, time={alns_time:.2f}s"
        )

    # ================================================================
    # mode_alns_milp — ALNS 割当 → MILP 充電最適化
    # ================================================================
    elif run_mode == "mode_alns_milp":
        method = "ALNS+MILP"
        flag_overrides = cfg.get("milp_flag_overrides", None)
        result, _alns_r, _milp_r, alns_time, milp_time, alns_params_used = (
            _solve_alns_milp(cfg, data, ms, dp, flag_overrides)
        )

    # ================================================================
    # 既存モード (thesis_mode, mode_A, mode_B, etc.)
    # ================================================================
    elif run_mode in (
        "thesis_mode",
        "mode_B_resource_assignment",
        "mode_A_journey_charge",
        "thesis_mode_route_editable",
        "mode_duty_constrained",
    ):
        method = "MILP"
        _load_duty_data(cfg, data, run_mode)
        result, milp_time = _solve_milp_core(cfg, data, ms, dp, run_mode)
        print(
            f"  status={result.status}, obj={result.objective_value}, time={milp_time:.2f}s"
        )

    elif run_mode in ("mode_simple_reproduction", "mode_route_sensitivity"):
        method = "MILP"
        result, milp_time = _solve_milp_core(cfg, data, ms, dp, "thesis_mode")
        print(
            f"  status={result.status}, obj={result.objective_value}, time={milp_time:.2f}s"
        )

    elif run_mode == "mode_uncertainty_eval":
        from src.solver_alns import solve_alns, ALNSParams

        method = "ALNS"
        n_scenarios = cfg.get("uncertainty", {}).get(
            "n_scenarios", cfg.get("n_scenarios", 5)
        )
        results = []
        for i in range(n_scenarios):
            res = solve_alns(data, ms, dp, params=ALNSParams(max_iterations=100))
            results.append(res)
        result = min(results, key=lambda r: r.objective_value or float("inf"))
        alns_time = sum(r.solve_time_sec for r in results)
        print(
            f"  uncertainty: {n_scenarios} scenarios, best obj={result.objective_value}"
        )

    else:
        raise ValueError(f"Unknown mode: {run_mode}")

    total_time = _time.perf_counter() - t_total_start

    # ================================================================
    # シミュレータ検証 (全モード共通)
    # ================================================================
    sim_result = None
    try:
        from src.simulator import simulate

        sim_result = simulate(data, ms, dp, result)
    except Exception as e:
        print(f"  [warn] シミュレータ検証スキップ: {e}")

    # ================================================================
    # outputs/ に保存
    # ================================================================
    out_root = Path(
        cfg.get("output_dir", cfg.get("paths", {}).get("output_dir", "outputs"))
    )

    try:
        from src.result_exporter import export_all

        if sim_result is not None:
            export_all(data, ms, dp, result, sim_result, out_root)
        else:
            _export_minimal(result, out_root)
    except Exception as e:
        print(f"  [warn] エクスポートスキップ: {e}")

    # ================================================================
    # 結果記録 (ExperimentLogger)
    # ================================================================
    try:
        from src.pipeline.logger import ExperimentLogger, record_result

        logger = ExperimentLogger(
            csv_path=out_root / "experiment_log.csv",
            sqlite_path=out_root / "experiment_log.sqlite",
        )
        from src.model_factory import get_mode_flags

        milp_flags = None
        try:
            milp_flags_raw = get_mode_flags(run_mode, data)
            milp_flags = milp_flags_raw if isinstance(milp_flags_raw, dict) else None
        except Exception:
            pass

        record_result(
            logger,
            method=method,
            mode=run_mode,
            milp_result=result,
            sim_result=sim_result,
            data=data,
            ms=ms,
            config_path=config_path,
            alns_params=alns_params_used,
            milp_flags=milp_flags,
            alns_time_sec=alns_time,
            milp_time_sec=milp_time,
            total_time_sec=total_time,
            notes=f"auto-log from pipeline/solve.py mode={run_mode}",
        )
        print(f"  [logger] 実験結果を記録しました")
    except Exception as e:
        print(f"  [warn] ロガー記録スキップ: {e}")

    # ================================================================
    # ギャップ分析 (spec_v3 §9)
    # ================================================================
    if cfg.get("gap_analysis", {}).get("enabled", False) and sim_result is not None:
        try:
            from src.pipeline.gap_analysis import run_gap_analysis, export_gap_report

            gap_report = run_gap_analysis(data, ms, dp, result, sim_result)
            export_gap_report(gap_report, out_root / "gap_analysis.md")
            print(f"  gap analysis: {gap_report.total_issues} issue(s) detected")
        except Exception as e:
            print(f"  [warn] ギャップ分析スキップ: {e}")

    # ================================================================
    # 遅延耐性テスト (spec_v3 §10)
    # ================================================================
    delay_cfg = cfg.get("delay_resilience_test", {})
    if delay_cfg.get("enabled", False):
        try:
            from src.pipeline.delay_resilience import (
                run_delay_resilience_test,
                export_delay_report,
            )

            # duties / trips は route-editable モード時のみ data に存在する
            duties = getattr(data, "duty_list", [])
            trips = getattr(data, "generated_trips", [])
            delay_report = run_delay_resilience_test(
                duties=duties,
                trips=trips,
                n_scenarios=delay_cfg.get("n_scenarios", 10),
                delay_probability=delay_cfg.get("delay_probability", 0.15),
                delay_mean_min=delay_cfg.get("delay_mean_min", 5.0),
                seed=delay_cfg.get("seed", 42),
            )
            export_delay_report(delay_report, out_root / "delay_resilience.md")
            print(f"  delay resilience: {delay_report.n_scenarios} scenarios evaluated")
        except Exception as e:
            print(f"  [warn] 遅延耐性テストスキップ: {e}")

    print(f"[solve] 完了 → {out_root} (total={total_time:.2f}s)")
    return {
        "result": result,
        "sim_result": sim_result,
        "method": method,
        "dispatch_preprocess": dispatch_report,
    }


def _export_minimal(result, out_root):
    """SimulationResult なしで最低限の結果を保存する。"""
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    run_dir = Path(out_root) / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": result.status,
        "objective_value": result.objective_value,
        "solve_time_sec": result.solve_time_sec,
        "mip_gap": result.mip_gap,
        "n_unserved": len(result.unserved_tasks),
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="solve — 最適化パイプライン")
    parser.add_argument("--config", default="config/experiment_config.json")
    parser.add_argument(
        "--mode",
        default=None,
        choices=[
            "mode_milp_only",
            "mode_alns_only",
            "mode_alns_milp",
            "thesis_mode",
            "mode_A_journey_charge",
            "mode_B_resource_assignment",
            "thesis_mode_route_editable",
            "mode_duty_constrained",
            "mode_simple_reproduction",
            "mode_route_sensitivity",
            "mode_uncertainty_eval",
        ],
    )
    parser.add_argument(
        "--time-limit", type=float, default=None, help="ソルバー制限時間 [秒]"
    )
    args = parser.parse_args()

    if args.time_limit is not None:
        cfg_path = Path(args.config)
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["time_limit_sec"] = args.time_limit
        import tempfile, os

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(cfg, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        try:
            solve(tmp_path, args.mode)
        finally:
            os.unlink(tmp_path)
    else:
        solve(args.config, args.mode)


if __name__ == "__main__":
    main()
