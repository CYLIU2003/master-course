from __future__ import annotations

import pytest

from tests._reporting_finalizer_utils import RUN_EXPECTATIONS, finalized_run, read_rows


ALLOWED_NON_OK = {"vehicle-soc-violation", "solver-status"}


@pytest.mark.parametrize("run_id", sorted(RUN_EXPECTATIONS))
def test_reporting_finalizer_reconciliation(tmp_path, run_id):
    run_dir = finalized_run(tmp_path, run_id)
    rows = read_rows(run_dir / "strict_reconciliation.csv")
    statuses = {row["domain"]: row["status"] for row in rows}

    unexpected = {
        domain: status
        for domain, status in statuses.items()
        if status != "OK"
        and not (
            domain in ALLOWED_NON_OK
            and status in {"OUT_OF_SCOPE_REMAINS", "NG"}
        )
    }
    assert unexpected == {}

    for domain in ["energy", "identity", "vehicle-charge-allocation", "fuel", "co2", "cost", "bess-metadata"]:
        assert statuses[domain] == "OK"
    assert statuses["vehicle-soc-violation"] == "OUT_OF_SCOPE_REMAINS"
    assert statuses["solver-status"] == "NG"
