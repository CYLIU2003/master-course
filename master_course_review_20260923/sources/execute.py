from __future__ import annotations

import warnings

from src.optimization import OptimizationMode
from src.optimization.common.problem import normalize_phase, VALID_PHASES


# Modes that route into the canonical MILP engine regardless of phase.
_MILP_MODE_TOKENS = {
    "milp",
    "mode_milp_only",
    "exact",
    "thesis_mode",
    "debug_mode",
    "mode_milp",
    *VALID_PHASES,
    "phase1",
    "phase2",
    "phase3",
    "phase4",
    "diagnostic_mode",
}

_PHASE_ALIAS_MAP = {
    "phase1": "phase1_charging_only",
    "phase2": "phase2_assignment_only",
    "phase3": "phase3_two_stage",
    "phase4": "phase4_integrated",
    "diagnostic_mode": "diagnostic",
}

_LEGACY_PHASE_MAP = {
    "thesis_mode": "phase3_two_stage",
    "mode_milp_only": "phase3_two_stage",
}


def parse_optimization_mode(mode: str) -> OptimizationMode:
    normalized = (mode or "").strip().lower()
    if normalized in _MILP_MODE_TOKENS:
        return OptimizationMode.MILP
    if normalized in {"alns", "mode_alns_only", "heuristic"}:
        return OptimizationMode.ALNS
    if normalized in {"ga", "mode_ga_only"}:
        return OptimizationMode.GA
    if normalized in {"abc", "mode_abc_only"}:
        return OptimizationMode.ABC
    return OptimizationMode.HYBRID


def normalize_solver_mode(mode: str) -> str:
    normalized = (mode or "").strip().lower()

    if normalized in VALID_PHASES:
        return normalized
    if normalized in _PHASE_ALIAS_MAP:
        return _PHASE_ALIAS_MAP[normalized]

    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
        "thesis": "thesis_mode",
        "debug": "debug_mode",
        "alns": "mode_alns_only",
        "heuristic": "mode_alns_only",
        "ga": "mode_ga_only",
        "genetic": "mode_ga_only",
        "abc": "mode_abc_only",
        "colony": "mode_abc_only",
        "hybrid": "mode_hybrid",
    }

    resolved_mode = alias_map.get(normalized, normalized or "mode_milp_only")

    legacy_modes = {
        "mode_a_journey_charge",
        "mode_a",
        "mode_b_optimistic",
        "mode_b",
        "mode_alns_milp",
    }

    if resolved_mode.lower() in legacy_modes:
        legacy_to_canonical = {
            "mode_alns_milp": "mode_hybrid",
            "mode_a_journey_charge": None,
            "mode_a": None,
            "mode_b_optimistic": None,
            "mode_b": None,
        }
        canonical_replacement = legacy_to_canonical.get(resolved_mode.lower())
        if canonical_replacement:
            warnings.warn(
                f"Solver mode '{mode}' is deprecated. "
                f"Auto-routing to canonical mode '{canonical_replacement}'.",
                DeprecationWarning,
                stacklevel=2,
            )
            return canonical_replacement
        raise ValueError(
            f"Solver mode '{mode}' (normalized: '{resolved_mode}') is no longer supported. "
            "Legacy thesis modes have been deprecated. "
            "Supported modes: mode_milp_only, mode_alns_only, mode_ga_only, mode_abc_only, mode_hybrid, "
            "and the explicit phase tokens phase1_charging_only, phase2_assignment_only, "
            "phase3_two_stage, phase4_integrated, diagnostic. "
            "These use the canonical optimization engine (src/optimization/)."
        )

    return resolved_mode


def phase_from_solver_mode(solver_mode: str) -> str:
    """Map a normalized BFF solver-mode token onto an OptimizationConfig.phase.

    Phase tokens (phase1_charging_only / phase2 / phase3 / phase4 / diagnostic)
    are returned verbatim. Legacy aliases thesis_mode/mode_milp_only resolve to
    phase3_two_stage. Public debug_mode intentionally remains the legacy
    integrated debug path and does not become the diagnostic phase implicitly.
    Non-MILP canonical modes return an empty phase so their historical paths are
    not accidentally marked as thesis MILP phases.
    """
    normalized = (solver_mode or "").strip().lower()
    if normalized in VALID_PHASES:
        return normalized
    if normalized in _PHASE_ALIAS_MAP:
        return _PHASE_ALIAS_MAP[normalized]
    if normalized in _LEGACY_PHASE_MAP:
        return _LEGACY_PHASE_MAP[normalized]
    return ""
