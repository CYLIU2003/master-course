"""
バス運行可視化ツール（Tkinter）

最適化結果フォルダから、EV/エンジン区別付きの運行可視化図を生成する。

実行:
python tools/bus_operation_visualizer_tk.py
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Tuple

import pandas as pd

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Patch, Rectangle
from tools._visualizer_report_utils import (
    RunMeta,
    collect_run_meta,
    load_run_payloads,
    resolve_run_dir_input,
)


# 英語は Times New Roman、日本語は Meiryo を優先
matplotlib.rcParams["font.family"] = ["Times New Roman", "Meiryo"]
matplotlib.rcParams["axes.unicode_minus"] = False


@dataclass
class TimelineBundle:
    run_dir: Path
    events: pd.DataFrame
    vehicle_types: Dict[str, str]
    charging: pd.DataFrame
    refuel_events: pd.DataFrame
    delta_t_min: int
    horizon_minute: int
    horizon_max_minute: int
    summary_json: dict
    cost_detail_json: dict
    co2_detail_json: dict
    optimization_result_json: dict
    canonical_solver_result_json: dict
    kpi_summary_json: dict
    run_manifest_json: dict
    simulation_result_json: dict
    input_metadata: dict
    run_meta: RunMeta


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json_or_empty(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _build_summary_rows(bundle: TimelineBundle) -> List[Tuple[str, str]]:
    optimization = bundle.optimization_result_json or {}
    canonical = bundle.canonical_solver_result_json or {}
    summary = optimization.get("summary") if isinstance(optimization.get("summary"), dict) else {}
    cost_breakdown = optimization.get("cost_breakdown") if isinstance(optimization.get("cost_breakdown"), dict) else {}
    solution_validity = (
        optimization.get("solution_validity")
        if isinstance(optimization.get("solution_validity"), dict)
        else (
            summary.get("solution_validity")
            if isinstance(summary.get("solution_validity"), dict)
            else {}
        )
    )
    simulation_summary = (
        bundle.simulation_result_json.get("simulation_summary")
        if isinstance(bundle.simulation_result_json.get("simulation_summary"), dict)
        else {}
    )
    run_meta = bundle.run_meta

    status = str(run_meta.status or "UNKNOWN")
    objective = _safe_float(run_meta.objective_value, 0.0)
    solve_time_sec = _safe_float(run_meta.solve_time_sec, 0.0)
    unmet_trips = int(summary.get("trip_count_unserved") or 0)
    refuel_count = 0
    refuel_total_l = 0.0
    if not bundle.refuel_events.empty:
        refuel_count = len(bundle.refuel_events)
        refuel_total_l = float(pd.to_numeric(bundle.refuel_events["refuel_liters"], errors="coerce").fillna(0.0).sum())
    validity_badge = (
        "検証済み"
        if bool(solution_validity.get("validated_feasible"))
        else (
            f"暫定/無効 ({solution_validity.get('status_reason')})"
            if solution_validity
            else "未判定"
        )
    )

    rows = [
        ("入力種別", str(bundle.input_metadata.get("input_kind") or "run_dir")),
        ("読込フォルダ", str(bundle.run_dir)),
        ("比較bundle", str(bundle.input_metadata.get("report_bundle_dir") or "")),
        ("自動選択run", str(bundle.input_metadata.get("selected_run_id") or bundle.run_dir.name)),
        ("mode", str(run_meta.mode or optimization.get("mode") or "")),
        ("ステータス", status),
        ("exact / fallback", run_meta.exactness_label),
        ("termination reason", str(run_meta.termination_reason or canonical.get("termination_reason") or "")),
        ("plan source", str(run_meta.plan_source or ((canonical.get("metadata") or {}).get("source")) or "")),
        ("scenario_id", str(run_meta.scenario_id or optimization.get("scenario_id") or "")),
        ("prepared_input_id", str(run_meta.prepared_input_id or optimization.get("prepared_input_id") or "")),
        ("objective_mode", str(run_meta.objective_mode or optimization.get("objective_mode") or "")),
        ("営業所", str(run_meta.depot or ((optimization.get("scope") or {}).get("depotId")) or "")),
        ("運行種別", str(run_meta.service or ((optimization.get("scope") or {}).get("serviceId")) or "")),
        ("service_date", str(((optimization.get("prepared_scope_summary") or {}).get("service_date")) or "")),
        ("解の妥当性", validity_badge),
        ("目的関数値 [モデル単位]", f"{objective:.6f}"),
        ("求解時間 [秒]", f"{solve_time_sec:.6f}"),
        ("未割当便数 [便]", str(unmet_trips)),
        ("担当便数 [便]", str(int(summary.get("trip_count_served") or 0))),
        ("使用車両数 [台]", str(int(summary.get("vehicle_count_used") or 0))),
        ("補給イベント数 [件]", str(refuel_count)),
        ("補給総量 [L]", f"{refuel_total_l:.6f}"),
        ("総コスト [円]", f"{_safe_float(cost_breakdown.get('total_cost'), 0.0):.6f}"),
        ("復路ボーナス [円]", f"{_safe_float(cost_breakdown.get('return_leg_bonus'), 0.0):.6f}"),
        ("電力コスト [円]", f"{_safe_float(cost_breakdown.get('energy_cost'), 0.0):.6f}"),
        ("電力コスト基準", str(optimization.get("electricity_cost_basis") or "provisional_drive")),
        ("電力コスト(仮) [円]", f"{_safe_float(cost_breakdown.get('electricity_cost_provisional'), 0.0):.6f}"),
        ("電力コスト(充電実績) [円]", f"{_safe_float(cost_breakdown.get('electricity_cost_charged'), 0.0):.6f}"),
        ("燃料コスト [円]", f"{_safe_float(cost_breakdown.get('fuel_cost'), 0.0):.6f}"),
        ("デマンド料金 [円]", f"{_safe_float(cost_breakdown.get('demand_charge'), 0.0):.6f}"),
        ("電池劣化コスト [円]", f"{_safe_float(cost_breakdown.get('degradation_cost'), 0.0):.6f}"),
        ("総CO2排出量 [kg-CO2]", f"{_safe_float(cost_breakdown.get('total_co2_kg'), 0.0):.6f}"),
        ("CO2コスト [円]", f"{_safe_float(cost_breakdown.get('co2_cost'), 0.0):.6f}"),
        ("simulation_result 有無", "あり" if bundle.simulation_result_json else "なし"),
        ("simulation_result_path", str(run_meta.simulation_result_path or "")),
        ("simulation feasibility", str(simulation_summary.get("feasible") if simulation_summary else "未実行")),
    ]
    return rows


def _flatten_dict_for_details(prefix: str, value, out: List[Tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            _flatten_dict_for_details(key, v, out)
        return
    if isinstance(value, list):
        out.append((prefix, f"list[{len(value)}]"))
        return
    out.append((prefix, str(value)))


def _build_details_rows(bundle: TimelineBundle) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    _flatten_dict_for_details("入力メタデータ", bundle.input_metadata or {}, rows)
    _flatten_dict_for_details("run_overview", {
        "date": bundle.run_meta.date,
        "scenario_id": bundle.run_meta.scenario_id,
        "depot": bundle.run_meta.depot,
        "service": bundle.run_meta.service,
        "run_id": bundle.run_meta.run_id,
        "mode": bundle.run_meta.mode,
        "status": bundle.run_meta.status,
        "exactness": bundle.run_meta.exactness_label,
        "objective_value": bundle.run_meta.objective_value,
        "solve_time_sec": bundle.run_meta.solve_time_sec,
        "trip_count_served": bundle.run_meta.trip_count_served,
        "trip_count_unserved": bundle.run_meta.trip_count_unserved,
        "vehicle_count_used": bundle.run_meta.vehicle_count_used,
        "termination_reason": bundle.run_meta.termination_reason,
        "plan_source": bundle.run_meta.plan_source,
    }, rows)
    _flatten_dict_for_details("サマリー", bundle.summary_json or {}, rows)
    _flatten_dict_for_details("optimization_result", bundle.optimization_result_json or {}, rows)
    _flatten_dict_for_details("canonical_solver_result", bundle.canonical_solver_result_json or {}, rows)
    _flatten_dict_for_details("run_manifest", bundle.run_manifest_json or {}, rows)
    _flatten_dict_for_details("kpi_summary", bundle.kpi_summary_json or {}, rows)
    _flatten_dict_for_details("simulation_result", bundle.simulation_result_json or {}, rows)
    _flatten_dict_for_details("コスト内訳詳細", bundle.cost_detail_json or {}, rows)
    _flatten_dict_for_details("CO2内訳", bundle.co2_detail_json or {}, rows)
    if not bundle.refuel_events.empty:
        route_band_counts = (
            bundle.refuel_events.get("route_band_id", pd.Series(dtype=str))
            .fillna("")
            .astype(str)
            .str.strip()
        )
        route_band_counts = route_band_counts[route_band_counts != ""]
        if not route_band_counts.empty:
            for band_id, count in route_band_counts.value_counts().items():
                rows.append((f"補給イベント.route_band.{band_id}", str(int(count))))
        top_rows = bundle.refuel_events.head(10)
        for idx, r in top_rows.iterrows():
            rows.append(
                (
                    f"補給イベント.sample[{int(idx)}]",
                    (
                        f"vehicle={r.get('vehicle_id', '')}, "
                        f"type={r.get('vehicle_type', '')}, "
                        f"band={r.get('route_band_id', '')}, "
                        f"liters={_safe_float(r.get('refuel_liters', 0.0), 0.0):.3f}, "
                        f"time={r.get('time_hhmm', '')}"
                    ),
                )
            )
    return rows


def _build_raw_json_text(bundle: TimelineBundle) -> str:
    payload = {
        "input_metadata": bundle.input_metadata or {},
        "run_overview": {
            "date": bundle.run_meta.date,
            "scenario_id": bundle.run_meta.scenario_id,
            "depot": bundle.run_meta.depot,
            "service": bundle.run_meta.service,
            "run_id": bundle.run_meta.run_id,
            "mode": bundle.run_meta.mode,
            "status": bundle.run_meta.status,
            "exactness": bundle.run_meta.exactness_label,
            "objective_value": bundle.run_meta.objective_value,
            "solve_time_sec": bundle.run_meta.solve_time_sec,
            "trip_count_served": bundle.run_meta.trip_count_served,
            "trip_count_unserved": bundle.run_meta.trip_count_unserved,
            "vehicle_count_used": bundle.run_meta.vehicle_count_used,
            "termination_reason": bundle.run_meta.termination_reason,
            "plan_source": bundle.run_meta.plan_source,
        },
        "summary": bundle.summary_json or {},
        "optimization_result": bundle.optimization_result_json or {},
        "canonical_solver_result": bundle.canonical_solver_result_json or {},
        "run_manifest": bundle.run_manifest_json or {},
        "kpi_summary": bundle.kpi_summary_json or {},
        "simulation_result": bundle.simulation_result_json or {},
        "cost_breakdown_detail": bundle.cost_detail_json or {},
        "co2_breakdown": bundle.co2_detail_json or {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _read_csv_or_empty(path: Path, required_columns: List[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=required_columns)
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=required_columns)
    for col in required_columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def _safe_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _detect_delta_t_min(run_dir: Path, events: pd.DataFrame) -> int:
    json_path = run_dir / "vehicle_timelines.json"
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "delta_t_min" in payload:
                return _safe_int(payload.get("delta_t_min"), 15)
        except Exception:
            pass

    duration_slots = pd.to_numeric(events["duration_slots"], errors="coerce")
    duration_min = pd.to_numeric(events["duration_min"], errors="coerce")
    valid = events[(duration_slots.fillna(0) > 0) & (duration_min.fillna(0) > 0)].copy()
    if valid.empty:
        return 15
    valid_slots = pd.to_numeric(valid["duration_slots"], errors="coerce")
    valid_minutes = pd.to_numeric(valid["duration_min"], errors="coerce")
    ratio = (valid_minutes / valid_slots).median()
    return max(1, _safe_int(ratio, 15))


def _load_bundle(run_dir: Path) -> TimelineBundle:
    payloads = load_run_payloads(run_dir)
    gantt = _read_csv_or_empty(
        run_dir / "vehicle_timeline_gantt.csv",
        [
            "vehicle_id",
            "event_type",
            "state",
            "vehicle_type",
            "start_time_idx",
            "end_time_idx",
            "start_minute",
            "end_minute",
            "start_time",
            "end_time",
            "duration_slots",
            "duration_min",
            "band_id",
            "band_label",
            "route_id",
            "route_family_code",
            "trip_id",
            "charger_id",
            "charge_power_kw",
            "refuel_liters",
        ],
    )

    if gantt.empty:
        raise ValueError("vehicle_timeline_gantt.csv が空か、存在しません。")

    if "event_type" not in gantt.columns or gantt["event_type"].isna().all():
        gantt["event_type"] = gantt.get("state", pd.Series(dtype=str))
    gantt["event_type"] = gantt["event_type"].astype(str).str.lower().str.strip()
    gantt = gantt[gantt["event_type"].astype(str).str.lower().isin(["service", "deadhead", "charge", "refuel"])].copy()
    gantt["start_time_idx"] = pd.to_numeric(gantt["start_time_idx"], errors="coerce")
    gantt["end_time_idx"] = pd.to_numeric(gantt["end_time_idx"], errors="coerce")

    if ("start_minute" not in gantt.columns or gantt["start_minute"].isna().all()) and "start_time" in gantt.columns:
        start_ts = pd.to_datetime(gantt["start_time"], errors="coerce")
        gantt["start_minute"] = start_ts.dt.hour.fillna(0).astype(int) * 60 + start_ts.dt.minute.fillna(0).astype(int)
    if ("end_minute" not in gantt.columns or gantt["end_minute"].isna().all()) and "end_time" in gantt.columns:
        end_ts = pd.to_datetime(gantt["end_time"], errors="coerce")
        gantt["end_minute"] = end_ts.dt.hour.fillna(0).astype(int) * 60 + end_ts.dt.minute.fillna(0).astype(int)

    if "start_minute" not in gantt.columns or gantt["start_minute"].isna().all():
        gantt["start_minute"] = gantt["start_time_idx"].fillna(0) * 15
    if "end_minute" not in gantt.columns or gantt["end_minute"].isna().all():
        gantt["end_minute"] = (gantt["end_time_idx"].fillna(0) + 1) * 15

    gantt["start_minute"] = pd.to_numeric(gantt["start_minute"], errors="coerce").fillna(0).astype(int)
    gantt["end_minute"] = pd.to_numeric(gantt["end_minute"], errors="coerce").fillna(gantt["start_minute"]).astype(int)
    if gantt["start_time_idx"].isna().all():
        gantt["start_time_idx"] = (gantt["start_minute"] // 15).astype(int)
    else:
        gantt["start_time_idx"] = gantt["start_time_idx"].fillna(gantt["start_minute"] // 15).astype(int)
    if gantt["end_time_idx"].isna().all():
        gantt["end_time_idx"] = ((gantt["end_minute"] - 1).clip(lower=0) // 15).astype(int)
    else:
        gantt["end_time_idx"] = gantt["end_time_idx"].fillna(((gantt["end_minute"] - 1).clip(lower=0) // 15)).astype(int)

    schedule = _read_csv_or_empty(
        run_dir / "vehicle_schedule.csv",
        ["vehicle_id", "vehicle_type", "task_id"],
    )

    vehicle_types: Dict[str, str] = {}
    if not schedule.empty:
        sub = schedule[["vehicle_id", "vehicle_type"]].dropna().copy()
        sub["vehicle_type"] = sub["vehicle_type"].astype(str).str.upper().str.strip()
        sub = sub[sub["vehicle_type"] != ""]
        if not sub.empty:
            # Use mode to robustly classify each vehicle.
            mode = sub.groupby("vehicle_id")["vehicle_type"].agg(
                lambda s: s.mode().iat[0] if not s.mode().empty else (s.iloc[0] if not s.empty else "UNKNOWN")
            )
            vehicle_types = {str(k): str(v) for k, v in mode.items()}

    charging = _read_csv_or_empty(
        run_dir / "charging_schedule.csv",
        ["vehicle_id", "time_idx", "p_charge_kw", "z_charge", "charger_id"],
    )
    if not charging.empty:
        charging["time_idx"] = pd.to_numeric(charging["time_idx"], errors="coerce").fillna(0).astype(int)
        charging["p_charge_kw"] = pd.to_numeric(charging["p_charge_kw"], errors="coerce").fillna(0.0)

    delta_t_min = _detect_delta_t_min(run_dir, gantt)

    refuel_events = _read_csv_or_empty(
        run_dir / "refuel_events.csv",
        [
            "vehicle_id",
            "vehicle_type",
            "depot_id",
            "route_band_id",
            "route_band_label",
            "slot_index",
            "event_time",
            "time_hhmm",
            "refuel_liters",
        ],
    )
    if not refuel_events.empty:
        refuel_events["slot_index"] = pd.to_numeric(refuel_events["slot_index"], errors="coerce").fillna(0).astype(int)
        refuel_events["refuel_liters"] = pd.to_numeric(refuel_events["refuel_liters"], errors="coerce").fillna(0.0)
        # Backward-compatible minute reconstruction when event_time is missing.
        if "event_time" not in refuel_events.columns or refuel_events["event_time"].isna().all():
            refuel_events["event_time"] = pd.NA
        refuel_events["event_minute"] = refuel_events["slot_index"] * delta_t_min
        if "vehicle_type" in refuel_events.columns:
            fallback_types = (
                refuel_events[["vehicle_id", "vehicle_type"]]
                .dropna()
                .assign(vehicle_id=lambda d: d["vehicle_id"].astype(str), vehicle_type=lambda d: d["vehicle_type"].astype(str).str.upper().str.strip())
            )
            for _, row in fallback_types.iterrows():
                vid = str(row["vehicle_id"])
                vtype = str(row["vehicle_type"])
                if vid and vtype and vid not in vehicle_types:
                    vehicle_types[vid] = vtype
    else:
        refuel_events = pd.DataFrame(
            columns=[
                "vehicle_id",
                "vehicle_type",
                "depot_id",
                "route_band_id",
                "route_band_label",
                "slot_index",
                "event_time",
                "time_hhmm",
                "refuel_liters",
                "event_minute",
            ]
        )

    min_from_events = _safe_int(pd.to_numeric(gantt["start_minute"], errors="coerce").min(), 0)
    max_from_events = _safe_int(pd.to_numeric(gantt["end_minute"], errors="coerce").max(), 24 * 60)

    if not charging.empty:
        c_min = _safe_int(charging["time_idx"].min(), 0) * delta_t_min
        c_max = (_safe_int(charging["time_idx"].max(), 0) + 1) * delta_t_min
        horizon_min = min(min_from_events, c_min)
        horizon_max = max(max_from_events, c_max)
    else:
        horizon_min = min_from_events
        horizon_max = max_from_events

    # Round outward to full hours for cleaner publication axes.
    horizon_min = (horizon_min // 60) * 60
    horizon_max = ((horizon_max + 59) // 60) * 60

    return TimelineBundle(
        run_dir=run_dir,
        events=gantt,
        vehicle_types=vehicle_types,
        charging=charging,
        refuel_events=refuel_events,
        delta_t_min=delta_t_min,
        horizon_minute=horizon_min,
        horizon_max_minute=horizon_max,
        summary_json=payloads["summary"],
        cost_detail_json=payloads["cost_breakdown_detail"],
        co2_detail_json=payloads["co2_breakdown"],
        optimization_result_json=payloads["optimization_result"],
        canonical_solver_result_json=payloads["canonical_solver_result"],
        kpi_summary_json=payloads["kpi_summary"],
        run_manifest_json=payloads["run_manifest"],
        simulation_result_json=payloads["simulation_result"],
        input_metadata={"input_kind": "run_dir"},
        run_meta=collect_run_meta(run_dir),
    )


def _vehicle_label(vehicle_id: str, vehicle_type: str, idx: int) -> str:
    t = vehicle_type.upper()
    if t == "BEV" or "EV" in t:
        return f"EV-{idx:02d}"
    if t in {"ICE", "ENGINE", "DIESEL"}:
        return f"ENG-{idx:02d}"
    return f"BUS-{idx:02d}"


def _type_key(vehicle_type: str) -> int:
    t = vehicle_type.upper()
    if t == "BEV" or "EV" in t:
        return 0
    if t in {"ICE", "ENGINE", "DIESEL"}:
        return 1
    return 2


def _compute_station_segments(service_segments: List[Tuple[float, float]], start: float, end: float) -> List[Tuple[float, float]]:
    if not service_segments:
        return [(start, end)]
    segments = []
    cursor = start
    for s0, s1 in sorted(service_segments):
        if s0 > cursor:
            segments.append((cursor, min(s0, end)))
        cursor = max(cursor, s1)
    if cursor < end:
        segments.append((cursor, end))
    return [(a, b) for a, b in segments if b - a > 0]


def _build_vehicle_order(bundle: TimelineBundle, only_assigned: bool) -> List[str]:
    if only_assigned:
        ids = sorted(bundle.events["vehicle_id"].astype(str).unique().tolist())
    else:
        all_ids = set(bundle.events["vehicle_id"].astype(str).unique().tolist())
        all_ids.update(bundle.vehicle_types.keys())
        all_ids.update(bundle.charging["vehicle_id"].astype(str).unique().tolist())
        if not bundle.refuel_events.empty:
            all_ids.update(bundle.refuel_events["vehicle_id"].astype(str).unique().tolist())
        ids = sorted(all_ids)

    ids.sort(key=lambda vid: (_type_key(bundle.vehicle_types.get(vid, "UNKNOWN")), vid))
    return ids


def _make_ticks(horizon_min: int, horizon_max: int) -> List[int]:
    ticks = []
    cur = horizon_min
    while cur <= horizon_max:
        ticks.append(cur)
        cur += 240  # every 4 hours
    if ticks[-1] != horizon_max:
        ticks.append(horizon_max)
    return ticks


def _format_hhmm(minute: int) -> str:
    h = (minute // 60) % 24
    m = minute % 60
    return f"{h:02d}:{m:02d}"


def _route_color(route_key: str) -> str:
    palette = [
        "#1d4ed8",
        "#0f766e",
        "#b45309",
        "#be123c",
        "#6d28d9",
        "#0369a1",
        "#c2410c",
        "#7c3aed",
    ]
    normalized = str(route_key or "").strip() or "service"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return palette[int(digest[:8], 16) % len(palette)]


def _event_bar_style(row: pd.Series) -> tuple[str, str, str]:
    event_type = str(row.get("event_type") or row.get("state") or "").strip().lower()
    if event_type == "service":
        route_key = (
            str(row.get("band_id") or "").strip()
            or str(row.get("route_family_code") or "").strip()
            or str(row.get("route_id") or "").strip()
            or str(row.get("trip_id") or "").strip()
        )
        return _route_color(route_key), "#0f172a", "#ffffff"
    if event_type == "deadhead":
        return "#cbd5e1", "#475569", "#0f172a"
    if event_type == "charge":
        return "#86efac", "#15803d", "#14532d"
    if event_type == "refuel":
        return "#d9f99d", "#65a30d", "#365314"
    return "#e5e7eb", "#6b7280", "#111827"


def _event_bar_label(row: pd.Series) -> str:
    event_type = str(row.get("event_type") or row.get("state") or "").strip().lower()
    if event_type == "service":
        for candidate in (
            row.get("band_label"),
            row.get("band_id"),
            row.get("route_family_code"),
            row.get("route_id"),
            row.get("trip_id"),
        ):
            text = str(candidate or "").strip()
            if text:
                return text
        return "運用"
    if event_type == "deadhead":
        return "回送"
    if event_type == "charge":
        try:
            power_kw = float(row.get("charge_power_kw") or 0.0)
        except (TypeError, ValueError):
            power_kw = 0.0
        return f"充電 {power_kw:.0f}kW" if power_kw > 0.0 else "充電"
    if event_type == "refuel":
        try:
            liters = float(row.get("refuel_liters") or 0.0)
        except (TypeError, ValueError):
            liters = 0.0
        return f"給油 {liters:.0f}L" if liters > 0.0 else "給油"
    return event_type or "event"


def _plot_style_1(bundle: TimelineBundle, vehicle_ids: List[str], only_assigned: bool):
    fig_h = max(4.0, len(vehicle_ids) * 0.34 + 1.6)
    fig, ax = plt.subplots(figsize=(12.0, fig_h), dpi=160)

    ytick_labels = []
    ytick_pos = []

    for i, vid in enumerate(vehicle_ids):
        vtype = bundle.vehicle_types.get(vid, "UNKNOWN").upper()
        if vtype not in {"BEV", "ICE"}:
            if "EV" in vtype:
                vtype = "BEV"
            elif any(x in vtype for x in ["ICE", "ENGINE", "DIESEL"]):
                vtype = "ICE"
            else:
                vtype = "UNKNOWN"

        lane_events = bundle.events[bundle.events["vehicle_id"].astype(str) == vid].copy()
        lane_events = lane_events.sort_values(["start_minute", "end_minute", "event_type"])

        ax.barh(
            i,
            bundle.horizon_max_minute - bundle.horizon_minute,
            left=bundle.horizon_minute,
            height=0.72,
            color="#ffffff",
            edgecolor="#d4d4d8",
            linewidth=0.5,
            zorder=0,
        )

        for _, row in lane_events.iterrows():
            start_minute = float(row["start_minute"])
            end_minute = float(row["end_minute"])
            width = max(0.5, end_minute - start_minute)
            fill, edge, text_color = _event_bar_style(row)
            event_type = str(row.get("event_type") or row.get("state") or "").strip().lower()
            linestyle = "--" if event_type == "deadhead" else "solid"
            ax.barh(
                i,
                width,
                left=start_minute,
                height=0.72,
                color=fill,
                edgecolor=edge,
                linewidth=0.8,
                linestyle=linestyle,
                zorder=2,
            )
            label = _event_bar_label(row)
            if width >= 36:
                max_chars = max(int((width - 8) // 8), 3)
                if len(label) > max_chars:
                    label = label[: max_chars - 1] + "…"
                ax.text(
                    start_minute + 2,
                    i,
                    label,
                    va="center",
                    ha="left",
                    fontsize=7.5,
                    color=text_color,
                    zorder=3,
                    clip_on=True,
                )

        ytick_pos.append(i)
        ytick_labels.append(f"{_vehicle_label(vid, vtype, i + 1)}  {vid}")

    ticks = _make_ticks(bundle.horizon_minute, bundle.horizon_max_minute)
    ax.set_xlim(bundle.horizon_minute, bundle.horizon_max_minute)
    ax.set_xticks(ticks)
    ax.set_xticklabels([_format_hhmm(t) for t in ticks], fontsize=10)
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(ytick_labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("時刻 [時:分]", fontsize=12)
    ax.set_ylabel("車両番号 [台]", fontsize=12)
    ax.grid(axis="x", color="#d0d0d0", linewidth=0.5)
    title_suffix = "（割当車両のみ）" if only_assigned else "（全車両）"
    ax.set_title(f"車両別 運用・回送・充電タイムライン {title_suffix}", fontsize=13)

    legend_items = [
        Patch(facecolor="#1d4ed8", edgecolor="#0f172a", label="運用中（バー内ラベルが路線）"),
        Patch(facecolor="#cbd5e1", edgecolor="#475569", label="回送"),
        Patch(facecolor="#86efac", edgecolor="#15803d", label="充電"),
        Patch(facecolor="#d9f99d", edgecolor="#65a30d", label="給油"),
    ]
    ax.legend(handles=legend_items, loc="upper right", frameon=True, fontsize=10)

    fig.tight_layout()
    return fig


def _plot_style_2(bundle: TimelineBundle, vehicle_ids: List[str], only_assigned: bool):
    fig_h = max(4.0, len(vehicle_ids) * 0.28 + 1.8)
    fig, ax = plt.subplots(figsize=(12.0, fig_h), dpi=160)

    max_power = float(bundle.charging["p_charge_kw"].max()) if not bundle.charging.empty else 0.0
    if max_power <= 0:
        max_power = 1.0

    cmap = cm.get_cmap("Greens")

    ytick_labels = []
    ytick_pos = []

    charging_map: Dict[Tuple[str, int], float] = {}
    if not bundle.charging.empty:
        charging_work = bundle.charging.copy()
        charging_work["vehicle_id_norm"] = charging_work["vehicle_id"].astype(str)
        agg = charging_work.groupby(["vehicle_id_norm", "time_idx"], as_index=False)["p_charge_kw"].max()
        for _, r in agg.iterrows():
            charging_map[(str(r["vehicle_id_norm"]), int(r["time_idx"]))] = float(r["p_charge_kw"])

    refuel_map: Dict[str, List[Tuple[float, float]]] = {}
    if not bundle.refuel_events.empty:
        refuel_work = bundle.refuel_events.copy()
        refuel_work["vehicle_id_norm"] = refuel_work["vehicle_id"].astype(str)
        refuel_work["event_minute"] = pd.to_numeric(refuel_work.get("event_minute"), errors="coerce")
        refuel_work["refuel_liters"] = pd.to_numeric(refuel_work.get("refuel_liters"), errors="coerce").fillna(0.0)
        for _, r in refuel_work.iterrows():
            minute = float(r["event_minute"]) if pd.notna(r["event_minute"]) else float(r.get("slot_index", 0)) * float(bundle.delta_t_min)
            liters = float(r["refuel_liters"])
            refuel_map.setdefault(str(r["vehicle_id_norm"]), []).append((minute, liters))

    for i, vid in enumerate(vehicle_ids):
        vtype = bundle.vehicle_types.get(vid, "UNKNOWN").upper()

        lane_events = bundle.events[bundle.events["vehicle_id"].astype(str) == vid].copy()
        lane_events = lane_events.sort_values(["start_minute", "end_minute"])

        # Gray road blocks
        for _, r in lane_events.iterrows():
            x0 = float(r["start_minute"])
            x1 = float(r["end_minute"])
            ax.add_patch(
                Rectangle(
                    (x0, i - 0.35),
                    max(0.5, x1 - x0),
                    0.7,
                    facecolor="#d7d7d7",
                    edgecolor="none",
                    zorder=1,
                )
            )

        # Green charging blocks at slot resolution
        slot = bundle.delta_t_min
        start_idx = bundle.horizon_minute // slot
        end_idx = bundle.horizon_max_minute // slot
        for t_idx in range(start_idx, end_idx + 1):
            p = charging_map.get((vid, t_idx), 0.0)
            if p <= 0:
                continue
            ratio = max(0.0, min(1.0, p / max_power))
            color = cmap(0.25 + 0.7 * ratio)
            ax.add_patch(
                Rectangle(
                    (t_idx * slot, i - 0.35),
                    slot,
                    0.7,
                    facecolor=color,
                    edgecolor="white",
                    linewidth=0.2,
                    zorder=2,
                )
            )

        # ICE refuel markers (diamond), scaled by liters.
        for minute, liters in refuel_map.get(vid, []):
            if minute < bundle.horizon_minute or minute > bundle.horizon_max_minute:
                continue
            size = 28.0 + min(max(liters, 0.0), 80.0) * 1.6
            ax.scatter(
                [minute],
                [i],
                marker="D",
                s=size,
                c="#6cab2f",
                edgecolors="#3f7d1b",
                linewidths=0.8,
                zorder=3,
            )

        ytick_pos.append(i)
        ytick_labels.append(_vehicle_label(vid, vtype, i + 1))

    ticks = _make_ticks(bundle.horizon_minute, bundle.horizon_max_minute)
    ax.set_xlim(bundle.horizon_minute, bundle.horizon_max_minute)
    ax.set_xticks(ticks)
    ax.set_xticklabels([_format_hhmm(t) for t in ticks], fontsize=10)
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(ytick_labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("時刻 [時:分]", fontsize=12)
    ax.set_ylabel("車両番号 [台]", fontsize=12)
    ax.grid(axis="x", color="#d0d0d0", linewidth=0.5)
    title_suffix = "（割当車両のみ）" if only_assigned else "（全車両）"
    ax.set_title(f"運行・充電計画 {title_suffix}", fontsize=13)

    legend_items = [
        Patch(facecolor="#d7d7d7", edgecolor="none", label="走行中"),
        Patch(facecolor=cmap(0.85), edgecolor="none", label="充電中（出力比が高いほど濃色）"),
        Patch(facecolor="#6cab2f", edgecolor="#3f7d1b", label="補給イベント（菱形マーカー）"),
    ]
    ax.legend(handles=legend_items, loc="upper right", frameon=True, fontsize=10)

    fig.tight_layout()
    return fig


class BusOperationVisualizerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("バス運行可視化ツール")
        self.root.geometry("1420x920")

        self.bundle: TimelineBundle | None = None
        self.fig1 = None
        self.fig2 = None
        self.canvas1 = None
        self.canvas2 = None
        self.summary_tree = None
        self.detail_tree = None
        self.raw_text = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.run_dir_var = tk.StringVar(value="")
        ttk.Label(top, text="実行結果 / comparison bundle:").pack(side="left", padx=(0, 6))
        ttk.Entry(top, textvariable=self.run_dir_var, width=95).pack(side="left", padx=(0, 6), fill="x", expand=True)
        ttk.Button(top, text="参照", command=self._on_browse).pack(side="left", padx=4)
        ttk.Button(top, text="読込", command=self._on_load).pack(side="left", padx=4)

        self.only_assigned_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="割当車両のみ表示", variable=self.only_assigned_var).pack(side="left", padx=(12, 4))

        self.max_buses_var = tk.IntVar(value=45)
        ttk.Label(top, text="最大表示車両数 [台]:").pack(side="left", padx=(12, 4))
        ttk.Spinbox(top, from_=5, to=300, width=6, textvariable=self.max_buses_var).pack(side="left", padx=2)

        ttk.Button(top, text="描画", command=self._on_render).pack(side="left", padx=(12, 4))
        ttk.Button(top, text="PNG保存", command=lambda: self._on_save("png")).pack(side="left", padx=4)
        ttk.Button(top, text="SVG保存", command=lambda: self._on_save("svg")).pack(side="left", padx=4)
        ttk.Button(top, text="PDF保存", command=lambda: self._on_save("pdf")).pack(side="left", padx=4)

        info = (
            "フォント方針: 英語=Times New Roman / 日本語=Meiryo | "
            "EVとエンジン車はラベルとハッチで識別"
        )
        ttk.Label(self.root, text=info).pack(fill="x", padx=10)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_summary = ttk.Frame(self.nb)
        self.tab_details = ttk.Frame(self.nb)
        self.tab_raw = ttk.Frame(self.nb)
        self.tab1 = ttk.Frame(self.nb)
        self.tab2 = ttk.Frame(self.nb)
        self.nb.add(self.tab_summary, text="サマリー")
        self.nb.add(self.tab_details, text="詳細")
        self.nb.add(self.tab_raw, text="生JSON")
        self.nb.add(self.tab1, text="図A: ガント表示")
        self.nb.add(self.tab2, text="図B: 充電強度")

        self._build_info_tabs()

    def _build_info_tabs(self) -> None:
        self.summary_tree = ttk.Treeview(self.tab_summary, columns=("key", "value"), show="headings")
        self.summary_tree.heading("key", text="項目")
        self.summary_tree.heading("value", text="値")
        self.summary_tree.column("key", width=280, anchor="w")
        self.summary_tree.column("value", width=760, anchor="w")
        self.summary_tree.pack(fill="both", expand=True)

        self.detail_tree = ttk.Treeview(self.tab_details, columns=("key", "value"), show="headings")
        self.detail_tree.heading("key", text="項目")
        self.detail_tree.heading("value", text="値")
        self.detail_tree.column("key", width=420, anchor="w")
        self.detail_tree.column("value", width=620, anchor="w")
        self.detail_tree.pack(fill="both", expand=True)

        self.raw_text = ScrolledText(self.tab_raw, wrap=tk.NONE)
        self.raw_text.pack(fill="both", expand=True)

    def _populate_info_tabs(self) -> None:
        if self.bundle is None:
            return

        if self.summary_tree is not None:
            for row_id in self.summary_tree.get_children():
                self.summary_tree.delete(row_id)
            for key, value in _build_summary_rows(self.bundle):
                self.summary_tree.insert("", tk.END, values=(key, value))

        if self.detail_tree is not None:
            for row_id in self.detail_tree.get_children():
                self.detail_tree.delete(row_id)
            for key, value in _build_details_rows(self.bundle):
                self.detail_tree.insert("", tk.END, values=(key, value))

        if self.raw_text is not None:
            self.raw_text.delete("1.0", tk.END)
            self.raw_text.insert("1.0", _build_raw_json_text(self.bundle))

    def _on_browse(self) -> None:
        selected = filedialog.askdirectory(title="最適化 run フォルダまたは comparison bundle を選択")
        if selected:
            self.run_dir_var.set(selected)

    def _on_load(self) -> None:
        path_text = self.run_dir_var.get().strip()
        if not path_text:
            messagebox.showwarning("入力不足", "実行結果フォルダを指定してください。")
            return
        input_dir = Path(path_text)
        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("不正なフォルダ", "指定フォルダが存在しません。")
            return

        try:
            run_dir, input_metadata = resolve_run_dir_input(input_dir)
            self.bundle = _load_bundle(run_dir)
            self.bundle.input_metadata.update(input_metadata)
            self.bundle.run_meta = collect_run_meta(run_dir)
        except Exception as exc:
            messagebox.showerror("読込失敗", str(exc))
            return

        messagebox.showinfo(
            "読込完了",
            f"入力フォルダ:\n{input_dir}\n\n"
            f"読込run:\n{run_dir}\n\n"
            f"イベント数 [件]: {len(self.bundle.events):,}\n"
            f"車種情報付き車両数 [台]: {len(self.bundle.vehicle_types):,}\n"
            f"充電レコード数 [行]: {len(self.bundle.charging):,}",
        )
        self._populate_info_tabs()

    def _current_vehicle_ids(self) -> List[str]:
        if self.bundle is None:
            return []
        ids = _build_vehicle_order(self.bundle, only_assigned=self.only_assigned_var.get())
        max_n = max(1, int(self.max_buses_var.get()))
        return ids[:max_n]

    def _clear_canvas(self, tab: ttk.Frame, old_canvas):
        if old_canvas is not None:
            old_canvas.get_tk_widget().destroy()
        for child in tab.winfo_children():
            child.destroy()

    def _draw_figure(self, tab: ttk.Frame, figure):
        canvas = FigureCanvasTkAgg(figure, master=tab)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        return canvas

    def _on_render(self) -> None:
        if self.bundle is None:
            messagebox.showwarning("データなし", "先に読込を実行してください。")
            return

        vehicle_ids = self._current_vehicle_ids()
        if not vehicle_ids:
            messagebox.showwarning("車両なし", "描画対象の車両がありません。")
            return

        if self.fig1 is not None:
            plt.close(self.fig1)
        if self.fig2 is not None:
            plt.close(self.fig2)

        self.fig1 = _plot_style_1(self.bundle, vehicle_ids, self.only_assigned_var.get())
        self.fig2 = _plot_style_2(self.bundle, vehicle_ids, self.only_assigned_var.get())

        self._clear_canvas(self.tab1, self.canvas1)
        self._clear_canvas(self.tab2, self.canvas2)

        self.canvas1 = self._draw_figure(self.tab1, self.fig1)
        self.canvas2 = self._draw_figure(self.tab2, self.fig2)

    def _on_save(self, ext: str) -> None:
        if self.bundle is None or self.fig1 is None or self.fig2 is None:
            messagebox.showwarning("図が未作成", "先に読込と描画を実行してください。")
            return

        output_dir = self.bundle.run_dir / "figures"
        output_dir.mkdir(parents=True, exist_ok=True)

        p1 = output_dir / f"bus_operation_figure_a.{ext}"
        p2 = output_dir / f"bus_operation_figure_b.{ext}"

        self.fig1.savefig(p1, dpi=300, bbox_inches="tight")
        self.fig2.savefig(p2, dpi=300, bbox_inches="tight")

        messagebox.showinfo("保存完了", f"保存先:\n{p1}\n{p2}")


def main() -> None:
    root = tk.Tk()
    app = BusOperationVisualizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
