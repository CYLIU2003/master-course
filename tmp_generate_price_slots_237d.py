#!/usr/bin/env python3
"""
Generate energy price slots for scenario 237d5623-aa94-4f72-9da1-17b9070264be
Time-of-Use (TOU) pricing:
- Peak hours (09:00-16:00): 40 yen/kWh
- Off-peak hours (05:00-09:00, 16:00-21:00): 25 yen/kWh
"""
import json
from pathlib import Path

def generate_energy_price_slots(
    start_hour: int = 5,
    end_hour: int = 21,
    timestep_min: int = 15,
    peak_price: float = 40.0,
    offpeak_price: float = 25.0,
    peak_start_hour: int = 9,
    peak_end_hour: int = 16,
) -> list[dict]:
    """
    Generate TOU energy price slots.
    """
    total_hours = end_hour - start_hour
    slots_per_hour = 60 // timestep_min
    total_slots = total_hours * slots_per_hour
    
    slots = []
    
    for slot_idx in range(total_slots):
        slot_hour = start_hour + (slot_idx * timestep_min) / 60.0
        
        # Determine if peak or off-peak
        if peak_start_hour <= slot_hour < peak_end_hour:
            price = peak_price
            demand_weight = 1.0  # Peak hours count for demand charge
        else:
            price = offpeak_price
            demand_weight = 0.0  # Off-peak hours don't count
        
        slot = {
            "slot_index": slot_idx,
            "grid_buy_yen_per_kwh": price,
            "grid_sell_yen_per_kwh": 0.0,  # No sell-back
            "demand_charge_weight": demand_weight,
            "co2_factor": 0.5,  # kg-CO2/kWh (typical grid emission factor)
        }
        slots.append(slot)
    
    return slots


def update_scenario_with_price_slots(scenario_id: str):
    """Update scenario document with energy price slots."""
    scenario_path = Path(f"c:/master-course/output/scenarios/{scenario_id}.json")
    
    if not scenario_path.exists():
        print(f"❌ Scenario not found: {scenario_path}")
        return
    
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)
    
    # Generate price slots
    price_slots = generate_energy_price_slots(
        start_hour=5,
        end_hour=21,
        timestep_min=15,
        peak_price=40.0,
        offpeak_price=25.0,
        peak_start_hour=9,
        peak_end_hour=16,
    )
    
    print(f"✅ Generated {len(price_slots)} price slots")
    
    # Count peak vs off-peak
    peak_count = sum(1 for s in price_slots if s["demand_charge_weight"] > 0)
    offpeak_count = len(price_slots) - peak_count
    
    print(f"   Peak slots (40 yen/kWh): {peak_count}")
    print(f"   Off-peak slots (25 yen/kWh): {offpeak_count}")
    
    # Add to scenario_overlay
    if "scenario_overlay" not in scenario or scenario["scenario_overlay"] is None:
        scenario["scenario_overlay"] = {}
    
    scenario["scenario_overlay"]["energy_price_slots"] = price_slots
    
    # Write back to file
    with open(scenario_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Updated scenario: {scenario_path}")
    
    # Print sample
    print("\n=== Sample Price Slots (first 20) ===")
    for i in range(min(20, len(price_slots))):
        slot = price_slots[i]
        slot_hour = 5 + (i * 15) / 60.0
        hours = int(slot_hour)
        mins = int((slot_hour - hours) * 60)
        period = "PEAK" if slot["demand_charge_weight"] > 0 else "OFFPEAK"
        print(f"Slot {i:2d} ({hours:02d}:{mins:02d}): {slot['grid_buy_yen_per_kwh']:5.1f} yen/kWh  [{period}]")


if __name__ == "__main__":
    scenario_id = "237d5623-aa94-4f72-9da1-17b9070264be"
    update_scenario_with_price_slots(scenario_id)
