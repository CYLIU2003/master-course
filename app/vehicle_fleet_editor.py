"""
vehicle_fleet_editor.py
-----------------------
Per-vehicle configuration editor for the EV bus simulation app.

Public API:
    render_vehicle_fleet_editor() -> None   # main entry point called from main.py
    get_fleet_vehicles() -> list[dict]       # reads _vfe_fleet from session_state
"""

from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------
# Session-state keys
# ---------------------------------------------------------------------------
_SS_FLEET = "_vfe_fleet"
_SS_EDIT_IDX = "_vfe_edit_idx"  # int index into fleet, -1 = new, None = no edit


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------
_DEFAULT_EV: dict[str, Any] = {
    "vehicle_id": "",
    "vehicle_name": "",
    "vehicle_type": "electric",
    "base_profile_id": None,
    "is_custom": False,
    "passenger_capacity": 79,
    "battery_capacity_kWh": 350.0,
    "usable_battery_ratio": 0.9,
    "initial_soc": 0.8,
    "min_soc": 0.2,
    "max_soc": 0.95,
    "energy_consumption_kWh_per_km": 1.3,
    "charging_power_ac_kW": 50.0,
    "charging_power_dc_kW": 150.0,
    "charging_efficiency": 0.95,
    "aux_load_kW": 3.0,
    "purchase_cost_yen": 45000000,
    "maintenance_cost_per_km": 25.0,
    "lifetime_year": 12,
}

_DEFAULT_ENGINE: dict[str, Any] = {
    "vehicle_id": "",
    "vehicle_name": "",
    "vehicle_type": "engine",
    "base_profile_id": None,
    "is_custom": False,
    "passenger_capacity": 79,
    "fuel_type": "diesel",
    "fuel_tank_capacity_L": 150.0,
    "fuel_efficiency_km_per_L": 5.38,
    "fuel_consumption_L_per_km": 0.185874,
    "fuel_cost_per_L": 145.0,
    "co2_emission_kg_per_L": 2.58,
    "idle_fuel_L_per_h": 1.5,
    "purchase_cost_yen": 20000000,
    "maintenance_cost_per_km": 28.0,
    "lifetime_year": 15,
}


