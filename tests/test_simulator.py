"""
tests/test_simulator.py — シミュレータ回帰テスト (5件)

各テストは MILPResult と最低限の ProblemData / ModelSets / DerivedParams を
直接構築して simulator.py の検証ロジックを呼び出す。
Gurobi は不要 (MILPResult を手動で作る)。

テスト一覧:
  1. SOC 下限違反の検出
  2. 同時充電過負荷の検出
  3. タスク系列の実行不能 (時間重複) の検出
  4. 終日 SOC 目標未達の検出
  5. 系統容量上限超過の検出
"""

from __future__ import annotations

import sys
import os

# プロジェクトルートを sys.path に追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from src.data_schema import (
    ProblemData,
    Vehicle,
    Task,
    Charger,
    Site,
    ElectricityPrice,
)
from src.milp_model import MILPResult
from src.model_sets import ModelSets
from src.parameter_builder import DerivedParams
from src.simulator import (
    simulate,
    check_schedule_feasibility,
    SimulationResult,
    FeasibilityReport,
)


# ---------------------------------------------------------------------------
# テスト共通ヘルパー
# ---------------------------------------------------------------------------


def _make_minimal_data(
    n_periods: int = 8,
    delta_h: float = 0.5,
) -> ProblemData:
    """最小構成の ProblemData を生成する (2台 BEV, 2タスク, 1充電器, 1サイト)"""
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="V1",
                vehicle_type="BEV",
                home_depot="D1",
                battery_capacity=100.0,
                soc_init=80.0,
                soc_min=20.0,
                soc_max=100.0,
                soc_target_end=50.0,
                charge_power_max=50.0,
                charge_efficiency=1.0,
            ),
            Vehicle(
                vehicle_id="V2",
                vehicle_type="BEV",
                home_depot="D1",
                battery_capacity=100.0,
                soc_init=80.0,
                soc_min=20.0,
                soc_max=100.0,
                soc_target_end=50.0,
                charge_power_max=50.0,
                charge_efficiency=1.0,
            ),
        ],
        tasks=[
            Task(
                task_id="T1",
                start_time_idx=0,
                end_time_idx=3,
                origin="D1",
                destination="D1",
                energy_required_kwh_bev=30.0,
                demand_cover=True,
            ),
            Task(
                task_id="T2",
                start_time_idx=4,
                end_time_idx=7,
                origin="D1",
                destination="D1",
                energy_required_kwh_bev=30.0,
                demand_cover=True,
            ),
        ],
        chargers=[
            Charger(charger_id="C1", site_id="S1", power_max_kw=50.0),
        ],
        sites=[
            Site(site_id="S1", site_type="depot", grid_import_limit_kw=100.0),
        ],
        electricity_prices=[
            ElectricityPrice(
                site_id="S1", time_idx=t, grid_energy_price=20.0, base_load_kw=0.0
            )
            for t in range(n_periods)
        ],
        num_periods=n_periods,
        delta_t_hour=delta_h,
        enable_demand_charge=False,
        enable_pv=False,
        enable_battery_degradation=False,
    )
    return data


def _make_ms_dp(data: ProblemData):
    """ModelSets と DerivedParams を構築する"""
    from src.model_sets import build_model_sets
    from src.parameter_builder import build_derived_params

    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)
    return ms, dp


def _make_ok_milp_result(data: ProblemData, ms, dp) -> MILPResult:
    """feasible な基準 MILPResult を手動生成する"""
    T = len(ms.T)
    # V1 → T1, V2 → T2
    assignment = {"V1": ["T1"], "V2": ["T2"]}
    # SOC: 初期80 → T1でV1は30消費 → 50  (min=20 に対し余裕あり)
    soc_V1 = [80.0 - 30.0 * (t / 4) for t in range(T + 1)]
    soc_V2 = [80.0 - 30.0 * max(0, (t - 4) / 4) for t in range(T + 1)]
    # 充電なし
    charge_schedule = {
        "V1": {"C1": [0] * T},
        "V2": {"C1": [0] * T},
    }
    charge_power_kw = {
        "V1": {"C1": [0.0] * T},
        "V2": {"C1": [0.0] * T},
    }
    grid_import_kw = {"S1": [0.0] * T}
    pv_used_kw = {}
    return MILPResult(
        status="OPTIMAL",
        objective_value=0.0,
        solve_time_sec=0.0,
        assignment=assignment,
        soc_series={"V1": soc_V1, "V2": soc_V2},
        charge_schedule=charge_schedule,
        charge_power_kw=charge_power_kw,
        grid_import_kw=grid_import_kw,
        pv_used_kw=pv_used_kw,
        unserved_tasks=[],
    )


# ---------------------------------------------------------------------------
# テスト 1: SOC 下限違反の検出
# ---------------------------------------------------------------------------


