#!/usr/bin/env python3
"""
run_experiment.py — 修論実験エントリポイント

仕様書 §18.1 に準じた実行例:

    python run_experiment.py

    python run_experiment.py \\
        --config config/experiment_config.json \\
        --time-limit 300 \\
        --verbose

    python run_experiment.py \\
        --config config/experiment_config.json \\
        --no-pv --no-demand-charge

オプション引数で設定を上書きできる。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# src/ をパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from src.data_loader import load_problem_data
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params
from src.solver_runner import is_gurobi_available, run_milp_from_data
from src.simulator import simulate
from src.result_exporter import export_all
from src.visualization import save_all_plots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="電気バス運行・充電スケジューリング最適化 (仕様書 §18.1)"
    )
    parser.add_argument(
        "--config",
        default="config/experiment_config.json",
        help="設定ファイルパス (デフォルト: config/experiment_config.json)",
    )
    parser.add_argument("--time-limit", type=float, default=300.0, help="Gurobi 制限時間 [秒]")
    parser.add_argument("--mip-gap",    type=float, default=0.01,  help="MIP ギャップ")
    parser.add_argument("--threads",    type=int,   default=0,     help="スレッド数 (0=自動)")
    parser.add_argument("--verbose",    action="store_true",       help="Gurobi ログを表示")
    parser.add_argument("--no-pv",      action="store_true",       help="PV を無効化")
    parser.add_argument("--no-demand-charge", action="store_true", help="デマンド料金を無効化")
    parser.add_argument("--soft-soc",   action="store_true",       help="SOC 制約を soft に")
    parser.add_argument("--allow-partial", action="store_true",    help="部分充足を許可")
    parser.add_argument("--output-dir", default="outputs",         help="出力ルートディレクトリ")
    parser.add_argument("--label",      default=None,              help="実験ラベル")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not is_gurobi_available():
        print("[ERROR] Gurobi が利用できません。gurobipy をインストールしてください。")
        sys.exit(1)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] 設定ファイルが見つかりません: {config_path}")
        sys.exit(1)

    print(f"[INFO] 設定ファイル: {config_path}")

    # --- データ読込 ---
    print("[INFO] データを読み込み中...")
    data = load_problem_data(config_path)

    # CLI 引数で上書き
    if args.no_pv:
        data.enable_pv = False
    if args.no_demand_charge:
        data.enable_demand_charge = False
    if args.soft_soc:
        data.use_soft_soc_constraint = True
    if args.allow_partial:
        data.allow_partial_service = True

    print(f"  車両: BEV {0}, ICE {0} (集合構築後に確定)")

    # --- 集合・派生パラメータ ---
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    print(f"  車両: BEV {len(ms.K_BEV)} 台 / ICE {len(ms.K_ICE)} 台")
    print(f"  タスク: {len(ms.R)} 件")
    print(f"  充電器: {len(ms.C)} 基")
    print(f"  時間スロット: {data.num_periods} ({data.delta_t_min:.0f} 分刻み)")

    # --- MILP 求解 ---
    print("[INFO] MILP を求解中...")
    result = run_milp_from_data(
        data=data,
        ms=ms,
        dp=dp,
        time_limit_sec=args.time_limit,
        mip_gap=args.mip_gap,
        threads=args.threads,
        verbose=args.verbose,
    )

    print(f"[INFO] ステータス: {result.status}")
    if result.objective_value is not None:
        print(f"[INFO] 目的関数値: {result.objective_value:.2f} 円")
    if result.solve_time_sec:
        print(f"[INFO] 計算時間: {result.solve_time_sec:.2f} 秒")
    if result.unserved_tasks:
        print(f"[WARN] 未割当タスク: {result.unserved_tasks}")
    if result.infeasibility_info:
        print(f"[WARN] infeasible 情報: {result.infeasibility_info}")

    # --- シミュレーション評価 ---
    print("[INFO] シミュレーション評価中...")
    sim = simulate(data, ms, dp, result)

    # --- 出力 ---
    print("[INFO] 結果を出力中...")
    run_dir = export_all(
        data=data, ms=ms, dp=dp,
        milp_result=result,
        sim_result=sim,
        output_root=args.output_dir,
        run_label=args.label,
    )
    save_all_plots(run_dir, ms, dp, result, sim, data)

    print(f"[INFO] 出力完了: {run_dir}")
    print()
    print("===== 結果サマリー =====")
    print(f"  タスク担当率 : {sim.served_task_ratio * 100:.1f} %")
    print(f"  系統受電量   : {sim.total_grid_kwh:.2f} kWh")
    print(f"  電力量料金   : {sim.total_energy_cost:,.0f} 円")
    print(f"  燃料費       : {sim.total_fuel_cost:,.0f} 円")
    print(f"  デマンド料金 : {sim.total_demand_charge:,.0f} 円")
    print(f"  総コスト     : {sim.total_operating_cost:,.0f} 円")
    print(f"  SOC 最低値   : {sim.soc_min_kwh:.2f} kWh")
    print(f"  SOC 違反     : {len(sim.soc_violations)} 件")


if __name__ == "__main__":
    main()
