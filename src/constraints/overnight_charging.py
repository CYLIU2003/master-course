"""
constraints/overnight_charging.py — 夜間充電禁止制約

allow_overnight_depot_moves="forbid" のとき、MILP で夜間スロット (デフォルト 23:00-05:00) の
充電を禁止する。

これにより:
- バスは夜間に充電を開始できない
- 夜間に開始した充電は許可されない
- 運行スケジュールに応じた日中充電が強制される

Note:
  - ALNS では既に allow_overnight_depot_moves パラメータで対応済み
  - この制約は MILP パスでの同等機能を提供する
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ..gurobi_runtime import ensure_gurobi


def _parse_time_to_minutes(time_str: str) -> int:
    """Parse time string "HH:MM" to minutes from midnight."""
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _get_overnight_slots(
    num_slots: int,
    timestep_min: int,
    horizon_start_min: int,
    overnight_start: str = "23:00",
    overnight_end: str = "05:00",
) -> Tuple[int, ...]:
    """
    Determine which slot indices fall within the overnight window.
    
    Parameters
    ----------
    num_slots : int
        Total number of time slots in the planning horizon
    timestep_min : int
        Duration of each time slot in minutes
    horizon_start_min : int
        Start time of planning horizon in minutes from midnight
    overnight_start : str
        Start of overnight window (e.g., "23:00")
    overnight_end : str
        End of overnight window (e.g., "05:00")
    
    Returns
    -------
    Tuple of slot indices that fall within the overnight window
    """
    start_min = _parse_time_to_minutes(overnight_start)
    end_min = _parse_time_to_minutes(overnight_end)
    
    overnight_slots = []
    
    for slot_idx in range(num_slots):
        slot_start_min = horizon_start_min + slot_idx * timestep_min
        # Normalize to 24-hour clock (handle multi-day scenarios)
        slot_time_of_day = slot_start_min % (24 * 60)
        
        # Check if slot falls within overnight window
        # Handle wrap-around (e.g., 23:00 to 05:00 crosses midnight)
        if start_min > end_min:
            # Window crosses midnight (e.g., 23:00 - 05:00)
            is_overnight = slot_time_of_day >= start_min or slot_time_of_day < end_min
        else:
            # Window does not cross midnight
            is_overnight = start_min <= slot_time_of_day < end_min
        
        if is_overnight:
            overnight_slots.append(slot_idx)
    
    return tuple(overnight_slots)


def add_overnight_charging_constraints(
    model: Any,
    data: Any,
    ms: Any,
    dp: Any,
    vars: Dict[str, Any],
    overnight_start: str = "23:00",
    overnight_end: str = "05:00",
) -> None:
    """
    Add overnight charging prohibition constraints to the MILP model.
    
    For all BEV vehicles and all chargers, prohibit charging during the
    overnight window (default 23:00 - 05:00).
    
    Constraint:
        z[k, c, t] = 0  for all k in K_BEV, c in C, t in overnight_slots
    
    Parameters
    ----------
    model : gurobipy.Model
        The Gurobi model to add constraints to
    data : ProblemData
        Problem data containing timestep_min, horizon_start, etc.
    ms : ModelSets
        Model sets containing K_BEV, C, T
    dp : DerivedParams
        Derived parameters (not used directly but kept for consistency)
    vars : dict
        Dictionary of model variables, must contain "z_charge"
    overnight_start : str
        Start of overnight window in "HH:MM" format
    overnight_end : str
        End of overnight window in "HH:MM" format
    """
    gp, GRB = ensure_gurobi()
    z = vars.get("z_charge")
    
    if z is None:
        return  # No charging variables, skip
    
    K_BEV = ms.K_BEV
    C = ms.C
    T = ms.T
    
    if not K_BEV or not C or not T:
        return  # No BEV vehicles or chargers, skip
    
    # Determine timestep and horizon start
    timestep_min = getattr(data, "timestep_min", 30)
    horizon_start_str = getattr(data, "horizon_start", "04:00")
    horizon_start_min = _parse_time_to_minutes(horizon_start_str)
    
    # Get overnight slots
    overnight_slots = _get_overnight_slots(
        num_slots=len(T),
        timestep_min=timestep_min,
        horizon_start_min=horizon_start_min,
        overnight_start=overnight_start,
        overnight_end=overnight_end,
    )
    
    if not overnight_slots:
        return  # No overnight slots in this horizon
    
    # Add constraints: z[k, c, t] = 0 for all overnight slots
    for t in overnight_slots:
        if t not in T:
            continue
        for k in K_BEV:
            for c in C:
                if (k, c, t) in z:
                    model.addConstr(
                        z[k, c, t] == 0,
                        name=f"overnight_no_charge[{k},{c},{t}]",
                    )
    
    model.update()


def is_overnight_charging_enabled(data: Any) -> bool:
    """
    Check if overnight charging prohibition should be enabled.
    
    Returns True if allow_overnight_depot_moves == "forbid"
    """
    allow_overnight = getattr(data, "allow_overnight_depot_moves", "forbid")
    return str(allow_overnight).lower() == "forbid"
