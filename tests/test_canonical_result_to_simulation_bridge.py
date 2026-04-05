"""
Tests for canonical result to simulation bridge (Phase 2.2)

These tests verify that canonical optimization results are correctly
preserved when bridged to simulation, without dropping or zeroing fields.

Critical fields that must survive bridging:
- assignment
- soc_series
- charge_schedule / charge_power_kw
- grid_import_kw / grid_export_kw
- pv_used_kw / pv_to_bus_kwh
- peak_demand_kw
- obj_breakdown
- Detailed energy flow breakdown (grid_to_bus, pv_to_bus, bess_to_bus, etc.)
- SOC modeling notes and provenance flags
"""

import pytest
from typing import Dict, Any


class TestMILPResultSerialization:
    """Test MILPResult serialization preserves all fields."""
    
    def test_basic_fields_preserved(self):
        """Basic MILP result fields should be preserved."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        original = MILPResult(
            status="OPTIMAL",
            objective_value=12345.67,
            solve_time_sec=5.5,
            mip_gap=0.001,
            assignment={"v1": ["t1", "t2"], "v2": ["t3"]},
            unserved_tasks=["t4", "t5"],
            infeasibility_info="",
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.status == original.status
        assert deserialized.objective_value == original.objective_value
        assert deserialized.solve_time_sec == original.solve_time_sec
        assert deserialized.mip_gap == original.mip_gap
        assert deserialized.assignment == original.assignment
        assert deserialized.unserved_tasks == original.unserved_tasks
    
    def test_soc_series_preserved(self):
        """SOC series should be preserved through serialization."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        soc_series = {
            "v1": [100.0, 95.0, 90.0, 85.0, 100.0],
            "v2": [80.0, 75.0, 70.0, 80.0],
        }
        
        original = MILPResult(
            status="OPTIMAL",
            soc_series=soc_series,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.soc_series == soc_series
    
    def test_charge_schedule_preserved(self):
        """Charge schedule and power should be preserved."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        charge_schedule = {
            "v1": {"charger_1": [0, 1, 1, 0, 0]},
            "v2": {"charger_2": [1, 1, 0, 0, 0]},
        }
        charge_power_kw = {
            "v1": {"charger_1": [0.0, 50.0, 50.0, 0.0, 0.0]},
            "v2": {"charger_2": [30.0, 30.0, 0.0, 0.0, 0.0]},
        }
        
        original = MILPResult(
            status="OPTIMAL",
            charge_schedule=charge_schedule,
            charge_power_kw=charge_power_kw,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.charge_schedule == charge_schedule
        assert deserialized.charge_power_kw == charge_power_kw
    
    def test_grid_import_export_preserved(self):
        """Grid import/export should NOT be zeroed during bridging."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        grid_import = {"depot_1": [100.0, 120.0, 80.0, 90.0]}
        grid_export = {"depot_1": [0.0, 0.0, 20.0, 10.0]}
        
        original = MILPResult(
            status="OPTIMAL",
            grid_import_kw=grid_import,
            grid_export_kw=grid_export,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        # Critical: these must NOT be empty or zeroed
        assert deserialized.grid_import_kw == grid_import
        assert deserialized.grid_export_kw == grid_export
        assert len(deserialized.grid_import_kw["depot_1"]) == 4
        assert sum(deserialized.grid_import_kw["depot_1"]) > 0
    
    def test_pv_fields_preserved(self):
        """PV-related fields should NOT be zeroed during bridging."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        pv_used = {"depot_1": [0.0, 10.0, 20.0, 15.0]}
        pv_to_bus = {"depot_1": 45.0}
        
        original = MILPResult(
            status="OPTIMAL",
            pv_used_kw=pv_used,
            pv_to_bus_kwh=pv_to_bus,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.pv_used_kw == pv_used
        assert deserialized.pv_to_bus_kwh == pv_to_bus
    
    def test_peak_demand_preserved(self):
        """Peak demand should be preserved."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        peak_demand = {"depot_1": 150.0, "depot_2": 100.0}
        
        original = MILPResult(
            status="OPTIMAL",
            peak_demand_kw=peak_demand,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.peak_demand_kw == peak_demand
    
    def test_obj_breakdown_preserved(self):
        """Objective breakdown should be preserved."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        obj_breakdown = {
            "electricity_cost": 5000.0,
            "demand_charge": 2000.0,
            "unserved_penalty": 0.0,
            "pv_revenue": -500.0,
        }
        
        original = MILPResult(
            status="OPTIMAL",
            obj_breakdown=obj_breakdown,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.obj_breakdown == obj_breakdown


class TestDetailedEnergyFlowPreservation:
    """Test that detailed energy flow fields survive serialization."""
    
    def test_grid_to_bus_kwh_by_slot_preserved(self):
        """grid_to_bus_kwh_by_slot should survive round-trip."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        grid_to_bus = {
            ("depot_1", 0): 10.0,
            ("depot_1", 1): 15.0,
            ("depot_1", 2): 12.0,
        }
        
        original = MILPResult(
            status="OPTIMAL",
            grid_to_bus_kwh_by_slot=grid_to_bus,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.grid_to_bus_kwh_by_slot == grid_to_bus
    
    def test_pv_to_bus_kwh_by_slot_preserved(self):
        """pv_to_bus_kwh_by_slot should survive round-trip."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        pv_to_bus = {
            ("depot_1", 0): 5.0,
            ("depot_1", 1): 8.0,
            ("depot_1", 2): 6.0,
        }
        
        original = MILPResult(
            status="OPTIMAL",
            pv_to_bus_kwh_by_slot=pv_to_bus,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.pv_to_bus_kwh_by_slot == pv_to_bus
    
    def test_bess_to_bus_kwh_by_slot_preserved(self):
        """bess_to_bus_kwh_by_slot should survive round-trip."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        bess_to_bus = {
            ("depot_1", 0): 0.0,
            ("depot_1", 1): 3.0,
            ("depot_1", 2): 5.0,
        }
        
        original = MILPResult(
            status="OPTIMAL",
            bess_to_bus_kwh_by_slot=bess_to_bus,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.bess_to_bus_kwh_by_slot == bess_to_bus
    
    def test_all_energy_flow_fields_preserved_together(self):
        """All detailed energy flow fields should survive together."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        original = MILPResult(
            status="OPTIMAL",
            grid_to_bus_kwh_by_slot={("d1", 0): 10.0, ("d1", 1): 12.0},
            pv_to_bus_kwh_by_slot={("d1", 0): 5.0, ("d1", 1): 6.0},
            bess_to_bus_kwh_by_slot={("d1", 0): 2.0, ("d1", 1): 3.0},
            grid_to_bess_kwh_by_slot={("d1", 0): 0.0, ("d1", 1): 1.0},
            pv_to_bess_kwh_by_slot={("d1", 0): 1.0, ("d1", 1): 0.5},
            pv_curtailed_kwh_by_slot={("d1", 0): 0.0, ("d1", 1): 0.0},
            bess_soc_kwh_by_slot={("d1", 0): 50.0, ("d1", 1): 48.0},
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.grid_to_bus_kwh_by_slot == original.grid_to_bus_kwh_by_slot
        assert deserialized.pv_to_bus_kwh_by_slot == original.pv_to_bus_kwh_by_slot
        assert deserialized.bess_to_bus_kwh_by_slot == original.bess_to_bus_kwh_by_slot
        assert deserialized.grid_to_bess_kwh_by_slot == original.grid_to_bess_kwh_by_slot
        assert deserialized.pv_to_bess_kwh_by_slot == original.pv_to_bess_kwh_by_slot
        assert deserialized.pv_curtailed_kwh_by_slot == original.pv_curtailed_kwh_by_slot
        assert deserialized.bess_soc_kwh_by_slot == original.bess_soc_kwh_by_slot


class TestProvenanceFieldsPreservation:
    """Test that provenance and modeling note fields survive serialization."""
    
    def test_soc_modeling_note_preserved(self):
        """soc_modeling_note should survive serialization."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        original = MILPResult(
            status="OPTIMAL",
            soc_modeling_note="Custom SOC modeling note",
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.soc_modeling_note == "Custom SOC modeling note"
    
    def test_vehicle_provenance_is_exact_preserved(self):
        """vehicle_provenance_is_exact should survive serialization."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        original = MILPResult(
            status="OPTIMAL",
            vehicle_provenance_is_exact=False,
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.vehicle_provenance_is_exact is False
    
    def test_vehicle_provenance_note_preserved(self):
        """vehicle_provenance_note should survive serialization."""
        from src.milp_model import MILPResult
        from bff.mappers.solver_results import serialize_milp_result, deserialize_milp_result
        
        original = MILPResult(
            status="OPTIMAL",
            vehicle_provenance_note="Custom provenance note",
        )
        
        serialized = serialize_milp_result(original)
        deserialized = deserialize_milp_result(serialized)
        
        assert deserialized.vehicle_provenance_note == "Custom provenance note"


class TestCanonicalResultDeserializerExists:
    """Test that _deserialize_canonical_result function exists and works."""
    
    def test_function_exists(self):
        """_deserialize_canonical_result should exist in simulation module."""
        from bff.routers.simulation import _deserialize_canonical_result
        
        assert callable(_deserialize_canonical_result)
    
    def test_deserializes_canonical_format(self):
        """_deserialize_canonical_result should handle canonical format."""
        from bff.routers.simulation import _deserialize_canonical_result
        
        # Canonical format has specific structure with plan, solver_metadata, etc.
        canonical_data = {
            "total_cost": 10000.0,
            "solver_metadata": {
                "solver_status": "OPTIMAL",
                "solve_time_sec": 5.5,
                "mip_gap": 0.001,
            },
            "plan": {
                "vehicle_paths": {"v1": ["t1", "t2"]},
                "soc_kwh_by_vehicle_slot": {"v1": [100.0, 90.0, 80.0]},
                "unserved_trip_ids": [],
            },
            "depot_cost_ledger": [
                {"depot_id": "depot_1", "peak_demand_kw": 150.0},
            ],
            "cost_breakdown": {
                "electricity_cost": 5000.0,
                "demand_charge": 3000.0,
            },
        }
        
        result = _deserialize_canonical_result(canonical_data)
        
        assert result.status == "OPTIMAL"
        assert result.objective_value == 10000.0
        assert result.assignment == {"v1": ["t1", "t2"]}

    def test_deserializes_current_top_level_canonical_format(self):
        """Current canonical output keeps vehicle_paths at top level, not under plan."""
        from bff.routers.simulation import _deserialize_canonical_result

        canonical_data = {
            "objective_value": 345.6,
            "solver_status": "feasible",
            "solver_metadata": {
                "solver_status": "feasible",
                "solve_time_sec": 12.0,
                "mip_gap": 0.0,
            },
            "vehicle_paths": {"veh-1": ["trip-1", "trip-2"]},
            "unserved_trip_ids": [],
            "depot_cost_ledger": [
                {"depot_id": "depot-1", "peak_demand_kw": 88.0},
            ],
            "cost_breakdown": {
                "total_cost": 345.6,
            },
        }

        result = _deserialize_canonical_result(canonical_data)

        assert result.status == "feasible"
        assert result.objective_value == 345.6
        assert result.assignment == {"veh-1": ["trip-1", "trip-2"]}
        assert result.unserved_tasks == []
        assert result.peak_demand_kw == {"depot-1": 88.0}


class TestSimulationBridgeDoesNotZeroFields:
    """
    Test that simulation bridge does not zero/drop canonical fields.
    
    This was the original bug: simulation was converting canonical results
    to legacy format and losing detailed energy flow fields.
    """
    
    def test_bridge_preserves_grid_import(self):
        """Grid import should not be zeroed when bridging to simulation."""
        from src.milp_model import MILPResult
        
        result = MILPResult(
            status="OPTIMAL",
            grid_import_kw={"depot_1": [100.0, 120.0, 80.0]},
        )
        
        # Should not be empty
        assert result.grid_import_kw
        assert sum(result.grid_import_kw["depot_1"]) > 0
    
    def test_bridge_preserves_pv_fields(self):
        """PV fields should not be zeroed when bridging to simulation."""
        from src.milp_model import MILPResult
        
        result = MILPResult(
            status="OPTIMAL",
            pv_used_kw={"depot_1": [10.0, 20.0, 15.0]},
            pv_to_bus_kwh={"depot_1": 45.0},
        )
        
        # Should not be empty
        assert result.pv_used_kw
        assert result.pv_to_bus_kwh
        assert result.pv_to_bus_kwh["depot_1"] == 45.0


class TestCostBreakdownKeyMapping:
    """
    Test that cost breakdown keys are correctly mapped from canonical names to UI expected names.
    
    The canonical evaluator uses names like:
    - energy_cost
    - demand_cost
    - degradation_cost
    - co2_cost
    
    But the UI expects names like:
    - energy_cost (same)
    - demand_charge, total_demand_charge
    - battery_degradation_cost, degradation_cost, total_degradation_cost
    - co2_cost
    - total_fuel_cost
    """
    
    def test_canonical_cost_breakdown_keys(self):
        """CostBreakdown.to_dict() should return canonical keys."""
        from src.optimization.common.evaluator import CostBreakdown
        
        breakdown = CostBreakdown(
            energy_cost=1000.0,
            demand_cost=500.0,
            degradation_cost=200.0,
            co2_cost=100.0,
        )
        
        d = breakdown.to_dict()
        
        # Canonical keys
        assert d["energy_cost"] == 1000.0
        assert d["demand_cost"] == 500.0
        assert d["degradation_cost"] == 200.0
        assert d["co2_cost"] == 100.0
    
    def test_cost_breakdown_function_maps_to_ui_keys(self):
        """_cost_breakdown() should include both canonical and UI-expected keys."""
        from bff.routers.optimization import _cost_breakdown
        
        # Simulate canonical result payload with obj_breakdown
        result_payload = {
            "obj_breakdown": {
                "energy_cost": 1000.0,
                "demand_cost": 500.0,
                "degradation_cost": 200.0,
                "co2_cost": 100.0,
            }
        }
        
        cb = _cost_breakdown(result_payload, sim_payload=None)
        
        # Should have UI-expected keys
        assert "energy_cost" in cb
        assert "demand_charge" in cb
        assert "total_demand_charge" in cb
        assert "battery_degradation_cost" in cb
        assert "degradation_cost" in cb
        assert "total_degradation_cost" in cb
        assert "co2_cost" in cb
        
        # Values should be correct
        assert cb["energy_cost"] == 1000.0
        assert cb["demand_charge"] == 500.0
        assert cb["total_demand_charge"] == 500.0
        assert cb["battery_degradation_cost"] == 200.0
        assert cb["degradation_cost"] == 200.0
        assert cb["total_degradation_cost"] == 200.0
        assert cb["co2_cost"] == 100.0
    
    def test_cost_breakdown_aliases_electricity_to_energy(self):
        """_cost_breakdown() should accept electricity_cost as energy_cost alias."""
        from bff.routers.optimization import _cost_breakdown
        
        result_payload = {
            "obj_breakdown": {
                "electricity_cost": 1000.0,  # legacy key
            }
        }
        
        cb = _cost_breakdown(result_payload, sim_payload=None)
        
        assert cb["energy_cost"] == 1000.0
    
    def test_cost_breakdown_aliases_demand_charge_cost_to_demand(self):
        """_cost_breakdown() should accept demand_charge_cost as demand_cost alias."""
        from bff.routers.optimization import _cost_breakdown
        
        result_payload = {
            "obj_breakdown": {
                "demand_charge_cost": 500.0,  # legacy key
            }
        }
        
        cb = _cost_breakdown(result_payload, sim_payload=None)
        
        assert cb["demand_charge"] == 500.0
        assert cb["total_demand_charge"] == 500.0
    
    def test_cost_breakdown_aliases_emission_to_co2(self):
        """_cost_breakdown() should accept emission_cost as co2_cost alias."""
        from bff.routers.optimization import _cost_breakdown
        
        result_payload = {
            "obj_breakdown": {
                "emission_cost": 100.0,  # legacy key
            }
        }
        
        cb = _cost_breakdown(result_payload, sim_payload=None)
        
        assert cb["co2_cost"] == 100.0
    
    def test_cost_breakdown_total_cost_from_multiple_sources(self):
        """total_cost should come from sim_payload, result_payload, or obj_breakdown."""
        from bff.routers.optimization import _cost_breakdown
        
        # Test 1: from obj_breakdown.total_cost
        result_payload = {
            "obj_breakdown": {
                "total_cost": 5000.0,
            }
        }
        cb = _cost_breakdown(result_payload, sim_payload=None)
        assert cb["total_cost"] == 5000.0
        
        # Test 2: from objective_value
        result_payload = {
            "objective_value": 6000.0,
            "obj_breakdown": {},
        }
        cb = _cost_breakdown(result_payload, sim_payload=None)
        assert cb["total_cost"] == 6000.0
        
        # Test 3: from sim_payload (highest priority)
        result_payload = {
            "objective_value": 6000.0,
            "obj_breakdown": {"total_cost": 5000.0},
        }
        sim_payload = {"total_operating_cost": 7000.0}
        cb = _cost_breakdown(result_payload, sim_payload=sim_payload)
        assert cb["total_cost"] == 7000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