# ---------------------------------------------------------------------------
# Catalog loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data
def _load_catalog() -> dict:
    catalog_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "vehicle_catalog.json"
    )
    with open(catalog_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _e_key(field: str) -> str:
    return f"_vfe_e_{field}"


def _init_ss() -> None:
    if _SS_FLEET not in st.session_state:
        st.session_state[_SS_FLEET] = []
    if _SS_EDIT_IDX not in st.session_state:
        st.session_state[_SS_EDIT_IDX] = None


def _next_vehicle_id(fleet: list[dict], vtype: str) -> str:
    prefix = "EV" if vtype == "electric" else "DL"
    existing = {v["vehicle_id"] for v in fleet}
    for i in range(1, 1000):
        cid = f"{prefix}{i:03d}"
        if cid not in existing:
            return cid
    return f"{prefix}999"


def _preset_options(catalog: dict, vtype: str) -> list[tuple[str | None, str]]:
    """Return list of (profile_id, display_name) for the given vehicle type."""
    opts: list[tuple[str | None, str]] = [(None, "カスタム（手動入力）")]
    if vtype == "electric":
        for p in catalog.get("ev_presets", []):
            opts.append((p["profile_id"], p["display_name"]))
    else:
        for p in catalog.get("engine_presets", []):
            opts.append((p["profile_id"], p["display_name"]))
    return opts


def _get_preset(catalog: dict, profile_id: str | None) -> dict | None:
    if profile_id is None:
        return None
    for section in ("ev_presets", "engine_presets"):
        for p in catalog.get(section, []):
            if p["profile_id"] == profile_id:
                return p
    return None


def _validate(v: dict) -> list[str]:
    errors: list[str] = []
    if not str(v.get("vehicle_id", "")).strip():
        errors.append("vehicle_id が空です")
    if not str(v.get("vehicle_name", "")).strip():
        errors.append("vehicle_name が空です")
    if v.get("purchase_cost_yen", 0) < 0:
        errors.append("購入費用は 0 以上にしてください")
    if v.get("vehicle_type") == "electric":
        cap = v.get("battery_capacity_kWh", 0)
        if cap <= 0:
            errors.append("バッテリ容量は 0 より大きい値にしてください")
        lo = v.get("min_soc", 0.0)
        hi = v.get("max_soc", 1.0)
        ini = v.get("initial_soc", 0.8)
        if not (0.0 <= lo < hi <= 1.0):
            errors.append("SOC 範囲が不正です (0 ≤ min_soc < max_soc ≤ 1)")
        if ini < lo:
            errors.append("初期 SOC は min_soc 以上にしてください")
        if v.get("energy_consumption_kWh_per_km", 0) <= 0:
            errors.append("電費 [kWh/km] は 0 より大きい値にしてください")
        eff = v.get("charging_efficiency", 0.95)
        if not (0 < eff <= 1.0):
            errors.append("充電効率は (0, 1] の範囲にしてください")
    else:
        if v.get("fuel_tank_capacity_L", 0) <= 0:
            errors.append("燃料タンク容量は 0 より大きい値にしてください")
        if v.get("fuel_consumption_L_per_km", 0) <= 0:
            errors.append("燃費 [L/km] は 0 より大きい値にしてください")
        if v.get("fuel_cost_per_L", 0) <= 0:
            errors.append("燃料単価は 0 より大きい値にしてください")
    return errors


def _apply_preset_to_edit_keys(preset: dict) -> None:
    """Copy preset fields into _vfe_e_* session state keys."""
    skip = {"profile_id", "display_name"}
    for field, value in preset.items():
        if field in skip:
            continue
        if field == "purchase_cost_yen":
            st.session_state[_e_key("purchase_cost_man")] = value / 10000
        else:
            st.session_state[_e_key(field)] = value


def _read_edit_keys(vtype: str, vid: str, vname: str) -> dict:
    """Assemble vehicle dict from _vfe_e_* session state keys."""
    g = st.session_state.get

    base: dict[str, Any] = {
        "vehicle_id": vid.strip(),
        "vehicle_name": vname.strip(),
        "vehicle_type": vtype,
        "base_profile_id": g(_e_key("base_profile_id")),
        "is_custom": g(_e_key("is_custom"), False),
        "passenger_capacity": int(g(_e_key("passenger_capacity"), 79)),
        "purchase_cost_yen": int(g(_e_key("purchase_cost_man"), 0) * 10000),
        "maintenance_cost_per_km": float(g(_e_key("maintenance_cost_per_km"), 25.0)),
        "lifetime_year": int(g(_e_key("lifetime_year"), 12)),
    }

    if vtype == "electric":
        base.update(
            {
                "battery_capacity_kWh": float(g(_e_key("battery_capacity_kWh"), 350.0)),
                "usable_battery_ratio": float(g(_e_key("usable_battery_ratio"), 0.9)),
                "initial_soc": float(g(_e_key("initial_soc"), 0.8)),
                "min_soc": float(g(_e_key("min_soc"), 0.2)),
                "max_soc": float(g(_e_key("max_soc"), 0.95)),
                "energy_consumption_kWh_per_km": float(
                    g(_e_key("energy_consumption_kWh_per_km"), 1.3)
                ),
                "charging_power_ac_kW": float(g(_e_key("charging_power_ac_kW"), 50.0)),
                "charging_power_dc_kW": float(g(_e_key("charging_power_dc_kW"), 150.0)),
                "charging_efficiency": float(g(_e_key("charging_efficiency"), 0.95)),
                "aux_load_kW": float(g(_e_key("aux_load_kW"), 3.0)),
            }
        )
    else:
        base.update(
            {
                "fuel_type": str(g(_e_key("fuel_type"), "diesel")),
                "fuel_tank_capacity_L": float(g(_e_key("fuel_tank_capacity_L"), 150.0)),
                "fuel_efficiency_km_per_L": float(
                    g(_e_key("fuel_efficiency_km_per_L"), 5.0)
                ),
                "fuel_consumption_L_per_km": float(
                    g(_e_key("fuel_consumption_L_per_km"), 0.2)
                ),
                "fuel_cost_per_L": float(g(_e_key("fuel_cost_per_L"), 145.0)),
                "co2_emission_kg_per_L": float(
                    g(_e_key("co2_emission_kg_per_L"), 2.58)
                ),
                "idle_fuel_L_per_h": float(g(_e_key("idle_fuel_L_per_h"), 1.5)),
            }
        )
    return base


def _load_vehicle_into_edit_keys(v: dict) -> None:
    """Populate _vfe_e_* keys from an existing vehicle dict (for editing)."""
    vtype = v.get("vehicle_type", "electric")
    st.session_state[_e_key("base_profile_id")] = v.get("base_profile_id")
    st.session_state[_e_key("is_custom")] = v.get("is_custom", False)
    st.session_state[_e_key("passenger_capacity")] = v.get("passenger_capacity", 79)
    st.session_state[_e_key("purchase_cost_man")] = (
        v.get("purchase_cost_yen", 0) / 10000
    )
    st.session_state[_e_key("maintenance_cost_per_km")] = v.get(
        "maintenance_cost_per_km", 25.0
    )
    st.session_state[_e_key("lifetime_year")] = v.get("lifetime_year", 12)

    if vtype == "electric":
        for field in (
            "battery_capacity_kWh",
            "usable_battery_ratio",
            "initial_soc",
            "min_soc",
            "max_soc",
            "energy_consumption_kWh_per_km",
            "charging_power_ac_kW",
            "charging_power_dc_kW",
            "charging_efficiency",
            "aux_load_kW",
        ):
            if field in v:
                st.session_state[_e_key(field)] = v[field]
    else:
        for field in (
            "fuel_type",
            "fuel_tank_capacity_L",
            "fuel_efficiency_km_per_L",
            "fuel_consumption_L_per_km",
            "fuel_cost_per_L",
            "co2_emission_kg_per_L",
            "idle_fuel_L_per_h",
        ):
            if field in v:
                st.session_state[_e_key(field)] = v[field]


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
def _on_type_change(catalog: dict) -> None:
    """Called when the type radio changes. Reset EV/engine-specific edit keys."""
    new_type = st.session_state.get("_vfe_type_radio", "electric")
    template = _DEFAULT_EV if new_type == "electric" else _DEFAULT_ENGINE
    for field, value in template.items():
        if field in ("vehicle_id", "vehicle_name", "vehicle_type"):
            continue
        if field == "purchase_cost_yen":
            st.session_state[_e_key("purchase_cost_man")] = value / 10000
        else:
            st.session_state[_e_key(field)] = value
    # Reset preset selection
    st.session_state["_vfe_preset_sel"] = None
    st.session_state[_e_key("base_profile_id")] = None
    st.session_state[_e_key("is_custom")] = False


def _on_preset_change(catalog: dict) -> None:
    """Called when preset selectbox changes. Populate edit keys."""
    profile_id = st.session_state.get("_vfe_preset_sel")
    if profile_id is None:
        st.session_state[_e_key("is_custom")] = True
        st.session_state[_e_key("base_profile_id")] = None
        return
    preset = _get_preset(catalog, profile_id)
    if preset:
        _apply_preset_to_edit_keys(preset)
        st.session_state[_e_key("base_profile_id")] = profile_id
        st.session_state[_e_key("is_custom")] = False


# ---------------------------------------------------------------------------
# Fleet list renderer
# ---------------------------------------------------------------------------
def _render_fleet_list(fleet: list[dict]) -> None:
    if not fleet:
        st.info(
            "フリートに車両が登録されていません。下の「＋ 車両追加」ボタンで追加してください。"
        )
        return

    # Header
    h_cols = st.columns([1.5, 2, 1.2, 2.5, 1.5, 1.5, 1.5, 1.5])
    labels = [
        "ID",
        "名前",
        "種別",
        "プロファイル",
        "乗客数",
        "容量/燃費",
        "編集",
        "削除",
    ]
    for col, label in zip(h_cols, labels):
        col.markdown(f"**{label}**")

    st.markdown("---")

    for idx, v in enumerate(fleet):
        vtype = v.get("vehicle_type", "electric")
        type_badge = "🔋 EV" if vtype == "electric" else "⛽ エンジン"

        if vtype == "electric":
            cap_str = f"{v.get('battery_capacity_kWh', 0):.0f} kWh"
        else:
            eff = v.get("fuel_efficiency_km_per_L", 0)
            cap_str = f"{eff:.2f} km/L"

        profile_name = v.get("base_profile_id") or "カスタム"
        # Shorten display
        if len(profile_name) > 20:
            profile_name = profile_name[:18] + "…"

        row = st.columns([1.5, 2, 1.2, 2.5, 1.5, 1.5, 1.5, 1.5])
        row[0].write(v.get("vehicle_id", ""))
        row[1].write(v.get("vehicle_name", ""))
        row[2].write(type_badge)
        row[3].write(profile_name)
        row[4].write(str(v.get("passenger_capacity", "")))
        row[5].write(cap_str)

        if row[6].button("✏️", key=f"_vfe_edit_{idx}"):
            st.session_state[_SS_EDIT_IDX] = idx
            _load_vehicle_into_edit_keys(v)
            vtype_val = v.get("vehicle_type", "electric")
            st.session_state["_vfe_type_radio"] = vtype_val
            st.session_state["_vfe_preset_sel"] = v.get("base_profile_id")
            st.rerun()

        if row[7].button("🗑️", key=f"_vfe_del_{idx}"):
            fleet.pop(idx)
            st.session_state[_SS_FLEET] = fleet
            if st.session_state.get(_SS_EDIT_IDX) == idx:
                st.session_state[_SS_EDIT_IDX] = None
            st.rerun()


# ---------------------------------------------------------------------------
# EV fields
# ---------------------------------------------------------------------------
def _render_ev_fields() -> None:
    st.markdown("##### バッテリー・電費")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "バッテリ容量 [kWh]",
            min_value=10.0,
            max_value=1000.0,
            step=10.0,
            key=_e_key("battery_capacity_kWh"),
        )
        st.slider(
            "使用可能比率",
            min_value=0.5,
            max_value=1.0,
            step=0.01,
            key=_e_key("usable_battery_ratio"),
        )
        st.number_input(
            "電費 [kWh/km]",
            min_value=0.1,
            max_value=5.0,
            step=0.05,
            key=_e_key("energy_consumption_kWh_per_km"),
        )
        st.number_input(
            "補機負荷 [kW]",
            min_value=0.0,
            max_value=20.0,
            step=0.5,
            key=_e_key("aux_load_kW"),
        )
    with c2:
        st.slider(
            "初期 SOC",
            min_value=0.1,
            max_value=1.0,
            step=0.01,
            key=_e_key("initial_soc"),
        )
        st.slider(
            "SOC 下限",
            min_value=0.0,
            max_value=0.5,
            step=0.01,
            key=_e_key("min_soc"),
        )
        st.slider(
            "SOC 上限",
            min_value=0.5,
            max_value=1.0,
            step=0.01,
            key=_e_key("max_soc"),
        )
    st.markdown("##### 充電")
    d1, d2, d3 = st.columns(3)
    with d1:
        st.number_input(
            "AC 充電出力 [kW]",
            min_value=5.0,
            max_value=200.0,
            step=5.0,
            key=_e_key("charging_power_ac_kW"),
        )
    with d2:
        st.number_input(
            "DC 急速充電出力 [kW]",
            min_value=10.0,
            max_value=600.0,
            step=10.0,
            key=_e_key("charging_power_dc_kW"),
        )
    with d3:
        st.slider(
            "充電効率",
            min_value=0.5,
            max_value=1.0,
            step=0.01,
            key=_e_key("charging_efficiency"),
        )


