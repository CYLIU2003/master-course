from __future__ import annotations

from typing import Any, Dict, List, Optional

from bff.services.route_family import (
    RawRoute,
    RouteDerivedMeta,
    _DEPOT_THRESHOLD,
    _depot_signal,
    _determine_main_pair,
    _has_depot_keyword,
    _is_reverse_pair,
    _is_same_pair,
    _is_short_turn,
    _route_overlap_score,
    _stable_id,
    _terminal_membership_flags,
    extract_route_family_code,
    has_user_manual_override,
    normalize_terminal_name,
)
from src.route_code_utils import extract_route_series_from_candidates
from src.route_family_runtime import (
    normalize_direction as runtime_normalize_direction,
    normalize_variant_type as runtime_normalize_variant_type,
)


_OFFICIAL_CLASSIFICATION_SOURCE = "official_manual_override"


def _official_route_family_label(family_code: str) -> Optional[str]:
    labels = {
        "東98": "東京駅南口 ⇔ 清水",
        "渋41": "渋谷駅 ⇔ 大井町駅",
        "渋42": "渋谷駅 ⇔ 大崎駅西口",
    }
    return labels.get(family_code)


def _official_variant_override_for_family(
    family_code: str,
    start_stop: str,
    end_stop: str,
) -> Optional[tuple[str, str, int, float, str]]:
    if not family_code:
        return None

    start = normalize_terminal_name(start_stop)
    end = normalize_terminal_name(end_stop)
    pair = (start, end)

    if family_code == "東98":
        main_out = ("東京駅", "清水")
        main_in = ("清水", "東京駅")
        depot = "等々力操車所"
        depot_counterparts = {"東京駅", "清水", "目黒駅", "目黒郵便局"}

        if pair == main_out:
            return ("main_outbound", "outbound", 10, 0.99, "official_tag:EAST98_MAIN")
        if pair == main_in:
            return ("main_inbound", "inbound", 20, 0.99, "official_tag:EAST98_MAIN")
        if start == depot and end in depot_counterparts:
            return ("depot_out", "outbound", 40, 0.99, "official_tag:EAST98_DEPOT")
        if end == depot and start in depot_counterparts:
            return ("depot_in", "inbound", 50, 0.99, "official_tag:EAST98_DEPOT")
        return None

    if family_code == "渋41":
        if pair == ("渋谷駅", "大井町駅"):
            return ("main_outbound", "outbound", 10, 0.99, "official_tag:SHIBU41_MAIN")
        if pair == ("大井町駅", "渋谷駅"):
            return ("main_inbound", "inbound", 20, 0.99, "official_tag:SHIBU41_MAIN")

        short_turn_pairs = {
            ("渋谷駅", "中目黒駅"),
            ("中目黒駅", "渋谷駅"),
            ("渋谷駅", "大鳥神社前"),
            ("大鳥神社前", "渋谷駅"),
            ("渋谷駅", "新馬場駅前"),
            ("新馬場駅前", "渋谷駅"),
        }
        if pair in short_turn_pairs:
            direction = "outbound" if start == "渋谷駅" else "inbound"
            return ("short_turn", direction, 30, 0.98, "official_tag:SHIBU41_SHORT_TURN")

        if "清水" in {start, end}:
            direction = "outbound" if start == "渋谷駅" else "inbound"
            return ("branch", direction, 60, 0.98, "official_tag:SHIBU41_BRANCH")
        return None

    if family_code == "渋42":
        if pair == ("渋谷駅", "大崎駅"):
            return ("main_outbound", "outbound", 10, 0.99, "official_tag:SHIBU42_MAIN")
        if pair == ("大崎駅", "渋谷駅"):
            return ("main_inbound", "inbound", 20, 0.99, "official_tag:SHIBU42_MAIN")
        if "清水" in {start, end}:
            direction = "outbound" if start == "渋谷駅" else "inbound"
            return ("branch", direction, 60, 0.98, "official_tag:SHIBU42_BRANCH")
        return None

    return None


