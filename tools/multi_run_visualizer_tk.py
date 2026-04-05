"""
複数 run 比較可視化ツール（Tkinter）

`output/<date>/scenario/.../run_*` と `output/reports/.../comparison.json`
の両方を収集し、比較表・比較図・教授向けレポートを生成する。

実行:
python tools/multi_run_visualizer_tk.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Iterable, List

import pandas as pd

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from tools.bus_operation_visualizer_tk import (
    _build_vehicle_order,
    _load_bundle,
    _plot_style_1,
    _plot_style_2,
)
from tools._visualizer_report_utils import (
    RunMeta,
    build_professor_report_markdown,
    collect_run_metas,
    export_route_band_diagram_assets,
    fmt_num,
    safe_float,
    write_solver_comparison_exports,
)


matplotlib.rcParams["font.family"] = ["Times New Roman", "Meiryo"]
matplotlib.rcParams["axes.unicode_minus"] = False

ALL_FILTER = "すべて"


def _to_dataframe(items: Iterable[RunMeta]) -> pd.DataFrame:
    rows = []
    for m in items:
        rows.append(
            {
                "date": m.date,
                "scenario_id": m.scenario_id,
                "depot": m.depot,
                "service": m.service,
                "run_id": m.run_id,
                "status": m.status,
                "objective_value": m.objective_value,
                "solve_time_sec": m.solve_time_sec,
                "total_cost": m.total_cost,
                "total_co2_kg": m.total_co2_kg,
                "trip_count_served": m.trip_count_served,
                "trip_count_unserved": m.trip_count_unserved,
                "vehicle_count_used": m.vehicle_count_used,
                "mode": m.mode,
                "exactness": m.exactness_label,
                "termination_reason": m.termination_reason,
                "plan_source": m.plan_source,
                "prepared_input_id": m.prepared_input_id,
                "objective_mode": m.objective_mode,
                "report_bundle_name": m.report_bundle_name,
                "service_date": m.service_date,
                "planning_days": m.planning_days,
                "route_count": m.route_count,
                "vehicle_count_available": m.vehicle_count_available,
                "charger_count_available": m.charger_count_available,
                "simulation_feasible": m.simulation_feasible,
                "simulation_total_distance_km": m.simulation_total_distance_km,
                "simulation_total_energy_kwh": m.simulation_total_energy_kwh,
                "simulation_total_cost": m.simulation_total_cost,
                "simulation_total_co2_kg": m.simulation_total_co2_kg,
                "simulation_result_path": str(m.simulation_result_path) if m.simulation_result_path is not None else "",
                "run_dir": str(m.run_dir),
            }
        )
    return pd.DataFrame(rows)


def _build_markdown_report(df: pd.DataFrame, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "| Run | Mode | ステータス | exact/fallback | 総コスト [円] | 総CO2 [kg-CO2] | 目的関数値 [モデル単位] | 求解時間 [秒] | served | unserved | 使用車両 |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in df.iterrows():
        lines.append(
            "| "
            + f"{r['run_id']} | {r.get('mode') or '-'} | {r['status']} | {r.get('exactness') or '-'} | {fmt_num(safe_float(r.get('total_cost')))} | {fmt_num(safe_float(r.get('total_co2_kg')), 3)} | {fmt_num(safe_float(r.get('objective_value')))} | {fmt_num(safe_float(r.get('solve_time_sec')))} | {r.get('trip_count_served', 'NA')} | {r.get('trip_count_unserved', 'NA')} | {r.get('vehicle_count_used', 'NA')} |"
        )
    return "\n".join(lines) + "\n"


def _plot_metric_bar(df: pd.DataFrame, metric: str, y_label: str, title: str):
    fig_h = max(4.0, 2.8 + 0.28 * max(1, len(df)))
    fig, ax = plt.subplots(figsize=(12.0, fig_h), dpi=160)

    work = df.copy()
    work = work.dropna(subset=[metric])
    if work.empty:
        ax.text(0.5, 0.5, "データなし", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title)
        fig.tight_layout()
        return fig

    x = work["run_id"].astype(str)
    y = work[metric].astype(float)
    bars = ax.bar(x, y, color="#4f81bd", edgecolor="#2f4f6f")

    for b, val in zip(bars, y):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt_num(float(val), 2), ha="center", va="bottom", fontsize=8)

    ax.set_title(title)
    ax.set_xlabel("Run ID")
    ax.set_ylabel(y_label)
    ax.tick_params(axis="x", labelrotation=35)
    ax.grid(axis="y", color="#d0d0d0", linewidth=0.5)

    fig.tight_layout()
    return fig


class MultiRunVisualizerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("複数 run 比較可視化ツール")
        self.root.geometry("1560x960")

        self.all_metas: List[RunMeta] = []
        self.filtered_metas: List[RunMeta] = []
        self.current_df = pd.DataFrame()

        self.cost_canvas = None
        self.co2_canvas = None
        self.cost_fig = None
        self.co2_fig = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.base_dir_var = tk.StringVar(value="output")
        ttk.Label(top, text="基準フォルダ:").pack(side="left", padx=(0, 6))
        ttk.Entry(top, textvariable=self.base_dir_var, width=90).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(top, text="参照", command=self._on_browse).pack(side="left", padx=4)
        ttk.Button(top, text="走査", command=self._on_scan).pack(side="left", padx=4)

        filters = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        filters.pack(fill="x")

        self.date_var = tk.StringVar(value=ALL_FILTER)
        self.scenario_var = tk.StringVar(value=ALL_FILTER)
        self.depot_var = tk.StringVar(value=ALL_FILTER)
        self.service_var = tk.StringVar(value=ALL_FILTER)

        self.date_combo = self._add_filter_combo(filters, "日付", self.date_var)
        self.scenario_combo = self._add_filter_combo(filters, "シナリオ", self.scenario_var)
        self.depot_combo = self._add_filter_combo(filters, "営業所", self.depot_var)
        self.service_combo = self._add_filter_combo(filters, "運行種別", self.service_var)

        ttk.Button(filters, text="フィルタ適用", command=self._apply_filter).pack(side="left", padx=8)
        ttk.Button(filters, text="全選択", command=self._select_all_runs).pack(side="left", padx=4)
        ttk.Button(filters, text="選択解除", command=self._clear_runs).pack(side="left", padx=4)

        middle = ttk.Panedwindow(self.root, orient="horizontal")
        middle.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(middle)
        right = ttk.Frame(middle)
        middle.add(left, weight=1)
        middle.add(right, weight=3)

        ttk.Label(left, text="Run一覧").pack(anchor="w")
        self.run_listbox = tk.Listbox(left, selectmode=tk.EXTENDED, width=56, exportselection=False)
        self.run_listbox.pack(fill="both", expand=True)

        right_top = ttk.Frame(right)
        right_top.pack(fill="x")

        ttk.Button(right_top, text="比較表プレビュー", command=self._preview_text_summary).pack(side="left", padx=4)
        ttk.Button(right_top, text="比較図プレビュー", command=self._preview_charts).pack(side="left", padx=4)
        ttk.Button(right_top, text="先生向けレポート", command=self._export_professor_report_only).pack(side="left", padx=4)

        self.max_buses_var = tk.IntVar(value=45)
        self.only_assigned_var = tk.BooleanVar(value=True)
        ttk.Label(right_top, text="最大表示車両数 [台]").pack(side="left", padx=(16, 4))
        ttk.Spinbox(right_top, from_=5, to=300, width=6, textvariable=self.max_buses_var).pack(side="left")
        ttk.Checkbutton(right_top, text="割当車両のみ", variable=self.only_assigned_var).pack(side="left", padx=8)

        self.export_svg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right_top, text="SVG出力", variable=self.export_svg_var).pack(side="left", padx=8)

        ttk.Button(right_top, text="選択runを出力", command=self._export_selected).pack(side="right", padx=4)

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True, pady=(8, 0))

        self.tab_text = ttk.Frame(self.nb)
        self.tab_cost = ttk.Frame(self.nb)
        self.tab_co2 = ttk.Frame(self.nb)
        self.nb.add(self.tab_text, text="比較表")
        self.nb.add(self.tab_cost, text="総コスト")
        self.nb.add(self.tab_co2, text="総CO2")

        self.summary_tree = ttk.Treeview(
            self.tab_text,
            columns=(
                "run_id",
                "mode",
                "status",
                "exactness",
                "total_cost",
                "total_co2",
                "objective",
                "solve_time",
                "served",
                "unserved",
                "vehicles",
            ),
            show="headings",
        )
        self.summary_tree.heading("run_id", text="Run ID")
        self.summary_tree.heading("mode", text="Mode")
        self.summary_tree.heading("status", text="ステータス")
        self.summary_tree.heading("exactness", text="exact/fallback")
        self.summary_tree.heading("total_cost", text="総コスト [円]")
        self.summary_tree.heading("total_co2", text="総CO2 [kg-CO2]")
        self.summary_tree.heading("objective", text="目的関数値 [モデル単位]")
        self.summary_tree.heading("solve_time", text="求解時間 [秒]")
        self.summary_tree.heading("served", text="served")
        self.summary_tree.heading("unserved", text="unserved")
        self.summary_tree.heading("vehicles", text="使用車両")
        self.summary_tree.column("run_id", width=180, anchor="w")
        self.summary_tree.column("mode", width=90, anchor="center")
        self.summary_tree.column("status", width=110, anchor="center")
        self.summary_tree.column("exactness", width=120, anchor="center")
        self.summary_tree.column("total_cost", width=180, anchor="e")
        self.summary_tree.column("total_co2", width=150, anchor="e")
        self.summary_tree.column("objective", width=140, anchor="e")
        self.summary_tree.column("solve_time", width=130, anchor="e")
        self.summary_tree.column("served", width=90, anchor="e")
        self.summary_tree.column("unserved", width=90, anchor="e")
        self.summary_tree.column("vehicles", width=90, anchor="e")
        self.summary_tree.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(self.root, textvariable=self.status_var).pack(fill="x", padx=10, pady=(0, 6))

    def _add_filter_combo(self, parent, label: str, var: tk.StringVar):
        ttk.Label(parent, text=label).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(parent, textvariable=var, values=[ALL_FILTER], state="readonly", width=22)
        combo.pack(side="left", padx=(0, 10))
        return combo

    def _on_browse(self) -> None:
        selected = filedialog.askdirectory(title="output 配下の run folder または reports bundle を選択")
        if selected:
            self.base_dir_var.set(selected)

    def _on_scan(self) -> None:
        base = Path(self.base_dir_var.get().strip())
        if not base.exists():
            messagebox.showerror("不正なフォルダ", "指定フォルダが存在しません。")
            return

        self.all_metas = collect_run_metas(base)
        if not self.all_metas:
            messagebox.showwarning("runなし", "run_* フォルダまたは comparison bundle が見つかりませんでした。")
            return

        self._refresh_filter_options()
        self._apply_filter()
        self.status_var.set(f"走査完了: {len(self.all_metas):,} run / {base}")

    def _refresh_filter_options(self) -> None:
        def values(attr: str) -> List[str]:
            vals = sorted({getattr(m, attr) for m in self.all_metas})
            return [ALL_FILTER] + vals

        self.date_combo["values"] = values("date")
        self.scenario_combo["values"] = values("scenario_id")
        self.depot_combo["values"] = values("depot")
        self.service_combo["values"] = values("service")

        self.date_var.set(ALL_FILTER)
        self.scenario_var.set(ALL_FILTER)
        self.depot_var.set(ALL_FILTER)
        self.service_var.set(ALL_FILTER)

    def _match_filter(self, m: RunMeta) -> bool:
        checks = [
            (self.date_var.get(), m.date),
            (self.scenario_var.get(), m.scenario_id),
            (self.depot_var.get(), m.depot),
            (self.service_var.get(), m.service),
        ]
        for selected, actual in checks:
            if selected != ALL_FILTER and selected != actual:
                return False
        return True

    def _apply_filter(self) -> None:
        self.filtered_metas = [m for m in self.all_metas if self._match_filter(m)]
        self.run_listbox.delete(0, tk.END)

        for m in self.filtered_metas:
            total_cost = fmt_num(m.total_cost)
            total_co2 = fmt_num(m.total_co2_kg, 3)
            txt = (
                f"{m.run_id} | {m.mode or '-'} | {m.status} | {m.exactness_label} | "
                f"served={m.trip_count_served if m.trip_count_served is not None else 'NA'} | "
                f"unserved={m.trip_count_unserved if m.trip_count_unserved is not None else 'NA'} | "
                f"総コスト[円]={total_cost} | {m.date}/{m.scenario_id}/{m.depot}/{m.service}"
            )
            self.run_listbox.insert(tk.END, txt)

        self.status_var.set(f"フィルタ結果: {len(self.filtered_metas):,} run")

    def _selected_metas(self) -> List[RunMeta]:
        idxs = list(self.run_listbox.curselection())
        return [self.filtered_metas[i] for i in idxs if 0 <= i < len(self.filtered_metas)]

    def _select_all_runs(self) -> None:
        if self.filtered_metas:
            self.run_listbox.selection_set(0, tk.END)

    def _clear_runs(self) -> None:
        self.run_listbox.selection_clear(0, tk.END)

    def _summary_df_from_selection(self) -> pd.DataFrame:
        selected = self._selected_metas()
        if not selected:
            return pd.DataFrame()
        df = _to_dataframe(selected)
        cols = [
            "run_id",
            "mode",
            "status",
            "exactness",
            "total_cost",
            "total_co2_kg",
            "objective_value",
            "solve_time_sec",
            "trip_count_served",
            "trip_count_unserved",
            "vehicle_count_used",
            "termination_reason",
            "plan_source",
            "prepared_input_id",
            "objective_mode",
            "report_bundle_name",
            "run_dir",
        ]
        return df[cols].copy()

    def _preview_text_summary(self) -> None:
        df = self._summary_df_from_selection()
        self.current_df = df

        for row_id in self.summary_tree.get_children():
            self.summary_tree.delete(row_id)

        if df.empty:
            messagebox.showwarning("未選択", "run を1つ以上選択してください。")
            return

        for _, r in df.iterrows():
            self.summary_tree.insert(
                "",
                tk.END,
                values=(
                    str(r["run_id"]),
                    str(r.get("mode") or "-"),
                    str(r["status"]),
                    str(r.get("exactness") or "-"),
                    fmt_num(safe_float(r.get("total_cost"))),
                    fmt_num(safe_float(r.get("total_co2_kg")), 3),
                    fmt_num(safe_float(r.get("objective_value"))),
                    fmt_num(safe_float(r.get("solve_time_sec"))),
                    str(r.get("trip_count_served", "NA")),
                    str(r.get("trip_count_unserved", "NA")),
                    str(r.get("vehicle_count_used", "NA")),
                ),
            )

        self.status_var.set(f"比較表更新: {len(df):,} 行")

    def _clear_canvas(self, tab: ttk.Frame, old_canvas):
        if old_canvas is not None:
            old_canvas.get_tk_widget().destroy()
        for child in tab.winfo_children():
            child.destroy()

    def _preview_charts(self) -> None:
        df = self._summary_df_from_selection()
        self.current_df = df

        if df.empty:
            messagebox.showwarning("未選択", "run を1つ以上選択してください。")
            return

        if self.cost_fig is not None:
            plt.close(self.cost_fig)
        if self.co2_fig is not None:
            plt.close(self.co2_fig)

        self.cost_fig = _plot_metric_bar(df, "total_cost", "総コスト [円]", "run別 総コスト")
        self.co2_fig = _plot_metric_bar(df, "total_co2_kg", "総CO2 [kg-CO2]", "run別 総CO2")

        self._clear_canvas(self.tab_cost, self.cost_canvas)
        self._clear_canvas(self.tab_co2, self.co2_canvas)

        self.cost_canvas = FigureCanvasTkAgg(self.cost_fig, master=self.tab_cost)
        self.cost_canvas.draw()
        self.cost_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.co2_canvas = FigureCanvasTkAgg(self.co2_fig, master=self.tab_co2)
        self.co2_canvas.draw()
        self.co2_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.status_var.set("比較図を描画しました")

    def _ensure_preview_data(self) -> pd.DataFrame:
        if self.current_df.empty:
            self._preview_text_summary()
            self._preview_charts()
        return self.current_df

    def _export_selected(self) -> None:
        selected = self._selected_metas()
        if not selected:
            messagebox.showwarning("未選択", "run を1つ以上選択してください。")
            return

        self._preview_text_summary()
        self._preview_charts()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(self.base_dir_var.get().strip())
        out_root = base / "analysis_export" / timestamp
        out_root.mkdir(parents=True, exist_ok=True)

        df = _to_dataframe(selected)
        csv_path = out_root / "summary_table.csv"
        md_path = out_root / "summary_report.md"

        df_out = df[[
            "date",
            "scenario_id",
            "depot",
            "service",
            "run_id",
            "mode",
            "status",
            "exactness",
            "total_cost",
            "total_co2_kg",
            "objective_value",
            "solve_time_sec",
            "trip_count_served",
            "trip_count_unserved",
            "vehicle_count_used",
            "termination_reason",
            "plan_source",
            "prepared_input_id",
            "objective_mode",
            "report_bundle_name",
            "service_date",
            "planning_days",
            "route_count",
            "vehicle_count_available",
            "charger_count_available",
            "simulation_feasible",
            "simulation_total_distance_km",
            "simulation_total_energy_kwh",
            "simulation_total_cost",
            "simulation_total_co2_kg",
            "simulation_result_path",
            "run_dir",
        ]].copy()
        df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")
        md_path.write_text(_build_markdown_report(df_out, "run比較サマリー（総コスト・総CO2）"), encoding="utf-8")
        professor_report_path = out_root / "professor_report.md"
        professor_report_path.write_text(
            build_professor_report_markdown(selected, title="教授向けシナリオ報告"),
            encoding="utf-8",
        )
        solver_table_paths = write_solver_comparison_exports(selected, out_root)
        route_band_export = export_route_band_diagram_assets(selected, out_root)

        # Comparison figures
        if self.cost_fig is not None:
            self.cost_fig.savefig(out_root / "total_cost_comparison.png", dpi=300, bbox_inches="tight")
            if self.export_svg_var.get():
                self.cost_fig.savefig(out_root / "total_cost_comparison.svg", bbox_inches="tight")
        if self.co2_fig is not None:
            self.co2_fig.savefig(out_root / "total_co2_comparison.png", dpi=300, bbox_inches="tight")
            if self.export_svg_var.get():
                self.co2_fig.savefig(out_root / "total_co2_comparison.svg", bbox_inches="tight")

        # Per-run operation figures (reuse single-run plot logic)
        per_run_count = 0
        for meta in selected:
            try:
                bundle = _load_bundle(meta.run_dir)
                vehicle_ids = _build_vehicle_order(bundle, only_assigned=self.only_assigned_var.get())
                vehicle_ids = vehicle_ids[: max(1, int(self.max_buses_var.get()))]
                if not vehicle_ids:
                    continue

                fig_a = _plot_style_1(bundle, vehicle_ids, self.only_assigned_var.get())
                fig_b = _plot_style_2(bundle, vehicle_ids, self.only_assigned_var.get())

                run_out = out_root / meta.run_id
                run_out.mkdir(parents=True, exist_ok=True)
                fig_a.savefig(run_out / "bus_operation_figure_a.png", dpi=300, bbox_inches="tight")
                fig_b.savefig(run_out / "bus_operation_figure_b.png", dpi=300, bbox_inches="tight")
                if self.export_svg_var.get():
                    fig_a.savefig(run_out / "bus_operation_figure_a.svg", bbox_inches="tight")
                    fig_b.savefig(run_out / "bus_operation_figure_b.svg", bbox_inches="tight")
                plt.close(fig_a)
                plt.close(fig_b)
                per_run_count += 1
            except Exception:
                # Skip problematic runs and continue export.
                continue

        best_route_band_dir = route_band_export.get("best_bundle_route_band_dir")
        route_band_note = (
            f", route-band={best_route_band_dir}"
            if best_route_band_dir is not None
            else ""
        )
        self.status_var.set(
            f"出力完了: 対象run={len(selected):,}件, 個別図={per_run_count}件, solver表={solver_table_paths['csv_path'].name}{route_band_note}, 出力先={out_root}"
        )
        messagebox.showinfo("出力完了", f"出力先:\n{out_root}")

    def _export_professor_report_only(self) -> None:
        selected = self._selected_metas()
        if not selected:
            messagebox.showwarning("未選択", "run を1つ以上選択してください。")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(self.base_dir_var.get().strip())
        out_root = base / "analysis_export" / timestamp
        out_root.mkdir(parents=True, exist_ok=True)
        report_path = out_root / "professor_report.md"
        report_path.write_text(
            build_professor_report_markdown(selected, title="教授向けシナリオ報告"),
            encoding="utf-8",
        )
        self.status_var.set(f"先生向けレポートを出力しました: {report_path}")
        messagebox.showinfo("出力完了", f"先生向けレポート:\n{report_path}")


def main() -> None:
    root = tk.Tk()
    app = MultiRunVisualizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
