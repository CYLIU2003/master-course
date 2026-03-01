"""
src.pipeline.logger — 計算結果の記録と比較モジュール

全ソルバーモード (MILP / ALNS / ALNS+MILP) に共通の結果記録機能を提供。
CSV または SQLite に追記保存し、Jupyter Notebook 等で横並び比較できる。

Usage:
    from src.pipeline.logger import ExperimentLogger, record_result
    logger = ExperimentLogger("outputs/experiment_log.csv")
    logger.record(result_record)
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 結果レコード
# ---------------------------------------------------------------------------

@dataclass
class ResultRecord:
    """1 回の実験結果を表すレコード。"""

    # --- メタ情報 ---
    timestamp: str = ""
    run_id: str = ""
    config_path: str = ""

    # --- 問題規模 ---
    n_vehicles: int = 0
    n_vehicles_bev: int = 0
    n_vehicles_ice: int = 0
    n_tasks: int = 0
    n_chargers: int = 0
    n_sites: int = 0
    n_periods: int = 0
    delta_t_hour: float = 0.0

    # --- 解法情報 ---
    method: str = ""                  # "MILP" | "ALNS" | "ALNS+MILP"
    mode: str = ""                    # model_factory のモード名
    solver_status: str = ""

    # --- MILP 関連 ---
    milp_time_limit_sec: float = 0.0
    milp_mip_gap_setting: float = 0.0
    milp_mip_gap_actual: Optional[float] = None
    milp_flags: str = ""              # JSON 文字列

    # --- ALNS 関連 ---
    alns_max_iterations: int = 0
    alns_max_no_improve: int = 0
    alns_init_temp: float = 0.0
    alns_cooling_rate: float = 0.0
    alns_destroy_ratio_min: float = 0.0
    alns_destroy_ratio_max: float = 0.0
    alns_iterations_executed: int = 0

    # --- 計算時間 ---
    total_time_sec: float = 0.0
    alns_time_sec: float = 0.0
    milp_time_sec: float = 0.0

    # --- 目的関数・コスト ---
    objective_value: Optional[float] = None
    total_operating_cost: float = 0.0
    electricity_cost: float = 0.0
    demand_charge_cost: float = 0.0
    fuel_cost: float = 0.0
    degradation_cost: float = 0.0
    deadhead_cost: float = 0.0
    unserved_penalty: float = 0.0

    # --- KPI ---
    served_task_ratio: float = 0.0
    n_unserved_tasks: int = 0
    total_grid_kwh: float = 0.0
    total_pv_kwh: float = 0.0
    pv_self_consumption_ratio: float = 0.0
    peak_demand_kw: float = 0.0
    total_co2_kg: float = 0.0
    soc_min_kwh: float = 0.0
    n_soc_violations: int = 0
    vehicle_utilization: float = 0.0
    charger_utilization: float = 0.0
    n_vehicles_used: int = 0

    # --- フラグ ---
    enable_pv: bool = False
    enable_v2g: bool = False
    enable_demand_charge: bool = False
    enable_battery_degradation: bool = False

    # --- 自由メモ ---
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換。"""
        return asdict(self)


# ---------------------------------------------------------------------------
# CSV 列定義 (順序固定)
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "timestamp", "run_id", "config_path",
    "n_vehicles", "n_vehicles_bev", "n_vehicles_ice",
    "n_tasks", "n_chargers", "n_sites", "n_periods", "delta_t_hour",
    "method", "mode", "solver_status",
    "milp_time_limit_sec", "milp_mip_gap_setting", "milp_mip_gap_actual", "milp_flags",
    "alns_max_iterations", "alns_max_no_improve", "alns_init_temp",
    "alns_cooling_rate", "alns_destroy_ratio_min", "alns_destroy_ratio_max",
    "alns_iterations_executed",
    "total_time_sec", "alns_time_sec", "milp_time_sec",
    "objective_value", "total_operating_cost",
    "electricity_cost", "demand_charge_cost", "fuel_cost",
    "degradation_cost", "deadhead_cost", "unserved_penalty",
    "served_task_ratio", "n_unserved_tasks",
    "total_grid_kwh", "total_pv_kwh", "pv_self_consumption_ratio",
    "peak_demand_kw", "total_co2_kg",
    "soc_min_kwh", "n_soc_violations",
    "vehicle_utilization", "charger_utilization", "n_vehicles_used",
    "enable_pv", "enable_v2g", "enable_demand_charge", "enable_battery_degradation",
    "notes",
]


