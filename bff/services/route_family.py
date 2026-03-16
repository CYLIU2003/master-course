"""
bff/services/route_family.py

Route family / variant classification layer.

Design principles:
  - Raw ODPT/GTFS route/pattern records are NEVER merged.
  - Route family is a DERIVED layer for UI grouping and reporting.
  - depot_out/depot_in is a weak, scored heuristic — NOT a keyword-only rule.
  - Classification confidence is exposed so UI can decide presentation.
  - Dispatch remains trip-based; family is auxiliary metadata only.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.route_code_utils import extract_route_series_from_candidates, normalize_route_code, route_code_sort_key
from src.value_normalization import coerce_str_list

# ── Type aliases ───────────────────────────────────────────────

VariantType = Literal[
    "main",
    "main_outbound",
    "main_inbound",
    "short_turn",
    "branch",
    "depot_out",
    "depot_in",
    "unknown",
]

DirectionType = Literal["outbound", "inbound", "circular", "unknown"]


# ── Data classes ───────────────────────────────────────────────

@dataclass
class RawRoute:
    """Thin adapter for raw route dicts from the scenario store."""
    route_id: str
    name: str
    route_code: Optional[str] = None
    route_label: Optional[str] = None
    start_stop: Optional[str] = None
    end_stop: Optional[str] = None
    stop_sequence: List[str] = field(default_factory=list)
    distance_km: Optional[float] = None
    duration_min: Optional[int] = None
    trip_count: Optional[int] = None
    external_pattern_id: Optional[str] = None
    external_route_id: Optional[str] = None
    source: str = "unknown"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RawRoute":
        return cls(
            route_id=d.get("id") or d.get("route_id", ""),
            name=d.get("name", ""),
            route_code=d.get("routeCode"),
            route_label=d.get("routeLabel"),
            start_stop=d.get("startStop"),
            end_stop=d.get("endStop"),
            stop_sequence=coerce_str_list(d.get("stopSequence")),
            distance_km=d.get("distanceKm"),
            duration_min=d.get("durationMin"),
            trip_count=d.get("tripCount"),
            external_pattern_id=d.get("patternId"),
            external_route_id=d.get("routeExternalId"),
            source=d.get("source") or "unknown",
        )


@dataclass
class RouteDerivedMeta:
    """Derived route family / variant classification."""
    route_family_id: str
    route_family_code: str
    route_family_label: str
    route_variant_id: str
    route_variant_type: VariantType
    canonical_direction: DirectionType
    is_primary_variant: bool
    family_sort_order: int
    route_series_code: str = ""
    route_series_prefix: str = ""
    route_series_number: Optional[int] = None
    classification_confidence: float = 0.0
    classification_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routeFamilyId": self.route_family_id,
            "routeFamilyCode": self.route_family_code,
            "routeFamilyLabel": self.route_family_label,
            "routeVariantId": self.route_variant_id,
            "routeVariantType": self.route_variant_type,
            "canonicalDirection": self.canonical_direction,
            "isPrimaryVariant": self.is_primary_variant,
            "familySortOrder": self.family_sort_order,
            "routeSeriesCode": self.route_series_code,
            "routeSeriesPrefix": self.route_series_prefix,
            "routeSeriesNumber": self.route_series_number,
            "classificationConfidence": round(self.classification_confidence, 3),
            "classificationReasons": self.classification_reasons,
        }


# ── Text normalization ─────────────────────────────────────────

def normalize_text(value: Optional[str]) -> str:
    """NFKC normalize: full-width digits → half-width, collapse whitespace."""
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", value)
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_stop_name(name: Optional[str]) -> str:
    """Normalize for stop comparison (remove fluff)."""
    s = normalize_text(name)
    s = s.replace("(駅)", "駅")
    s = s.replace("バス停", "")
    s = re.sub(r"\s+", "", s)
    return s


# ── Route code extraction ──────────────────────────────────────

_ROUTE_CODE_PATTERNS = [
    r"^([^\s(（]+)",          # first token before whitespace/parens
    r"\b([A-Za-z]+\d+)\b",   # alphanumeric code like TW01
    r"\b([^\s]+?\d+)\b",     # any token ending in digits
]


def extract_route_family_code(route: RawRoute) -> str:
    """
    Extract a normalized route family code.
    Priority: routeCode > routeLabel > name (first token).
    Full-width digits are → half-width (via NFKC).
    """
    series_code, _prefix, _num, _source = extract_route_series_from_candidates(
        route.route_code,
        route.route_label,
        route.name,
    )
    if series_code:
        return series_code

    candidates = [normalize_text(route.route_code), normalize_text(route.route_label), normalize_text(route.name)]
    for text in candidates:
        if not text:
            continue
        for pattern in _ROUTE_CODE_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return normalize_route_code(m.group(1)).replace("\u2212", "-").replace("\u30fc", "-")

    return f"UNCLASSIFIED:{route.route_id}"


# ── Depot-like detection (helper signal, NOT a classifier) ─────

_DEPOT_KEYWORDS = [
    "営業所", "車庫", "操車所", "出張所", "駐車場", "車両基地", "センター",
]


def _has_depot_keyword(stop_name: str) -> bool:
    """Check if a stop name contains depot-like keywords."""
    s = normalize_stop_name(stop_name)
    return any(w in s for w in _DEPOT_KEYWORDS)


# ── Stable ID generation ──────────────────────────────────────

def _stable_id(prefix: str, *parts: str) -> str:
    raw = "||".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _direction_for_variant_type(
    variant_type: VariantType,
    fallback: DirectionType = "unknown",
) -> DirectionType:
    if variant_type in {"main_outbound", "depot_out"}:
        return "outbound"
    if variant_type in {"main_inbound", "depot_in"}:
        return "inbound"
    if variant_type in {"main", "branch", "unknown"}:
        return fallback
    if variant_type == "short_turn":
        return fallback
    return fallback


# ── Terminal pair helpers ──────────────────────────────────────

def _terminal_pair(route: RawRoute) -> Tuple[str, str]:
    return (
        normalize_stop_name(route.start_stop),
        normalize_stop_name(route.end_stop),
    )


def _is_reverse_pair(a: RawRoute, b: RawRoute) -> bool:
    a0, a1 = _terminal_pair(a)
    b0, b1 = _terminal_pair(b)
    return a0 == b1 and a1 == b0 and a0 != a1


def _is_same_pair(a: RawRoute, b: RawRoute) -> bool:
    return _terminal_pair(a) == _terminal_pair(b)


# ── Scoring helpers ────────────────────────────────────────────

def _score_as_main(route: RawRoute) -> Tuple[int, int, float]:
    """Score for picking primary main routes; higher is better."""
    trip_count = route.trip_count or 0
    stop_count = len(route.stop_sequence or [])
    distance = route.distance_km or 0.0
    return (trip_count, stop_count, distance)


def _normalized_stop_sequence(route: RawRoute) -> List[str]:
    return [
        normalize_stop_name(x)
        for x in (route.stop_sequence or [])
        if normalize_stop_name(x)
    ]


def _is_subsequence(shorter: List[str], longer: List[str]) -> bool:
    """Check if shorter is an ordered subsequence of longer."""
    if not shorter or not longer:
        return False
    it = iter(longer)
    return all(any(s == x for x in it) for s in shorter)


def _common_prefix_ratio(a: List[str], b: List[str]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    same = 0
    for i in range(n):
        if a[i] == b[i]:
            same += 1
        else:
            break
    return same / max(len(a), len(b), 1)


# ── Short-turn / branch detection ─────────────────────────────

def _is_short_turn(candidate: RawRoute, main_route: RawRoute) -> bool:
    cseq = _normalized_stop_sequence(candidate)
    mseq = _normalized_stop_sequence(main_route)
    if len(cseq) >= len(mseq):
        return False
    return _is_subsequence(cseq, mseq)


def _is_branch(candidate: RawRoute, main_route: RawRoute) -> bool:
    cseq = _normalized_stop_sequence(candidate)
    mseq = _normalized_stop_sequence(main_route)
    if not cseq or not mseq:
        return False
    if _is_same_pair(candidate, main_route) or _is_reverse_pair(candidate, main_route):
        return False
    return _common_prefix_ratio(cseq, mseq) >= 0.4


# ── Depot signal scoring (NOT keyword-only) ────────────────────

def _depot_signal(
    route: RawRoute,
    main_routes: List[RawRoute],
) -> Tuple[float, List[str]]:
    """
    Compute a depot-likelihood score.
    This is a WEAK heuristic — it must NOT be used alone.
    Depot classification only applies when the route is NOT already
    classified as main/reverse/short-turn/branch.
    """
    score = 0.0
    reasons: List[str] = []

    start = normalize_stop_name(route.start_stop)
    end = normalize_stop_name(route.end_stop)

    # Keyword signal (weak)
    if _has_depot_keyword(start):
        score += 0.8
        reasons.append("start contains depot-like keyword")
    if _has_depot_keyword(end):
        score += 0.8
        reasons.append("end contains depot-like keyword")

    # Low trip count signal
    trip_count = route.trip_count or 0
    if trip_count <= 2:
        score += 1.0
        reasons.append("very low trip count (<=2)")
    elif trip_count <= 5:
        score += 0.5
        reasons.append("low trip count (<=5)")

    # Shorter than main routes
    if main_routes:
        main_max_distance = max((r.distance_km or 0.0) for r in main_routes)
        if main_max_distance > 0 and (route.distance_km or 0.0) < 0.7 * main_max_distance:
            score += 0.8
            reasons.append("shorter than 70% of main route distance")

    # stop sequence is prefix/suffix of main
    rseq = _normalized_stop_sequence(route)
    for main in main_routes:
        mseq = _normalized_stop_sequence(main)
        if _is_subsequence(rseq, mseq) and len(rseq) < len(mseq):
            score += 0.8
            reasons.append("stop sequence is subset of main")
            break

    return score, reasons


# ── Main pair detection ────────────────────────────────────────

def _determine_main_pair(
    routes: List[RawRoute],
) -> Tuple[Optional[RawRoute], Optional[RawRoute]]:
    """Pick the primary main pair (outbound, inbound) by score."""
    ranked = sorted(routes, key=_score_as_main, reverse=True)
    if not ranked:
        return None, None

    main_a = ranked[0]
    for other in ranked[1:]:
        if _is_reverse_pair(main_a, other):
            return main_a, other

    return main_a, None


# ── Family classification ─────────────────────────────────────

_DEPOT_THRESHOLD = 2.0  # depot signal must exceed this to classify


def classify_family(routes: List[RawRoute]) -> Dict[str, RouteDerivedMeta]:
    """
    Classify all routes within one family.
    Returns a dict mapping route_id -> RouteDerivedMeta.
    """
    if not routes:
        return {}

    family_code = extract_route_family_code(routes[0])
    series_code, series_prefix, series_number, _series_source = extract_route_series_from_candidates(
        routes[0].route_code,
        routes[0].route_label,
        routes[0].name,
    )
    family_id = _stable_id("routefam", family_code)

    main_out, main_in = _determine_main_pair(routes)
    main_candidates = [r for r in [main_out, main_in] if r is not None]

    result: Dict[str, RouteDerivedMeta] = {}

    for route in routes:
        variant_type: VariantType = "unknown"
        direction: DirectionType = "unknown"
        is_primary = False
        sort_order = 999
        confidence = 0.0
        reasons: List[str] = []

        # ── 1) Main outbound/inbound ─────────────────────────
        if main_out and route.route_id == main_out.route_id:
            variant_type = "main_outbound" if main_in else "main"
            direction = "outbound" if main_in else "unknown"
            is_primary = True
            sort_order = 10
            confidence = 0.95
            reasons.append("highest score in family" + (
                "; reverse pair found" if main_in else "; no reverse pair"
            ))

        elif main_in and route.route_id == main_in.route_id:
            variant_type = "main_inbound"
            direction = "inbound"
            is_primary = True
            sort_order = 20
            confidence = 0.95
            reasons.append("reverse pair of primary outbound")

        # ── 2) Additional reverse pair detection ─────────────
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

        # ── 3) Short-turn ────────────────────────────────────
        elif main_out and _is_short_turn(route, main_out):
            variant_type = "short_turn"
            direction = "outbound"
            sort_order = 30
            confidence = 0.75
            reasons.append("stop sequence is strict subset of main outbound")

        elif main_in and _is_short_turn(route, main_in):
            variant_type = "short_turn"
            direction = "inbound"
            sort_order = 30
            confidence = 0.75
            reasons.append("stop sequence is strict subset of main inbound")

        # ── 4) Branch ────────────────────────────────────────
        elif main_out and _is_branch(route, main_out):
            variant_type = "branch"
            direction = "unknown"
            sort_order = 60
            confidence = 0.60
            reasons.append("shares >= 40% prefix with main outbound but different terminal pair")

        elif main_in and _is_branch(route, main_in):
            variant_type = "branch"
            direction = "unknown"
            sort_order = 60
            confidence = 0.60
            reasons.append("shares >= 40% prefix with main inbound but different terminal pair")

        else:
            # ── 5) Depot signal (scored, NOT keyword-only) ───
            dep_score, dep_reasons = _depot_signal(route, main_candidates)
            if dep_score >= _DEPOT_THRESHOLD:
                start = normalize_stop_name(route.start_stop)
                end = normalize_stop_name(route.end_stop)
                if _has_depot_keyword(start) and not _has_depot_keyword(end):
                    variant_type = "depot_out"
                    direction = "outbound"
                    sort_order = 40
                elif not _has_depot_keyword(start) and _has_depot_keyword(end):
                    variant_type = "depot_in"
                    direction = "inbound"
                    sort_order = 50
                else:
                    # Both or neither have depot keyword; weak signal
                    variant_type = "unknown"
                    sort_order = 999

                confidence = min(dep_score / 4.0, 0.85)
                reasons.extend(dep_reasons)
                reasons.append(f"depot signal score={dep_score:.2f} >= {_DEPOT_THRESHOLD}")
            else:
                # ── 6) Truly unknown ─────────────────────────
                variant_type = "unknown"
                confidence = 0.1
                if dep_reasons:
                    reasons.extend(dep_reasons)
                    reasons.append(
                        f"depot signal score={dep_score:.2f} below threshold {_DEPOT_THRESHOLD}"
                    )
                else:
                    reasons.append("no classification criteria matched")

        variant_id = _stable_id("routevar", family_code, route.route_id)

        result[route.route_id] = RouteDerivedMeta(
            route_family_id=family_id,
            route_family_code=family_code,
            route_family_label=family_code,
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


# ── Public API ─────────────────────────────────────────────────

def derive_route_family_metadata(
    all_routes: List[Dict[str, Any]],
) -> Dict[str, RouteDerivedMeta]:
    """
    Given a list of raw route dicts, compute family/variant metadata
    for every route. Returns {route_id: RouteDerivedMeta}.
    """
    raw_routes = [RawRoute.from_dict(d) for d in all_routes]

    groups: Dict[str, List[RawRoute]] = {}
    for route in raw_routes:
        family_code = extract_route_family_code(route)
        groups.setdefault(family_code, []).append(route)

    derived: Dict[str, RouteDerivedMeta] = {}
    for _family_code, routes in groups.items():
        derived.update(classify_family(routes))

    return derived


def enrich_routes_with_family(
    routes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Enrich a list of route dicts with family/variant metadata.
    Returns the same list with family fields injected (non-destructive).
    """
    metadata = derive_route_family_metadata(routes)
    for route in routes:
        route_id = route.get("id") or route.get("route_id", "")
        meta = metadata.get(route_id)
        if meta:
            route.update(meta.to_dict())
        manual_variant = route.get("routeVariantTypeManual")
        if manual_variant:
            route["routeVariantType"] = manual_variant
            route["canonicalDirection"] = (
                route.get("canonicalDirectionManual")
                or _direction_for_variant_type(
                    manual_variant,
                    route.get("canonicalDirection") or "unknown",
                )
            )
            route["classificationConfidence"] = 1.0
            route["classificationReasons"] = [
                f"manual override: {manual_variant}",
            ]
            route["classificationSource"] = "manual_override"
        else:
            route["classificationSource"] = "derived"
    return routes