# ---------------------------------------------------------------------------
# Engine fields
# ---------------------------------------------------------------------------
def _render_engine_fields() -> None:
    st.markdown("##### 燃料・燃費")
    c1, c2 = st.columns(2)
    with c1:
        st.selectbox(
            "燃料種別",
            options=["diesel", "gasoline", "CNG"],
            key=_e_key("fuel_type"),
        )
        st.number_input(
            "燃料タンク容量 [L]",
            min_value=10.0,
            max_value=500.0,
            step=10.0,
            key=_e_key("fuel_tank_capacity_L"),
        )
        st.number_input(
            "燃費 [km/L]",
            min_value=1.0,
            max_value=30.0,
            step=0.1,
            key=_e_key("fuel_efficiency_km_per_L"),
        )
        st.number_input(
            "燃料消費率 [L/km]",
            min_value=0.01,
            max_value=1.0,
            step=0.005,
            format="%.4f",
            key=_e_key("fuel_consumption_L_per_km"),
        )
    with c2:
        st.number_input(
            "燃料単価 [円/L]",
            min_value=50.0,
            max_value=500.0,
            step=5.0,
            key=_e_key("fuel_cost_per_L"),
        )
        st.number_input(
            "CO₂排出係数 [kg/L]",
            min_value=0.5,
            max_value=5.0,
            step=0.01,
            key=_e_key("co2_emission_kg_per_L"),
        )
        st.number_input(
            "アイドル燃料消費 [L/h]",
            min_value=0.0,
            max_value=10.0,
            step=0.1,
            key=_e_key("idle_fuel_L_per_h"),
        )


