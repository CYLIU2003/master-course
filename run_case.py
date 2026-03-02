#!/usr/bin/env python3
"""
run_case.py — ケース別実験 CLI ハーネス

config/cases/*.json を入力に受け取り、src.pipeline.solve.solve() を呼び出して
10 KPI を抽出・出力する。GUI なしで研究再現に使う最小エントリポイント。

使用方法:
    python run_case.py --case config/cases/mode_A_case01.json
    python run_case.py --case config/cases/mode_B_case01.json
    python run_case.py --case config/cases/mode_A_case01.json --verbose

出力ファイル (results/{case_name}/):
    kpi.json   — 10 KPI 数値
    kpi.csv    — 論文比較用フラット CSV
    report.md  — 実験サマリ Markdown

10 必須 KPI:
    objective_value       : MILP 目的関数値 [円]
    total_energy_cost     : 電力量料金合計 [円]
    total_demand_charge   : デマンド料金合計 [円]
    total_fuel_cost       : ICE 燃料費合計 [円]
    vehicle_fixed_cost    : 使用車両固定費合計 [円]
    unmet_trips           : 未割当タスク数 [件]
    soc_min_margin_kwh    : SOC 下限余裕 (最小 SOC - 下限) [kWh]
    charger_utilization   : 充電器平均稼働率 [0-1]
    peak_grid_power_kw    : 系統ピーク受電電力 [kW]
    solve_time_sec        : ソルバー計算時間 [秒]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent))


# ---------------------------------------------------------------------------
# KPI 抽出
# ---------------------------------------------------------------------------


def _compute_vehicle_fixed_cost(milp_result: Any, dp: Any) -> float:
    """使用された車両の固定費合計 [円] を計算する。"""
    cost = 0.0
    for k, tasks in milp_result.assignment.items():
        if tasks:
            veh = dp.vehicle_lut.get(k)
            if veh is not None:
                cost += getattr(veh, "fixed_use_cost", 0.0)
    return round(cost, 2)


def _compute_soc_min_margin(milp_result: Any, dp: Any) -> float:
    """
    全 BEV 車両の (min SOC - SOC 下限) の最小値 [kWh] を返す。
    マイナスになる場合は SOC 違反を意味する。
    """
    margin = float("inf")
    for k, soc_series in milp_result.soc_series.items():
        veh = dp.vehicle_lut.get(k)
        if veh is None:
            continue
        soc_min_limit = getattr(veh, "soc_min", None) or 0.0
        if soc_series:
            min_soc = min(soc_series)
            margin = min(margin, min_soc - soc_min_limit)
    return round(margin, 4) if margin < float("inf") else 0.0


def _avg_charger_utilization(sim_result: Any) -> float:
    """充電器平均稼働率 [0-1]"""
    util = getattr(sim_result, "charger_utilization", {})
    if not util:
        return 0.0
    return round(sum(util.values()) / len(util), 4)


def extract_kpis(
    milp_result: Any,
    sim_result: Optional[Any],
    dp: Any,
    case_name: str,
    run_mode: str,
) -> Dict[str, Any]:
    """
    solve() の返却値から 10 KPI を抽出して dict で返す。

    sim_result が None の場合はシミュレータ由来の KPI を 0 で埋める。
    """
    obj_val = getattr(milp_result, "objective_value", None)
    solve_t = getattr(milp_result, "solve_time_sec", 0.0)
    status = getattr(milp_result, "status", "UNKNOWN")

    if sim_result is not None:
        energy_cost = getattr(sim_result, "total_energy_cost", 0.0)
        demand_charge = getattr(sim_result, "total_demand_charge", 0.0)
        fuel_cost = getattr(sim_result, "total_fuel_cost", 0.0)
        unmet = len(getattr(sim_result, "unserved_tasks", []))
        peak_kw = getattr(sim_result, "peak_demand_kw", 0.0)
        charger_util = _avg_charger_utilization(sim_result)
    else:
        energy_cost = demand_charge = fuel_cost = 0.0
        unmet = len(getattr(milp_result, "unserved_tasks", []))
        peak_kw = charger_util = 0.0

    vehicle_fixed = _compute_vehicle_fixed_cost(milp_result, dp)
    soc_margin = _compute_soc_min_margin(milp_result, dp)

    return {
        "case_name": case_name,
        "run_mode": run_mode,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        # --- 10 必須 KPI ---
        "objective_value": obj_val,
        "total_energy_cost": energy_cost,
        "total_demand_charge": demand_charge,
        "total_fuel_cost": fuel_cost,
        "vehicle_fixed_cost": vehicle_fixed,
        "unmet_trips": unmet,
        "soc_min_margin_kwh": soc_margin,
        "charger_utilization": charger_util,
        "peak_grid_power_kw": peak_kw,
        "solve_time_sec": round(solve_t, 3),
    }


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------


def save_kpi_json(kpis: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "kpi.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kpis, f, ensure_ascii=False, indent=2)
    return path


def save_kpi_csv(kpis: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "kpi.csv"
    KPI_KEYS = [
        "case_name",
        "run_mode",
        "status",
        "timestamp",
        "objective_value",
        "total_energy_cost",
        "total_demand_charge",
        "total_fuel_cost",
        "vehicle_fixed_cost",
        "unmet_trips",
        "soc_min_margin_kwh",
        "charger_utilization",
        "peak_grid_power_kw",
        "solve_time_sec",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=KPI_KEYS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(kpis)
    return path


def save_report_md(
    kpis: Dict[str, Any], milp_result: Any, sim_result: Optional[Any], out_dir: Path
) -> Path:
    """実験結果サマリを Markdown で保存する。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.md"

    lines = [
        f"# 実験レポート: {kpis['case_name']}",
        f"",
        f"- **モード**: {kpis['run_mode']}",
        f"- **ステータス**: {kpis['status']}",
        f"- **実行日時**: {kpis['timestamp']}",
        f"",
        f"## 10 KPI サマリ",
        f"",
        f"| KPI | 値 | 単位 |",
        f"|-----|-----|------|",
        f"| objective_value | {_fmt(kpis['objective_value'])} | 円 |",
        f"| total_energy_cost | {_fmt(kpis['total_energy_cost'])} | 円 |",
        f"| total_demand_charge | {_fmt(kpis['total_demand_charge'])} | 円 |",
        f"| total_fuel_cost | {_fmt(kpis['total_fuel_cost'])} | 円 |",
        f"| vehicle_fixed_cost | {_fmt(kpis['vehicle_fixed_cost'])} | 円 |",
        f"| unmet_trips | {kpis['unmet_trips']} | 件 |",
        f"| soc_min_margin_kwh | {_fmt(kpis['soc_min_margin_kwh'])} | kWh |",
        f"| charger_utilization | {kpis['charger_utilization']:.2%} | - |",
        f"| peak_grid_power_kw | {_fmt(kpis['peak_grid_power_kw'])} | kW |",
        f"| solve_time_sec | {kpis['solve_time_sec']:.3f} | 秒 |",
    ]

    # 割当サマリ
    if milp_result is not None:
        lines += ["", "## 車両割当サマリ", ""]
        for k, tasks in milp_result.assignment.items():
            lines.append(f"- **{k}**: {', '.join(tasks) if tasks else '(未使用)'}")

    # 未割当タスク
    unserved = []
    if sim_result is not None:
        unserved = getattr(sim_result, "unserved_tasks", [])
    elif milp_result is not None:
        unserved = getattr(milp_result, "unserved_tasks", [])
    if unserved:
        lines += ["", "## 未割当タスク", ""]
        for r in unserved:
            lines.append(f"- {r}")

    # 実行可能性診断
    if sim_result is not None:
        fr = getattr(sim_result, "feasibility_report", None)
        if fr is not None:
            lines += ["", "## 実行可能性診断", "", "```"]
            lines.append(fr.summary())
            lines += ["```"]

    lines += ["", "---", "*Generated by run_case.py*", ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.2f}"


