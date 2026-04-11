"""
バックアップ運用コンソール (Tkinter)

目的:
- フロント運用の主要機能を Tk で代替
- シナリオ管理 / quick-setup / 車両管理 / テンプレート管理 / 実行 / 結果確認

実行:
  python tools/scenario_backup_tk.py
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import csv
import json
import os
import re
import threading
import tkinter as tk
import unicodedata
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any
from urllib import error, parse, request

from src.objective_modes import normalize_objective_mode
from src.optimization.common.cost_components import (
    COST_COMPONENT_DEFINITIONS,
    default_cost_component_flags,
    normalize_cost_component_flags,
)
from src.optimization.common.pv_area import (
    DEFAULT_PANEL_POWER_DENSITY_KW_M2,
    DEFAULT_PERFORMANCE_RATIO,
    DEFAULT_USABLE_AREA_RATIO,
    estimate_depot_pv_from_area,
    positive_or_none,
)
from src.route_family_runtime import (
    normalize_direction,
    normalize_variant_type,
)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DERIVED_PV_PROFILE_DIR = _REPO_ROOT / "data" / "derived" / "pv_profiles"
_SOLCAST_AVG_PROFILE_ID = "solcast_avg_2025_08_60min"
_ACTUAL_DATE_PV_PROFILE_ID = "actual_date_profile"
_WEATHER_MODE_OPTIONS = (
    _ACTUAL_DATE_PV_PROFILE_ID,
    "sunny",
    "cloudy",
    "rainy",
)
_RESULT_METRIC_LABELS = {
    "status": "状態",
    "mode": "実行モード",
    "objective": "目的値",
    "total_cost": "総コスト",
    "total_cost_with_assets": "総コスト(資産込み)",
    "served_trips": "担当便数",
    "unserved_trips": "未担当便数",
    "vehicle_count_used": "使用車両数",
    "solve_time_seconds": "計算時間[s]",
    "energy_cost": "電力コスト",
    "electricity_cost_final": "確定電力コスト",
    "electricity_cost_provisional_leftover": "暫定電力コスト残",
    "vehicle_cost": "車両コスト",
    "driver_cost": "乗務員コスト",
    "penalty_unserved": "未担当ペナルティ",
    "fuel_cost": "燃料コスト",
    "demand_charge": "デマンド料金",
    "battery_degradation_cost": "電池劣化コスト",
    "co2_cost": "CO2コスト",
    "total_co2_kg": "CO2排出量[kg]",
}
_PRIMARY_COST_BREAKDOWN_KEYS = (
    "total_cost",
    "total_cost_with_assets",
    "energy_cost",
    "electricity_cost_final",
    "vehicle_cost",
    "driver_cost",
    "penalty_unserved",
    "demand_charge",
    "fuel_cost",
    "battery_degradation_cost",
    "co2_cost",
)
_RESULT_COMPARE_KEYS = (
    "status",
    "mode",
    "total_cost",
    "objective",
    "served_trips",
    "unserved_trips",
    "vehicle_count_used",
    "solve_time_seconds",
    "energy_cost",
    "vehicle_cost",
    "driver_cost",
    "penalty_unserved",
    "electricity_cost_final",
    "electricity_cost_provisional_leftover",
    "fuel_cost",
    "demand_charge",
    "battery_degradation_cost",
    "co2_cost",
)


def _group_cost_components_for_ui() -> list[tuple[str, list[Any]]]:
    grouped: list[tuple[str, list[Any]]] = []
    for definition in COST_COMPONENT_DEFINITIONS:
        if not grouped or grouped[-1][0] != definition.section:
            grouped.append((definition.section, []))
        grouped[-1][1].append(definition)
    return grouped


def _result_metric_label(key: str) -> str:
    return _RESULT_METRIC_LABELS.get(str(key), str(key))


def _result_numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _format_result_value(value: Any) -> str:
    numeric = _result_numeric(value)
    if numeric is None:
        return "" if value is None else str(value)
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{int(round(numeric)):,}"
    return f"{numeric:,.3f}".rstrip("0").rstrip(".")


def _ordered_cost_breakdown_items(costs: Any) -> list[dict[str, Any]]:
    if not isinstance(costs, dict):
        return []
    total_cost = _result_numeric(costs.get("total_cost"))
    if total_cost is None or abs(total_cost) <= 1e-9:
        total_cost = _result_numeric(costs.get("total_cost_with_assets"))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered_keys = [*list(_PRIMARY_COST_BREAKDOWN_KEYS), *[str(key) for key in costs.keys()]]
    total_keys = {"total_cost", "total_cost_with_assets"}
    for order, key in enumerate(ordered_keys):
        if key in seen:
            continue
        if key not in costs:
            continue
        seen.add(key)
        value = costs.get(key)
        numeric = _result_numeric(value)
        non_zero = numeric is not None and abs(numeric) > 1e-9
        share = None
        if (
            numeric is not None
            and total_cost is not None
            and abs(total_cost) > 1e-9
            and key not in total_keys
        ):
            share = numeric / total_cost
        items.append(
            {
                "key": key,
                "label": _result_metric_label(key),
                "value": value,
                "numeric": numeric,
                "share": share,
                "non_zero": non_zero,
                "sort_rank": order,
            }
        )
    items.sort(
        key=lambda row: (
            0 if row["key"] in total_keys else 1 if row["non_zero"] else 2,
            row["sort_rank"],
            row["key"],
        )
    )
    return items


class _Tooltip:
    """ウィジェット上にホバーすると表示されるシンプルなツールチップ。"""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event: Any = None) -> None:
        if self._tip or not self._text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tip = tk.Toplevel(self._widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tip.attributes("-topmost", True)
        tk.Label(
            tip,
            text=self._text,
            justify=tk.LEFT,
            background="#ffffc0",
            relief="solid",
            borderwidth=1,
            font=("TkDefaultFont", 8),
            wraplength=320,
            padx=4,
            pady=3,
        ).pack()

    def _hide(self, _event: Any = None) -> None:
        if self._tip:
            self._tip.destroy()
            self._tip = None


def _dataset_item_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("dataset_id") or item.get("datasetId") or "").strip()


def _dataset_runtime_ready(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("runtimeReady")
        or item.get("runtime_ready")
        or item.get("builtReady")
        or item.get("built_ready")
        or item.get("shardReady")
        or item.get("shard_ready")
    )


def _normalize_scope_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "").strip())


def _scope_depot_id(route: dict[str, Any]) -> str:
    depot_id = _normalize_scope_text(route.get("depotId"))
    return depot_id or "__unassigned__"


def _scope_route_family_code(route: dict[str, Any]) -> str:
    return (
        _normalize_scope_text(route.get("routeFamilyCode"))
        or _normalize_scope_text(route.get("routeSeriesCode"))
        or _normalize_scope_text(route.get("routeCode"))
        or _normalize_scope_text(route.get("id"))
        or "UNCLASSIFIED"
    )


def _scope_family_key(depot_id: str, family_code: str) -> str:
    return f"{depot_id}::{family_code}"


def _scope_route_sort_key(route: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _scope_depot_id(route),
        _scope_route_family_code(route),
        int(route.get("familySortOrder") or 999),
        _normalize_scope_text(route.get("routeLabel") or route.get("name") or ""),
        _normalize_scope_text(route.get("id")),
    )


def _sanitize_objective_weights(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in payload.items():
        try:
            out[str(key)] = float(value)
        except Exception:
            continue
    return out


def _compose_saved_objective_weights(
    base_weights: dict[str, float],
    *,
    slack_penalty: float | None,
    degradation_weight: float | None,
) -> dict[str, float]:
    saved = _sanitize_objective_weights(base_weights)
    if slack_penalty is not None and slack_penalty > 0:
        saved["slack_penalty"] = float(slack_penalty)
    if degradation_weight is not None and degradation_weight > 0:
        saved["degradation"] = float(degradation_weight)
    return saved


def _split_saved_objective_weights(
    payload: Any,
) -> tuple[dict[str, float], float | None, float | None]:
    saved = _sanitize_objective_weights(payload)
    slack_penalty = saved.pop("slack_penalty", None)
    degradation_weight = saved.pop("degradation", None)
    legacy_degradation = saved.pop("battery_degradation_cost", None)
    if degradation_weight is None:
        degradation_weight = legacy_degradation
    return saved, slack_penalty, degradation_weight


def _group_scope_routes_by_family(
    routes: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    family_keys_by_depot: dict[str, list[str]] = {}
    family_route_ids: dict[str, list[str]] = {}
    family_labels: dict[str, str] = {}

    for route in sorted(routes, key=_scope_route_sort_key):
        route_id = _normalize_scope_text(route.get("id"))
        if not route_id:
            continue
        depot_id = _scope_depot_id(route)
        family_code = _scope_route_family_code(route)
        family_key = _scope_family_key(depot_id, family_code)
        if family_key not in family_route_ids:
            family_route_ids[family_key] = []
            family_label = _normalize_scope_text(
                route.get("routeFamilyLabel")
                or route.get("displayName")
                or route.get("routeLabel")
            )
            family_labels[family_key] = (
                f"{family_code} | {family_label}"
                if family_label and family_label != family_code
                else family_code
            )
            family_keys_by_depot.setdefault(depot_id, []).append(family_key)
        family_route_ids[family_key].append(route_id)

    return family_keys_by_depot, family_route_ids, family_labels


def _expand_selected_routes_to_family_members(
    routes: list[dict[str, Any]],
    selected_route_ids: set[str],
) -> set[str]:
    selected_pairs: set[tuple[str, str]] = set()
    for route in routes:
        route_id = _normalize_scope_text(route.get("id"))
        if route_id and route_id in selected_route_ids:
            selected_pairs.add((_scope_depot_id(route), _scope_route_family_code(route)))
    if not selected_pairs:
        return set(selected_route_ids)

    expanded = set(selected_route_ids)
    for route in routes:
        route_id = _normalize_scope_text(route.get("id"))
        if not route_id:
            continue
        pair = (_scope_depot_id(route), _scope_route_family_code(route))
        if pair in selected_pairs:
            expanded.add(route_id)
    return expanded


def _scope_variant_display_name(route: dict[str, Any]) -> str:
    raw_variant = str(route.get("routeVariantType") or "").strip()
    variant = (
        normalize_variant_type(raw_variant, direction="unknown")
        if raw_variant
        else "unknown"
    )
    direction = normalize_direction(route.get("canonicalDirection"), default="unknown")
    labels = {
        "main_outbound": "本線 上り",
        "main_inbound": "本線 下り",
        "main": "本線",
        "short_turn": "区間便",
        "branch": "枝線",
        "depot_out": "出庫便",
        "depot_in": "入庫便",
        "depot": "入出庫便",
        "unknown": "未分類",
    }
    base = labels.get(variant, "未分類")
    if variant in {"short_turn", "branch"} and direction in {"outbound", "inbound"}:
        dir_label = "上り" if direction == "outbound" else "下り"
        return f"{base} {dir_label}"
    return base


def _scope_route_child_label(route: dict[str, Any]) -> str:
    variant_label = _scope_variant_display_name(route)
    route_label = _normalize_scope_text(
        route.get("routeLabel")
        or route.get("name")
        or route.get("displayName")
        or route.get("id")
    )
    return f"{variant_label} | {route_label}"


def _scope_route_trip_count(route: dict[str, Any], day_type: str | None = None) -> int:
    counts = route.get("tripCountsByDayType") or {}
    if isinstance(counts, dict) and day_type:
        raw = counts.get(str(day_type).strip())
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            pass
    for key in ("tripCountSelectedDay", "tripCount"):
        raw = route.get(key)
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return 0


def _scope_route_total_trip_count(route: dict[str, Any]) -> int:
    raw_total = route.get("tripCountTotal")
    try:
        return int(float(raw_total))
    except (TypeError, ValueError):
        pass
    counts = route.get("tripCountsByDayType") or {}
    if isinstance(counts, dict) and counts:
        total = 0
        for value in counts.values():
            try:
                total += int(float(value))
            except (TypeError, ValueError):
                continue
        return total
    return _scope_route_trip_count(route)


def _scope_trip_count_text(
    route: dict[str, Any],
    *,
    day_type: str,
    day_type_label: str,
) -> str:
    selected_trip_count = _scope_route_trip_count(route, day_type)
    total_trip_count = _scope_route_total_trip_count(route)
    if total_trip_count > 0 and total_trip_count != selected_trip_count:
        return f"{day_type_label}{selected_trip_count}便 / 全{total_trip_count}便"
    return f"{day_type_label}{selected_trip_count}便"


def _scope_variant_bucket(route: dict[str, Any]) -> str:
    raw_variant = str(route.get("routeVariantType") or "").strip()
    variant = (
        normalize_variant_type(raw_variant, direction="unknown")
        if raw_variant
        else "unknown"
    )
    if variant in {"main", "main_outbound", "main_inbound"}:
        return "main"
    if variant == "short_turn":
        return "shortTurn"
    if variant in {"depot", "depot_in", "depot_out"}:
        return "depot"
    if variant == "branch":
        return "branch"
    return "unknown"


def _empty_scope_route_summary() -> dict[str, int]:
    return {
        "familyCount": 0,
        "routeCount": 0,
        "tripCount": 0,
        "mainRouteCount": 0,
        "mainTripCount": 0,
        "shortTurnRouteCount": 0,
        "shortTurnTripCount": 0,
        "depotRouteCount": 0,
        "depotTripCount": 0,
        "branchRouteCount": 0,
        "branchTripCount": 0,
        "unknownRouteCount": 0,
        "unknownTripCount": 0,
    }


def _scope_summarize_routes(
    routes: list[dict[str, Any]],
    *,
    day_type: str,
) -> dict[str, int]:
    summary = _empty_scope_route_summary()
    family_codes: set[str] = set()
    for route in routes:
        route_id = _normalize_scope_text(route.get("id"))
        if not route_id:
            continue
        summary["routeCount"] += 1
        trip_count = _scope_route_trip_count(route, day_type)
        summary["tripCount"] += trip_count
        family_code = _scope_route_family_code(route)
        if family_code:
            family_codes.add(family_code)
        bucket = _scope_variant_bucket(route)
        summary[f"{bucket}RouteCount"] += 1
        summary[f"{bucket}TripCount"] += trip_count
    summary["familyCount"] = len(family_codes)
    return summary


def _scope_variant_mix_text(summary: dict[str, Any], *, metric: str = "trips") -> str:
    suffix = "TripCount" if metric == "trips" else "RouteCount"
    labels = {
        "main": "本線",
        "shortTurn": "区間",
        "depot": "入出庫",
        "branch": "枝線",
        "unknown": "未分類",
    }
    parts: list[str] = []
    for bucket in ("main", "shortTurn", "depot", "branch", "unknown"):
        raw = summary.get(f"{bucket}{suffix}")
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            continue
        unit = "便" if metric == "trips" else "variant"
        parts.append(f"{labels[bucket]}{value}{unit}")
    return " / ".join(parts) if parts else "内訳なし"


def _scope_route_search_text(route: dict[str, Any]) -> str:
    fields = [
        route.get("id"),
        route.get("displayName"),
        route.get("routeCode"),
        route.get("routeLabel"),
        route.get("routeFamilyCode"),
        route.get("routeFamilyLabel"),
        route.get("routeSeriesCode"),
        route.get("canonicalDirection"),
        route.get("depotId"),
        _scope_variant_display_name(route),
    ]
    return " ".join(
        _normalize_scope_text(value).lower()
        for value in fields
        if _normalize_scope_text(value)
    )


def _scope_filter_routes(
    routes: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_scope_text(query).lower()
    if not normalized_query:
        return list(routes)
    tokens = [token for token in normalized_query.split() if token]
    if not tokens:
        return list(routes)
    filtered: list[dict[str, Any]] = []
    for route in routes:
        haystack = str(route.get("_scopeSearchText") or "")
        if not haystack:
            haystack = _scope_route_search_text(route)
        if all(token in haystack for token in tokens):
            filtered.append(route)
    return filtered


def _scope_visible_routes_for_day(
    routes: list[dict[str, Any]],
    day_type: str,
) -> list[dict[str, Any]]:
    _ = day_type
    return list(routes)


def _choose_dataset_options(datasets_resp: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in list(datasets_resp.get("items") or []) if isinstance(item, dict)]
    all_dataset_ids: list[str] = []
    runtime_ready_ids: list[str] = []
    hidden_ids: list[str] = []
    for item in items:
        dataset_id = _dataset_item_id(item)
        if not dataset_id:
            continue
        all_dataset_ids.append(dataset_id)
        if _dataset_runtime_ready(item):
            runtime_ready_ids.append(dataset_id)
        else:
            hidden_ids.append(dataset_id)

    use_runtime_ready_only = bool(runtime_ready_ids)
    visible_ids = runtime_ready_ids if use_runtime_ready_only else all_dataset_ids
    default_dataset_id = str(datasets_resp.get("defaultDatasetId") or "").strip()
    if "tokyu_full" in visible_ids:
        default_dataset_id = "tokyu_full"
    elif default_dataset_id not in visible_ids:
        default_dataset_id = visible_ids[0] if visible_ids else "tokyu_full"

    return {
        "visibleIds": visible_ids,
        "hiddenIds": hidden_ids if use_runtime_ready_only else [],
        "defaultDatasetId": default_dataset_id,
        "usedRuntimeReadyOnly": use_runtime_ready_only,
    }


def _default_depot_energy_asset_row(depot_id: str) -> dict[str, Any]:
    return {
        "depot_id": depot_id,
        "pv_enabled": False,
        "pv_generation_kwh_by_slot": [],
        "capacity_factor_by_slot": [],
        "depot_area_m2": None,
        "usable_area_ratio": DEFAULT_USABLE_AREA_RATIO,
        "panel_power_density_kw_m2": DEFAULT_PANEL_POWER_DENSITY_KW_M2,
        "performance_ratio": DEFAULT_PERFORMANCE_RATIO,
        "estimated_installable_area_m2": 0.0,
        "pv_capacity_kw": 0.0,
        "bess_enabled": False,
        "bess_energy_kwh": 0.0,
        "bess_power_kw": 0.0,
        "bess_initial_soc_kwh": 0.0,
        "bess_soc_min_kwh": 0.0,
        "bess_soc_max_kwh": 0.0,
        "allow_grid_to_bess": False,
        "grid_to_bess_price_mode": "tou",
        "grid_to_bess_price_threshold_yen_per_kwh": 0.0,
        "grid_to_bess_allowed_slot_indices": [],
        "bess_priority_mode": "cost_driven",
        "bess_terminal_soc_min_kwh": 0.0,
        "provisional_energy_cost_yen_per_kwh": 0.0,
    }


def _coerce_float_list(values: Any) -> list[float]:
    out: list[float] = []
    for item in list(values or []):
        try:
            out.append(float(item or 0.0))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _parse_iso_date_or_none(value: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def _build_service_dates(
    start_date_text: str,
    *,
    planning_days: int,
) -> list[str] | None:
    start_date = _parse_iso_date_or_none(start_date_text)
    if start_date is None:
        return [] if not str(start_date_text or "").strip() else None
    day_count = max(int(planning_days or 1), 1)
    return [
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range(day_count)
    ]


def _format_service_dates_summary(service_dates: list[str]) -> str:
    if not service_dates:
        return "未設定"
    if len(service_dates) == 1:
        return service_dates[0]
    return f"{service_dates[0]} .. {service_dates[-1]} ({len(service_dates)}日)"


def _load_daily_pv_profile_for_depot(
    depot_id: str,
    service_date: str,
    *,
    profile_root: Path = _DERIVED_PV_PROFILE_DIR,
) -> dict[str, Any] | None:
    path = profile_root / f"{depot_id}_{service_date}_60min.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None

    try:
        slot_minutes = max(int(doc.get("slot_minutes") or 60), 1)
    except (TypeError, ValueError):
        slot_minutes = 60
    duration_h = max(slot_minutes / 60.0, 1.0e-9)
    try:
        capacity_kw = float(doc.get("capacity_kw") or doc.get("pv_capacity_kw") or 0.0)
    except (TypeError, ValueError):
        capacity_kw = 0.0
    slots = _coerce_float_list(doc.get("pv_generation_kwh_by_slot") or [])
    capacity_factors = _coerce_float_list(doc.get("capacity_factor_by_slot") or [])
    if not capacity_factors and slots and capacity_kw > 0.0:
        capacity_factors = [
            round(max(value, 0.0) / (capacity_kw * duration_h), 6)
            for value in slots
        ]
    if not slots and capacity_factors:
        slots = [
            round(max(capacity_kw, 0.0) * max(value, 0.0) * duration_h, 6)
            for value in capacity_factors
        ]
    if capacity_factors and len(capacity_factors) != len(slots):
        if slots and capacity_kw > 0.0:
            capacity_factors = [
                round(max(value, 0.0) / (capacity_kw * duration_h), 6)
                for value in slots
            ]
        elif capacity_factors:
            slots = [
                round(max(capacity_kw, 0.0) * max(value, 0.0) * duration_h, 6)
                for value in capacity_factors
            ]
    if not slots:
        return None
    return {
        "date": service_date,
        "depotId": depot_id,
        "path": str(path),
        "slotMinutes": slot_minutes,
        "capacityKw": capacity_kw,
        "capacityFactorBySlot": capacity_factors,
        "pvGenerationKwhBySlot": slots,
    }


def _compose_pv_generation_from_capacity_factors(
    capacity_kw: float,
    factor_rows: list[dict[str, Any]],
) -> tuple[list[float], list[dict[str, Any]]]:
    combined_slots: list[float] = []
    generation_rows: list[dict[str, Any]] = []
    effective_capacity_kw = max(float(capacity_kw or 0.0), 0.0)
    for item in factor_rows:
        slot_minutes = max(
            int(item.get("slot_minutes") or item.get("slotMinutes") or 60),
            1,
        )
        duration_h = max(slot_minutes / 60.0, 1.0e-9)
        factors = _coerce_float_list(
            item.get("capacity_factor_by_slot") or item.get("capacityFactorBySlot") or []
        )
        daily_slots = [
            round(effective_capacity_kw * max(value, 0.0) * duration_h, 6)
            for value in factors
        ]
        generation_rows.append(
            {
                "date": str(item.get("date") or ""),
                "slot_minutes": slot_minutes,
                "pv_generation_kwh_by_slot": daily_slots,
            }
        )
        combined_slots.extend(daily_slots)
    return combined_slots, generation_rows


def _apply_area_pv_estimate_to_row(row: dict[str, Any]) -> float:
    area_value = row.get("depot_area_m2")
    if area_value is None:
        area_value = row.get("depotAreaM2")
    estimate = estimate_depot_pv_from_area(
        area_value,
        usable_area_ratio=row.get("usable_area_ratio", row.get("usableAreaRatio")),
        panel_power_density_kw_m2=row.get(
            "panel_power_density_kw_m2",
            row.get("panelPowerDensityKwM2"),
        ),
    )
    row["depot_area_m2"] = estimate.depot_area_m2
    row["usable_area_ratio"] = estimate.usable_area_ratio
    row["panel_power_density_kw_m2"] = estimate.panel_power_density_kw_m2
    try:
        performance_ratio = float(row.get("performance_ratio") or row.get("performanceRatio") or DEFAULT_PERFORMANCE_RATIO)
    except (TypeError, ValueError):
        performance_ratio = DEFAULT_PERFORMANCE_RATIO
    if performance_ratio <= 0.0:
        performance_ratio = DEFAULT_PERFORMANCE_RATIO
    row["performance_ratio"] = performance_ratio
    row["estimated_installable_area_m2"] = round(estimate.installable_area_m2, 6)
    row["pv_capacity_kw"] = round(estimate.capacity_kw, 6) if estimate.depot_area_m2 is not None else 0.0
    row["pv_enabled"] = estimate.depot_area_m2 is not None and estimate.capacity_kw > 0.0
    return float(row["pv_capacity_kw"])


def _rebuild_pv_generation_for_row(row: dict[str, Any]) -> dict[str, Any]:
    capacity_kw = _apply_area_pv_estimate_to_row(row)
    factor_rows = list(row.get("pv_capacity_factor_by_date") or [])
    if not factor_rows:
        return row
    combined_slots, generation_rows = _compose_pv_generation_from_capacity_factors(
        capacity_kw,
        factor_rows,
    )
    row["pv_generation_kwh_by_slot"] = combined_slots
    row["pv_generation_kwh_by_date"] = generation_rows
    row["pv_profile_dates"] = [
        str(item.get("date") or "")
        for item in generation_rows
        if str(item.get("date") or "").strip()
    ]
    return row


def _load_selected_date_pv_profile_for_depot(
    depot_id: str,
    service_dates: list[str],
    *,
    current_depot_area_m2: Any = None,
    profile_root: Path = _DERIVED_PV_PROFILE_DIR,
) -> tuple[dict[str, Any] | None, list[str]]:
    profiles: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    for service_date in service_dates:
        profile = _load_daily_pv_profile_for_depot(
            depot_id,
            service_date,
            profile_root=profile_root,
        )
        if profile is None:
            missing_dates.append(service_date)
            continue
        profiles.append(profile)
    if missing_dates:
        return None, missing_dates
    if not profiles:
        return None, list(service_dates)

    default_capacity_kw = 0.0
    for item in profiles:
        try:
            value = float(item.get("capacityKw") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0.0:
            default_capacity_kw = value
            break
    estimate = estimate_depot_pv_from_area(current_depot_area_m2)
    effective_capacity_kw = estimate.capacity_kw if estimate.depot_area_m2 is not None else 0.0
    factor_rows = [
        {
            "date": item["date"],
            "slot_minutes": item["slotMinutes"],
            "capacity_factor_by_slot": list(item.get("capacityFactorBySlot") or []),
        }
        for item in profiles
    ]
    combined_slots, generation_rows = _compose_pv_generation_from_capacity_factors(
        effective_capacity_kw,
        factor_rows,
    )
    first_date = service_dates[0]
    last_date = service_dates[-1]
    profile_range = first_date if len(service_dates) == 1 else f"{first_date}_to_{last_date}"
    return (
        {
            "profileId": f"{depot_id}_{profile_range}_{profiles[0]['slotMinutes']}min",
            "depotId": depot_id,
            "serviceDates": list(service_dates),
            "slotMinutes": int(profiles[0]["slotMinutes"]),
            "capacityKw": round(effective_capacity_kw, 6),
            "defaultCapacityKw": round(default_capacity_kw, 6),
            "depotAreaM2": estimate.depot_area_m2,
            "estimatedInstallableAreaM2": round(estimate.installable_area_m2, 6),
            "pvGenerationKwhBySlot": combined_slots,
            "pvGenerationKwhByDate": generation_rows,
            "pvCapacityFactorByDate": factor_rows,
        },
        [],
    )


def _merge_selected_depot_pv_assets(
    selected_depot_ids: list[str],
    current_rows: list[dict[str, Any]] | None,
    service_dates: list[str],
    *,
    depot_area_by_id: dict[str, Any] | None = None,
    profile_root: Path = _DERIVED_PV_PROFILE_DIR,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows_by_depot: dict[str, dict[str, Any]] = {}
    ordered_existing_ids: list[str] = []
    for item in current_rows or []:
        if not isinstance(item, dict):
            continue
        depot_id = str(item.get("depot_id") or item.get("depotId") or "").strip()
        if not depot_id:
            continue
        rows_by_depot[depot_id] = dict(item)
        ordered_existing_ids.append(depot_id)

    synced_ids: list[str] = []
    missing_ids: list[str] = []
    for depot_id in selected_depot_ids:
        row = dict(rows_by_depot.get(depot_id) or _default_depot_energy_asset_row(depot_id))
        row["depot_id"] = depot_id
        if row.get("depot_area_m2") is None and row.get("depotAreaM2") is None:
            area_value = (depot_area_by_id or {}).get(depot_id)
            if area_value is not None:
                row["depot_area_m2"] = area_value
        area_m2 = row.get("depot_area_m2") if row.get("depot_area_m2") is not None else row.get("depotAreaM2")
        if positive_or_none(area_m2) is None:
            row["pv_capacity_factor_by_date"] = []
            row["pv_generation_kwh_by_slot"] = []
            row["pv_generation_kwh_by_date"] = []
            row["pv_profile_dates"] = []
            _apply_area_pv_estimate_to_row(row)
            rows_by_depot[depot_id] = row
            continue
        profile, missing_dates = _load_selected_date_pv_profile_for_depot(
            depot_id,
            service_dates,
            current_depot_area_m2=area_m2,
            profile_root=profile_root,
        )
        if profile is None:
            if missing_dates:
                missing_ids.append(f"{depot_id} ({', '.join(missing_dates)})")
            else:
                missing_ids.append(depot_id)
            continue
        row["pv_enabled"] = True
        row["pv_case_id"] = profile["profileId"]
        row["pv_profile_source"] = "derived_daily"
        row["pv_profile_dates"] = list(profile["serviceDates"])
        row["pv_slot_minutes"] = int(profile["slotMinutes"])
        row["pv_generation_kwh_by_slot"] = list(profile["pvGenerationKwhBySlot"])
        row["pv_generation_kwh_by_date"] = [
            {
                "date": str(item.get("date") or ""),
                "slot_minutes": int(item.get("slot_minutes") or 60),
                "pv_generation_kwh_by_slot": list(item.get("pv_generation_kwh_by_slot") or []),
            }
            for item in profile.get("pvGenerationKwhByDate") or []
        ]
        row["pv_capacity_factor_by_date"] = [
            {
                "date": str(item.get("date") or ""),
                "slot_minutes": int(item.get("slot_minutes") or 60),
                "capacity_factor_by_slot": list(item.get("capacity_factor_by_slot") or []),
            }
            for item in profile.get("pvCapacityFactorByDate") or []
        ]
        row["depot_area_m2"] = profile.get("depotAreaM2")
        row["estimated_installable_area_m2"] = profile.get("estimatedInstallableAreaM2")
        row["usable_area_ratio"] = DEFAULT_USABLE_AREA_RATIO
        row["panel_power_density_kw_m2"] = DEFAULT_PANEL_POWER_DENSITY_KW_M2
        row["performance_ratio"] = DEFAULT_PERFORMANCE_RATIO
        row["pv_capacity_kw"] = float(profile.get("capacityKw") or 0.0)
        rows_by_depot[depot_id] = row
        synced_ids.append(depot_id)

    ordered_ids: list[str] = []
    for depot_id in selected_depot_ids:
        if depot_id in rows_by_depot and depot_id not in ordered_ids:
            ordered_ids.append(depot_id)
    for depot_id in ordered_existing_ids:
        if depot_id in rows_by_depot and depot_id not in ordered_ids:
            ordered_ids.append(depot_id)

    return [rows_by_depot[depot_id] for depot_id in ordered_ids], synced_ids, missing_ids


class BFFClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = ""
        self.direct_mode = str(os.getenv("MC_DIRECT_CALL", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def set_direct_mode(self, enabled: bool) -> None:
        self.direct_mode = bool(enabled)

    def _try_request_direct(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.direct_mode:
            return None
        try:
            from bff.services.direct_runtime import call_direct, is_direct_supported
        except Exception:
            return None
        if not is_direct_supported(method, path):
            return None
        return call_direct(method=method, path=path, body=body)

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
        timeout_seconds: float = 45.0,
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
            with request.urlopen(req, timeout=timeout_seconds) as resp:
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
        timeout_seconds: float = 45.0,
    ) -> dict[str, Any]:
        direct_result = self._try_request_direct(method, path, body=body)
        if direct_result is not None:
            return direct_result
        try:
            return self._request_once(method, path, body=body, query=query, timeout_seconds=timeout_seconds)
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
                timeout_seconds=timeout_seconds,
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

    def get_app_datasets(self) -> dict[str, Any]:
        return self._request("GET", "/app/datasets")

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

    def list_depots(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/depots")

    def get_depot(self, scenario_id: str, depot_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/depots/{depot_id}")

    def update_depot(self, scenario_id: str, depot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/scenarios/{scenario_id}/depots/{depot_id}", payload)

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
            timeout_seconds=180.0,
        )

    def run_optimization(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/run-optimization", payload, timeout_seconds=180.0)

    def reoptimize(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/scenarios/{scenario_id}/reoptimize", payload, timeout_seconds=180.0)

    def get_simulation_capabilities(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/simulation/capabilities")

    def get_optimization_capabilities(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/optimization/capabilities")

    def get_simulation_result(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/simulation")

    def get_optimization_result(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}/optimization")

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        return self._request("GET", f"/scenarios/{scenario_id}")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("予備運用コンソール")
        self._fleet_window: tk.Toplevel | None = None
        self._fleet_built = False
        self.fleet_depot_var: tk.StringVar | None = None
        self.fleet_depot_combo: ttk.Combobox | None = None
        self.dup_target_depot_var: tk.StringVar | None = None
        self.dup_target_depot_combo: ttk.Combobox | None = None
        self.vehicle_tree: ttk.Treeview | None = None
        self.template_tree: ttk.Treeview | None = None

        self.client = BFFClient("http://127.0.0.1:8000")
        self.scenarios: list[dict[str, Any]] = []
        self.prepared_input_id = ""
        self.prepared_ready = False
        self.prepared_trip_count = 0
        self.prepared_dirty_reason = ""
        self.prepared_profile_name = ""
        self.last_job_id = ""
        self.vehicle_rows: list[dict[str, Any]] = []
        self.template_rows: list[dict[str, Any]] = []
        self.route_label_file_var = tk.StringVar(value="")
        self.scope_filter_var = tk.StringVar(value="")
        self.scope_summary_var = tk.StringVar(value="営業所・路線が未読込です")
        self.scope_selection_detail_var = tk.StringVar(value="")
        self.scope_depots: list[dict[str, Any]] = []
        self.scope_all_routes: list[dict[str, Any]] = []
        self.scope_routes: list[dict[str, Any]] = []
        self.scope_routes_by_depot: dict[str, list[str]] = {}
        self.scope_family_keys_by_depot: dict[str, list[str]] = {}
        self.scope_family_route_ids: dict[str, list[str]] = {}
        self.scope_family_label_by_key: dict[str, str] = {}
        self.scope_route_by_id: dict[str, dict[str, Any]] = {}
        self.scope_depot_by_id: dict[str, dict[str, Any]] = {}
        self.scope_day_type_summaries: list[dict[str, Any]] = []
        self.scope_day_type_label_by_id: dict[str, str] = {}
        self.scope_selected_depot_ids: set[str] = set()
        self.scope_selected_route_ids: set[str] = set()
        self.scope_depot_vars: dict[str, tk.BooleanVar] = {}
        self.scope_family_vars: dict[str, tk.BooleanVar] = {}
        self.scope_route_vars: dict[str, tk.BooleanVar] = {}
        self.scope_depot_open_vars: dict[str, tk.BooleanVar] = {}
        self.scope_family_open_vars: dict[str, tk.BooleanVar] = {}
        self.day_type_summary_tree: ttk.Treeview | None = None
        self._suspend_day_type_summary_event = False
        self.available_dataset_ids: list[str] = []
        self.day_type_options = ["WEEKDAY", "SAT", "SUN_HOL", "SAT_HOL"]
        self.weather_mode_options = list(_WEATHER_MODE_OPTIONS)
        self.default_dataset_id: str = "tokyu_full"
        self.depot_manager_window: tk.Toplevel | None = None
        self.optimization_window: tk.Toplevel | None = None
        self.optimization_console: ScrolledText | None = None
        self.optimization_progress_var = tk.DoubleVar(value=0.0)
        self.optimization_status_var = tk.StringVar(value="待機中")
        self.optimization_job_id = ""
        self.optimization_polling = False
        self.optimization_last_message = ""
        self.optimization_last_status = ""
        self.optimization_last_progress = -1.0
        self.optimization_poll_count = 0
        self.optimization_last_snapshot_json = ""
        self.wait_until_finish_var = tk.BooleanVar(value=False)
        self.rebuild_dispatch_before_opt_var = tk.BooleanVar(value=False)
        self.execution_mode_var: tk.StringVar | None = None
        self._suspend_prepare_watchers = False
        self._suspend_route_lock_sync = False
        self.compare_scenario_a_var = tk.StringVar(value="")
        self.compare_scenario_b_var = tk.StringVar(value="")
        self._busy_count: int = 0
        self._busy_var = tk.StringVar(value="")
        self._scope_filter_debounce_id: str | None = None
        self.run_transport_var = tk.StringVar(value="直結" if self.client.direct_mode else "HTTP互換")
        self.base_url_entry: ttk.Entry | None = None
        self.base_url_label: ttk.Label | None = None

        self._build_ui()
        self._refresh_service_dates_preview()
        self._register_prepare_dependency_watchers()
        self._register_scope_ui_watchers()
        self._bind_keyboard_shortcuts()

    def _build_ui(self) -> None:
        # ── レスポンシブウィンドウサイズ ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(1500, max(1000, int(sw * 0.88)))
        h = min(980, max(680, int(sh * 0.88)))
        x = (sw - w) // 2
        y = max(0, (sh - h) // 2 - 20)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(900, 600)

        # ── 上部バー：実行モード / 接続 ──
        top = ttk.Frame(self.root, padding=(8, 4))
        top.pack(fill=tk.X)
        ttk.Label(top, text="実行モード").pack(side=tk.LEFT)
        transport_combo = ttk.Combobox(
            top,
            state="readonly",
            textvariable=self.run_transport_var,
            values=["直結", "HTTP互換"],
            width=10,
        )
        transport_combo.pack(side=tk.LEFT, padx=(4, 8))
        transport_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_transport_mode_changed())

        self.base_url_label = ttk.Label(top, text="BFF URL")
        self.base_url_label.pack(side=tk.LEFT)
        self.base_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        self.base_url_entry = ttk.Entry(top, textvariable=self.base_url_var, width=30)
        self.base_url_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="接続確認", command=self.on_connect).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="使い方ヘルプ", command=self.open_help_window).pack(side=tk.LEFT, padx=(8, 2))
        tool_menu_btn = ttk.Menubutton(top, text="ツール")
        tool_menu_btn.pack(side=tk.LEFT, padx=(8, 2))
        tool_menu = tk.Menu(tool_menu_btn, tearoff=False)
        tool_menu.add_command(label="車両・テンプレート管理", command=self.open_fleet_window)
        tool_menu.add_command(label="営業所別充電器管理", command=self.open_vehicle_depot_manager)
        tool_menu.add_command(label="機能情報", command=self.show_capabilities)
        tool_menu_btn.configure(menu=tool_menu)
        ttk.Label(top, textvariable=self._busy_var, foreground="#c0392b", font=("TkDefaultFont", 9, "bold")).pack(side=tk.RIGHT, padx=8)
        self._on_transport_mode_changed()

        # ── シナリオバー ──
        scenario_frame = ttk.LabelFrame(self.root, text="シナリオ", padding=(8, 4))
        scenario_frame.pack(fill=tk.X, padx=8, pady=(0, 2))

        sc_row1 = ttk.Frame(scenario_frame)
        sc_row1.pack(fill=tk.X)
        ttk.Button(sc_row1, text="一覧更新", command=self.refresh_scenarios).pack(side=tk.LEFT, padx=(0, 4))
        self.scenario_combo = ttk.Combobox(sc_row1, state="readonly", width=54)
        self.scenario_combo.pack(side=tk.LEFT, padx=4)
        self.scenario_combo.bind("<<ComboboxSelected>>", self.on_scenario_changed)
        ttk.Button(sc_row1, text="新規作成", command=self.create_scenario).pack(side=tk.LEFT, padx=4)
        ttk.Button(sc_row1, text="複製", command=self.duplicate_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(sc_row1, text="有効化", command=self.activate_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(sc_row1, text="削除", command=self.delete_scenario).pack(side=tk.LEFT, padx=2)

        sc_row2 = ttk.Frame(scenario_frame)
        sc_row2.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(sc_row2, text="新規名").pack(side=tk.LEFT)
        self.new_name_var = tk.StringVar(value="バックアップ実行シナリオ")
        ttk.Entry(sc_row2, textvariable=self.new_name_var, width=22).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(sc_row2, text="datasetId").pack(side=tk.LEFT)
        self.dataset_id_var = tk.StringVar(value=self.default_dataset_id)
        self.dataset_combo = ttk.Combobox(sc_row2, textvariable=self.dataset_id_var, width=16)
        self.dataset_combo.pack(side=tk.LEFT, padx=4)
        ttk.Label(sc_row2, text="seed").pack(side=tk.LEFT, padx=(8, 4))
        self.random_seed_var = tk.StringVar(value="42")
        ttk.Entry(sc_row2, textvariable=self.random_seed_var, width=8).pack(side=tk.LEFT)
        ttk.Separator(sc_row2, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=12)
        ttk.Label(sc_row2, text="比較A").pack(side=tk.LEFT)
        self.compare_a_combo = ttk.Combobox(sc_row2, state="readonly", textvariable=self.compare_scenario_a_var, width=18)
        self.compare_a_combo.pack(side=tk.LEFT, padx=4)
        ttk.Label(sc_row2, text="B").pack(side=tk.LEFT)
        self.compare_b_combo = ttk.Combobox(sc_row2, state="readonly", textvariable=self.compare_scenario_b_var, width=18)
        self.compare_b_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(sc_row2, text="比較実行", command=self.open_compare_window).pack(side=tk.LEFT, padx=4)

        # ── ワークフローガイド ──
        guide = ttk.LabelFrame(self.root, text="操作ガイド（通常フロー）", padding=(8, 2))
        guide.pack(fill=tk.X, padx=8, pady=(2, 2))
        steps = [
            ("①", "シナリオ選択・作成", "#1a5276"),
            ("②", "左パネルで営業所・路線・日付を設定", "#1a5276"),
            ("③", "Quick Setup 保存 → ② ソルバー設定", "#1a5276"),
            ("④", "③ Solver対応 Prepare を実行", "#117a65"),
            ("⑤", "実行種別を選んで ④ 実行", "#117a65"),
            ("⑥", "「Optimization結果」で結果確認", "#6e2f6e"),
        ]
        guide_inner = ttk.Frame(guide)
        guide_inner.pack(fill=tk.X)
        for num, text, color in steps:
            cell = ttk.Frame(guide_inner)
            cell.pack(side=tk.LEFT, padx=(0, 14))
            ttk.Label(cell, text=num, foreground=color, font=("TkDefaultFont", 9, "bold")).pack(side=tk.LEFT)
            ttk.Label(cell, text=f" {text}", foreground=color).pack(side=tk.LEFT)

        # ── メインエリア（垂直 Paned：上=パネル群, 下=ログ）──
        vpane = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        vpane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        main_area = ttk.Frame(vpane)
        log_area = ttk.Frame(vpane)
        vpane.add(main_area, weight=5)
        vpane.add(log_area, weight=1)

        # 水平 Paned：左（スコープ）＋ 中（実行）
        main = ttk.Panedwindow(main_area, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        mid = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(mid, weight=3)

        self._build_scope_panel(left)
        self._build_run_panel(mid)

        self.log = ScrolledText(log_area)
        self.log.pack(fill=tk.BOTH, expand=True)

    def _build_scope_panel(self, parent: ttk.Frame) -> None:
        scope = ttk.LabelFrame(parent, text="対象スコープ / Quick Setup", padding=8)
        scope.pack(fill=tk.BOTH, expand=True)

        # ── Quick Setup ボタン（常時表示・最上部）──
        top = ttk.Frame(scope)
        top.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(top, text="Quick Setup 読込", command=self.load_quick_setup).pack(side=tk.LEFT)
        ttk.Button(top, text="Quick Setup 保存", command=self.save_quick_setup).pack(side=tk.LEFT, padx=6)

        # ── 運行設定（常時表示）── canvas より上に置くことで常に見える
        self.day_type_var = tk.StringVar(value="WEEKDAY")
        self.service_date_var = tk.StringVar(value="")
        self.planning_days_var = tk.StringVar(value="1")
        self.operation_start_time_var = tk.StringVar(value="05:00")
        self.operation_end_time_var = tk.StringVar(value="23:00")
        self.service_dates_preview_var = tk.StringVar(value="対象日: 未設定")
        self.route_limit_var = tk.StringVar(value="600")

        day_row = ttk.Frame(scope)
        day_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(day_row, text="運行種別", width=12).pack(side=tk.LEFT)
        self.day_type_combo = ttk.Combobox(
            day_row, textvariable=self.day_type_var, state="readonly", values=self.day_type_options, width=14,
        )
        self.day_type_combo.pack(side=tk.LEFT)
        ttk.Label(day_row, text="運行日(YYYY-MM-DD)", width=18).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(day_row, textvariable=self.service_date_var, width=12).pack(side=tk.LEFT)
        ttk.Label(day_row, text="計画日数", width=10).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(day_row, textvariable=self.planning_days_var, width=4).pack(side=tk.LEFT)
        ttk.Label(day_row, text="配車開始", width=8).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(day_row, textvariable=self.operation_start_time_var, width=6).pack(side=tk.LEFT)
        ttk.Label(day_row, text="配車終了", width=8).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Entry(day_row, textvariable=self.operation_end_time_var, width=6).pack(side=tk.LEFT)
        ttk.Label(day_row, textvariable=self.service_dates_preview_var, foreground="#444").pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        day_table = ttk.LabelFrame(scope, text="運行種別サマリ", padding=(4, 2))
        day_table.pack(fill=tk.X, pady=(2, 4))
        ttk.Label(
            day_table,
            text="この表は便数内訳を切り替えるためのものです。下の営業所・路線一覧の表示母集団は変えません。",
            foreground="#444",
        ).pack(anchor="w")
        day_tree_wrap = ttk.Frame(day_table)
        day_tree_wrap.pack(fill=tk.X, pady=(2, 0))
        self.day_type_summary_tree = ttk.Treeview(
            day_tree_wrap,
            columns=("serviceId", "label", "familyCount", "routeCount", "tripCount", "variantMix"),
            show="headings",
            height=4,
        )
        self.day_type_summary_tree.heading("serviceId", text="service")
        self.day_type_summary_tree.heading("label", text="種別")
        self.day_type_summary_tree.heading("familyCount", text="系統family")
        self.day_type_summary_tree.heading("routeCount", text="variant")
        self.day_type_summary_tree.heading("tripCount", text="trip数")
        self.day_type_summary_tree.heading("variantMix", text="運行種別内訳")
        self.day_type_summary_tree.column("serviceId", width=100, anchor="w")
        self.day_type_summary_tree.column("label", width=120, anchor="w")
        self.day_type_summary_tree.column("familyCount", width=80, anchor="e")
        self.day_type_summary_tree.column("routeCount", width=80, anchor="e")
        self.day_type_summary_tree.column("tripCount", width=90, anchor="e")
        self.day_type_summary_tree.column("variantMix", width=260, anchor="w")
        self.day_type_summary_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        day_tree_ysb = ttk.Scrollbar(day_tree_wrap, orient=tk.VERTICAL, command=self.day_type_summary_tree.yview)
        day_tree_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.day_type_summary_tree.configure(yscrollcommand=day_tree_ysb.set)
        self.day_type_summary_tree.bind("<<TreeviewSelect>>", self._on_day_type_summary_selected)

        # ── 接続フラグ（常時表示・コンパクト 2行）──
        flags_lf = ttk.LabelFrame(scope, text="接続設定", padding=(4, 2))
        flags_lf.pack(fill=tk.X, pady=(2, 4))
        self.include_short_turn_var = tk.BooleanVar(value=True)
        self.include_depot_moves_var = tk.BooleanVar(value=True)
        self.include_deadhead_var = tk.BooleanVar(value=True)
        self.allow_intra_var = tk.BooleanVar(value=False)
        self.allow_inter_var = tk.BooleanVar(value=False)
        self.fixed_route_band_mode_var = tk.BooleanVar(value=True)
        frow1 = ttk.Frame(flags_lf)
        frow1.pack(fill=tk.X)
        ttk.Checkbutton(frow1, text="区間便", variable=self.include_short_turn_var).pack(side=tk.LEFT)
        ttk.Checkbutton(frow1, text="入出庫便", variable=self.include_depot_moves_var).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(frow1, text="回送", variable=self.include_deadhead_var).pack(side=tk.LEFT)
        frow2 = ttk.Frame(flags_lf)
        frow2.pack(fill=tk.X)
        ttk.Checkbutton(frow2, text="営業所間トレード許可", variable=self.allow_inter_var).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(
            frow2,
            text="日次路線固定（車両固定バンド）",
            variable=self.fixed_route_band_mode_var,
        ).pack(side=tk.LEFT, padx=8)
        ttk.Label(
            frow2,
            text="ON の間は営業所内の路線トレードを止め、ダイヤグラム出力も自動で有効化します。",
            foreground="#555",
        ).pack(side=tk.LEFT, padx=(8, 0))

        # ── 営業所・路線チェックリスト（スクロール・残りスペースを全て使用）──
        scope_hdr = ttk.Frame(scope)
        scope_hdr.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(scope_hdr, text="営業所・路線選択").pack(side=tk.LEFT)
        ttk.Button(scope_hdr, text="全ON", command=lambda: self._set_all_depots_checked(True)).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(scope_hdr, text="全OFF", command=lambda: self._set_all_depots_checked(False)).pack(side=tk.LEFT, padx=2)
        ttk.Button(scope_hdr, text="全展開", command=lambda: self._set_all_depots_open(True)).pack(side=tk.LEFT, padx=(6, 2))
        ttk.Button(scope_hdr, text="折りたたむ", command=lambda: self._set_all_depots_open(False)).pack(side=tk.LEFT, padx=2)
        ttk.Label(scope_hdr, text="検索").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Entry(scope_hdr, textvariable=self.scope_filter_var, width=22).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(scope_hdr, text="クリア", command=lambda: self.scope_filter_var.set("")).pack(side=tk.LEFT, padx=(4, 0))
        scope_summary = ttk.Frame(scope)
        scope_summary.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(scope_summary, textvariable=self.scope_summary_var, foreground="#22313f").pack(anchor="w")
        ttk.Label(scope_summary, textvariable=self.scope_selection_detail_var, foreground="#555").pack(anchor="w")
        _scope_canvas_wrap = ttk.Frame(scope)
        _scope_canvas_wrap.pack(fill=tk.BOTH, expand=True)
        self.scope_canvas = tk.Canvas(_scope_canvas_wrap, highlightthickness=0, bg="#f8f8f8")
        scope_ysb = ttk.Scrollbar(_scope_canvas_wrap, orient=tk.VERTICAL, command=self.scope_canvas.yview)
        scope_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.scope_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scope_canvas.configure(yscrollcommand=scope_ysb.set)
        self.scope_inner = ttk.Frame(self.scope_canvas)
        self.scope_inner_window = self.scope_canvas.create_window((0, 0), window=self.scope_inner, anchor="nw")
        self.scope_inner.bind("<Configure>", lambda _e: self.scope_canvas.configure(scrollregion=self.scope_canvas.bbox("all")))
        self.scope_canvas.bind("<Configure>", lambda e: self.scope_canvas.itemconfigure(self.scope_inner_window, width=e.width))
        self.scope_canvas.bind("<MouseWheel>", lambda e: self.scope_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.scope_inner.bind("<MouseWheel>", lambda e: self.scope_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── ラベルファイル操作（最下部・補助機能）──
        label_ops = ttk.Frame(scope)
        label_ops.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(label_ops, text="ラベルファイル", command=self.pick_route_label_file).pack(side=tk.LEFT)
        ttk.Button(label_ops, text="シナリオへ反映", command=self.apply_route_labels_to_scenario).pack(side=tk.LEFT, padx=4)
        ttk.Entry(label_ops, textvariable=self.route_label_file_var, width=16).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_run_panel(self, parent: ttk.Frame) -> None:
        ops = ttk.LabelFrame(parent, text="実行パラメータ / 実行", padding=8)
        ops.pack(fill=tk.BOTH, expand=True)

        # ── アクションバー（スクロール外・常時表示）──
        # 推奨フロー: シナリオ保存 → ソルバー設定 → Prepare → 実行
        action_bar = ttk.Frame(ops, relief="flat")
        action_bar.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            action_bar,
            text="① シナリオ保存  →  ② ソルバー設定  →  ③ Solver対応 Prepare  →  ④ 実行",
            foreground="#1a5276",
            font=("TkDefaultFont", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(action_bar)
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row, text="① シナリオ保存", command=self.save_quick_setup,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="② ソルバー設定", command=self.open_solver_settings_window).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="③ Solver対応 Prepare", command=self.prepare).pack(side=tk.LEFT, padx=4)
        self.execution_mode_var = tk.StringVar(value="最適化計算")
        ttk.Label(btn_row, text="④ 実行種別").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Combobox(
            btn_row,
            state="readonly",
            textvariable=self.execution_mode_var,
            values=["最適化計算", "Preparedシミュレーション", "再最適化"],
            width=20,
        ).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="④ 実行", command=self.run_selected_execution).pack(side=tk.LEFT, padx=4)

        self.prepared_var = tk.StringVar(value="prepared_input_id: -")
        self.job_var = tk.StringVar(value="job: -")
        status_row = ttk.Frame(action_bar)
        status_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(status_row, textvariable=self.prepared_var, foreground="#555").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.job_var, foreground="#555").pack(side=tk.LEFT, padx=12)
        self._update_prepared_status_label()

        result_row = ttk.Frame(action_bar)
        result_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(result_row, text="Optimization結果", command=self.show_optimization_result).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(result_row, text="Simulation結果", command=self.show_simulation_result).pack(side=tk.LEFT, padx=4)
        ttk.Button(result_row, text="ダイヤグラム表示", command=self.show_vehicle_diagram).pack(side=tk.LEFT, padx=4)

        ttk.Separator(ops, orient="horizontal").pack(fill=tk.X, pady=4)

        # ── パラメータエリア（スクロール可能）──
        _run_canvas = tk.Canvas(ops, highlightthickness=0)
        _run_ysb = ttk.Scrollbar(ops, orient=tk.VERTICAL, command=_run_canvas.yview)
        _run_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        _run_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _run_canvas.configure(yscrollcommand=_run_ysb.set)
        _run_inner = ttk.Frame(_run_canvas)
        _run_inner_win = _run_canvas.create_window((0, 0), window=_run_inner, anchor="nw")
        _run_inner.bind("<Configure>", lambda _: _run_canvas.configure(scrollregion=_run_canvas.bbox("all")))
        _run_canvas.bind("<Configure>", lambda e: _run_canvas.itemconfigure(_run_inner_win, width=e.width))
        _run_canvas.bind("<MouseWheel>", lambda e: _run_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        _run_inner.bind("<MouseWheel>", lambda e: _run_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # 以降のウィジェットは _run_inner に配置する
        ops = _run_inner  # noqa: F841

        self.initial_soc_var = tk.StringVar(value="0.8")
        self.soc_min_var = tk.StringVar(value="0.2")
        self.soc_max_var = tk.StringVar(value="0.9")
        self.cost_component_vars = {
            key: tk.BooleanVar(value=value)
            for key, value in default_cost_component_flags().items()
        }
        # ── パラメータ変数の初期化 ──
        self.grid_flat_price_var = tk.StringVar(value="30")
        self.diesel_price_var = tk.StringVar(value="145")
        self.demand_charge_var = tk.StringVar(value="1500")
        self.depot_power_limit_var = tk.StringVar(value="500")
        self.deadhead_speed_kmh_var = tk.StringVar(value="18")
        self.tou_text_var = tk.StringVar(value="0-12:15,12-20:40,20-48:20")
        self.grid_sell_price_var = tk.StringVar(value="0")
        self.grid_co2_var = tk.StringVar(value="0")
        self.co2_price_var = tk.StringVar(value="0")
        self.ice_co2_kg_per_l_var = tk.StringVar(value="2.64")
        self.degradation_weight_var = tk.StringVar(value="0")
        self.contract_penalty_coeff_var = tk.StringVar(value="1000000")
        self.unserved_penalty_var = tk.StringVar(value="10000")
        self.objective_weights_json_var = tk.StringVar(value="")
        self.objective_preset_var = tk.StringVar(value="cost")
        self.max_start_fragments_var = tk.StringVar(value="100")
        self.max_end_fragments_var = tk.StringVar(value="100")
        self.initial_soc_percent_var = tk.StringVar(value="0.8")
        self.final_soc_floor_percent_var = tk.StringVar(value="0.2")
        self.final_soc_target_percent_var = tk.StringVar(value="0.8")
        self.final_soc_target_tolerance_percent_var = tk.StringVar(value="0.0")
        self.initial_ice_fuel_percent_var = tk.StringVar(value="100.0")
        self.min_ice_fuel_percent_var = tk.StringVar(value="10.0")
        self.max_ice_fuel_percent_var = tk.StringVar(value="90.0")
        self.default_ice_tank_capacity_l_var = tk.StringVar(value="300.0")
        self.pv_profile_id_var = tk.StringVar(value="")
        self.weather_mode_var = tk.StringVar(value=_ACTUAL_DATE_PV_PROFILE_ID)
        self.weather_factor_scalar_var = tk.StringVar(value="1.0")
        self.depot_energy_assets_json_var = tk.StringVar(value="")
        self.co2_price_source_var = tk.StringVar(value="manual")
        self.co2_reference_date_var = tk.StringVar(value="")
        self.enable_vehicle_diagram_output_var = tk.BooleanVar(value=True)

        # ════════════════════════════════
        # 基本パラメータ
        # ════════════════════════════════
        basic = ttk.LabelFrame(ops, text="基本パラメータ", padding=6)
        basic.pack(fill=tk.X, pady=(0, 4))

        # ── エネルギー単価 ──
        energy_grp = ttk.LabelFrame(basic, text="エネルギー単価", padding=4)
        energy_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            energy_grp,
            "燃料単価 [円/L]", self.diesel_price_var,
            tip0="軽油の単価 [円/L]。ICE バスの燃料費（O1）計算に使用。例: 145",
            label1="電気代単価 [円/kWh]", var1=self.grid_flat_price_var,
            tip1="系統電力の平均単価 [円/kWh]。TOU帯が未設定のときフォールバック。例: 30",
        )
        self._param_row2(
            energy_grp,
            "需要単価 [円/kW/月]", self.demand_charge_var,
            tip0=(
                "ピーク需要電力 1kW あたりの月額基本料金 [円/kW/月]。\n"
                "充電タイミングを分散させるインセンティブとして機能。例: 1500"
            ),
            label1="契約上限 [kW]", var1=self.depot_power_limit_var,
            tip1=(
                "営業所の系統受電契約電力上限 [kW]。\n"
                "この値を超えると制約違反になる。例: 500"
            ),
        )
        self._param_row2(
            energy_grp,
            "売電単価 [円/kWh]", self.grid_sell_price_var,
            tip0="PV 余剰電力の売電単価 [円/kWh]。現行実装では参考値。例: 0",
            label1="回送速度 [km/h]", var1=self.deadhead_speed_kmh_var,
            tip1=(
                "営業所↔停留所間の回送推定速度 [km/h]。\n"
                "便連結の接続可否判定（到着+折返+回送 ≤ 出発）に使用。例: 18"
            ),
        )
        self._labeled_entry(
            energy_grp, "TOU帯", self.tou_text_var,
            tooltip=(
                "時間帯別電力単価（Time-of-Use）の設定。\n"
                "形式: 開始スロット-終了スロット:単価[円/kWh], ...\n"
                "スロット番号は 30 分刻みで 0〜48（0=0:00, 24=12:00, 48=24:00）。\n"
                "例: 0-12:15,12-20:40,20-48:20\n"
                "  → 0:00〜6:00 は 15円, 6:00〜10:00 は 40円, 10:00〜24:00 は 20円"
            ),
        )

        # ── 充電・SOC ──
        soc_grp = ttk.LabelFrame(basic, text="充電・SOC", padding=4)
        soc_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            soc_grp,
            "初期SOC", self.initial_soc_var,
            tip0="運行開始時の電池残量比率（0〜1）。1.0 = 満充電。例: 0.8",
            label1="SOC下限 (バッファ)", var1=self.soc_min_var,
            tip1="走行中に下回れない SOC 下限（0〜1）。小さいほど柔軟だが電欠リスクが上がる。例: 0.2",
        )
        self._param_row2(
            soc_grp,
            "SOC上限 (過充電防止)", self.soc_max_var,
            tip0="充電を停止する SOC 上限（0〜1）。過充電防止。例: 0.9",
        )

        # ── 目的関数コスト項目 ──
        cost_toggle_frame = ttk.LabelFrame(basic, text="目的関数に含めるコスト項目", padding=6)
        cost_toggle_frame.pack(fill=tk.X, pady=(0, 0))
        ttk.Label(cost_toggle_frame, text="項目").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(cost_toggle_frame, text="目的関数に含める").grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(cost_toggle_frame, text="内容").grid(row=0, column=2, sticky="w")
        row_idx = 1
        for section, definitions in _group_cost_components_for_ui():
            ttk.Label(
                cost_toggle_frame,
                text=section,
                foreground="#1a5276",
                font=("TkDefaultFont", 9, "bold"),
            ).grid(row=row_idx, column=0, sticky="w", pady=(6 if row_idx > 1 else 4, 2))
            row_idx += 1
            for definition in definitions:
                ttk.Label(cost_toggle_frame, text=definition.label).grid(
                    row=row_idx, column=0, sticky="w", padx=(0, 8), pady=2,
                )
                ttk.Checkbutton(
                    cost_toggle_frame,
                    variable=self.cost_component_vars[definition.key],
                ).grid(row=row_idx, column=1, sticky="w", padx=(0, 8), pady=2)
                description = definition.description
                if definition.solver_scope == "milp_only":
                    description = "MILPのみ: " + description
                ttk.Label(
                    cost_toggle_frame,
                    text=description,
                    foreground="#555",
                ).grid(row=row_idx, column=2, sticky="w", pady=2)
                row_idx += 1
        cost_toggle_frame.columnconfigure(2, weight=1)

        # ════════════════════════════════
        # 詳細パラメータ
        # ════════════════════════════════
        advanced = ttk.LabelFrame(ops, text="詳細パラメータ", padding=6)
        advanced.pack(fill=tk.X, pady=(0, 4))

        # ── ペナルティ ──
        penalty_grp = ttk.LabelFrame(advanced, text="ペナルティ", padding=4)
        penalty_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            penalty_grp,
            "未配車罰金 [円/便]", self.unserved_penalty_var,
            tip0=(
                "便が未配車になった場合のペナルティ [円/便]。\n"
                "大きいほど欠便を嫌う。通常は 100,000 以上推奨。"
            ),
            label1="契約超過係数", var1=self.contract_penalty_coeff_var,
            tip1="系統受電が契約上限を超えた際の罰則係数。大きいほど厳しく守る。例: 1000000",
        )

        # ── CO₂・環境 ──
        co2_grp = ttk.LabelFrame(advanced, text="CO₂・環境", padding=4)
        co2_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            co2_grp,
            "CO2原単位 [kg/kWh]", self.grid_co2_var,
            tip0="系統電力の CO₂排出係数 [kg/kWh]。co2 モードの排出量計算に使用。例: 0.5",
            label1="CO2単価 [円/kg]", var1=self.co2_price_var,
            tip1=(
                "CO₂排出 1kg あたりのコスト [円/kg]（total_cost モード用）。\n"
                "0 = CO₂費は目的関数に加算しない。"
            ),
        )
        self._param_row2(
            co2_grp,
            "CO2価格ソース", self.co2_price_source_var,
            tip0="CO₂価格の参照元。manual = 手動入力、jets = JETS 市場価格（参照日要設定）",
            label1="CO2参照日 (JETS)", var1=self.co2_reference_date_var,
            tip1="co2_price_source=jets の場合の参照日（YYYY-MM-DD）。manual の場合は不要。",
        )
        self._param_row2(
            co2_grp,
            "軽油CO2係数 [kg/L]", self.ice_co2_kg_per_l_var,
            tip0="軽油 1L 燃焼時の CO₂排出量 [kg/L]。デフォルト 2.64（環境省係数）。",
            label1="劣化重み", var1=self.degradation_weight_var,
            tip1=(
                "電池劣化コストの重み係数。\n"
                "充電量/容量 × 50円/cycle × この重みが目的関数に加算される。\n"
                "0 = 劣化費用を含まない。"
            ),
        )

        # ── ICE燃料 ──
        ice_grp = ttk.LabelFrame(advanced, text="ICE燃料", padding=4)
        ice_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            ice_grp,
            "初期燃料比", self.initial_ice_fuel_percent_var,
            label1="最低燃料バッファ", var1=self.min_ice_fuel_percent_var,
        )
        self._param_row2(
            ice_grp,
            "燃料上限バッファ", self.max_ice_fuel_percent_var,
            label1="タンク容量 [L]", var1=self.default_ice_tank_capacity_l_var,
        )

        # ── SOC詳細 ──
        soc_detail_grp = ttk.LabelFrame(advanced, text="SOC詳細", padding=4)
        soc_detail_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            soc_detail_grp,
            "初期SOC比", self.initial_soc_percent_var,
            label1="終了SOC目標", var1=self.final_soc_target_percent_var,
        )
        self._param_row2(
            soc_detail_grp,
            "終了SOC床", self.final_soc_floor_percent_var,
            label1="目標許容±", var1=self.final_soc_target_tolerance_percent_var,
        )

        # ── PV・天候 ──
        pv_grp = ttk.LabelFrame(advanced, text="PV・天候", padding=4)
        pv_grp.pack(fill=tk.X, pady=(0, 4))
        self._param_row2(
            pv_grp,
            "PVプロファイルID", self.pv_profile_id_var,
            label1="天気係数", var1=self.weather_factor_scalar_var,
        )
        weather_row = ttk.Frame(pv_grp)
        weather_row.pack(fill=tk.X, pady=1)
        weather_label = ttk.Label(weather_row, text="天気モード", width=18)
        weather_label.pack(side=tk.LEFT)
        _Tooltip(
            weather_label,
            "actual_date_profile は運行日と計画日数で選ばれた実日のPVを使います。sunny/cloudy/rainy は手動係数に寄せたい場合の補助です。",
        )
        self.weather_mode_combo = ttk.Combobox(
            weather_row,
            textvariable=self.weather_mode_var,
            state="readonly",
            values=self.weather_mode_options,
        )
        self.weather_mode_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        asset_row = self._labeled_entry(
            pv_grp,
            "営業所エネルギー資産(JSON)",
            self.depot_energy_assets_json_var,
            tooltip=(
                "営業所別のPV/BESS設定をJSON配列で入力します。\n"
                "例: [{\"depot_id\":\"dep-1\",\"bess_enabled\":true,\"bess_energy_kwh\":500}]\n"
                "空欄の場合は既存設定を保持します。"
            ),
        )
        ttk.Button(asset_row, text="行編集...", command=self.open_depot_energy_assets_editor).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            asset_row,
            text="選択営業所へ実日PV同期",
            command=self.sync_selected_depot_pv_assets,
        ).pack(side=tk.LEFT, padx=(6, 0))

        # ── 最適化・その他 ──
        optim_grp = ttk.LabelFrame(advanced, text="最適化・その他", padding=4)
        optim_grp.pack(fill=tk.X, pady=(0, 0))
        self._param_row2(
            optim_grp,
            "目的プリセット", self.objective_preset_var,
            tip0="重みプリセット。cost / co2 / balanced / utilization から選択。ソルバー設定の objectiveMode と合わせること。",
            label1="開始断片上限", var1=self.max_start_fragments_var,
            tip1=(
                "各車両が 1 日に出庫できる最大回数（C3 制約）。\n"
                "通常は 1。増やすと分割シフト（午前・午後）を許容する。"
            ),
        )
        self._param_row2(
            optim_grp,
            "終了断片上限", self.max_end_fragments_var,
            tip0="各車両が 1 日に入庫できる最大回数。通常は開始断片上限と同じ値にする。",
        )
        self._labeled_entry(optim_grp, "拡張係数(JSON)", self.objective_weights_json_var)
        ttk.Checkbutton(optim_grp, text="車両ダイヤグラム出力", variable=self.enable_vehicle_diagram_output_var).pack(anchor="w", pady=(2, 0))
        self._labeled_entry(optim_grp, "車両導入費(編集は車両/テンプレ画面)", tk.StringVar(value="個別設定"), readonly=True)

        # ── ソルバー詳細設定 ──
        self.solver_mode_var = tk.StringVar(value="mode_hybrid")  # Default to canonical hybrid mode
        self.objective_mode_var = tk.StringVar(value="total_cost")
        self.time_limit_var = tk.StringVar(value="300")
        self.mip_gap_var = tk.StringVar(value="0.01")
        self.alns_iter_var = tk.StringVar(value="500")
        self.no_improvement_limit_var = tk.StringVar(value="100")
        self.destroy_fraction_var = tk.StringVar(value="0.25")
        self.allow_partial_service_var = tk.BooleanVar(value=False)

        settings_box = ttk.LabelFrame(ops, text="ソルバー詳細設定", padding=6)
        settings_box.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(settings_box, text="手順②でソルバー種別・時間上限・反復回数を先に確定してください。", foreground="#444").pack(anchor="w")
        ttk.Button(settings_box, text="② ソルバー設定を開く", command=self.open_solver_settings_window).pack(anchor="w", pady=(4, 0))

        # ── ジョブ監視 ──
        job_row = ttk.Frame(ops)
        job_row.pack(fill=tk.X, pady=4)
        ttk.Label(job_row, text="詳細操作", foreground="#555").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(job_row, text="手動 job_id", width=20).pack(side=tk.LEFT)
        self.manual_job_id_var = tk.StringVar(value="")
        ttk.Entry(job_row, textvariable=self.manual_job_id_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(job_row, text="ジョブ監視", command=self.poll_last_job).pack(side=tk.LEFT, padx=4)

        # Scenario Compare はシナリオバーの「比較実行」ボタンから行います

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
        self.fleet_depot_combo = ttk.Combobox(top, textvariable=self.fleet_depot_var, state="readonly", width=20)
        self.fleet_depot_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="車両一覧更新", command=self.refresh_vehicles).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="車両を追加...", command=self.open_vehicle_create_window).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Button(top, text="テンプレートから営業所へ追加...", command=self.open_template_apply_window).pack(side=tk.LEFT, padx=4)

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
        heading_map = {
            "id": "車両ID",
            "depotId": "営業所",
            "type": "車種",
            "modelName": "車両名",
            "acquisitionCost": "導入費(円)",
            "energyConsumption": "電費/燃費係数",
            "chargePowerKw": "充電出力(kW)",
            "enabled": "有効",
        }
        for c in cols:
            self.vehicle_tree.heading(c, text=heading_map.get(c, c))
            self.vehicle_tree.column(c, width=120, anchor="w")
        self.vehicle_tree.column("modelName", width=180, anchor="w")
        self.vehicle_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.vehicle_tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.vehicle_tree.configure(yscrollcommand=ysb.set)
        self.vehicle_tree.bind("<<TreeviewSelect>>", self.on_vehicle_select)

        # ── Scrollable form area ──
        _vform_wrap = ttk.Frame(tab)
        _vform_wrap.pack(fill=tk.BOTH, expand=False)
        _vform_canvas = tk.Canvas(_vform_wrap, highlightthickness=0, height=300)
        _vform_ysb = ttk.Scrollbar(_vform_wrap, orient=tk.VERTICAL, command=_vform_canvas.yview)
        _vform_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        _vform_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _vform_canvas.configure(yscrollcommand=_vform_ysb.set)
        _vform_inner = ttk.Frame(_vform_canvas)
        _vform_win = _vform_canvas.create_window((0, 0), window=_vform_inner, anchor="nw")
        _vform_inner.bind(
            "<Configure>",
            lambda _: _vform_canvas.configure(scrollregion=_vform_canvas.bbox("all")),
        )
        _vform_canvas.bind(
            "<Configure>",
            lambda e: _vform_canvas.itemconfig(_vform_win, width=e.width),
        )
        _vform_canvas.bind(
            "<MouseWheel>",
            lambda e: _vform_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )
        _vform_inner.bind(
            "<MouseWheel>",
            lambda e: _vform_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        form = ttk.LabelFrame(_vform_inner, text="車両編集", padding=6)
        form.pack(fill=tk.X, expand=True)

        self.v_id_var = tk.StringVar(value="")
        self.v_depot_var = tk.StringVar(value="")
        self.v_type_var = tk.StringVar(value="BEV")
        self.v_model_code_var = tk.StringVar(value="")
        self.v_model_var = tk.StringVar(value="")
        self.v_cap_var = tk.StringVar(value="0")
        self.v_battery_var = tk.StringVar(value="300")
        self.v_fuel_tank_var = tk.StringVar(value="")
        self.v_energy_var = tk.StringVar(value="1.2")
        self.v_km_per_l_var = tk.StringVar(value="")
        self.v_co2_gpkm_var = tk.StringVar(value="")
        self.v_curb_weight_var = tk.StringVar(value="")
        self.v_gross_weight_var = tk.StringVar(value="")
        self.v_engine_disp_var = tk.StringVar(value="")
        self.v_max_torque_var = tk.StringVar(value="")
        self.v_max_power_var = tk.StringVar(value="")
        self.v_charge_kw_var = tk.StringVar(value="90")
        self.v_min_soc_var = tk.StringVar(value="")
        self.v_max_soc_var = tk.StringVar(value="")
        self.v_acq_cost_var = tk.StringVar(value="0")
        self.v_enabled_var = tk.BooleanVar(value=True)

        self._labeled_entry(form, "車両ID", self.v_id_var, readonly=True)
        self._labeled_entry(form, "営業所ID", self.v_depot_var)

        type_row = ttk.Frame(form)
        type_row.pack(fill=tk.X, pady=2)
        ttk.Label(type_row, text="車種", width=36).pack(side=tk.LEFT)
        self.vehicle_type_combo = ttk.Combobox(type_row, textvariable=self.v_type_var, state="readonly", values=["BEV", "ICE"])
        self.vehicle_type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._labeled_entry(form, "モデルコード", self.v_model_code_var)
        self._labeled_entry(form, "車両名", self.v_model_var)
        self._labeled_entry(form, "定員(人)", self.v_cap_var)
        self._labeled_entry(form, "消費係数", self.v_energy_var)
        self._labeled_entry(form, "車重(kg)", self.v_curb_weight_var)
        self._labeled_entry(form, "総重量(kg)", self.v_gross_weight_var)
        self._labeled_entry(form, "導入費(円)", self.v_acq_cost_var)

        self.vehicle_ev_box = ttk.LabelFrame(form, text="EV専用パラメータ", padding=4)
        self.vehicle_ev_box.pack(fill=tk.X, pady=(4, 2))
        self._labeled_entry(self.vehicle_ev_box, "電池容量(kWh)", self.v_battery_var)
        self._labeled_entry(self.vehicle_ev_box, "充電出力(kW)", self.v_charge_kw_var)
        self._labeled_entry(self.vehicle_ev_box, "最小SOC(0-1)", self.v_min_soc_var)
        self._labeled_entry(self.vehicle_ev_box, "最大SOC(0-1)", self.v_max_soc_var)

        self.vehicle_ice_box = ttk.LabelFrame(form, text="エンジン車専用パラメータ", padding=4)
        self.vehicle_ice_box.pack(fill=tk.X, pady=(2, 2))
        self._labeled_entry(self.vehicle_ice_box, "燃料タンク(L)", self.v_fuel_tank_var)
        self._labeled_entry(self.vehicle_ice_box, "燃費(km/L)", self.v_km_per_l_var)
        self._labeled_entry(self.vehicle_ice_box, "CO2排出(g/km)", self.v_co2_gpkm_var)
        self._labeled_entry(self.vehicle_ice_box, "排気量(L)", self.v_engine_disp_var)
        self._labeled_entry(self.vehicle_ice_box, "最大トルク(Nm)", self.v_max_torque_var)
        self._labeled_entry(self.vehicle_ice_box, "最大出力(kW)", self.v_max_power_var)

        ttk.Checkbutton(form, text="有効", variable=self.v_enabled_var).pack(anchor="w")

        action = ttk.Frame(form)
        action.pack(fill=tk.X, pady=4)
        ttk.Button(action, text="更新", command=self.update_vehicle_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="削除", command=self.delete_selected_vehicle).pack(side=tk.LEFT, padx=3)

        self.dup_count_var = tk.StringVar(value="1")
        self.dup_target_depot_var = tk.StringVar(value="")
        ttk.Label(action, text="複製数").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Entry(action, textvariable=self.dup_count_var, width=5).pack(side=tk.LEFT)
        ttk.Label(action, text="複製先営業所").pack(side=tk.LEFT, padx=(8, 2))
        self.dup_target_depot_combo = ttk.Combobox(
            action,
            textvariable=self.dup_target_depot_var,
            state="readonly",
            width=14,
        )
        self.dup_target_depot_combo.pack(side=tk.LEFT)
        ttk.Button(action, text="複製", command=self.duplicate_selected_vehicle).pack(side=tk.LEFT, padx=3)
        self.apply_template_id_var = tk.StringVar(value="")
        self.apply_template_qty_var = tk.StringVar(value="1")

        self.vehicle_type_combo.bind("<<ComboboxSelected>>", self._update_vehicle_form_visibility)
        self._update_vehicle_form_visibility()
        self._bind_canvas_mousewheel(_vform_canvas, _vform_inner)

    def _build_template_tab(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill=tk.X)
        ttk.Button(top, text="テンプレート一覧更新", command=self.refresh_templates).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="テンプレートを追加...", command=self.open_template_create_window).pack(side=tk.LEFT, padx=4)

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
        heading_map = {
            "id": "テンプレートID",
            "name": "名称",
            "type": "車種",
            "modelName": "車両名",
            "acquisitionCost": "導入費(円)",
            "energyConsumption": "消費係数",
            "chargePowerKw": "充電出力(kW)",
        }
        for c in cols:
            self.template_tree.heading(c, text=heading_map.get(c, c))
            self.template_tree.column(c, width=130, anchor="w")
        self.template_tree.column("name", width=180)
        self.template_tree.pack(fill=tk.BOTH, expand=True, pady=6)
        self.template_tree.bind("<<TreeviewSelect>>", self.on_template_select)

        # ── Scrollable form area ──
        _tform_wrap = ttk.Frame(tab)
        _tform_wrap.pack(fill=tk.BOTH, expand=False)
        _tform_canvas = tk.Canvas(_tform_wrap, highlightthickness=0, height=300)
        _tform_ysb = ttk.Scrollbar(_tform_wrap, orient=tk.VERTICAL, command=_tform_canvas.yview)
        _tform_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        _tform_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _tform_canvas.configure(yscrollcommand=_tform_ysb.set)
        _tform_inner = ttk.Frame(_tform_canvas)
        _tform_win = _tform_canvas.create_window((0, 0), window=_tform_inner, anchor="nw")
        _tform_inner.bind(
            "<Configure>",
            lambda _: _tform_canvas.configure(scrollregion=_tform_canvas.bbox("all")),
        )
        _tform_canvas.bind(
            "<Configure>",
            lambda e: _tform_canvas.itemconfig(_tform_win, width=e.width),
        )
        _tform_canvas.bind(
            "<MouseWheel>",
            lambda e: _tform_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )
        _tform_inner.bind(
            "<MouseWheel>",
            lambda e: _tform_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        form = ttk.LabelFrame(_tform_inner, text="テンプレート編集", padding=6)
        form.pack(fill=tk.X, expand=True)

        self.t_id_var = tk.StringVar(value="")
        self.t_name_var = tk.StringVar(value="")
        self.t_type_var = tk.StringVar(value="BEV")
        self.t_model_code_var = tk.StringVar(value="")
        self.t_model_var = tk.StringVar(value="")
        self.t_cap_var = tk.StringVar(value="0")
        self.t_battery_var = tk.StringVar(value="300")
        self.t_fuel_tank_var = tk.StringVar(value="")
        self.t_energy_var = tk.StringVar(value="1.2")
        self.t_km_per_l_var = tk.StringVar(value="")
        self.t_co2_gpkm_var = tk.StringVar(value="")
        self.t_curb_weight_var = tk.StringVar(value="")
        self.t_gross_weight_var = tk.StringVar(value="")
        self.t_engine_disp_var = tk.StringVar(value="")
        self.t_max_torque_var = tk.StringVar(value="")
        self.t_max_power_var = tk.StringVar(value="")
        self.t_charge_var = tk.StringVar(value="90")
        self.t_min_soc_var = tk.StringVar(value="")
        self.t_max_soc_var = tk.StringVar(value="")
        self.t_acq_cost_var = tk.StringVar(value="0")
        self.t_enabled_var = tk.BooleanVar(value=True)

        self._labeled_entry(form, "テンプレートID", self.t_id_var, readonly=True)
        self._labeled_entry(form, "名称", self.t_name_var)

        t_type_row = ttk.Frame(form)
        t_type_row.pack(fill=tk.X, pady=2)
        ttk.Label(t_type_row, text="車種", width=36).pack(side=tk.LEFT)
        self.template_type_combo = ttk.Combobox(t_type_row, textvariable=self.t_type_var, state="readonly", values=["BEV", "ICE"])
        self.template_type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._labeled_entry(form, "モデルコード", self.t_model_code_var)
        self._labeled_entry(form, "車両名", self.t_model_var)
        self._labeled_entry(form, "定員(人)", self.t_cap_var)
        self._labeled_entry(form, "消費係数", self.t_energy_var)
        self._labeled_entry(form, "車重(kg)", self.t_curb_weight_var)
        self._labeled_entry(form, "総重量(kg)", self.t_gross_weight_var)
        self._labeled_entry(form, "導入費(円)", self.t_acq_cost_var)

        self.template_ev_box = ttk.LabelFrame(form, text="EV専用パラメータ", padding=4)
        self.template_ev_box.pack(fill=tk.X, pady=(4, 2))
        self._labeled_entry(self.template_ev_box, "電池容量(kWh)", self.t_battery_var)
        self._labeled_entry(self.template_ev_box, "充電出力(kW)", self.t_charge_var)
        self._labeled_entry(self.template_ev_box, "最小SOC(0-1)", self.t_min_soc_var)
        self._labeled_entry(self.template_ev_box, "最大SOC(0-1)", self.t_max_soc_var)

        self.template_ice_box = ttk.LabelFrame(form, text="エンジン車専用パラメータ", padding=4)
        self.template_ice_box.pack(fill=tk.X, pady=(2, 2))
        self._labeled_entry(self.template_ice_box, "燃料タンク(L)", self.t_fuel_tank_var)
        self._labeled_entry(self.template_ice_box, "燃費(km/L)", self.t_km_per_l_var)
        self._labeled_entry(self.template_ice_box, "CO2排出(g/km)", self.t_co2_gpkm_var)
        self._labeled_entry(self.template_ice_box, "排気量(L)", self.t_engine_disp_var)
        self._labeled_entry(self.template_ice_box, "最大トルク(Nm)", self.t_max_torque_var)
        self._labeled_entry(self.template_ice_box, "最大出力(kW)", self.t_max_power_var)

        ttk.Checkbutton(form, text="有効", variable=self.t_enabled_var).pack(anchor="w")

        action = ttk.Frame(form)
        action.pack(fill=tk.X, pady=4)
        ttk.Button(action, text="更新", command=self.update_template_from_form).pack(side=tk.LEFT, padx=3)
        ttk.Button(action, text="削除", command=self.delete_selected_template).pack(side=tk.LEFT, padx=3)

        self.template_type_combo.bind("<<ComboboxSelected>>", self._update_template_form_visibility)
        self._update_template_form_visibility()
        self._bind_canvas_mousewheel(_tform_canvas, _tform_inner)

    def _labeled_entry(
        self,
        parent: ttk.Frame,
        label: str,
        var: tk.StringVar,
        readonly: bool = False,
        tooltip: str = "",
    ) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        lbl = ttk.Label(row, text=label, width=36)
        lbl.pack(side=tk.LEFT)
        if tooltip:
            _Tooltip(lbl, tooltip)
        state = "readonly" if readonly else "normal"
        ttk.Entry(row, textvariable=var, state=state).pack(side=tk.LEFT, fill=tk.X, expand=True)
        return row

    def _param_row2(
        self,
        parent: ttk.Frame,
        label0: str,
        var0: tk.Variable,
        tip0: str = "",
        label1: str = "",
        var1: "tk.Variable | None" = None,
        tip1: str = "",
    ) -> None:
        """2列パラメータ行。var1=None のときは左列のみ表示。"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=1)
        frame.columnconfigure(1, weight=1)
        if var1 is not None:
            frame.columnconfigure(3, weight=1)
        lbl0 = ttk.Label(frame, text=label0, width=18, anchor="w")
        lbl0.grid(row=0, column=0, sticky="w")
        if tip0:
            _Tooltip(lbl0, tip0)
        ttk.Entry(frame, textvariable=var0).grid(row=0, column=1, sticky="ew", padx=(2, 4))
        if var1 is not None:
            lbl1 = ttk.Label(frame, text=label1, width=18, anchor="w")
            lbl1.grid(row=0, column=2, sticky="w", padx=(4, 0))
            if tip1:
                _Tooltip(lbl1, tip1)
            ttk.Entry(frame, textvariable=var1).grid(row=0, column=3, sticky="ew", padx=(2, 0))

    def log_line(self, msg: str) -> None:
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def _queue_on_ui_thread(self, callback) -> bool:
        if not self._widget_exists(self.root):
            return False
        try:
            self.root.after(0, callback)
            return True
        except (RuntimeError, tk.TclError):
            return False

    def _update_busy_status(self) -> None:
        if not self._widget_exists(self.root):
            return
        self._busy_var.set("⏳ 処理中..." if self._busy_count > 0 else "")

    def run_bg(self, action, done=None) -> None:
        self._busy_count += 1
        self._update_busy_status()

        def worker() -> None:
            try:
                result = action()
                self._queue_on_ui_thread(lambda: done(result) if done else None)
            except Exception as exc:
                err_msg = str(exc)

                def _show_error(msg: str = err_msg) -> None:
                    if "Dataset '" in msg and "not found" in msg and self.available_dataset_ids:
                        msg = msg + "\n\n利用可能 datasetId: " + ", ".join(self.available_dataset_ids)
                    if "BUILT_DATASET_REQUIRED" in msg or "Built dataset is not available" in msg:
                        msg = (
                            msg
                            + "\n\n対処: data/catalog-fast がある場合は次を実行してください。"
                            + "\npython catalog_update_app.py refresh gtfs-pipeline --source-dir data/catalog-fast --built-datasets tokyu_core,tokyu_full"
                            + "\n完了後にBFFを再起動してください。"
                        )
                    self.log_line(f"エラー: {msg}")
                    messagebox.showerror("エラー", msg)

                self._queue_on_ui_thread(_show_error)
            finally:
                def _dec() -> None:
                    self._busy_count = max(0, self._busy_count - 1)
                    self._update_busy_status()

                self._queue_on_ui_thread(_dec)

        threading.Thread(target=worker, daemon=True).start()

    def _selected_scenario_id(self) -> str:
        idx = self.scenario_combo.current()
        if idx < 0 or idx >= len(self.scenarios):
            return ""
        return str(self.scenarios[idx].get("id") or "")

    @staticmethod
    def _widget_exists(widget: Any) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except (tk.TclError, RuntimeError, AttributeError):
            return False

    def _fleet_window_ready(self) -> bool:
        return self._fleet_built and self._widget_exists(self._fleet_window)

    def _set_cost_component_flags_from_payload(self, simulation_settings: dict[str, Any]) -> None:
        flags = normalize_cost_component_flags(
            simulation_settings.get("costComponentFlags"),
            legacy_disable_vehicle_acquisition_cost=simulation_settings.get(
                "disableVehicleAcquisitionCost"
            ),
            legacy_enable_vehicle_cost=simulation_settings.get("enableVehicleCost"),
            legacy_enable_driver_cost=simulation_settings.get("enableDriverCost"),
            legacy_enable_other_cost=simulation_settings.get("enableOtherCost"),
        )
        for key, variable in self.cost_component_vars.items():
            variable.set(bool(flags.get(key, True)))

    def _cost_component_flags_payload(self) -> dict[str, bool]:
        return {
            key: bool(variable.get())
            for key, variable in self.cost_component_vars.items()
        }

    def _vehicle_panel_ready(self) -> bool:
        return (
            self._fleet_window_ready()
            and self.fleet_depot_var is not None
            and self._widget_exists(self.fleet_depot_combo)
            and self._widget_exists(self.vehicle_tree)
        )

    def _template_panel_ready(self) -> bool:
        return self._fleet_window_ready() and self._widget_exists(self.template_tree)

    def _depot_check_state(self, depot_id: str) -> str:
        route_ids = self.scope_routes_by_depot.get(depot_id, [])
        if not route_ids:
            return "checked" if depot_id in self.scope_selected_depot_ids else "unchecked"
        selected_count = sum(1 for rid in route_ids if rid in self.scope_selected_route_ids)
        if selected_count <= 0:
            return "unchecked"
        if selected_count >= len(route_ids):
            return "checked"
        return "partial"

    def _sync_depot_selection_from_routes(self) -> None:
        next_selected: set[str] = {
            depot_id
            for depot_id in self.scope_selected_depot_ids
            if not self.scope_routes_by_depot.get(depot_id)
        }
        for depot_id, route_ids in self.scope_routes_by_depot.items():
            if any(rid in self.scope_selected_route_ids for rid in route_ids):
                next_selected.add(depot_id)
        self.scope_selected_depot_ids = next_selected

    def _set_all_depots_checked(self, checked: bool) -> None:
        if checked:
            self.scope_selected_depot_ids = set(self.scope_depot_by_id.keys())
            self.scope_selected_route_ids = set(self.scope_route_by_id.keys())
        else:
            self.scope_selected_depot_ids.clear()
            self.scope_selected_route_ids.clear()
        self._mark_prepared_stale("営業所・路線の一括選択を変更")
        self._render_scope_checklist()

    def _set_all_depots_open(self, is_open: bool) -> None:
        for depot_id in self.scope_depot_by_id:
            var = self.scope_depot_open_vars.get(depot_id)
            if var is not None:
                var.set(is_open)
        self._render_scope_checklist()

    def _on_toggle_depot(self, depot_id: str) -> None:
        checked = bool((self.scope_depot_vars.get(depot_id) or tk.BooleanVar(value=False)).get())
        route_ids = self.scope_routes_by_depot.get(depot_id, [])
        if checked:
            self.scope_selected_depot_ids.add(depot_id)
            for route_id in route_ids:
                self.scope_selected_route_ids.add(route_id)
        else:
            self.scope_selected_depot_ids.discard(depot_id)
            for route_id in route_ids:
                self.scope_selected_route_ids.discard(route_id)
        self._sync_depot_selection_from_routes()
        self._mark_prepared_stale("営業所選択を変更")
        self._render_scope_checklist()

    def _on_toggle_route(self, depot_id: str, route_id: str) -> None:
        checked = bool((self.scope_route_vars.get(route_id) or tk.BooleanVar(value=False)).get())
        if checked:
            self.scope_selected_route_ids.add(route_id)
        else:
            self.scope_selected_route_ids.discard(route_id)
        self._sync_depot_selection_from_routes()
        self._mark_prepared_stale("路線選択を変更")
        self._render_scope_checklist()

    def _on_toggle_family(self, depot_id: str, family_key: str) -> None:
        checked = bool((self.scope_family_vars.get(family_key) or tk.BooleanVar(value=False)).get())
        for route_id in self.scope_family_route_ids.get(family_key, []):
            if checked:
                self.scope_selected_route_ids.add(route_id)
            else:
                self.scope_selected_route_ids.discard(route_id)
        self._sync_depot_selection_from_routes()
        self._mark_prepared_stale("系統選択を変更")
        self._render_scope_checklist()

    def _bind_canvas_mousewheel(self, canvas: tk.Canvas, widget: tk.Widget) -> None:
        """Recursively bind MouseWheel on widget tree to scroll the given canvas."""
        widget.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        for child in widget.winfo_children():
            self._bind_canvas_mousewheel(canvas, child)

    def _bind_scope_mousewheel(self, widget: tk.Widget) -> None:
        """Canvas 内に動的生成された子ウィジェット全てにマウスホイールを伝播させる。"""
        self._bind_canvas_mousewheel(self.scope_canvas, widget)

    def _refresh_scope_overview(
        self,
        *,
        filtered_routes: list[dict[str, Any]],
        day_type: str,
    ) -> None:
        full_summary = _scope_summarize_routes(self.scope_routes, day_type=day_type)
        filtered_summary = _scope_summarize_routes(filtered_routes, day_type=day_type)
        selected_routes = [
            self.scope_route_by_id.get(route_id) or {}
            for route_id in self.scope_selected_route_ids
            if route_id in self.scope_route_by_id
        ]
        selected_summary = _scope_summarize_routes(selected_routes, day_type=day_type)
        full_depot_count = len(
            [depot_id for depot_id, route_ids in self.scope_routes_by_depot.items() if route_ids]
        )
        filtered_route_ids = {
            _normalize_scope_text(route.get("id"))
            for route in filtered_routes
            if _normalize_scope_text(route.get("id"))
        }
        filtered_depot_count = len(
            [
                depot_id
                for depot_id, route_ids in self.scope_routes_by_depot.items()
                if any(route_id in filtered_route_ids for route_id in route_ids)
            ]
        )
        selected_depot_count = len(
            [
                depot_id
                for depot_id in self.scope_selected_depot_ids
                if any(route_id in self.scope_selected_route_ids for route_id in self.scope_routes_by_depot.get(depot_id, []))
            ]
        )
        query = self.scope_filter_var.get().strip()
        day_type_label = self._current_day_type_label()
        if query:
            self.scope_summary_var.set(
                f"{day_type_label} 表示一致: {filtered_depot_count}/{full_depot_count}営業所, "
                f"{filtered_summary['familyCount']}/{full_summary['familyCount']}系統, "
                f"{filtered_summary['routeCount']}/{full_summary['routeCount']}variant, "
                f"{filtered_summary['tripCount']}/{full_summary['tripCount']}便"
            )
        else:
            self.scope_summary_var.set(
                f"{day_type_label} 表示: {full_depot_count}営業所, "
                f"{full_summary['familyCount']}系統, "
                f"{full_summary['routeCount']}variant, "
                f"{full_summary['tripCount']}便"
            )
        self.scope_selection_detail_var.set(
            f"選択: {selected_depot_count}営業所, "
            f"{selected_summary['familyCount']}系統, "
            f"{selected_summary['routeCount']}variant, "
            f"{selected_summary['tripCount']}便, "
            f"{_scope_variant_mix_text(selected_summary, metric='trips')}"
        )

    def _render_scope_checklist(self) -> None:
        self._scope_filter_debounce_id = None
        try:
            if not self._widget_exists(self.scope_inner):
                return
            for child in self.scope_inner.winfo_children():
                child.destroy()
        except tk.TclError:
            return

        self.scope_depot_vars = {}
        self.scope_family_vars = {}
        self.scope_route_vars = {}
        day_type = self.day_type_var.get().strip() or "WEEKDAY"
        day_type_label = self._current_day_type_label()
        filtered_routes = _scope_filter_routes(
            self.scope_routes,
            self.scope_filter_var.get(),
        )
        filtered_depot_ids = {
            _scope_depot_id(route)
            for route in filtered_routes
            if _normalize_scope_text(route.get("id"))
        }
        (
            _filtered_family_keys_by_depot,
            filtered_family_route_ids,
            filtered_family_label_by_key,
        ) = _group_scope_routes_by_family(filtered_routes)
        visible_family_keys = set(filtered_family_route_ids.keys())
        self._refresh_scope_overview(filtered_routes=filtered_routes, day_type=day_type)

        if not filtered_routes:
            hint = "検索条件に一致する路線がありません。" if self.scope_filter_var.get().strip() else "表示可能な路線がありません。"
            ttk.Label(
                self.scope_inner,
                text=hint,
                foreground="#666",
                padding=(6, 12),
            ).pack(anchor="w")
            self._bind_scope_mousewheel(self.scope_inner)
            return

        for depot in self.scope_depots:
            depot_id = str(depot.get("id") or "").strip()
            if not depot_id:
                continue
            if depot_id not in filtered_depot_ids:
                continue
            depot_name = str(depot.get("name") or depot_id)
            route_ids = self.scope_routes_by_depot.get(depot_id, [])
            if not route_ids:
                continue
            selected_count = sum(1 for rid in route_ids if rid in self.scope_selected_route_ids)
            depot_routes = [self.scope_route_by_id.get(rid) or {} for rid in route_ids]
            depot_summary = _scope_summarize_routes(depot_routes, day_type=day_type)

            row = ttk.Frame(self.scope_inner)
            row.pack(fill=tk.X, pady=1)

            open_var = self.scope_depot_open_vars.get(depot_id)
            if open_var is None:
                open_var = tk.BooleanVar(value=False)
                self.scope_depot_open_vars[depot_id] = open_var
            ttk.Checkbutton(row, text=("▼" if open_var.get() else "▶"), variable=open_var, command=self._render_scope_checklist, width=2).pack(side=tk.LEFT)

            dep_var = tk.BooleanVar(value=depot_id in self.scope_selected_depot_ids)
            self.scope_depot_vars[depot_id] = dep_var
            ttk.Checkbutton(
                row,
                text=(
                    f"{depot_id} | {depot_name} "
                    f"(選択{selected_count}/{depot_summary['routeCount']}variant, "
                    f"{depot_summary['familyCount']}系統, "
                    f"{day_type_label}{depot_summary['tripCount']}便, "
                    f"{_scope_variant_mix_text(depot_summary, metric='trips')})"
                ),
                variable=dep_var,
                command=lambda d=depot_id: self._on_toggle_depot(d),
            ).pack(side=tk.LEFT, anchor="w")

            if open_var.get():
                for family_key in self.scope_family_keys_by_depot.get(depot_id, []):
                    if family_key not in visible_family_keys:
                        continue
                    family_route_ids = self.scope_family_route_ids.get(family_key, [])
                    family_selected_count = sum(
                        1 for rid in family_route_ids if rid in self.scope_selected_route_ids
                    )
                    family_routes = [self.scope_route_by_id.get(rid) or {} for rid in family_route_ids]
                    family_summary = _scope_summarize_routes(family_routes, day_type=day_type)
                    family_row = ttk.Frame(self.scope_inner)
                    family_row.pack(fill=tk.X, padx=16, pady=1)

                    family_open_var = self.scope_family_open_vars.get(family_key)
                    if family_open_var is None:
                        family_open_var = tk.BooleanVar(value=False)
                        self.scope_family_open_vars[family_key] = family_open_var
                    ttk.Checkbutton(
                        family_row,
                        text=("▼" if family_open_var.get() else "▶"),
                        variable=family_open_var,
                        command=self._render_scope_checklist,
                        width=2,
                    ).pack(side=tk.LEFT)

                    family_var = tk.BooleanVar(
                        value=(
                            family_selected_count == len(family_route_ids)
                            and family_selected_count > 0
                        )
                    )
                    self.scope_family_vars[family_key] = family_var
                    family_label = self.scope_family_label_by_key.get(
                        family_key,
                        filtered_family_label_by_key.get(family_key, family_key),
                    )
                    ttk.Checkbutton(
                        family_row,
                        text=(
                            f"{family_label} "
                            f"(選択{family_selected_count}/{family_summary['routeCount']}variant, "
                            f"{day_type_label}{family_summary['tripCount']}便, "
                            f"{_scope_variant_mix_text(family_summary, metric='trips')})"
                        ),
                        variable=family_var,
                        command=lambda d=depot_id, fk=family_key: self._on_toggle_family(d, fk),
                    ).pack(side=tk.LEFT, anchor="w")

                    if family_open_var.get():
                        for route_id in family_route_ids:
                            route = self.scope_route_by_id.get(route_id) or {}
                            route_row = ttk.Frame(self.scope_inner)
                            route_row.pack(fill=tk.X, padx=34)
                            route_var = tk.BooleanVar(value=route_id in self.scope_selected_route_ids)
                            self.scope_route_vars[route_id] = route_var
                            ttk.Checkbutton(
                                route_row,
                                text=(
                                    f"{_scope_route_child_label(route)} "
                                    f"({_scope_trip_count_text(route, day_type=day_type, day_type_label=day_type_label)})"
                                ),
                                variable=route_var,
                                command=lambda d=depot_id, r=route_id: self._on_toggle_route(d, r),
                            ).pack(side=tk.LEFT, anchor="w")

        # 動的生成した子ウィジェット全てにマウスホイールを伝播させる
        self._bind_scope_mousewheel(self.scope_inner)

    def _set_scope_data(
        self,
        depots: list[dict[str, Any]],
        routes: list[dict[str, Any]],
        selected_depots: set[str],
        selected_routes: set[str],
    ) -> None:
        self.scope_depots = list(depots)
        self.scope_all_routes = list(routes)
        self.scope_depot_by_id = {
            str(item.get("id") or "").strip(): item
            for item in self.scope_depots
            if str(item.get("id") or "").strip()
        }
        self.scope_selected_route_ids = set(
            str(rid).strip() for rid in selected_routes if str(rid).strip()
        )
        self.scope_selected_depot_ids = {
            did for did in selected_depots if did in self.scope_depot_by_id
        }
        self._refresh_scope_route_cache(self.scope_all_routes)
        self._apply_day_type_scope_filter()

    def _selected_depot_ids(self) -> list[str]:
        return sorted(self.scope_selected_depot_ids)

    def _selected_route_ids(self) -> list[str]:
        return sorted(self.scope_selected_route_ids)

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

    @staticmethod
    def _normalize_powertrain_payload(payload: dict[str, Any]) -> dict[str, Any]:
        vtype = str(payload.get("type") or "BEV").strip().upper()
        payload["type"] = vtype
        if vtype == "BEV":
            payload["fuelTankL"] = None
            payload["fuelEfficiencyKmPerL"] = None
            payload["co2EmissionGPerKm"] = None
            payload["engineDisplacementL"] = None
        else:
            payload["batteryKwh"] = None
            payload["chargePowerKw"] = None
            payload["minSoc"] = None
            payload["maxSoc"] = None
        return payload

    def _update_vehicle_form_visibility(self, _event=None) -> None:
        vtype = self.v_type_var.get().strip().upper() or "BEV"
        if vtype == "BEV":
            self.vehicle_ev_box.pack(fill=tk.X, pady=(4, 2))
            self.vehicle_ice_box.pack_forget()
        else:
            self.vehicle_ice_box.pack(fill=tk.X, pady=(2, 2))
            self.vehicle_ev_box.pack_forget()

    def _update_template_form_visibility(self, _event=None) -> None:
        vtype = self.t_type_var.get().strip().upper() or "BEV"
        if vtype == "BEV":
            self.template_ev_box.pack(fill=tk.X, pady=(4, 2))
            self.template_ice_box.pack_forget()
        else:
            self.template_ice_box.pack(fill=tk.X, pady=(2, 2))
            self.template_ev_box.pack_forget()

    def _build_vehicle_payload_from_form(self) -> dict[str, Any]:
        payload = {
            "depotId": self.v_depot_var.get().strip(),
            "type": self.v_type_var.get().strip().upper() or "BEV",
            "modelCode": self.v_model_code_var.get().strip() or None,
            "modelName": self.v_model_var.get().strip(),
            "capacityPassengers": self._parse_int(self.v_cap_var.get(), 0),
            "batteryKwh": self._parse_optional_float(self.v_battery_var.get()),
            "fuelTankL": self._parse_optional_float(self.v_fuel_tank_var.get()),
            "energyConsumption": self._parse_float(self.v_energy_var.get(), 0.0),
            "fuelEfficiencyKmPerL": self._parse_optional_float(self.v_km_per_l_var.get()),
            "co2EmissionGPerKm": self._parse_optional_float(self.v_co2_gpkm_var.get()),
            "curbWeightKg": self._parse_optional_float(self.v_curb_weight_var.get()),
            "grossVehicleWeightKg": self._parse_optional_float(self.v_gross_weight_var.get()),
            "engineDisplacementL": self._parse_optional_float(self.v_engine_disp_var.get()),
            "maxTorqueNm": self._parse_optional_float(self.v_max_torque_var.get()),
            "maxPowerKw": self._parse_optional_float(self.v_max_power_var.get()),
            "chargePowerKw": self._parse_optional_float(self.v_charge_kw_var.get()),
            "minSoc": self._parse_optional_float(self.v_min_soc_var.get()),
            "maxSoc": self._parse_optional_float(self.v_max_soc_var.get()),
            "acquisitionCost": self._parse_float(self.v_acq_cost_var.get(), 0.0),
            "enabled": bool(self.v_enabled_var.get()),
        }
        return self._normalize_powertrain_payload(payload)

    def _build_template_payload_from_form(self) -> dict[str, Any]:
        payload = {
            "name": self.t_name_var.get().strip(),
            "type": self.t_type_var.get().strip().upper() or "BEV",
            "modelCode": self.t_model_code_var.get().strip() or None,
            "modelName": self.t_model_var.get().strip(),
            "capacityPassengers": self._parse_int(self.t_cap_var.get(), 0),
            "batteryKwh": self._parse_optional_float(self.t_battery_var.get()),
            "fuelTankL": self._parse_optional_float(self.t_fuel_tank_var.get()),
            "energyConsumption": self._parse_float(self.t_energy_var.get(), 0.0),
            "fuelEfficiencyKmPerL": self._parse_optional_float(self.t_km_per_l_var.get()),
            "co2EmissionGPerKm": self._parse_optional_float(self.t_co2_gpkm_var.get()),
            "curbWeightKg": self._parse_optional_float(self.t_curb_weight_var.get()),
            "grossVehicleWeightKg": self._parse_optional_float(self.t_gross_weight_var.get()),
            "engineDisplacementL": self._parse_optional_float(self.t_engine_disp_var.get()),
            "maxTorqueNm": self._parse_optional_float(self.t_max_torque_var.get()),
            "maxPowerKw": self._parse_optional_float(self.t_max_power_var.get()),
            "chargePowerKw": self._parse_optional_float(self.t_charge_var.get()),
            "minSoc": self._parse_optional_float(self.t_min_soc_var.get()),
            "maxSoc": self._parse_optional_float(self.t_max_soc_var.get()),
            "acquisitionCost": self._parse_float(self.t_acq_cost_var.get(), 0.0),
            "enabled": bool(self.t_enabled_var.get()),
        }
        return self._normalize_powertrain_payload(payload)

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
    def _format_tou_text(bands: Any) -> str:
        if not isinstance(bands, list):
            return ""
        chunks: list[str] = []
        for item in bands:
            if not isinstance(item, dict):
                continue
            s = item.get("start_hour")
            e = item.get("end_hour")
            p = item.get("price_per_kwh")
            if s is None or e is None or p is None:
                continue
            chunks.append(f"{int(s)}-{int(e)}:{float(p):g}")
        return ",".join(chunks)

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
        return normalize_direction(value, default=default)

    @staticmethod
    def _normalize_variant_type(value: Any) -> str:
        if str(value or "").strip() == "":
            return "unknown"
        return normalize_variant_type(value, direction="unknown")

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

    def _parse_depot_energy_assets_json_or_none(self) -> list[dict[str, Any]] | None:
        raw = self.depot_energy_assets_json_var.get().strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except Exception:
            messagebox.showwarning("入力エラー", "depot_energy_assets は JSON 形式で入力してください")
            raise ValueError("invalid_depot_energy_assets_json")
        if not isinstance(payload, list):
            messagebox.showwarning("入力エラー", "depot_energy_assets は JSON 配列で入力してください")
            raise ValueError("invalid_depot_energy_assets_shape")
        out: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                out.append(dict(item))
        return out

    def _planning_days_value(self) -> int:
        return max(self._parse_int(self.planning_days_var.get(), 1), 1)

    def _normalize_hhmm_text(self, value: str, *, default: str) -> str:
        text = str(value or "").strip()
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
        if not match:
            return default
        hh = int(match.group(1))
        mm = int(match.group(2))
        if mm < 0 or mm >= 60:
            return default
        hh = hh % 24
        return f"{hh:02d}:{mm:02d}"

    def _planning_horizon_hours_value(self, planning_days: int) -> float:
        start_hhmm = self._normalize_hhmm_text(self.operation_start_time_var.get(), default="05:00")
        end_hhmm = self._normalize_hhmm_text(self.operation_end_time_var.get(), default="23:00")
        start_h, start_m = [int(part) for part in start_hhmm.split(":")]
        end_h, end_m = [int(part) for part in end_hhmm.split(":")]
        start_min = start_h * 60 + start_m
        end_min = end_h * 60 + end_m
        day_minutes = end_min - start_min
        if day_minutes <= 0:
            day_minutes += 24 * 60
        if planning_days > 1:
            return 24.0 * float(planning_days)
        return max(day_minutes / 60.0, 1.0)

    def _selected_service_dates(self, *, announce: bool) -> list[str] | None:
        raw_service_date = self.service_date_var.get().strip()
        service_dates = _build_service_dates(
            raw_service_date,
            planning_days=self._planning_days_value(),
        )
        if service_dates is None and announce:
            messagebox.showwarning("入力エラー", "運行日は YYYY-MM-DD 形式で入力してください")
        return service_dates

    def _refresh_service_dates_preview(self) -> None:
        service_dates = self._selected_service_dates(announce=False)
        if service_dates is None:
            self.service_dates_preview_var.set("対象日: 日付形式エラー")
            return
        self.service_dates_preview_var.set(
            "対象日: " + _format_service_dates_summary(service_dates)
        )

    def _sync_pv_assets_for_selected_depots(
        self,
        *,
        announce: bool,
    ) -> list[dict[str, Any]] | None:
        try:
            current_rows = self._parse_depot_energy_assets_json_or_none() or []
        except ValueError:
            return None

        service_dates = self._selected_service_dates(announce=announce)
        if service_dates is None:
            return None
        if not service_dates:
            if announce:
                messagebox.showwarning("入力不足", "運行日を入力してからPV同期してください")
            return None

        selected_depot_ids = self._selected_depot_ids()
        depot_area_by_id = {
            str(item.get("id") or "").strip(): item.get("depotAreaM2", item.get("depot_area_m2"))
            for item in self.scope_depots
            if str(item.get("id") or "").strip()
        }
        merged_rows, synced_ids, missing_ids = _merge_selected_depot_pv_assets(
            selected_depot_ids,
            current_rows,
            service_dates,
            depot_area_by_id=depot_area_by_id,
        )
        if not synced_ids and not current_rows:
            if announce:
                messagebox.showwarning(
                    "実日PV同期",
                    "選択営業所に対応する実日PVプロファイルが見つかりませんでした。",
                )
            return current_rows

        if merged_rows:
            self.depot_energy_assets_json_var.set(
                json.dumps(merged_rows, ensure_ascii=True, separators=(",", ":"))
            )
        if synced_ids:
            profile_range = (
                service_dates[0]
                if len(service_dates) == 1
                else f"{service_dates[0]}_to_{service_dates[-1]}"
            )
            if len(synced_ids) == 1:
                self.pv_profile_id_var.set(f"{synced_ids[0]}_{profile_range}_60min")
            else:
                self.pv_profile_id_var.set(
                    f"selected_depots_{profile_range}_60min"
                )
            self.weather_mode_var.set(_ACTUAL_DATE_PV_PROFILE_ID)
            self.log_line(
                "選択営業所へ実日PVを同期: "
                + ", ".join(synced_ids)
                + f" / dates={_format_service_dates_summary(service_dates)}"
            )
        if missing_ids:
            self.log_line(
                "実日PVプロファイル未検出: " + ", ".join(missing_ids)
            )
        if announce:
            messagebox.showinfo(
                "実日PV同期",
                "同期した営業所: "
                + (", ".join(synced_ids) if synced_ids else "なし")
                + f"\n対象日: {_format_service_dates_summary(service_dates)}"
                + (
                    "\n未検出: " + ", ".join(missing_ids)
                    if missing_ids
                    else ""
                ),
            )
        return merged_rows

    def sync_selected_depot_pv_assets(self) -> None:
        self._sync_pv_assets_for_selected_depots(announce=True)

    def open_depot_energy_assets_editor(self) -> None:
        try:
            current_rows = self._parse_depot_energy_assets_json_or_none() or []
        except ValueError:
            return

        win = tk.Toplevel(self.root)
        win.title("営業所エネルギー資産 行編集")
        win.geometry("1160x640")

        rows: list[dict[str, Any]] = [dict(item) for item in current_rows]
        service_dates = self._selected_service_dates(announce=False) or []

        top_note = ttk.Label(
            win,
            text=(
                "depot_energy_assets を行単位で編集します。保存すると JSON 欄へ反映されます。"
                f" 実日PV同期の対象日: {_format_service_dates_summary(service_dates)}"
            ),
            foreground="#444",
        )
        top_note.pack(anchor="w", padx=10, pady=(10, 4))

        tree_frame = ttk.Frame(win, padding=(10, 0, 10, 0))
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = (
            "depot_id",
            "pv_period",
            "pv_slots",
            "depot_area_m2",
            "estimated_installable_area_m2",
            "pv_enabled",
            "pv_capacity_kw",
            "bess_enabled",
            "bess_energy_kwh",
            "bess_power_kw",
            "allow_grid_to_bess",
            "grid_to_bess_price_threshold_yen_per_kwh",
            "bess_terminal_soc_min_kwh",
        )
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        headers = {
            "depot_id": "営業所ID",
            "pv_period": "PV対象日",
            "pv_slots": "PVスロット数",
            "depot_area_m2": "営業所面積[m²]",
            "estimated_installable_area_m2": "PV設置可能面積[m²]",
            "pv_enabled": "PV有効",
            "pv_capacity_kw": "推定PV容量[kW]",
            "bess_enabled": "BESS有効",
            "bess_energy_kwh": "BESS容量[kWh]",
            "bess_power_kw": "BESS出力[kW]",
            "allow_grid_to_bess": "Grid→BESS",
            "grid_to_bess_price_threshold_yen_per_kwh": "Grid→BESS閾値[円/kWh]",
            "bess_terminal_soc_min_kwh": "終端SOC下限[kWh]",
        }
        widths = {
            "depot_id": 120,
            "pv_period": 180,
            "pv_slots": 90,
            "depot_area_m2": 110,
            "estimated_installable_area_m2": 130,
            "pv_enabled": 70,
            "pv_capacity_kw": 100,
            "bess_enabled": 80,
            "bess_energy_kwh": 120,
            "bess_power_kw": 120,
            "allow_grid_to_bess": 90,
            "grid_to_bess_price_threshold_yen_per_kwh": 170,
            "bess_terminal_soc_min_kwh": 140,
        }
        for col in cols:
            tree.heading(col, text=headers[col])
            tree.column(col, width=widths[col], anchor="center")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=ysb.set)

        editor = ttk.LabelFrame(win, text="行編集", padding=10)
        editor.pack(fill=tk.X, padx=10, pady=(8, 6))

        depot_id_var = tk.StringVar(value="")
        pv_enabled_var = tk.BooleanVar(value=False)
        depot_area_m2_var = tk.StringVar(value="")
        estimated_installable_area_var = tk.StringVar(value="0")
        pv_capacity_kw_var = tk.StringVar(value="0")
        bess_enabled_var = tk.BooleanVar(value=False)
        bess_energy_kwh_var = tk.StringVar(value="0")
        bess_power_kw_var = tk.StringVar(value="0")
        bess_initial_soc_kwh_var = tk.StringVar(value="0")
        bess_soc_min_kwh_var = tk.StringVar(value="0")
        bess_soc_max_kwh_var = tk.StringVar(value="0")
        allow_grid_to_bess_var = tk.BooleanVar(value=False)
        grid_to_bess_price_threshold_var = tk.StringVar(value="0")
        grid_to_bess_allowed_slots_var = tk.StringVar(value="")
        bess_terminal_soc_min_kwh_var = tk.StringVar(value="0")
        provisional_energy_cost_var = tk.StringVar(value="0")
        pv_dates_info_var = tk.StringVar(value="")
        pv_slot_count_info_var = tk.StringVar(value="0")

        depots = [str(item.get("id") or "").strip() for item in self.scope_depots if str(item.get("id") or "").strip()]
        if depots:
            dep_row = ttk.Frame(editor)
            dep_row.pack(fill=tk.X, pady=2)
            ttk.Label(dep_row, text="営業所ID", width=34).pack(side=tk.LEFT)
            depot_combo = ttk.Combobox(dep_row, textvariable=depot_id_var, state="readonly", values=depots)
            depot_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            self._labeled_entry(editor, "営業所ID", depot_id_var)

        flag_row = ttk.Frame(editor)
        flag_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(flag_row, text="PV有効(面積>0で自動)", variable=pv_enabled_var).pack(side=tk.LEFT)
        ttk.Checkbutton(flag_row, text="BESS有効", variable=bess_enabled_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(flag_row, text="Grid→BESS許可", variable=allow_grid_to_bess_var).pack(side=tk.LEFT, padx=(12, 0))

        self._labeled_entry(editor, "営業所面積[m²] depot_area_m2", depot_area_m2_var)
        self._labeled_entry(editor, "推定PV設置可能面積[m²]", estimated_installable_area_var, readonly=True)
        self._labeled_entry(editor, "推定PV容量[kW] pv_capacity_kw", pv_capacity_kw_var, readonly=True)
        self._labeled_entry(editor, "BESS容量[kWh] bess_energy_kwh", bess_energy_kwh_var)
        self._labeled_entry(editor, "BESS出力[kW] bess_power_kw", bess_power_kw_var)
        self._labeled_entry(editor, "BESS初期SOC[kWh] bess_initial_soc_kwh", bess_initial_soc_kwh_var)
        self._labeled_entry(editor, "BESS最小SOC[kWh] bess_soc_min_kwh", bess_soc_min_kwh_var)
        self._labeled_entry(editor, "BESS最大SOC[kWh] bess_soc_max_kwh", bess_soc_max_kwh_var)
        self._labeled_entry(editor, "Grid→BESS閾値[円/kWh]", grid_to_bess_price_threshold_var)
        self._labeled_entry(editor, "Grid→BESS許可スロット(カンマ区切り)", grid_to_bess_allowed_slots_var)
        self._labeled_entry(editor, "終端SOC下限[kWh]", bess_terminal_soc_min_kwh_var)
        self._labeled_entry(editor, "仮コスト単価[円/kWh]", provisional_energy_cost_var)
        self._labeled_entry(editor, "PV対象日(読取専用)", pv_dates_info_var, readonly=True)
        self._labeled_entry(editor, "PVスロット数(読取専用)", pv_slot_count_info_var, readonly=True)

        selected_index: list[int | None] = [None]

        def _refresh_pv_area_preview(*_args: Any) -> None:
            estimate = estimate_depot_pv_from_area(depot_area_m2_var.get())
            estimated_installable_area_var.set(f"{estimate.installable_area_m2:.3f}")
            pv_capacity_kw_var.set(f"{estimate.capacity_kw:.3f}" if estimate.depot_area_m2 is not None else "0")
            pv_enabled_var.set(estimate.depot_area_m2 is not None and estimate.capacity_kw > 0.0)

        depot_area_m2_var.trace_add("write", _refresh_pv_area_preview)

        def _row_to_values(row: dict[str, Any]) -> tuple[Any, ...]:
            pv_dates = list(row.get("pv_profile_dates") or [])
            pv_slots = list(row.get("pv_generation_kwh_by_slot") or [])
            return (
                str(row.get("depot_id") or row.get("depotId") or ""),
                _format_service_dates_summary(pv_dates),
                len(pv_slots),
                row.get("depot_area_m2", row.get("depotAreaM2")),
                row.get("estimated_installable_area_m2", 0.0),
                bool(row.get("pv_enabled", False)),
                row.get("pv_capacity_kw", 0.0),
                bool(row.get("bess_enabled", False)),
                row.get("bess_energy_kwh", 0.0),
                row.get("bess_power_kw", 0.0),
                bool(row.get("allow_grid_to_bess", False)),
                row.get("grid_to_bess_price_threshold_yen_per_kwh", 0.0),
                row.get("bess_terminal_soc_min_kwh", 0.0),
            )

        def _refresh_tree() -> None:
            tree.delete(*tree.get_children())
            for idx, row in enumerate(rows):
                tree.insert("", tk.END, iid=str(idx), values=_row_to_values(row))

        def _set_form_from_row(row: dict[str, Any]) -> None:
            depot_id_var.set(str(row.get("depot_id") or row.get("depotId") or ""))
            pv_enabled_var.set(bool(row.get("pv_enabled", False)))
            depot_area = row.get("depot_area_m2", row.get("depotAreaM2"))
            depot_area_m2_var.set("" if depot_area is None else str(depot_area))
            _refresh_pv_area_preview()
            bess_enabled_var.set(bool(row.get("bess_enabled", False)))
            bess_energy_kwh_var.set(str(row.get("bess_energy_kwh", 0.0)))
            bess_power_kw_var.set(str(row.get("bess_power_kw", 0.0)))
            bess_initial_soc_kwh_var.set(str(row.get("bess_initial_soc_kwh", 0.0)))
            bess_soc_min_kwh_var.set(str(row.get("bess_soc_min_kwh", 0.0)))
            bess_soc_max_kwh_var.set(str(row.get("bess_soc_max_kwh", 0.0)))
            allow_grid_to_bess_var.set(bool(row.get("allow_grid_to_bess", False)))
            grid_to_bess_price_threshold_var.set(
                str(row.get("grid_to_bess_price_threshold_yen_per_kwh", 0.0))
            )
            grid_to_bess_allowed_slots_var.set(
                ",".join(str(v) for v in (row.get("grid_to_bess_allowed_slot_indices") or []))
            )
            bess_terminal_soc_min_kwh_var.set(str(row.get("bess_terminal_soc_min_kwh", 0.0)))
            provisional_energy_cost_var.set(str(row.get("provisional_energy_cost_yen_per_kwh", 0.0)))
            pv_dates = list(row.get("pv_profile_dates") or [])
            pv_dates_info_var.set(_format_service_dates_summary(pv_dates))
            pv_slot_count_info_var.set(str(len(row.get("pv_generation_kwh_by_slot") or [])))

        def _read_form_to_row(base: dict[str, Any] | None = None) -> dict[str, Any] | None:
            depot_id = depot_id_var.get().strip()
            if not depot_id:
                messagebox.showwarning("入力不足", "営業所IDを入力してください", parent=win)
                return None
            row = dict(base or {})
            row["depot_id"] = depot_id
            area_text = depot_area_m2_var.get().strip()
            row["depot_area_m2"] = self._parse_float(area_text, 0.0) if area_text else None
            row["bess_enabled"] = bool(bess_enabled_var.get())
            row["bess_energy_kwh"] = self._parse_float(bess_energy_kwh_var.get(), 0.0)
            row["bess_power_kw"] = self._parse_float(bess_power_kw_var.get(), 0.0)
            row["bess_initial_soc_kwh"] = self._parse_float(bess_initial_soc_kwh_var.get(), 0.0)
            row["bess_soc_min_kwh"] = self._parse_float(bess_soc_min_kwh_var.get(), 0.0)
            row["bess_soc_max_kwh"] = self._parse_float(bess_soc_max_kwh_var.get(), 0.0)
            row["allow_grid_to_bess"] = bool(allow_grid_to_bess_var.get())
            row["grid_to_bess_price_threshold_yen_per_kwh"] = self._parse_float(
                grid_to_bess_price_threshold_var.get(),
                0.0,
            )
            raw_slots = [item.strip() for item in grid_to_bess_allowed_slots_var.get().split(",") if item.strip()]
            parsed_slots: list[int] = []
            for item in raw_slots:
                try:
                    parsed_slots.append(int(item))
                except ValueError:
                    messagebox.showwarning("入力エラー", f"許可スロット '{item}' は整数で入力してください", parent=win)
                    return None
            row["grid_to_bess_allowed_slot_indices"] = parsed_slots
            row["bess_terminal_soc_min_kwh"] = self._parse_float(bess_terminal_soc_min_kwh_var.get(), 0.0)
            row["provisional_energy_cost_yen_per_kwh"] = self._parse_float(provisional_energy_cost_var.get(), 0.0)
            row = _rebuild_pv_generation_for_row(row)
            return row

        def _clear_form() -> None:
            selected_index[0] = None
            depot_id_var.set("")
            pv_enabled_var.set(False)
            depot_area_m2_var.set("")
            estimated_installable_area_var.set("0")
            pv_capacity_kw_var.set("0")
            bess_enabled_var.set(False)
            bess_energy_kwh_var.set("0")
            bess_power_kw_var.set("0")
            bess_initial_soc_kwh_var.set("0")
            bess_soc_min_kwh_var.set("0")
            bess_soc_max_kwh_var.set("0")
            allow_grid_to_bess_var.set(False)
            grid_to_bess_price_threshold_var.set("0")
            grid_to_bess_allowed_slots_var.set("")
            bess_terminal_soc_min_kwh_var.set("0")
            provisional_energy_cost_var.set("0")
            pv_dates_info_var.set("")
            pv_slot_count_info_var.set("0")

        def _on_select(_event=None) -> None:
            sel = tree.selection()
            if not sel:
                selected_index[0] = None
                return
            idx = int(sel[0])
            selected_index[0] = idx
            _set_form_from_row(rows[idx])

        tree.bind("<<TreeviewSelect>>", _on_select)

        btns = ttk.Frame(editor)
        btns.pack(fill=tk.X, pady=(8, 0))

        def _add_row() -> None:
            row = _read_form_to_row()
            if row is None:
                return
            rows.append(row)
            _refresh_tree()
            tree.selection_set(str(len(rows) - 1))
            tree.see(str(len(rows) - 1))

        def _update_row() -> None:
            idx = selected_index[0]
            if idx is None or idx < 0 or idx >= len(rows):
                messagebox.showwarning("未選択", "更新する行を選択してください", parent=win)
                return
            row = _read_form_to_row(base=rows[idx])
            if row is None:
                return
            rows[idx] = row
            _refresh_tree()
            tree.selection_set(str(idx))

        def _delete_row() -> None:
            idx = selected_index[0]
            if idx is None or idx < 0 or idx >= len(rows):
                messagebox.showwarning("未選択", "削除する行を選択してください", parent=win)
                return
            del rows[idx]
            _refresh_tree()
            _clear_form()

        def _build_default_row_for_depot(depot_id: str) -> dict[str, Any]:
            row = _default_depot_energy_asset_row(depot_id)
            depot = getattr(self, "scope_depot_by_id", {}).get(depot_id) or {}
            if isinstance(depot, dict):
                area_value = depot.get("depotAreaM2", depot.get("depot_area_m2"))
                if area_value is not None:
                    row["depot_area_m2"] = area_value
            return _rebuild_pv_generation_for_row(row)

        def _generate_rows_for_all_depots() -> None:
            depot_ids = [
                str(item.get("id") or "").strip()
                for item in self.scope_depots
                if str(item.get("id") or "").strip()
            ]
            if not depot_ids:
                messagebox.showwarning("営業所なし", "営業所一覧が未ロードです。Quick Setup を読込してください", parent=win)
                return

            existing_ids = {
                str(item.get("depot_id") or item.get("depotId") or "").strip()
                for item in rows
                if isinstance(item, dict)
            }
            added = 0
            for depot_id in depot_ids:
                if depot_id in existing_ids:
                    continue
                rows.append(_build_default_row_for_depot(depot_id))
                existing_ids.add(depot_id)
                added += 1

            _refresh_tree()
            if rows:
                tree.selection_set("0")
                _on_select()
            self.log_line(
                f"depot_energy_assets 初期テンプレ行を自動生成: 追加={added} / 既存維持={len(depot_ids) - added}"
            )
            messagebox.showinfo(
                "自動生成完了",
                f"営業所テンプレ行の追加: {added} 件\n既存行は保持しました。",
                parent=win,
            )

        ttk.Button(btns, text="新規行追加", command=_add_row).pack(side=tk.LEFT)
        ttk.Button(btns, text="営業所ごとに初期行を自動生成", command=_generate_rows_for_all_depots).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="選択行更新", command=_update_row).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="選択行削除", command=_delete_row).pack(side=tk.LEFT)
        ttk.Button(btns, text="入力クリア", command=_clear_form).pack(side=tk.LEFT, padx=6)

        footer = ttk.Frame(win, padding=(10, 6, 10, 10))
        footer.pack(fill=tk.X)

        def _apply_to_json() -> None:
            dumped = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
            self.depot_energy_assets_json_var.set(dumped)
            self.log_line(f"depot_energy_assets を行編集から反映しました: {len(rows)}件")
            win.destroy()

        ttk.Button(footer, text="JSONへ反映して閉じる", command=_apply_to_json).pack(side=tk.RIGHT)
        ttk.Button(footer, text="キャンセル", command=win.destroy).pack(side=tk.RIGHT, padx=(0, 6))

        _refresh_tree()
        if rows:
            tree.selection_set("0")
            _on_select()

    def _set_day_type_value(self, day_type: str) -> None:
        value = str(day_type or "WEEKDAY").strip() or "WEEKDAY"
        options = list(self.day_type_options)
        if value not in options:
            options.append(value)
            self.day_type_options = options
            self.day_type_combo.configure(values=options)
        self.day_type_var.set(value)

    def _set_day_type_options_from_payload(self, entries: list[dict[str, Any]]) -> None:
        options: list[str] = []
        for entry in entries:
            service_id = str(entry.get("serviceId") or "").strip()
            if service_id and service_id not in options:
                options.append(service_id)
        if not options:
            return
        self.day_type_options = options
        self.day_type_combo.configure(values=options)

    def _on_fixed_route_band_mode_changed(self) -> None:
        if self._suspend_route_lock_sync:
            return
        if self.fixed_route_band_mode_var.get():
            self.allow_intra_var.set(False)
            if not self.enable_vehicle_diagram_output_var.get():
                self.enable_vehicle_diagram_output_var.set(True)

    def _bind_keyboard_shortcuts(self) -> None:
        """Register global keyboard shortcuts for common operations."""
        self.root.bind("<F5>", lambda _e: self.refresh_scenarios())
        self.root.bind("<Control-s>", lambda _e: self.save_quick_setup())
        self.root.bind("<Control-n>", lambda _e: self.create_scenario())
        self.root.bind("<Control-r>", lambda _e: self.refresh_scenarios())

    def _debounced_render_scope_checklist(self) -> None:
        """Debounce scope filter to avoid rebuilding UI on every keystroke."""
        if self._scope_filter_debounce_id is not None:
            self.root.after_cancel(self._scope_filter_debounce_id)
        self._scope_filter_debounce_id = self.root.after(250, self._render_scope_checklist)

    def _register_scope_ui_watchers(self) -> None:
        self.day_type_var.trace_add("write", lambda *_args: self._on_day_type_changed())
        self.service_date_var.trace_add("write", lambda *_args: self._refresh_service_dates_preview())
        self.planning_days_var.trace_add("write", lambda *_args: self._refresh_service_dates_preview())
        self.scope_filter_var.trace_add("write", lambda *_args: self._debounced_render_scope_checklist())
        self.fixed_route_band_mode_var.trace_add(
            "write",
            lambda *_args: self._on_fixed_route_band_mode_changed(),
        )

    def _current_day_type_label(self) -> str:
        service_id = self.day_type_var.get().strip() or "WEEKDAY"
        return self.scope_day_type_label_by_id.get(service_id, service_id)

    def _set_day_type_summaries(self, entries: list[dict[str, Any]]) -> None:
        summaries = [
            dict(entry)
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("serviceId") or "").strip()
        ]
        if not summaries:
            summaries = [
                {
                    "serviceId": service_id,
                    "label": service_id,
                    "familyCount": 0,
                    "routeCount": 0,
                    "tripCount": 0,
                    "mainRouteCount": 0,
                    "mainTripCount": 0,
                    "shortTurnRouteCount": 0,
                    "shortTurnTripCount": 0,
                    "depotRouteCount": 0,
                    "depotTripCount": 0,
                    "branchRouteCount": 0,
                    "branchTripCount": 0,
                    "unknownRouteCount": 0,
                    "unknownTripCount": 0,
                    "selected": service_id == self.day_type_var.get().strip(),
                }
                for service_id in self.day_type_options
                if service_id
            ]
        self.scope_day_type_summaries = summaries
        self.scope_day_type_label_by_id = {
            str(entry.get("serviceId") or "").strip(): str(entry.get("label") or entry.get("serviceId") or "").strip()
            for entry in self.scope_day_type_summaries
            if str(entry.get("serviceId") or "").strip()
        }
        self._refresh_day_type_summary_tree()

    def _refresh_day_type_summary_tree(self) -> None:
        if not self._widget_exists(self.day_type_summary_tree):
            return
        current_service_id = self.day_type_var.get().strip() or "WEEKDAY"
        tree = self.day_type_summary_tree
        tree.delete(*tree.get_children())
        for entry in self.scope_day_type_summaries:
            service_id = str(entry.get("serviceId") or "").strip()
            if not service_id:
                continue
            tree.insert(
                "",
                tk.END,
                iid=service_id,
                values=(
                    service_id,
                    str(entry.get("label") or service_id),
                    int(entry.get("familyCount") or 0),
                    int(entry.get("routeCount") or 0),
                    int(entry.get("tripCount") or 0),
                    _scope_variant_mix_text(entry, metric="trips"),
                ),
            )
        if current_service_id and tree.exists(current_service_id):
            self._suspend_day_type_summary_event = True
            try:
                tree.selection_set(current_service_id)
                tree.focus(current_service_id)
            finally:
                self._suspend_day_type_summary_event = False

    def _on_day_type_summary_selected(self, _event=None) -> None:
        if self._suspend_day_type_summary_event or not self._widget_exists(self.day_type_summary_tree):
            return
        selection = self.day_type_summary_tree.selection()
        if not selection:
            return
        service_id = str(selection[0] or "").strip()
        if service_id and service_id != self.day_type_var.get().strip():
            self.day_type_var.set(service_id)

    def _refresh_scope_route_cache(self, routes: list[dict[str, Any]]) -> None:
        self.scope_routes = []
        for item in routes:
            if not isinstance(item, dict):
                continue
            route = dict(item)
            route["_scopeSearchText"] = _scope_route_search_text(route)
            self.scope_routes.append(route)
        self.scope_route_by_id = {
            str(item.get("id") or "").strip(): item
            for item in self.scope_routes
            if str(item.get("id") or "").strip()
        }
        self.scope_routes_by_depot = {}
        for route in self.scope_routes:
            route_id = str(route.get("id") or "").strip()
            if not route_id:
                continue
            depot_id = str(route.get("depotId") or "").strip()
            if not depot_id or depot_id not in self.scope_depot_by_id:
                depot_id = "__unassigned__"
                if depot_id not in self.scope_depot_by_id:
                    unassigned = {
                        "id": "__unassigned__",
                        "name": "未割当営業所",
                    }
                    self.scope_depots.append(unassigned)
                    self.scope_depot_by_id[depot_id] = unassigned
            self.scope_routes_by_depot.setdefault(depot_id, []).append(route_id)

        for depot in self.scope_depots:
            depot_id = str(depot.get("id") or "").strip()
            if depot_id and depot_id not in self.scope_routes_by_depot:
                self.scope_routes_by_depot[depot_id] = []

        (
            self.scope_family_keys_by_depot,
            self.scope_family_route_ids,
            self.scope_family_label_by_key,
        ) = _group_scope_routes_by_family(self.scope_routes)

    def _apply_day_type_scope_filter(self) -> None:
        self.scope_selected_route_ids = {
            rid for rid in self.scope_selected_route_ids if rid in self.scope_route_by_id
        }
        self.scope_selected_depot_ids = {
            did for did in self.scope_selected_depot_ids if did in self.scope_depot_by_id
        }
        self._sync_depot_selection_from_routes()
        self._render_scope_checklist()

    def _on_day_type_changed(self) -> None:
        self._refresh_day_type_summary_tree()
        self._apply_day_type_scope_filter()
        if self._suspend_prepare_watchers or not self.scope_day_type_summaries:
            return
        current_service_id = self.day_type_var.get().strip() or "WEEKDAY"
        current_day_summary = next(
            (
                item
                for item in self.scope_day_type_summaries
                if str(item.get("serviceId") or "").strip() == current_service_id
            ),
            None,
        )
        if current_day_summary is not None:
            self.log_line(
                "運行種別を切替: "
                f"{self._current_day_type_label()} "
                f"(families={int(current_day_summary.get('familyCount') or 0)}, "
                f"routes={int(current_day_summary.get('routeCount') or 0)}, "
                f"trips={int(current_day_summary.get('tripCount') or 0)}, "
                f"{_scope_variant_mix_text(current_day_summary, metric='trips')})"
            )

    def _refresh_depot_dropdowns(self, depots: list[dict[str, Any]]) -> None:
        depot_ids = [str(d.get("id") or "").strip() for d in depots if str(d.get("id") or "").strip()]
        if self._widget_exists(self.fleet_depot_combo):
            self.fleet_depot_combo.configure(values=depot_ids)
        if self._widget_exists(self.dup_target_depot_combo):
            self.dup_target_depot_combo.configure(values=depot_ids)
        if self.fleet_depot_var is not None:
            if depot_ids and self.fleet_depot_var.get().strip() not in depot_ids:
                self.fleet_depot_var.set(depot_ids[0])
        if self.dup_target_depot_var is not None:
            if self.dup_target_depot_var.get().strip() not in depot_ids:
                self.dup_target_depot_var.set("")

    def on_connect(self) -> None:
        self.client.set_direct_mode(self.run_transport_var.get().strip() != "HTTP互換")
        self.client.set_base_url(self.base_url_var.get().strip())

        def action() -> dict[str, Any]:
            prefix = self.client.detect_api_prefix()
            context = self.client.get_app_context()
            datasets = self.client.get_app_datasets()
            return {"prefix": prefix, "context": context, "datasets": datasets}

        def done(resp: dict[str, Any]) -> None:
            shown = resp.get("prefix") or "(なし)"
            self.log_line(f"接続成功: {self.client.base_url} / API prefix = {shown}")
            self.log_line("App context: " + json.dumps(resp.get("context", {}), ensure_ascii=False))
            self._apply_dataset_options(resp.get("datasets") or {})
            self.refresh_scenarios()

        self.run_bg(action, done)

    def _on_transport_mode_changed(self) -> None:
        use_http = self.run_transport_var.get().strip() == "HTTP互換"
        self.client.set_direct_mode(not use_http)
        if self._widget_exists(self.base_url_label):
            if use_http:
                self.base_url_label.pack(side=tk.LEFT)
            else:
                self.base_url_label.pack_forget()
        if self._widget_exists(self.base_url_entry):
            if use_http:
                self.base_url_entry.pack(side=tk.LEFT, padx=6)
            else:
                self.base_url_entry.pack_forget()

    def _apply_dataset_options(self, datasets_resp: dict[str, Any]) -> None:
        selected = _choose_dataset_options(datasets_resp)
        self.available_dataset_ids = list(selected.get("visibleIds") or [])
        self.default_dataset_id = str(selected.get("defaultDatasetId") or "tokyu_full").strip() or "tokyu_full"
        self.dataset_combo["values"] = self.available_dataset_ids
        if not self.dataset_id_var.get().strip() or self.dataset_id_var.get().strip() not in self.available_dataset_ids:
            self.dataset_id_var.set(self.default_dataset_id)
        hidden_ids = [str(item).strip() for item in (selected.get("hiddenIds") or []) if str(item).strip()]
        if hidden_ids:
            self.log_line("runtime 未整備 dataset を候補から除外: " + ", ".join(hidden_ids))
        elif datasets_resp.get("items") and not selected.get("usedRuntimeReadyOnly"):
            self.log_line("runtimeReady dataset が見つからないため全 dataset 候補を表示します")
        self.log_line(f"dataset候補取得: {len(self.available_dataset_ids)} 件 (default={self.default_dataset_id})")

    def refresh_scenarios(self) -> None:
        def action() -> dict[str, Any]:
            return self.client.list_scenarios()

        def done(resp: dict[str, Any]) -> None:
            self.scenarios = list(resp.get("items") or [])
            labels = [f"{i.get('name', '(名称なし)')} [{i.get('id', '')}]" for i in self.scenarios]
            for combo in (self.scenario_combo, self.compare_a_combo, self.compare_b_combo):
                combo["values"] = labels
            if labels:
                self.scenario_combo.current(0)
                self.on_scenario_changed()
                if not self.compare_scenario_a_var.get():
                    self.compare_a_combo.current(0)
                if len(labels) > 1 and not self.compare_scenario_b_var.get():
                    self.compare_b_combo.current(1)
                elif len(labels) == 1 and not self.compare_scenario_b_var.get():
                    self.compare_b_combo.current(0)
            self.log_line(f"シナリオ取得: {len(self.scenarios)} 件")

        self.run_bg(action, done)

    @staticmethod
    def _extract_id_from_label(label: str) -> str:
        text = str(label or "").strip()
        if not text:
            return ""
        if "[" not in text or "]" not in text:
            return ""
        return text.rsplit("[", 1)[-1].rstrip("]").strip()

    def _compare_ids(self) -> tuple[str, str]:
        scenario_a = self._extract_id_from_label(self.compare_scenario_a_var.get())
        scenario_b = self._extract_id_from_label(self.compare_scenario_b_var.get())
        return scenario_a, scenario_b

    @staticmethod
    def _pick_number(*values: Any) -> float | None:
        for value in values:
            if value is None:
                continue
            try:
                return float(value)
            except Exception:
                continue
        return None

    @staticmethod
    def _pick_text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _extract_result_summary(self, resp: dict[str, Any]) -> dict[str, Any]:
        solver_result = dict(resp.get("solver_result") or {})
        kpi = dict(resp.get("kpi") or {})
        run_summary = dict(resp.get("summary") or {})
        costs = dict(resp.get("cost_breakdown") or {})
        simulation_summary = dict(resp.get("simulation_summary") or {})
        summary = {
            "status": self._pick_text(resp.get("status"), solver_result.get("status"), "unknown"),
            "mode": self._pick_text(resp.get("mode"), resp.get("solver_mode"), solver_result.get("mode")),
            "total_cost": self._pick_number(
                costs.get("total_cost"),
                costs.get("total_cost_with_assets"),
                resp.get("objective_value"),
                solver_result.get("objective_value"),
            ),
            "objective": self._pick_number(resp.get("objective_value"), solver_result.get("objective_value")),
            "served_trips": self._pick_number(
                run_summary.get("trip_count_served"),
                kpi.get("served_trips"),
                resp.get("served_trips"),
            ),
            "unserved_trips": self._pick_number(
                run_summary.get("trip_count_unserved"),
                kpi.get("unmet_trips"),
                resp.get("unmet_trips"),
            ),
            "vehicle_count_used": self._pick_number(
                run_summary.get("vehicle_count_used"),
                kpi.get("vehicle_count_used"),
            ),
            "solve_time_seconds": self._pick_number(
                solver_result.get("solve_time_seconds"),
                kpi.get("solve_time_sec"),
                resp.get("solve_time_seconds"),
            ),
            "energy_cost": self._pick_number(
                costs.get("total_energy_cost"),
                costs.get("electricity_cost_final"),
                costs.get("energy_cost"),
                resp.get("total_energy_cost"),
            ),
            "electricity_cost_final": self._pick_number(
                costs.get("electricity_cost_final"),
                costs.get("energy_cost"),
                simulation_summary.get("total_energy_cost"),
            ),
            "vehicle_cost": self._pick_number(
                costs.get("vehicle_cost"),
                costs.get("vehicle_fixed_cost"),
            ),
            "driver_cost": self._pick_number(costs.get("driver_cost")),
            "penalty_unserved": self._pick_number(costs.get("penalty_unserved")),
            "electricity_cost_provisional_leftover": self._pick_number(
                costs.get("electricity_cost_provisional_leftover"),
                simulation_summary.get("electricity_cost_provisional_leftover_jpy"),
                self._pick_number(
                    simulation_summary.get("electricity_cost_provisional_jpy"),
                    costs.get("electricity_cost_provisional"),
                )
                - self._pick_number(
                    simulation_summary.get("electricity_cost_charged_jpy"),
                    costs.get("electricity_cost_charged"),
                    costs.get("electricity_cost_final"),
                )
                if self._pick_number(
                    simulation_summary.get("electricity_cost_provisional_jpy"),
                    costs.get("electricity_cost_provisional"),
                ) is not None
                and self._pick_number(
                    simulation_summary.get("electricity_cost_charged_jpy"),
                    costs.get("electricity_cost_charged"),
                    costs.get("electricity_cost_final"),
                ) is not None
                else None,
            ),
            "fuel_cost": self._pick_number(
                costs.get("total_fuel_cost"),
                costs.get("fuel_cost"),
                resp.get("total_fuel_cost"),
            ),
            "demand_charge": self._pick_number(
                costs.get("total_demand_charge"),
                costs.get("demand_charge"),
                resp.get("total_demand_charge"),
            ),
            "battery_degradation_cost": self._pick_number(
                costs.get("total_degradation_cost"),
                costs.get("battery_degradation_cost"),
                costs.get("degradation_cost"),
                resp.get("total_degradation_cost"),
            ),
            "total_co2_kg": self._pick_number(
                costs.get("total_co2_kg"),
                resp.get("total_co2_kg"),
                (resp.get("simulation_summary") or {}).get("total_co2_kg"),
            ),
            "co2_cost": self._pick_number(
                costs.get("co2_cost"),
                resp.get("co2_cost"),
            ),
        }
        return summary

    def _open_kv_window(self, title: str, data: dict[str, Any]) -> None:
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("980x680")
        notebook = ttk.Notebook(win)
        notebook.pack(fill=tk.BOTH, expand=True)

        summary_tab = ttk.Frame(notebook, padding=6)
        cost_tab = ttk.Frame(notebook, padding=6)
        details_tab = ttk.Frame(notebook, padding=6)
        raw_tab = ttk.Frame(notebook, padding=6)
        notebook.add(summary_tab, text="Summary")
        notebook.add(cost_tab, text="Cost Breakdown")
        notebook.add(details_tab, text="Details")
        notebook.add(raw_tab, text="Raw JSON")

        summary = self._extract_result_summary(data)
        cost_rows = _ordered_cost_breakdown_items(data.get("cost_breakdown") or {})
        non_zero_cost_rows = [row for row in cost_rows if row.get("non_zero")]

        ttk.Label(
            summary_tab,
            text=(
                f"主要KPIと内訳を表示します。非ゼロ内訳 {len(non_zero_cost_rows)} 件"
                if non_zero_cost_rows
                else "主要KPIと内訳を表示します。"
            ),
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))

        summary_tree = ttk.Treeview(summary_tab, columns=("item", "value"), show="headings")
        summary_tree.heading("item", text="項目")
        summary_tree.heading("value", text="value")
        summary_tree.column("item", width=320, anchor="w")
        summary_tree.column("value", width=580, anchor="w")
        summary_tree.tag_configure("nonzero", background="#fff4cf")
        summary_tree.pack(fill=tk.BOTH, expand=True)

        for key, value in summary.items():
            if value is None or value == "":
                continue
            tags = ()
            numeric = _result_numeric(value)
            if key in {"total_cost", "energy_cost", "vehicle_cost", "driver_cost", "penalty_unserved"} and numeric is not None and abs(numeric) > 1e-9:
                tags = ("nonzero",)
            summary_tree.insert(
                "",
                tk.END,
                values=(_result_metric_label(key), _format_result_value(value)),
                tags=tags,
            )

        ttk.Label(
            cost_tab,
            text="総コストを先頭に、非ゼロの内訳を上段へ並べています。",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))
        cost_tree = ttk.Treeview(cost_tab, columns=("item", "key", "value", "share"), show="headings")
        cost_tree.heading("item", text="項目")
        cost_tree.heading("key", text="key")
        cost_tree.heading("value", text="value")
        cost_tree.heading("share", text="share")
        cost_tree.column("item", width=260, anchor="w")
        cost_tree.column("key", width=220, anchor="w")
        cost_tree.column("value", width=220, anchor="e")
        cost_tree.column("share", width=120, anchor="e")
        cost_tree.tag_configure("nonzero", background="#fff4cf")
        cost_tree.pack(fill=tk.BOTH, expand=True)

        for row in cost_rows:
            share_text = ""
            share = row.get("share")
            if isinstance(share, float):
                share_text = f"{share * 100:.1f}%"
            cost_tree.insert(
                "",
                tk.END,
                values=(
                    row["label"],
                    row["key"],
                    _format_result_value(row.get("value")),
                    share_text,
                ),
                tags=("nonzero",) if row.get("non_zero") else (),
            )

        detail_tree = ttk.Treeview(details_tab, columns=("section", "key", "value"), show="headings")
        detail_tree.heading("section", text="section")
        detail_tree.heading("key", text="key")
        detail_tree.heading("value", text="value")
        detail_tree.column("section", width=160, anchor="w")
        detail_tree.column("key", width=220, anchor="w")
        detail_tree.column("value", width=420, anchor="w")
        detail_tree.pack(fill=tk.BOTH, expand=True)

        for section in ("summary", "kpi", "cost_breakdown", "solver_result"):
            block = data.get(section)
            if isinstance(block, dict):
                entries = (
                    [(row["key"], row.get("value")) for row in cost_rows]
                    if section == "cost_breakdown"
                    else list(block.items())
                )
                for key, value in entries:
                    if isinstance(value, (dict, list, tuple)):
                        shown = json.dumps(value, ensure_ascii=False, default=str)
                    else:
                        shown = _format_result_value(value)
                    detail_tree.insert("", tk.END, values=(section, key, shown))

        raw = ScrolledText(raw_tab)
        raw.pack(fill=tk.BOTH, expand=True)
        raw.insert(tk.END, json.dumps(data, ensure_ascii=False, indent=2, default=str))
        raw.configure(state="disabled")

    def _open_compare_window(self, title: str, scenario_a: str, scenario_b: str, a_data: dict[str, Any], b_data: dict[str, Any]) -> None:
        a_summary = self._extract_result_summary(a_data)
        b_summary = self._extract_result_summary(b_data)

        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("980x620")

        tree = ttk.Treeview(win, columns=("metric", "scenario_a", "scenario_b", "delta"), show="headings")
        tree.heading("metric", text="metric")
        tree.heading("scenario_a", text=f"A: {scenario_a}")
        tree.heading("scenario_b", text=f"B: {scenario_b}")
        tree.heading("delta", text="delta(B-A)")
        tree.column("metric", width=260, anchor="w")
        tree.column("scenario_a", width=230, anchor="w")
        tree.column("scenario_b", width=230, anchor="w")
        tree.column("delta", width=220, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True)

        for key in _RESULT_COMPARE_KEYS:
            av = a_summary.get(key)
            bv = b_summary.get(key)
            delta: Any = ""
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                delta = _format_result_value(float(bv) - float(av))
            tree.insert(
                "",
                tk.END,
                values=(
                    _result_metric_label(key),
                    _format_result_value(av),
                    _format_result_value(bv),
                    delta,
                ),
            )

    def compare_optimization_results(self) -> None:
        scenario_a, scenario_b = self._compare_ids()
        if not scenario_a or not scenario_b:
            messagebox.showwarning("入力不足", "比較する2つのシナリオを選択してください")
            return

        def action() -> dict[str, Any]:
            return {
                "a": self.client.get_optimization_result(scenario_a),
                "b": self.client.get_optimization_result(scenario_b),
            }

        def done(resp: dict[str, Any]) -> None:
            self._open_compare_window("Optimization Compare", scenario_a, scenario_b, resp.get("a") or {}, resp.get("b") or {})
            self.log_line(f"Optimization比較を表示: A={scenario_a}, B={scenario_b}")

        self.run_bg(action, done)

    def compare_simulation_results(self) -> None:
        scenario_a, scenario_b = self._compare_ids()
        if not scenario_a or not scenario_b:
            messagebox.showwarning("入力不足", "比較する2つのシナリオを選択してください")
            return

        def action() -> dict[str, Any]:
            return {
                "a": self.client.get_simulation_result(scenario_a),
                "b": self.client.get_simulation_result(scenario_b),
            }

        def done(resp: dict[str, Any]) -> None:
            self._open_compare_window("Simulation Compare", scenario_a, scenario_b, resp.get("a") or {}, resp.get("b") or {})
            self.log_line(f"Simulation比較を表示: A={scenario_a}, B={scenario_b}")

        self.run_bg(action, done)

    def on_scenario_changed(self, _event=None) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        self._clear_prepared_state()
        self.load_quick_setup()
        if self._fleet_window_ready():
            self.refresh_templates()
            self.refresh_vehicles()
        self.log_line(f"シナリオ選択完了: {scenario_id}")
        if _event is not None:
            messagebox.showinfo("シナリオ選択", f"シナリオ選択完了\n{scenario_id}")

    def create_scenario(self) -> None:
        name = self.new_name_var.get().strip()
        if not name:
            messagebox.showwarning("入力不足", "シナリオ名を入力してください")
            return
        dataset_id = self.dataset_id_var.get().strip() or self.default_dataset_id or "tokyu_full"
        if self.available_dataset_ids and dataset_id not in self.available_dataset_ids:
            messagebox.showwarning("入力エラー", f"datasetId が無効です: {dataset_id}\n候補: {', '.join(self.available_dataset_ids)}")
            return
        random_seed = self._parse_int(self.random_seed_var.get(), 42)

        def action() -> dict[str, Any]:
            return self.client.create_scenario(name, "backup console", dataset_id, random_seed)

        def done(resp: dict[str, Any]) -> None:
            scenario_id = str(resp.get("id") or "").strip()
            effective_dataset_id = str(resp.get("datasetId") or "").strip()
            if effective_dataset_id and effective_dataset_id != dataset_id:
                self.log_line(
                    f"シナリオ作成: {name} [{scenario_id}] "
                    f"(requested={dataset_id}, effective={effective_dataset_id})"
                )
            elif effective_dataset_id:
                self.log_line(f"シナリオ作成: {name} [{scenario_id}] (dataset={effective_dataset_id})")
            else:
                self.log_line(f"シナリオ作成: {name} [{scenario_id}]")
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
            dispatch_scope = dict(resp.get("dispatchScope") or {})
            selected_day_type = str(dispatch_scope.get("dayType") or "WEEKDAY")
            self._suspend_prepare_watchers = True
            self._set_day_type_options_from_payload(
                list(resp.get("availableDayTypes") or [])
            )
            self._set_day_type_summaries(list(resp.get("dayTypeSummaries") or []))
            self._set_day_type_value(selected_day_type)
            if str(dispatch_scope.get("routeSelectionMode") or "") == "include":
                expanded_routes = _expand_selected_routes_to_family_members(routes, selected_routes)
                if len(expanded_routes) != len(selected_routes):
                    self.log_line(
                        "系統単位の初期選択へ展開: "
                        f"{len(selected_routes)} -> {len(expanded_routes)} routes"
                    )
                selected_routes = expanded_routes
            self._set_scope_data(depots, routes, selected_depots, selected_routes)

            trip = dict(dispatch_scope.get("tripSelection") or {})
            self.include_short_turn_var.set(bool(trip.get("includeShortTurn", True)))
            self.include_depot_moves_var.set(bool(trip.get("includeDepotMoves", True)))
            self.include_deadhead_var.set(bool(trip.get("includeDeadhead", True)))
            self._suspend_route_lock_sync = True
            self.allow_intra_var.set(bool(dispatch_scope.get("allowIntraDepotRouteSwap", False)))
            self.allow_inter_var.set(bool(dispatch_scope.get("allowInterDepotSwap", False)))
            self.fixed_route_band_mode_var.set(bool(dispatch_scope.get("fixedRouteBandMode", True)))
            self._suspend_route_lock_sync = False

            solver = dict(resp.get("solverSettings") or {})
            sim = dict(resp.get("simulationSettings") or {})
            self.service_date_var.set(str(sim.get("serviceDate") or ""))
            planning_days = sim.get("planningDays")
            if planning_days is None:
                service_dates = list(sim.get("serviceDates") or [])
                planning_days = len(service_dates) if service_dates else 1
            self.planning_days_var.set(str(planning_days or 1))
            self.operation_start_time_var.set(str(sim.get("startTime") or "05:00"))
            self.operation_end_time_var.set(str(sim.get("endTime") or "23:00"))
            self.solver_mode_var.set(str(solver.get("solverMode") or "hybrid"))
            self.objective_mode_var.set(
                normalize_objective_mode(solver.get("objectiveMode") or "total_cost")
            )
            self.time_limit_var.set(str(solver.get("timeLimitSeconds") or 300))
            self.mip_gap_var.set(str(solver.get("mipGap") if solver.get("mipGap") is not None else 0.01))
            self.alns_iter_var.set(str(solver.get("alnsIterations") or 500))
            self.no_improvement_limit_var.set(str(solver.get("noImprovementLimit") or 100))
            self.destroy_fraction_var.set(str(solver.get("destroyFraction") if solver.get("destroyFraction") is not None else 0.25))
            self.random_seed_var.set(str(solver.get("randomSeed") or 42))
            self.objective_preset_var.set(str(solver.get("objectivePreset") or sim.get("objectivePreset") or "cost"))
            self.max_start_fragments_var.set(str(solver.get("maxStartFragmentsPerVehicle") or 100))
            self.max_end_fragments_var.set(str(solver.get("maxEndFragmentsPerVehicle") or 100))
            self.enable_vehicle_diagram_output_var.set(bool(solver.get("enableVehicleDiagramOutput", True)))
            self.allow_partial_service_var.set(bool(sim.get("allowPartialService", False)))
            self.unserved_penalty_var.set(str(sim.get("unservedPenalty") or 10000))
            self.grid_flat_price_var.set(str(sim.get("gridFlatPricePerKwh") or 30))
            self.grid_sell_price_var.set(str(sim.get("gridSellPricePerKwh") or 0))
            self.demand_charge_var.set(str(sim.get("demandChargeCostPerKw") or 1500))
            self.diesel_price_var.set(str(sim.get("dieselPricePerL") or 145))
            self.grid_co2_var.set(str(sim.get("gridCo2KgPerKwh") or 0))
            self.co2_price_var.set(str(sim.get("co2PricePerKg") or 0))
            self.co2_price_source_var.set(str(sim.get("co2PriceSource") or "manual"))
            self.co2_reference_date_var.set(str(sim.get("co2ReferenceDate") or ""))
            self.ice_co2_kg_per_l_var.set(str(sim.get("iceCo2KgPerL") or 2.64))
            self.degradation_weight_var.set(str(sim.get("degradationWeight") or 0))
            self.depot_power_limit_var.set(str(sim.get("depotPowerLimitKw") or 500))
            self.initial_soc_var.set(str(sim.get("initialSoc") or 0.8))
            self.soc_min_var.set(str(sim.get("socMin") or 0.2))
            self.soc_max_var.set(str(sim.get("socMax") or 0.9))
            self._set_cost_component_flags_from_payload(sim)
            self.initial_soc_percent_var.set(str(sim.get("initialSocPercent") or 0.8))
            self.final_soc_floor_percent_var.set(str(sim.get("finalSocFloorPercent") or 0.2))
            self.final_soc_target_percent_var.set(
                str(sim.get("finalSocTargetPercent") or sim.get("finalSocFloorPercent") or 0.8)
            )
            self.final_soc_target_tolerance_percent_var.set(
                str(sim.get("finalSocTargetTolerancePercent") or 0.0)
            )
            self.initial_ice_fuel_percent_var.set(str(sim.get("initialIceFuelPercent") or 100.0))
            self.min_ice_fuel_percent_var.set(str(sim.get("minIceFuelPercent") or 10.0))
            self.default_ice_tank_capacity_l_var.set(str(sim.get("defaultIceTankCapacityL") or 300.0))
            self.max_ice_fuel_percent_var.set(str(sim.get("maxIceFuelPercent") or 90.0))
            self.deadhead_speed_kmh_var.set(str(sim.get("deadheadSpeedKmh") or 18.0))
            self.pv_profile_id_var.set(str(sim.get("pvProfileId") or ""))
            weather_mode = str(sim.get("weatherMode") or _ACTUAL_DATE_PV_PROFILE_ID)
            if weather_mode and weather_mode not in self.weather_mode_options:
                self.weather_mode_options = [*self.weather_mode_options, weather_mode]
                if self._widget_exists(getattr(self, "weather_mode_combo", None)):
                    self.weather_mode_combo.configure(values=self.weather_mode_options)
            self.weather_mode_var.set(weather_mode)
            self.weather_factor_scalar_var.set(str(sim.get("weatherFactorScalar") or 1.0))
            self.tou_text_var.set(self._format_tou_text(sim.get("touPricing") or []))
            depot_energy_assets = sim.get("depotEnergyAssets")
            if isinstance(depot_energy_assets, list):
                self.depot_energy_assets_json_var.set(
                    json.dumps(depot_energy_assets, ensure_ascii=True, separators=(",", ":"))
                )
            else:
                self.depot_energy_assets_json_var.set("")
            objective_weights_raw, slack_penalty, degradation_weight = _split_saved_objective_weights(
                sim.get("objectiveWeights") or {}
            )
            self.objective_weights_json_var.set(
                json.dumps(objective_weights_raw, ensure_ascii=True, separators=(",", ":"))
                if objective_weights_raw
                else ""
            )
            self.contract_penalty_coeff_var.set(str(slack_penalty if slack_penalty is not None else 1000000.0))
            if degradation_weight is not None:
                self.degradation_weight_var.set(str(degradation_weight))
            if self.fixed_route_band_mode_var.get() and not self.enable_vehicle_diagram_output_var.get():
                self.enable_vehicle_diagram_output_var.set(True)
            self._suspend_prepare_watchers = False

            self._refresh_depot_dropdowns(depots)
            if resp.get("routeMetadataRepaired"):
                self.log_line(
                    "[路線分類] 路線メタデータを自動補正しました "
                    f"({len(routes)}件の routeVariantType / routeFamilyCode を最新カタログから再分類)"
                )
            self.log_line(
                "Quick Setup を読み込みました "
                f"(depots={len(depots)}件/{len(selected_depots)}選択, "
                f"routes={len(routes)}件/{len(selected_routes)}選択)"
            )
            current_day_summary = next(
                (
                    item
                    for item in self.scope_day_type_summaries
                    if str(item.get("serviceId") or "").strip() == selected_day_type
                ),
                None,
            )
            if current_day_summary is not None:
                self.log_line(
                    "運行種別サマリ: "
                    f"{self._current_day_type_label()} "
                    f"(families={int(current_day_summary.get('familyCount') or 0)}, "
                    f"routes={int(current_day_summary.get('routeCount') or 0)}, "
                    f"trips={int(current_day_summary.get('tripCount') or 0)}, "
                    f"{_scope_variant_mix_text(current_day_summary, metric='trips')})"
                )
            if routes:
                self.log_line(
                    "路線一覧の表示母集団は固定し、選択中の運行種別に応じて便数表示だけを切り替えています。"
                )
            if (depots and not selected_depots) or (routes and not selected_routes):
                self.log_line(
                    "営業所または路線の選択が空です。stale な保存選択が runtime 補正で外れた可能性があります。"
                    "Quick Setup で選び直してから Prepare を実行してください。"
                )

        self.run_bg(action, done)

    def save_quick_setup(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        synced_assets = self._sync_pv_assets_for_selected_depots(announce=False)
        if synced_assets is None:
            return
        fixed_route_band_mode = self.fixed_route_band_mode_var.get()
        allow_intra_depot_swap = (
            False if fixed_route_band_mode else self.allow_intra_var.get()
        )
        objective_weights = _compose_saved_objective_weights(
            self._parse_objective_weights_json(),
            slack_penalty=self._parse_float(self.contract_penalty_coeff_var.get(), 1000000.0),
            degradation_weight=self._parse_float(self.degradation_weight_var.get(), 0.0),
        )
        service_dates = self._selected_service_dates(announce=True)
        if service_dates is None:
            return
        if not service_dates:
            messagebox.showwarning("入力不足", "Quick Setup 保存前に運行日を入力してください")
            return
        planning_days = self._planning_days_value()

        payload = {
            "selectedDepotIds": self._selected_depot_ids(),
            "selectedRouteIds": self._selected_route_ids(),
            "dayType": self.day_type_var.get().strip(),
            "serviceDate": self.service_date_var.get().strip() or None,
            "planningDays": planning_days,
            "serviceDates": service_dates,
            "includeShortTurn": self.include_short_turn_var.get(),
            "includeDepotMoves": self.include_depot_moves_var.get(),
            "includeDeadhead": self.include_deadhead_var.get(),
            "allowIntraDepotRouteSwap": allow_intra_depot_swap,
            "allowInterDepotSwap": self.allow_inter_var.get(),
            "fixedRouteBandMode": fixed_route_band_mode,
            "solverMode": self.solver_mode_var.get().strip(),
            "objectiveMode": self.objective_mode_var.get().strip(),
            "objectivePreset": self.objective_preset_var.get().strip() or "cost",
            "timeLimitSeconds": self._parse_int(self.time_limit_var.get(), 300),
            "mipGap": self._parse_float(self.mip_gap_var.get(), 0.01),
            "alnsIterations": self._parse_int(self.alns_iter_var.get(), 500),
            "noImprovementLimit": self._parse_int(self.no_improvement_limit_var.get(), 100),
            "destroyFraction": self._parse_float(self.destroy_fraction_var.get(), 0.25),
            "maxStartFragmentsPerVehicle": self._parse_int(self.max_start_fragments_var.get(), 100),
            "maxEndFragmentsPerVehicle": self._parse_int(self.max_end_fragments_var.get(), 100),
            "enableVehicleDiagramOutput": self.enable_vehicle_diagram_output_var.get(),
            "allowPartialService": self.allow_partial_service_var.get(),
            "unservedPenalty": self._parse_float(self.unserved_penalty_var.get(), 10000.0),
            "initialSoc": self._parse_float(self.initial_soc_var.get(), 0.8),
            "socMin": self._parse_float(self.soc_min_var.get(), 0.2),
            "socMax": self._parse_float(self.soc_max_var.get(), 0.9),
            "costComponentFlags": self._cost_component_flags_payload(),
            "gridFlatPricePerKwh": self._parse_float(self.grid_flat_price_var.get(), 0.0),
            "gridSellPricePerKwh": self._parse_float(self.grid_sell_price_var.get(), 0.0),
            "demandChargeCostPerKw": self._parse_float(self.demand_charge_var.get(), 0.0),
            "dieselPricePerL": self._parse_float(self.diesel_price_var.get(), 145.0),
            "gridCo2KgPerKwh": self._parse_float(self.grid_co2_var.get(), 0.0),
            "co2PricePerKg": self._parse_float(self.co2_price_var.get(), 0.0),
            "touPricing": self._parse_tou_text(),
            "co2PriceSource": self.co2_price_source_var.get().strip() or "manual",
            "co2ReferenceDate": self.co2_reference_date_var.get().strip() or None,
            "iceCo2KgPerL": self._parse_float(self.ice_co2_kg_per_l_var.get(), 2.64),
            "depotPowerLimitKw": self._parse_float(self.depot_power_limit_var.get(), 500.0),
            "degradationWeight": self._parse_float(self.degradation_weight_var.get(), 0.0),
            "initialSocPercent": self._parse_float(self.initial_soc_percent_var.get(), 0.8),
            "finalSocFloorPercent": self._parse_float(self.final_soc_floor_percent_var.get(), 0.2),
            "finalSocTargetPercent": self._parse_float(self.final_soc_target_percent_var.get(), 0.8),
            "finalSocTargetTolerancePercent": self._parse_float(
                self.final_soc_target_tolerance_percent_var.get(),
                0.0,
            ),
            "initialIceFuelPercent": self._parse_float(self.initial_ice_fuel_percent_var.get(), 100.0),
            "minIceFuelPercent": self._parse_float(self.min_ice_fuel_percent_var.get(), 10.0),
            "maxIceFuelPercent": self._parse_float(self.max_ice_fuel_percent_var.get(), 90.0),
            "defaultIceTankCapacityL": self._parse_float(
                self.default_ice_tank_capacity_l_var.get(),
                300.0,
            ),
            "deadheadSpeedKmh": self._parse_float(self.deadhead_speed_kmh_var.get(), 18.0),
            "pvProfileId": self.pv_profile_id_var.get().strip() or None,
            "weatherMode": self.weather_mode_var.get().strip() or _ACTUAL_DATE_PV_PROFILE_ID,
            "weatherFactorScalar": self._parse_float(self.weather_factor_scalar_var.get(), 1.0),
            "objectiveWeights": objective_weights,
            "randomSeed": self._parse_int(self.random_seed_var.get(), 42),
            "startTime": self._normalize_hhmm_text(self.operation_start_time_var.get(), default="05:00"),
            "endTime": self._normalize_hhmm_text(self.operation_end_time_var.get(), default="23:00"),
            "planningHorizonHours": self._planning_horizon_hours_value(planning_days),
        }
        payload["depotEnergyAssets"] = synced_assets
        def _on_save_done(_resp: dict[str, Any]) -> None:
            self.log_line("Quick Setup を保存しました")
            self._mark_prepared_stale("Quick Setup 保存後のため再Prepareが必要です", announce=True)
            self.load_quick_setup()

        self.run_bg(lambda: self.client.put_quick_setup(scenario_id, payload), _on_save_done)

    def refresh_vehicles(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        if not self._vehicle_panel_ready():
            return
        depot_id = self.fleet_depot_var.get().strip() or None

        def done(resp: dict[str, Any]) -> None:
            self.vehicle_rows = list(resp.get("items") or [])
            try:
                if not self._widget_exists(self.vehicle_tree):
                    return
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
            except tk.TclError:
                return
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
            self.v_model_code_var.set(str(v.get("modelCode") or ""))
            self.v_model_var.set(str(v.get("modelName") or ""))
            self.v_cap_var.set(str(v.get("capacityPassengers") or 0))
            self.v_battery_var.set("" if v.get("batteryKwh") is None else str(v.get("batteryKwh")))
            self.v_fuel_tank_var.set("" if v.get("fuelTankL") is None else str(v.get("fuelTankL")))
            self.v_energy_var.set(str(v.get("energyConsumption") or 0.0))
            self.v_km_per_l_var.set("" if v.get("fuelEfficiencyKmPerL") is None else str(v.get("fuelEfficiencyKmPerL")))
            self.v_co2_gpkm_var.set("" if v.get("co2EmissionGPerKm") is None else str(v.get("co2EmissionGPerKm")))
            self.v_curb_weight_var.set("" if v.get("curbWeightKg") is None else str(v.get("curbWeightKg")))
            self.v_gross_weight_var.set("" if v.get("grossVehicleWeightKg") is None else str(v.get("grossVehicleWeightKg")))
            self.v_engine_disp_var.set("" if v.get("engineDisplacementL") is None else str(v.get("engineDisplacementL")))
            self.v_max_torque_var.set("" if v.get("maxTorqueNm") is None else str(v.get("maxTorqueNm")))
            self.v_max_power_var.set("" if v.get("maxPowerKw") is None else str(v.get("maxPowerKw")))
            self.v_charge_kw_var.set("" if v.get("chargePowerKw") is None else str(v.get("chargePowerKw")))
            self.v_min_soc_var.set("" if v.get("minSoc") is None else str(v.get("minSoc")))
            self.v_max_soc_var.set("" if v.get("maxSoc") is None else str(v.get("maxSoc")))
            self.v_acq_cost_var.set(str(v.get("acquisitionCost") or 0.0))
            self.v_enabled_var.set(bool(v.get("enabled", True)))
            self._update_vehicle_form_visibility()

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
            "modelCode": template.get("modelCode"),
            "modelName": str(template.get("modelName") or template.get("name") or "TemplateVehicle"),
            "capacityPassengers": int(template.get("capacityPassengers") or 0),
            "batteryKwh": template.get("batteryKwh"),
            "fuelTankL": template.get("fuelTankL"),
            "energyConsumption": float(template.get("energyConsumption") or 0.0),
            "fuelEfficiencyKmPerL": template.get("fuelEfficiencyKmPerL"),
            "co2EmissionGPerKm": template.get("co2EmissionGPerKm"),
            "curbWeightKg": template.get("curbWeightKg"),
            "grossVehicleWeightKg": template.get("grossVehicleWeightKg"),
            "engineDisplacementL": template.get("engineDisplacementL"),
            "maxTorqueNm": template.get("maxTorqueNm"),
            "maxPowerKw": template.get("maxPowerKw"),
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

    def _current_depot_choices(self) -> list[str]:
        from_scope = [str(d.get("id") or "").strip() for d in self.scope_depots if str(d.get("id") or "").strip()]
        if from_scope:
            return from_scope
        from_combo = [str(x).strip() for x in (self.fleet_depot_combo.cget("values") or ()) if str(x).strip()]
        return from_combo

    def open_vehicle_create_window(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        win = tk.Toplevel(self.root)
        win.title("車両追加")
        win.geometry("620x700")

        depot_choices = self._current_depot_choices()
        depot_var = tk.StringVar(value=(self.fleet_depot_var.get().strip() or (depot_choices[0] if depot_choices else "")))
        qty_var = tk.StringVar(value="1")
        type_var = tk.StringVar(value="BEV")
        model_code_var = tk.StringVar(value="")
        model_name_var = tk.StringVar(value="")
        cap_var = tk.StringVar(value="0")
        energy_var = tk.StringVar(value="1.2")
        acq_var = tk.StringVar(value="0")
        enabled_var = tk.BooleanVar(value=True)
        battery_var = tk.StringVar(value="300")
        charge_var = tk.StringVar(value="90")
        min_soc_var = tk.StringVar(value="")
        max_soc_var = tk.StringVar(value="")
        fuel_tank_var = tk.StringVar(value="")
        kmpl_var = tk.StringVar(value="")
        co2_var = tk.StringVar(value="")
        engine_var = tk.StringVar(value="")

        base = ttk.LabelFrame(win, text="基本情報", padding=8)
        base.pack(fill=tk.X, padx=10, pady=(10, 6))
        depot_row = ttk.Frame(base)
        depot_row.pack(fill=tk.X, pady=2)
        ttk.Label(depot_row, text="営業所", width=20).pack(side=tk.LEFT)
        depot_combo = ttk.Combobox(depot_row, textvariable=depot_var, state="readonly", values=depot_choices)
        depot_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._labeled_entry(base, "追加台数", qty_var)
        type_row = ttk.Frame(base)
        type_row.pack(fill=tk.X, pady=2)
        ttk.Label(type_row, text="車種", width=20).pack(side=tk.LEFT)
        type_combo = ttk.Combobox(type_row, textvariable=type_var, state="readonly", values=["BEV", "ICE"])
        type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._labeled_entry(base, "モデルコード", model_code_var)
        self._labeled_entry(base, "車両名", model_name_var)
        self._labeled_entry(base, "定員(人)", cap_var)
        self._labeled_entry(base, "消費係数", energy_var)
        self._labeled_entry(base, "導入費(円)", acq_var)
        ttk.Checkbutton(base, text="有効", variable=enabled_var).pack(anchor="w")

        ev_box = ttk.LabelFrame(win, text="EV専用", padding=8)
        ev_box.pack(fill=tk.X, padx=10, pady=4)
        self._labeled_entry(ev_box, "電池容量(kWh)", battery_var)
        self._labeled_entry(ev_box, "充電出力(kW)", charge_var)
        self._labeled_entry(ev_box, "最小SOC(0-1)", min_soc_var)
        self._labeled_entry(ev_box, "最大SOC(0-1)", max_soc_var)

        ice_box = ttk.LabelFrame(win, text="エンジン車専用", padding=8)
        ice_box.pack(fill=tk.X, padx=10, pady=4)
        self._labeled_entry(ice_box, "燃料タンク(L)", fuel_tank_var)
        self._labeled_entry(ice_box, "燃費(km/L)", kmpl_var)
        self._labeled_entry(ice_box, "CO2排出(g/km)", co2_var)
        self._labeled_entry(ice_box, "排気量(L)", engine_var)

        def refresh_type(_event=None) -> None:
            if type_var.get().strip().upper() == "BEV":
                ev_box.pack(fill=tk.X, padx=10, pady=4)
                ice_box.pack_forget()
            else:
                ice_box.pack(fill=tk.X, padx=10, pady=4)
                ev_box.pack_forget()

        type_combo.bind("<<ComboboxSelected>>", refresh_type)
        refresh_type()

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=10)

        def submit() -> None:
            depot_id = depot_var.get().strip()
            if not depot_id:
                messagebox.showwarning("入力不足", "営業所を選択してください")
                return
            qty = max(1, self._parse_int(qty_var.get(), 1))
            payload = self._normalize_powertrain_payload(
                {
                    "depotId": depot_id,
                    "type": type_var.get().strip().upper() or "BEV",
                    "modelCode": model_code_var.get().strip() or None,
                    "modelName": model_name_var.get().strip() or "NewVehicle",
                    "capacityPassengers": self._parse_int(cap_var.get(), 0),
                    "batteryKwh": self._parse_optional_float(battery_var.get()),
                    "fuelTankL": self._parse_optional_float(fuel_tank_var.get()),
                    "energyConsumption": self._parse_float(energy_var.get(), 0.0),
                    "fuelEfficiencyKmPerL": self._parse_optional_float(kmpl_var.get()),
                    "co2EmissionGPerKm": self._parse_optional_float(co2_var.get()),
                    "engineDisplacementL": self._parse_optional_float(engine_var.get()),
                    "chargePowerKw": self._parse_optional_float(charge_var.get()),
                    "minSoc": self._parse_optional_float(min_soc_var.get()),
                    "maxSoc": self._parse_optional_float(max_soc_var.get()),
                    "acquisitionCost": self._parse_float(acq_var.get(), 0.0),
                    "enabled": bool(enabled_var.get()),
                }
            )

            def action() -> dict[str, Any]:
                if qty == 1:
                    self.client.create_vehicle(scenario_id, payload)
                    return {"total": 1}
                batch = dict(payload)
                batch["quantity"] = qty
                return self.client.create_vehicle_batch(scenario_id, batch)

            def done(resp: dict[str, Any]) -> None:
                self.log_line(f"車両を追加: {depot_id} x {resp.get('total') or qty}")
                self.fleet_depot_var.set(depot_id)
                self.refresh_vehicles()
                win.destroy()

            self.run_bg(action, done)

        ttk.Button(btns, text="追加", command=submit).pack(side=tk.RIGHT)
        ttk.Button(btns, text="キャンセル", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    def open_template_create_window(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        win = tk.Toplevel(self.root)
        win.title("テンプレート追加")
        win.geometry("620x760")

        depot_choices = self._current_depot_choices()
        name_var = tk.StringVar(value="")
        type_var = tk.StringVar(value="BEV")
        model_code_var = tk.StringVar(value="")
        model_name_var = tk.StringVar(value="")
        cap_var = tk.StringVar(value="0")
        energy_var = tk.StringVar(value="1.2")
        acq_var = tk.StringVar(value="0")
        enabled_var = tk.BooleanVar(value=True)
        battery_var = tk.StringVar(value="300")
        charge_var = tk.StringVar(value="90")
        min_soc_var = tk.StringVar(value="")
        max_soc_var = tk.StringVar(value="")
        fuel_tank_var = tk.StringVar(value="")
        kmpl_var = tk.StringVar(value="")
        co2_var = tk.StringVar(value="")
        engine_var = tk.StringVar(value="")
        apply_now_var = tk.BooleanVar(value=False)
        apply_depot_var = tk.StringVar(value=(self.fleet_depot_var.get().strip() or (depot_choices[0] if depot_choices else "")))
        apply_qty_var = tk.StringVar(value="1")

        base = ttk.LabelFrame(win, text="テンプレート基本情報", padding=8)
        base.pack(fill=tk.X, padx=10, pady=(10, 6))
        self._labeled_entry(base, "名称", name_var)
        type_row = ttk.Frame(base)
        type_row.pack(fill=tk.X, pady=2)
        ttk.Label(type_row, text="車種", width=20).pack(side=tk.LEFT)
        type_combo = ttk.Combobox(type_row, textvariable=type_var, state="readonly", values=["BEV", "ICE"])
        type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._labeled_entry(base, "モデルコード", model_code_var)
        self._labeled_entry(base, "車両名", model_name_var)
        self._labeled_entry(base, "定員(人)", cap_var)
        self._labeled_entry(base, "消費係数", energy_var)
        self._labeled_entry(base, "導入費(円)", acq_var)
        ttk.Checkbutton(base, text="有効", variable=enabled_var).pack(anchor="w")

        ev_box = ttk.LabelFrame(win, text="EV専用", padding=8)
        ev_box.pack(fill=tk.X, padx=10, pady=4)
        self._labeled_entry(ev_box, "電池容量(kWh)", battery_var)
        self._labeled_entry(ev_box, "充電出力(kW)", charge_var)
        self._labeled_entry(ev_box, "最小SOC(0-1)", min_soc_var)
        self._labeled_entry(ev_box, "最大SOC(0-1)", max_soc_var)

        ice_box = ttk.LabelFrame(win, text="エンジン車専用", padding=8)
        ice_box.pack(fill=tk.X, padx=10, pady=4)
        self._labeled_entry(ice_box, "燃料タンク(L)", fuel_tank_var)
        self._labeled_entry(ice_box, "燃費(km/L)", kmpl_var)
        self._labeled_entry(ice_box, "CO2排出(g/km)", co2_var)
        self._labeled_entry(ice_box, "排気量(L)", engine_var)

        apply_box = ttk.LabelFrame(win, text="作成後に営業所へ車両追加（任意）", padding=8)
        apply_box.pack(fill=tk.X, padx=10, pady=(6, 4))
        ttk.Checkbutton(apply_box, text="作成直後に追加する", variable=apply_now_var).pack(anchor="w")
        dep_row = ttk.Frame(apply_box)
        dep_row.pack(fill=tk.X, pady=2)
        ttk.Label(dep_row, text="営業所", width=20).pack(side=tk.LEFT)
        dep_combo = ttk.Combobox(dep_row, textvariable=apply_depot_var, state="readonly", values=depot_choices)
        dep_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._labeled_entry(apply_box, "追加台数", apply_qty_var)

        def refresh_type(_event=None) -> None:
            if type_var.get().strip().upper() == "BEV":
                ev_box.pack(fill=tk.X, padx=10, pady=4)
                ice_box.pack_forget()
            else:
                ice_box.pack(fill=tk.X, padx=10, pady=4)
                ev_box.pack_forget()

        type_combo.bind("<<ComboboxSelected>>", refresh_type)
        refresh_type()

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=10)

        def submit() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("入力不足", "テンプレート名を入力してください")
                return
            template_payload = self._normalize_powertrain_payload(
                {
                    "name": name,
                    "type": type_var.get().strip().upper() or "BEV",
                    "modelCode": model_code_var.get().strip() or None,
                    "modelName": model_name_var.get().strip() or name,
                    "capacityPassengers": self._parse_int(cap_var.get(), 0),
                    "batteryKwh": self._parse_optional_float(battery_var.get()),
                    "fuelTankL": self._parse_optional_float(fuel_tank_var.get()),
                    "energyConsumption": self._parse_float(energy_var.get(), 0.0),
                    "fuelEfficiencyKmPerL": self._parse_optional_float(kmpl_var.get()),
                    "co2EmissionGPerKm": self._parse_optional_float(co2_var.get()),
                    "engineDisplacementL": self._parse_optional_float(engine_var.get()),
                    "chargePowerKw": self._parse_optional_float(charge_var.get()),
                    "minSoc": self._parse_optional_float(min_soc_var.get()),
                    "maxSoc": self._parse_optional_float(max_soc_var.get()),
                    "acquisitionCost": self._parse_float(acq_var.get(), 0.0),
                    "enabled": bool(enabled_var.get()),
                }
            )

            apply_now = bool(apply_now_var.get())
            apply_depot = apply_depot_var.get().strip()
            apply_qty = max(1, self._parse_int(apply_qty_var.get(), 1))
            if apply_now and not apply_depot:
                messagebox.showwarning("入力不足", "営業所を選択してください")
                return

            def action() -> dict[str, Any]:
                created = self.client.create_vehicle_template(scenario_id, template_payload)
                created_id = str(created.get("id") or created.get("templateId") or "")
                if apply_now:
                    vehicle_payload = dict(template_payload)
                    vehicle_payload.pop("name", None)
                    vehicle_payload["depotId"] = apply_depot
                    vehicle_payload["quantity"] = apply_qty
                    self.client.create_vehicle_batch(scenario_id, vehicle_payload)
                return {"templateId": created_id, "applied": apply_now, "depotId": apply_depot, "qty": apply_qty}

            def done(resp: dict[str, Any]) -> None:
                self.log_line(f"テンプレートを作成: {resp.get('templateId') or '(id不明)'}")
                if resp.get("applied"):
                    self.log_line(f"テンプレート由来で車両追加: {resp.get('depotId')} x {resp.get('qty')}")
                    self.fleet_depot_var.set(str(resp.get("depotId") or ""))
                    self.refresh_vehicles()
                self.refresh_templates()
                win.destroy()

            self.run_bg(action, done)

        ttk.Button(btns, text="作成", command=submit).pack(side=tk.RIGHT)
        ttk.Button(btns, text="キャンセル", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    def open_template_apply_window(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        if not self.template_rows:
            messagebox.showwarning("入力不足", "先にテンプレート一覧更新を実行してください")
            return

        win = tk.Toplevel(self.root)
        win.title("テンプレートから営業所へ車両追加")
        win.geometry("560x260")

        depot_choices = self._current_depot_choices()
        template_choices = [f"{str(t.get('id') or '')} | {str(t.get('name') or t.get('modelName') or '')}" for t in self.template_rows]
        template_var = tk.StringVar(value=(template_choices[0] if template_choices else ""))
        depot_var = tk.StringVar(value=(self.fleet_depot_var.get().strip() or (depot_choices[0] if depot_choices else "")))
        qty_var = tk.StringVar(value="1")

        form = ttk.Frame(win, padding=10)
        form.pack(fill=tk.BOTH, expand=True)

        row1 = ttk.Frame(form)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="テンプレート", width=18).pack(side=tk.LEFT)
        ttk.Combobox(row1, textvariable=template_var, state="readonly", values=template_choices).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row2 = ttk.Frame(form)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="営業所", width=18).pack(side=tk.LEFT)
        ttk.Combobox(row2, textvariable=depot_var, state="readonly", values=depot_choices).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row3 = ttk.Frame(form)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="追加台数", width=18).pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=qty_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        btns = ttk.Frame(form)
        btns.pack(fill=tk.X, pady=(10, 0))

        def submit() -> None:
            template_text = template_var.get().strip()
            template_id = template_text.split("|", 1)[0].strip()
            depot_id = depot_var.get().strip()
            qty = max(1, self._parse_int(qty_var.get(), 1))
            if not template_id or not depot_id:
                messagebox.showwarning("入力不足", "テンプレートと営業所を選択してください")
                return
            template = next((t for t in self.template_rows if str(t.get("id") or "") == template_id), None)
            if template is None:
                messagebox.showwarning("入力不足", "テンプレートが見つかりません。一覧更新してください")
                return

            payload = self._normalize_powertrain_payload(
                {
                    "depotId": depot_id,
                    "type": str(template.get("type") or "BEV"),
                    "modelCode": template.get("modelCode"),
                    "modelName": str(template.get("modelName") or template.get("name") or "TemplateVehicle"),
                    "capacityPassengers": int(template.get("capacityPassengers") or 0),
                    "batteryKwh": template.get("batteryKwh"),
                    "fuelTankL": template.get("fuelTankL"),
                    "energyConsumption": float(template.get("energyConsumption") or 0.0),
                    "fuelEfficiencyKmPerL": template.get("fuelEfficiencyKmPerL"),
                    "co2EmissionGPerKm": template.get("co2EmissionGPerKm"),
                    "engineDisplacementL": template.get("engineDisplacementL"),
                    "chargePowerKw": template.get("chargePowerKw"),
                    "minSoc": template.get("minSoc"),
                    "maxSoc": template.get("maxSoc"),
                    "acquisitionCost": float(template.get("acquisitionCost") or 0.0),
                    "enabled": bool(template.get("enabled", True)),
                    "quantity": qty,
                }
            )
            payload["quantity"] = qty

            self.run_bg(
                lambda: self.client.create_vehicle_batch(scenario_id, payload),
                lambda resp: (
                    self.log_line(f"テンプレート導入: {template_id} -> {depot_id} x {resp.get('total') or qty}"),
                    self.fleet_depot_var.set(depot_id),
                    self.refresh_vehicles(),
                    win.destroy(),
                ),
            )

        ttk.Button(btns, text="追加", command=submit).pack(side=tk.RIGHT)
        ttk.Button(btns, text="キャンセル", command=win.destroy).pack(side=tk.RIGHT, padx=6)

    def refresh_templates(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        if not self._template_panel_ready():
            return

        def done(resp: dict[str, Any]) -> None:
            self.template_rows = list(resp.get("items") or [])
            if not self._widget_exists(self.template_tree):
                return
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
        self.t_model_code_var.set(str(row.get("modelCode") or ""))
        self.t_model_var.set(str(row.get("modelName") or ""))
        self.t_cap_var.set(str(row.get("capacityPassengers") or 0))
        self.t_battery_var.set("" if row.get("batteryKwh") is None else str(row.get("batteryKwh")))
        self.t_fuel_tank_var.set("" if row.get("fuelTankL") is None else str(row.get("fuelTankL")))
        self.t_energy_var.set(str(row.get("energyConsumption") or 0.0))
        self.t_km_per_l_var.set("" if row.get("fuelEfficiencyKmPerL") is None else str(row.get("fuelEfficiencyKmPerL")))
        self.t_co2_gpkm_var.set("" if row.get("co2EmissionGPerKm") is None else str(row.get("co2EmissionGPerKm")))
        self.t_curb_weight_var.set("" if row.get("curbWeightKg") is None else str(row.get("curbWeightKg")))
        self.t_gross_weight_var.set("" if row.get("grossVehicleWeightKg") is None else str(row.get("grossVehicleWeightKg")))
        self.t_engine_disp_var.set("" if row.get("engineDisplacementL") is None else str(row.get("engineDisplacementL")))
        self.t_max_torque_var.set("" if row.get("maxTorqueNm") is None else str(row.get("maxTorqueNm")))
        self.t_max_power_var.set("" if row.get("maxPowerKw") is None else str(row.get("maxPowerKw")))
        self.t_charge_var.set("" if row.get("chargePowerKw") is None else str(row.get("chargePowerKw")))
        self.t_min_soc_var.set("" if row.get("minSoc") is None else str(row.get("minSoc")))
        self.t_max_soc_var.set("" if row.get("maxSoc") is None else str(row.get("maxSoc")))
        self.t_acq_cost_var.set(str(row.get("acquisitionCost") or 0.0))
        self.t_enabled_var.set(bool(row.get("enabled", True)))
        self._update_template_form_visibility()

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
        objective_weights = _compose_saved_objective_weights(
            self._parse_objective_weights_json(),
            slack_penalty=self._parse_float(self.contract_penalty_coeff_var.get(), 1000000.0),
            degradation_weight=self._parse_float(self.degradation_weight_var.get(), 0.0),
        )
        service_dates = self._selected_service_dates(announce=False)
        if service_dates is None:
            raise ValueError("invalid_service_date")
        if not service_dates:
            messagebox.showwarning("入力不足", "Prepare 前に運行日を入力してください")
            raise ValueError("missing_service_date")
        planning_days = self._planning_days_value()
        minimum_horizon_hours = 24.0 * float(planning_days) if planning_days > 1 else 20.0
        depot_energy_assets = self._sync_pv_assets_for_selected_depots(announce=False)
        if depot_energy_assets is None:
            raise ValueError("invalid_depot_energy_assets")
        fixed_route_band_mode = self.fixed_route_band_mode_var.get()
        allow_intra_depot_swap = (
            False if fixed_route_band_mode else self.allow_intra_var.get()
        )

        return {
            "selected_depot_ids": self._selected_depot_ids(),
            "selected_route_ids": self._selected_route_ids(),
            "day_type": self.day_type_var.get().strip(),
            "service_date": self.service_date_var.get().strip() or None,
            "service_dates": service_dates,
            "include_short_turn": self.include_short_turn_var.get(),
            "include_depot_moves": self.include_depot_moves_var.get(),
            "include_deadhead": self.include_deadhead_var.get(),
            "allow_intra_depot_route_swap": allow_intra_depot_swap,
            "allow_inter_depot_swap": self.allow_inter_var.get(),
            "simulation_settings": {
                "initial_soc": self._parse_float(self.initial_soc_var.get(), 0.8),
                "soc_min": self._parse_float(self.soc_min_var.get(), 0.2),
                "soc_max": self._parse_float(self.soc_max_var.get(), 0.9),
                "use_selected_depot_vehicle_inventory": True,
                "use_selected_depot_charger_inventory": True,
                "cost_component_flags": self._cost_component_flags_payload(),
                "deadhead_speed_kmh": self._parse_float(self.deadhead_speed_kmh_var.get(), 18.0),
                "solver_mode": self.solver_mode_var.get().strip(),
                "objective_mode": self.objective_mode_var.get().strip(),
                "objective_preset": self.objective_preset_var.get().strip() or "cost",
                "planning_days": planning_days,
                "service_dates": service_dates,
                "fixed_route_band_mode": fixed_route_band_mode,
                "enable_vehicle_diagram_output": (
                    self.enable_vehicle_diagram_output_var.get()
                    or fixed_route_band_mode
                ),
                "allow_partial_service": self.allow_partial_service_var.get(),
                "unserved_penalty": self._parse_float(self.unserved_penalty_var.get(), 10000.0),
                "time_limit_seconds": self._parse_int(self.time_limit_var.get(), 300),
                "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
                "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
                "no_improvement_limit": self._parse_int(self.no_improvement_limit_var.get(), 100),
                "destroy_fraction": self._parse_float(self.destroy_fraction_var.get(), 0.25),
                "include_deadhead": self.include_deadhead_var.get(),
                "grid_flat_price_per_kwh": self._parse_float(self.grid_flat_price_var.get(), 0.0),
                "grid_sell_price_per_kwh": self._parse_float(self.grid_sell_price_var.get(), 0.0),
                "demand_charge_cost_per_kw": self._parse_float(self.demand_charge_var.get(), 0.0),
                "diesel_price_per_l": self._parse_float(self.diesel_price_var.get(), 145.0),
                "grid_co2_kg_per_kwh": self._parse_float(self.grid_co2_var.get(), 0.0),
                "co2_price_per_kg": self._parse_float(self.co2_price_var.get(), 0.0),
                "ice_co2_kg_per_l": self._parse_float(self.ice_co2_kg_per_l_var.get(), 2.64),
                "depot_power_limit_kw": self._parse_float(self.depot_power_limit_var.get(), 500.0),
                "tou_pricing": self._parse_tou_text(),
                "objective_weights": objective_weights,
                "depot_energy_assets": depot_energy_assets,
                "pv_profile_id": self.pv_profile_id_var.get().strip() or None,
                "weather_mode": self.weather_mode_var.get().strip() or _ACTUAL_DATE_PV_PROFILE_ID,
                "weather_factor_scalar": self._parse_float(self.weather_factor_scalar_var.get(), 1.0),
                "planning_horizon_hours": minimum_horizon_hours,
                "random_seed": self._parse_int(self.random_seed_var.get(), 42),
            },
        }

    def prepare(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        self.log_line("入力データ作成(Prepare)を開始します")
        self.log_line("Prepare は現在選択している営業所・路線だけを対象に入力データを作成します")
        messagebox.showinfo("実行開始", "入力データ作成(Prepare)を開始します")

        def done(resp: dict[str, Any]) -> None:
            self._sync_prepared_state_from_response(resp)
            prepare_profile = dict(resp.get("prepareProfile") or {})
            self.log_line(
                f"Prepare完了: ready={resp.get('ready')} / tripCount={resp.get('tripCount')} / primaryDepot={resp.get('primaryDepotId')}"
            )
            self.log_line(
                "Prepare solver profile: "
                f"requested={resp.get('solverModeRequested')} / "
                f"effective={resp.get('solverModeEffective')} / "
                f"profile={prepare_profile.get('profile')}"
            )
            self.log_line(f"Prepare objective mode: {resp.get('objectiveMode') or self.objective_mode_var.get().strip()}")
            self.log_line(
                f"Prepare採用台数: vehicles={resp.get('vehicleCount', '-')} / chargers={resp.get('chargerCount', '-')}"
            )
            for warning in resp.get("warnings") or []:
                self.log_line(f"警告: {warning}")
            if self.prepared_ready:
                messagebox.showinfo("Prepare完了", f"prepared_input_id: {self.prepared_input_id or '-'}")
            else:
                route_count = int(resp.get("routeCount") or 0)
                if route_count <= 0:
                    reason = "営業所または路線が未選択です。Quick Setup を確認してください。"
                else:
                    reason = "選択 route / day type / service_date を確認してください。"
                messagebox.showwarning(
                    "Prepare未完了",
                    f"tripCount={self.prepared_trip_count} のため実行対象がありません。{reason}",
                )

        try:
            payload = self._prepare_payload()
        except ValueError:
            return
        self.run_bg(lambda: self.client.prepare_simulation(scenario_id, payload), done)

    def _set_job_from_resp(self, resp: dict[str, Any], label: str) -> None:
        self.last_job_id = str(resp.get("job_id") or resp.get("jobId") or "")
        self.job_var.set(f"job: {self.last_job_id or '-'}")
        self.manual_job_id_var.set(self.last_job_id)
        self.log_line(f"{label}: {self.last_job_id}")

    def _is_stale_prepared_input_error(self, message: str) -> bool:
        text = str(message or "")
        return "HTTP 409" in text and "Prepared input is stale" in text

    def _extract_stale_prepared_input_ids(self, message: str) -> tuple[str, str]:
        text = str(message or "")
        marker = "HTTP 409:"
        marker_index = text.find(marker)
        if marker_index < 0:
            return "", ""
        payload = text[marker_index + len(marker):].strip()
        if not payload:
            return "", ""
        try:
            body = json.loads(payload)
        except Exception:
            return "", ""
        detail = body.get("detail") if isinstance(body, dict) else {}
        if not isinstance(detail, dict):
            return "", ""
        stale = str(detail.get("preparedInputId") or "")
        current = str(detail.get("currentPreparedInputId") or "")
        return stale, current

    def _sync_prepared_state_from_response(self, resp: dict[str, Any]) -> None:
        self.prepared_input_id = str(resp.get("preparedInputId") or "")
        self.prepared_ready = bool(resp.get("ready"))
        self.prepared_trip_count = int(resp.get("tripCount") or 0)
        prepare_profile = dict(resp.get("prepareProfile") or {})
        self.prepared_dirty_reason = ""
        self.prepared_profile_name = str(prepare_profile.get("profile") or "")
        self._update_prepared_status_label()

    def _wrap_execution_with_prepare_retry(
        self,
        *,
        scenario_id: str,
        action_label: str,
        prepare_payload: dict[str, Any],
        payload: dict[str, Any],
        request_action,
    ):
        def wrapped() -> dict[str, Any]:
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    return request_action()
                except RuntimeError as exc:
                    message = str(exc)
                    if not self._is_stale_prepared_input_error(message) or attempt >= max_attempts:
                        raise

                    stale_id, current_id = self._extract_stale_prepared_input_ids(message)
                    current_payload_id = str(payload.get("prepared_input_id") or "")
                    if current_id and current_id != current_payload_id:
                        payload["prepared_input_id"] = current_id

                        def sync_with_server_current() -> None:
                            self.prepared_input_id = current_id
                            self._update_prepared_status_label()
                            if stale_id:
                                self.log_line(
                                    f"{action_label}: stale検知 ({stale_id} -> {current_id})。server 現在IDへ自動同期して再送します"
                                )
                            else:
                                self.log_line(
                                    f"{action_label}: stale検知。server 現在ID {current_id} へ自動同期して再送します"
                                )

                        self._queue_on_ui_thread(sync_with_server_current)
                        continue

                    self._queue_on_ui_thread(
                        lambda: self.log_line(
                            f"{action_label}: prepared input が stale だったため Prepare を自動再実行します"
                        )
                    )
                    prep_resp = self.client.prepare_simulation(scenario_id, prepare_payload)
                    new_prepared_input_id = str(prep_resp.get("preparedInputId") or "")
                    if not new_prepared_input_id or not bool(prep_resp.get("ready")):
                        raise RuntimeError(
                            "自動Prepareに失敗しました。Prepare を手動で再実行してください。"
                        )

                    payload["prepared_input_id"] = new_prepared_input_id

                    def sync_state() -> None:
                        self._sync_prepared_state_from_response(prep_resp)
                        self.log_line(f"自動Prepare完了: prepared_input_id: {new_prepared_input_id}")
                        for warning in prep_resp.get("warnings") or []:
                            self.log_line(f"警告: {warning}")

                    self._queue_on_ui_thread(sync_state)
            raise RuntimeError("実行に失敗しました。Prepare を再実行してから再試行してください。")

        return wrapped

    def _ensure_prepared_before_execution(self, action_label: str) -> str | None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return None
        if not self.prepared_input_id:
            messagebox.showwarning("Prepare未実行", "先に Solver対応 Prepare を実行してください")
            return None
        if not self.prepared_ready or self.prepared_trip_count <= 0:
            reason = self.prepared_dirty_reason or "tripCount=0 または stale な prepared_input_id です。"
            messagebox.showwarning(
                "Prepare未完了",
                f"{action_label} の前に Prepare をやり直してください。\n{reason}",
            )
            return None
        return scenario_id

    def _ensure_execution_window(self, title: str) -> None:
        scenario_id = self._selected_scenario_id() or "-"
        if self.optimization_window and self.optimization_window.winfo_exists():
            self.optimization_window.title(title)
            self.optimization_window.lift()
            return

        win = tk.Toplevel(self.root)
        self.optimization_window = win
        win.title(title)
        win.geometry("900x600")

        top = ttk.Frame(win, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"シナリオ: {scenario_id}", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(top, text="実行すると進捗とメッセージが下のコンソールに表示されます。", foreground="#444").pack(anchor="w", pady=(2, 6))

        status_row = ttk.Frame(top)
        status_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(status_row, text="進捗", width=8).pack(side=tk.LEFT)
        progress = ttk.Progressbar(status_row, mode="determinate", maximum=100, variable=self.optimization_progress_var)
        progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(status_row, textvariable=self.optimization_status_var, width=18).pack(side=tk.LEFT, padx=(8, 0))

        console_frame = ttk.LabelFrame(win, text="実行ログ (PowerShell風)", padding=8)
        console_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.optimization_console = ScrolledText(console_frame, height=20, bg="#111", fg="#d8ffd8", insertbackground="#d8ffd8")
        self.optimization_console.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(win, padding=(10, 0, 10, 10))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="閉じる", command=win.destroy).pack(side=tk.RIGHT, padx=6)

        def on_close() -> None:
            self.optimization_polling = False
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

    def _submit_execution_job(
        self,
        *,
        window_title: str,
        action_label: str,
        payload: dict[str, Any] | None,
        request_action,
    ) -> None:
        self._ensure_execution_window(window_title)
        self.optimization_progress_var.set(0.0)
        self.optimization_status_var.set("送信中")
        self.optimization_last_message = ""
        self.optimization_last_status = ""
        self.optimization_last_progress = -1.0
        self.optimization_poll_count = 0
        self.optimization_last_snapshot_json = ""
        self._optimization_console_log(f"{action_label}を開始します")
        if payload is not None:
            self._optimization_console_log("payload=" + json.dumps(payload, ensure_ascii=False, indent=2))
        self.log_line(f"{action_label}を開始します")

        def done(resp: dict[str, Any]) -> None:
            self._set_job_from_resp(resp, f"{action_label}ジョブ開始")
            self.optimization_job_id = self.last_job_id
            self.optimization_status_var.set("実行中")
            self._optimization_console_log(f"ジョブ開始: {self.optimization_job_id}")
            if payload is not None:
                self._optimization_console_log(
                    "payload_effective=" + json.dumps(payload, ensure_ascii=False, indent=2)
                )
            self._optimization_console_log(
                "start_response=" + json.dumps(resp or {}, ensure_ascii=False, indent=2)
            )
            self._start_optimization_polling(action_label)

        self.run_bg(request_action, done)

    def run_selected_execution(self) -> None:
        action_kind = self._execution_mode_kind()
        if action_kind == "prepared_simulation":
            scenario_id = self._ensure_prepared_before_execution("Preparedシミュレーション")
            if not scenario_id:
                return
            try:
                prepare_payload = self._prepare_payload()
            except ValueError:
                return
            payload = {
                "prepared_input_id": self.prepared_input_id,
                "source": "duties",
            }
            request_action = self._wrap_execution_with_prepare_retry(
                scenario_id=scenario_id,
                action_label="Preparedシミュレーション",
                prepare_payload=prepare_payload,
                payload=payload,
                request_action=lambda: self.client.run_prepared_simulation(
                    scenario_id,
                    payload["prepared_input_id"],
                    payload["source"],
                ),
            )
            self._submit_execution_job(
                window_title="Preparedシミュレーションモニター",
                action_label="Preparedシミュレーション",
                payload=payload,
                request_action=request_action,
            )
            return

        if action_kind == "reoptimization":
            scenario_id = self._ensure_prepared_before_execution("再最適化")
            if not scenario_id:
                return
            depots = self._selected_depot_ids()
            try:
                prepare_payload = self._prepare_payload()
            except ValueError:
                return
            payload = {
                "mode": self.solver_mode_var.get().strip(),
                "prepared_input_id": self.prepared_input_id,
                "current_time": datetime.now().strftime("%H:%M"),
                "time_limit_seconds": self._parse_int(self.time_limit_var.get(), 300),
                "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
                "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
                "no_improvement_limit": self._parse_int(self.no_improvement_limit_var.get(), 100),
                "destroy_fraction": self._parse_float(self.destroy_fraction_var.get(), 0.25),
                "service_id": self.day_type_var.get().strip() or None,
                "depot_id": depots[0] if depots else None,
            }
            request_action = self._wrap_execution_with_prepare_retry(
                scenario_id=scenario_id,
                action_label="再最適化",
                prepare_payload=prepare_payload,
                payload=payload,
                request_action=lambda: self.client.reoptimize(scenario_id, payload),
            )
            self._submit_execution_job(
                window_title="再最適化モニター",
                action_label="再最適化",
                payload=payload,
                request_action=request_action,
            )
            return

        scenario_id = self._ensure_prepared_before_execution("最適化計算")
        if not scenario_id:
            return
        depots = self._selected_depot_ids()
        effective_time_limit = self._effective_optimization_time_limit_seconds()
        try:
            prepare_payload = self._prepare_payload()
        except ValueError:
            return
        payload = {
            "mode": self.solver_mode_var.get().strip(),
            "prepared_input_id": self.prepared_input_id,
            "time_limit_seconds": effective_time_limit,
            "mip_gap": self._parse_float(self.mip_gap_var.get(), 0.01),
            "alns_iterations": self._parse_int(self.alns_iter_var.get(), 500),
            "no_improvement_limit": self._parse_int(self.no_improvement_limit_var.get(), 100),
            "destroy_fraction": self._parse_float(self.destroy_fraction_var.get(), 0.25),
            "service_id": self.day_type_var.get().strip() or None,
            "depot_id": depots[0] if depots else None,
            "rebuild_dispatch": bool(self.rebuild_dispatch_before_opt_var.get()),
        }
        request_action = self._wrap_execution_with_prepare_retry(
            scenario_id=scenario_id,
            action_label="最適化計算",
            prepare_payload=prepare_payload,
            payload=payload,
            request_action=lambda: self.client.run_optimization(scenario_id, payload),
        )
        if payload["mode"] == "mode_milp_only" and self.prepared_trip_count >= 2000:
            continue_run = messagebox.askyesno(
                "大規模MILP警告",
                "現在のスコープは大規模です。\n"
                f"tripCount={self.prepared_trip_count} / solver=mode_milp_only\n\n"
                "exact MILP は非常に長くなる可能性があります。\n"
                "通常は hybrid または mode_alns_only を推奨します。\n"
                "そのまま実行しますか？",
            )
            if not continue_run:
                self.log_line("大規模MILP警告により実行を中止しました")
                return
        if self.wait_until_finish_var.get():
            self.log_line("終了まで待機モードで実行します")
        if not self.rebuild_dispatch_before_opt_var.get():
            self.log_line("軽量化: prepared scope を直接使い、dispatch再構築は省略します")
        self._submit_execution_job(
            window_title="最適化実行モニター",
            action_label="最適化計算",
            payload=payload,
            request_action=request_action,
        )

    def run_prepared(self) -> None:
        if self.execution_mode_var is not None:
            self.execution_mode_var.set("Preparedシミュレーション")
        self.run_selected_execution()

    def run_optimization(self) -> None:
        if self.execution_mode_var is not None:
            self.execution_mode_var.set("最適化計算")
        self.run_selected_execution()

    # ソルバー側ハードキャップ（bff 側の _MAX_TIME_LIMIT_SECONDS と同値）
    _SOLVER_HARD_CAP_SECONDS = 86400  # 1 日

    def _effective_optimization_time_limit_seconds(self) -> int:
        if self.wait_until_finish_var.get():
            # 「終了まで待機」モードでもサーバー側ハードキャップ (1 日) を使う。
            # かつてここで 604800 (7 日) を返していたが、Gurobi が
            # OutputFlag=0 のまま 7 日間ブロックする事故が発生したため廃止。
            return self._SOLVER_HARD_CAP_SECONDS
        raw = self._parse_int(self.time_limit_var.get(), 300)
        if raw > self._SOLVER_HARD_CAP_SECONDS:
            self.log_line(
                f"[警告] time_limit {raw}s はハードキャップ {self._SOLVER_HARD_CAP_SECONDS}s を超えています。"
                f" → {self._SOLVER_HARD_CAP_SECONDS}s に制限します。"
            )
            return self._SOLVER_HARD_CAP_SECONDS
        return raw

    def _execution_mode_kind(self) -> str:
        raw = str((self.execution_mode_var.get() if self.execution_mode_var else "") or "").strip()
        mapping = {
            "最適化計算": "optimization",
            "Preparedシミュレーション": "prepared_simulation",
            "再最適化": "reoptimization",
        }
        return mapping.get(raw, "optimization")

    def _update_prepared_status_label(self) -> None:
        if not hasattr(self, "prepared_var"):
            return
        base = self.prepared_input_id or "-"
        suffix = ""
        if self.prepared_profile_name:
            suffix += f" [{self.prepared_profile_name}]"
        if self.prepared_dirty_reason:
            suffix += f" [stale: {self.prepared_dirty_reason}]"
        self.prepared_var.set(f"prepared_input_id: {base}{suffix}")

    def _mark_prepared_stale(self, reason: str, *, clear_id: bool = False, announce: bool = False) -> None:
        if self._suspend_prepare_watchers:
            return
        if clear_id:
            self.prepared_input_id = ""
            self.prepared_trip_count = 0
            self.prepared_profile_name = ""
        if not self.prepared_input_id and not self.prepared_ready:
            self.prepared_dirty_reason = ""
            self._update_prepared_status_label()
            return
        self.prepared_ready = False
        self.prepared_dirty_reason = reason
        self._update_prepared_status_label()
        if announce:
            self.log_line(f"Prepare を再実行してください: {reason}")

    def _clear_prepared_state(self) -> None:
        self.prepared_input_id = ""
        self.prepared_ready = False
        self.prepared_trip_count = 0
        self.prepared_dirty_reason = ""
        self.prepared_profile_name = ""
        self._update_prepared_status_label()

    def _register_prepare_dependency_watchers(self) -> None:
        watched_pairs = [
            (self.day_type_var, "運行種別を変更"),
            (self.service_date_var, "運行日を変更"),
            (self.planning_days_var, "計画日数を変更"),
            (self.include_short_turn_var, "区間便設定を変更"),
            (self.include_depot_moves_var, "入出庫便設定を変更"),
            (self.include_deadhead_var, "回送設定を変更"),
            (self.allow_intra_var, "営業所内トレード設定を変更"),
            (self.allow_inter_var, "営業所間トレード設定を変更"),
            (self.fixed_route_band_mode_var, "固定路線バンド設定を変更"),
            (self.solver_mode_var, "ソルバー種別を変更"),
            (self.objective_mode_var, "目的関数モードを変更"),
            (self.objective_preset_var, "目的プリセットを変更"),
            (self.allow_partial_service_var, "未配車許容設定を変更"),
            (self.initial_soc_var, "SOC初期値を変更"),
            (self.soc_min_var, "SOC下限を変更"),
            (self.soc_max_var, "SOC上限を変更"),
            (self.unserved_penalty_var, "未配車ペナルティを変更"),
            (self.grid_flat_price_var, "電気料金を変更"),
            (self.grid_sell_price_var, "売電単価を変更"),
            (self.demand_charge_var, "需要料金を変更"),
            (self.diesel_price_var, "軽油単価を変更"),
            (self.deadhead_speed_kmh_var, "回送速度を変更"),
            (self.grid_co2_var, "CO2原単位を変更"),
            (self.co2_price_var, "CO2単価を変更"),
            (self.ice_co2_kg_per_l_var, "軽油CO2係数を変更"),
            (self.degradation_weight_var, "劣化重みを変更"),
            (self.depot_power_limit_var, "営業所契約電力を変更"),
            (self.max_start_fragments_var, "開始断片上限を変更"),
            (self.max_end_fragments_var, "終了断片上限を変更"),
            (self.initial_soc_percent_var, "初期SOC比を変更"),
            (self.final_soc_floor_percent_var, "終了SOC床を変更"),
            (self.final_soc_target_percent_var, "終了SOC目標を変更"),
            (self.final_soc_target_tolerance_percent_var, "終了SOC目標許容幅を変更"),
            (self.initial_ice_fuel_percent_var, "ICE初期燃料比を変更"),
            (self.min_ice_fuel_percent_var, "ICE最低燃料バッファを変更"),
            (self.max_ice_fuel_percent_var, "ICE燃料バッファ上限を変更"),
            (self.default_ice_tank_capacity_l_var, "ICE既定タンク容量を変更"),
            (self.pv_profile_id_var, "PVプロファイルを変更"),
            (self.weather_mode_var, "天気モードを変更"),
            (self.weather_factor_scalar_var, "天気係数を変更"),
            (self.depot_energy_assets_json_var, "営業所エネルギー資産設定を変更"),
            (self.co2_price_source_var, "CO2価格ソースを変更"),
            (self.co2_reference_date_var, "CO2参照日を変更"),
            (self.enable_vehicle_diagram_output_var, "ダイヤグラム出力設定を変更"),
        ]
        watched_pairs.extend(
            (
                self.cost_component_vars[definition.key],
                f"{definition.label}設定を変更",
            )
            for definition in COST_COMPONENT_DEFINITIONS
        )
        for variable, reason in watched_pairs:
            variable.trace_add("write", lambda *_args, r=reason: self._mark_prepared_stale(r))

    def _extract_job_progress_percent(self, job: dict[str, Any]) -> float:
        raw = job.get("progress")
        if isinstance(raw, dict):
            raw = raw.get("percent") or raw.get("progress") or raw.get("value")
        if raw is None:
            raw = job.get("progressPercent")
        if raw is None:
            return 0.0
        try:
            value = float(raw)
        except Exception:
            return 0.0
        if 0.0 <= value <= 1.0:
            value *= 100.0
        return max(0.0, min(100.0, value))

    def _optimization_console_log(self, text: str) -> None:
        if not self.optimization_console:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.optimization_console.insert(tk.END, f"[{stamp}] {text}\n")
        self.optimization_console.see(tk.END)

    def _log_build_audit_summary(self, scenario_doc: dict[str, Any]) -> None:
        audit = dict(scenario_doc.get("problemdata_build_audit") or {})
        if not audit:
            self._optimization_console_log("build_audit: 取得なし")
            return
        self._optimization_console_log(
            "build_audit: "
            f"trips={audit.get('trip_count')}, "
            f"tasks={audit.get('task_count')}, "
            f"vehicles={audit.get('vehicle_count')}, "
            f"graph_edges={audit.get('graph_edge_count')}, "
            f"travel_connections={audit.get('travel_connection_count')}"
        )
        for warning in list(audit.get("warnings") or []):
            self._optimization_console_log(f"build_audit.warning: {warning}")
        for err in list(audit.get("errors") or []):
            self._optimization_console_log(f"build_audit.error: {err}")

    def _parse_connection_metrics_from_error(self, error_text: str) -> dict[str, int]:
        text = str(error_text or "")
        match = re.search(
            r"tasks\s*=\s*(\d+)\s*,\s*vehicles\s*=\s*(\d+)\s*,\s*travel_connections\s*=\s*(\d+)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return {}
        try:
            return {
                "task_count": int(match.group(1)),
                "vehicle_count": int(match.group(2)),
                "travel_connection_count": int(match.group(3)),
            }
        except Exception:
            return {}

    def _load_prepared_input_summary(
        self,
        *,
        scenario_id: str,
        prepared_input_id: str,
    ) -> dict[str, Any]:
        if not scenario_id or not prepared_input_id:
            return {}

        candidates = [
            _REPO_ROOT / "output" / "prepared_inputs" / scenario_id / f"{prepared_input_id}.json",
            _REPO_ROOT / "outputs" / "prepared_inputs" / scenario_id / f"{prepared_input_id}.json",
        ]
        for file_path in candidates:
            if not file_path.exists():
                continue
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            counts = dict(raw.get("counts") or {})
            return {
                "path": str(file_path),
                "trip_count": raw.get("trip_count") if raw.get("trip_count") is not None else counts.get("trip_count"),
                "route_count": counts.get("route_count"),
                "vehicle_count": counts.get("vehicle_count"),
                "depot_count": counts.get("depot_count"),
                "timetable_row_count": raw.get("timetable_row_count") if raw.get("timetable_row_count") is not None else counts.get("timetable_row_count"),
            }
        return {}

    def _log_failure_guidance(self, error_text: str) -> None:
        lowered = str(error_text or "").lower()
        if "no travel connections generated" in lowered and "allow_partial_service" in lowered:
            self._optimization_console_log("対処ガイド: 接続グラフが0件です。")
            self._optimization_console_log("  1) Quick Setupで『未配車許容(allowPartialService)』をON")
            self._optimization_console_log("  2) Quick Setup保存 → Solver対応 Prepare を再実行")
            self._optimization_console_log("  3) それでもNGなら route scope を絞って travel_connection_count > 0 を確認")
            self._optimization_console_log("  4) 厳格運用(未配車許容OFF)時は travel_connection_count=0 のまま実行不可")

    def _log_runtime_failure_diagnostics(self, *, error_text: str = "") -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        prepared_input_id = str(self.prepared_input_id or "").strip()
        try:
            scenario_doc = self.client.get_scenario(scenario_id)
        except Exception as exc:
            self._optimization_console_log(f"診断取得失敗: {exc}")
            scenario_doc = {}

        has_build_audit = bool((scenario_doc or {}).get("problemdata_build_audit"))
        self._log_build_audit_summary(scenario_doc or {})
        if not has_build_audit:
            fallback_metrics = self._parse_connection_metrics_from_error(error_text)
            if fallback_metrics:
                self._optimization_console_log(
                    "build_audit(fallback:error): "
                    f"tasks={fallback_metrics.get('task_count')}, "
                    f"vehicles={fallback_metrics.get('vehicle_count')}, "
                    f"travel_connections={fallback_metrics.get('travel_connection_count')}"
                )
            prepared_summary = self._load_prepared_input_summary(
                scenario_id=scenario_id,
                prepared_input_id=prepared_input_id,
            )
            if prepared_summary:
                self._optimization_console_log(
                    "prepared_input_summary: "
                    f"trips={prepared_summary.get('trip_count')}, "
                    f"routes={prepared_summary.get('route_count')}, "
                    f"vehicles={prepared_summary.get('vehicle_count')}, "
                    f"depots={prepared_summary.get('depot_count')}, "
                    f"timetable_rows={prepared_summary.get('timetable_row_count')}"
                )
                self._optimization_console_log(
                    f"prepared_input_path: {prepared_summary.get('path')}"
                )
        opt_audit = dict(scenario_doc.get("optimization_audit") or {})
        if opt_audit:
            self._optimization_console_log(
                "optimization_audit: "
                f"status={opt_audit.get('solver_status')}, "
                f"warnings={len(list(opt_audit.get('warnings') or []))}, "
                f"errors={len(list(opt_audit.get('errors') or []))}"
            )

    @staticmethod
    def _compact_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(job.get("metadata") or {}) if isinstance(job.get("metadata"), dict) else {}
        prepared_input_id = metadata.get("prepared_input_id")
        requested_prepared_input_id = metadata.get("requested_prepared_input_id")
        prepared_input_path = metadata.get("prepared_input_path")
        return {
            "job_id": job.get("job_id") or job.get("jobId"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "message": job.get("message"),
            "result_key": job.get("result_key") or job.get("resultKey"),
            "error": job.get("error"),
            "metadata": {
                "started_at": metadata.get("started_at"),
                "updated_at": metadata.get("updated_at"),
                "pid": metadata.get("pid"),
                "orphaned": metadata.get("orphaned"),
                "scenario_id": metadata.get("scenario_id") or metadata.get("scenarioId"),
                "mode": metadata.get("mode"),
                "prepared_input_id": prepared_input_id,
                "requested_prepared_input_id": requested_prepared_input_id,
                "prepared_input_path": prepared_input_path,
            },
        }

    def _log_job_snapshot_if_changed(self, job: dict[str, Any], *, force: bool = False) -> None:
        snapshot = self._compact_job_snapshot(job)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        if not force and encoded == self.optimization_last_snapshot_json:
            return
        self.optimization_last_snapshot_json = encoded
        self._optimization_console_log("job_snapshot=" + json.dumps(snapshot, ensure_ascii=False, indent=2))

    def _start_optimization_polling(self, action_label: str) -> None:
        if not self.optimization_job_id:
            return
        self.optimization_polling = True

        def tick() -> None:
            if not self.optimization_polling:
                return
            if not self.optimization_window or not self.optimization_window.winfo_exists():
                self.optimization_polling = False
                return
            job_id = self.optimization_job_id

            def done(job: dict[str, Any]) -> None:
                self.optimization_poll_count += 1
                status = str(job.get("status") or "").lower()
                progress = self._extract_job_progress_percent(job)
                message = str(job.get("message") or "")

                status_changed = status != self.optimization_last_status
                progress_changed = abs(progress - self.optimization_last_progress) >= 0.1
                message_changed = bool(message and message != self.optimization_last_message)

                if message and message != self.optimization_last_message:
                    self.optimization_last_message = message
                    self._optimization_console_log(message)

                if status_changed or progress_changed or message_changed:
                    self._optimization_console_log(
                        f"poll#{self.optimization_poll_count} status={status or 'running'} progress={progress:.1f}% message={message or '-'}"
                    )

                if status_changed or message_changed or (self.optimization_poll_count % 5 == 0):
                    self._log_job_snapshot_if_changed(job, force=status_changed or message_changed)

                self.optimization_last_status = status
                self.optimization_last_progress = progress
                self.optimization_progress_var.set(progress)
                shown = status or "running"
                self.optimization_status_var.set(shown)
                self.job_var.set(f"job: {job_id} ({shown})")
                self.log_line(f"実行監視: action={action_label} status={shown} progress={progress:.1f}%")

                finished = status in {"completed", "failed", "error", "cancelled", "canceled"}
                if finished:
                    self.optimization_polling = False
                    error_text = str(job.get("error") or "").strip()
                    if error_text:
                        self._optimization_console_log("error(traceback/full)=\n" + error_text)
                        self._log_failure_guidance(error_text)
                    self._log_job_snapshot_if_changed(job, force=True)
                    self._log_runtime_failure_diagnostics(error_text=error_text)
                    self._optimization_console_log(f"ジョブ終了: status={shown}")
                    if error_text:
                        first_line = next(
                            (line.strip() for line in error_text.splitlines() if line.strip()),
                            error_text,
                        )
                        messagebox.showerror(
                            "実行ジョブ",
                            f"{action_label} が失敗しました。\n{first_line}\n\n詳細は最適化実行モニターのログを確認してください。",
                        )
                    else:
                        messagebox.showinfo("実行ジョブ", f"{action_label} が完了しました。\nstatus={shown}")
                    return
                if self.optimization_window and self.optimization_window.winfo_exists():
                    self.optimization_window.after(2000, tick)

            self.run_bg(lambda: self.client.get_job(job_id), done)

        tick()

    def run_simulation_legacy(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return
        depots = self._selected_depot_ids()
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
        if self.execution_mode_var is not None:
            self.execution_mode_var.set("再最適化")
        self.run_selected_execution()

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

    # ──────────────────────────────────────────────────────────────
    # 別ウィンドウ管理
    # ──────────────────────────────────────────────────────────────

    def open_fleet_window(self) -> None:
        """車両・テンプレート管理ウィンドウを開く（既に開いている場合は前面に出す）。"""
        if self._fleet_window is not None and self._fleet_window.winfo_exists():
            self._fleet_window.lift()
            self._fleet_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._fleet_window = win
        win.title("車両・テンプレート管理")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(1100, int(sw * 0.7))
        h = min(820, int(sh * 0.82))
        win.geometry(f"{w}x{h}")
        win.minsize(800, 500)

        info = ttk.Frame(win, padding=(8, 4))
        info.pack(fill=tk.X)
        ttk.Label(
            info,
            text="ヒント: 車両台数・充電出力を設定したら、メイン画面で Solver対応 Prepare → ④ 実行 を行ってください。",
            foreground="#1a5276",
        ).pack(anchor="w")

        fleet_frame = ttk.Frame(win, padding=4)
        fleet_frame.pack(fill=tk.BOTH, expand=True)
        self._build_fleet_panel(fleet_frame)
        self._refresh_depot_dropdowns(self.scope_depots)
        self._fleet_built = True

        def on_close() -> None:
            self._fleet_built = False
            self._fleet_window = None
            self.vehicle_tree = None
            self.template_tree = None
            self.fleet_depot_combo = None
            self.dup_target_depot_combo = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        # 既にシナリオ・営業所情報がある場合は反映
        if self._fleet_window_ready() and self.fleet_depot_var is not None:
            scenario_id = self._selected_scenario_id()
            if scenario_id:
                self.refresh_templates()
                self.refresh_vehicles()

    def open_compare_window(self) -> None:
        """シナリオ比較ウィンドウを開く。"""
        win = tk.Toplevel(self.root)
        win.title("シナリオ比較")
        win.geometry("700x400")

        ttk.Label(
            win,
            text="2つのシナリオの最適化・シミュレーション結果を比較します。\nシナリオバーで A・B を選択してから実行してください。",
            foreground="#444",
            justify=tk.LEFT,
        ).pack(anchor="w", padx=12, pady=(10, 6))

        a_label = self.compare_scenario_a_var.get() or "(未選択)"
        b_label = self.compare_scenario_b_var.get() or "(未選択)"
        ttk.Label(win, text=f"A: {a_label}").pack(anchor="w", padx=12)
        ttk.Label(win, text=f"B: {b_label}").pack(anchor="w", padx=12, pady=(0, 10))

        btn_row = ttk.Frame(win)
        btn_row.pack(anchor="w", padx=12)
        ttk.Button(btn_row, text="Optimization比較", command=lambda: [self.compare_optimization_results(), win.lift()]).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Simulation比較", command=lambda: [self.compare_simulation_results(), win.lift()]).pack(side=tk.LEFT, padx=4)

        ttk.Separator(win, orient="horizontal").pack(fill=tk.X, pady=10, padx=8)
        ttk.Label(win, text="比較結果はこのウィンドウの下に出力されます。", foreground="#555").pack(anchor="w", padx=12)
        result_text = ScrolledText(win, height=12)
        result_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def open_help_window(self) -> None:
        """使い方ヘルプウィンドウを開く。"""
        win = tk.Toplevel(self.root)
        win.title("使い方ヘルプ")
        win.geometry("680x620")
        win.resizable(True, True)

        nb = ttk.Notebook(win)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def make_tab(title: str, content: str) -> None:
            tab = ttk.Frame(nb, padding=10)
            nb.add(tab, text=title)
            st = ScrolledText(tab, wrap=tk.WORD, font=("TkDefaultFont", 9))
            st.pack(fill=tk.BOTH, expand=True)
            st.insert("1.0", content)
            st.configure(state="disabled")

        make_tab("基本フロー", """\
【通常の最適化フロー】

① シナリオ選択・作成
  - 「一覧更新」でシナリオ一覧を取得
  - 既存シナリオをコンボから選択 または「新規作成」
  - 研究用コピーを作るには「複製」が便利です

② 営業所・路線・日付の設定（左パネル）
  - 「Quick Setup 読込」で保存済み設定を呼び出す
  - 対象の営業所にチェックを入れ、▶ で路線を展開して選択
  - 運行種別（WEEKDAY/SATURDAY/HOLIDAYなど）と運行日を設定
  - 設定が決まったら「Quick Setup 保存」

③ ソルバー設定（中パネル）
  - 燃料単価・電気代・SOC上下限などを確認・変更
  - 詳細パラメータ（CO₂・劣化費）は下へスクロール
  - 「② ソルバー設定」を押してソルバー種別・時間上限・反復回数を設定
  - ソルバー設定を変えたら Prepare は stale になるため、次の手順で再作成します

④ Solver対応 Prepare
  - 「③ Solver対応 Prepare」をクリック
  - prepared_input_id と solver profile が表示されれば完了

⑤ 実行
  - 実行種別で「最適化計算 / Preparedシミュレーション / 再最適化」を選択
  - 「④ 実行」をクリックするとモニターが開き、ジョブIDと進捗が表示されます

⑥ 結果確認
  - 「Optimization結果」ボタンで詳細ウィンドウが開きます
  - Summary タブで solver_status が OPTIMAL/FEASIBLE か確認
""")

        make_tab("パラメータ説明", """\
【主要パラメータ説明】

■ 燃料・電気代
  diesel_price_per_l      軽油単価 [円/L]（例: 145）
  grid_flat_price_per_kwh 系統電力の平均単価 [円/kWh]（例: 30）
                          TOU帯が設定されていない場合のフォールバック
  TOU帯                   時間帯別単価。スロット番号は 30 分刻みで 0〜48
                          形式: "開始-終了:単価,..."
                          例: 0-12:15,12-20:40,20-48:20
                            → 0:00〜6:00=15円, 6:00〜10:00=40円, 10:00〜24:00=20円
                          ※スロット 48 は 24:00。翌日 0:00 扱い。

■ SOC（State of Charge / バッテリー残量）
  initial_soc             運行開始時の電池残量比率（0〜1、例: 0.8）
                          1.0 = 満充電。Prepare 後は initial_soc_percent に引き継がれる
  soc_min                 走行中に下回れない SOC 下限（0〜1）
                          小さいほど柔軟だが電欠リスク上昇。例: 0.2
  soc_max                 充電を停止する SOC 上限（0〜1）。例: 0.9
  initial_soc_percent     Prepare レベルで使用される開始 SOC（通常は initial_soc と同じ値）
  final_soc_floor_percent 帰庫後の SOC 最低保証（翌日分の確保）。例: 0.2
  final_soc_target_percent 帰庫後 SOC の目標値（可能な範囲で目指す）。例: 0.8
  final_soc_target_tolerance_percent
                          目標 SOC の許容誤差（例: 0.05）。0 = 厳密な等式制約

■ 充電器・電力
  depot_power_limit_kw    営業所の系統受電契約電力上限 [kW]（例: 500）
                          超過すると罰則または INFEASIBLE になる
  demand_charge_cost_per_kw
                          ピーク需要電力 1 kW あたりの月次基本料金 [円/kW]（例: 1500）
                          充電を分散させるインセンティブとして機能（O3）
  deadhead_speed_kmh      回送速度の推定値 [km/h]（例: 18）
                          接続可否判定: arrival + turnaround + deadhead_time ≤ departure

■ CO₂・劣化（詳細パラメータ）
  grid_co2_kg_per_kwh     系統電力の CO₂排出係数 [kg/kWh]（例: 0.5）
  ice_co2_kg_per_l        軽油の CO₂排出係数 [kg/L]。デフォルト: 2.64
  co2_price_per_kg        CO₂費単価 [円/kg]（total_cost モード用）
                          0 = CO₂費を目的関数に含まない
                          co2 モードでは 0 でも CO₂排出量そのものを最小化
  degradation_weight      電池劣化コストの重み（0 = 劣化費用無効）
                          充電量 / cap × 50 円/cycle × 重みが目的関数に加算

■ ペナルティ
  unserved_penalty        未配車便への罰則 [円/便]。最小 10,000 円
                          通常は 100,000 以上推奨（欠便をほぼ禁止）
  slack_penalty           系統受電の契約超過罰則係数（例: 1,000,000）

■ 断片制約
  max_start_fragments     各車両が 1 日に出庫できる最大回数（C3 制約）
                          通常は 1（1 日 1 出庫）。増やすと分割シフトを許容
  max_end_fragments       各車両の最大入庫回数。通常は start と同じ値

■ ICE（エンジンバス）
  initial_ice_fuel_percent ICE 初期燃料比率（%）。例: 100
  min_ice_fuel_percent     最低燃料バッファ（%）。例: 10
  max_ice_fuel_percent     燃料充填上限（%）。例: 90
  default_ice_tank_capacity_l ICE タンク容量 [L]（未設定車両のフォールバック）。例: 300

■ ソルバー（手順②）
  ソルバー種別  mode_milp_only（厳密解）/ hybrid（MILP+ALNS）/ mode_alns_only / ga / abc
  目的関数      total_cost（総コスト最小）/ co2（CO₂排出最小）
                / balanced（コスト＋CO₂加重和）/ utilization（稼働率重視）
  時間上限(秒)  MILP / hybrid の最大計算時間（例: 300 秒）
  MIP gap       最適性ギャップ許容率（例: 0.01 = 1%）
  反復回数      ALNS / GA / ABC の探索反復数（例: 500）
  注意          objectiveMode やソルバー種別を変えたら必ず手順③の Prepare をやり直す
""")

        make_tab("トラブルシューティング", """\
【よくある問題と対処法】

■ INFEASIBLE（解なし）になる
  → soc_min が高すぎる → 0.2 以下に下げる
  → depot_power_limit_kw が低すぎる → 増やすか、車両台数を減らす
  → 車両台数が便数に対して少なすぎる → 車両管理ウィンドウで BEV 台数を増加
  → max_start_fragments が 1 の場合、時刻的に接続不可能な便がある可能性
    → 車両台数を増やすか、対象路線を絞る

■ tripCount=0（Prepare 後）
  → 選択した dayType × route の組合せで trip が存在しない
  → 運行種別サマリを確認し、trip 数が表示されている行を選択し直す

■ HTTP 503 エラー
  → 別のジョブが実行中 → 実行監視で完了を待ってから再試行
  → BFF が起動していない → python run_app.py で再起動

■ HTTP 500 エラー
  → Prepare が stale（「③ Prepare」が必要の表示あり）→ Prepare を再実行
  → ログに詳細エラーが表示されている場合は内容を確認

■ ジョブが終わらない（タイムアウト待ち）
  → 「② ソルバー設定」で time_limit_seconds を短縮（例: 60 秒）
  → ソルバー種別を mode_alns_only に変更（MILP より高速）
  → hybrid の場合は ALNS 部分が先に動くので数分待つと改善することがある

■ solver_status = OPTIMAL だがコストが異常に高い
  → unserved_penalty が低く、欠便が許容されている可能性
  → Optimization結果 > Details > unserved_task_count を確認
  → unserved_penalty を 100,000 以上に増やして再実行

■ objective_value が None
  → solver_status を確認（ALNS/GA/ABC は独自の objective を返す場合がある）
  → Summary タブの solver_status が OPTIMAL/FEASIBLE か確認

■ "⏳ 処理中..." がずっと消えない
  → BFF との通信に失敗している可能性 → ログエリアのエラーを確認
  → BFF URL が正しいか（デフォルト: http://127.0.0.1:8000）

■ Gurobi ライセンスエラー
  → python -c "import gurobipy as gp; m=gp.Model(); m.optimize()" で確認
  → "gurobi_ok" が出ればライセンス有効。エラーが出る場合はライセンス設定を確認

■ Quick Setup 読込後に選択が空になる
  → stale な保存選択が runtime 補正で外れた可能性
  → 営業所を選択し直してから Quick Setup 保存 → Prepare を再実行
""")

        ttk.Button(win, text="閉じる", command=win.destroy).pack(pady=6)

    def open_solver_settings_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("詳細設定 / ソルバー設定")
        win.geometry("620x520")

        ttk.Label(
            win,
            text="手順②の設定画面です。ここを変更したら手順③の Prepare をやり直してください。",
            foreground="#444",
        ).pack(anchor="w", padx=10, pady=(10, 2))

        ttk.Label(win, text="ソルバー種別 (canonical optimization engine)", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
        solver_combo = ttk.Combobox(
            win,
            state="readonly",
            textvariable=self.solver_mode_var,
            values=["mode_milp_only", "mode_alns_only", "mode_hybrid", "mode_ga_only", "mode_abc_only"],
        )
        solver_combo.pack(fill=tk.X, padx=10)
        _Tooltip(
            solver_combo,
            "mode_milp_only: 厳密MILP (大規模で遅い)\n"
            "mode_alns_only: メタヒューリスティック (高速、近似解)\n"
            "mode_hybrid: ALNS+MILP混合 (推奨、バランス型)\n"
            "mode_ga_only: 遺伝的アルゴリズム (実験的)\n"
            "mode_abc_only: 人工蜂コロニー (実験的)\n\n"
            "注意: 旧thesis_mode/mode_alns_milp等は非推奨です",
        )

        body = ttk.Frame(win)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        solver_box = ttk.LabelFrame(body, text="ソルバー詳細", padding=8)
        solver_box.pack(fill=tk.X, pady=(0, 8))

        sim_box = ttk.LabelFrame(body, text="実行時ポリシー (Advanced)", padding=8)
        sim_box.pack(fill=tk.X)

        row_obj = ttk.Frame(solver_box)
        row_obj.pack(fill=tk.X, pady=3)
        ttk.Label(row_obj, text="目的関数モード", width=24).pack(side=tk.LEFT)
        ttk.Combobox(
            row_obj,
            textvariable=self.objective_mode_var,
            state="readonly",
            values=["total_cost", "co2"],
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            solver_box,
            text="total_cost = コスト最小 / co2 = CO2排出最小",
            foreground="#555",
        ).pack(anchor="w")

        row_tl = ttk.Frame(solver_box)
        row_tl.pack(fill=tk.X, pady=3)
        ttk.Label(row_tl, text="時間上限(秒)", width=24).pack(side=tk.LEFT)
        ttk.Entry(row_tl, textvariable=self.time_limit_var, width=10).pack(side=tk.LEFT)
        ttk.Label(
            row_tl,
            text=f"(上限 {self._SOLVER_HARD_CAP_SECONDS}s = 24h。MILP初期確認は 300〜600s 推奨)",
            foreground="#888",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=(6, 0))

        row_wait = ttk.Frame(solver_box)
        row_wait.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(
            row_wait,
            text="終了まで待つ（ハードキャップ内で最大時間を使う）",
            variable=self.wait_until_finish_var,
        ).pack(side=tk.LEFT)

        row_rebuild = ttk.Frame(sim_box)
        row_rebuild.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(
            row_rebuild,
            text="実行前にdispatchを再構築する（重い）",
            variable=self.rebuild_dispatch_before_opt_var,
        ).pack(side=tk.LEFT)

        row_gap = ttk.Frame(solver_box)
        row_gap.pack(fill=tk.X, pady=3)
        ttk.Label(row_gap, text="MILPギャップ", width=24).pack(side=tk.LEFT)
        ttk.Entry(row_gap, textvariable=self.mip_gap_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_iter = ttk.Frame(solver_box)
        row_iter.pack(fill=tk.X, pady=3)
        ttk.Label(row_iter, text="反復回数(ALNS/GA/ABC)", width=24).pack(side=tk.LEFT)
        ttk.Entry(row_iter, textvariable=self.alns_iter_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_no_improve = ttk.Frame(solver_box)
        row_no_improve.pack(fill=tk.X, pady=3)
        lbl_no_improve = ttk.Label(row_no_improve, text="改善なし上限(ALNS)", width=24)
        lbl_no_improve.pack(side=tk.LEFT)
        _Tooltip(lbl_no_improve, "ALNS: この反復数だけ目的関数が改善しなければ早期終了。\nデフォルト: 100")
        ttk.Entry(row_no_improve, textvariable=self.no_improvement_limit_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_destroy = ttk.Frame(solver_box)
        row_destroy.pack(fill=tk.X, pady=3)
        lbl_destroy = ttk.Label(row_destroy, text="破壊率上限(ALNS)", width=24)
        lbl_destroy.pack(side=tk.LEFT)
        _Tooltip(lbl_destroy, "ALNS: 1反復で破壊する便の割合の上限 (0.0〜1.0)。\n大きいほど探索が広いが不安定になる。デフォルト: 0.25")
        ttk.Entry(row_destroy, textvariable=self.destroy_fraction_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_partial = ttk.Frame(sim_box)
        row_partial.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row_partial, text="未配車許容", variable=self.allow_partial_service_var).pack(side=tk.LEFT)

        row_penalty = ttk.Frame(sim_box)
        row_penalty.pack(fill=tk.X, pady=3)
        ttk.Label(row_penalty, text="未配車ペナルティ", width=24).pack(side=tk.LEFT)
        ttk.Entry(row_penalty, textvariable=self.unserved_penalty_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        info = ttk.Label(body, text="", foreground="#444")
        info.pack(anchor="w", pady=(8, 0))

        def refresh_visibility(_event=None) -> None:
            mode = self.solver_mode_var.get().strip().lower()
            is_milp_like = mode in {"mode_milp_only", "hybrid", "milp"}
            is_meta_like = mode in {"mode_alns_only", "ga", "abc", "alns"}
            uses_alns = is_meta_like or mode == "hybrid"

            if is_milp_like:
                row_gap.pack(fill=tk.X, pady=3)
            else:
                row_gap.pack_forget()

            if uses_alns:
                row_iter.pack(fill=tk.X, pady=3)
                row_no_improve.pack(fill=tk.X, pady=3)
                row_destroy.pack(fill=tk.X, pady=3)
            else:
                row_iter.pack_forget()
                row_no_improve.pack_forget()
                row_destroy.pack_forget()

            info.configure(text=f"現在のモード: {self.solver_mode_var.get()} / 表示項目を自動切替")

        solver_combo.bind("<<ComboboxSelected>>", refresh_visibility)
        refresh_visibility()

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btns, text="閉じる", command=win.destroy).pack(side=tk.RIGHT)

    def open_vehicle_depot_manager(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        win = tk.Toplevel(self.root)
        self.depot_manager_window = win
        win.title("営業所別充電器管理")
        win.geometry("980x620")

        left = ttk.Frame(win, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)
        right = ttk.Frame(win, padding=8)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="営業所一覧").pack(anchor="w")
        depot_list = tk.Listbox(left, width=32, height=28)
        depot_list.pack(fill=tk.Y, expand=True)

        ops = ttk.Frame(left)
        ops.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(ops, text="再読込", command=lambda: self._load_depot_manager_data(depot_list)).pack(side=tk.LEFT)

        charger_box = ttk.LabelFrame(right, text="営業所充電器設定", padding=8)
        charger_box.pack(fill=tk.X)
        self.dm_depot_id_var = tk.StringVar(value="")
        self.dm_depot_name_var = tk.StringVar(value="")
        self.dm_normal_count_var = tk.StringVar(value="0")
        self.dm_normal_kw_var = tk.StringVar(value="0")
        self.dm_fast_count_var = tk.StringVar(value="0")
        self.dm_fast_kw_var = tk.StringVar(value="0")
        self.dm_depot_area_m2_var = tk.StringVar(value="")
        self.dm_installable_area_m2_var = tk.StringVar(value="0")
        self.dm_pv_capacity_kw_var = tk.StringVar(value="0")

        self._labeled_entry(charger_box, "営業所ID", self.dm_depot_id_var, readonly=True)
        self._labeled_entry(charger_box, "営業所名", self.dm_depot_name_var, readonly=True)
        self._labeled_entry(charger_box, "普通充電器台数", self.dm_normal_count_var)
        self._labeled_entry(charger_box, "普通充電器出力(kW)", self.dm_normal_kw_var)
        self._labeled_entry(charger_box, "急速充電器台数", self.dm_fast_count_var)
        self._labeled_entry(charger_box, "急速充電器出力(kW)", self.dm_fast_kw_var)
        self._labeled_entry(charger_box, "営業所面積 [m²]", self.dm_depot_area_m2_var)
        self._labeled_entry(charger_box, "推定PV設置可能面積 [m²]", self.dm_installable_area_m2_var, readonly=True)
        self._labeled_entry(charger_box, "推定PV設備容量 [kW]", self.dm_pv_capacity_kw_var, readonly=True)
        self.dm_depot_area_m2_var.trace_add("write", lambda *_args: self._refresh_depot_manager_pv_preview())

        btn_row = ttk.Frame(charger_box)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="保存", command=self._save_depot_charger_settings).pack(side=tk.LEFT)

        ttk.Label(right, text="「車両・テンプレート管理」ボタンで車両管理ウィンドウを開くと連動します。", foreground="#444").pack(anchor="w", pady=(8, 0))

        depot_list.bind("<<ListboxSelect>>", lambda _e: self._on_depot_manager_select(depot_list))
        self._load_depot_manager_data(depot_list)

    def _refresh_depot_manager_pv_preview(self) -> None:
        area_var = getattr(self, "dm_depot_area_m2_var", None)
        estimate = estimate_depot_pv_from_area(area_var.get() if area_var is not None else "")
        if hasattr(self, "dm_installable_area_m2_var"):
            self.dm_installable_area_m2_var.set(f"{estimate.installable_area_m2:.3f}")
        if hasattr(self, "dm_pv_capacity_kw_var"):
            self.dm_pv_capacity_kw_var.set(f"{estimate.capacity_kw:.3f}" if estimate.depot_area_m2 is not None else "0")

    def _load_depot_manager_data(self, depot_list: tk.Listbox) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return

        def action() -> dict[str, Any]:
            return self.client.list_depots(scenario_id)

        def done(resp: dict[str, Any]) -> None:
            self.dm_depots = list(resp.get("items") or [])
            depot_list.delete(0, tk.END)
            for depot in self.dm_depots:
                did = str(depot.get("id") or "")
                name = str(depot.get("name") or did)
                depot_list.insert(tk.END, f"{did} | {name}")
            self.log_line(f"営業所一覧取得: {len(self.dm_depots)} 件")

        self.run_bg(action, done)

    def _on_depot_manager_select(self, depot_list: tk.Listbox) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            return
        sel = depot_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        depot = self.dm_depots[idx] if 0 <= idx < len(self.dm_depots) else None
        if not depot:
            return
        depot_id = str(depot.get("id") or "").strip()
        if not depot_id:
            return

        def done(detail: dict[str, Any]) -> None:
            self.dm_depot_id_var.set(str(detail.get("id") or ""))
            self.dm_depot_name_var.set(str(detail.get("name") or ""))
            self.dm_normal_count_var.set(str(detail.get("normalChargerCount") or 0))
            self.dm_normal_kw_var.set(str(detail.get("normalChargerPowerKw") or 0))
            self.dm_fast_count_var.set(str(detail.get("fastChargerCount") or 0))
            self.dm_fast_kw_var.set(str(detail.get("fastChargerPowerKw") or 0))
            area_value = detail.get("depotAreaM2", detail.get("depot_area_m2"))
            self.dm_depot_area_m2_var.set("" if area_value is None else str(area_value))
            self._refresh_depot_manager_pv_preview()

        self.run_bg(lambda: self.client.get_depot(scenario_id, depot_id), done)

    def _save_depot_charger_settings(self) -> None:
        scenario_id = self._selected_scenario_id()
        depot_id = self.dm_depot_id_var.get().strip()
        if not scenario_id or not depot_id:
            messagebox.showwarning("入力不足", "先に営業所を選択してください")
            return

        payload = {
            "normalChargerCount": max(0, self._parse_int(self.dm_normal_count_var.get(), 0)),
            "normalChargerPowerKw": max(0.0, self._parse_float(self.dm_normal_kw_var.get(), 0.0)),
            "fastChargerCount": max(0, self._parse_int(self.dm_fast_count_var.get(), 0)),
            "fastChargerPowerKw": max(0.0, self._parse_float(self.dm_fast_kw_var.get(), 0.0)),
            "depotAreaM2": max(0.0, self._parse_float(self.dm_depot_area_m2_var.get(), 0.0)),
        }

        def done(resp: dict[str, Any]) -> None:
            if isinstance(resp, dict):
                if hasattr(self, "scope_depot_by_id"):
                    self.scope_depot_by_id[depot_id] = {**self.scope_depot_by_id.get(depot_id, {}), **resp}
                for idx, depot in enumerate(getattr(self, "scope_depots", []) or []):
                    if str(depot.get("id") or "").strip() == depot_id:
                        self.scope_depots[idx] = {**depot, **resp}
                        break
            self.log_line(f"営業所充電器設定を更新: {depot_id}")
            self._mark_prepared_stale("営業所充電器/PV面積設定を変更したため再Prepareが必要です", announce=False)

        self.run_bg(lambda: self.client.update_depot(scenario_id, depot_id, payload), done)

    def _apply_selected_depot_to_vehicle_tab(self, depot_list: tk.Listbox) -> None:
        sel = depot_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        depot = self.dm_depots[idx] if 0 <= idx < len(self.dm_depots) else None
        if not depot:
            return
        depot_id = str(depot.get("id") or "").strip()
        if not depot_id:
            return
        self.open_fleet_window()
        self.fleet_depot_var.set(depot_id)
        self.v_depot_var.set(depot_id)
        self.refresh_vehicles()

    def show_vehicle_diagram(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(result: dict[str, Any]) -> None:
            self._open_vehicle_diagram_window(result)
            self.log_line("車両ダイヤグラムを表示しました")

        self.run_bg(lambda: self.client.get_optimization_result(scenario_id), done)

    def _open_vehicle_diagram_window(self, result: dict[str, Any]) -> None:
        trips = (result.get("dispatch_report") or {}).get("trips") or []
        trip_info: dict[str, dict] = {str(t.get("trip_id") or ""): t for t in trips}
        assignment: dict[str, list] = (result.get("solver_result") or {}).get("assignment") or {}
        unserved: list = (result.get("solver_result") or {}).get("unserved_tasks") or []

        win = tk.Toplevel(self.root)
        win.title("車両ダイヤグラム (最適化結果)")
        win.geometry("1200x620")

        # ── サマリ行 ──
        status = str(result.get("solver_status") or result.get("status") or "-")
        obj = result.get("objective_value")
        obj_str = f"{obj:.1f}" if isinstance(obj, (int, float)) else str(obj or "-")
        total_served = sum(len(v or []) for v in assignment.values())
        dep_id = (result.get("scope") or {}).get("depotId") or "-"
        svc_id = (result.get("scope") or {}).get("serviceId") or "-"
        ttk.Label(
            win,
            text=(
                f"営業所: {dep_id}  運行種別: {svc_id}  "
                f"status: {status}  目的関数値: {obj_str}  "
                f"配車便数: {total_served}  未配車便数: {len(unserved)}"
            ),
        ).pack(anchor="w", padx=6, pady=(6, 2))

        # ── 車両スケジュール表 ──
        cols = ("vehicle_id", "trip_count", "first_dep", "last_arr", "route_codes", "departures")
        wrap = ttk.Frame(win)
        wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=22)
        tree.heading("vehicle_id", text="車両ID")
        tree.heading("trip_count", text="便数")
        tree.heading("first_dep", text="初便発")
        tree.heading("last_arr", text="終便着")
        tree.heading("route_codes", text="担当系統")
        tree.heading("departures", text="発車時刻一覧")
        tree.column("vehicle_id", width=220, anchor="w")
        tree.column("trip_count", width=48, anchor="e")
        tree.column("first_dep", width=62, anchor="center")
        tree.column("last_arr", width=62, anchor="center")
        tree.column("route_codes", width=160, anchor="w")
        tree.column("departures", width=560, anchor="w")

        for vehicle_id in sorted(assignment.keys()):
            task_ids = sorted(
                assignment[vehicle_id] or [],
                key=lambda tid: str(trip_info.get(str(tid), {}).get("departure") or "99:99"),
            )
            if not task_ids:
                continue
            route_codes = sorted(set(
                str(trip_info.get(str(tid), {}).get("route_family_code") or
                    trip_info.get(str(tid), {}).get("route_id") or "")
                for tid in task_ids
            ))
            deps = [str(trip_info.get(str(tid), {}).get("departure") or "") for tid in task_ids]
            arrs = [str(trip_info.get(str(tid), {}).get("arrival") or "") for tid in task_ids]
            first_dep = deps[0] if deps else ""
            last_arr = arrs[-1] if arrs else ""
            dep_summary = "  ".join(deps[:10])
            if len(deps) > 10:
                dep_summary += f"  … ({len(deps)}便)"
            tree.insert("", tk.END, values=(
                vehicle_id, len(task_ids), first_dep, last_arr,
                "  ".join(route_codes[:5]), dep_summary,
            ))

        ysb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=tree.yview)
        xsb = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(fill=tk.BOTH, expand=True)

    def show_simulation_result(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(resp: dict[str, Any]) -> None:
            self._open_kv_window(f"Simulation結果: {scenario_id}", resp)
            self.log_line("Simulation結果を詳細ウィンドウで表示しました")

        self.run_bg(lambda: self.client.get_simulation_result(scenario_id), done)

    def show_optimization_result(self) -> None:
        scenario_id = self._selected_scenario_id()
        if not scenario_id:
            messagebox.showwarning("入力不足", "先にシナリオを選択してください")
            return

        def done(resp: dict[str, Any]) -> None:
            self._open_kv_window(f"Optimization結果: {scenario_id}", resp)
            self.log_line("Optimization結果を詳細ウィンドウで表示しました")

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