# ---------------------------------------------------------------------------
# Edit panel
# ---------------------------------------------------------------------------
def _render_edit_panel(catalog: dict, fleet: list[dict]) -> None:
    edit_idx = st.session_state.get(_SS_EDIT_IDX)
    is_new = edit_idx == -1

    st.markdown("#### " + ("➕ 新規車両追加" if is_new else "✏️ 車両編集"))

    # --- Vehicle type ---
    current_vtype = st.session_state.get("_vfe_type_radio", "electric")
    st.radio(
        "車両種別",
        options=["electric", "engine"],
        format_func=lambda x: "🔋 電気バス (EV)"
        if x == "electric"
        else "⛽ エンジンバス",
        horizontal=True,
        key="_vfe_type_radio",
        on_change=_on_type_change,
        args=(catalog,),
    )
    vtype = st.session_state.get("_vfe_type_radio", "electric")

    # --- Preset selector ---
    preset_opts = _preset_options(catalog, vtype)
    preset_ids = [pid for pid, _ in preset_opts]
    preset_labels = {pid: lbl for pid, lbl in preset_opts}

    current_preset = st.session_state.get("_vfe_preset_sel", None)
    if current_preset not in preset_ids:
        current_preset = None
        st.session_state["_vfe_preset_sel"] = None

    st.selectbox(
        "プリセット選択",
        options=preset_ids,
        format_func=lambda x: preset_labels.get(x, "カスタム（手動入力）"),
        key="_vfe_preset_sel",
        on_change=_on_preset_change,
        args=(catalog,),
    )

    st.markdown("---")

    # --- Identity fields ---
    id_col, name_col = st.columns(2)
    with id_col:
        vid_default = ""
        if is_new:
            vid_default = _next_vehicle_id(fleet, vtype)
        elif edit_idx is not None and 0 <= edit_idx < len(fleet):
            vid_default = fleet[edit_idx]["vehicle_id"]
        vid = st.text_input("車両 ID", value=vid_default, key="_vfe_e_vid")

    with name_col:
        vname_default = ""
        if edit_idx is not None and not is_new and 0 <= edit_idx < len(fleet):
            vname_default = fleet[edit_idx]["vehicle_name"]
        vname = st.text_input("車両名", value=vname_default, key="_vfe_e_vname")

    # --- Shared fields ---
    sh1, sh2, sh3 = st.columns(3)
    with sh1:
        st.number_input(
            "乗客定員",
            min_value=1,
            max_value=200,
            step=1,
            key=_e_key("passenger_capacity"),
        )
    with sh2:
        st.number_input(
            "購入費用 [万円]",
            min_value=0.0,
            max_value=100000.0,
            step=100.0,
            key=_e_key("purchase_cost_man"),
        )
    with sh3:
        st.number_input(
            "耐用年数 [年]",
            min_value=1,
            max_value=30,
            step=1,
            key=_e_key("lifetime_year"),
        )
    st.number_input(
        "維持費 [円/km]",
        min_value=0.0,
        max_value=500.0,
        step=1.0,
        key=_e_key("maintenance_cost_per_km"),
    )

    st.markdown("---")

    # --- Type-specific fields ---
    if vtype == "electric":
        _render_ev_fields()
    else:
        _render_engine_fields()

    st.markdown("---")

    # --- Save / Cancel buttons ---
    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 4])
    with btn_col1:
        save_clicked = st.button(
            "💾 保存", type="primary", key="_vfe_save_btn", use_container_width=True
        )
    with btn_col2:
        cancel_clicked = st.button(
            "キャンセル", key="_vfe_cancel_btn", use_container_width=True
        )

    if save_clicked:
        new_v = _read_edit_keys(vtype, vid, vname)
        errors = _validate(new_v)
        if errors:
            for err in errors:
                st.error(err)
        else:
            if is_new:
                fleet.append(new_v)
            else:
                fleet[edit_idx] = new_v
            st.session_state[_SS_FLEET] = fleet
            st.session_state[_SS_EDIT_IDX] = None
            st.rerun()

    if cancel_clicked:
        st.session_state[_SS_EDIT_IDX] = None
        st.rerun()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_vehicle_fleet_editor() -> None:
    """Main entry point. Renders the vehicle fleet editor UI block."""
    _init_ss()
    catalog = _load_catalog()
    fleet: list[dict] = st.session_state[_SS_FLEET]
    edit_idx = st.session_state.get(_SS_EDIT_IDX)

    st.markdown("#### 🚌 フリート車両設定")

    if edit_idx is None:
        # --- Fleet list view ---
        _render_fleet_list(fleet)

        st.markdown("")
        add_col, dup_col = st.columns([2, 6])
        with add_col:
            if st.button(
                "➕ 車両追加",
                type="primary",
                key="_vfe_add_btn",
                use_container_width=True,
            ):
                vtype = "electric"
                st.session_state["_vfe_type_radio"] = vtype
                st.session_state["_vfe_preset_sel"] = None
                # Load EV defaults into edit keys
                for field, value in _DEFAULT_EV.items():
                    if field in ("vehicle_id", "vehicle_name", "vehicle_type"):
                        continue
                    if field == "purchase_cost_yen":
                        st.session_state[_e_key("purchase_cost_man")] = value / 10000
                    else:
                        st.session_state[_e_key(field)] = value
                st.session_state[_e_key("is_custom")] = False
                st.session_state[_e_key("base_profile_id")] = None
                st.session_state[_SS_EDIT_IDX] = -1
                st.rerun()
    else:
        # --- Edit panel ---
        _render_edit_panel(catalog, fleet)


def get_fleet_vehicles() -> list[dict]:
    """Return the current fleet vehicle list from session state."""
    return st.session_state.get(_SS_FLEET, [])
