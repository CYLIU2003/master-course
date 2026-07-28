from __future__ import annotations

from bff.services.optimization_run.cost_breakdown import (
    CANONICAL_LEDGER_COMPONENT_SOURCES,
    canonical_cost_ledger_from_breakdown,
)


def _ledger(breakdown: dict) -> dict:
    return canonical_cost_ledger_from_breakdown(
        breakdown=breakdown,
        scenario_id="scenario-a",
        source="rolling_executed_day",
        objective_mode="total_cost",
        objective_value=0.0,
        objective_is_actual_cost=True,
        solver_objective_matches_accounting_total=False,
        carbon_price_jpy_per_kg=0.0,
    )


def test_every_enabled_canonical_component_has_an_explicit_source() -> None:
    breakdown = {
        source_key: float(index)
        for index, (source_key, _flag_key) in enumerate(
            CANONICAL_LEDGER_COMPONENT_SOURCES.values(),
            start=1,
        )
    }
    breakdown["cost_component_flags"] = {
        flag_key: True
        for _source_key, flag_key in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.values()
        )
    }
    breakdown["total_cost"] = sum(
        breakdown[source_key]
        for source_key, _flag_key in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.values()
        )
    )

    ledger = _ledger(breakdown)

    assert ledger["component_schema_satisfied"] is True
    assert ledger["missing_enabled_component_sources"] == []
    assert set(ledger["components"]) == set(
        CANONICAL_LEDGER_COMPONENT_SOURCES
    )
    assert all(
        status["enabled"]
        and status["status"] == "ENABLED"
        and status["source_present"]
        for status in ledger["component_status"].values()
    )


def test_missing_enabled_component_source_is_not_treated_as_zero_evidence() -> None:
    ledger = _ledger(
        {
            "total_cost": 0.0,
            "cost_component_flags": {
                flag_key: True
                for _source_key, flag_key in (
                    CANONICAL_LEDGER_COMPONENT_SOURCES.values()
                )
            },
        }
    )

    assert ledger["component_schema_satisfied"] is False
    assert set(ledger["missing_enabled_component_sources"]) == set(
        CANONICAL_LEDGER_COMPONENT_SOURCES
    )


def test_disabled_component_is_explicitly_skipped_and_zero() -> None:
    breakdown = {
        source_key: 0.0
        for source_key, _flag_key in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.values()
        )
    }
    breakdown["cost_component_flags"] = {
        flag_key: flag_key != "fuel_cost"
        for _source_key, flag_key in (
            CANONICAL_LEDGER_COMPONENT_SOURCES.values()
        )
    }
    breakdown["total_cost"] = 0.0

    ledger = _ledger(breakdown)

    fuel_status = ledger["component_status"]["fuel_cost_jpy"]
    assert fuel_status == {
        "enabled": False,
        "status": "SKIPPED",
        "source_key": "fuel_cost",
        "source_present": True,
        "value_jpy": 0.0,
    }
