"""
visualization.py — matplotlib 可視化ユーティリティ

仕様書 §13.2 担当:
  - SOC 推移グラフ
  - 受電電力時系列グラフ
  - PV 利用率グラフ
  - 充電器利用率ヒートマップ
  - ガントチャート風の車両運行図
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    _MPL_AVAILABLE = True
    # 日本語フォント対応
    try:
        import japanize_matplotlib  # noqa: F401
    except ImportError:
        pass
except ImportError:
    _MPL_AVAILABLE = False

from .data_schema import ProblemData
from .milp_model import MILPResult
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_pv_gen
from .simulator import SimulationResult


def _time_labels(num_periods: int, start_hour: int = 6, delta_min: int = 15) -> List[str]:
    labels = []
    for i in range(num_periods):
        total = start_hour * 60 + i * delta_min
        labels.append(f"{total // 60:02d}:{total % 60:02d}")
    return labels


# ---------------------------------------------------------------------------
# §13.2 SOC 推移グラフ
# ---------------------------------------------------------------------------

def plot_soc(
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
    data: ProblemData,
    save_path: Optional[Path] = None,
) -> Optional[Any]:
    if not _MPL_AVAILABLE:
        return None
    labels = _time_labels(data.num_periods, delta_min=int(data.delta_t_min))
    fig, ax = plt.subplots(figsize=(12, 5))

    for k in ms.K_BEV:
        soc = milp.soc_series.get(k, [])
        if soc:
            ax.plot(range(len(soc)), soc, label=k)
            veh = dp.vehicle_lut[k]
            ax.axhline(veh.soc_min or 0, color="red", linestyle="--", alpha=0.3)
            ax.axhline(veh.soc_max or 200, color="blue", linestyle="--", alpha=0.3)

    ax.set_title("SOC 推移 [kWh]")
    ax.set_xlabel("time_idx")
    ax.set_ylabel("SOC [kWh]")
    ax.legend(loc="upper right")
    ax.set_xticks(range(0, data.num_periods, max(1, data.num_periods // 16)))
    ax.set_xticklabels(labels[:: max(1, data.num_periods // 16)], rotation=45)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return None
    return fig


# ---------------------------------------------------------------------------
# §13.2 受電電力時系列グラフ
# ---------------------------------------------------------------------------

def plot_grid_power(
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
    data: ProblemData,
    save_path: Optional[Path] = None,
) -> Optional[Any]:
    if not _MPL_AVAILABLE:
        return None
    labels = _time_labels(data.num_periods, delta_min=int(data.delta_t_min))
    fig, ax = plt.subplots(figsize=(12, 4))

    for site_id, series in milp.grid_import_kw.items():
        ax.plot(range(len(series)), series, label=f"系統受電 {site_id}")

    if data.enable_pv:
        for site_id in ms.I_CHARGE:
            pv_series = milp.pv_used_kw.get(site_id, [])
            if pv_series:
                ax.fill_between(range(len(pv_series)), pv_series,
                                alpha=0.3, label=f"PV 自家消費 {site_id}")

    ax.set_title("受電電力推移 [kW]")
    ax.set_xlabel("time_idx")
    ax.set_ylabel("電力 [kW]")
    ax.legend()
    ax.set_xticks(range(0, data.num_periods, max(1, data.num_periods // 16)))
    ax.set_xticklabels(labels[:: max(1, data.num_periods // 16)], rotation=45)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return None
    return fig


# ---------------------------------------------------------------------------
# §13.2 充電器利用率ヒートマップ
# ---------------------------------------------------------------------------

def plot_charger_heatmap(
    ms: ModelSets,
    milp: MILPResult,
    data: ProblemData,
    save_path: Optional[Path] = None,
) -> Optional[Any]:
    if not _MPL_AVAILABLE:
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    C = ms.C
    T = ms.T
    if not C or not T:
        return None

    matrix = np.zeros((len(C), len(T)))
    for i_c, c in enumerate(C):
        for k in ms.K_BEV:
            series = milp.charge_schedule.get(k, {}).get(c, [])
            for t_idx, val in enumerate(series):
                if t_idx < len(T):
                    matrix[i_c, t_idx] += val

    fig, ax = plt.subplots(figsize=(14, max(2, len(C) * 0.8)))
    im = ax.imshow(matrix, aspect="auto", cmap="Greens", interpolation="nearest")
    ax.set_yticks(range(len(C)))
    ax.set_yticklabels(C)
    ax.set_xlabel("time_idx")
    ax.set_title("充電器利用ヒートマップ (各スロットの充電車両数)")
    plt.colorbar(im, ax=ax)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return None
    return fig


# ---------------------------------------------------------------------------
# §13.2 ガントチャート風の車両運行図
# ---------------------------------------------------------------------------

def plot_gantt(
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
    data: ProblemData,
    save_path: Optional[Path] = None,
) -> Optional[Any]:
    if not _MPL_AVAILABLE:
        return None

    K_ALL = ms.K_ALL
    fig, ax = plt.subplots(figsize=(14, max(3, len(K_ALL) * 0.7)))

    colors = {"running": "#4CAF50", "charging": "#2196F3", "idle": "#EEEEEE"}
    T = ms.T

    for y_pos, k in enumerate(K_ALL):
        assigned = milp.assignment.get(k, [])

        # 運行区間
        for r_id in assigned:
            task = dp.task_lut.get(r_id)
            if task:
                ax.barh(
                    y_pos,
                    task.end_time_idx - task.start_time_idx + 1,
                    left=task.start_time_idx,
                    height=0.5,
                    color=colors["running"],
                    edgecolor="white",
                )

        # 充電区間
        for c in ms.C:
            z_series = milp.charge_schedule.get(k, {}).get(c, [])
            start = None
            for t_idx, val in enumerate(z_series):
                if val > 0 and start is None:
                    start = t_idx
                elif val == 0 and start is not None:
                    ax.barh(y_pos, t_idx - start, left=start,
                            height=0.3, color=colors["charging"], alpha=0.8)
                    start = None
            if start is not None:
                ax.barh(y_pos, len(z_series) - start, left=start,
                        height=0.3, color=colors["charging"], alpha=0.8)

    ax.set_yticks(range(len(K_ALL)))
    ax.set_yticklabels(K_ALL)
    ax.set_xlabel("time_idx")
    ax.set_title("車両運行ガントチャート")

    legend_items = [
        mpatches.Patch(color=colors["running"], label="運行"),
        mpatches.Patch(color=colors["charging"], label="充電"),
    ]
    ax.legend(handles=legend_items, loc="upper right")
    ax.set_xlim(0, len(T))
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        return None
    return fig


# ---------------------------------------------------------------------------
# 一括保存
# ---------------------------------------------------------------------------

def save_all_plots(
    run_dir: Path,
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
    sim: SimulationResult,
    data: ProblemData,
) -> None:
    """全グラフを run_dir に保存する"""
    plot_soc(ms, dp, milp, data, save_path=run_dir / "soc_timeseries.png")
    plot_grid_power(ms, dp, milp, data, save_path=run_dir / "grid_power.png")
    plot_charger_heatmap(ms, milp, data, save_path=run_dir / "charger_heatmap.png")
    plot_gantt(ms, dp, milp, data, save_path=run_dir / "gantt.png")
