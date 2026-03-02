"""
pipeline_bridge.py — GUI → src.pipeline.* アダプター

GUI から src.pipeline.* を呼び出すための薄いラッパー。
GUI も CLI も同じ ExperimentConfig (JSON) を通じて同じパイプラインを呼ぶことを保証する。

原則 (advisor.md より):
  - GUI は src.pipeline.solve / simulate / report を「呼ぶだけ」
  - GUI 上で編集した内容は JSON / CSV に保存し、それを pipeline に渡す
  - GUI 側にソルバーロジックを持たない
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# ケース一覧
# ---------------------------------------------------------------------------


def list_cases() -> List[Tuple[str, Path]]:
    """
    config/cases/ にある実験ケースの一覧を返す。

    Returns
    -------
    [(case_name, config_path), ...]
    """
    cases_dir = ROOT / "config" / "cases"
    if not cases_dir.exists():
        return []
    return [(p.stem, p) for p in sorted(cases_dir.glob("*.json"))]


def load_config_meta(config_path: str) -> Dict[str, Any]:
    """設定ファイルのメタ情報を返す (mode, paths セクション等)。"""
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# パイプライン実行 (src.pipeline.solve を呼ぶだけ)
# ---------------------------------------------------------------------------


def run_solve(
    config_path: str,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    src.pipeline.solve.solve() を実行する。

    Parameters
    ----------
    config_path : str
        ExperimentConfig JSON のパス
    mode : str or None
        モード上書き。None の場合は設定ファイルの値を使用。

    Returns
    -------
    {"result": MILPResult, "sim_result": SimulationResult | None, "method": str}
    """
    from src.pipeline.solve import solve

    return solve(config_path, mode)


# ---------------------------------------------------------------------------
# 10 KPI 正規化
# ---------------------------------------------------------------------------


def extract_10_kpis(
    milp_result: Any,
    sim_result: Optional[Any],
) -> Dict[str, Any]:
    """
    論文再現仕様の 10 KPI を正規化して返す。

    KPI 定義 (agent.md §4 / reproduction_spec.md):
      1.  objective_value      目的関数値 [円]
      2.  total_energy_cost    電力量料金 [円]
      3.  total_demand_charge  デマンド料金 [円]
      4.  total_fuel_cost      燃料費 [円]
      5.  vehicle_fixed_cost   車両固定費 [円]  (未実装時 None)
      6.  unmet_trips          未割当タスク数
      7.  soc_min_margin_kwh   最低 SOC [kWh]
      8.  charger_utilization  充電器平均利用率 [0-1]
      9.  peak_grid_power_kw   ピーク受電電力 [kW]
      10. solve_time_sec       求解時間 [秒]
    """
    unmet = milp_result.unserved_tasks or []

    if sim_result is not None:
        total_energy = sim_result.total_energy_cost
        total_demand = sim_result.total_demand_charge
        total_fuel = sim_result.total_fuel_cost
        soc_min = sim_result.soc_min_kwh
        peak_kw = sim_result.peak_demand_kw
        charger_util_dict = sim_result.charger_utilization or {}
        avg_charger_util = (
            sum(charger_util_dict.values()) / len(charger_util_dict)
            if charger_util_dict
            else 0.0
        )
    else:
        total_energy = None
        total_demand = None
        total_fuel = None
        soc_min = None
        peak_kw = None
        avg_charger_util = None

    return {
        "objective_value": milp_result.objective_value,
        "total_energy_cost": total_energy,
        "total_demand_charge": total_demand,
        "total_fuel_cost": total_fuel,
        "vehicle_fixed_cost": None,
        "unmet_trips": len(unmet),
        "soc_min_margin_kwh": soc_min,
        "charger_utilization": round(avg_charger_util, 4)
        if avg_charger_util is not None
        else None,
        "peak_grid_power_kw": peak_kw,
        "solve_time_sec": milp_result.solve_time_sec,
    }


# ---------------------------------------------------------------------------
# グラフ用データ変換ヘルパー
# ---------------------------------------------------------------------------


def build_charger_totals(milp_result: Any) -> Dict[str, List[float]]:
    """
    充電器ごとの同時稼働台数時系列を返す。

    Returns
    -------
    {charger_id: [台数, ...], ...}
    """
    schedules = milp_result.charge_schedule or {}
    totals: Dict[str, List[float]] = {}
    for _v_id, c_dict in schedules.items():
        for c_id, series in c_dict.items():
            if c_id not in totals:
                totals[c_id] = [0.0] * len(series)
            for t, val in enumerate(series):
                if t < len(totals[c_id]):
                    totals[c_id][t] += float(val)
    return totals


def build_time_labels(data: Any) -> List[str]:
    """
    ProblemData から時刻ラベルリストを生成する。

    Returns
    -------
    ["05:00", "05:15", ...]
    """
    try:
        start_min = (
            int(data.start_time_hour * 60)
            if hasattr(data, "start_time_hour")
            else 5 * 60
        )
        delta_min = int(data.delta_t_min) if hasattr(data, "delta_t_min") else 15
        n = data.num_periods if hasattr(data, "num_periods") else 64
        labels = []
        for i in range(n + 1):
            total_min = start_min + i * delta_min
            h = (total_min // 60) % 24
            m = total_min % 60
            labels.append(f"{h:02d}:{m:02d}")
        return labels
    except Exception:
        return [str(i) for i in range(65)]


def make_feasibility_dict(feasibility_report: Any) -> Dict[str, bool]:
    """FeasibilityReport を {category: bool} の辞書に変換する。"""
    fr = feasibility_report
    return {
        "trip_coverage": fr.trip_coverage_ok,
        "time_connection": fr.time_connection_ok,
        "SOC balance": fr.soc_ok,
        "charger capacity": fr.charger_ok,
        "grid limit": fr.grid_limit_ok,
        "end-of-day SOC": fr.end_soc_ok,
    }