# ---------------------------------------------------------------------------
# ExperimentLogger
# ---------------------------------------------------------------------------

class ExperimentLogger:
    """CSV / SQLite への結果追記ロガー。

    Parameters
    ----------
    csv_path : str or Path
        CSV ファイルパス (自動作成・追記)
    sqlite_path : str or Path or None
        SQLite パス (None なら SQLite 非使用)
    """

    def __init__(
        self,
        csv_path: str | Path = "outputs/experiment_log.csv",
        sqlite_path: Optional[str | Path] = "outputs/experiment_log.sqlite",
    ):
        self.csv_path = Path(csv_path)
        self.sqlite_path = Path(sqlite_path) if sqlite_path else None
        self._ensure_csv()
        if self.sqlite_path:
            self._ensure_sqlite()

    # ---- CSV ----

    def _ensure_csv(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
                writer.writeheader()

    def _append_csv(self, rec: ResultRecord) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writerow(rec.to_dict())

    # ---- SQLite ----

    def _ensure_sqlite(self) -> None:
        if not self.sqlite_path:
            return
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sqlite_path))
        c = conn.cursor()
        cols = ", ".join(f'"{col}" TEXT' for col in _CSV_COLUMNS)
        c.execute(f"CREATE TABLE IF NOT EXISTS experiments ({cols})")
        conn.commit()
        conn.close()

    def _insert_sqlite(self, rec: ResultRecord) -> None:
        if not self.sqlite_path:
            return
        conn = sqlite3.connect(str(self.sqlite_path))
        c = conn.cursor()
        d = rec.to_dict()
        placeholders = ", ".join(["?"] * len(_CSV_COLUMNS))
        col_names = ", ".join(f'"{col}"' for col in _CSV_COLUMNS)
        values = [str(d.get(col, "")) for col in _CSV_COLUMNS]
        c.execute(f"INSERT INTO experiments ({col_names}) VALUES ({placeholders})", values)
        conn.commit()
        conn.close()

    # ---- 公開 API ----

    def record(self, rec: ResultRecord) -> None:
        """結果レコードを CSV と SQLite に追記する。"""
        if not rec.timestamp:
            rec.timestamp = datetime.now().isoformat()
        if not rec.run_id:
            rec.run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self._append_csv(rec)
        if self.sqlite_path:
            self._insert_sqlite(rec)

    def load_csv(self):
        """CSV を pandas DataFrame として読み込む。"""
        import pandas as pd
        return pd.read_csv(self.csv_path)

    def load_sqlite(self, query: str = "SELECT * FROM experiments"):
        """SQLite をクエリして pandas DataFrame として返す。"""
        import pandas as pd
        conn = sqlite3.connect(str(self.sqlite_path))
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df


# ---------------------------------------------------------------------------
# ヘルパー: MILPResult / SimulationResult → ResultRecord
# ---------------------------------------------------------------------------

