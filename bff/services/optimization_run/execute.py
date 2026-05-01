from __future__ import annotations

import warnings

from src.optimization import OptimizationMode


def parse_optimization_mode(mode: str) -> OptimizationMode:
    normalized = (mode or "").strip().lower()
    if normalized in {"milp", "mode_milp_only", "exact"}:
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
    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
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
        "thesis_mode",
        "mode_a_journey_charge",
        "mode_a",
        "mode_b_optimistic",
        "mode_b",
        "mode_alns_milp",
    }

    if resolved_mode.lower() in legacy_modes:
        legacy_to_canonical = {
            "mode_alns_milp": "mode_hybrid",
            "thesis_mode": None,
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
            "Supported modes: mode_milp_only, mode_alns_only, mode_ga_only, mode_abc_only, mode_hybrid. "
            "These use the canonical optimization engine (src/optimization/)."
        )

    return resolved_mode
