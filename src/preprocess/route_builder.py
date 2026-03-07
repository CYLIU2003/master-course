"""
src.preprocess.route_builder — 路線ネットワーク整合性検査・集計

spec_v3 §10.1 / agent_route_editable §2.1
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.schemas.route_entities import Route, Segment, RouteVariant, Stop, Terminal


def validate_route_network(
    routes: List[Route],
    stops: List[Stop],
    segments: List[Segment],
    variants: List[RouteVariant],
    terminals: List[Terminal],
) -> List[str]:
    """路線ネットワークの整合性を検査する。

    Returns
    -------
    errors : List[str]
        問題点のリスト。空リストなら OK。
    """
    errors: List[str] = []

    route_ids = {r.route_id for r in routes}
    stop_ids = {s.stop_id for s in stops}
    seg_ids = {s.segment_id for s in segments}
    terminal_ids = {t.terminal_id for t in terminals}

    # Stop の route_id 参照
    for s in stops:
        if s.route_id not in route_ids:
            errors.append(f"Stop {s.stop_id}: route_id '{s.route_id}' が routes に存在しない")

    # Segment の stop 参照
    for seg in segments:
        if seg.route_id not in route_ids:
            errors.append(f"Segment {seg.segment_id}: route_id '{seg.route_id}' が存在しない")
        if seg.from_stop_id not in stop_ids:
            errors.append(f"Segment {seg.segment_id}: from_stop_id '{seg.from_stop_id}' が存在しない")
        if seg.to_stop_id not in stop_ids:
            errors.append(f"Segment {seg.segment_id}: to_stop_id '{seg.to_stop_id}' が存在しない")
        if seg.distance_km < 0:
            errors.append(f"Segment {seg.segment_id}: distance_km が負値 ({seg.distance_km})")

    # RouteVariant の segment 参照
    for v in variants:
        if v.route_id not in route_ids:
            errors.append(f"Variant {v.variant_id}: route_id '{v.route_id}' が存在しない")
        for sid in v.segment_id_list:
            if sid not in seg_ids:
                errors.append(f"Variant {v.variant_id}: segment '{sid}' が存在しない")

    return errors


def build_variant_segments(
    variant: RouteVariant,
    seg_index: Dict[str, Segment],
) -> List[Segment]:
    """RouteVariant の segment_id_list を実体 Segment リストに展開する。

    Parameters
    ----------
    variant : RouteVariant
    seg_index : Dict[str, Segment]
        segment_id → Segment のインデックス

    Returns
    -------
    List[Segment] : sequence 順に並んだ Segment リスト
    """
    result: List[Segment] = []
    for sid in variant.segment_id_list:
        seg = seg_index.get(sid)
        if seg is None:
            raise KeyError(f"Segment '{sid}' が seg_index に存在しない")
        result.append(seg)
    return result


def summarize_route_statistics(
    variant: RouteVariant,
    segments: List[Segment],
) -> Dict[str, float]:
    """Variant の統計量を計算する。

    Returns
    -------
    dict with keys:
        total_distance_km, total_runtime_min, total_dwell_min,
        avg_speed_kmh, segment_count, grade_weighted_avg_pct
    """
    total_dist = sum(s.distance_km for s in segments)
    total_run = sum(s.scheduled_run_time_min for s in segments)
    n = len(segments)

    avg_speed = (total_dist / (total_run / 60.0)) if total_run > 0 else 0.0

    grade_vals = [s.grade_avg_pct for s in segments if s.grade_avg_pct is not None]
    grade_weighted = (
        sum(abs(g) * s.distance_km for g, s in zip(grade_vals, segments) if g is not None)
        / total_dist
        if total_dist > 0 and grade_vals
        else 0.0
    )

    return {
        "total_distance_km": round(total_dist, 4),
        "total_runtime_min": round(total_run, 2),
        "avg_speed_kmh": round(avg_speed, 2),
        "segment_count": n,
        "grade_weighted_avg_pct": round(grade_weighted, 4),
    }
