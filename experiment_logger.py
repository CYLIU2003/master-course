"""
experiment_logger.py — シミュレーション実験ログ・レポート生成モジュール

使い方:
    from src.experiment_logger import ExperimentLogger

    logger = ExperimentLogger(results_dir="results")
    report = logger.log(scenario=scenario_dict, result=result_dict)
    print(report.summary_text)   # ターミナル表示
    # → results/exp_<timestamp>_<depot>_<objective>.json  (機械可読)
    # → results/exp_<timestamp>_<depot>_<objective>.md    (論文用メモ)
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
#  データクラス
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ExperimentConditions:
    """実験条件（主条件）"""
    depot: str
    routes: list[str]
    fleet_bev_model: str
    fleet_bev_count: int
    fleet_ice_model: str
    fleet_ice_count: int
    objective: str                     # total_cost / co2
    method: str = "MILP"               # MILP / ALNS / MILP+ALNS / GA / SA など


@dataclass
class CostConditions:
    """実験副条件（コスト・料金パラメータ）"""
    tou_offpeak_jpy_per_kwh: float
    tou_midpeak_jpy_per_kwh: float
    tou_onpeak_jpy_per_kwh: float
    diesel_jpy_per_l: float
    demand_jpy_per_kw_month: float
    grid_max_kw: float
    vehicle_fixed_cost_jpy_per_day: float = 0.0
    pv_capacity_kw: float = 0.0        # PV搭載時


@dataclass
class SolverSettings:
    """ソルバー設定"""
    solver_name: str                   # gurobi / highs / cbc
    time_limit_sec: int
    mip_gap_pct: float | None = None   # 終了時の MIP Gap (%)
    threads: int | None = None
    seed: int | None = None            # 乱数シード（ALNS/GA 用）


@dataclass
class SimulationResults:
    """結果サマリ"""
    status: str                        # OPTIMAL / FEASIBLE / INFEASIBLE / TIME_LIMIT など
    objective_value: float | None
    total_cost_jpy: float | None
    electricity_cost_jpy: float | None
    diesel_cost_jpy: float | None
    demand_charge_jpy: float | None
    vehicle_fixed_cost_jpy: float | None
    co2_kg: float | None
    bev_trips: int | None
    ice_trips: int | None
    total_trips: int | None
    total_charging_kwh: float | None
    peak_charging_kw: float | None
    solve_time_sec: float | None
    mip_gap_pct: float | None          # 求解後の実績 Gap
    # 詳細（あれば）
    charging_schedule: dict | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ReproducibilityInfo:
    """再現性情報"""
    timestamp_utc: str
    timestamp_local: str
    git_commit: str | None
    python_version: str
    platform: str
    scenario_hash: str                 # シナリオ JSON の SHA256 (先頭 12 文字)
    seed: int | None


@dataclass
class ExperimentReport:
    """実験レポート全体"""
    experiment_id: str
    conditions: ExperimentConditions
    cost_conditions: CostConditions
    solver_settings: SolverSettings
    results: SimulationResults
    reproducibility: ReproducibilityInfo
    # 出力パス（log() 後に設定）
    json_path: Path | None = None
    md_path: Path | None = None

    @property
    def summary_text(self) -> str:
        """ターミナル用サマリ（カラーなし）"""
        r = self.results
        c = self.conditions
        cc = self.cost_conditions
        s = self.solver_settings
        rep = self.reproducibility

        lines: list[str] = []
        SEP = "=" * 64

        lines += [
            SEP,
            f"  実験レポート  [{self.experiment_id}]",
            SEP,
            "",
            "【実験条件】",
            f"  手法        : {c.method}",
            f"  営業所      : {c.depot}",
            f"  路線        : {', '.join(c.routes)}",
            f"  目的関数    : {c.objective}",
            f"  BEV         : {c.fleet_bev_model} × {c.fleet_bev_count} 台",
            f"  ICE         : {c.fleet_ice_model} × {c.fleet_ice_count} 台",
            "",
            "【副条件（コスト）】",
            f"  電気料金 TOU: オフ {cc.tou_offpeak_jpy_per_kwh} / ミッド {cc.tou_midpeak_jpy_per_kwh}"
            f" / オン {cc.tou_onpeak_jpy_per_kwh}  JPY/kWh",
            f"  軽油単価    : {cc.diesel_jpy_per_l} JPY/L",
            f"  デマンド料金: {cc.demand_jpy_per_kw_month} JPY/kW/月",
            f"  受電上限    : {cc.grid_max_kw} kW",
            f"  車両固定費  : {cc.vehicle_fixed_cost_jpy_per_day} JPY/台/日",
        ]
        if cc.pv_capacity_kw > 0:
            lines.append(f"  PV容量      : {cc.pv_capacity_kw} kW")

        lines += [
            "",
            "【ソルバー設定】",
            f"  ソルバー    : {s.solver_name}",
            f"  時間制限    : {s.time_limit_sec} 秒",
        ]
        if s.mip_gap_pct is not None:
            lines.append(f"  MIP Gap目標 : {s.mip_gap_pct:.3f} %")
        if s.threads:
            lines.append(f"  スレッド数  : {s.threads}")
        if s.seed is not None:
            lines.append(f"  乱数シード  : {s.seed}")

        status_mark = "✅" if r.status == "OPTIMAL" else ("⚠️" if r.status in ("FEASIBLE", "TIME_LIMIT") else "❌")
        lines += [
            "",
            "【結果サマリ】",
            f"  求解状態    : {status_mark} {r.status}",
        ]
        if r.solve_time_sec is not None:
            lines.append(f"  求解時間    : {r.solve_time_sec:.2f} 秒")
        if r.mip_gap_pct is not None:
            lines.append(f"  MIP Gap実績 : {r.mip_gap_pct:.4f} %")
        if r.objective_value is not None:
            lines.append(f"  目的値      : {r.objective_value:,.4f}")
        if r.total_cost_jpy is not None:
            lines.append(f"  総コスト    : {r.total_cost_jpy:,.2f} JPY")
        if r.electricity_cost_jpy is not None:
            lines.append(f"    電気代    : {r.electricity_cost_jpy:,.2f} JPY")
        if r.diesel_cost_jpy is not None:
            lines.append(f"    軽油代    : {r.diesel_cost_jpy:,.2f} JPY")
        if r.demand_charge_jpy is not None:
            lines.append(f"    デマンド  : {r.demand_charge_jpy:,.2f} JPY")
        if r.co2_kg is not None:
            lines.append(f"  CO₂排出量  : {r.co2_kg:,.4f} kg")
        if r.bev_trips is not None or r.ice_trips is not None:
            bev_s = str(r.bev_trips) if r.bev_trips is not None else "-"
            ice_s = str(r.ice_trips) if r.ice_trips is not None else "-"
            tot_s = str(r.total_trips) if r.total_trips is not None else "-"
            lines.append(f"  割当便数    : BEV {bev_s} 便 / ICE {ice_s} 便 / 計 {tot_s} 便")
        if r.total_charging_kwh is not None:
            lines.append(f"  充電量合計  : {r.total_charging_kwh:,.3f} kWh")
        if r.peak_charging_kw is not None:
            lines.append(f"  充電ピーク  : {r.peak_charging_kw:,.1f} kW")

        lines += [
            "",
            "【再現性情報】",
            f"  実験ID      : {self.experiment_id}",
            f"  タイムスタンプ: {rep.timestamp_local}",
            f"  Gitコミット  : {rep.git_commit or '不明'}",
            f"  シナリオHash : {rep.scenario_hash}",
            f"  Python      : {rep.python_version}",
        ]
        if self.json_path:
            lines.append(f"  JSONログ    : {self.json_path}")
        if self.md_path:
            lines.append(f"  Markdownログ: {self.md_path}")
        lines += ["", SEP]

        return "\n".join(lines)

    @property
    def markdown_text(self) -> str:
        """論文・ノート用 Markdown"""
        r = self.results
        c = self.conditions
        cc = self.cost_conditions
        s = self.solver_settings
        rep = self.reproducibility

        status_badge = (
            "🟢 OPTIMAL" if r.status == "OPTIMAL"
            else f"🟡 {r.status}" if r.status in ("FEASIBLE", "TIME_LIMIT")
            else f"🔴 {r.status}"
        )

        lines = [
            f"# 実験レポート `{self.experiment_id}`",
            "",
            f"> 生成: {rep.timestamp_local}  |  Git: `{rep.git_commit or 'N/A'}`  |  Hash: `{rep.scenario_hash}`",
            "",
            "## 実験条件",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| 手法 | **{c.method}** |",
            f"| 目的関数 | `{c.objective}` |",
            f"| 営業所 | {c.depot} |",
            f"| 路線 | {', '.join(c.routes)} |",
            f"| BEV | {c.fleet_bev_model} × {c.fleet_bev_count} 台 |",
            f"| ICE | {c.fleet_ice_model} × {c.fleet_ice_count} 台 |",
            "",
            "## 副条件（コスト・料金）",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| TOU (オフ/ミッド/オン) | {cc.tou_offpeak_jpy_per_kwh} / {cc.tou_midpeak_jpy_per_kwh} / {cc.tou_onpeak_jpy_per_kwh} JPY/kWh |",
            f"| 軽油単価 | {cc.diesel_jpy_per_l} JPY/L |",
            f"| デマンド料金 | {cc.demand_jpy_per_kw_month} JPY/kW/月 |",
            f"| 受電上限 | {cc.grid_max_kw} kW |",
            f"| 車両固定費 | {cc.vehicle_fixed_cost_jpy_per_day} JPY/台/日 |",
        ]
        if cc.pv_capacity_kw > 0:
            lines.append(f"| PV容量 | {cc.pv_capacity_kw} kW |")

        lines += [
            "",
            "## ソルバー設定",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| ソルバー | {s.solver_name} |",
            f"| 時間制限 | {s.time_limit_sec} 秒 |",
        ]
        if s.mip_gap_pct is not None:
            lines.append(f"| MIP Gap 目標 | {s.mip_gap_pct:.3f} % |")
        if s.threads:
            lines.append(f"| スレッド数 | {s.threads} |")
        if s.seed is not None:
            lines.append(f"| 乱数シード | {s.seed} |")

        lines += [
            "",
            "## 結果サマリ",
            "",
            f"**求解状態: {status_badge}**",
            "",
            "| 指標 | 値 |",
            "|------|-----|",
        ]
        _add = lambda label, val, fmt="{:,.4f}": lines.append(
            f"| {label} | {fmt.format(val)} |"
        ) if val is not None else None

        _add("目的値", r.objective_value)
        _add("総コスト", r.total_cost_jpy, "{:,.2f} JPY")
        _add("　電気代", r.electricity_cost_jpy, "{:,.2f} JPY")
        _add("　軽油代", r.diesel_cost_jpy, "{:,.2f} JPY")
        _add("　デマンド料金", r.demand_charge_jpy, "{:,.2f} JPY")
        _add("　車両固定費計", r.vehicle_fixed_cost_jpy, "{:,.2f} JPY")
        _add("CO₂排出量", r.co2_kg, "{:,.4f} kg")

        if r.bev_trips is not None or r.ice_trips is not None:
            bev_s = str(r.bev_trips) if r.bev_trips is not None else "-"
            ice_s = str(r.ice_trips) if r.ice_trips is not None else "-"
            tot_s = str(r.total_trips) if r.total_trips is not None else "-"
            lines.append(f"| BEV/ICE/計 便数 | {bev_s} / {ice_s} / {tot_s} 便 |")

        _add("充電量合計", r.total_charging_kwh, "{:,.3f} kWh")
        _add("充電ピーク", r.peak_charging_kw, "{:,.1f} kW")
        _add("求解時間", r.solve_time_sec, "{:.2f} 秒")
        if r.mip_gap_pct is not None:
            lines.append(f"| MIP Gap 実績 | {r.mip_gap_pct:.4f} % |")

        lines += [
            "",
            "## 再現性情報",
            "",
            f"- **実験ID**: `{self.experiment_id}`",
            f"- **タイムスタンプ (UTC)**: `{rep.timestamp_utc}`",
            f"- **タイムスタンプ (Local)**: `{rep.timestamp_local}`",
            f"- **Git コミット**: `{rep.git_commit or 'N/A'}`",
            f"- **シナリオ Hash (SHA256[:12])**: `{rep.scenario_hash}`",
            f"- **Python**: `{rep.python_version}`",
            f"- **Platform**: `{rep.platform}`",
        ]
        if s.seed is not None:
            lines.append(f"- **乱数シード**: `{s.seed}`")

        if r.extra:
            lines += ["", "## 追加情報", "", "```json",
                      json.dumps(r.extra, ensure_ascii=False, indent=2), "```"]

        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
#  ロガー本体
# ──────────────────────────────────────────────────────────────────────────────

class ExperimentLogger:
    """
    シナリオ JSON + 結果 dict → ExperimentReport を生成し保存するクラス。

    Parameters
    ----------
    results_dir : str | Path
        レポートを保存するディレクトリ（自動作成）
    default_method : str
        手法名デフォルト（シナリオに method キーがない場合に使用）
    """

    def __init__(
        self,
        results_dir: str | Path = "results",
        default_method: str = "MILP",
    ) -> None:
        self.results_dir = Path(results_dir)
        self.default_method = default_method
        self.results_dir.mkdir(parents=True, exist_ok=True)

    # ── パブリック API ──────────────────────────────────────────────────────

    def log(
        self,
        scenario: dict[str, Any],
        result: dict[str, Any],
        *,
        method: str | None = None,
        seed: int | None = None,
        extra_solver: dict | None = None,
    ) -> ExperimentReport:
        """
        シナリオと結果からレポートを生成して保存する。

        Parameters
        ----------
        scenario : dict
            run_simulation に渡したシナリオ JSON（dict）
        result : dict
            run_simulation が返した結果 JSON（dict）
        method : str, optional
            手法名（"MILP", "ALNS", "MILP+ALNS", "GA" など）
            scenario["method"] があればそちらを優先
        seed : int, optional
            乱数シード（ALNS/GA 使用時）
        extra_solver : dict, optional
            ソルバーが返した追加情報 (gap, threads, etc.)

        Returns
        -------
        ExperimentReport
        """
        method = scenario.get("method") or method or self.default_method
        extra_solver = extra_solver or {}
        ts = datetime.now()
        ts_utc = datetime.now(timezone.utc)

        # シナリオ Hash
        scenario_bytes = json.dumps(scenario, sort_keys=True, ensure_ascii=True).encode()
        scenario_hash = hashlib.sha256(scenario_bytes).hexdigest()[:12]

        # 実験ID: YYYYMMDD_HHMMSS_<depot>_<objective>_<hash>
        depot_key = scenario.get("depot", "unknown")
        obj_key = scenario.get("objective", "unknown")
        exp_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{depot_key}_{obj_key}_{scenario_hash}"

        conditions = self._parse_conditions(scenario, method)
        cost_cond = self._parse_cost_conditions(scenario)
        solver_settings = self._parse_solver_settings(scenario, extra_solver, seed)
        sim_results = self._parse_results(result)
        repro = ReproducibilityInfo(
            timestamp_utc=ts_utc.isoformat(),
            timestamp_local=ts.isoformat(),
            git_commit=self._git_commit(),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=platform.platform(),
            scenario_hash=scenario_hash,
            seed=seed,
        )

        report = ExperimentReport(
            experiment_id=exp_id,
            conditions=conditions,
            cost_conditions=cost_cond,
            solver_settings=solver_settings,
            results=sim_results,
            reproducibility=repro,
        )

        # 保存
        report.json_path = self._save_json(report, exp_id)
        report.md_path   = self._save_md(report, exp_id)

        return report

    # ── 内部ヘルパー ─────────────────────────────────────────────────────────

    def _parse_conditions(self, sc: dict, method: str) -> ExperimentConditions:
        fleet = sc.get("fleet", [])
        bev = next((v for v in fleet if v.get("vehicle_type") == "BEV"), {})
        ice = next((v for v in fleet if v.get("vehicle_type") == "ICE"), {})
        return ExperimentConditions(
            depot=sc.get("depot", ""),
            routes=sc.get("routes", []),
            fleet_bev_model=bev.get("model", ""),
            fleet_bev_count=bev.get("count", 0),
            fleet_ice_model=ice.get("model", ""),
            fleet_ice_count=ice.get("count", 0),
            objective=sc.get("objective", ""),
            method=method,
        )

    def _parse_cost_conditions(self, sc: dict) -> CostConditions:
        costs = sc.get("costs", {})
        tou = costs.get("tou_rates", {})
        grid = sc.get("grid", {})
        return CostConditions(
            tou_offpeak_jpy_per_kwh=tou.get("offpeak", 0.0),
            tou_midpeak_jpy_per_kwh=tou.get("midpeak", 0.0),
            tou_onpeak_jpy_per_kwh=tou.get("onpeak", 0.0),
            diesel_jpy_per_l=costs.get("diesel_jpy_per_l", 0.0),
            demand_jpy_per_kw_month=costs.get("demand_jpy_per_kw", 0.0),
            grid_max_kw=grid.get("max_kw", 0.0),
            vehicle_fixed_cost_jpy_per_day=costs.get("vehicle_fixed_cost", 0.0),
            pv_capacity_kw=sc.get("pv", {}).get("capacity_kw", 0.0),
        )

    def _parse_solver_settings(self, sc: dict, extra: dict, seed: int | None) -> SolverSettings:
        solver = sc.get("solver", {})
        return SolverSettings(
            solver_name=solver.get("name", "unknown"),
            time_limit_sec=solver.get("time_limit_sec", 0),
            mip_gap_pct=extra.get("mip_gap_pct") or solver.get("mip_gap_pct"),
            threads=extra.get("threads") or solver.get("threads"),
            seed=seed or solver.get("seed"),
        )

    def _parse_results(self, r: dict) -> SimulationResults:
        """
        run_simulation.py が返す結果 dict をパース。
        キー名は実際の実装に合わせて調整してください。
        """
        # ネストされた可能性のあるキーを安全に取得
        def get(*keys, default=None):
            d = r
            for k in keys:
                if not isinstance(d, dict):
                    return default
                d = d.get(k, default)
                if d is None:
                    return default
            return d

        # コスト内訳（フラット or ネスト両対応）
        cost_breakdown = r.get("cost_breakdown", {})

        return SimulationResults(
            status=r.get("status", "UNKNOWN"),
            objective_value=r.get("objective_value") or r.get("obj_value"),
            total_cost_jpy=(
                r.get("total_cost_jpy")
                or r.get("total_cost")
                or cost_breakdown.get("total")
            ),
            electricity_cost_jpy=(
                r.get("electricity_cost_jpy")
                or cost_breakdown.get("electricity")
            ),
            diesel_cost_jpy=(
                r.get("diesel_cost_jpy")
                or cost_breakdown.get("diesel")
            ),
            demand_charge_jpy=(
                r.get("demand_charge_jpy")
                or cost_breakdown.get("demand")
            ),
            vehicle_fixed_cost_jpy=(
                r.get("vehicle_fixed_cost_jpy")
                or cost_breakdown.get("vehicle_fixed")
            ),
            co2_kg=r.get("co2_kg") or r.get("co2"),
            bev_trips=r.get("bev_trips") or r.get("trips", {}).get("bev"),
            ice_trips=r.get("ice_trips") or r.get("trips", {}).get("ice"),
            total_trips=(
                r.get("total_trips")
                or r.get("trips", {}).get("total")
                or (
                    (r.get("bev_trips", 0) or 0) + (r.get("ice_trips", 0) or 0)
                    if r.get("bev_trips") is not None or r.get("ice_trips") is not None
                    else None
                )
            ),
            total_charging_kwh=(
                r.get("total_charging_kwh")
                or r.get("charging", {}).get("total_kwh")
            ),
            peak_charging_kw=(
                r.get("peak_charging_kw")
                or r.get("charging", {}).get("peak_kw")
            ),
            solve_time_sec=r.get("solve_time_sec") or r.get("solve_time"),
            mip_gap_pct=r.get("mip_gap_pct") or r.get("mip_gap"),
            charging_schedule=r.get("charging_schedule"),
            extra={k: v for k, v in r.items() if k not in {
                "status", "objective_value", "obj_value", "total_cost_jpy",
                "total_cost", "cost_breakdown", "electricity_cost_jpy",
                "diesel_cost_jpy", "demand_charge_jpy", "vehicle_fixed_cost_jpy",
                "co2_kg", "co2", "bev_trips", "ice_trips", "total_trips", "trips",
                "total_charging_kwh", "peak_charging_kw", "charging",
                "solve_time_sec", "solve_time", "mip_gap_pct", "mip_gap",
                "charging_schedule",
            }},
        )

    def _save_json(self, report: ExperimentReport, exp_id: str) -> Path:
        path = self.results_dir / f"exp_{exp_id}.json"
        # dataclass → dict（再帰的に変換）
        data = _dataclass_to_dict(report)
        data.pop("json_path", None)
        data.pop("md_path", None)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def _save_md(self, report: ExperimentReport, exp_id: str) -> Path:
        path = self.results_dir / f"exp_{exp_id}.md"
        path.write_text(report.markdown_text, encoding="utf-8")
        return path

    @staticmethod
    def _git_commit() -> str | None:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────────────
#  ユーティリティ
# ──────────────────────────────────────────────────────────────────────────────

def _dataclass_to_dict(obj: Any) -> Any:
    """dataclass を再帰的に dict に変換（Path は str に）"""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, list):
        return [_dataclass_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


# ──────────────────────────────────────────────────────────────────────────────
#  便利関数: run_simulation.py から呼べるワンライナー
# ──────────────────────────────────────────────────────────────────────────────

_default_logger: ExperimentLogger | None = None


def log_experiment(
    scenario: dict[str, Any],
    result: dict[str, Any],
    *,
    results_dir: str | Path = "results",
    method: str | None = None,
    seed: int | None = None,
    print_summary: bool = True,
) -> ExperimentReport:
    """
    ワンライナー呼び出し用。run_simulation.py の末尾に追記するだけで使える。

    例:
        from src.experiment_logger import log_experiment
        report = log_experiment(scenario, result, method="MILP")
        # → ターミナルにサマリを表示し results/ に JSON+MD を保存
    """
    global _default_logger
    if _default_logger is None or str(_default_logger.results_dir) != str(results_dir):
        _default_logger = ExperimentLogger(results_dir=results_dir)
    report = _default_logger.log(scenario, result, method=method, seed=seed)
    if print_summary:
        print(report.summary_text)
    return report


# ──────────────────────────────────────────────────────────────────────────────
#  CLI: 既存の result JSON を後からレポート化する
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="既存のシナリオ/結果 JSON から実験レポートを生成"
    )
    parser.add_argument("--scenario", type=Path, required=True, help="シナリオ JSON")
    parser.add_argument("--result",   type=Path, required=True, help="結果 JSON")
    parser.add_argument("--method",   default="MILP", help="手法名 (MILP/ALNS/…)")
    parser.add_argument("--seed",     type=int, default=None, help="乱数シード")
    parser.add_argument("--out",      type=Path, default=Path("results"),
                        help="出力ディレクトリ (default: results/)")
    args = parser.parse_args()

    with open(args.scenario) as f:
        sc = json.load(f)
    with open(args.result) as f:
        res = json.load(f)

    logger = ExperimentLogger(results_dir=args.out)
    report = logger.log(sc, res, method=args.method, seed=args.seed)
    print(report.summary_text)
    print(f"\nJSON → {report.json_path}")
    print(f"MD   → {report.md_path}")
