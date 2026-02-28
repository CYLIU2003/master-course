"""
simulator.py — 与えられた計画を時系列評価するシミュレータ

仕様書 §14.6, agent.md §2.2, §4, §6.3 担当:
  - 与えられた配車・充電計画をもとに、時系列評価を再計算する
  - MILP 解の妥当性検証にも使う
  - 導出変数・評価指標を計算する (§8)
  - 実行可能性の診断と原因切り分けを行う (agent.md §6.3)

単位: kW, kWh, hour, km (§16)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .data_schema import ProblemData
from .milp_model import MILPResult
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_grid_price, get_pv_gen, get_base_load


# ---------------------------------------------------------------------------
# §6.3 (agent.md) 実行可能性診断
# ---------------------------------------------------------------------------

@dataclass
class FeasibilityIssue:
    """個別の実行不能原因"""
    category: str          # "trip_coverage" | "time_connection" | "soc_shortage"
                           # | "charger_shortage" | "grid_limit" | "end_soc_target"
    severity: str          # "error" | "warning"
    vehicle_id: str = ""
    task_id: str = ""
    time_idx: int = -1
    detail: str = ""

    def __str__(self) -> str:
        parts = [f"[{self.severity.upper()}] {self.category}"]
        if self.vehicle_id:
            parts.append(f"vehicle={self.vehicle_id}")
        if self.task_id:
            parts.append(f"task={self.task_id}")
        if self.time_idx >= 0:
            parts.append(f"t={self.time_idx}")
        parts.append(self.detail)
        return " | ".join(parts)


@dataclass
class FeasibilityReport:
    """
    実行可能性診断の結果 (agent.md §6.3)

    infeasible 時に「trip coverage / time connection /
    SOC shortage / charger shortage / grid limit / end-of-day SOC target」
    のどれが原因かを推定する。
    """
    feasible: bool = True
    issues: List[FeasibilityIssue] = field(default_factory=list)

    # カテゴリ別集計
    trip_coverage_ok: bool = True
    time_connection_ok: bool = True
    soc_ok: bool = True
    charger_ok: bool = True
    grid_limit_ok: bool = True
    end_soc_ok: bool = True

    def summary(self) -> str:
        lines = []
        lines.append(f"実行可能性: {'OK' if self.feasible else 'NG'}")
        lines.append(f"  trip coverage    : {'OK' if self.trip_coverage_ok else 'NG'}")
        lines.append(f"  time connection  : {'OK' if self.time_connection_ok else 'NG'}")
        lines.append(f"  SOC balance      : {'OK' if self.soc_ok else 'NG'}")
        lines.append(f"  charger capacity : {'OK' if self.charger_ok else 'NG'}")
        lines.append(f"  grid limit       : {'OK' if self.grid_limit_ok else 'NG'}")
        lines.append(f"  end-of-day SOC   : {'OK' if self.end_soc_ok else 'NG'}")
        if self.issues:
            lines.append(f"  問題数: {len(self.issues)}")
            for iss in self.issues[:10]:
                lines.append(f"    {iss}")
            if len(self.issues) > 10:
                lines.append(f"    ... 他 {len(self.issues) - 10} 件")
        return "\n".join(lines)


def check_schedule_feasibility(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
) -> FeasibilityReport:
    """
    MILP 結果の実行可能性を検証し、原因カテゴリを特定する。

    agent.md §6.3 が要求する cut-off:
      - trip coverage impossible
      - time connection impossible
      - SOC shortage
      - charger shortage
      - site grid limit too tight
      - end-of-day SOC target too strict
    """
    report = FeasibilityReport()
    T = ms.T

    # === 1) Trip Coverage ===
    assigned_tasks: set = set()
    for k, tasks in milp_result.assignment.items():
        assigned_tasks.update(tasks)
    for r in ms.R:
        task = dp.task_lut[r]
        if task.demand_cover and r not in assigned_tasks:
            report.feasible = False
            report.trip_coverage_ok = False
            report.issues.append(FeasibilityIssue(
                "trip_coverage", "error", task_id=r,
                detail=f"必須タスク {r} が未割当",
            ))

    # === 2) Time Connection ===
    for k, tasks in milp_result.assignment.items():
        sorted_tasks = sorted(tasks, key=lambda r: dp.task_lut[r].start_time_idx)
        for i in range(len(sorted_tasks) - 1):
            r1, r2 = sorted_tasks[i], sorted_tasks[i + 1]
            t1, t2 = dp.task_lut[r1], dp.task_lut[r2]
            can = dp.can_follow.get(r1, {}).get(r2, None)
            if can is False:
                report.feasible = False
                report.time_connection_ok = False
                report.issues.append(FeasibilityIssue(
                    "time_connection", "error", vehicle_id=k,
                    detail=f"{r1} -> {r2} は接続不可 "
                           f"(end={t1.end_time_idx}, start={t2.start_time_idx})",
                ))
            elif can is None:
                # can_follow 情報なし: 時間重複チェック
                if t1.end_time_idx >= t2.start_time_idx:
                    report.feasible = False
                    report.time_connection_ok = False
                    report.issues.append(FeasibilityIssue(
                        "time_connection", "error", vehicle_id=k,
                        detail=f"{r1}(end={t1.end_time_idx}) と "
                               f"{r2}(start={t2.start_time_idx}) が重複",
                    ))

    # === 3) SOC ===
    for k, soc_series in milp_result.soc_series.items():
        veh = dp.vehicle_lut.get(k)
        if not veh:
            continue
        soc_min_limit = veh.soc_min or 0.0
        soc_max_limit = veh.soc_max or (veh.battery_capacity or 999)
        for t_idx, soc_val in enumerate(soc_series):
            if soc_val < soc_min_limit - 1e-3:
                report.soc_ok = False
                report.feasible = False
                report.issues.append(FeasibilityIssue(
                    "soc_shortage", "error", vehicle_id=k, time_idx=t_idx,
                    detail=f"SOC={soc_val:.1f} < min={soc_min_limit:.1f}",
                ))
        # End-of-day SOC
        if soc_series and veh.soc_target_end is not None:
            end_soc = soc_series[-1]
            if end_soc < veh.soc_target_end - 1e-3:
                report.end_soc_ok = False
                report.issues.append(FeasibilityIssue(
                    "end_soc_target", "warning", vehicle_id=k,
                    detail=f"end SOC={end_soc:.1f} < target={veh.soc_target_end:.1f}",
                ))

    # === 4) Charger Capacity ===
    for t_idx in T:
        for c in ms.C:
            count = 0
            for k in ms.K_BEV:
                series = milp_result.charge_schedule.get(k, {}).get(c, [])
                if t_idx < len(series) and series[t_idx] > 0:
                    count += 1
            if count > 1:
                report.charger_ok = False
                report.feasible = False
                report.issues.append(FeasibilityIssue(
                    "charger_shortage", "error", time_idx=t_idx,
                    detail=f"充電器 {c} に同時 {count} 台 (上限1)",
                ))

    # === 5) Grid Limit ===
    for site_id, series in milp_result.grid_import_kw.items():
        site = dp.site_lut.get(site_id)
        if not site:
            continue
        for t_idx, kw in enumerate(series):
            if kw > site.grid_import_limit_kw + 1e-3:
                report.grid_limit_ok = False
                report.issues.append(FeasibilityIssue(
                    "grid_limit", "warning", time_idx=t_idx,
                    detail=f"site={site_id} grid={kw:.1f}kW > limit={site.grid_import_limit_kw:.1f}kW",
                ))

    return report


@dataclass
class SimulationResult:
    """
    シミュレーション評価結果 (仕様書 §8)

    MILP の決定変数は使わず、解から計算した評価指標のみ保持する。
    """

    # --- §8 導出量 ---
    total_operating_cost: float = 0.0       # 総運行コスト [円]
    total_energy_cost: float = 0.0          # 電力量料金合計 [円]
    total_demand_charge: float = 0.0        # デマンド料金合計 [円]
    total_degradation_cost: float = 0.0     # 電池劣化コスト合計 [円]
    total_fuel_cost: float = 0.0            # ICE 燃料費合計 [円]
    total_co2_kg: float = 0.0               # CO2 排出量 [kg]

    pv_self_consumption_ratio: float = 0.0  # PV 自家消費率 [-]
    total_pv_kwh: float = 0.0               # PV 利用量 [kWh]
    total_grid_kwh: float = 0.0             # 系統受電量 [kWh]
    peak_demand_kw: float = 0.0             # ピーク需要 [kW]

    # 充電器利用率: charger_id -> utilization [0-1]
    charger_utilization: Dict[str, float] = field(default_factory=dict)
    # 車両稼働率: vehicle_id -> utilization [0-1]
    vehicle_utilization: Dict[str, float] = field(default_factory=dict)

    served_task_ratio: float = 0.0          # 担当済みタスク割合 [-]
    unserved_tasks: List[str] = field(default_factory=list)

    # SOC 推移検証
    soc_min_kwh: float = 0.0
    soc_violations: List[str] = field(default_factory=list)  # 違反 vehicle x time

    infeasibility_penalty_total: float = 0.0

    # 時系列: site_id -> [kW/kWh, ...]
    grid_import_kw_series: Dict[str, List[float]] = field(default_factory=dict)
    pv_used_kw_series: Dict[str, List[float]] = field(default_factory=dict)

    # 実行可能性診断 (agent.md §6.3)
    feasibility_report: Optional[FeasibilityReport] = None


def simulate(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    demand_charge_rate: float = 1500.0,  # 円/kW
) -> SimulationResult:
    """
    MILP 結果を受け取り、時系列シミュレーションで評価指標を計算する。

    Parameters
    ----------
    data          : ProblemData
    ms            : ModelSets
    dp            : DerivedParams
    milp_result   : MILPResult
    demand_charge_rate : float
        デマンド料金単価 [円/kW]

    Returns
    -------
    SimulationResult
    """
    sim = SimulationResult()
    T   = ms.T
    delta_h = data.delta_t_hour

    if milp_result.status not in ("OPTIMAL", "TIME_LIMIT", "SUBOPTIMAL"):
        return sim

    # ===== SOC 検証 =====
    min_soc = float("inf")
    for k, soc_series in milp_result.soc_series.items():
        veh = dp.vehicle_lut[k]
        soc_min_limit = veh.soc_min or 0.0
        for t_idx, soc_val in enumerate(soc_series):
            if soc_val < min_soc:
                min_soc = soc_val
            if soc_val < soc_min_limit - 1e-3:
                sim.soc_violations.append(f"{k}@t={t_idx}")
    sim.soc_min_kwh = round(min_soc, 4) if min_soc < float("inf") else 0.0

    # ===== 系統受電・電力料金 =====
    total_grid = 0.0
    total_cost = 0.0
    peak_kw = 0.0
    for site_id, series in milp_result.grid_import_kw.items():
        sim.grid_import_kw_series[site_id] = series
        for t_idx, kw in enumerate(series):
            kwh = kw * delta_h
            total_grid += kwh
            total_cost += get_grid_price(dp, site_id, t_idx) * kwh
            if kw > peak_kw:
                peak_kw = kw

    sim.total_grid_kwh   = round(total_grid, 4)
    sim.total_energy_cost = round(total_cost, 2)
    sim.peak_demand_kw   = round(peak_kw, 4)

    if data.enable_demand_charge:
        sim.total_demand_charge = round(demand_charge_rate * peak_kw, 2)

    # ===== PV 利用 =====
    total_pv = 0.0
    total_pv_gen = 0.0
    for site_id, series in milp_result.pv_used_kw.items():
        sim.pv_used_kw_series[site_id] = series
        for t_idx, kw in enumerate(series):
            total_pv += kw * delta_h
    # PV 発電量合計
    for site_id in ms.I_CHARGE:
        for t_idx in T:
            total_pv_gen += get_pv_gen(dp, site_id, t_idx) * delta_h

    sim.total_pv_kwh = round(total_pv, 4)
    if total_pv_gen > 0:
        sim.pv_self_consumption_ratio = round(total_pv / total_pv_gen, 4)

    # ===== 燃料費・CO2 (ICE) =====
    for k in ms.K_ICE:
        veh = dp.vehicle_lut[k]
        for r in milp_result.assignment.get(k, []):
            fuel_l = dp.task_fuel_ice.get(r, 0.0)
            sim.total_fuel_cost += veh.fuel_cost_coeff * fuel_l
            sim.total_co2_kg    += veh.co2_emission_coeff * fuel_l

    sim.total_fuel_cost = round(sim.total_fuel_cost, 2)
    sim.total_co2_kg    = round(sim.total_co2_kg, 4)

    # ===== 電池劣化コスト =====
    if data.enable_battery_degradation:
        for k in ms.K_BEV:
            veh = dp.vehicle_lut[k]
            coeff = veh.battery_degradation_cost_coeff
            for c, power_series in milp_result.charge_power_kw.get(k, {}).items():
                for kw in power_series:
                    sim.total_degradation_cost += coeff * kw * delta_h * veh.charge_efficiency
        sim.total_degradation_cost = round(sim.total_degradation_cost, 2)

    # ===== 総コスト =====
    sim.total_operating_cost = round(
        sim.total_energy_cost
        + sim.total_demand_charge
        + sim.total_fuel_cost
        + sim.total_degradation_cost,
        2,
    )

    # ===== タスク担当率 =====
    total_tasks = len(ms.R)
    served = sum(len(v) for v in milp_result.assignment.values())
    sim.unserved_tasks = milp_result.unserved_tasks[:]
    sim.served_task_ratio = round(served / total_tasks, 4) if total_tasks > 0 else 0.0

    # ===== 充電器利用率 =====
    for c in ms.C:
        used_slots = 0
        for k in ms.K_BEV:
            series = milp_result.charge_schedule.get(k, {}).get(c, [])
            used_slots += sum(series)
        sim.charger_utilization[c] = round(used_slots / max(len(T), 1), 4)

    # ===== 車両稼働率 =====
    for k in ms.K_ALL:
        assigned = milp_result.assignment.get(k, [])
        active_slots = sum(
            sum(dp.task_active.get(r, [0] * len(T)))
            for r in assigned
        )
        sim.vehicle_utilization[k] = round(active_slots / max(len(T), 1), 4)

    # ===== 実行可能性診断 (agent.md §6.3) =====
    sim.feasibility_report = check_schedule_feasibility(data, ms, dp, milp_result)

    return sim


# ---------------------------------------------------------------------------
# SOC トレース再計算 (agent.md §2.2)
# ---------------------------------------------------------------------------

def compute_soc_trace(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    assignment: Dict[str, List[str]],
    charge_power_kw: Dict[str, Dict[str, List[float]]],
) -> Dict[str, List[float]]:
    """
    任意のスケジュールから SOC 時系列を再計算する。

    Parameters
    ----------
    assignment      : vehicle_id -> [task_id, ...]
    charge_power_kw : vehicle_id -> charger_id -> [kW per slot]

    Returns
    -------
    vehicle_id -> [soc_0, soc_1, ..., soc_T]
    """
    delta_h = data.delta_t_hour
    soc_traces: Dict[str, List[float]] = {}

    for k in ms.K_BEV:
        veh = dp.vehicle_lut[k]
        soc_init = veh.soc_init or 0.0
        soc_series = [soc_init]
        soc = soc_init

        assigned_tasks = assignment.get(k, [])

        for t_idx in ms.T:
            # 消費
            drive_kwh = 0.0
            for r in assigned_tasks:
                energy_per_slot = dp.task_energy_per_slot.get(r, [])
                if t_idx < len(energy_per_slot):
                    drive_kwh += energy_per_slot[t_idx]

            # 充電
            charge_kwh = 0.0
            for c_id, power_series in charge_power_kw.get(k, {}).items():
                if t_idx < len(power_series):
                    charge_kwh += veh.charge_efficiency * power_series[t_idx] * delta_h

            soc = soc - drive_kwh + charge_kwh
            soc_series.append(round(soc, 4))

        soc_traces[k] = soc_series

    return soc_traces
