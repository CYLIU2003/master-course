"""
src.pipeline.sensitivity_runner — 感度分析パラメトリックスイープ

spec_v3 §8.2: route_length_multiplier / headway / energy_model_level を
系統的にスイープし、各条件での最適化結果を収集する。

Usage:
    python -m src.pipeline.sensitivity_runner --config config/test_route_sensitivity.json
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dataclasses import dataclass, field


@dataclass
class SensitivityCase:
    """1 つの感度スイープケース"""
    case_id: str
    parameter_name: str
    parameter_value: float
    objective_value: Optional[float] = None
    status: str = ""
    solve_time_sec: float = 0.0
    vehicles_used: int = 0
    unserved_tasks: int = 0
    total_energy_kwh: float = 0.0
    peak_demand_kw: float = 0.0
    gap_issues: int = 0
    extra_kpi: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SensitivityReport:
    """感度分析結果レポート"""
    parameter_name: str
    cases: List[SensitivityCase] = field(default_factory=list)
    base_case_id: Optional[str] = None

    @property
    def n_cases(self) -> int:
        return len(self.cases)

    def best_case(self) -> Optional[SensitivityCase]:
        feasible = [c for c in self.cases if c.objective_value is not None]
        if not feasible:
            return None
        return min(feasible, key=lambda c: c.objective_value)


def run_parameter_sweep(
    config_path: str,
    parameter_name: str = "route_length_multiplier",
    values: Optional[List[float]] = None,
) -> SensitivityReport:
    """
    指定パラメータを values のリストでスイープし各ケースを求解する。

    Parameters
    ----------
    config_path    : ベース設定ファイル
    parameter_name : スイープ対象パラメータ名
    values         : パラメータ値のリスト (None → config から読み取り)

    Returns
    -------
    SensitivityReport
    """
    cfg_path = Path(config_path)
    with open(cfg_path, encoding="utf-8") as f:
        base_cfg = json.load(f)

    # values の決定
    if values is None:
        sens_cfg = base_cfg.get("sensitivity", {})
        values = sens_cfg.get("multipliers", [0.8, 0.9, 1.0, 1.1, 1.2, 1.5])

    report = SensitivityReport(parameter_name=parameter_name)
    print(f"[sensitivity] parameter={parameter_name}, {len(values)} cases")

    for i, val in enumerate(values):
        case_id = f"{parameter_name}_{val:.2f}"
        case = SensitivityCase(case_id=case_id, parameter_name=parameter_name, parameter_value=val)

        if val == 1.0:
            report.base_case_id = case_id

        # 設定のコピーとパラメータ上書き
        cfg = copy.deepcopy(base_cfg)
        cfg[parameter_name] = val

        # 一時 config ファイル書き出し
        tmp_cfg_path = cfg_path.parent / f"_tmp_sens_{i}.json"
        with open(tmp_cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        try:
            from src.data_loader import load_problem_data
            from src.model_sets import build_model_sets
            from src.parameter_builder import build_derived_params
            from src.model_factory import build_model_by_mode

            data = load_problem_data(str(tmp_cfg_path))

            # route_length_multiplier はタスクの距離に直接適用
            if parameter_name == "route_length_multiplier" and val != 1.0:
                for task in data.tasks:
                    task.distance_km *= val
                    task.energy_required_kwh_bev *= val

            ms = build_model_sets(data)
            dp = build_derived_params(data, ms)

            mode = cfg.get("mode", "thesis_mode")
            model, vars_ = build_model_by_mode(mode, data, ms, dp)
            model.Params.OutputFlag = 0
            model.Params.TimeLimit = cfg.get("solver", {}).get("time_limit_sec", 300)

            t0 = time.perf_counter()
            model.optimize()
            elapsed = time.perf_counter() - t0

            from src.milp_model import extract_result
            result = extract_result(model, data, ms, dp, vars_, elapsed)

            case.status = result.status
            case.objective_value = result.objective_value
            case.solve_time_sec = elapsed
            case.vehicles_used = len(result.assignment)
            case.unserved_tasks = len(result.unserved_tasks)
            case.total_energy_kwh = sum(
                sum(series) for series_dict in result.charge_power_kw.values()
                for series in series_dict.values()
            ) * data.delta_t_hour
            case.peak_demand_kw = max(result.peak_demand_kw.values()) if result.peak_demand_kw else 0.0

            print(f"  [{i+1}/{len(values)}] {case_id}: obj={case.objective_value:.0f}, "
                  f"vehicles={case.vehicles_used}, time={elapsed:.1f}s")

        except Exception as e:
            case.status = f"ERROR: {e}"
            print(f"  [{i+1}/{len(values)}] {case_id}: ERROR - {e}")

        finally:
            # 一時ファイル削除
            if tmp_cfg_path.exists():
                tmp_cfg_path.unlink()

        report.cases.append(case)

    return report


def export_sensitivity_csv(report: SensitivityReport, out_path: Path):
    """感度分析結果を CSV に書き出す。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id", "parameter_name", "parameter_value",
        "status", "objective_value", "solve_time_sec",
        "vehicles_used", "unserved_tasks", "total_energy_kwh", "peak_demand_kw",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for case in report.cases:
            writer.writerow({
                "case_id": case.case_id,
                "parameter_name": case.parameter_name,
                "parameter_value": case.parameter_value,
                "status": case.status,
                "objective_value": case.objective_value,
                "solve_time_sec": round(case.solve_time_sec, 2),
                "vehicles_used": case.vehicles_used,
                "unserved_tasks": case.unserved_tasks,
                "total_energy_kwh": round(case.total_energy_kwh, 2),
                "peak_demand_kw": round(case.peak_demand_kw, 2),
            })
    print(f"  → sensitivity CSV: {out_path}")


