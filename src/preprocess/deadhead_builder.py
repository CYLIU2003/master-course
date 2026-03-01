"""
src.preprocess.deadhead_builder — Trip 間接続弧（デッドヘッド）生成

spec_v3 §4.3 / §10.6 / agent_route_editable §2.5
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from src.schemas.route_entities import DeadheadArc, GeneratedTrip, Terminal


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%H:%M")


def _minutes_between(t_start: str, t_end: str) -> float:
    """t_end - t_start [min]。翌日越えを考慮。"""
    dt_s = _parse_time(t_start)
    dt_e = _parse_time(t_end)
    diff = (dt_e - dt_s).total_seconds() / 60.0
    if diff < 0:
        diff += 24 * 60  # 翌日越え
    return diff


def build_deadhead_arcs(
    trips: List[GeneratedTrip],
    terminals: List[Terminal],
    turnaround_buffer_min: float = 5.0,
    deadhead_speed_kmh: float = 30.0,
    terminal_distance_km: Optional[Dict[Tuple[str, str], float]] = None,
) -> List[DeadheadArc]:
    """Trip 間の実行可能接続弧を生成する。

    接続 feasible 条件 (spec_v3 §4.3):
        arrival_time_i + turnaround_buffer + deadhead_time_ij <= departure_time_j
        同一 terminal なら deadhead = 0

    Parameters
    ----------
    trips : List[GeneratedTrip]
    terminals : List[Terminal]
    turnaround_buffer_min : float
        同一 terminal でのアイドル最小時間 [min]
    deadhead_speed_kmh : float
        デッドヘッド走行速度 (terminal 間距離 → 時間 の変換)
    terminal_distance_km : Optional[Dict[(from_id, to_id), float]]
        terminal 間距離 [km]。None の場合 0 とみなす。

    Returns
    -------
    List[DeadheadArc]
    """
    arcs: List[DeadheadArc] = []

    for i, trip_i in enumerate(trips):
        for j, trip_j in enumerate(trips):
            if i == j:
                continue

            from_terminal = trip_i.destination_terminal_id
            to_terminal = trip_j.origin_terminal_id

            # デッドヘッド距離・時間
            if from_terminal == to_terminal:
                dh_dist = 0.0
                dh_time = 0.0
            else:
                if terminal_distance_km:
                    dh_dist = terminal_distance_km.get(
                        (from_terminal, to_terminal),
                        terminal_distance_km.get((to_terminal, from_terminal), 0.0),
                    )
                else:
                    dh_dist = 0.0
                dh_time = (dh_dist / deadhead_speed_kmh * 60.0) if deadhead_speed_kmh > 0 else 0.0

            # feasibility 判定
            slack = _minutes_between(trip_i.arrival_time, trip_j.departure_time)
            required = turnaround_buffer_min + dh_time
            is_feasible = slack >= required

            reason = None if is_feasible else (
                f"slack={slack:.1f}min < required={required:.1f}min "
                f"(buffer={turnaround_buffer_min}+dh={dh_time:.1f})"
            )

            arc = DeadheadArc(
                arc_id=f"dh_{trip_i.trip_id}_to_{trip_j.trip_id}",
                from_trip_id=trip_i.trip_id,
                to_trip_id=trip_j.trip_id,
                from_terminal_id=from_terminal,
                to_terminal_id=to_terminal,
                deadhead_time_min=round(dh_time, 2),
                deadhead_distance_km=round(dh_dist, 4),
                is_feasible_connection=is_feasible,
                infeasibility_reason=reason,
            )
            arcs.append(arc)

    return arcs


def build_can_follow_matrix(
    arcs: List[DeadheadArc],
) -> Dict[str, Set[str]]:
    """feasible な接続のみを trip_id → Set[trip_id] 辞書に変換する。

    Returns
    -------
    Dict[trip_i_id, Set[trip_j_id]] : trip_i に続けて trip_j を担当可能
    """
    matrix: Dict[str, Set[str]] = {}
    for arc in arcs:
        if arc.is_feasible_connection:
            matrix.setdefault(arc.from_trip_id, set()).add(arc.to_trip_id)
    return matrix
