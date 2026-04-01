from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CostComponentDefinition:
    key: str
    label: str
    description: str
    section: str
    solver_scope: str = "common"


COST_COMPONENT_DEFINITIONS: tuple[CostComponentDefinition, ...] = (
    CostComponentDefinition(
        key="vehicle_fixed_cost",
        label="車両固定費（日割り導入費）",
        description="`vehicle.fixed_use_cost_jpy` を目的関数へ加算します。旧 `disable_vehicle_acquisition_cost` と同じ責務です。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="driver_cost",
        label="運転士コスト",
        description="拘束時間ベースの運転士コストを目的関数へ加算します。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="electricity_cost",
        label="系統電力コスト",
        description="EV 充電・系統購入に対する `electricity_cost_final` を加算します。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="fuel_cost",
        label="燃料コスト",
        description="ICE の軽油コスト `fuel_cost_final` を加算します。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="demand_charge_cost",
        label="需要料金",
        description="営業所ピーク電力に対する `demand_cost` を加算します。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="co2_cost",
        label="CO2コスト",
        description="`co2_price_per_kg` に基づく排出コストを加算します。",
        section="主要コスト",
    ),
    CostComponentDefinition(
        key="unserved_penalty",
        label="未配車ペナルティ",
        description="未担当便 1 本ごとの `unserved_penalty` を加算します。",
        section="品質/制約ペナルティ",
    ),
    CostComponentDefinition(
        key="switch_cost",
        label="車種切替コスト",
        description="基準計画からの車種切替件数に対する `switch_cost` を加算します。",
        section="品質/制約ペナルティ",
    ),
    CostComponentDefinition(
        key="battery_degradation_cost",
        label="車載電池劣化コスト",
        description="車載電池の充放電サイクルに対する `degradation_cost` を加算します。",
        section="品質/制約ペナルティ",
    ),
    CostComponentDefinition(
        key="deviation_cost",
        label="基準計画乖離コスト",
        description="baseline plan との差分件数に対する `deviation_cost` を加算します。",
        section="品質/制約ペナルティ",
    ),
    CostComponentDefinition(
        key="contract_overage_penalty",
        label="契約超過ペナルティ",
        description="`depot_power_limit_kw` 超過分に対する `contract_overage_cost` を加算します。",
        section="品質/制約ペナルティ",
    ),
    CostComponentDefinition(
        key="charge_session_start_penalty",
        label="充電開始ペナルティ",
        description="充電セッション開始回数に対する MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="slot_concurrency_penalty",
        label="同時充電超過ペナルティ",
        description="同一スロットの充電集中に対する MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="early_charge_penalty",
        label="早充電ペナルティ",
        description="早い時刻の充電を抑える MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="soc_upper_buffer_penalty",
        label="SOC上限制約緩和ペナルティ",
        description="`charge_to_upper_buffer_penalty_yen_per_kwh` に対応する MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="final_soc_target_penalty",
        label="終端SOC目標ペナルティ",
        description="終端 SOC 目標からの超過乖離に対する MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="grid_to_bus_priority_penalty",
        label="系統→車両優先ペナルティ",
        description="BESS 利用より系統直充電を選びすぎる場合の MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
    CostComponentDefinition(
        key="grid_to_bess_priority_penalty",
        label="系統→BESS優先ペナルティ",
        description="系統から BESS への充電を抑える MILP 内部ペナルティです。",
        section="MILP充電ペナルティ",
        solver_scope="milp_only",
    ),
)

COST_COMPONENT_KEYS: tuple[str, ...] = tuple(item.key for item in COST_COMPONENT_DEFINITIONS)
LEGACY_OTHER_COMPONENT_KEYS: tuple[str, ...] = tuple(
    item.key
    for item in COST_COMPONENT_DEFINITIONS
    if item.key not in {"vehicle_fixed_cost", "driver_cost"}
)


def default_cost_component_flags() -> dict[str, bool]:
    return {key: True for key in COST_COMPONENT_KEYS}


def normalize_cost_component_flags(
    flags: Mapping[str, Any] | None = None,
    *,
    legacy_disable_vehicle_acquisition_cost: Any = None,
    legacy_enable_vehicle_cost: Any = None,
    legacy_enable_driver_cost: Any = None,
    legacy_enable_other_cost: Any = None,
) -> dict[str, bool]:
    normalized = default_cost_component_flags()
    explicit_keys: set[str] = set()
    if isinstance(flags, Mapping):
        for key in COST_COMPONENT_KEYS:
            if key not in flags:
                continue
            normalized[key] = bool(flags.get(key))
            explicit_keys.add(key)

    vehicle_flag: bool | None = None
    if legacy_disable_vehicle_acquisition_cost is not None:
        vehicle_flag = not bool(legacy_disable_vehicle_acquisition_cost)
    elif legacy_enable_vehicle_cost is not None:
        vehicle_flag = bool(legacy_enable_vehicle_cost)
    if vehicle_flag is not None and "vehicle_fixed_cost" not in explicit_keys:
        normalized["vehicle_fixed_cost"] = vehicle_flag

    if legacy_enable_driver_cost is not None and "driver_cost" not in explicit_keys:
        normalized["driver_cost"] = bool(legacy_enable_driver_cost)

    if legacy_enable_other_cost is not None:
        legacy_other_enabled = bool(legacy_enable_other_cost)
        for key in LEGACY_OTHER_COMPONENT_KEYS:
            if key in explicit_keys:
                continue
            normalized[key] = legacy_other_enabled

    return normalized


def legacy_cost_component_flags(flags: Mapping[str, Any] | None) -> dict[str, bool]:
    normalized = normalize_cost_component_flags(flags)
    return {
        "disable_vehicle_acquisition_cost": not bool(normalized["vehicle_fixed_cost"]),
        "enable_vehicle_cost": bool(normalized["vehicle_fixed_cost"]),
        "enable_driver_cost": bool(normalized["driver_cost"]),
        "enable_other_cost": all(bool(normalized[key]) for key in LEGACY_OTHER_COMPONENT_KEYS),
    }


__all__ = [
    "COST_COMPONENT_DEFINITIONS",
    "COST_COMPONENT_KEYS",
    "LEGACY_OTHER_COMPONENT_KEYS",
    "CostComponentDefinition",
    "default_cost_component_flags",
    "legacy_cost_component_flags",
    "normalize_cost_component_flags",
]
