"""
model_factory.py — モード切替型モデル構築 (agent.md §2.4, v2 §16)

先行研究の「再現モード」と thesis 独自拡張を factory pattern で切り替える。

対応モード:
  mode_A_journey_charge       : §16.1  journey 後充電 decision (assignment 固定)
  mode_B_resource_assignment  : §16.2  vehicle-trip assignment + charging
  thesis_mode                 : §17    PV + demand charge + mixed fleet + etc.

使い方:
    model, vars = build_model_by_mode("mode_B_resource_assignment", data, ms, dp)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .data_schema import ProblemData
from .model_sets import ModelSets
from .parameter_builder import DerivedParams
from .milp_model import MILPResult, build_milp_model, extract_result

# ---------------------------------------------------------------------------
# Mode 定義
# ---------------------------------------------------------------------------

AVAILABLE_MODES = [
    "mode_A_journey_charge",
    "mode_B_resource_assignment",
    "thesis_mode",
    # v3 新モード (spec_v3 §8 / agent_route_editable §4)
    "mode_simple_reproduction",
    "mode_route_sensitivity",
    "mode_uncertainty_eval",
    "thesis_mode_route_editable",
    # v3 行路モード (spec_v3 §6)
    "mode_duty_constrained",
    # v4 解法分離モード — MILP/ALNS/ALNS+MILP 比較検証用
    "mode_milp_only",
    "mode_alns_only",
    "mode_alns_milp",
]

# 各モードのデフォルト制約フラグ
MODE_FLAGS: Dict[str, Dict[str, bool]] = {
    # Mode A: assignment 固定, 充電 decision のみ
    "mode_A_journey_charge": {
        "assignment": False,         # x は外部固定
        "soc": True,
        "charging": True,
        "charger_capacity": True,
        "energy_balance": True,
        "pv_grid": False,
        "battery_degradation": False,
        "v2g": False,
        "demand_charge": False,
    },
    # Mode B: vehicle-trip assignment + charging (基本モデル)
    "mode_B_resource_assignment": {
        "assignment": True,
        "soc": True,
        "charging": True,
        "charger_capacity": True,
        "energy_balance": True,
        "pv_grid": False,
        "battery_degradation": False,
        "v2g": False,
        "demand_charge": False,
    },
    # Thesis mode: 全フラグを data のフラグに従う
    "thesis_mode": None,  # → build_milp_model に None を渡し data.enable_* で決まる

    # --- v3 新モード (spec_v3 §8 / agent_route_editable §4) ---

    # 先行研究再現: 固定トリップ入力, 充電のみ最適化 (Level-0 エネルギーモデル)
    "mode_simple_reproduction": {
        "assignment": True,
        "soc": True,
        "charging": True,
        "charger_capacity": True,
        "energy_balance": True,
        "pv_grid": False,
        "battery_degradation": False,
        "v2g": False,
        "demand_charge": False,
    },

    # 路線長感度分析 (Chen et al. 2023 の距離スケーリング)
    "mode_route_sensitivity": {
        "assignment": True,
        "soc": True,
        "charging": True,
        "charger_capacity": True,
        "energy_balance": True,
        "pv_grid": False,
        "battery_degradation": False,
        "v2g": False,
        "demand_charge": False,
    },

    # 不確実性評価: シナリオサンプリング → ALNS ループ
    "mode_uncertainty_eval": {
        "assignment": True,
        "soc": True,
        "charging": True,
        "charger_capacity": True,
        "energy_balance": True,
        "pv_grid": False,
        "battery_degradation": False,
        "v2g": False,
        "demand_charge": False,
    },

    # 修論完全モード: route-detail 2層 + BEV/ICE 比較 + 全機能
    "thesis_mode_route_editable": None,  # → data.enable_* で制御

    # v3 行路制約モード: duty ベースの割当を強制
    "mode_duty_constrained": None,  # → data.enable_* + duty_assignment で制御

    # v4 解法分離モード (MILP/ALNS/ALNS+MILP 比較検証)
    # mode_milp_only: 既存 MILP モデルをそのまま解く (flags は外部設定で変更可)
    "mode_milp_only": None,  # → data.enable_* で制御

    # mode_alns_only: ALNS で便割当 → 簡易ヒューリスティック充電 (pipeline で dispatch)
    "mode_alns_only": None,  # → pipeline/solve.py で ALNS を呼び出し

    # mode_alns_milp: ALNS 割当 → MILP で充電/SOC 厳密最適化 (pipeline で dispatch)
    "mode_alns_milp": None,  # → pipeline/solve.py で ALNS+MILP を呼び出し
}

# 各モードの説明
MODE_DESCRIPTIONS: Dict[str, str] = {
    "mode_A_journey_charge": (
        "先行研究再現: journey 後充電 decision モデル (He et al. 2023, TRD 115)\n"
        "- vehicle-trip assignment は入力済み (固定)\n"
        "- 充電 decision のみ最適化\n"
        "- charger capacity, SOC, 電力量料金を考慮"
    ),
    "mode_B_resource_assignment": (
        "先行研究再現: resource assignment + charging station capacity (Chen et al. 2023, TRD 118)\n"
        "- vehicle-trip assignment を同時最適化\n"
        "- charger capacity 制約\n"
        "- SOC 遷移追跡"
    ),
    "thesis_mode": (
        "修論独自モード: PV + demand charge + mixed fleet + uncertainty\n"
        "- config の enable_* フラグに従って全機能を有効化\n"
        "- PV 自家消費、V2G、電池劣化、デマンド料金を選択的に追加"
    ),
    # v3 新モード説明
    "mode_simple_reproduction": (
        "先行研究再現・簡易モード (spec_v3 §8.1)\n"
        "- 外部固定トリップを直接入力 (route-detail 生成不要)\n"
        "- Level-0 エネルギーモデル (base_rate × distance)\n"
        "- PV/V2G/劣化/デマンド料金は無効"
    ),
    "mode_route_sensitivity": (
        "路線長感度分析モード (spec_v3 §8.2 / Chen et al. 2023)\n"
        "- route_length_multiplier でセグメント距離を均一スケーリング\n"
        "- エネルギー・コストへの感度を系統的に評価\n"
        "- 0.5〜2.0 の range でパラメトリックスイープ"
    ),
    "mode_uncertainty_eval": (
        "不確実性評価モード (spec_v3 §8.3)\n"
        "- ScenarioTripEnergy を n_scenarios 件生成\n"
        "- 各シナリオに対して ALNS を実行し分布を推定\n"
        "- Pareto フロンティア: 期待コスト vs SOC 違反確率"
    ),
    "thesis_mode_route_editable": (
        "修論完全モード: route-detail 2層構造 (spec_v3 §8.4 / agent_route_editable §4)\n"
        "- Layer A (route-detail) → Layer B (trip abstraction) パイプライン使用\n"
        "- BEV / ICE / HEV パワートレイン比較を同一路線データで実施\n"
        "- PV 自家消費、V2G、電池劣化、デマンド料金を全て有効化可能\n"
        "- route_edit_rules で路線・停留所・セグメントを動的編集"
    ),
    "mode_duty_constrained": (
        "行路制約モード (spec_v3 §6 行路設定表)\n"
        "- 行路 (vehicle_duties.csv) に基づく車両-トリップバンドリング\n"
        "- 各行路は 1 台の車両に排他的に割り当て\n"
        "- 行路内のトリップ順序・充電機会を尊重\n"
        "- 遅延耐性分析・ギャップ分析と連携"
    ),
    # v4 解法分離モード
    "mode_milp_only": (
        "MILP 専用モード (v4 解法分離)\n"
        "- 既存の MILP モデルをそのまま解く\n"
        "- model_factory の各種フラグ (充電/PV/行路/V2G 等) を外部設定で変更可能\n"
        "- Gurobi (MILP) の厳密解法を使用"
    ),
    "mode_alns_only": (
        "ALNS 専用モード (v4 解法分離)\n"
        "- 便割当を ALNS (破壊・修復オペレータ + SA) で探索\n"
        "- 充電スケジュールは簡易ヒューリスティックまたは内側 LP\n"
        "- 大規模問題で Gurobi MILP が時間切れになる場合に使用"
    ),
    "mode_alns_milp": (
        "ALNS+MILP ハイブリッドモード (v4 解法分離)\n"
        "- Phase 1: ALNS で便チェーン割当を探索\n"
        "- Phase 2: ALNS 割当を固定し MILP で充電/SOC/電力料金を厳密最適化\n"
        "- 合計コストが改善する場合のみ MILP 解を採用\n"
        "- 大規模問題と厳密解の両立を目指す"
    ),
}


def get_mode_flags(
    mode: str,
    data: ProblemData,
    overrides: Optional[Dict[str, bool]] = None,
) -> Optional[Dict[str, bool]]:
    """
    モード名から制約 ON/OFF フラグを返す。

    Parameters
    ----------
    mode      : モード名
    data      : ProblemData (thesis_mode ではフラグ参照)
    overrides : 任意の上書き

    Returns
    -------
    flags dict or None (→ build_milp_model のデフォルト動作)
    """
    if mode not in MODE_FLAGS:
        raise ValueError(f"不明なモード: {mode}. 選択可能: {AVAILABLE_MODES}")

    flags = MODE_FLAGS[mode]

    if flags is None:
        # thesis_mode: data のフラグに従う (build_milp_model では flags=None で全自動)
        if overrides:
            flags = {
                "assignment": True,
                "soc": True,
                "charging": True,
                "charger_capacity": True,
                "energy_balance": True,
                "pv_grid": data.enable_pv,
                "battery_degradation": data.enable_battery_degradation,
                "v2g": data.enable_v2g,
                "demand_charge": data.enable_demand_charge,
            }
            flags.update(overrides)
        return flags
    else:
        result = dict(flags)
        if overrides:
            result.update(overrides)
        return result


def build_model_by_mode(
    mode: str,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    fixed_assignment: Optional[Dict[str, List[str]]] = None,
    flag_overrides: Optional[Dict[str, bool]] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """
    モード名に基づいてモデルを構築する。

    Parameters
    ----------
    mode              : モード名
    data              : ProblemData
    ms                : ModelSets
    dp                : DerivedParams
    fixed_assignment  : mode_A 用の固定割当 {vehicle_id: [task_id, ...]}
    flag_overrides    : 制約フラグ上書き

    Returns
    -------
    (model, vars_dict)
    """
    flags = get_mode_flags(mode, data, flag_overrides)

    model, vars_ = build_milp_model(data, ms, dp, flags)

    # === v3 新モード固有の前処理 ===

    # mode_route_sensitivity: セグメント距離をスケーリング
    if mode == "mode_route_sensitivity":
        multiplier = getattr(data, "route_length_multiplier", 1.0)
        if multiplier != 1.0:
            for task in data.tasks:
                task.distance_km = getattr(task, "distance_km", 0.0) * multiplier
                task.energy_kwh = getattr(task, "energy_kwh", 0.0) * multiplier

    # thesis_mode_route_editable: 両パワートレインの cost を merged
    if mode == "thesis_mode_route_editable":
        # GeneratedTrip の BEV/ICE 両推定値は data.tasks に格納済み前提
        # (pipeline.build_inputs → pipeline.solve で注入)
        pass

    # mode_duty_constrained: 行路の duty_assignment を必ず有効化
    if mode == "mode_duty_constrained":
        data.duty_assignment_enabled = True

    # === Mode A: 割当を固定 ===
    if mode == "mode_A_journey_charge" and fixed_assignment:
        x = vars_["x_assign"]
        for k in ms.K_ALL:
            for r in ms.R:
                if r in fixed_assignment.get(k, []):
                    model.addConstr(x[k, r] == 1, name=f"fix_assign_{k}_{r}")
                else:
                    model.addConstr(x[k, r] == 0, name=f"fix_noassign_{k}_{r}")
        # u_vehicle も固定
        u = vars_.get("u_vehicle")
        if u is not None:
            for k in ms.K_ALL:
                if k in fixed_assignment and fixed_assignment[k]:
                    model.addConstr(u[k] == 1, name=f"fix_use_{k}")
                else:
                    model.addConstr(u[k] == 0, name=f"fix_nouse_{k}")
        model.update()

    return model, vars_


def generate_greedy_assignment(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
) -> Dict[str, List[str]]:
    """
    mode_A 用のグリーディ割当を生成する。
    タスクを開始時刻順にソートし、時間重複しないバスに貪欲割当。

    Returns
    -------
    {vehicle_id: [task_id, ...]}
    """
    assignment: Dict[str, List[str]] = {k: [] for k in ms.K_ALL}
    sorted_tasks = sorted(data.tasks, key=lambda t: t.start_time_idx)

    for task in sorted_tasks:
        best_k = None
        best_load = float("inf")

        for k in ms.K_ALL:
            # 車種チェック
            rvt = (task.required_vehicle_type or "").upper()
            veh = dp.vehicle_lut[k]
            if rvt and rvt != veh.vehicle_type:
                continue

            # 互換チェック
            if ms.vehicle_task_feasible.get(k) and task.task_id not in ms.vehicle_task_feasible[k]:
                continue

            # 重複チェック
            conflict = False
            for r in assignment[k]:
                t_ex = dp.task_lut[r]
                if not (t_ex.end_time_idx < task.start_time_idx or task.end_time_idx < t_ex.start_time_idx):
                    conflict = True
                    break
            if conflict:
                continue

            load = sum(dp.task_energy_bev.get(r, 0) for r in assignment[k])
            if load < best_load:
                best_load = load
                best_k = k

        if best_k is not None:
            assignment[best_k].append(task.task_id)

    return assignment
