"""Necessary session-time limits for the continuous Stage 1 charging model."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def add_session_time_relaxation(
    model: Any, grb: Any, *, vehicle_id: str,
    slot_indices: Sequence[int], charge_power: Mapping, charge_on: Mapping,
    power_limit_kw: float, timestep_h: float, metadata: Mapping,
) -> int:
    """Preserve every exact charging session while excluding impossible energy.

    Start/end variables stay continuous. Lower bounds on their changes and
    nonnegative overhead give a relaxation of Stage 2's binary session model.
    Both horizon boundaries are inactive, as in the full-week Stage 2 model.
    SOC taper and minimum on-time remain deferred to Stage 2.
    """
    mode = str(metadata.get('charging_power_model') or 'constant_power_v0').strip().lower()
    if mode == 'constant_power_v0' or not slot_indices:
        return 0
    if mode != 'piecewise_soc_taper_v1':
        raise ValueError(f'unsupported charging_power_model: {mode}')
    setup_h = max(float(metadata.get('charge_setup_minutes') or 0), 0.0) / 60
    teardown_h = max(float(metadata.get('charge_teardown_minutes') or 0), 0.0) / 60
    minimum_minutes = max(int(metadata.get('minimum_charge_session_minutes') or 0), 0)
    required_slots = max(math.ceil(minimum_minutes / max(timestep_h * 60, 1.0)), 1)
    if setup_h + teardown_h >= timestep_h * required_slots:
        raise ValueError('charge setup and teardown time must be shorter than the minimum charge-session duration')
    if setup_h == teardown_h == 0:
        return 0
    power = max(float(power_limit_kw), 0.0)
    for position, slot in enumerate(slot_indices):
        key = (vehicle_id, slot)
        on = charge_on[key]
        previous = charge_on[(vehicle_id, slot_indices[position - 1])] if position else 0.0
        following = charge_on[(vehicle_id, slot_indices[position + 1])] if position + 1 < len(slot_indices) else 0.0
        start = model.addVar(lb=0, ub=1, vtype=grb.CONTINUOUS,
                             name=f'stage1_session_start__{vehicle_id}__{slot}')
        end = model.addVar(lb=0, ub=1, vtype=grb.CONTINUOUS,
                           name=f'stage1_session_end__{vehicle_id}__{slot}')
        model.addConstr(start >= on - previous,
                        name=f'stage1_session_start_lower__{vehicle_id}__{slot}')
        model.addConstr(end >= on - following,
                        name=f'stage1_session_end_lower__{vehicle_id}__{slot}')
        model.addConstr(
            charge_power[key] * timestep_h <= power * (timestep_h * on - setup_h * start - teardown_h * end),
            name=f'stage1_session_net_time__{vehicle_id}__{slot}',
        )
    return 3 * len(slot_indices)