# ---------------------------------------------------------------------------
# CLI 出力
# ---------------------------------------------------------------------------


def print_kpi_table(kpis: Dict[str, Any]) -> None:
    print()
    print(f"{'=' * 56}")
    print(f"  実験結果: {kpis['case_name']} ({kpis['run_mode']})")
    print(f"  ステータス: {kpis['status']}")
    print(f"{'=' * 56}")
    print(f"  {'KPI':<28} {'値':>18}  {'単位'}")
    print(f"  {'-' * 52}")
    rows = [
        ("objective_value", kpis["objective_value"], "円"),
        ("total_energy_cost", kpis["total_energy_cost"], "円"),
        ("total_demand_charge", kpis["total_demand_charge"], "円"),
        ("total_fuel_cost", kpis["total_fuel_cost"], "円"),
        ("vehicle_fixed_cost", kpis["vehicle_fixed_cost"], "円"),
        ("unmet_trips", kpis["unmet_trips"], "件"),
        ("soc_min_margin_kwh", kpis["soc_min_margin_kwh"], "kWh"),
        ("charger_utilization", f"{kpis['charger_utilization']:.2%}", "-"),
        ("peak_grid_power_kw", kpis["peak_grid_power_kw"], "kW"),
        ("solve_time_sec", kpis["solve_time_sec"], "秒"),
    ]
    for label, val, unit in rows:
        if isinstance(val, float):
            val_str = f"{val:>18,.3f}"
        else:
            val_str = f"{val!s:>18}"
        print(f"  {label:<28} {val_str}  {unit}")
    print(f"{'=' * 56}")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="run_case.py — ケース別実験ハーネス (src.pipeline.solve 経由)"
    )
    parser.add_argument(
        "--case",
        required=True,
        help="ケース設定 JSON ファイルパス (例: config/cases/mode_A_case01.json)",
    )
    parser.add_argument(
        "--mode",
        default=None,
        help="ソルバーモード上書き (省略時は config の mode フィールドを使用)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="結果出力先ルート (省略時は results/{case_name}/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Gurobi のログを表示する",
    )
    args = parser.parse_args()

    case_path = Path(args.case)
    if not case_path.exists():
        print(
            f"[ERROR] ケース設定ファイルが見つかりません: {case_path}", file=sys.stderr
        )
        return 1

    case_name = case_path.stem  # e.g. "mode_A_case01"

    # 出力先
    if args.output_dir:
        out_dir = Path(args.output_dir) / case_name
    else:
        out_dir = Path("results") / case_name

    print(f"[run_case] ケース: {case_name}")
    print(f"[run_case] 設定: {case_path}")
    print(f"[run_case] 出力先: {out_dir}")

    # --- モード取得 ---
    with open(case_path, encoding="utf-8") as f:
        cfg = json.load(f)
    run_mode = args.mode or cfg.get("mode", "thesis_mode")
    print(f"[run_case] モード: {run_mode}")

    # --- Gurobi 確認 ---
    try:
        from src.solver_runner import is_gurobi_available

        if not is_gurobi_available():
            print(
                "[ERROR] Gurobi が利用できません。gurobipy をインストールしてください。",
                file=sys.stderr,
            )
            return 1
    except ImportError:
        pass  # solver_runner がなくても続行 (ImportError は solve() 内で検出される)

    # --- Verbose: Gurobi 出力 ON ---
    if args.verbose:
        cfg["solver"] = cfg.get("solver", {})
        cfg["solver"]["verbose"] = True
        import tempfile, os

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(cfg, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        case_path_used = tmp_path
    else:
        tmp_path = None
        case_path_used = str(case_path)

    try:
        # --- ソルバー実行 ---
        from src.pipeline.solve import solve
        from src.data_loader import load_problem_data
        from src.model_sets import build_model_sets
        from src.parameter_builder import build_derived_params

        raw = solve(case_path_used, run_mode)
        milp_result = raw["result"]
        sim_result = raw.get("sim_result")

        # KPI 抽出に dp が必要 → 再ロード (軽量)
        data = load_problem_data(case_path_used)
        ms = build_model_sets(data)
        dp = build_derived_params(data, ms)

        # --- KPI 抽出 ---
        kpis = extract_kpis(milp_result, sim_result, dp, case_name, run_mode)

        # --- 出力 ---
        json_path = save_kpi_json(kpis, out_dir)
        csv_path = save_kpi_csv(kpis, out_dir)
        md_path = save_report_md(kpis, milp_result, sim_result, out_dir)

        # --- 標準出力 ---
        print_kpi_table(kpis)
        print(f"[run_case] 出力完了:")
        print(f"  {json_path}")
        print(f"  {csv_path}")
        print(f"  {md_path}")

        return 0

    except Exception as e:
        print(f"[ERROR] 実行中にエラーが発生しました: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1

    finally:
        if tmp_path and Path(tmp_path).exists():
            import os

            os.unlink(tmp_path)


if __name__ == "__main__":
    sys.exit(main())