def _apply_official_variant_override(
    route: RawRoute,
    family_code: str,
    variant_type: str,
    direction: str,
    sort_order: int,
    confidence: float,
    reasons: List[str],
) -> tuple[str, str, int, float, List[str], bool]:
    override = _official_variant_override_for_family(
        family_code,
        str(route.start_stop or ""),
        str(route.end_stop or ""),
    )
    if override is None:
        return variant_type, direction, sort_order, confidence, reasons, False

    o_variant_type, o_direction, o_sort_order, o_confidence, o_reason = override
    merged_reasons = list(reasons)
    merged_reasons.append(o_reason)
    return o_variant_type, o_direction, o_sort_order, max(confidence, o_confidence), merged_reasons, True


def effective_route_direction(route: Dict[str, Any], default: str = "unknown") -> str:
    if has_user_manual_override(route):
        return runtime_normalize_direction(
            route.get("canonicalDirectionManual") or route.get("canonicalDirection") or default,
            default=default,
        )
    return runtime_normalize_direction(
        route.get("canonicalDirection")
        or route.get("canonical_direction")
        or route.get("direction")
        or default,
        default=default,
    )


def effective_route_variant_type(route: Dict[str, Any], default: str = "unknown") -> str:
    direction = effective_route_direction(route, default="unknown")
    if has_user_manual_override(route):
        return runtime_normalize_variant_type(
            route.get("routeVariantTypeManual") or route.get("routeVariantType") or default,
            direction=direction,
        )
    return runtime_normalize_variant_type(
        route.get("routeVariantType")
        or route.get("route_variant_type")
        or default,
        direction=direction,
    )


def _best_depot_reference(
    route: RawRoute,
    routes: List[RawRoute],
) -> tuple[Optional[RawRoute], float, tuple[bool, bool, bool, bool]]:
    start = str(route.start_stop or "")
    end = str(route.end_stop or "")
    start_is_depot = _has_depot_keyword(start)
    end_is_depot = _has_depot_keyword(end)
    if start_is_depot == end_is_depot:
        return None, 0.0, (False, False, False, False)

    depot_terminal = normalize_terminal_name(start if start_is_depot else end)
    best_route: Optional[RawRoute] = None
    best_score = 0.0
    best_flags = (False, False, False, False)

    for candidate in routes:
        if candidate.route_id == route.route_id:
            continue
        candidate_start = normalize_terminal_name(candidate.start_stop)
        candidate_end = normalize_terminal_name(candidate.end_stop)
        if depot_terminal not in {candidate_start, candidate_end}:
            continue
        flags = _terminal_membership_flags(route, candidate)
        overlap = _route_overlap_score(route, candidate)
        score = overlap
        if flags[2] or flags[3]:
            score += 0.35
        if flags[0] and flags[1]:
            score += 0.2
        if (candidate.trip_count or 0) > (route.trip_count or 0):
            score += 0.05
        if score > best_score:
            best_route = candidate
            best_score = score
            best_flags = flags
    return best_route, best_score, best_flags


