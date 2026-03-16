"""
バックアップ運用コンソール (Tkinter)

目的:
- フロント運用の主要機能を Tk で代替
- シナリオ管理 / quick-setup / 車両管理 / テンプレート管理 / 実行 / 結果確認

実行:
  python tools/scenario_backup_tk.py
"""

from __future__ import annotations

from datetime import datetime
import csv
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any
from urllib import error, parse, request


class BFFClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = ""

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _full_url(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        prefix: str | None = None,
    ) -> str:
        pfx = self.api_prefix if prefix is None else prefix
        if not path.startswith("/"):
            path = "/" + path
        if pfx and not pfx.startswith("/"):
            pfx = "/" + pfx
        base = f"{self.base_url}{pfx}{path}"
        if not query:
            return base
        q = {k: v for k, v in query.items() if v is not None and v != ""}
        if not q:
            return base
        return f"{base}?{parse.urlencode(q)}"

    def _request_once(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        prefix: str | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            self._full_url(path, query=query, prefix=prefix),
            method=method,
            data=data,
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"接続失敗: {exc}") from exc

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        allow_prefix_fallback: bool = True,
    ) -> dict[str, Any]:
        try:
            return self._request_once(method, path, body=body, query=query)
        except RuntimeError as exc:
            if not allow_prefix_fallback:
                raise
            if "HTTP 404" not in str(exc):
                raise

            alt_prefix = "/api" if self.api_prefix == "" else ""
            result = self._request_once(
                method,
                path,
                body=body,
                query=query,
                prefix=alt_prefix,
            )
            self.api_prefix = alt_prefix
            return result

    def detect_api_prefix(self) -> str:
        candidates: list[str] = []
        for p in [self.api_prefix, "/api", ""]:
            if p not in candidates:
                candidates.append(p)

        for p in candidates:
            try:
                self._request_once("GET", "/app/context", prefix=p)
                self.api_prefix = p
                return p
            except Exception:
                continue

        for p in candidates:
            try:
                self._request_once("GET", "/scenarios", prefix=p)
                self.api_prefix = p
                return p
            except Exception:
                continue

        raise RuntimeError("BFFに接続できませんでした。URLを確認してください。")

    def list_scenarios(self) -> dict[str, Any]:
        return self._request("GET", "/scenarios")

    def get_app_context(self) -> dict[str, Any]:
        return self._request("GET", "/app/context")

    def create_scenario(
        self,
        name: str,
        description: str,
        dataset_id: str,
        random_seed: int,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/scenarios",
            {
                "name": name,
                "description": description,
                "datasetId": dataset_id,
                "randomSeed": random_seed,
                "mode": "thesis_mode",
                "operatorId": "tokyu",
            },
        )

    def duplicate_scenario(self, scenario_id: str, name: str | None = None) -> dict[str, Any]:
        body = {"name": name} if name else {}
        return self._request("POST", f"/scenarios/{scenario_id}/duplicate", body)

    def delete_scenario(self, scenario_id: str) -> None:
        self._request("DELETE", f"/scenarios/{scenario_id}")

    def activate_scenario(self, scenario_id: str) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/activate")

    def get_quick_setup(self, scenario_id: str, route_limit: int | None = None) -> dict[str, Any]:
        query = {"routeLimit": route_limit} if route_limit is not None else None
        return self._request("GET", f"/scenarios/{scenario_id}/quick-setup", query=query)

    def put_quick_setup(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/scenarios/{scenario_id}/quick-setup", payload)

    def list_routes(self, scenario_id: str, depot_id: str | None = None) -> dict[str, Any]:
        query = {"depotId": depot_id} if depot_id else None
        return self._request("GET", f"/scenarios/{scenario_id}/routes", query=query)

    def update_route(self, scenario_id: str, route_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/scenarios/{scenario_id}/routes/{route_id}", payload)

    def list_vehicles(self, scenario_id: str, depot_id: str | None = None) -> dict[str, Any]:
        query = {"depotId": depot_id} if depot_id else None
        return self._request("GET", f"/scenarios/{scenario_id}/vehicles", query=query)

    def create_vehicle(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/vehicles", payload)

    def create_vehicle_batch(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/vehicles/bulk", payload)

    def get_vehicle(self, scenario_id: str, vehicle_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/vehicles/{vehicle_id}")

    def update_vehicle(self, scenario_id: str, vehicle_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/scenarios/{scenario_id}/vehicles/{vehicle_id}", payload)

    def duplicate_vehicle(self, scenario_id: str, vehicle_id: str, target_depot_id: str | None = None) -> dict[str, Any]:
        payload = {"targetDepotId": target_depot_id} if target_depot_id else {}
        return self._request("POST", f"/scenarios/{scenario_id}/vehicles/{vehicle_id}/duplicate", payload)

    def duplicate_vehicle_bulk(
        self,
        scenario_id: str,
        vehicle_id: str,
        quantity: int,
        target_depot_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"quantity": quantity}
        if target_depot_id:
            payload["targetDepotId"] = target_depot_id
        return self._request("POST", f"/scenarios/{scenario_id}/vehicles/{vehicle_id}/duplicate-bulk", payload)

    def delete_vehicle(self, scenario_id: str, vehicle_id: str) -> None:
        self._request("DELETE", f"/scenarios/{scenario_id}/vehicles/{vehicle_id}")

    def list_vehicle_templates(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/vehicle-templates")

    def create_vehicle_template(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/vehicle-templates", payload)

    def update_vehicle_template(self, scenario_id: str, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/scenarios/{scenario_id}/vehicle-templates/{template_id}", payload)

    def delete_vehicle_template(self, scenario_id: str, template_id: str) -> None:
        self._request("DELETE", f"/scenarios/{scenario_id}/vehicle-templates/{template_id}")

    def prepare_simulation(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/simulation/prepare", payload)

    def run_simulation_legacy(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/run-simulation", payload)

    def run_prepared_simulation(self, scenario_id: str, prepared_input_id: str, source: str = "duties") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/scenarios/{scenario_id}/simulation/run",
            {"prepared_input_id": prepared_input_id, "source": source},
        )

    def run_optimization(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/run-optimization", payload)

    def reoptimize(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/reoptimize", payload)

    def get_simulation_capabilities(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/simulation/capabilities")

    def get_optimization_capabilities(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/optimization/capabilities")

    def get_simulation_result(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/simulation")

    def get_optimization_result(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/optimization")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("予備運用コンソール")
        self.root.geometry("1500x980")

        self.client = BFFClient("http://127.0.0.1:8000")
        self.scenarios: list[dict[str, Any]] = []
        self.prepared_input_id = ""
        self.last_job_id = ""
        self.vehicle_rows: list[dict[str, Any]] = []
        self.template_rows: list[dict[str, Any]] = []
        self.advanced_visible = False
        self.route_label_file_var = tk.StringVar(value="")

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="BFF URL").pack(side=tk.LEFT)
        self.base_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        ttk.Entry(top, textvariable=self.base_url_var, width=40).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="接続確認", command=self.on_connect).pack(side=tk.LEFT, padx=4)

        scenario_frame = ttk.LabelFrame(self.root, text="シナリオ", padding=8)
        scenario_frame.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(scenario_frame, text="一覧更新", command=self.refresh_scenarios).pack(side=tk.LEFT, padx=4)
        self.scenario_combo = ttk.Combobox(scenario_frame, state="readonly", width=60)
        self.scenario_combo.pack(side=tk.LEFT, padx=6)
        self.scenario_combo.bind("<<ComboboxSelected>>", self.on_scenario_changed)

        ttk.Label(scenario_frame, text="新規名").pack(side=tk.LEFT, padx=(12, 4))
        self.new_name_var = tk.StringVar(value="バックアップ実行シナリオ")
        ttk.Entry(scenario_frame, textvariable=self.new_name_var, width=22).pack(side=tk.LEFT)

        ttk.Label(scenario_frame, text="datasetId").pack(side=tk.LEFT, padx=(8, 4))
        self.dataset_id_var = tk.StringVar(value="tokyu_bus_full")
        ttk.Entry(scenario_frame, textvariable=self.dataset_id_var, width=16).pack(side=tk.LEFT)

        ttk.Label(scenario_frame, text="seed").pack(side=tk.LEFT, padx=(8, 4))
        self.random_seed_var = tk.StringVar(value="42")
        ttk.Entry(scenario_frame, textvariable=self.random_seed_var, width=8).pack(side=tk.LEFT)

        ttk.Button(scenario_frame, text="新規作成", command=self.create_scenario).pack(side=tk.LEFT, padx=6)
        ttk.Button(scenario_frame, text="複製", command=self.duplicate_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(scenario_frame, text="有効化", command=self.activate_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(scenario_frame, text="削除", command=self.delete_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(scenario_frame, text="App Context", command=self.show_app_context).pack(side=tk.LEFT, padx=2)

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        left = ttk.Frame(main)
        mid = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(mid, weight=3)
        main.add(right, weight=4)

        self._build_scope_panel(left)
        self._build_run_panel(mid)
        self._build_fleet_panel(right)

        self.log = ScrolledText(self.root, height=12)
        self.log.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))

    def _build_scope_panel(self, parent: ttk.Frame) -> None:
        scope = ttk.LabelFrame(parent, text="対象スコープ / Quick Setup", padding=8)
        scope.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(scope)
        top.pack(fill=tk.X)
        ttk.Button(top, text="Quick Setup 読込", command=self.load_quick_setup).pack(side=tk.LEFT, pady=(0, 6))
        ttk.Button(top, text="Quick Setup 保存", command=self.save_quick_setup).pack(side=tk.LEFT, padx=6)

        label_ops = ttk.Frame(scope)
        label_ops.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(label_ops, text="ラベルファイル選択", command=self.pick_route_label_file).pack(side=tk.LEFT)
        ttk.Button(label_ops, text="ラベルをシナリオへ反映", command=self.apply_route_labels_to_scenario).pack(side=tk.LEFT, padx=6)
        ttk.Entry(label_ops, textvariable=self.route_label_file_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        list_wrap = ttk.Frame(scope)
        list_wrap.pack(fill=tk.BOTH, expand=True)

        dep_col = ttk.Frame(list_wrap)
        route_col = ttk.Frame(list_wrap)
        dep_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        route_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        ttk.Label(dep_col, text="営業所").pack(anchor="w")
        self.depot_list = tk.Listbox(dep_col, selectmode=tk.MULTIPLE, height=14, exportselection=False)
        self.depot_list.pack(fill=tk.BOTH, expand=True)

        ttk.Label(route_col, text="路線").pack(anchor="w")
        self.route_list = tk.Listbox(route_col, selectmode=tk.MULTIPLE, height=14, exportselection=False)
        self.route_list.pack(fill=tk.BOTH, expand=True)

        flags = ttk.Frame(scope)
        flags.pack(fill=tk.X, pady=8)
        self.include_short_turn_var = tk.BooleanVar(value=True)
        self.include_depot_moves_var = tk.BooleanVar(value=True)
        self.include_deadhead_var = tk.BooleanVar(value=True)
        self.allow_intra_var = tk.BooleanVar(value=False)
        self.allow_inter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(flags, text="区間便を含める", variable=self.include_short_turn_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="入出庫便を含める", variable=self.include_depot_moves_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="回送を含める", variable=self.include_deadhead_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="営業所内の路線間トレード許可", variable=self.allow_intra_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="営業所間トレード許可", variable=self.allow_inter_var).pack(anchor="w")

        base = ttk.Frame(scope)
        base.pack(fill=tk.X, pady=6)
        self.day_type_var = tk.StringVar(value="WEEKDAY")
        self.service_date_var = tk.StringVar(value="")
        self.route_limit_var = tk.StringVar(value="600")
        self._labeled_entry(base, "運行種別 (day_type)", self.day_type_var)
        self._labeled_entry(base, "運行日 (YYYY-MM-DD)", self.service_date_var)
        self._labeled_entry(base, "路線読み込み上限(route_limit)", self.route_limit_var)

    def _build_run_panel(self, parent: ttk.Frame) -> None:
        ops = ttk.LabelFrame(parent, text="実行パラメータ / 実行", padding=8)
        ops.pack(fill=tk.BOTH, expand=True)

        sim = ttk.LabelFrame(ops, text="Basic Parameters", padding=6)
        sim.pack(fill=tk.X, pady=4)
        self.vehicle_count_var = tk.StringVar(value="10")
        self.charger_count_var = tk.StringVar(value="4")
        self.initial_soc_var = tk.StringVar(value="0.8")
        self.charger_power_var = tk.StringVar(value="90")

        self._labeled_entry(sim, "シミュレーション車両台数", self.vehicle_count_var)
        self._labeled_entry(sim, "充電器台数", self.charger_count_var)
        self._labeled_entry(sim, "初期SOC", self.initial_soc_var)
        self._labeled_entry(sim, "充電器出力(kW)", self.charger_power_var)

        costs = ttk.LabelFrame(ops, text="Cost / Tariff Parameters", padding=6)
        costs.pack(fill=tk.X, pady=4)
        self.grid_flat_price_var = tk.StringVar(value="30")
        self.grid_sell_price_var = tk.StringVar(value="0")
        self.demand_charge_var = tk.StringVar(value="1500")
        self.diesel_price_var = tk.StringVar(value="145")
        self.grid_co2_var = tk.StringVar(value="0")
        self.co2_price_var = tk.StringVar(value="1")
        self.depot_power_limit_var = tk.StringVar(value="500")
        self.contract_penalty_coeff_var = tk.StringVar(value="1000000")
        self.unserved_penalty_var = tk.StringVar(value="10000")
        self.objective_weights_json_var = tk.StringVar(value="")
        self.tou_text_var = tk.StringVar(value="0-12:15,12-20:40,20-48:20")

        self._labeled_entry(costs, "車両導入費(編集は車両/テンプレ画面)", tk.StringVar(value="個別設定"), readonly=True)
        self._labeled_entry(costs, "燃料単価 diesel_price_per_l", self.diesel_price_var)
        self._labeled_entry(costs, "電気代単価 grid_flat_price_per_kwh", self.grid_flat_price_var)
        self._labeled_entry(costs, "売電単価 grid_sell_price_per_kwh", self.grid_sell_price_var)
        self._labeled_entry(costs, "TOU帯 (例 0-12:15,12-20:40)", self.tou_text_var)
        self._labeled_entry(costs, "需要単価 demand_charge_cost_per_kw", self.demand_charge_var)
        self._labeled_entry(costs, "契約上限 depot_power_limit_kw", self.depot_power_limit_var)
        self._labeled_entry(costs, "契約超過罰金係数(slack_penalty)", self.contract_penalty_coeff_var)
        self._labeled_entry(costs, "未配車罰金 unserved_penalty", self.unserved_penalty_var)
        self._labeled_entry(costs, "CO2原単位 grid_co2_kg_per_kwh", self.grid_co2_var)
        self._labeled_entry(costs, "CO2単価 co2_price_per_kg", self.co2_price_var)
        self._labeled_entry(costs, "拡張係数 objective_weights(JSON)", self.objective_weights_json_var)

        self.advanced_btn = ttk.Button(ops, text="Advanced Options", command=self.toggle_advanced)
        self.advanced_btn.pack(anchor="w", pady=(8, 4))

        self.advanced_frame = ttk.LabelFrame(ops, text="Advanced Options", padding=6)
        self.solver_mode_var = tk.StringVar(value="hybrid")
        self.objective_mode_var = tk.StringVar(value="total_cost")
        self.time_limit_var = tk.StringVar(value="300")
        self.mip_gap_var = tk.StringVar(value="0.01")
        self.alns_iter_var = tk.StringVar(value="500")
        self.allow_partial_service_var = tk.BooleanVar(value=False)

        self._labeled_entry(self.advanced_frame, "solver_mode", self.solver_mode_var)
        self._labeled_entry(self.advanced_frame, "objective_mode", self.objective_mode_var)
        self._labeled_entry(self.advanced_frame, "time_limit_seconds", self.time_limit_var)
        self._labeled_entry(self.advanced_frame, "mip_gap", self.mip_gap_var)
        self._labeled_entry(self.advanced_frame, "alns_iterations", self.alns_iter_var)
        ttk.Checkbutton(
            self.advanced_frame,
            text="allow_partial_service",
            variable=self.allow_partial_service_var,
        ).pack(anchor="w")

        self.advanced_frame.pack_forget()

        btn_row = ttk.Frame(ops)
        btn_row.pack(fill=tk.X, pady=8)
        ttk.Button(btn_row, text="入力データ作成 (Prepare)", command=self.prepare).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Prepared実行", command=self.run_prepared).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="シミュレーション実行(legacy)", command=self.run_simulation_legacy).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="最適化実行", command=self.run_optimization).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="再最適化", command=self.run_reoptimize).pack(side=tk.LEFT, padx=4)

        self.prepared_var = tk.StringVar(value="prepared_input_id: -")
        ttk.Label(ops, textvariable=self.prepared_var).pack(anchor="w", pady=4)
        self.job_var = tk.StringVar(value="job: -")
        ttk.Label(ops, textvariable=self.job_var).pack(anchor="w", pady=2)

        job_row = ttk.Frame(ops)
        job_row.pack(fill=tk.X, pady=4)
        ttk.Label(job_row, text="手動 job_id", width=20).pack(side=tk.LEFT)
        self.manual_job_id_var = tk.StringVar(value="")
        ttk.Entry(job_row, textvariable=self.manual_job_id_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(job_row, text="ジョブ監視", command=self.poll_last_job).pack(side=tk.LEFT, padx=4)

        info_btn_row = ttk.Frame(ops)
        info_btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(info_btn_row, text="機能情報", command=self.show_capabilities).pack(side=tk.LEFT, padx=4)
        ttk.Button(info_btn_row, text="Simulation結果", command=self.show_simulation_result).pack(side=tk.LEFT, padx=4)
        ttk.Button(info_btn_row, text="Optimization結果", command=self.show_optimization_result).pack(side=tk.LEFT, padx=4)

    def _build_fleet_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Notebook(parent)
        panel.pack(fill=tk.BOTH, expand=True)

        vehicle_tab = ttk.Frame(panel, padding=6)
        template_tab = ttk.Frame(panel, padding=6)
        panel.add(vehicle_tab, text="車両管理")
        panel.add(template_tab, text="テンプレート管理")

        self._build_vehicle_tab(vehicle_tab)
        self._build_template_tab(template_tab)

    def _build_vehicle_tab(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill=tk.X)
        self.fleet_depot_var = tk.StringVar(value="")
        ttk.Label(top, text="営業所ID").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.fleet_depot_var, width=14).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="車両一覧更新", command=self.refresh_vehicles).pack(side=tk.LEFT, padx=4)

        self.target_bev_count_var = tk.StringVar(value="10")
        self.default_energy_var = tk.StringVar(value="1.2")
        self.default_battery_var = tk.StringVar(value="300")
        self.default_charge_kw_var = tk.StringVar(value="90")
        ttk.Label(top, text="BEV目標台数").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Entry(top, textvariable=self.target_bev_count_var, width=6).pack(side=tk.LEFT)
        ttk.Button(top, text="BEV台数を反映", command=self.apply_fleet_count).pack(side=tk.LEFT, padx=4)

        tree_wrap = ttk.Frame(tab)
        tree_wrap.pack(fill=tk.BOTH, expand=True, pady=6)

        cols = (
            "id",
            "depotId",
            "type",
            "modelName",
            "acquisitionCost",
            "energyConsumption",
            "chargePowerKw",
            "enabled",
        )
        self.vehicle_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=12)
        for c in cols:
            self.vehicle_tree.heading(c, text=c)
            self.vehicle_tree.column(c, width=120, anchor="w")
        self.vehicle_tree.column("modelName", width=180, anchor="w")
        self.vehicle_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.vehicle_tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.vehicle_tree.configure(yscrollcommand=ysb.set)
        self.vehicle_tree.bind("<<TreeviewSelect>>", self.on_vehicle_select)

        form = ttk.LabelFrame(tab, text="車両編集", padding=6)
        form.pack(fill=tk.X)

        self.v_id_var = tk.StringVar(value="")
        self.v_depot_var = tk.StringVar(value="")
        self.v_type_var = tk.StringVar(value="BEV")
        self.v_model_var = tk.StringVar(value="")
        self.v_cap_var = tk.StringVar(value="0")
        self.v_battery_var = tk.StringVar(value="300")
        self.v_fuel_tank_var = tk.StringVar(value="")
        self.v_energy_var = tk.StringVar(value="1.2")
        self.v_charge_kw_var = tk.StringVar(value="90")
        self.v_min_soc_var = tk.StringVar(value="")
        self.v_max_soc_var = tk.StringVar(value="")
        self.v_acq_cost_var = tk.StringVar(value="0")
        self.v_enabled_var = tk.BooleanVar(value=True)

        self._labeled_entry(form, "id", self.v_id_var, readonly=True)
        self._labeled_entry(form, "depotId", self.v_depot_var)
        self._labeled_entry(form, "type (BEV/ICE)", self.v_type_var)
        self._labeled_entry(form, "modelName", self.v_model_var)
        self._labeled_entry(form, "capacityPassengers", self.v_cap_var)
        self._labeled_entry(form, "batteryKwh", self.v_battery_var)
        self._labeled_entry(form, "fuelTankL", self.v_fuel_tank_var)
        self._labeled_entry(form, "energyConsumption", self.v_energy_var)
        self._labeled_entry(form, "chargePowerKw", self.v_charge_kw_var)
        self._labeled_entry(form, "minSoc", self.v_min_soc_var)
        self._labeled_entry(form, "maxSoc", self.v_max_soc_var)
        self._labeled_entry(form, "acquisitionCost", self.v_acq_cost_var)
        ttk.Checkbutton(form, text="enabled", variable=self.v_enabled_var).pack(anchor="w")

        action = ttk.Frame(form)
        action.pack(fill=tk.X, pady=4)
        ttk.Button(action, text="新規作成", command=self.create_vehicle_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="更新", command=self.update_vehicle_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="削除", command=self.delete_selected_vehicle).pack(side=tk.LEFT, padx=3)

        self.dup_count_var = tk.StringVar(value="1")
        self.dup_target_depot_var = tk.StringVar(value="")
        ttk.Label(action, text="複製数").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Entry(action, textvariable=self.dup_count_var, width=5).pack(side=tk.LEFT)
        ttk.Label(action, text="複製先営業所").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(action, textvariable=self.dup_target_depot_var, width=10).pack(side=tk.LEFT)
        ttk.Button(action, text="複製", command=self.duplicate_selected_vehicle).pack(side=tk.LEFT, padx=3)

        tmpl = ttk.Frame(form)
        tmpl.pack(fill=tk.X, pady=4)
        self.apply_template_id_var = tk.StringVar(value="")
        self.apply_template_qty_var = tk.StringVar(value="1")
        ttk.Label(tmpl, text="テンプレートID").pack(side=tk.LEFT)
        ttk.Entry(tmpl, textvariable=self.apply_template_id_var, width=20).pack(side=tk.LEFT, padx=3)
        ttk.Label(tmpl, text="導入台数").pack(side=tk.LEFT)
        ttk.Entry(tmpl, textvariable=self.apply_template_qty_var, width=6).pack(side=tk.LEFT, padx=3)
        ttk.Button(tmpl, text="テンプレート導入", command=self.apply_template_to_depot).pack(side=tk.LEFT, padx=4)

    def _build_template_tab(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill=tk.X)
        ttk.Button(top, text="テンプレート一覧更新", command=self.refresh_templates).pack(side=tk.LEFT, padx=4)

        cols = (
            "id",
            "name",
            "type",
            "modelName",
            "acquisitionCost",
            "energyConsumption",
            "chargePowerKw",
        )
        self.template_tree = ttk.Treeview(tab, columns=cols, show="headings", height=12)
        for c in cols:
            self.template_tree.heading(c, text=c)
            self.template_tree.column(c, width=130, anchor="w")
        self.template_tree.column("name", width=180)
        self.template_tree.pack(fill=tk.BOTH, expand=True, pady=6)
        self.template_tree.bind("<<TreeviewSelect>>", self.on_template_select)

        form = ttk.LabelFrame(tab, text="テンプレート編集", padding=6)
        form.pack(fill=tk.X)

        self.t_id_var = tk.StringVar(value="")
        self.t_name_var = tk.StringVar(value="")
        self.t_type_var = tk.StringVar(value="BEV")
        self.t_model_var = tk.StringVar(value="")
        self.t_cap_var = tk.StringVar(value="0")
        self.t_battery_var = tk.StringVar(value="300")
        self.t_fuel_tank_var = tk.StringVar(value="")
        self.t_energy_var = tk.StringVar(value="1.2")
        self.t_charge_var = tk.StringVar(value="90")
        self.t_min_soc_var = tk.StringVar(value="")
        self.t_max_soc_var = tk.StringVar(value="")
        self.t_acq_cost_var = tk.StringVar(value="0")
        self.t_enabled_var = tk.BooleanVar(value=True)

        self._labeled_entry(form, "id", self.t_id_var, readonly=True)
        self._labeled_entry(form, "name", self.t_name_var)
        self._labeled_entry(form, "type", self.t_type_var)
        self._labeled_entry(form, "modelName", self.t_model_var)
        self._labeled_entry(form, "capacityPassengers", self.t_cap_var)
        self._labeled_entry(form, "batteryKwh", self.t_battery_var)
        self._labeled_entry(form, "fuelTankL", self.t_fuel_tank_var)
        self._labeled_entry(form, "energyConsumption", self.t_energy_var)
        self._labeled_entry(form, "chargePowerKw", self.t_charge_var)
        self._labeled_entry(form, "minSoc", self.t_min_soc_var)
        self._labeled_entry(form, "maxSoc", self.t_max_soc_var)
        self._labeled_entry(form, "acquisitionCost", self.t_acq_cost_var)
        ttk.Checkbutton(form, text="enabled", variable=self.t_enabled_var).pack(anchor="w")

        action = ttk.Frame(form)
        action.pack(fill=tk.X, pady=4)
        ttk.Button(action, text="新規作成", command=self.create_template_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="更新", command=self.update_template_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="削除", command=self.delete_selected_template).pack(side=tk.LEFT, padx=3)

    def _labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, readonly: bool = False) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=36).pack(side=tk.LEFT)
        state = "readonly" if readonly else "normal"
        ttk.Entry(row, textvariable=var, state=state).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def log_line(self, msg: str) -> None:
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def run_bg(self, action, done=None) -> None:
        def worker() -> None:
            try:
                result = action()
                self.root.after(0, lambda: done(result) if done else None)
            except Exception as exc:
                err_msg = str(exc)

                def _show_error(msg: str = err_msg) -> None:
                    self.log_line(f"エラー: {msg}")
                    messagebox.showerror("エラー", msg)

                self.root.after(0, _show_error)

        threading.Thread(target=worker, daemon=True).start()

    def _selected_scenario_id(self) -> str:
        idx = self.scenario_combo.current()
        if idx < 0 or idx >= len(self.scenarios):
            return ""
        return str(self.scenarios[idx].get("id") or "")

    def _selected_ids_from_list(self, listbox: tk.Listbox) -> list[str]:
        out: list[str] = []
        for idx in listbox.curselection():
            raw = listbox.get(idx)
            out.append(raw.split("|", 1)[0].strip())
        return out

    def _parse_int(self, value: str, default: int = 0) -> int:
        try:
            return int(value.strip())
        except Exception:
            return default

    def _parse_float(self, value: str, default: float = 0.0) -> float:
        try:
            return float(value.strip())
        except Exception:
            return default

    def _parse_optional_float(self, value: str) -> float | None:
        v = value.strip()
        if not v:
            return None
        return self._parse_float(v)

    def _build_vehicle_payload_from_form(self) -> dict[str, Any]:
        return {
            "depotId": self.v_depot_var.get().strip(),
            "type": self.v_type_var.get().strip().upper() or "BEV",
            "modelName": self.v_model_var.get().strip(),
            "capacityPassengers": self._parse_int(self.v_cap_var.get(), 0),
            "batteryKwh": self._parse_optional_float(self.v_battery_var.get()),
            "fuelTankL": self._parse_optional_float(self.v_fuel_tank_var.get()),
            "energyConsumption": self._parse_float(self.v_energy_var.get(), 0.0),
            "chargePowerKw": self._parse_optional_float(self.v_charge_kw_var.get()),
            "minSoc": self._parse_optional_float(self.v_min_soc_var.get()),
            "maxSoc": self._parse_optional_float(self.v_max_soc_var.get()),
            "acquisitionCost": self._parse_float(self.v_acq_cost_var.get(), 0.0),
            "enabled": bool(self.v_enabled_var.get()),
        }

    def _build_template_payload_from_form(self) -> dict[str, Any]:
        return {
            "name": self.t_name_var.get().strip(),
            "type": self.t_type_var.get().strip().upper() or "BEV",
            "modelName": self.t_model_var.get().strip(),
            "capacityPassengers": self._parse_int(self.t_cap_var.get(), 0),
            "batteryKwh": self._parse_optional_float(self.t_battery_var.get()),
            "fuelTankL": self._parse_optional_float(self.t_fuel_tank_var.get()),
            "energyConsumption": self._parse_float(self.t_energy_var.get(), 0.0),
            "chargePowerKw": self._parse_optional_float(self.t_charge_var.get()),
            "minSoc": self._parse_optional_float(self.t_min_soc_var.get()),
            "maxSoc": self._parse_optional_float(self.t_max_soc_var.get()),
            "acquisitionCost": self._parse_float(self.t_acq_cost_var.get(), 0.0),
            "enabled": bool(self.t_enabled_var.get()),
        }

    def _parse_tou_text(self) -> list[dict[str, Any]]:
        text = self.tou_text_var.get().strip()
        if not text:
            return []
        bands: list[dict[str, Any]] = []
        chunks = [c.strip() for c in text.split(",") if c.strip()]
        for c in chunks:
            parts = [p.strip() for p in c.split(":", 1)]
            if len(parts) != 2:
                continue
            span, price = parts
            se = [x.strip() for x in span.split("-", 1)]
            if len(se) != 2:
                continue
            s = self._parse_int(se[0], 0)
            e = self._parse_int(se[1], 0)
            p = self._parse_float(price, 0.0)
            if e > s:
                bands.append({"start_hour": s, "end_hour": e, "price_per_kwh": p})
        return bands

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return None
    @staticmethod
    def _normalize_direction(value: Any, default: str = "outbound") -> str:
        text = str(value or "").strip().lower()
        if text in {"outbound", "out", "up", "上り", "上り便", "↗"}:
            return "outbound"
        if text in {"inbound", "in", "down", "下り", "下り便", "↙"}:
            return "inbound"
        if text in {"circular", "loop", "循環", "循環線"}:
            return "circular"
        return default

    @staticmethod
    def _normalize_variant_type(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"main", "main_outbound", "main_inbound", "本線"}:
            return "main"
        if text in {"short_turn", "区間", "区間便"}:
            return "short_turn"
        if text in {"depot", "depot_in", "depot_out", "入出庫", "入出庫便", "入庫", "出庫"}:
            return "depot"
        if text in {"branch", "枝線"}:
            return "branch"
        return "unknown"

    def pick_route_label_file(self) -> None:
        path = filedialog.askopenfilename(
            title="手動ラベルファイルを選択",
            filetypes=[
                ("ラベルCSV/JSON/JSONL", "*.csv *.json *.jsonl"),
                ("CSV", "*.csv"),
                ("JSON", "*.json"),
                ("JSONL", "*.jsonl"),
                ("すべて", "*.*"),
            ],
        )
        if not path:
            return
        self.route_label_file_var.set(path)

    def _load_label_rows(self, path: str) -> list[dict[str, Any]]:
        if path.lower().endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict) and isinstance(obj.get("items"), list):
                return [dict(item) for item in obj.get("items") if isinstance(item, dict)]
            if isinstance(obj, list):
                return [dict(item) for item in obj if isinstance(item, dict)]
            return []

        if path.lower().endswith(".jsonl"):
            rows: list[dict[str, Any]] = []
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        rows.append(dict(obj))
            return rows

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    def apply_route_labels_to_scenario(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        label_path = self.route_label_file_var.get().strip()
        if not label_path:
            messagebox.showwarning("入力不足", "先にラベルファイルを選択してください")
            return

        def action() -> dict[str, Any]:
            rows = self._load_label_rows(label_path)
            if not rows:
                raise RuntimeError("ラベルファイルに有効な行がありません")

            routes_resp = self.client.list_routes(scenario_id)
            routes = list(routes_resp.get("items") or [])
            route_ids = {str(item.get("id") or "").strip() for item in routes}

            applied = 0
            skipped = 0
            not_found = 0

            for row in rows:
                route_id = str(row.get("route_id") or row.get("id") or "").strip()
                if not route_id:
                    skipped += 1
                    continue
                if route_id not in route_ids:
                    not_found += 1
                    continue

                route_series_code = str(
                    row.get("routeSeriesCode") or row.get("route_series_code") or ""
                ).strip()
                route_series_prefix = str(
                    row.get("routeSeriesPrefix") or row.get("route_series_prefix") or ""
                ).strip()
                route_series_number_raw = row.get("routeSeriesNumber") or row.get("route_series_number")
                route_series_number: int | None = None
                try:
                    if route_series_number_raw not in (None, ""):
                        route_series_number = int(str(route_series_number_raw).strip())
                except Exception:
                    route_series_number = None

                route_family_code = str(
                    row.get("routeFamilyCode")
                    or row.get("route_family_code")
                    or route_series_code
                    or ""
                ).strip()
                route_family_label = str(
                    row.get("routeFamilyLabel")
                    or row.get("route_family_label")
                    or route_family_code
                    or ""
                ).strip()

                variant_manual = self._normalize_variant_type(
                    row.get("routeVariantTypeManual")
                    or row.get("routeVariantType")
                    or row.get("route_variant_type")
                    or "unknown"
                )
                direction_manual = self._normalize_direction(
                    row.get("canonicalDirectionManual")
                    or row.get("canonicalDirection")
                    or row.get("canonical_direction")
                    or row.get("direction")
                    or "outbound"
                )
                depot_id = str(
                    row.get("depotId")
                    or row.get("depot_id")
                    or row.get("homeDepotId")
                    or ""
                ).strip()

                payload: dict[str, Any] = {}
                if route_family_code:
                    payload["routeFamilyCode"] = route_family_code
                if route_family_label:
                    payload["routeFamilyLabel"] = route_family_label
                if route_series_code:
                    payload["routeSeriesCode"] = route_series_code
                if route_series_prefix:
                    payload["routeSeriesPrefix"] = route_series_prefix
                if route_series_number is not None:
                    payload["routeSeriesNumber"] = route_series_number
                if variant_manual and variant_manual != "unknown":
                    payload["routeVariantTypeManual"] = variant_manual
                    payload["routeVariantType"] = variant_manual
                if direction_manual:
                    payload["canonicalDirectionManual"] = direction_manual
                    payload["canonicalDirection"] = direction_manual
                if depot_id:
                    payload["depotId"] = depot_id

                is_primary = self._parse_bool(row.get("isPrimaryVariant"))
                if is_primary is not None:
                    payload["isPrimaryVariant"] = is_primary

                if not payload:
                    skipped += 1
                    continue

                self.client.update_route(scenario_id, route_id, payload)
                applied += 1

            return {
                "total": len(rows),
                "applied": applied,
                "skipped": skipped,
                "notFound": not_found,
            }

        def done(resp: dict[str, Any]) -> None:
            self.log_line(
                "ラベル反映完了: "
                f"total={resp.get('total')} applied={resp.get('applied')} "
                f"skipped={resp.get('skipped')} not_found={resp.get('notFound')}"
            )
            self.load_quick_setup()

        self.run_bg(action, done)

    def _parse_objective_weights_json(self) -> dict[str, float]:
        raw = self.objective_weights_json_var.get().strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            messagebox.showwarning("入力エラー", "objective_weights は JSON 形式で入力してください")
            return {}
        if not isinstance(payload, dict):
            messagebox.showwarning("入力エラー", "objective_weights は JSON object で入力してください")
            return {}
        out: dict[str, float] = {}
        for k, v in payload.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                continue
        return out

    def toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.pack(fill=tk.X, pady=4)
            self.advanced_btn.configure(text="Hide Advanced Options")
        else:
            self.advanced_frame.pack_forget()
            self.advanced_btn.configure(text="Advanced Options")

    def on_connect(self) -> None:
        self.client.set_base_url(self.base_url_var.get().strip())

        def action() -> dict[str, Any]:
            prefix = self.client.detect_api_prefix()
            context = self.client.get_app_context()
            return {"prefix": prefix, "context": context}

        def done(resp: dict[str, Any]) -> None:
            shown = resp.get("prefix") or "(なし)"
            self.log_line(f"接続成功: {self.client.base_url} / API prefix = {shown}")
            self.log_line("App context: " + json.dumps(resp.get("context", {}), ensure_ascii=False))
            self.refresh_scenarios()

        self.run_bg(action, done)

    def refresh_scenarios(self) -> None:
        def action() -> dict[str, Any]:
            return self.client.list_scenarios()

        def done(resp: dict[str, Any]) -> None:
            self.scenarios = list(resp.get("items") or [])
            labels = [f"{i.get('name', '(名称なし)')} [{i.get('id', '')}]" for i in self.scenarios]
            self.scenario_combo["values"] = labels
            if labels:
                self.scenario_combo.current(0)
                self.on_scenario_changed()
            self.log_line(f"シナリオ取得: {len(self.scenarios)} 件")

        self.run_bg(action, done)

    def on_scenario_changed(self, _event=None) -> None:
        if not self._selected_scenario_id():
            return
        self.load_quick_setup()
        self.refresh_templates()
        self.refresh_vehicles()

    def create_scenario(self) -> None:
        name = self.new_name_var.get().strip()
        if not name:
            messagebox.showwarning("入力不足", "シナリオ名を入力してください")
            return
        dataset_id = self.dataset_id_var.get().strip() or "tokyu_bus_full"
        random_seed = self._parse_int(self.random_seed_var.get(), 42)

        def action() -> dict[str, Any]:
            return self.client.create_scenario(name, "backup console", dataset_id, random_seed)

        def done(_resp: dict[str, Any]) -> None:
            self.log_line(f"シナリオ作成: {name}")
            self.refresh_scenarios()

        self.run_bg(action, done)

    def duplicate_scenario(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        name = f"{self.new_name_var.get().strip() or 'バックアップ実行シナリオ'} (copy)"

        self.run_bg(
            lambda: self.client.duplicate_scenario(scenario_id, name),
            lambda _resp: (self.log_line(f"シナリオ複製: 元={scenario_id}"), self.refresh_scenarios()),
        )

    def activate_scenario(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        self.run_bg(
            lambda: self.client.activate_scenario(scenario_id),
            lambda resp: self.log_line(f"シナリオ有効化: {resp.get('activeScenarioId') or scenario_id}"),
        )

    def delete_scenario(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        if not messagebox.askyesno("確認", f"シナリオ {scenario_id} を削除しますか？"):
            return

        def action() -> dict[str, Any]:
            self.client.delete_scenario(scenario_id)
            return {}

        self.run_bg(action, lambda _resp: (self.log_line(f"シナリオ削除: {scenario_id}"), self.refresh_scenarios()))

    def show_app_context(self) -> None:
        self.run_bg(self.client.get_app_context, lambda resp: self.log_line("App context: " + json.dumps(resp, ensure_ascii=False)))

    def load_quick_setup(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return

        def action() -> dict[str, Any]:
            route_limit = self._parse_int(self.route_limit_var.get(), 600)
            return self.client.get_quick_setup(scenario_id, route_limit)

        def done(resp: dict[str, Any]) -> None:
            depots = list(resp.get("depots") or [])
            routes = list(resp.get("routes") or [])
            selected_depots = set(resp.get("selectedDepotIds") or [])
            selected_routes = set(resp.get("selectedRouteIds") or [])

            self.depot_list.delete(0, tk.END)
            for idx, depot in enumerate(depots):
                did = str(depot.get("id") or "")
                self.depot_list.insert(tk.END, f"{did} | {depot.get('name', '')}")
                if did in selected_depots:
                    self.depot_list.selection_set(idx)

            self.route_list.delete(0, tk.END)
            for idx, route in enumerate(routes):
                rid = str(route.get("id") or "")
                self.route_list.insert(tk.END, f"{rid} | {route.get('name', '')}")
                if rid in selected_routes:
                    self.route_list.selection_set(idx)

            trip = dict(resp.get("tripSelection") or {})
            self.include_short_turn_var.set(bool(trip.get("includeShortTurn", True)))
            self.include_depot_moves_var.set(bool(trip.get("includeDepotMoves", True)))
            self.include_deadhead_var.set(bool(trip.get("includeDeadhead", True)))
            self.allow_intra_var.set(bool(resp.get("allowIntraDepotRouteSwap", False)))
            self.allow_inter_var.set(bool(resp.get("allowInterDepotSwap", False)))

            solver = dict(resp.get("solver") or {})
            self.day_type_var.set(str(resp.get("dayType") or "WEEKDAY"))
            self.service_date_var.set(str(resp.get("serviceDate") or ""))
            self.solver_mode_var.set(str(solver.get("mode") or "hybrid"))
            self.objective_mode_var.set(str(solver.get("objectiveMode") or "total_cost"))
            self.time_limit_var.set(str(solver.get("timeLimitSeconds") or 300))
            self.mip_gap_var.set(str(solver.get("mipGap") if solver.get("mipGap") is not None else 0.01))
            self.alns_iter_var.set(str(solver.get("alnsIterations") or 500))

            if depots and not self.fleet_depot_var.get().strip():
                self.fleet_depot_var.set(str(depots[0].get("id") or ""))
            self.log_line("Quick Setup を読み込みました")

        self.run_bg(action, done)

    def save_quick_setup(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        payload = {
            "selectedDepotIds": self._selected_ids_from_list(self.depot_list),
            "selectedRouteIds": self._selected_ids_from_list(self.route_list),
            "dayType": self.day_type_var.get().strip(),
            "serviceDate": self.service_date_var.get().strip() or None,
            "includeShortTurn": self.include_short_turn_var.get(),
            "includeDepotMoves": self.include_depot_moves_var.get(),
            "includeDeadhead": self.include_deadhead_var.get(),
            "allowIntraDepotRouteSwap": self.allow_intra_var.get(),
            "allowInterDepotSwap": self.allow_inter_var.get(),
            "solverMode": self.solver_mode_var.get().strip(),
            "objectiveMode": self.objective_mode_var.get().strip(),
            "timeLimitSeconds": self._parse_int(self.time_limit_var.get(), 300),
            "mipGap": self._parse_float(self.mip_gap_var.get(), 0.01),
            "alnsIterations": self._parse_int(self.alns_iter_var.get(), 500),
        }
        self.run_bg(
            lambda: self.client.put_quick_setup(scenario_id, payload),
            lambda _resp: self.log_line("Quick Setup を保存しました"),
        )

    def refresh_vehicles(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        depot_id = self.fleet_depot_var.get().strip() or None

        def done(resp: dict[str, Any]) -> None:
            self.vehicle_rows = list(resp.get("items") or [])
            self.vehicle_tree.delete(*self.vehicle_tree.get_children())
            for row in self.vehicle_rows:
                self.vehicle_tree.insert(
                    "",
                    tk.END,
                    iid=str(row.get("id") or ""),
                    values=(
                        row.get("id"),
                        row.get("depotId"),
                        row.get("type"),
                        row.get("modelName"),
                        row.get("acquisitionCost"),
                        row.get("energyConsumption"),
                        row.get("chargePowerKw"),
                        row.get("enabled"),
                    ),
                )
            self.log_line(f"車両一覧取得: {len(self.vehicle_rows)} 件")

        self.run_bg(lambda: self.client.list_vehicles(scenario_id, depot_id), done)

    def on_vehicle_select(self, _event=None) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        selected = self.vehicle_tree.selection()
        if not selected:
            return
        vehicle_id = selected[0]

        def done(v: dict[str, Any]) -> None:
            self.v_id_var.set(str(v.get("id") or ""))
            self.v_depot_var.set(str(v.get("depotId") or ""))
            self.v_type_var.set(str(v.get("type") or "BEV"))
            self.v_model_var.set(str(v.get("modelName") or ""))
            self.v_cap_var.set(str(v.get("capacityPassengers") or 0))
            self.v_battery_var.set("" if v.get("batteryKwh") is None else str(v.get("batteryKwh")))
            self.v_fuel_tank_var.set("" if v.get("fuelTankL") is None else str(v.get("fuelTankL")))
            self.v_energy_var.set(str(v.get("energyConsumption") or 0.0))
            self.v_charge_kw_var.set("" if v.get("chargePowerKw") is None else str(v.get("chargePowerKw")))
            self.v_min_soc_var.set("" if v.get("minSoc") is None else str(v.get("minSoc")))
            self.v_max_soc_var.set("" if v.get("maxSoc") is None else str(v.get("maxSoc")))
            self.v_acq_cost_var.set(str(v.get("acquisitionCost") or 0.0))
            self.v_enabled_var.set(bool(v.get("enabled", True)))

        self.run_bg(lambda: self.client.get_vehicle(scenario_id, vehicle_id), done)

    def create_vehicle_from_form(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        payload = self._build_vehicle_payload_from_form()
        if not payload.get("depotId"):
            messagebox.showwarning("入力不足", "depotId を入力してください")
            return
        self.run_bg(
            lambda: self.client.create_vehicle(scenario_id, payload),
            lambda _resp: (self.log_line("車両を新規作成しました"), self.refresh_vehicles()),
        )

    def update_vehicle_from_form(self) -> None:
        scenario_id = self._selected_scenario_id()
        vehicle_id = self.v_id_var.get().strip()
        if not scenario_id or not vehicle_id:
            messagebox.showwarning("入力不足", "更新対象車両を選択してください")
            return
        payload = self._build_vehicle_payload_from_form()
        self.run_bg(
            lambda: self.client.update_vehicle(scenario_id, vehicle_id, payload),
            lambda _resp: (self.log_line(f"車両を更新しました: {vehicle_id}"), self.refresh_vehicles()),
        )

    def delete_selected_vehicle(self) -> None:
        scenario_id = self._selected_scenario_id()
        vehicle_id = self.v_id_var.get().strip()
        if not scenario_id or not vehicle_id:
            messagebox.showwarning("入力不足", "削除対象車両を選択してください")
            return
        if not messagebox.askyesno("確認", f"車両 {vehicle_id} を削除しますか？"):
            return

        def action() -> dict[str, Any]:
            self.client.delete_vehicle(scenario_id, vehicle_id)
            return {}

        self.run_bg(action, lambda _resp: (self.log_line(f"車両削除: {vehicle_id}"), self.refresh_vehicles()))

    def duplicate_selected_vehicle(self) -> None:
        scenario_id = self._selected_scenario_id()
        vehicle_id = self.v_id_var.get().strip()
        if not scenario_id or not vehicle_id:
            messagebox.showwarning("入力不足", "複製対象車両を選択してください")
            return
        quantity = max(1, self._parse_int(self.dup_count_var.get(), 1))
        target_depot_id = self.dup_target_depot_var.get().strip() or None

        if quantity == 1:
            self.run_bg(
                lambda: self.client.duplicate_vehicle(scenario_id, vehicle_id, target_depot_id),
                lambda _resp: (self.log_line(f"車両複製: {vehicle_id}"), self.refresh_vehicles()),
            )
            return

        self.run_bg(
            lambda: self.client.duplicate_vehicle_bulk(scenario_id, vehicle_id, quantity, target_depot_id),
            lambda resp: (
                self.log_line(f"車両一括複製: {vehicle_id} x {resp.get('total') or quantity}"),
                self.refresh_vehicles(),
            ),
        )

    def apply_template_to_depot(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        depot_id = self.fleet_depot_var.get().strip()
        template_id = self.apply_template_id_var.get().strip()
        qty = max(1, self._parse_int(self.apply_template_qty_var.get(), 1))
        if not depot_id or not template_id:
            messagebox.showwarning("入力不足", "depotId と templateId を入力してください")
            return

        template = next((t for t in self.template_rows if str(t.get("id") or "") == template_id), None)
        if template is None:
            messagebox.showwarning("入力不足", "指定 templateId が一覧にありません。先にテンプレート一覧更新を実行してください")
            return

        payload = {
            "depotId": depot_id,
            "type": str(template.get("type") or "BEV"),
            "modelName": str(template.get("modelName") or template.get("name") or "TemplateVehicle"),
            "capacityPassengers": int(template.get("capacityPassengers") or 0),
            "batteryKwh": template.get("batteryKwh"),
            "fuelTankL": template.get("fuelTankL"),
            "energyConsumption": float(template.get("energyConsumption") or 0.0),
            "chargePowerKw": template.get("chargePowerKw"),
            "minSoc": template.get("minSoc"),
            "maxSoc": template.get("maxSoc"),
            "acquisitionCost": float(template.get("acquisitionCost") or 0.0),
            "enabled": bool(template.get("enabled", True)),
            "quantity": qty,
        }
        self.run_bg(
            lambda: self.client.create_vehicle_batch(scenario_id, payload),
            lambda resp: (
                self.log_line(f"テンプレート導入: {template_id} -> {depot_id} x {resp.get('total') or qty}"),
                self.refresh_vehicles(),
            ),
        )

    def refresh_templates(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return

        def done(resp: dict[str, Any]) -> None:
            self.template_rows = list(resp.get("items") or [])
            self.template_tree.delete(*self.template_tree.get_children())
            for row in self.template_rows:
                self.template_tree.insert(
                    "",
                    tk.END,
                    iid=str(row.get("id") or ""),
                    values=(
                        row.get("id"),
                        row.get("name"),
                        row.get("type"),
                        row.get("modelName"),
                        row.get("acquisitionCost"),
                        row.get("energyConsumption"),
                        row.get("chargePowerKw"),
                    ),
                )
            self.log_line(f"テンプレート一覧取得: {len(self.template_rows)} 件")

        self.run_bg(lambda: self.client.list_vehicle_templates(scenario_id), done)

    def on_template_select(self, _event=None) -> None:
        selected = self.template_tree.selection()
        if not selected:
            return
        tid = selected[0]
        row = next((r for r in self.template_rows if str(r.get("id") or "") == tid), None)
        if row is None:
            return

        self.t_id_var.set(str(row.get("id") or ""))
        self.t_name_var.set(str(row.get("name") or ""))
        self.t_type_var.set(str(row.get("type") or "BEV"))
        self.t_model_var.set(str(row.get("modelName") or ""))
        self.t_cap_var.set(str(row.get("capacityPassengers") or 0))
        self.t_battery_var.set("" if row.get("batteryKwh") is None else str(row.get("batteryKwh")))
        self.t_fuel_tank_var.set("" if row.get("fuelTankL") is None else str(row.get("fuelTankL")))
        self.t_energy_var.set(str(row.get("energyConsumption") or 0.0))
        self.t_charge_var.set("" if row.get("chargePowerKw") is None else str(row.get("chargePowerKw")))
        self.t_min_soc_var.set("" if row.get("minSoc") is None else str(row.get("minSoc")))
        self.t_max_soc_var.set("" if row.get("maxSoc") is None else str(row.get("maxSoc")))
        self.t_acq_cost_var.set(str(row.get("acquisitionCost") or 0.0))
        self.t_enabled_var.set(bool(row.get("enabled", True)))

    def create_template_from_form(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        payload = self._build_template_payload_from_form()
        if not payload.get("name"):
            messagebox.showwarning("入力不足", "template name を入力してください")
            return
        self.run_bg(
            lambda: self.client.create_vehicle_template(scenario_id, payload),
            lambda _resp: (self.log_line("テンプレートを作成しました"), self.refresh_templates()),
        )

    def update_template_from_form(self) -> None:
        scenario_id = self._selected_scenario_id()
        template_id = self.t_id_var.get().strip()
        if not scenario_id or not template_id:
            messagebox.showwarning("入力不足", "更新対象テンプレートを選択してください")
            return
        payload = self._build_template_payload_from_form()
        self.run_bg(
            lambda: self.client.update_vehicle_template(scenario_id, template_id, payload),
            lambda _resp: (self.log_line(f"テンプレート更新: {template_id}"), self.refresh_templates()),
        )

    def delete_selected_template(self) -> None:
        scenario_id = self._selected_scenario_id()
        template_id = self.t_id_var.get().strip()
        if not scenario_id or not template_id:
            messagebox.showwarning("入力不足", "削除対象テンプレートを選択してください")
            return
        if not messagebox.askyesno("確認", f"テンプレート {template_id} を削除しますか？"):
            return

        def action() -> dict[str, Any]:
            self.client.delete_vehicle_template(scenario_id, template_id)
            return {}

        self.run_bg(action, lambda _resp: (self.log_line(f"テンプレート削除: {template_id}"), self.refresh_templates()))

    def apply_fleet_count(self) -> None:
        scenario_id = self._selected_scenario_id()
        depot_id = self.fleet_depot_var.get().strip()
        if not scenario_id or not depot_id:
            messagebox.showwarning("入力不足", "シナリオと営業所IDを入力してください")
            return
        target = self._parse_int(self.target_bev_count_var.get(), 0)
        if target < 0:
            messagebox.showwarning("入力エラー", "目標台数は0以上にしてください")
            return
        if not messagebox.askyesno("確認", f"営業所 {depot_id} の BEV 台数を {target} 台に調整しますか？"):
            return
        energy = self._parse_float(self.default_energy_var.get(), 1.2)
        battery = self._parse_float(self.default_battery_var.get(), 300.0)
        charge_kw = self._parse_float(self.default_charge_kw_var.get(), 90.0)

        def action() -> dict[str, Any]:
            resp = self.client.list_vehicles(scenario_id, depot_id)
            vehicles = list(resp.get("items") or [])
            bevs = [v for v in vehicles if str(v.get("type") or "").upper() == "BEV"]
            diff = target - len(bevs)
            if diff > 0:
                self.client.create_vehicle_batch(
                    scenario_id,
                    {
                        "depotId": depot_id,
                        "type": "BEV",
                        "modelName": "Backup-BEV",
                        "capacityPassengers": 0,
                        "batteryKwh": battery,
                        "energyConsumption": energy,
                        "chargePowerKw": charge_kw,
                        "acquisitionCost": 0.0,
                        "enabled": True,
                        "quantity": diff,
                    },
                )
            elif diff < 0:
                for v in bevs[diff:]:
                    vid = str(v.get("id") or "").strip()
                    if vid:
                        self.client.delete_vehicle(scenario_id, vid)
            return {"before": len(bevs), "after": target}

        self.run_bg(
            action,
            lambda info: (
                self.log_line(f"BEV台数調整: {info['before']} -> {info['after']} (営業所: {depot_id})"),
                self.refresh_vehicles(),
            ),
        )

    def _prepare_payload(self) -> dict[str, Any]:
        objective_weights = self._parse_objective_weights_json()
        contract_penalty = self._parse_float(self.contract_penalty_coeff_var.get(), 1000000.0)
        if contract_penalty > 0:
            objective_weights.setdefault("slack_penalty", contract_penalty)

        return {
            "selected_depot_ids": self._selected_ids_from_list(self.depot_list),
            "selected_route_ids": self._selected_ids_from_list(self.route_list),
            "day_type": self.day_type_var.get().strip(),
            "service_date": self.service_date_var.get().strip() or None,
            "include_short_turn": self.include_short_turn_var.get(),
            "include_depot_moves": self.include_depot_moves_var.get(),
            "include_deadhead": self.include_deadhead_var.get(),
            "allow_intra_depot_route_swap": self.allow_intra_var.get(),
            "allow_inter_depot_swap": self.allow_inter_var.get(),
            "simulation_settings": {
                "vehicle_count": self._parse_int(self.vehicle_count_var.get(), 10),
                "charger_count": self._parse_int(self.charger_count_var.get(), 4),
                "initial_soc": self._parse_float(self.initial_soc_var.get(), 0.8),
                "charger_power_kw": self._parse_float(self.charger_power_var.get(), 90.0),
                "solver_mode": self.solver_mode_var.get().strip(),
                "objective_mode": self.objective_mode_var.get().strip(),
                "allow_partial_service": self.allow_partial_service_var.get(),
                "unserved_penalty": self._parse_float(self.unserved_penalty_var.get(), 10000.0),
                "time_limit_seconds": self._parse_int(self.time_limit_var.get(), 300),
                "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
                "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
                "include_deadhead": self.include_deadhead_var.get(),
                "grid_flat_price_per_kwh": self._parse_float(self.grid_flat_price_var.get(), 0.0),
                "grid_sell_price_per_kwh": self._parse_float(self.grid_sell_price_var.get(), 0.0),
                "demand_charge_cost_per_kw": self._parse_float(self.demand_charge_var.get(), 0.0),
                "diesel_price_per_l": self._parse_float(self.diesel_price_var.get(), 145.0),
                "grid_co2_kg_per_kwh": self._parse_float(self.grid_co2_var.get(), 0.0),
                "co2_price_per_kg": self._parse_float(self.co2_price_var.get(), 1.0),
                "depot_power_limit_kw": self._parse_float(self.depot_power_limit_var.get(), 500.0),
                "tou_pricing": self._parse_tou_text(),
                "objective_weights": objective_weights,
            },
        }

    def prepare(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(resp: dict[str, Any]) -> None:
            self.prepared_input_id = str(resp.get("preparedInputId") or "")
            self.prepared_var.set(f"prepared_input_id: {self.prepared_input_id or '-'}")
            self.log_line(
                f"Prepare完了: ready={resp.get('ready')} / tripCount={resp.get('tripCount')} / primaryDepot={resp.get('primaryDepotId')}"
            )
            for warning in resp.get("warnings") or []:
                self.log_line(f"警告: {warning}")

        self.run_bg(lambda: self.client.prepare_simulation(scenario_id, self._prepare_payload()), done)

    def _set_job_from_resp(self, resp: dict[str, Any], label: str) -> None:
        self.last_job_id = str(resp.get("job_id") or resp.get("jobId") or "")
        self.job_var.set(f"job: {self.last_job_id or '-'}")
        self.manual_job_id_var.set(self.last_job_id)
        self.log_line(f"{label}: {self.last_job_id}")

    def run_prepared(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id or not self.prepared_input_id:
            messagebox.showwarning("入力不足", "先に Prepare を実行してください")
            return
        self.run_bg(
            lambda: self.client.run_prepared_simulation(scenario_id, self.prepared_input_id),
            lambda resp: self._set_job_from_resp(resp, "Prepared実行ジョブ開始"),
        )

    def run_optimization(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        depots = self._selected_ids_from_list(self.depot_list)
        payload = {
            "mode": self.solver_mode_var.get().strip(),
            "time_limit_seconds": self._parse_int(self.time_limit_var.get(), 300),
            "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
            "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
            "service_id": self.day_type_var.get().strip() or None,
            "depot_id": depots[0] if depots else None,
        }
        self.run_bg(
            lambda: self.client.run_optimization(scenario_id, payload),
            lambda resp: self._set_job_from_resp(resp, "最適化ジョブ開始"),
        )

    def run_simulation_legacy(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        depots = self._selected_ids_from_list(self.depot_list)
        payload = {
            "service_id": self.day_type_var.get().strip() or None,
            "depot_id": depots[0] if depots else None,
            "source": "duties",
        }
        self.run_bg(
            lambda: self.client.run_simulation_legacy(scenario_id, payload),
            lambda resp: self._set_job_from_resp(resp, "Legacyシミュレーションジョブ開始"),
        )

    def run_reoptimize(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        depots = self._selected_ids_from_list(self.depot_list)
        payload = {
            "mode": self.solver_mode_var.get().strip(),
            "current_time": datetime.now().strftime("%H:%M"),
            "time_limit_seconds": self._parse_int(self.time_limit_var.get(), 300),
            "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
            "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
            "service_id": self.day_type_var.get().strip() or None,
            "depot_id": depots[0] if depots else None,
        }
        self.run_bg(
            lambda: self.client.reoptimize(scenario_id, payload),
            lambda resp: self._set_job_from_resp(resp, "再最適化ジョブ開始"),
        )

    def show_capabilities(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def action() -> dict[str, Any]:
            return {
                "simulation": self.client.get_simulation_capabilities(scenario_id),
                "optimization": self.client.get_optimization_capabilities(scenario_id),
            }

        self.run_bg(action, lambda resp: self.log_line("機能情報: " + json.dumps(resp, ensure_ascii=False)))

    def show_simulation_result(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(resp: dict[str, Any]) -> None:
            summary = {
                "status": resp.get("status"),
                "objective": resp.get("objective_value"),
                "cost_breakdown": resp.get("cost_breakdown"),
                "kpi": resp.get("kpi"),
            }
            self.log_line("Simulation結果: " + json.dumps(summary, ensure_ascii=False))

        self.run_bg(lambda: self.client.get_simulation_result(scenario_id), done)

    def show_optimization_result(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(resp: dict[str, Any]) -> None:
            summary = {
                "status": resp.get("status"),
                "objective": resp.get("objective_value"),
                "cost_breakdown": resp.get("cost_breakdown"),
                "kpi": resp.get("kpi"),
            }
            self.log_line("Optimization結果: " + json.dumps(summary, ensure_ascii=False))

        self.run_bg(lambda: self.client.get_optimization_result(scenario_id), done)

    def poll_last_job(self) -> None:
        job_id = self.manual_job_id_var.get().strip() or self.last_job_id
        if not job_id:
            messagebox.showwarning("入力不足", "監視対象の job_id がありません")
            return

        def done(job: dict[str, Any]) -> None:
            status = str(job.get("status") or "")
            progress = job.get("progress")
            msg = str(job.get("message") or "")
            self.log_line(f"Job {job_id}: status={status} progress={progress} message={msg}")
            if status:
                self.job_var.set(f"job: {job_id} ({status})")

        self.run_bg(lambda: self.client.get_job(job_id), done)


def main() -> None:
    root = tk.Tk()
    _ = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