def build_route_family_summary(
    routes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build family-level summary DTOs from route dicts that already
    have family metadata enriched.
    """
    families: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        fid = route.get("routeFamilyId")
        if fid:
            families.setdefault(fid, []).append(route)

    summaries: List[Dict[str, Any]] = []
    for family_id, members in families.items():
        first = members[0]

        variant_types = {m.get("routeVariantType") for m in members}
        main_count = sum(
            1
            for m in members
            if (m.get("routeVariantType") or "").startswith("main")
        )

        # Aggregate link status
        agg = _aggregate_link_status(members)

        # Collect start/end candidates
        starts = sorted({m.get("startStop", "") for m in members if m.get("startStop")})
        ends = sorted({m.get("endStop", "") for m in members if m.get("endStop")})

        summaries.append({
            "routeFamilyId": family_id,
            "routeFamilyCode": first.get("routeFamilyCode", ""),
            "routeFamilyLabel": first.get("routeFamilyLabel", ""),
            "routeSeriesCode": first.get("routeSeriesCode", ""),
            "routeSeriesPrefix": first.get("routeSeriesPrefix", ""),
            "routeSeriesNumber": first.get("routeSeriesNumber"),
            "primaryColor": first.get("color"),
            "variantCount": len(members),
            "mainVariantCount": main_count,
            "hasShortTurn": "short_turn" in variant_types,
            "hasBranch": "branch" in variant_types,
            "hasDepotVariant": any(
                v in variant_types for v in ("depot_out", "depot_in")
            ),
            "startStopCandidates": starts,
            "endStopCandidates": ends,
            **agg,
        })

    return sorted(
        summaries,
        key=lambda s: route_code_sort_key(str(s.get("routeFamilyCode") or "")),
    )


def build_route_family_detail(
    family_id: str,
    routes: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Build a detailed family DTO, including all variant routes.
    `routes` should already be family-enriched.
    """
    members = [r for r in routes if r.get("routeFamilyId") == family_id]
    if not members:
        return None

    first = members[0]
    summary = build_route_family_summary(members)
    summary_item = summary[0] if summary else {}

    # Detect canonical main pair
    main_out = next(
        (m for m in members if m.get("routeVariantType") == "main_outbound"), None
    )
    main_in = next(
        (m for m in members if m.get("routeVariantType") == "main_inbound"), None
    )

    canonical_pair = None
    if main_out or main_in:
        canonical_pair = {
            "outboundRouteId": main_out.get("id") if main_out else None,
            "inboundRouteId": main_in.get("id") if main_in else None,
            "outboundStartStop": main_out.get("startStop") if main_out else None,
            "outboundEndStop": main_out.get("endStop") if main_out else None,
            "inboundStartStop": main_in.get("startStop") if main_in else None,
            "inboundEndStop": main_in.get("endStop") if main_in else None,
        }

    # Sort variants by familySortOrder
    sorted_variants = sorted(members, key=lambda m: m.get("familySortOrder", 999))

    return {
        "routeFamilyId": family_id,
        "routeFamilyCode": first.get("routeFamilyCode", ""),
        "routeFamilyLabel": first.get("routeFamilyLabel", ""),
        "routeSeriesCode": first.get("routeSeriesCode", ""),
        "routeSeriesPrefix": first.get("routeSeriesPrefix", ""),
        "routeSeriesNumber": first.get("routeSeriesNumber"),
        "summary": summary_item,
        "variants": sorted_variants,
        "canonicalMainPair": canonical_pair,
        "timetableDiagnostics": _timetable_diagnostics(members),
    }


# ── Aggregation helpers ────────────────────────────────────────

_STATE_RANK = {"linked": 0, "partial": 1, "unlinked": 2, "error": 3}


def _aggregate_link_status(route_variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate linkStatus across raw variants."""
    stops_resolved = 0
    stops_missing = 0
    trips_linked = 0
    stop_tt_linked = 0
    warnings: List[str] = []
    agg_state = "linked"

    for r in route_variants:
        ls = r.get("linkStatus") or {}
        stops_resolved += ls.get("stopsResolved", 0)
        stops_missing += ls.get("stopsMissing", 0)
        trips_linked += ls.get("tripsLinked", 0)
        stop_tt_linked += ls.get("stopTimetableEntriesLinked", 0)
        warnings.extend(ls.get("warnings") or [])

        state = r.get("linkState") or "unlinked"
        if _STATE_RANK.get(state, 2) > _STATE_RANK.get(agg_state, 0):
            agg_state = state

    return {
        "aggregatedLinkState": agg_state,
        "aggregatedLinkStatus": {
            "stopsResolved": stops_resolved,
            "stopsMissing": stops_missing,
            "tripsLinked": trips_linked,
            "stopTimetableEntriesLinked": stop_tt_linked,
            "warnings": sorted(set(warnings)),
        },
    }


def _timetable_diagnostics(route_variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build family-level timetable diagnostics."""
    with_trips = sum(1 for r in route_variants if int(r.get("tripCount") or 0) > 0)
    total_trips = sum(int(r.get("tripCount") or 0) for r in route_variants)

    ls_total = 0
    stt_total = 0
    for r in route_variants:
        ls = r.get("linkStatus") or {}
        ls_total += ls.get("tripsLinked", 0)
        stt_total += ls.get("stopTimetableEntriesLinked", 0)

    warnings = []
    if total_trips == 0:
        warnings.append("no timetable rows found for any variant in this family")
    if ls_total == 0 and total_trips > 0:
        warnings.append("trips exist but none are linked")

    return {
        "rawRouteCount": len(route_variants),
        "rawRoutesWithTrips": with_trips,
        "rawRoutesWithStopTimetables": sum(
            1 for r in route_variants
            if (r.get("linkStatus") or {}).get("stopTimetableEntriesLinked", 0) > 0
        ),
        "totalTripsLinked": ls_total,
        "totalStopTimetableEntriesLinked": stt_total,
        "warnings": warnings,
    }
