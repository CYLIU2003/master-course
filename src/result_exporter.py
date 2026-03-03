"""
result_exporter.py — CSV / JSON / Markdown / Excel 出力

仕様書 §13, §14.7 担当:
  - summary.json            (§13.1.1)
  - vehicle_schedule.csv    (§13.1.2)
  - charging_schedule.csv   (§13.1.3)
  - site_power_balance.csv  (§13.1.4)
  - experiment_report.md    (§13.1.5)
  - results.xlsx            (Excel multi-sheet export)
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data_schema import ProblemData
from .milp_model import MILPResult
from .model_sets import ModelSets
from .parameter_builder import DerivedParams, get_grid_price
from .simulator import SimulationResult


def _make_run_dir(output_root: str | Path) -> Path:
    """outputs/run_yyyymmdd_hhmm/ ディレクトリを作成して返す"""
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    run_dir = Path(output_root) / f"run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def export_all(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    output_root: str | Path = "outputs",
    run_label: Optional[str] = None,
) -> Path:
    """
    全出力ファイルを一括生成する。

    Returns
    -------
    Path
        出力ディレクトリ
    """
    run_dir = _make_run_dir(output_root)

    export_summary_json(run_dir, milp_result, sim_result, run_label)
    export_vehicle_schedule(run_dir, data, ms, dp, milp_result)
    export_charging_schedule(run_dir, ms, milp_result)
    export_site_power_balance(run_dir, ms, milp_result, sim_result, data)
    export_experiment_report(run_dir, data, ms, milp_result, sim_result, run_label)
    try:
        export_excel(data, ms, dp, milp_result, sim_result, run_dir, run_label)
    except ImportError:
        pass  # openpyxl 未インストール時はスキップ

    return run_dir


# ---------------------------------------------------------------------------
# §13.1.1 summary.json
# ---------------------------------------------------------------------------


def export_summary_json(
    run_dir: Path,
    milp: MILPResult,
    sim: SimulationResult,
    run_label: Optional[str] = None,
) -> None:
    summary = {
        "run_label": run_label or "",
        "timestamp": datetime.now().isoformat(),
        "status": milp.status,
        "objective_value": milp.objective_value,
        "mip_gap": milp.mip_gap,
        "solve_time_sec": milp.solve_time_sec,
        "infeasibility_info": milp.infeasibility_info,
        "cost_breakdown": {
            "total_operating_cost": sim.total_operating_cost,
            "electricity_cost": sim.total_energy_cost,
            "demand_charge": sim.total_demand_charge,
            "fuel_cost": sim.total_fuel_cost,
            "degradation_cost": sim.total_degradation_cost,
        },
        "kpi": {
            "served_task_ratio": sim.served_task_ratio,
            "unserved_tasks": sim.unserved_tasks,
            "total_grid_kwh": sim.total_grid_kwh,
            "total_pv_kwh": sim.total_pv_kwh,
            "pv_self_consumption_ratio": sim.pv_self_consumption_ratio,
            "peak_demand_kw": sim.peak_demand_kw,
            "total_co2_kg": sim.total_co2_kg,
            "soc_min_kwh": sim.soc_min_kwh,
            "soc_violations": sim.soc_violations,
            "vehicle_utilization": sim.vehicle_utilization,
            "charger_utilization": sim.charger_utilization,
        },
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# §13.1.2 vehicle_schedule.csv
# ---------------------------------------------------------------------------


def export_vehicle_schedule(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp: MILPResult,
) -> None:
    rows = []
    for k in ms.K_ALL:
        assigned = milp.assignment.get(k, [])
        if assigned:
            for r_id in assigned:
                task = dp.task_lut.get(r_id)
                rows.append(
                    {
                        "vehicle_id": k,
                        "vehicle_type": dp.vehicle_lut[k].vehicle_type,
                        "task_id": r_id,
                        "start_time_idx": task.start_time_idx if task else "",
                        "end_time_idx": task.end_time_idx if task else "",
                        "origin": task.origin if task else "",
                        "destination": task.destination if task else "",
                        "distance_km": task.distance_km if task else "",
                        "energy_kwh_bev": task.energy_required_kwh_bev if task else "",
                    }
                )
        else:
            rows.append(
                {
                    "vehicle_id": k,
                    "vehicle_type": dp.vehicle_lut[k].vehicle_type,
                    "task_id": "(unassigned)",
                    "start_time_idx": "",
                    "end_time_idx": "",
                    "origin": "",
                    "destination": "",
                    "distance_km": "",
                    "energy_kwh_bev": "",
                }
            )

    _write_csv(run_dir / "vehicle_schedule.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.3 charging_schedule.csv
# ---------------------------------------------------------------------------


def export_charging_schedule(
    run_dir: Path,
    ms: ModelSets,
    milp: MILPResult,
) -> None:
    rows = []
    for k in ms.K_BEV:
        soc_series = milp.soc_series.get(k, [])
        for c in ms.C:
            pwr_series = milp.charge_power_kw.get(k, {}).get(c, [0.0] * len(ms.T))
            z_series = milp.charge_schedule.get(k, {}).get(c, [0] * len(ms.T))
            for t_idx in ms.T:
                soc_val = soc_series[t_idx] if t_idx < len(soc_series) else ""
                rows.append(
                    {
                        "vehicle_id": k,
                        "charger_id": c,
                        "time_idx": t_idx,
                        "z_charge": z_series[t_idx] if t_idx < len(z_series) else 0,
                        "p_charge_kw": pwr_series[t_idx]
                        if t_idx < len(pwr_series)
                        else 0.0,
                        "soc_kwh": soc_val,
                    }
                )

    _write_csv(run_dir / "charging_schedule.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.4 site_power_balance.csv
# ---------------------------------------------------------------------------


def export_site_power_balance(
    run_dir: Path,
    ms: ModelSets,
    milp: MILPResult,
    sim: SimulationResult,
    data: ProblemData,
) -> None:
    rows = []
    for site_id in ms.I_CHARGE:
        grid_series = milp.grid_import_kw.get(site_id, [0.0] * len(ms.T))
        pv_series = milp.pv_used_kw.get(site_id, [0.0] * len(ms.T))
        for t_idx in ms.T:
            rows.append(
                {
                    "site_id": site_id,
                    "time_idx": t_idx,
                    "grid_import_kw": grid_series[t_idx]
                    if t_idx < len(grid_series)
                    else 0.0,
                    "pv_used_kw": pv_series[t_idx] if t_idx < len(pv_series) else 0.0,
                    "peak_demand_kw": milp.peak_demand_kw.get(site_id, 0.0),
                }
            )

    _write_csv(run_dir / "site_power_balance.csv", rows)


# ---------------------------------------------------------------------------
# §13.1.5 experiment_report.md
# ---------------------------------------------------------------------------


def export_experiment_report(
    run_dir: Path,
    data: ProblemData,
    ms: ModelSets,
    milp: MILPResult,
    sim: SimulationResult,
    run_label: Optional[str] = None,
) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 実験レポート — {run_label or ts}",
        "",
        "## 条件一覧",
        f"- 実行日時: {ts}",
        f"- 車両数 BEV: {len(ms.K_BEV)}, ICE: {len(ms.K_ICE)}",
        f"- タスク数: {len(ms.R)}",
        f"- 充電器数: {len(ms.C)}",
        f"- 時間刻み: {data.delta_t_min:.0f} 分 ({data.num_periods} スロット)",
        f"- PV 有効: {data.enable_pv}",
        f"- V2G 有効: {data.enable_v2g}",
        f"- デマンド料金有効: {data.enable_demand_charge}",
        "",
        "## ソルバー結果",
        f"- ステータス: **{milp.status}**",
        f"- 目的関数値: {milp.objective_value}",
        f"- MIP ギャップ: {milp.mip_gap}",
        f"- 計算時間: {milp.solve_time_sec:.2f} 秒",
        "",
        "## 目的関数内訳",
        f"| 項目 | 値 [円] |",
        f"|------|---------|",
        f"| 電力量料金 | {sim.total_energy_cost:,.0f} |",
        f"| デマンド料金 | {sim.total_demand_charge:,.0f} |",
        f"| 燃料費 | {sim.total_fuel_cost:,.0f} |",
        f"| 電池劣化 | {sim.total_degradation_cost:,.0f} |",
        f"| **合計** | **{sim.total_operating_cost:,.0f}** |",
        "",
        "## 主要 KPI",
        f"- タスク担当率: {sim.served_task_ratio * 100:.1f} %",
        f"- 未担当タスク: {sim.unserved_tasks or 'なし'}",
        f"- 系統受電量: {sim.total_grid_kwh:.2f} kWh",
        f"- PV 利用量: {sim.total_pv_kwh:.2f} kWh",
        f"- PV 自家消費率: {sim.pv_self_consumption_ratio * 100:.1f} %",
        f"- ピーク需要: {sim.peak_demand_kw:.2f} kW",
        f"- CO2 排出: {sim.total_co2_kg:.2f} kg",
        f"- 最低 SOC: {sim.soc_min_kwh:.2f} kWh",
        f"- SOC 違反: {len(sim.soc_violations)} 件",
        "",
        "## infeasible 情報",
        milp.infeasibility_info or "なし",
        "",
        "---",
        "*本レポートは result_exporter.py により自動生成されました。*",
    ]
    with open(run_dir / "experiment_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Excel multi-sheet export (openpyxl)
# ---------------------------------------------------------------------------


def export_excel(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    run_dir: Path,
    run_label: Optional[str] = None,
) -> Path:
    """
    openpyxl を使い、results.xlsx を run_dir 内に生成する。

    シート構成
    ----------
    Summary          : KPI サマリー（縦持ちキー/値テーブル）
    KPIs             : 10 KPI 一覧（数値）
    VehicleSchedule  : vehicle_schedule.csv と同内容
    ChargingSchedule : charging_schedule.csv と同内容（先頭 10,000 行）
    SitePowerBalance : site_power_balance.csv と同内容

    Returns
    -------
    Path
        生成した xlsx ファイルのパス
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise ImportError(
            "Excel エクスポートには openpyxl が必要です: pip install openpyxl"
        ) from exc

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # デフォルトシートを削除

    # ---- ヘルパー: シートにテーブルを書く -----------------------------------
    def _write_sheet(
        ws: "openpyxl.worksheet.worksheet.Worksheet",
        headers: List[str],
        rows_data: List[List[Any]],
        freeze: bool = True,
    ) -> None:
        header_fill = PatternFill(fill_type="solid", fgColor="1F5C99")
        header_font = Font(bold=True, color="FFFFFF")
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for row_idx, row_vals in enumerate(rows_data, 2):
            for col_idx, val in enumerate(row_vals, 1):
                ws.cell(row=row_idx, column=col_idx, value=val)
        # 列幅自動調整（最大 40 文字）
        for col_idx, h in enumerate(headers, 1):
            col_letter = get_column_letter(col_idx)
            max_len = max(
                len(str(h)),
                max((len(str(r[col_idx - 1])) for r in rows_data if r), default=0),
            )
            ws.column_dimensions[col_letter].width = min(max_len + 2, 40)
        if freeze:
            ws.freeze_panes = "A2"

    # ---- Sheet 1: Summary --------------------------------------------------
    ws_sum = wb.create_sheet("Summary")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_rows: List[List[Any]] = [
        ["実行ラベル", run_label or ""],
        ["生成日時", ts],
        ["ステータス", milp_result.status],
        ["目的関数値 [円]", milp_result.objective_value],
        ["MIP ギャップ", milp_result.mip_gap],
        ["計算時間 [秒]", round(milp_result.solve_time_sec, 3)],
        ["BEV 台数", len(ms.K_BEV)],
        ["ICE 台数", len(ms.K_ICE)],
        ["タスク数", len(ms.R)],
        ["充電器数", len(ms.C)],
        ["時間刻み [分]", data.delta_t_min],
        ["時間スロット数", data.num_periods],
        ["PV 有効", data.enable_pv],
        ["V2G 有効", data.enable_v2g],
        ["デマンド料金有効", data.enable_demand_charge],
        ["--- コスト内訳 ---", ""],
        ["電力量料金 [円]", round(sim_result.total_energy_cost, 0)],
        ["デマンド料金 [円]", round(sim_result.total_demand_charge, 0)],
        ["燃料費 [円]", round(sim_result.total_fuel_cost, 0)],
        ["電池劣化費 [円]", round(sim_result.total_degradation_cost, 0)],
        ["運行コスト合計 [円]", round(sim_result.total_operating_cost, 0)],
    ]
    _write_sheet(ws_sum, ["項目", "値"], summary_rows)

    # ---- Sheet 2: KPIs -----------------------------------------------------
    ws_kpi = wb.create_sheet("KPIs")
    kpi_rows: List[List[Any]] = [
        ["objective_value", milp_result.objective_value],
        ["total_energy_cost", round(sim_result.total_energy_cost, 2)],
        ["total_demand_charge", round(sim_result.total_demand_charge, 2)],
        ["total_fuel_cost", round(sim_result.total_fuel_cost, 2)],
        [
            "vehicle_fixed_cost",
            round(getattr(sim_result, "vehicle_fixed_cost", 0.0), 2),
        ],
        ["unmet_trips", sim_result.unserved_tasks or 0],
        ["soc_min_margin_kwh", round(getattr(sim_result, "soc_min_kwh", 0.0), 3)],
        ["charger_utilization", round(sim_result.charger_utilization, 4)],
        ["peak_grid_power_kw", round(sim_result.peak_demand_kw, 2)],
        ["solve_time_sec", round(milp_result.solve_time_sec, 3)],
    ]
    _write_sheet(ws_kpi, ["KPI", "値"], kpi_rows)

    # ---- Sheet 3: VehicleSchedule ------------------------------------------
    ws_vs = wb.create_sheet("VehicleSchedule")
    vs_headers = [
        "vehicle_id",
        "vehicle_type",
        "task_id",
        "start_time_idx",
        "end_time_idx",
        "origin",
        "destination",
        "distance_km",
        "energy_kwh_bev",
    ]
    vs_rows: List[List[Any]] = []
    for k in ms.K_ALL:
        assigned = milp_result.assignment.get(k, [])
        if assigned:
            for r_id in assigned:
                task = dp.task_lut.get(r_id)
                vs_rows.append(
                    [
                        k,
                        dp.vehicle_lut[k].vehicle_type,
                        r_id,
                        task.start_time_idx if task else "",
                        task.end_time_idx if task else "",
                        task.origin if task else "",
                        task.destination if task else "",
                        task.distance_km if task else "",
                        task.energy_required_kwh_bev if task else "",
                    ]
                )
        else:
            vs_rows.append(
                [
                    k,
                    dp.vehicle_lut[k].vehicle_type,
                    "(unassigned)",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    _write_sheet(ws_vs, vs_headers, vs_rows)

    # ---- Sheet 4: ChargingSchedule (先頭 10,000 行に制限) ------------------
    ws_cs = wb.create_sheet("ChargingSchedule")
    cs_headers = [
        "vehicle_id",
        "charger_id",
        "time_idx",
        "z_charge",
        "p_charge_kw",
        "soc_kwh",
    ]
    cs_rows: List[List[Any]] = []
    MAX_CS_ROWS = 10_000
    for k in ms.K_BEV:
        if len(cs_rows) >= MAX_CS_ROWS:
            break
        soc_series = milp_result.soc_series.get(k, [])
        for c in ms.C:
            if len(cs_rows) >= MAX_CS_ROWS:
                break
            pwr_series = milp_result.charge_power_kw.get(k, {}).get(
                c, [0.0] * len(ms.T)
            )
            z_series = milp_result.charge_schedule.get(k, {}).get(c, [0] * len(ms.T))
            for t_idx in ms.T:
                if len(cs_rows) >= MAX_CS_ROWS:
                    break
                soc_val = soc_series[t_idx] if t_idx < len(soc_series) else ""
                cs_rows.append(
                    [
                        k,
                        c,
                        t_idx,
                        z_series[t_idx] if t_idx < len(z_series) else 0,
                        pwr_series[t_idx] if t_idx < len(pwr_series) else 0.0,
                        soc_val,
                    ]
                )
    _write_sheet(ws_cs, cs_headers, cs_rows)

    # ---- Sheet 5: SitePowerBalance -----------------------------------------
    ws_sp = wb.create_sheet("SitePowerBalance")
    sp_headers = [
        "site_id",
        "time_idx",
        "grid_import_kw",
        "pv_used_kw",
        "peak_demand_kw",
    ]
    sp_rows: List[List[Any]] = []
    for site_id in ms.I_CHARGE:
        grid_series = milp_result.grid_import_kw.get(site_id, [0.0] * len(ms.T))
        pv_series = milp_result.pv_used_kw.get(site_id, [0.0] * len(ms.T))
        for t_idx in ms.T:
            sp_rows.append(
                [
                    site_id,
                    t_idx,
                    grid_series[t_idx] if t_idx < len(grid_series) else 0.0,
                    pv_series[t_idx] if t_idx < len(pv_series) else 0.0,
                    milp_result.peak_demand_kw.get(site_id, 0.0),
                ]
            )
    _write_sheet(ws_sp, sp_headers, sp_rows)

    # ---- 保存 --------------------------------------------------------------
    out_path = run_dir / "results.xlsx"
    wb.save(out_path)
    return out_path


def export_excel_bytes(
    data: ProblemData,
    ms: ModelSets,
    dp: DerivedParams,
    milp_result: MILPResult,
    sim_result: SimulationResult,
    run_label: Optional[str] = None,
) -> bytes:
    """
    results.xlsx をファイルに保存せず bytes として返す。
    Streamlit の st.download_button に直接渡せる。

    Parameters
    ----------
    data, ms, dp, milp_result, sim_result : 各パイプライン出力
    run_label : 任意のラベル文字列

    Returns
    -------
    bytes
        xlsx バイナリデータ
    """
    import io
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = _Path(tmp)
        xlsx_path = export_excel(
            data, ms, dp, milp_result, sim_result, tmp_path, run_label
        )
        return xlsx_path.read_bytes()
