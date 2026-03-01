"""
src.pipeline.gap_analysis — 最適化とシミュレーションのギャップ分析

最適化解の品質を時系列シミュレーションで検証し、
最適化モデルで見落とされがちな要素を特定・レポートする。

対象:
  - 詳細 SOC 推移と充電器利用
  - ピーク電力超過
  - PV / TOU 電力料金の再評価
  - バッテリ劣化パターン
  - 行路制約の影響比較
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class GapIssue:
    """最適化解とシミュレーションの乖離項目。"""
    category: str           # "soc" | "charger" | "grid" | "degradation" | "delay" | "unserved"
    severity: str           # "critical" | "warning" | "info"
    vehicle_id: Optional[str] = None
    time_idx: Optional[int] = None
    description: str = ""
    milp_value: Optional[float] = None
    sim_value: Optional[float] = None
    gap_pct: Optional[float] = None


@dataclass
class GapAnalysisReport:
    """ギャップ分析レポート全体。"""
    total_issues: int = 0
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    issues: List[GapIssue] = field(default_factory=list)

    # --- カテゴリ別サマリ ---
    soc_violation_count: int = 0
    charger_conflict_count: int = 0
    grid_limit_violation_count: int = 0
    degradation_gap_pct: float = 0.0
    unserved_gap: int = 0

    # --- 行路制約比較 ---
    duty_mode_vehicle_count: Optional[int] = None
    free_mode_vehicle_count: Optional[int] = None
    duty_mode_cost: Optional[float] = None
    free_mode_cost: Optional[float] = None

    # --- エネルギーギャップ ---
    milp_total_energy_kwh: float = 0.0
    sim_total_energy_kwh: float = 0.0
    energy_gap_pct: float = 0.0

    def add_issue(self, issue: GapIssue):
        self.issues.append(issue)
        self.total_issues += 1
        if issue.severity == "critical":
            self.critical_count += 1
        elif issue.severity == "warning":
            self.warning_count += 1
        else:
            self.info_count += 1

    def summary(self) -> str:
        lines = [
            f"=== ギャップ分析サマリ ===",
            f"総問題数: {self.total_issues} "
            f"(critical={self.critical_count}, warning={self.warning_count}, info={self.info_count})",
            f"SOC 違反: {self.soc_violation_count} 件",
            f"充電器衝突: {self.charger_conflict_count} 件",
            f"系統受電超過: {self.grid_limit_violation_count} 件",
            f"エネルギー乖離: MILP={self.milp_total_energy_kwh:.1f} kWh, "
            f"SIM={self.sim_total_energy_kwh:.1f} kWh "
            f"(gap={self.energy_gap_pct:.1f}%)",
        ]
        if self.duty_mode_cost is not None and self.free_mode_cost is not None:
            lines.append(
                f"行路制約比較: duty=¥{self.duty_mode_cost:,.0f}, "
                f"free=¥{self.free_mode_cost:,.0f}, "
                f"diff={(self.duty_mode_cost - self.free_mode_cost):+,.0f}"
            )
        return "\n".join(lines)


def run_gap_analysis(
    data: Any,
    ms: Any,
    dp: Any,
    milp_result: Any,
    sim_result: Any,
    duties: Optional[List] = None,
) -> GapAnalysisReport:
    """MILP 解とシミュレーション結果のギャップを分析する。

    Parameters
    ----------
    data : ProblemData
    ms : ModelSets
    dp : DerivedParams
    milp_result : MILPResult
    sim_result : SimulationResult
    duties : Optional[List[VehicleDuty]]

    Returns
    -------
    GapAnalysisReport
    """
    report = GapAnalysisReport()

    # --- 1. SOC 違反検出 ---
    _check_soc_gaps(data, ms, dp, milp_result, report)

    # --- 2. 充電器占有衝突検出 ---
    _check_charger_conflicts(data, ms, dp, milp_result, report)

    # --- 3. 系統受電上限検出 ---
    _check_grid_limit(data, ms, dp, milp_result, report)

    # --- 4. エネルギー消費乖離 ---
    _check_energy_gap(data, ms, dp, milp_result, sim_result, report)

    # --- 5. バッテリ劣化パターン ---
    _check_degradation_pattern(data, ms, dp, milp_result, report)

    return report


def _check_soc_gaps(data, ms, dp, milp_result, report: GapAnalysisReport):
    """SOC 推移の詳細検証。"""
    soc_series = getattr(milp_result, "soc_series", {})
    for k in ms.K_BEV:
        veh = dp.vehicle_lut.get(k)
        if veh is None:
            continue
        soc_min = veh.soc_min or 0.0
        for t in ms.T:
            soc_val = soc_series.get((k, t))
            if soc_val is not None and soc_val < soc_min - data.EPSILON:
                report.soc_violation_count += 1
                report.add_issue(GapIssue(
                    category="soc",
                    severity="critical",
                    vehicle_id=k,
                    time_idx=t,
                    description=f"SOC={soc_val:.2f} kWh < min={soc_min:.2f} kWh",
                    sim_value=soc_val,
                    milp_value=soc_min,
                ))


def _check_charger_conflicts(data, ms, dp, milp_result, report: GapAnalysisReport):
    """同一充電器への同時接続を検出。"""
    charge_schedule = getattr(milp_result, "charge_schedule", {})
    for t in ms.T:
        charger_usage: Dict[str, List[str]] = {}
        for (k, c, t_idx), val in charge_schedule.items():
            if t_idx == t and val > 0.5:
                charger_usage.setdefault(c, []).append(k)
        for c, vehicles in charger_usage.items():
            if len(vehicles) > 1:
                report.charger_conflict_count += 1
                report.add_issue(GapIssue(
                    category="charger",
                    severity="critical",
                    time_idx=t,
                    description=f"充電器 {c} に {len(vehicles)} 台同時接続: {vehicles}",
                ))


def _check_grid_limit(data, ms, dp, milp_result, report: GapAnalysisReport):
    """系統受電が grid_import_limit を超えていないか確認。"""
    grid_import = getattr(milp_result, "grid_import_kw", {})
    for site in data.sites:
        for t in ms.T:
            import_val = grid_import.get((site.site_id, t), 0.0)
            if import_val > site.grid_import_limit_kw + data.EPSILON:
                report.grid_limit_violation_count += 1
                report.add_issue(GapIssue(
                    category="grid",
                    severity="warning",
                    time_idx=t,
                    description=(
                        f"Site {site.site_id}: 受電={import_val:.1f} kW > "
                        f"上限={site.grid_import_limit_kw:.1f} kW"
                    ),
                    sim_value=import_val,
                    milp_value=site.grid_import_limit_kw,
                ))


def _check_energy_gap(data, ms, dp, milp_result, sim_result, report: GapAnalysisReport):
    """MILP 目的関数のエネルギー項とシミュレーション値の乖離。"""
    milp_energy = getattr(sim_result, "total_grid_kwh", 0.0)
    # 概算: 全 BEV の消費合計
    sim_energy = 0.0
    for k in ms.K_BEV:
        tasks = milp_result.assignment.get(k, [])
        for tid in tasks:
            sim_energy += dp.task_energy_bev.get(tid, 0.0)

    report.milp_total_energy_kwh = round(milp_energy, 2)
    report.sim_total_energy_kwh = round(sim_energy, 2)
    if milp_energy > 0:
        report.energy_gap_pct = round(
            abs(milp_energy - sim_energy) / milp_energy * 100, 2
        )
    if report.energy_gap_pct > 10.0:
        report.add_issue(GapIssue(
            category="energy",
            severity="warning",
            description=(
                f"エネルギー消費乖離 {report.energy_gap_pct:.1f}%: "
                f"grid={milp_energy:.1f} kWh vs task_sum={sim_energy:.1f} kWh"
            ),
            milp_value=milp_energy,
            sim_value=sim_energy,
            gap_pct=report.energy_gap_pct,
        ))


def _check_degradation_pattern(data, ms, dp, milp_result, report: GapAnalysisReport):
    """急速充電回数・平均 SOC 範囲を計測し劣化リスクを評価。"""
    charge_power = getattr(milp_result, "charge_power_kw", {})
    for k in ms.K_BEV:
        rapid_count = 0
        total_charge_kwh = 0.0
        for (vk, c, t), power_val in charge_power.items():
            if vk == k and power_val > 0.0:
                total_charge_kwh += power_val * data.delta_t_hour
                # 急速充電: > 50kW
                charger = dp.charger_lut.get(c)
                if charger and charger.power_max_kw >= 50.0:
                    rapid_count += 1

        if rapid_count > 6:
            report.add_issue(GapIssue(
                category="degradation",
                severity="warning",
                vehicle_id=k,
                description=(
                    f"急速充電 {rapid_count} 回/日 (>{6}回): "
                    f"バッテリ劣化リスク高。充電量計={total_charge_kwh:.1f} kWh"
                ),
            ))


def export_gap_report(
    report: GapAnalysisReport,
    output_path: Path,
) -> None:
    """ギャップ分析レポートを Markdown で出力する。"""
    lines: List[str] = []
    lines.append("# ギャップ分析レポート\n")
    lines.append(report.summary())
    lines.append("")

    if report.issues:
        lines.append("\n## 詳細問題一覧\n")
        lines.append("| # | カテゴリ | 重要度 | 車両 | 時刻 | 説明 |")
        lines.append("|---|---------|--------|------|------|------|")
        for i, issue in enumerate(report.issues[:50], 1):
            vid = issue.vehicle_id or "-"
            tidx = str(issue.time_idx) if issue.time_idx is not None else "-"
            lines.append(f"| {i} | {issue.category} | {issue.severity} | "
                        f"{vid} | {tidx} | {issue.description} |")

    lines.append("\n---\n*Generated by gap_analysis pipeline*\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[gap_analysis] → {output_path}")
