#!/usr/bin/env python3
"""
Generate PV profile for scenario 237d5623-aa94-4f72-9da1-17b9070264be
PV capacity: 100kW
Operating hours: 05:00-21:00 (16 hours, 64 slots @ 15min)
"""
import json
import math
from pathlib import Path

def generate_pv_profile(
    pv_capacity_kw: float = 100.0,
    start_hour: int = 5,
    end_hour: int = 21,
    timestep_min: int = 15,
) -> list[float]:
    """
    Generate realistic PV generation profile using sinusoidal approximation.
    
    PV generation pattern:
    - 05:00-07:00: Sunrise ramp-up (0% -> 40%)
    - 07:00-09:00: Morning rise (40% -> 80%)
    - 09:00-15:00: Peak generation (80% -> 100% -> 80%)
    - 15:00-17:00: Afternoon decline (80% -> 40%)
    - 17:00-21:00: Sunset ramp-down (40% -> 0%)
    """
    total_hours = end_hour - start_hour
    slots_per_hour = 60 // timestep_min
    total_slots = total_hours * slots_per_hour
    
    profile = []
    
    # Peak solar noon at 12:00
    peak_hour = 12.0
    
    for slot_idx in range(total_slots):
        slot_hour = start_hour + (slot_idx * timestep_min) / 60.0
        
        # Sinusoidal generation with peak at solar noon
        # Phase shift to center peak at 12:00
        hour_from_sunrise = slot_hour - start_hour
        hour_to_sunset = end_hour - slot_hour
        
        if hour_from_sunrise < 0 or hour_to_sunset < 0:
            # Outside operating hours
            generation_kw = 0.0
        else:
            # Use sinusoidal curve centered at solar noon
            # Normalize to 0-1 range over the day
            day_fraction = (slot_hour - start_hour) / total_hours
            
            # Sin curve: 0 at sunrise/sunset, 1 at solar noon
            sin_value = math.sin(math.pi * day_fraction)
            
            # Apply realistic capacity factor
            # Morning/evening: lower factor
            # Midday: higher factor (up to 90% of installed capacity)
            if 6 <= slot_hour < 8:
                capacity_factor = 0.5  # Morning
            elif 8 <= slot_hour < 16:
                capacity_factor = 0.9  # Midday peak
            elif 16 <= slot_hour < 18:
                capacity_factor = 0.7  # Afternoon
            else:
                capacity_factor = 0.3  # Early morning / evening
            
            generation_kw = pv_capacity_kw * sin_value * capacity_factor
            
            # Ensure non-negative
            generation_kw = max(0.0, generation_kw)
        
        profile.append(round(generation_kw, 2))
    
    return profile


def update_scenario_with_pv_profile(scenario_id: str):
    """Update scenario document with PV generation profile."""
    scenario_path = Path(f"c:/master-course/output/scenarios/{scenario_id}.json")
    
    if not scenario_path.exists():
        print(f"❌ Scenario not found: {scenario_path}")
        return
    
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)
    
    # Generate PV profile
    pv_profile = generate_pv_profile(
        pv_capacity_kw=100.0,
        start_hour=5,
        end_hour=21,
        timestep_min=15,
    )
    
    # Convert kW to kWh for 15-min slots
    timestep_h = 15.0 / 60.0
    pv_kwh_by_slot = [kw * timestep_h for kw in pv_profile]
    
    print(f"✅ Generated PV profile: {len(pv_kwh_by_slot)} slots")
    print(f"   Total generation: {sum(pv_kwh_by_slot):.2f} kWh/day")
    print(f"   Peak generation: {max(pv_kwh_by_slot):.2f} kWh/slot ({max(pv_profile):.2f} kW)")
    print(f"   Average (daylight): {sum(pv_kwh_by_slot)/len([x for x in pv_kwh_by_slot if x > 0]):.2f} kWh/slot")
    
    # Update simulation_config with PV profile
    if "simulation_config" not in scenario or scenario["simulation_config"] is None:
        scenario["simulation_config"] = {}
    
    if "depot_energy_assets" not in scenario["simulation_config"]:
        scenario["simulation_config"]["depot_energy_assets"] = []
    
    # Find or create depot asset entry
    depot_asset = next(
        (asset for asset in scenario["simulation_config"]["depot_energy_assets"] 
         if asset.get("depot_id") == "tsurumaki"),
        None
    )
    
    if depot_asset is None:
        depot_asset = {"depot_id": "tsurumaki"}
        scenario["simulation_config"]["depot_energy_assets"].append(depot_asset)
    
    # Update PV settings
    depot_asset["pv_enabled"] = True
    depot_asset["pv_generation_kwh_by_slot"] = pv_kwh_by_slot
    depot_asset["pv_capacity_kw"] = 100.0
    
    # Write back to file
    with open(scenario_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Updated scenario: {scenario_path}")
    
    # Also print sample values
    print("\n=== Sample PV Generation (first 20 slots) ===")
    for i in range(min(20, len(pv_profile))):
        slot_hour = 5 + (i * 15) / 60.0
        hours = int(slot_hour)
        mins = int((slot_hour - hours) * 60)
        print(f"Slot {i:2d} ({hours:02d}:{mins:02d}): {pv_profile[i]:5.2f} kW -> {pv_kwh_by_slot[i]:5.2f} kWh")


if __name__ == "__main__":
    scenario_id = "237d5623-aa94-4f72-9da1-17b9070264be"
    update_scenario_with_pv_profile(scenario_id)
