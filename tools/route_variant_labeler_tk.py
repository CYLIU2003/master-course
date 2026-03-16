"""
Manual Route Variant Labeler (Tkinter)

Purpose
-------
Small desktop UI to manually label route variants and directions with
frontend/backend-aligned field names.

Input
-----
Any CSV/JSONL containing route-like rows. Typical accepted columns:
- route_id / id
- route_name / name / routeLabel
- route_code / routeCode
- direction / canonicalDirection / canonical_direction
- routeVariantId / route_variant_id / odptPatternId / odpt_pattern_id
- routeVariantType / route_variant_type
- operator_id / operatorId / source_operator (optional)

Output
------
1) Manual label mapping CSV (route_variant_manual_labels.csv)
2) Manual label mapping JSON (route_variant_manual_labels.json)
3) Optional merged CSV where label columns are applied onto original rows
4) Optional merged JSONL where label columns are applied onto original rows

Usage
-----
python tools/route_variant_labeler_tk.py
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any
from tkinter import BOTH, END, HORIZONTAL, LEFT, RIGHT, VERTICAL, X, Y, BooleanVar, Scrollbar, StringVar, Tk, messagebox, filedialog
from tkinter import ttk

try:
    from src.route_code_utils import extract_route_series_from_candidates
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from src.route_code_utils import extract_route_series_from_candidates


DIRECTION_CHOICES = ["上り", "下り", "循環線"]
ROUTE_VARIANT_CHOICES = ["本線", "区間便", "入出庫便"]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROUTE_TO_DEPOT_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_route_to_depot_full.csv",
    _REPO_ROOT / "tokyu_bus_route_to_depot.csv",
    _REPO_ROOT / "data" / "seed" / "tokyu" / "route_to_depot.csv",
)
_DEPOT_MASTER_CANDIDATES = (
    _REPO_ROOT / "tokyu_bus_depots_master_full.json",
    _REPO_ROOT / "tokyu_bus_depots_master.json",
    _REPO_ROOT / "data" / "seed" / "tokyu" / "depots.json",
)


@dataclass
class RouteLabelRow:
    key: str
    operator_id: str
    route_id: str
    route_code: str
    route_series_code: str
    route_series_prefix: str
    route_series_number: int | None
    route_family_code: str
    route_family_label: str
    route_name: str
    depot_id: str
    depot_name: str
    route_variant_id: str
    direction: str
    canonicalDirection: str
    canonical_direction: str
    routeVariantType: str
    route_variant_type: str
    routeVariantTypeManual: str
    canonicalDirectionManual: str
    isPrimaryVariant: bool
    classificationConfidence: float
    classificationReasons: str
    classificationSource: str = "manual_override"


class LabelerApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("路線タグ付与ツール")
        self.root.geometry("1280x760")

        self.input_path: Path | None = None
        self.original_rows: list[dict[str, Any]] = []
        self.labels: dict[str, RouteLabelRow] = {}
        self.keys: list[str] = []
        self.key_depot: dict[str, str] = {}
        self.skipped_missing_operator_count: int = 0
        self.depot_names_by_code: dict[str, str] = {}
        self.known_depot_labels: set[str] = set()
        self.depot_id_by_name: dict[str, str] = {}
        self.depot_name_by_id: dict[str, str] = {}

        self._load_authority_depot_maps()

        self._build_ui()

    @staticmethod
    def _normalize_code(text: str) -> str:
        return unicodedata.normalize("NFKC", str(text or "").strip())

    @staticmethod
    def _first_existing_path(candidates: tuple[Path, ...]) -> Path | None:
        for path in candidates:
            if path.exists():
                return path
        return None

    def _load_authority_depot_maps(self) -> None:
        route_map_path = self._first_existing_path(_ROUTE_TO_DEPOT_CANDIDATES)
        if route_map_path:
            try:
                with route_map_path.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        route_code = self._normalize_code(row.get("route_code") or "")
                        depot_id = str(row.get("depot_id") or "").strip()
                        depot_name = str(row.get("depot_name") or "").strip()
                        service_type = str(row.get("service_type") or "").strip().lower()
                        if not route_code or not depot_name:
                            continue
                        if service_type and service_type != "route_code":
                            continue
                        self.depot_names_by_code.setdefault(route_code, depot_name)
                        self.known_depot_labels.add(depot_name)
                        if depot_id:
                            self.depot_id_by_name.setdefault(depot_name, depot_id)
                            self.depot_name_by_id.setdefault(depot_id, depot_name)
            except Exception:
                pass

        depot_master_path = self._first_existing_path(_DEPOT_MASTER_CANDIDATES)
        if depot_master_path:
            try:
                payload = json.loads(depot_master_path.read_text(encoding="utf-8"))
                for depot in payload.get("depots") or []:
                    if not isinstance(depot, dict):
                        continue
                    name = str(depot.get("name") or "").strip()
                    depot_id = str(depot.get("depot_id") or depot.get("depotId") or depot.get("id") or "").strip()
                    if name:
                        self.known_depot_labels.add(name)
                        if depot_id:
                            self.depot_id_by_name.setdefault(name, depot_id)
                            self.depot_name_by_id.setdefault(depot_id, name)
            except Exception:
                pass

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=X)

        ttk.Button(top, text="ファイル読込 (CSV/JSONL)", command=self.open_file).pack(side=LEFT, padx=4)
        ttk.Button(top, text="ラベル保存 CSV/JSON", command=self.save_labels).pack(side=LEFT, padx=4)
        ttk.Button(top, text="マージ保存 CSV", command=self.save_merged_csv).pack(side=LEFT, padx=4)
        ttk.Button(top, text="マージ保存 JSONL", command=self.save_merged_jsonl).pack(side=LEFT, padx=4)

        self.operator_override_var = StringVar(value="tokyu")
        ttk.Label(top, text="operator_id 補完").pack(side=LEFT, padx=(12, 4))
        ttk.Combobox(
            top,
            textvariable=self.operator_override_var,
            values=["", "tokyu", "toei"],
            state="readonly",
            width=8,
        ).pack(side=LEFT)

        self.depot_filter_var = StringVar(value="all")
        ttk.Label(top, text="営業所表示").pack(side=LEFT, padx=(16, 4))
        self.depot_filter_combo = ttk.Combobox(
            top,
            textvariable=self.depot_filter_var,
            values=["all"],
            state="readonly",
            width=20,
        )
        self.depot_filter_combo.pack(side=LEFT)
        self.depot_filter_combo.bind("<<ComboboxSelected>>", self._on_depot_filter_changed)

        self.number_order_var = StringVar(value="asc")
        ttk.Label(top, text="系統番号ソート").pack(side=LEFT, padx=(16, 6))
        ttk.Combobox(top, textvariable=self.number_order_var, values=["asc", "desc"], state="readonly", width=8).pack(side=LEFT)
        ttk.Button(top, text="並び替え適用", command=self.apply_sort).pack(side=LEFT, padx=6)

        self.path_var = StringVar(value="未読込")
        ttk.Label(top, textvariable=self.path_var).pack(side=LEFT, padx=12)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill=BOTH, expand=True)

        left = ttk.Frame(body, padding=8)
        right = ttk.Frame(body, padding=8)
        body.add(left, weight=2)
        body.add(right, weight=3)

        # Left: table
        table_wrap = ttk.Frame(left)
        table_wrap.pack(fill=BOTH, expand=True)

        self.tree = ttk.Treeview(
            table_wrap,
            columns=(
                "route_id",
                "series",
                "route_name",
                "direction",
                "routeVariantType",
                "confidence",
            ),
            show="tree headings",
            selectmode="extended",
            height=30,
        )
        self.tree.heading("#0", text="営業所 / Family")
        self.tree.column("#0", width=260, anchor="w")
        self.tree.heading("route_id", text="route_id")
        self.tree.heading("series", text="系統")
        self.tree.heading("route_name", text="路線名")
        self.tree.heading("direction", text="方向")
        self.tree.heading("routeVariantType", text="便種")
        self.tree.heading("confidence", text="信頼度")
        self.tree.column("route_id", width=180, anchor="w")
        self.tree.column("series", width=120, anchor="center")
        self.tree.column("route_name", width=260, anchor="w")
        self.tree.column("direction", width=110, anchor="center")
        self.tree.column("routeVariantType", width=150, anchor="center")
        self.tree.column("confidence", width=90, anchor="center")
        ysb = Scrollbar(table_wrap, orient=VERTICAL, command=self.tree.yview)
        xsb = Scrollbar(table_wrap, orient=HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<MouseWheel>", self._on_tree_mouse_wheel)
        self.tree.bind("<Button-4>", self._on_tree_mouse_wheel)
        self.tree.bind("<Button-5>", self._on_tree_mouse_wheel)

        # Right: editor
        form = ttk.Frame(right)
        form.pack(fill=BOTH, expand=True)

        self.key_var = StringVar(value="")
        self.series_code_var = StringVar(value="")
        self.operator_var = StringVar(value="")
        self.route_id_var = StringVar(value="")
        self.route_code_var = StringVar(value="")
        self.route_name_var = StringVar(value="")
        self.depot_var = StringVar(value="")
        self.variant_id_var = StringVar(value="")
        self.direction_var = StringVar(value="上り")
        self.variant_var = StringVar(value="本線")
        self.confidence_var = StringVar(value="1.0")
        self.reasons_var = StringVar(value="")
        self.primary_var = BooleanVar(value=False)

        row = 0
        self._add_readonly(form, row, "key", self.key_var); row += 1
        self._add_readonly(form, row, "operator_id", self.operator_var); row += 1
        self._add_readonly(form, row, "route_id", self.route_id_var); row += 1
        self._add_readonly(form, row, "routeSeriesCode (系統)", self.series_code_var); row += 1
        self._add_readonly(form, row, "route_code", self.route_code_var); row += 1
        self._add_readonly(form, row, "route_name", self.route_name_var); row += 1
        ttk.Label(form, text="depot (営業所)").grid(row=row, column=0, sticky="w", pady=4)
        self.depot_combo = ttk.Combobox(form, textvariable=self.depot_var, values=[], state="readonly")
        self.depot_combo.grid(row=row, column=1, sticky="ew", pady=4)
        row += 1
        self._add_readonly(form, row, "routeVariantId", self.variant_id_var); row += 1

        ttk.Label(form, text="direction / canonicalDirection (方向)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.direction_var, values=DIRECTION_CHOICES, state="readonly").grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(form, text="routeVariantType (本線/区間便/入出庫便)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.variant_var, values=ROUTE_VARIANT_CHOICES, state="readonly").grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(form, text="isPrimaryVariant (主系統)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Checkbutton(form, variable=self.primary_var).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(form, text="classificationConfidence (0-1)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.confidence_var).grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Label(form, text="classificationReasons (カンマ区切り)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.reasons_var).grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Button(form, text="選択行へラベル反映", command=self.apply_current).grid(row=row, column=0, columnspan=2, sticky="ew", pady=12)

        form.columnconfigure(1, weight=1)

    def _add_readonly(self, parent: ttk.Frame, row: int, label: str, var: StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ent = ttk.Entry(parent, textvariable=var, state="readonly")
        ent.grid(row=row, column=1, sticky="ew", pady=4)

    @staticmethod
    def _pick(row: dict[str, Any], *keys: str, default: str = "") -> str:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return default

    def _route_key(self, row: dict[str, Any]) -> str:
        operator_id = self._pick(row, "operator_id", "operatorId", "source_operator", default="")
        route_variant_id = self._pick(
            row,
            "routeVariantId",
            "route_variant_id",
            "odptPatternId",
            "odpt_pattern_id",
            default="",
        )
        route_id = self._pick(row, "route_id", "id", default="")
        direction = self._pick(row, "direction", "canonicalDirection", "canonical_direction", default="unknown")

        if route_variant_id:
            base = f"variant:{route_variant_id}"
        else:
            base = f"route:{route_id}:dir:{direction}"

        return f"{operator_id}:{base}" if operator_id else base

    @staticmethod
    def _normalize_direction(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"outbound", "out", "up", "上り", "上り便", "↗"}:
            return "outbound"
        if text in {"inbound", "in", "down", "下り", "下り便", "↙"}:
            return "inbound"
        if text in {"circular", "loop", "循環", "循環線"}:
            return "circular"
        return "outbound"

    @staticmethod
    def _direction_to_choice(value: Any) -> str:
        normalized = LabelerApp._normalize_direction(value)
        if normalized == "inbound":
            return "下り"
        if normalized == "circular":
            return "循環線"
        return "上り"

    @staticmethod
    def _normalize_variant(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"short_turn", "区間", "区間便"}:
            return "short_turn"
        if text in {"depot", "depot_in", "depot_out", "入出庫", "入出庫便", "入庫", "出庫"}:
            return "depot"
        return "main"

    @staticmethod
    def _variant_to_choice(value: Any) -> str:
        normalized = LabelerApp._normalize_variant(value)
        if normalized == "short_turn":
            return "区間便"
        if normalized == "depot":
            return "入出庫便"
        return "本線"

    def _extract_depot_label(self, row: dict[str, Any], operator_id: str) -> str:
        depot_name = self._pick(
            row,
            "depot_name",
            "depotName",
            "depot_label",
            default="",
        )
        if depot_name:
            return depot_name

        depot = self._pick(
            row,
            "depot_id",
            "depotId",
            "depot",
            "depot_code",
            "depotCode",
            "home_depot",
            "homeDepot",
            "homeDepotId",
            default="",
        )
        if depot:
            return self.depot_name_by_id.get(depot, depot)

        for stop_key in ("startStop", "start_stop", "origin", "endStop", "end_stop", "destination"):
            stop_name = self._pick(row, stop_key, default="")
            if stop_name and ("営業所" in stop_name or "車庫" in stop_name):
                return stop_name

        route_label = self._pick(row, "routeLabel", "name", "route_name", default="")
        if route_label:
            match = re.search(r"([^)（\s]*?(営業所|車庫))", route_label)
            if match:
                return match.group(1)

        route_code = self._normalize_code(self._pick(row, "route_code", "routeCode", default=""))
        if route_code:
            mapped = self.depot_names_by_code.get(route_code)
            if mapped:
                return mapped

        if operator_id:
            return f"{operator_id}:未設定営業所"
        return "未設定営業所"

    def _extract_depot_id(self, row: dict[str, Any]) -> str:
        depot_id = self._pick(
            row,
            "depot_id",
            "depotId",
            "homeDepotId",
            "home_depot_id",
            default="",
        )
        if depot_id:
            return depot_id

        route_code = self._normalize_code(self._pick(row, "route_code", "routeCode", default=""))
        if route_code:
            mapped_name = self.depot_names_by_code.get(route_code)
            if mapped_name:
                return self.depot_id_by_name.get(mapped_name, "")
        return ""

    def _on_depot_filter_changed(self, _event=None) -> None:
        self.refresh_tree()
        first_key = self._first_visible_leaf_key()
        if first_key:
            self.tree.selection_set(first_key)
            self.tree.focus(first_key)
            self.tree.see(first_key)
            self.load_to_editor(first_key)

    def _first_visible_leaf_key(self) -> str | None:
        current_filter = self.depot_filter_var.get().strip()
        for key in self.keys:
            if current_filter and current_filter != "all":
                if self.key_depot.get(key, "未設定営業所") != current_filter:
                    continue
            return key
        return None

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="路線/便データを開く (CSV/JSONL)",
            filetypes=[("CSV/JSONL ファイル", "*.csv *.jsonl"), ("CSV ファイル", "*.csv"), ("JSONL ファイル", "*.jsonl"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return

        input_path = Path(path)
        if input_path.suffix.lower() == ".jsonl":
            rows = self._load_jsonl(input_path)
        else:
            rows = self._load_csv(input_path)

        if not rows:
            messagebox.showwarning("データなし", "選択したファイルに行データがありません。")
            return

        self.input_path = input_path
        self.path_var.set(str(input_path))
        self.original_rows = rows
        self.labels.clear()
        self.keys.clear()
        self.key_depot.clear()
        self.skipped_missing_operator_count = 0
        filled_missing_operator_count = 0
        operator_override = self.operator_override_var.get().strip()

        for row in rows:
            operator_id = self._pick(row, "operator_id", "operatorId", "source_operator", default="")
            if not operator_id:
                if operator_override:
                    # Explicit user selection is allowed; do not infer automatically.
                    # Persist override onto the row so merge-save keying stays consistent.
                    operator_id = operator_override
                    row["operator_id"] = operator_id
                    filled_missing_operator_count += 1
                else:
                    # Keep operator boundary strict: do not load rows without operator_id.
                    self.skipped_missing_operator_count += 1
                    continue

            key = self._route_key(row)
            if key in self.labels:
                continue
            route_id = self._pick(row, "route_id", "id", default="")
            route_code = self._pick(row, "route_code", "routeCode", default="")
            route_name = self._pick(row, "route_name", "name", "routeLabel", default="")
            route_series_code, route_series_prefix, route_series_number, _series_source = extract_route_series_from_candidates(
                route_code,
                route_name,
            )
            route_variant_id = self._pick(
                row,
                "routeVariantId",
                "route_variant_id",
                "odptPatternId",
                "odpt_pattern_id",
                default="",
            )
            depot_id = self._extract_depot_id(row)
            depot_name = self._extract_depot_label(row, operator_id)
            if depot_id and (not depot_name or "未設定営業所" in depot_name):
                depot_name = self.depot_name_by_id.get(depot_id, depot_name)
            direction = self._normalize_direction(
                self._pick(row, "direction", "canonicalDirection", "canonical_direction", default="")
            )
            variant = self._pick(
                row,
                "routeVariantTypeManual",
                "routeVariantType",
                "route_variant_type",
                default="",
            )
            variant = self._normalize_variant(variant)
            confidence_raw = self._pick(row, "classificationConfidence", default="1.0")
            try:
                confidence = float(confidence_raw)
            except ValueError:
                confidence = 1.0

            reason_values = row.get("classificationReasons") or row.get("classification_reasons") or ""
            if isinstance(reason_values, list):
                reasons_str = ",".join(str(item) for item in reason_values)
            else:
                reasons_str = str(reason_values)

            label = RouteLabelRow(
                key=key,
                operator_id=operator_id,
                route_id=route_id,
                route_code=route_code,
                route_series_code=route_series_code,
                route_series_prefix=route_series_prefix,
                route_series_number=route_series_number,
                route_family_code=route_series_code or route_code,
                route_family_label=route_series_code or route_name or route_code,
                route_name=route_name,
                depot_id=depot_id,
                depot_name=depot_name,
                route_variant_id=route_variant_id,
                direction=direction,
                canonicalDirection=direction,
                canonical_direction=direction,
                routeVariantType=variant,
                route_variant_type=variant,
                routeVariantTypeManual=variant,
                canonicalDirectionManual=direction,
                isPrimaryVariant=False,
                classificationConfidence=max(0.0, min(1.0, confidence)),
                classificationReasons=reasons_str,
            )
            self.labels[key] = label
            self.keys.append(key)
            self.key_depot[key] = label.depot_name

        self.keys = self._sorted_keys()
        depot_values = sorted({value for value in self.key_depot.values() if value})
        depot_values = sorted(set(depot_values).union(self.known_depot_labels))
        self.depot_filter_combo.configure(values=["all", *depot_values])
        self.depot_combo.configure(values=depot_values)
        if self.depot_filter_var.get() not in ["all", *depot_values]:
            self.depot_filter_var.set("all")

        self.refresh_tree()
        if filled_missing_operator_count > 0:
            messagebox.showinfo(
                "operator 補完",
                f"operator_id がない行を {filled_missing_operator_count} 件、"
                f"'{operator_override}' で補完しました。",
            )
        if self.skipped_missing_operator_count > 0:
            messagebox.showwarning(
                "operator 境界",
                f"operator_id がない行を {self.skipped_missing_operator_count} 件スキップしました。",
            )
        first_key = self._first_visible_leaf_key()
        if first_key:
            self.tree.selection_set(first_key)
            self.tree.focus(first_key)
            self.tree.see(first_key)
            self.load_to_editor(first_key)

    def _load_csv(self, csv_path: Path) -> list[dict[str, Any]]:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    def _load_jsonl(self, jsonl_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        invalid_lines = 0
        with jsonl_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    invalid_lines += 1

        if invalid_lines > 0:
            messagebox.showwarning(
                "JSONL 警告",
                f"不正な JSONL 行を {invalid_lines} 件スキップしました。",
            )

        return rows

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        selected_depot = self.depot_filter_var.get().strip()

        groups: dict[str, dict[str, list[str]]] = {}
        for key in self.keys:
            depot_label = self.key_depot.get(key, "未設定営業所")
            if selected_depot and selected_depot != "all" and depot_label != selected_depot:
                continue
            family_code = self.labels[key].route_series_code or self.labels[key].route_code or "未分類"
            groups.setdefault(depot_label, {}).setdefault(family_code, []).append(key)

        if selected_depot and selected_depot != "all":
            depot_order = [selected_depot] if selected_depot in groups else []
        else:
            depot_order = sorted(groups.keys())

        for depot_label in depot_order:
            family_map = groups.get(depot_label) or {}
            if not family_map:
                continue

            if selected_depot and selected_depot != "all":
                depot_parent = ""
            else:
                depot_id = f"grp:depot:{depot_label}"
                total_count = sum(len(items) for items in family_map.values())
                self.tree.insert("", END, iid=depot_id, text=f"{depot_label} ({total_count}件)", open=True)
                depot_parent = depot_id

            for family_code in sorted(family_map.keys()):
                leaf_keys = family_map[family_code]
                family_id = f"grp:family:{depot_label}:{family_code}"
                self.tree.insert(
                    depot_parent,
                    END,
                    iid=family_id,
                    text=f"{family_code} ({len(leaf_keys)}件)",
                    open=False,
                )
                for key in leaf_keys:
                    row = self.labels[key]
                    self.tree.insert(
                        family_id,
                        END,
                        iid=key,
                        text="route",
                        values=(
                            row.route_id,
                            row.route_series_code,
                            row.route_name,
                            row.direction,
                            row.routeVariantType,
                            f"{row.classificationConfidence:.2f}",
                        ),
                    )

    def _sorted_keys(self) -> list[str]:
        reverse_num = self.number_order_var.get().strip().lower() == "desc"

        def _num_key(v: int | None) -> int:
            if v is None:
                return 10**9
            return -v if reverse_num else v

        return sorted(
            self.keys,
            key=lambda k: (
                self.labels[k].route_series_prefix or "~",
                _num_key(self.labels[k].route_series_number),
                self.labels[k].route_series_code or self.labels[k].route_code,
                self.labels[k].route_name,
                self.labels[k].route_id,
            ),
        )

    def apply_sort(self) -> None:
        if not self.keys:
            return
        selected = self.tree.selection()
        current_key = next((item for item in selected if item in self.labels), None)
        self.keys = self._sorted_keys()
        self.refresh_tree()
        if current_key and current_key in self.labels:
            self.tree.selection_set(current_key)
            self.tree.focus(current_key)
            self.tree.see(current_key)

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        first_leaf = next((item for item in selected if item in self.labels), None)
        if not first_leaf:
            return
        self.load_to_editor(first_leaf)

    def _collect_leaf_keys(self, node_id: str) -> list[str]:
        if node_id in self.labels:
            return [node_id]
        keys: list[str] = []
        for child in self.tree.get_children(node_id):
            keys.extend(self._collect_leaf_keys(child))
        return keys

    def _on_tree_mouse_wheel(self, event) -> str:
        if event.delta:
            units = -1 if event.delta > 0 else 1
            self.tree.yview_scroll(units, "units")
        elif event.num == 4:
            self.tree.yview_scroll(-1, "units")
        elif event.num == 5:
            self.tree.yview_scroll(1, "units")
        return "break"

    def load_to_editor(self, key: str) -> None:
        row = self.labels[key]
        self.key_var.set(row.key)
        self.operator_var.set(row.operator_id)
        self.route_id_var.set(row.route_id)
        self.series_code_var.set(row.route_series_code)
        self.route_code_var.set(row.route_code)
        self.route_name_var.set(row.route_name)
        self.depot_var.set(row.depot_name)
        self.variant_id_var.set(row.route_variant_id)
        self.direction_var.set(self._direction_to_choice(row.direction))
        self.variant_var.set(self._variant_to_choice(row.routeVariantType))
        self.primary_var.set(bool(row.isPrimaryVariant))
        self.confidence_var.set(f"{row.classificationConfidence:.2f}")
        self.reasons_var.set(row.classificationReasons)

    def apply_current(self) -> None:
        selected = self.tree.selection()
        target_keys: list[str] = []
        for item in selected:
            target_keys.extend(self._collect_leaf_keys(item))

        # Keep selection order while removing duplicates.
        target_keys = list(dict.fromkeys(target_keys))

        if not target_keys:
            focused = self.tree.focus()
            if focused:
                target_keys = self._collect_leaf_keys(focused)

        if not target_keys:
            key = self.key_var.get().strip()
            if key in self.labels:
                target_keys = [key]
        if not target_keys:
            messagebox.showwarning("未選択", "先に行を選択してください。")
            return

        try:
            confidence = float(self.confidence_var.get().strip())
        except ValueError:
            messagebox.showwarning("入力エラー", "classificationConfidence は数値で入力してください。")
            return

        confidence = max(0.0, min(1.0, confidence))
        direction = self._normalize_direction(self.direction_var.get())
        variant = self._normalize_variant(self.variant_var.get())
        depot_name = self.depot_var.get().strip()
        depot_id = self.depot_id_by_name.get(depot_name, "") if depot_name else ""

        for key in target_keys:
            row = self.labels[key]
            row.direction = direction
            row.canonicalDirection = direction
            row.canonical_direction = direction
            row.routeVariantType = variant
            row.route_variant_type = variant
            row.routeVariantTypeManual = variant
            row.canonicalDirectionManual = direction
            if depot_name:
                row.depot_name = depot_name
                row.depot_id = depot_id
                self.key_depot[key] = depot_name
            row.isPrimaryVariant = bool(self.primary_var.get())
            row.classificationConfidence = confidence
            row.classificationReasons = self.reasons_var.get().strip()
            self.labels[key] = row

        self.refresh_tree()
        self.tree.selection_set(target_keys)
        self.tree.focus(target_keys[0])
        self.tree.see(target_keys[0])
        self.load_to_editor(target_keys[0])
        messagebox.showinfo("反映完了", f"{len(target_keys)} 件の路線にラベルを反映しました。")

    def _labels_as_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for key in self.keys:
            row = self.labels[key]
            rows.append(asdict(row))
        return rows

    def save_labels(self) -> None:
        if not self.labels:
            messagebox.showwarning("ラベルなし", "先に CSV/JSONL を読み込んでください。")
            return

        default_base = "route_variant_manual_labels"
        if self.input_path is not None:
            default_dir = self.input_path.parent
        else:
            default_dir = Path.cwd()

        csv_path = filedialog.asksaveasfilename(
            title="ラベルCSVを保存",
            defaultextension=".csv",
            initialdir=str(default_dir),
            initialfile=f"{default_base}.csv",
            filetypes=[("CSV ファイル", "*.csv")],
        )
        if not csv_path:
            return

        json_path = str(Path(csv_path).with_suffix(".json"))
        rows = self._labels_as_rows()

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"items": rows}, f, ensure_ascii=False, indent=2)

        messagebox.showinfo("保存完了", f"保存しました:\n{csv_path}\n{json_path}")

    def save_merged_csv(self) -> None:
        if not self.original_rows or not self.labels:
            messagebox.showwarning("データなし", "先にファイル読込とラベル反映を実行してください。")
            return

        default_name = "labeled_input.csv"
        if self.input_path is not None:
            default_dir = self.input_path.parent
        else:
            default_dir = Path.cwd()

        out_path = filedialog.asksaveasfilename(
            title="マージ済みCSVを保存",
            defaultextension=".csv",
            initialdir=str(default_dir),
            initialfile=default_name,
            filetypes=[("CSV ファイル", "*.csv")],
        )
        if not out_path:
            return

        merged: list[dict[str, object]] = []
        for row in self.original_rows:
            key = self._route_key(row)
            label = self.labels.get(key)
            out = dict(row)
            if label is not None:
                out.update(
                    {
                        "direction": label.direction,
                        "canonicalDirection": label.canonicalDirection,
                        "canonical_direction": label.canonical_direction,
                        "routeVariantType": label.routeVariantType,
                        "route_variant_type": label.route_variant_type,
                        "routeVariantTypeManual": label.routeVariantTypeManual,
                        "canonicalDirectionManual": label.canonicalDirectionManual,
                        "isPrimaryVariant": str(label.isPrimaryVariant).lower(),
                        "classificationConfidence": label.classificationConfidence,
                        "classificationReasons": label.classificationReasons,
                        "classificationSource": label.classificationSource,
                        "routeVariantId": label.route_variant_id,
                        "route_variant_id": label.route_variant_id,
                        "operator_id": label.operator_id,
                        "depot_id": label.depot_id,
                        "depotId": label.depot_id,
                        "depot_name": label.depot_name,
                        "depotName": label.depot_name,
                        "routeSeriesCode": label.route_series_code,
                        "routeSeriesPrefix": label.route_series_prefix,
                        "routeSeriesNumber": label.route_series_number,
                        "routeFamilyCode": label.route_family_code,
                        "routeFamilyLabel": label.route_family_label,
                    }
                )
            merged.append(out)

        fieldnames: list[str] = []
        for row in merged:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(merged)

        messagebox.showinfo("保存完了", f"マージ済みCSVを保存しました:\n{out_path}")

    def save_merged_jsonl(self) -> None:
        if not self.original_rows or not self.labels:
            messagebox.showwarning("データなし", "先にファイル読込とラベル反映を実行してください。")
            return

        default_name = "labeled_input.jsonl"
        if self.input_path is not None:
            default_dir = self.input_path.parent
        else:
            default_dir = Path.cwd()

        out_path = filedialog.asksaveasfilename(
            title="マージ済みJSONLを保存",
            defaultextension=".jsonl",
            initialdir=str(default_dir),
            initialfile=default_name,
            filetypes=[("JSONL ファイル", "*.jsonl")],
        )
        if not out_path:
            return

        merged: list[dict[str, object]] = []
        for row in self.original_rows:
            key = self._route_key(row)
            label = self.labels.get(key)
            out = dict(row)
            if label is not None:
                out.update(
                    {
                        "direction": label.direction,
                        "canonicalDirection": label.canonicalDirection,
                        "canonical_direction": label.canonical_direction,
                        "routeVariantType": label.routeVariantType,
                        "route_variant_type": label.route_variant_type,
                        "routeVariantTypeManual": label.routeVariantTypeManual,
                        "canonicalDirectionManual": label.canonicalDirectionManual,
                        "isPrimaryVariant": bool(label.isPrimaryVariant),
                        "classificationConfidence": label.classificationConfidence,
                        "classificationReasons": label.classificationReasons,
                        "classificationSource": label.classificationSource,
                        "routeVariantId": label.route_variant_id,
                        "route_variant_id": label.route_variant_id,
                        "operator_id": label.operator_id,
                        "depot_id": label.depot_id,
                        "depotId": label.depot_id,
                        "depot_name": label.depot_name,
                        "depotName": label.depot_name,
                        "routeSeriesCode": label.route_series_code,
                        "routeSeriesPrefix": label.route_series_prefix,
                        "routeSeriesNumber": label.route_series_number,
                        "routeFamilyCode": label.route_family_code,
                        "routeFamilyLabel": label.route_family_label,
                    }
                )
            merged.append(out)

        with open(out_path, "w", encoding="utf-8") as f:
            for row in merged:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        messagebox.showinfo("保存完了", f"マージ済みJSONLを保存しました:\n{out_path}")


def main() -> None:
    root = Tk()
    app = LabelerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
