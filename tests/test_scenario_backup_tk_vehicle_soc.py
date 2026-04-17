from __future__ import annotations

from tools.scenario_backup_tk import App


class DummyVar:
    def __init__(self, value) -> None:
        self._value = value

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value


def _vehicle_form_app(vehicle_type: str = "BEV", initial_soc: str = "0.75") -> App:
    app = App.__new__(App)
    app.v_depot_var = DummyVar("dep-1")
    app.v_type_var = DummyVar(vehicle_type)
    app.v_model_code_var = DummyVar("MODEL-1")
    app.v_model_var = DummyVar("Vehicle 1")
    app.v_cap_var = DummyVar("40")
    app.v_battery_var = DummyVar("300")
    app.v_fuel_tank_var = DummyVar("")
    app.v_energy_var = DummyVar("1.2")
    app.v_km_per_l_var = DummyVar("")
    app.v_co2_gpkm_var = DummyVar("")
    app.v_curb_weight_var = DummyVar("")
    app.v_gross_weight_var = DummyVar("")
    app.v_engine_disp_var = DummyVar("")
    app.v_max_torque_var = DummyVar("")
    app.v_max_power_var = DummyVar("")
    app.v_charge_kw_var = DummyVar("90")
    app.v_initial_soc_var = DummyVar(initial_soc)
    app.v_min_soc_var = DummyVar("0.2")
    app.v_max_soc_var = DummyVar("0.9")
    app.v_acq_cost_var = DummyVar("0")
    app.v_enabled_var = DummyVar(True)
    return app


def test_build_vehicle_payload_includes_initial_soc_for_bev_and_clears_for_ice() -> None:
    app = _vehicle_form_app(vehicle_type="BEV", initial_soc="0.75")

    bev_payload = App._build_vehicle_payload_from_form(app)
    assert bev_payload["type"] == "BEV"
    assert bev_payload["initialSoc"] == 0.75

    app.v_type_var.set("ICE")
    ice_payload = App._build_vehicle_payload_from_form(app)
    assert ice_payload["type"] == "ICE"
    assert ice_payload["initialSoc"] is None
    assert ice_payload["batteryKwh"] is None