def _classify_family_runtime(routes: List[RawRoute]) -> Dict[str, RouteDerivedMeta]:
    if not routes:
        return {}

    family_code = extract_route_family_code(routes[0])
    series_code, series_prefix, series_number, _series_source = (
        extract_route_series_from_candidates(
            routes[0].route_code,
            routes[0].route_label,
            routes[0].name,
        )
    )
    family_id = _stable_id("routefam", family_code)
    main_out, main_in = _determine_main_pair(routes)
    main_candidates = [r for r in (main_out, main_in) if r is not None]

    result: Dict[str, RouteDerivedMeta] = {}
    for route in routes:
        variant_type = "unknown"
        direction = "unknown"
        is_primary = False
        sort_order = 999
        confidence = 0.0
        reasons: List[str] = []

        if main_out and route.route_id == main_out.route_id:
            variant_type = "main_outbound" if main_in else "main"
            direction = "outbound" if main_in else "unknown"
            is_primary = True
            sort_order = 10
            confidence = 0.95
            reasons.append(
                "highest score in family"
                + ("; reverse pair found" if main_in else "; no reverse pair")
            )
        elif main_in and route.route_id == main_in.route_id:
            variant_type = "main_inbound"
            direction = "inbound"
            is_primary = True
            sort_order = 20
            confidence = 0.95
            reasons.append("reverse pair of primary outbound")
        elif main_out and _is_same_pair(route, main_out):
            variant_type = "main_outbound" if main_in else "main"
            direction = "outbound" if main_in else "unknown"
            sort_order = 10
            confidence = 0.90
            reasons.append("terminal pair matches main outbound")
        elif main_in and _is_same_pair(route, main_in):
            variant_type = "main_inbound"
            direction = "inbound"
            sort_order = 20
            confidence = 0.90
            reasons.append("terminal pair matches main inbound")
        elif main_out and _is_reverse_pair(route, main_out):
            variant_type = "main_inbound"
            direction = "inbound"
            sort_order = 20
            confidence = 0.85
            reasons.append("terminal pair is reverse of main outbound")
        elif main_in and _is_reverse_pair(route, main_in):
            variant_type = "main_outbound"
            direction = "outbound"
            sort_order = 10
            confidence = 0.85
            reasons.append("terminal pair is reverse of main inbound")
        else:
            start = str(route.start_stop or "")
            end = str(route.end_stop or "")
            start_is_depot = _has_depot_keyword(start)
            end_is_depot = _has_depot_keyword(end)
            depot_reference, depot_ref_score, depot_ref_flags = _best_depot_reference(
                route,
                routes,
            )

            best_main: Optional[RawRoute] = None
            best_direction = "unknown"
            best_overlap = 0.0
            for candidate_main, candidate_direction in (
                (main_out, "outbound"),
                (main_in, "inbound"),
            ):
                overlap = _route_overlap_score(route, candidate_main)
                if overlap > best_overlap:
                    best_main = candidate_main
                    best_direction = candidate_direction
                    best_overlap = overlap

            if (start_is_depot ^ end_is_depot) and best_main is not None:
                start_on, end_on, start_interior, end_interior = _terminal_membership_flags(
                    route, best_main
                )
                if (
                    best_overlap >= 0.45
                    or start_on
                    or end_on
                    or start_interior
                    or end_interior
                ):
                    variant_type = "depot_out" if start_is_depot else "depot_in"
                    direction = "outbound" if start_is_depot else "inbound"
                    sort_order = 40 if start_is_depot else 50
                    confidence = max(0.72, min(0.90, 0.6 + best_overlap * 0.3))
                    reasons.append("depot-like terminal plus overlap with main corridor")
                    if start_interior or end_interior:
                        reasons.append("non-depot terminal lies inside main stop sequence")

            if (
                variant_type == "unknown"
                and (start_is_depot ^ end_is_depot)
                and depot_reference is not None
            ):
                start_on, end_on, start_interior, end_interior = depot_ref_flags
                if depot_ref_score >= 0.65 or (
                    start_on and end_on and (start_interior or end_interior)
                ):
                    variant_type = "depot_out" if start_is_depot else "depot_in"
                    direction = "outbound" if start_is_depot else "inbound"
                    sort_order = 40 if start_is_depot else 50
                    confidence = max(0.70, min(0.88, 0.52 + depot_ref_score * 0.25))
                    reasons.append(
                        "depot-like terminal plus overlap with same-family depot corridor"
                    )
                    if start_interior or end_interior:
                        reasons.append("non-depot terminal lies inside depot feeder corridor")

            if variant_type == "unknown" and not start_is_depot and not end_is_depot:
                for candidate_main, candidate_direction in (
                    (main_out, "outbound"),
                    (main_in, "inbound"),
                ):
                    if candidate_main is None:
                        continue
                    start_on, end_on, start_interior, end_interior = _terminal_membership_flags(
                        route, candidate_main
                    )
                    if _is_short_turn(route, candidate_main) or (
                        start_on and end_on and (start_interior or end_interior)
                    ):
                        variant_type = "short_turn"
                        direction = candidate_direction
                        sort_order = 30
                        confidence = 0.78
                        reasons.append(
                            "both terminals lie on main corridor and at least one is interior"
                        )
                        break

            if variant_type == "unknown" and best_main is not None and best_overlap >= 0.4:
                variant_type = "branch"
                direction = best_direction
                sort_order = 60
                confidence = max(0.60, min(0.82, 0.45 + best_overlap * 0.35))
                reasons.append(
                    "overlaps strongly with main corridor but uses a different terminal pair"
                )

            if variant_type == "unknown":
                dep_score, dep_reasons = _depot_signal(route, main_candidates)
                if dep_score >= _DEPOT_THRESHOLD:
                    if start_is_depot and not end_is_depot:
                        variant_type = "depot_out"
                        direction = "outbound"
                        sort_order = 40
                    elif end_is_depot and not start_is_depot:
                        variant_type = "depot_in"
                        direction = "inbound"
                        sort_order = 50
                    confidence = min(dep_score / 4.0, 0.85)
                    reasons.extend(dep_reasons)
                    reasons.append(
                        f"depot signal score={dep_score:.2f} >= {_DEPOT_THRESHOLD}"
                    )
                else:
                    confidence = 0.1
                    if dep_reasons:
                        reasons.extend(dep_reasons)
                        reasons.append(
                            f"depot signal score={dep_score:.2f} below threshold {_DEPOT_THRESHOLD}"
                        )
                    else:
                        reasons.append("no classification criteria matched")

        start_is_depot = _has_depot_keyword(str(route.start_stop or ""))
        end_is_depot = _has_depot_keyword(str(route.end_stop or ""))
        if route.route_code == "出入庫" and (start_is_depot ^ end_is_depot):
            variant_type = "depot_out" if start_is_depot else "depot_in"
            direction = "outbound" if start_is_depot else "inbound"
            sort_order = 40 if start_is_depot else 50
            confidence = max(confidence, 0.92)
            reasons.append("generic depot move route code")

        (
            variant_type,
            direction,
            sort_order,
            confidence,
            reasons,
            official_override_applied,
        ) = _apply_official_variant_override(
            route,
            family_code,
            variant_type,
            direction,
            sort_order,
            confidence,
            reasons,
        )

        family_label = _official_route_family_label(family_code) if official_override_applied else family_code

        variant_id = _stable_id("routevar", family_code, route.route_id)
        result[route.route_id] = RouteDerivedMeta(
            route_family_id=family_id,
            route_family_code=family_code,
            route_family_label=family_label,
            route_variant_id=variant_id,
            route_variant_type=variant_type,
            canonical_direction=direction,
            is_primary_variant=is_primary,
            family_sort_order=sort_order,
            route_series_code=series_code or family_code,
            route_series_prefix=series_prefix,
            route_series_number=series_number,
            classification_confidence=confidence,
            classification_reasons=reasons,
        )
    return result