def build_result_record(
    *,
    method: str,
    mode: str,
    milp_result: Any = None,
    sim_result: Any = None,
    data: Any = None,
    ms: Any = None,
    config_path: str = "",
    alns_params: Any = None,
    milp_flags: Optional[Dict[str, bool]] = None,
    alns_time_sec: float = 0.0,
    milp_time_sec: float = 0.0,
    total_time_sec: float = 0.0,
    alns_iterations_executed: int = 0,
    notes: str = "",
) -> ResultRecord:
    """各コンポーネントの結果から ResultRecord を構築する."""
    rec = ResultRecord(
        config_path=config_path,
        method=method,
        mode=mode,
        total_time_sec=total_time_sec,
        alns_time_sec=alns_time_sec,
        milp_time_sec=milp_time_sec,
        alns_iterations_executed=alns_iterations_executed,
        notes=notes,
    )

    # --- 問題規模 ---
    if data is not None:
        rec.n_vehicles = len(getattr(data, "vehicles", []))
        rec.n_tasks = len(getattr(data, "tasks", []))
        rec.n_chargers = len(getattr(data, "chargers", []))
        rec.n_sites = len(getattr(data, "sites", []))
        rec.n_periods = getattr(data, "num_periods", 0)
        rec.delta_t_hour = getattr(data, "delta_t_hour", 0.0)
        rec.enable_pv = getattr(data, "enable_pv", False)
        rec.enable_v2g = getattr(data, "enable_v2g", False)
        rec.enable_demand_charge = getattr(data, "enable_demand_charge", False)
        rec.enable_battery_degradation = getattr(data, "enable_battery_degradation", False)

    if ms is not None:
        rec.n_vehicles_bev = len(getattr(ms, "K_BEV", []))
        rec.n_vehicles_ice = len(getattr(ms, "K_ICE", []))

    # --- MILP 結果 ---
    if milp_result is not None:
        rec.solver_status = getattr(milp_result, "status", "")
        rec.objective_value = getattr(milp_result, "objective_value", None)
        rec.milp_mip_gap_actual = getattr(milp_result, "mip_gap", None)
        rec.n_unserved_tasks = len(getattr(milp_result, "unserved_tasks", []))
        # コスト内訳
        ob = getattr(milp_result, "obj_breakdown", {})
        rec.electricity_cost = ob.get("electricity_cost", 0.0)
        rec.demand_charge_cost = ob.get("demand_charge_cost", 0.0)
        rec.fuel_cost = ob.get("fuel_cost", 0.0)
        rec.degradation_cost = ob.get("battery_degradation_cost", 0.0)
        rec.deadhead_cost = ob.get("deadhead_cost", 0.0)
        rec.unserved_penalty = ob.get("unserved_penalty", 0.0)
        # 車両使用数
        assignment = getattr(milp_result, "assignment", {})
        rec.n_vehicles_used = sum(1 for v, ts in assignment.items() if ts)
        if not rec.milp_time_sec:
            rec.milp_time_sec = getattr(milp_result, "solve_time_sec", 0.0)

    # --- シミュレーション結果 ---
    if sim_result is not None:
        rec.total_operating_cost = getattr(sim_result, "total_operating_cost", 0.0)
        rec.total_grid_kwh = getattr(sim_result, "total_grid_kwh", 0.0)
        rec.total_pv_kwh = getattr(sim_result, "total_pv_kwh", 0.0)
        rec.pv_self_consumption_ratio = getattr(sim_result, "pv_self_consumption_ratio", 0.0)
        rec.peak_demand_kw = getattr(sim_result, "peak_demand_kw", 0.0)
        rec.total_co2_kg = getattr(sim_result, "total_co2_kg", 0.0)
        rec.soc_min_kwh = getattr(sim_result, "soc_min_kwh", 0.0)
        rec.n_soc_violations = len(getattr(sim_result, "soc_violations", []))
        rec.served_task_ratio = getattr(sim_result, "served_task_ratio", 0.0)
        rec.vehicle_utilization = getattr(sim_result, "vehicle_utilization", 0.0)
        rec.charger_utilization = getattr(sim_result, "charger_utilization", 0.0)

    # --- ALNS パラメータ ---
    if alns_params is not None:
        rec.alns_max_iterations = getattr(alns_params, "max_iterations", 0)
        rec.alns_max_no_improve = getattr(alns_params, "max_no_improve", 0)
        rec.alns_init_temp = getattr(alns_params, "init_temp", 0.0)
        rec.alns_cooling_rate = getattr(alns_params, "cooling_rate", 0.0)
        rec.alns_destroy_ratio_min = getattr(alns_params, "destroy_ratio_min", 0.0)
        rec.alns_destroy_ratio_max = getattr(alns_params, "destroy_ratio_max", 0.0)

    # --- MILP フラグ ---
    if milp_flags is not None:
        rec.milp_flags = json.dumps(milp_flags, ensure_ascii=False)

    return rec


def record_result(
    logger: ExperimentLogger,
    **kwargs,
) -> ResultRecord:
    """build_result_record → logger.record を一括で行うショートカット。"""
    rec = build_result_record(**kwargs)
    logger.record(rec)
    return rec
