"""
data_loader.py — CSV / JSON 入力読込 → ProblemData 変換

仕様書 §14.1 担当。
  - CSV / JSON を読み込み、data_schema の内部データクラスへ変換する
  - 欠損・型・単位整合を検証する
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

pd = None

try:
    import pandas as pd

    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False

from .data_schema import (
    Charger,
    ElectricityPrice,
    ProblemData,
    PVProfile,
    Site,
    Task,
    TravelConnection,
    Vehicle,
    VehicleChargerCompat,
    VehicleTaskCompat,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _na(val: Any) -> Optional[float]:
    """空文字・NaN → None、それ以外は float に変換"""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "none", "na"):
        return None
    return float(s)


def _bool_col(val: Any) -> bool:
    """文字列 'true'/'false' → bool"""
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def _read_csv(path: Path) -> List[Dict[str, str]]:
    """pandas なしでも動く簡易 CSV 読み込み"""
    if _PD_AVAILABLE:
        assert pd is not None
        df = pd.read_csv(path, dtype=str).fillna("")
        return df.to_dict(orient="records")
    rows: List[Dict[str, str]] = []
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    headers = [h.strip() for h in lines[0].split(",")]
    for line in lines[1:]:
        vals = [v.strip() for v in line.split(",")]
        rows.append(dict(zip(headers, vals)))
    return rows


def _load_required_csv_path(root: Path, paths: Dict[str, str], key: str) -> Path:
    rel = paths.get(key)
    if not rel:
        raise FileNotFoundError(f"config.paths['{key}'] is required")
    resolved = root / rel
    if not resolved.exists():
        raise FileNotFoundError(f"Required CSV not found for '{key}': {resolved}")
    return resolved


def _rebuild_from_build_inputs(
    data: ProblemData,
    cfg: Dict[str, Any],
    config_path: str | Path,
    dispatch_cfg: Dict[str, Any],
) -> None:
    """Use src.pipeline.build_inputs outputs as the canonical trip/arc source."""
    from src.pipeline.build_inputs import build_inputs
    from src.preprocess.trip_converter import (
        build_vehicle_task_compat,
        convert_deadhead_arcs_to_connections,
        convert_trips_to_tasks,
    )

    built = build_inputs(str(config_path))
    trips = built.get("trips", [])
    arcs = built.get("deadhead_arcs", [])

    delta_t_min = float(cfg.get("time_step_min", 15))
    start_time = str(cfg.get("start_time", "05:00"))
    default_penalty = float(dispatch_cfg.get("default_penalty_unserved", 10000.0))
    replace_tasks = bool(dispatch_cfg.get("replace_tasks_from_build_inputs", True))

    if replace_tasks and trips:
        data.tasks = convert_trips_to_tasks(
            trips,
            start_time=start_time,
            delta_t_min=delta_t_min,
            default_penalty=default_penalty,
        )
        if not data.vehicle_task_compat:
            data.vehicle_task_compat = build_vehicle_task_compat(
                data.vehicles, data.tasks
            )

    data.travel_connections = convert_deadhead_arcs_to_connections(
        arcs,
        delta_t_min=delta_t_min,
    )
    setattr(
        data,
        "_dispatch_preprocess_report",
        {
            "source": "build_inputs",
            "trip_count": len(trips),
            "edge_count": len(arcs),
            "generated_connections": len(data.travel_connections),
            "vehicle_types": tuple(),
            "warnings": tuple(),
            "replace_tasks": replace_tasks,
        },
    )


def _resolve_optional_path(root: Path, path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    candidate = root / path_str
    return candidate if candidate.exists() else None


def _load_turnaround_rules_csv(path: Optional[Path]) -> Dict[str, int]:
    if path is None:
        return {}
    rows = _read_csv(path)
    rules: Dict[str, int] = {}
    for r in rows:
        stop_id = str(r.get("stop_id", "")).strip()
        if not stop_id:
            continue
        try:
            mins = int(float(r.get("min_turnaround_min", 0) or 0))
        except (TypeError, ValueError):
            mins = 0
        rules[stop_id] = max(0, mins)
    return rules


def _load_deadhead_rules_csv(path: Optional[Path]) -> Dict[tuple[str, str], int]:
    if path is None:
        return {}
    rows = _read_csv(path)
    rules: Dict[tuple[str, str], int] = {}
    for r in rows:
        from_stop = str(r.get("from_stop", r.get("from_stop_id", ""))).strip()
        to_stop = str(r.get("to_stop", r.get("to_stop_id", ""))).strip()
        if not from_stop or not to_stop or from_stop == to_stop:
            continue
        try:
            mins = int(float(r.get("travel_time_min", 0) or 0))
        except (TypeError, ValueError):
            mins = 0
        # current dispatch context API treats 0 as "no rule" for different stops
        rules[(from_stop, to_stop)] = max(1, mins)
    return rules


# ---------------------------------------------------------------------------
# 個別ローダー
# ---------------------------------------------------------------------------


def load_vehicles(path: Path) -> List[Vehicle]:
    rows = _read_csv(path)
    vehicles: List[Vehicle] = []
    for r in rows:
        v = Vehicle(
            vehicle_id=r["vehicle_id"],
            vehicle_type=r["vehicle_type"].upper(),
            home_depot=r["home_depot"],
            battery_capacity=_na(r.get("battery_capacity")),
            soc_init=_na(r.get("soc_init")),
            soc_min=_na(r.get("soc_min")),
            soc_max=_na(r.get("soc_max")),
            soc_target_end=_na(r.get("soc_target_end")),
            charge_power_max=_na(r.get("charge_power_max")),
            discharge_power_max=_na(r.get("discharge_power_max")),
            fixed_use_cost=float(r.get("fixed_use_cost") or 0.0),
            max_operating_time=float(r.get("max_operating_time") or 24.0),
            max_distance=float(r.get("max_distance") or 9999.0),
            charge_efficiency=float(r.get("charge_efficiency") or 0.95),
            fuel_tank_capacity=_na(r.get("fuel_tank_capacity")),
            fuel_cost_coeff=float(r.get("fuel_cost_coeff") or 145.0),
            co2_emission_coeff=float(r.get("co2_emission_coeff") or 2.58),
        )
        vehicles.append(v)
    return vehicles


def load_tasks(path: Path) -> List[Task]:
    rows = _read_csv(path)
    tasks: List[Task] = []
    for r in rows:
        rt = r.get("required_vehicle_type", "").strip()
        t = Task(
            task_id=r["task_id"],
            start_time_idx=int(r["start_time_idx"]),
            end_time_idx=int(r["end_time_idx"]),
            origin=r["origin"],
            destination=r["destination"],
            distance_km=float(r.get("distance_km") or 0.0),
            energy_required_kwh_bev=float(r.get("energy_required_kwh_bev") or 0.0),
            fuel_required_liter_ice=float(r.get("fuel_required_liter_ice") or 0.0),
            required_vehicle_type=rt if rt else None,
            demand_cover=_bool_col(r.get("demand_cover", "true")),
            penalty_unserved=float(r.get("penalty_unserved") or 10000.0),
        )
        tasks.append(t)
    return tasks


def load_chargers(path: Path) -> List[Charger]:
    rows = _read_csv(path)
    chargers: List[Charger] = []
    for r in rows:
        c = Charger(
            charger_id=r["charger_id"],
            site_id=r["site_id"],
            power_max_kw=float(r["power_max_kw"]),
            efficiency=float(r.get("efficiency") or 0.95),
            power_min_kw=float(r.get("power_min_kw") or 0.0),
        )
        chargers.append(c)
    return chargers


def load_sites(path: Path) -> List[Site]:
    rows = _read_csv(path)
    sites: List[Site] = []
    for r in rows:
        s = Site(
            site_id=r["site_id"],
            site_type=r["site_type"],
            grid_import_limit_kw=float(r.get("grid_import_limit_kw") or 9999.0),
            contract_demand_limit_kw=float(r.get("contract_demand_limit_kw") or 9999.0),
            site_transformer_limit_kw=float(
                r.get("site_transformer_limit_kw") or 9999.0
            ),
        )
        sites.append(s)
    return sites


def load_pv_profile(path: Path) -> List[PVProfile]:
    rows = _read_csv(path)
    return [
        PVProfile(
            site_id=r["site_id"],
            time_idx=int(r["time_idx"]),
            pv_generation_kw=float(r.get("pv_generation_kw") or 0.0),
        )
        for r in rows
    ]


def load_electricity_price(path: Path) -> List[ElectricityPrice]:
    rows = _read_csv(path)
    return [
        ElectricityPrice(
            site_id=r["site_id"],
            time_idx=int(r["time_idx"]),
            grid_energy_price=float(r.get("grid_energy_price") or 0.0),
            sell_back_price=float(r.get("sell_back_price") or 0.0),
            base_load_kw=float(r.get("base_load_kw") or 0.0),
        )
        for r in rows
    ]


def load_travel_connection(path: Path) -> List[TravelConnection]:
    rows = _read_csv(path)
    return [
        TravelConnection(
            from_task_id=r["from_task_id"],
            to_task_id=r["to_task_id"],
            can_follow=_bool_col(r.get("can_follow", "true")),
            deadhead_time_slot=int(r.get("deadhead_time_slot") or 0),
            deadhead_distance_km=float(r.get("deadhead_distance_km") or 0.0),
            deadhead_energy_kwh=float(r.get("deadhead_energy_kwh") or 0.0),
        )
        for r in rows
    ]


def load_vehicle_task_compat(path: Path) -> List[VehicleTaskCompat]:
    rows = _read_csv(path)
    return [
        VehicleTaskCompat(
            vehicle_id=r["vehicle_id"],
            task_id=r["task_id"],
            feasible=_bool_col(r.get("feasible", "true")),
        )
        for r in rows
    ]


def load_vehicle_charger_compat(path: Path) -> List[VehicleChargerCompat]:
    rows = _read_csv(path)
    return [
        VehicleChargerCompat(
            vehicle_id=r["vehicle_id"],
            charger_id=r["charger_id"],
            feasible=_bool_col(r.get("feasible", "true")),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# config.json ローダー
# ---------------------------------------------------------------------------


def load_config(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# メインエントリポイント: config.json から全データを読込
# ---------------------------------------------------------------------------


def _find_project_root(config_path: Path) -> Path:
    """
    config_path の上位を辿って project root を探す。

    src/ ディレクトリ または .git/ がある最初の親を返す。
    見つからない場合は config の 2 つ上を返す（後方互換）。

    これにより config/experiment_config.json も config/cases/*.json も
    同じ project root を指せる。
    """
    p = config_path.resolve().parent
    for _ in range(6):
        if (p / "src").is_dir() or (p / ".git").is_dir():
            return p
        p = p.parent
    # フォールバック: 2 つ上 (旧来の挙動)
    return config_path.resolve().parent.parent


def load_problem_data(config_path: str | Path) -> ProblemData:
    """
    config.json を起点に全 CSV を読み込んで ProblemData を返す。

    Parameters
    ----------
    config_path : str | Path
        config/experiment_config.json または config/cases/*.json へのパス

    Returns
    -------
    ProblemData
        MILP / シミュレータへの統一入力
    """
    cfg = load_config(Path(config_path))
    root = _find_project_root(
        Path(config_path)
    )  # project root (src/ or .git/ がある階層)

    paths = cfg.get("paths", {})

    def abs_path(key: str) -> Optional[Path]:
        rel = paths.get(key)
        if not rel:
            return None
        p = root / rel
        return p if p.exists() else None

    def abs_path_from(value: Optional[str]) -> Optional[Path]:
        if not value:
            return None
        p = root / value
        return p if p.exists() else None

    # --- 必須 CSV ---
    vehicles_csv = _load_required_csv_path(root, paths, "vehicles_csv")
    tasks_csv = _load_required_csv_path(root, paths, "tasks_csv")
    chargers_csv = _load_required_csv_path(root, paths, "chargers_csv")
    sites_csv = _load_required_csv_path(root, paths, "sites_csv")

    vehicles = load_vehicles(vehicles_csv)
    tasks = load_tasks(tasks_csv)
    chargers = load_chargers(chargers_csv)
    sites = load_sites(sites_csv)

    # --- 任意 CSV ---
    pv_profile_csv = abs_path("pv_profile_csv")
    electricity_price_csv = abs_path("electricity_price_csv")
    travel_connection_csv = abs_path("travel_connection_csv")
    compat_vehicle_task_csv = abs_path("compat_vehicle_task_csv")
    compat_vehicle_charger_csv = abs_path("compat_vehicle_charger_csv")

    pv_profiles: List[PVProfile] = []
    if pv_profile_csv:
        pv_profiles = load_pv_profile(pv_profile_csv)

    electricity_prices: List[ElectricityPrice] = []
    if electricity_price_csv:
        electricity_prices = load_electricity_price(electricity_price_csv)

    travel_connections: List[TravelConnection] = []
    if travel_connection_csv:
        travel_connections = load_travel_connection(travel_connection_csv)

    vehicle_task_compat: List[VehicleTaskCompat] = []
    if compat_vehicle_task_csv:
        vehicle_task_compat = load_vehicle_task_compat(compat_vehicle_task_csv)

    vehicle_charger_compat: List[VehicleChargerCompat] = []
    if compat_vehicle_charger_csv:
        vehicle_charger_compat = load_vehicle_charger_compat(compat_vehicle_charger_csv)

    # --- パラメータ ---
    weights = cfg.get("objective_weights", {})
    big_m = cfg.get("big_m", {})
    step_min = float(cfg.get("time_step_min", 15))
    delta_h = step_min / 60.0
    num_periods = int(cfg.get("num_periods", 64))

    data = ProblemData(
        vehicles=vehicles,
        tasks=tasks,
        chargers=chargers,
        sites=sites,
        travel_connections=travel_connections,
        vehicle_task_compat=vehicle_task_compat,
        vehicle_charger_compat=vehicle_charger_compat,
        pv_profiles=pv_profiles,
        electricity_prices=electricity_prices,
        num_periods=num_periods,
        delta_t_hour=delta_h,
        planning_horizon_hours=float(cfg.get("planning_horizon_hours", 16.0)),
        allow_partial_service=bool(cfg.get("allow_partial_service", False)),
        enable_pv=bool(cfg.get("enable_pv", False)),
        enable_v2g=bool(cfg.get("enable_v2g", False)),
        enable_battery_degradation=bool(cfg.get("enable_battery_degradation", False)),
        enable_demand_charge=bool(cfg.get("enable_demand_charge", False)),
        use_soft_soc_constraint=bool(cfg.get("use_soft_soc_constraint", False)),
        objective_weights={
            **ProblemData.__dataclass_fields__["objective_weights"].default_factory(),
            **weights,
        },
        BIG_M_ASSIGN=float(big_m.get("BIG_M_ASSIGN", 1e6)),
        BIG_M_CHARGE=float(big_m.get("BIG_M_CHARGE", 1e6)),
        BIG_M_SOC=float(big_m.get("BIG_M_SOC", 1e6)),
        EPSILON=float(big_m.get("EPSILON", 1e-6)),
    )

    # --- dispatch 前処理 (時刻表ファースト接続グラフ由来の can_follow 生成) ---
    dispatch_cfg = cfg.get("dispatch_preprocess", {})
    dispatch_enabled = bool(dispatch_cfg.get("enabled", True))
    source = (
        str(dispatch_cfg.get("connection_source", "dispatch_graph")).strip().lower()
    )
    force_rebuild = bool(dispatch_cfg.get("force_rebuild_travel_connections", False))
    rebuild_when_missing = bool(dispatch_cfg.get("rebuild_when_missing", True))
    should_rebuild = force_rebuild or (
        rebuild_when_missing and len(data.travel_connections) == 0
    )

    if (
        dispatch_enabled
        and should_rebuild
        and source in ("build_inputs", "build_inputs_arcs")
    ):
        try:
            _rebuild_from_build_inputs(
                data=data,
                cfg=cfg,
                config_path=config_path,
                dispatch_cfg=dispatch_cfg,
            )
        except Exception as exc:
            print(f"  [warn] dispatch_preprocess(build_inputs) スキップ: {exc}")

    if (
        dispatch_enabled
        and should_rebuild
        and source in ("dispatch_graph", "dispatch_graph_if_missing")
    ):
        try:
            from src.dispatch.problemdata_adapter import (
                build_travel_connections_via_dispatch,
            )

            turnaround_path = abs_path("turnaround_rules_csv")
            if turnaround_path is None:
                turnaround_path = abs_path_from(
                    dispatch_cfg.get("turnaround_rules_csv")
                )

            deadhead_path = abs_path("deadhead_rules_csv")
            if deadhead_path is None:
                deadhead_path = abs_path_from(dispatch_cfg.get("deadhead_rules_csv"))

            turnaround_rules = _load_turnaround_rules_csv(turnaround_path)
            deadhead_rules = _load_deadhead_rules_csv(deadhead_path)
            default_turnaround_min = int(dispatch_cfg.get("default_turnaround_min", 10))
            service_date = str(
                dispatch_cfg.get("service_date", cfg.get("service_date", "1970-01-01"))
            )

            travel_connections, report = build_travel_connections_via_dispatch(
                data=data,
                service_date=service_date,
                default_turnaround_min=default_turnaround_min,
                turnaround_rules=turnaround_rules,
                deadhead_rules=deadhead_rules,
            )
            data.travel_connections = travel_connections
            setattr(data, "_dispatch_preprocess_report", report)
        except Exception as exc:
            print(f"  [warn] dispatch_preprocess スキップ: {exc}")

    return data