def test_soc_lower_limit_violation():
    """
    SOC が soc_min (20 kWh) を下回るスロットが存在する場合、
    check_schedule_feasibility が soc_ok=False を返すことを確認する。
    """
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    # V1 の SOC を途中で 10 kWh (< min=20) にする
    bad_soc = list(result.soc_series["V1"])
    bad_soc[3] = 10.0  # t=3 で下限割れ
    result.soc_series["V1"] = bad_soc

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.soc_ok is False, "SOC 下限違反が検出されるべき"
    assert report.feasible is False
    categories = [iss.category for iss in report.issues]
    assert "soc_shortage" in categories, f"soc_shortage が issues にない: {categories}"


# ---------------------------------------------------------------------------
# テスト 2: 同時充電過負荷の検出
# ---------------------------------------------------------------------------


def test_simultaneous_charger_overload():
    """
    1 台の充電器 C1 に 2 台の車両が同時刻に charge_schedule=1 を持つ場合、
    check_schedule_feasibility が charger_ok=False を返すことを確認する。
    """
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    # t=5 に V1 と V2 の両方が C1 で充電するよう設定 → 同時過負荷
    T = len(ms.T)
    sched_v1 = [0] * T
    sched_v2 = [0] * T
    sched_v1[5] = 1
    sched_v2[5] = 1  # 同時充電 (上限は 1台)
    result.charge_schedule["V1"]["C1"] = sched_v1
    result.charge_schedule["V2"]["C1"] = sched_v2

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.charger_ok is False, "充電器過負荷が検出されるべき"
    assert report.feasible is False
    categories = [iss.category for iss in report.issues]
    assert "charger_shortage" in categories, (
        f"charger_shortage が issues にない: {categories}"
    )


# ---------------------------------------------------------------------------
# テスト 3: タスク系列実行不能 (時間重複) の検出
# ---------------------------------------------------------------------------


def test_task_sequence_time_overlap():
    """
    同一車両に time_idx が重複するタスクが割り当てられた場合、
    check_schedule_feasibility が time_connection_ok=False を返すことを確認する。
    (T1: 0-3, T2: 4-7 を V1 に両方割り当て & can_follow=False に設定)
    """
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    # V1 に T1 と T2 両方割り当て。T1 end=3, T2 start=4 → 重複なし。
    # なので can_follow["T1"]["T2"] = False にして「接続不可」を強制する。
    dp.can_follow["T1"] = {"T2": False}
    result.assignment["V1"] = ["T1", "T2"]

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.time_connection_ok is False, "時間接続違反が検出されるべき"
    assert report.feasible is False
    categories = [iss.category for iss in report.issues]
    assert "time_connection" in categories, (
        f"time_connection が issues にない: {categories}"
    )


# ---------------------------------------------------------------------------
# テスト 4: 終日 SOC 目標未達の検出
# ---------------------------------------------------------------------------


def test_end_of_day_soc_violation():
    """
    最終スロットの SOC が soc_target_end (50 kWh) を下回る場合、
    check_schedule_feasibility が end_soc_ok=False を返すことを確認する。
    """
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    # V1 の終端 SOC を 30 kWh (<target=50) に設定
    bad_soc = list(result.soc_series["V1"])
    bad_soc[-1] = 30.0  # 終端が目標未達
    result.soc_series["V1"] = bad_soc

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.end_soc_ok is False, "終日 SOC 目標未達が検出されるべき"
    categories = [iss.category for iss in report.issues]
    assert "end_soc_target" in categories, (
        f"end_soc_target が issues にない: {categories}"
    )


# ---------------------------------------------------------------------------
# テスト 5: 系統容量上限超過の検出
# ---------------------------------------------------------------------------


def test_grid_capacity_violation():
    """
    サイト S1 の grid_import_limit_kw=100 kW を超える受電が発生した場合、
    check_schedule_feasibility が grid_limit_ok=False を返すことを確認する。
    """
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    # t=2 に 150 kW (> 100 kW limit) の受電を設定
    T = len(ms.T)
    grid_series = [0.0] * T
    grid_series[2] = 150.0
    result.grid_import_kw["S1"] = grid_series

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.grid_limit_ok is False, "系統容量超過が検出されるべき"
    categories = [iss.category for iss in report.issues]
    assert "grid_limit" in categories, f"grid_limit が issues にない: {categories}"


# ---------------------------------------------------------------------------
# 正常系スモークテスト (オプション)
# ---------------------------------------------------------------------------


def test_ok_schedule_passes_all_checks():
    """正常なスケジュールはすべての検証を通過することを確認する。"""
    data = _make_minimal_data()
    ms, dp = _make_ms_dp(data)
    result = _make_ok_milp_result(data, ms, dp)

    report = check_schedule_feasibility(data, ms, dp, result)

    # 個別カテゴリはすべて OK のはず (end_soc は soc_series[-1]=50 なので OK)
    # V1 の SOC: 80 - 30*(t/4) → t=4 で 50.0 = target なので OK
    # V2 の SOC: 80 → end は 50.0 = target なので OK
    assert report.soc_ok is True
    assert report.charger_ok is True
    assert report.time_connection_ok is True
    assert report.grid_limit_ok is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