def export_sensitivity_report_md(report: SensitivityReport, out_path: Path):
    """感度分析結果を Markdown レポートに書き出す。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 感度分析レポート: {report.parameter_name}",
        "",
        f"ケース数: {report.n_cases}",
        "",
        "## 結果一覧",
        "",
        "| ケース | 値 | 目的関数 | 車両数 | 未担当 | 計算時間(s) |",
        "|---|---|---|---|---|---|",
    ]
    for case in report.cases:
        obj_str = f"{case.objective_value:,.0f}" if case.objective_value is not None else "N/A"
        base_mark = " (base)" if case.case_id == report.base_case_id else ""
        lines.append(
            f"| {case.case_id}{base_mark} | {case.parameter_value:.2f} | "
            f"{obj_str} | {case.vehicles_used} | {case.unserved_tasks} | "
            f"{case.solve_time_sec:.1f} |"
        )

    # 変化率
    base = next((c for c in report.cases if c.case_id == report.base_case_id), None)
    if base and base.objective_value:
        lines.extend(["", "## ベースケースからの変化率", ""])
        lines.append("| ケース | 値 | 目的関数変化率 |")
        lines.append("|---|---|---|")
        for case in report.cases:
            if case.objective_value is not None:
                pct = (case.objective_value - base.objective_value) / base.objective_value * 100
                lines.append(f"| {case.case_id} | {case.parameter_value:.2f} | {pct:+.1f}% |")

    best = report.best_case()
    if best:
        lines.extend([
            "",
            f"## 最良ケース: {best.case_id}",
            f"- 目的関数: {best.objective_value:,.0f}",
            f"- 車両数: {best.vehicles_used}",
            f"- 計算時間: {best.solve_time_sec:.1f}s",
        ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  → sensitivity report: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="sensitivity_runner — パラメトリックスイープ実行")
    parser.add_argument("--config", default="config/test_route_sensitivity.json")
    parser.add_argument("--param", default="route_length_multiplier", help="スイープ対象パラメータ")
    parser.add_argument("--values", nargs="*", type=float, default=None, help="パラメータ値リスト")
    args = parser.parse_args()

    report = run_parameter_sweep(args.config, args.param, args.values)

    # 出力
    out_dir = Path("outputs/sensitivity")
    export_sensitivity_csv(report, out_dir / f"{args.param}_results.csv")
    export_sensitivity_report_md(report, out_dir / f"{args.param}_report.md")


if __name__ == "__main__":
    main()