def derive_route_family_metadata_for_runtime(
    all_routes: List[Dict[str, Any]],
) -> Dict[str, RouteDerivedMeta]:
    raw_routes = [RawRoute.from_dict(route) for route in all_routes]
    groups: Dict[str, List[RawRoute]] = {}
    for route in raw_routes:
        groups.setdefault(extract_route_family_code(route), []).append(route)

    derived: Dict[str, RouteDerivedMeta] = {}
    for routes in groups.values():
        derived.update(_classify_family_runtime(routes))
    return derived


def reclassify_routes_for_runtime(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched = [dict(route) for route in routes]
    metadata = derive_route_family_metadata_for_runtime(enriched)
    for route in enriched:
        route_id = str(route.get("id") or route.get("route_id") or "").strip()
        meta = metadata.get(route_id)
        if meta is not None:
            route.update(meta.to_dict())
        if has_user_manual_override(route):
            route["routeVariantType"] = effective_route_variant_type(route)
            route["canonicalDirection"] = effective_route_direction(route)
            route["classificationSource"] = "user_manual_override"
        else:
            route.pop("routeVariantTypeManual", None)
            route.pop("canonicalDirectionManual", None)
            family_code = str(route.get("routeFamilyCode") or route.get("routeCode") or "")
            start_stop = str(route.get("startStop") or "")
            end_stop = str(route.get("endStop") or "")
            if _official_variant_override_for_family(family_code, start_stop, end_stop):
                route["classificationSource"] = _OFFICIAL_CLASSIFICATION_SOURCE
            else:
                route["classificationSource"] = "derived_runtime"
    return enriched
