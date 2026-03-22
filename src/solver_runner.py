"""
solver_runner.py — MILP ソルバー実行管理

仕様書 §14.5 担当:
  - solver parameter 設定 (MIPGap, TimeLimit, Threads, Presolve)
  - モデル構築 → 最適化 → 結果取得・例外処理

使用例::

    from src.solver_runner import run_milp
    result = run_milp("config/experiment_config.json")
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import gurobipy as gp
    from gurobipy import GRB
    _GUROBI_AVAILABLE = True
except (ImportError, Exception):
    _GUROBI_AVAILABLE = False

from .data_loader import load_problem_data
from .data_schema import ProblemData
from .milp_model import MILPResult, build_milp_model, extract_result, _ensure_gurobi
from .model_sets import ModelSets, build_model_sets
from .parameter_builder import DerivedParams, build_derived_params


def is_gurobi_available() -> bool:
    """Check if gurobipy is available, retrying import if it failed at startup."""
    global _GUROBI_AVAILABLE
    if _GUROBI_AVAILABLE:
        return True
    try:
        _ensure_gurobi()
        _GUROBI_AVAILABLE = True
        return True
    except Exception:
        return False


def run_milp(
    config_path: str | Path,
    time_limit_sec: float = 300.0,
    mip_gap: float = 0.01,
    threads: int = 0,
    presolve: int = -1,
    gurobi_seed: Optional[int] = 42,
    verbose: bool = False,
    flags: Optional[Dict[str, bool]] = None,
) -> MILPResult:
    """
    config.json を起点に MILP を構築・求解して結果を返す。

    Parameters
    ----------
    config_path    : str | Path
        config/experiment_config.json のパス
    time_limit_sec : float
        Gurobi タイムリミット [秒]
    mip_gap        : float
        MIP ギャップ閾値
    threads        : int
        スレッド数 (0 = 自動)
    presolve       : int
        プリソルブ設定 (-1 = 自動)
    verbose        : bool
        Gurobi ログ出力
    flags          : dict, optional
        制約 ON/OFF フラグ

    Returns
    -------
    MILPResult
    """
    if not is_gurobi_available():
        return MILPResult(
            status="GUROBI_UNAVAILABLE",
            infeasibility_info="gurobipy がインストールされていません。",
        )

    # --- データ読込 ---
    data = load_problem_data(config_path)

    # --- 集合・派生パラメータ ---
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    return run_milp_from_data(
        data=data, ms=ms, dp=dp,
        time_limit_sec=time_limit_sec,
        mip_gap=mip_gap, threads=threads,
        presolve=presolve, gurobi_seed=gurobi_seed, verbose=verbose,
        flags=flags,
    )


def run_milp_from_data(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    time_limit_sec: float = 300.0,
    mip_gap: float = 0.01,
    threads: int = 0,
    presolve: int = -1,
    gurobi_seed: Optional[int] = 42,
    verbose: bool = False,
    flags: Optional[Dict[str, bool]] = None,
) -> MILPResult:
    """
    ProblemData / ModelSets / DerivedParams が揃っている場合の
    ダイレクト呼び出し。

    Returns
    -------
    MILPResult
    """
    if not is_gurobi_available():
        return MILPResult(status="GUROBI_UNAVAILABLE")

    # --- モデル構築 ---
    try:
        model, vars_ = build_milp_model(data, ms, dp, flags)
    except Exception as e:
        return MILPResult(status="BUILD_ERROR", infeasibility_info=str(e))

    # --- ソルバーパラメータ設定 ---
    model.Params.OutputFlag = 1 if verbose else 0
    model.Params.TimeLimit  = time_limit_sec
    model.Params.MIPGap     = mip_gap
    if gurobi_seed is not None:
        model.Params.Seed = int(gurobi_seed)
    if threads > 0:
        model.Params.Threads = threads
    if presolve >= 0:
        model.Params.Presolve = presolve

    # --- 求解 ---
    t_start = time.perf_counter()
    try:
        model.optimize()
    except gp.GurobiError as e:
        return MILPResult(status="GUROBI_ERROR", infeasibility_info=str(e))
    elapsed = time.perf_counter() - t_start

    # --- 結果抽出 ---
    return extract_result(model, data, ms, dp, vars_, elapsed)
