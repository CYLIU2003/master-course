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


def build_depot_arcs(
    trips: List[GeneratedTrip],
    terminals: List[Terminal],
    deadhead_speed_kmh: float = 30.0,
    terminal_distance_km: Optional[Dict[Tuple[str, str], float]] = None,
    energy_rate_kwh_per_km: float = 1.2,
    pullout_buffer_min: float = 10.0,
    pullin_buffer_min: float = 5.0,
) -> List[DeadheadArc]:
    """デポ出庫 (pull-out) / デポ入庫 (pull-in) 弧を生成する。

    spec_v3 §4.3 拡張:
      - pull_out: depot → trip.origin (始業前にデポから回送)
      - pull_in:  trip.destination → depot (終業後にデポへ回送)
      - 充電迂回弧 (charger_detour): trip ↔ charger_site 間の回送弧も付加

    Parameters
    ----------
    trips : List[GeneratedTrip]
    terminals : List[Terminal]
    deadhead_speed_kmh : float
    terminal_distance_km : 端末間距離 [km] 辞書
    energy_rate_kwh_per_km : float  デッドヘッド走行の BEV エネルギー消費率
    pullout_buffer_min : float  出庫準備時間 [min]
    pullin_buffer_min : float   入庫後片付時間 [min]

    Returns
    -------
    List[DeadheadArc]
    """
    depot_terminals = [t for t in terminals if getattr(t, 'is_depot', False)]
    charger_terminals = [t for t in terminals if getattr(t, 'has_charger_site', False)]
    arcs: List[DeadheadArc] = []

    def _dist(from_id: str, to_id: str) -> float:
        if from_id == to_id:
            return 0.0
        if terminal_distance_km:
            return terminal_distance_km.get(
                (from_id, to_id),
                terminal_distance_km.get((to_id, from_id), 0.0))
        return 0.0

    def _time(dist_km: float) -> float:
        return (dist_km / deadhead_speed_kmh * 60.0) if deadhead_speed_kmh > 0 else 0.0

    # --- pull-out arcs: depot → first stop of each trip ---
    for trip in trips:
        for depot in depot_terminals:
            dist = _dist(depot.terminal_id, trip.origin_terminal_id)
            dh_time = _time(dist) + pullout_buffer_min
            energy = dist * energy_rate_kwh_per_km

            arcs.append(DeadheadArc(
                arc_id=f"pullout_{depot.terminal_id}_to_{trip.trip_id}",
                from_trip_id=f"__depot_{depot.terminal_id}",
                to_trip_id=trip.trip_id,
                from_terminal_id=depot.terminal_id,
                to_terminal_id=trip.origin_terminal_id,
                deadhead_time_min=round(dh_time, 2),
                deadhead_distance_km=round(dist, 4),
                deadhead_energy_kwh_bev=round(energy, 4),
                is_feasible_connection=True,
            ))

    # --- pull-in arcs: last stop of each trip → depot ---
    for trip in trips:
        for depot in depot_terminals:
            dist = _dist(trip.destination_terminal_id, depot.terminal_id)
            dh_time = _time(dist) + pullin_buffer_min
            energy = dist * energy_rate_kwh_per_km

            arcs.append(DeadheadArc(
                arc_id=f"pullin_{trip.trip_id}_to_{depot.terminal_id}",
                from_trip_id=trip.trip_id,
                to_trip_id=f"__depot_{depot.terminal_id}",
                from_terminal_id=trip.destination_terminal_id,
                to_terminal_id=depot.terminal_id,
                deadhead_time_min=round(dh_time, 2),
                deadhead_distance_km=round(dist, 4),
                deadhead_energy_kwh_bev=round(energy, 4),
                is_feasible_connection=True,
            ))

    # --- charger detour arcs: trip → charger_site → next trip ---
    for trip in trips:
        for csit in charger_terminals:
            if csit.terminal_id == trip.destination_terminal_id:
                continue  # 既に終点が charger → 迂回不要
            dist_to = _dist(trip.destination_terminal_id, csit.terminal_id)
            if dist_to <= 0:
                continue
            dh_time_to = _time(dist_to)
            energy_to = dist_to * energy_rate_kwh_per_km

            arcs.append(DeadheadArc(
                arc_id=f"detour_{trip.trip_id}_to_{csit.terminal_id}",
                from_trip_id=trip.trip_id,
                to_trip_id=f"__charger_{csit.terminal_id}",
                from_terminal_id=trip.destination_terminal_id,
                to_terminal_id=csit.terminal_id,
                deadhead_time_min=round(dh_time_to, 2),
                deadhead_distance_km=round(dist_to, 4),
                deadhead_energy_kwh_bev=round(energy_to, 4),
                is_feasible_connection=True,
            ))

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


def build_full_network(
    trips: List[GeneratedTrip],
    terminals: List[Terminal],
    turnaround_buffer_min: float = 5.0,
    deadhead_speed_kmh: float = 30.0,
    terminal_distance_km: Optional[Dict[Tuple[str, str], float]] = None,
    energy_rate_kwh_per_km: float = 1.2,
) -> Tuple[List[DeadheadArc], Dict[str, Set[str]]]:
    """Trip 間弧 + デポ出入庫弧 + 充電迂回弧を統合した完全ネットワークを構築。

    Returns
    -------
    (all_arcs, can_follow_matrix)
    """
    trip_arcs = build_deadhead_arcs(
        trips, terminals, turnaround_buffer_min,
        deadhead_speed_kmh, terminal_distance_km,
    )
    depot_arcs = build_depot_arcs(
        trips, terminals, deadhead_speed_kmh,
        terminal_distance_km, energy_rate_kwh_per_km,
    )
    all_arcs = trip_arcs + depot_arcs
    matrix = build_can_follow_matrix(all_arcs)
    return all_arcs, matrix
