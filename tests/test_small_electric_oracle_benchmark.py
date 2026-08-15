from __future__ import annotations

import csv
from hashlib import sha256
import json

import pytest

from scripts.build_small_electric_oracle_certificate import (
    write_certificate_bundle,
)
from src.gurobi_runtime import is_gurobi_available
from src.optimization.validation.small_electric_oracle_benchmark import (
    assert_certificate_integrity,
    break_even_grid_price_jpy_per_kwh,
    build_small_electric_oracle_certificate,
)


def test_bounded_certificate_records_expected_boundary_cases() -> None:
    certificate = build_small_electric_oracle_certificate(
        require_integrated_gurobi=False
    )

    assert certificate["status"] == "DIAGNOSTIC_INDEPENDENT_ONLY"
    assert certificate["research_conclusion_eligible"] is False
    assert certificate["formal_run_substitute"] is False
    assert break_even_grid_price_jpy_per_kwh() == pytest.approx(
        23.9563439761
    )
    cases = {case["case_id"]: case for case in certificate["cases"]}
    assert cases["tariff_below_break_even"]["selected_powertrain"] == "BEV"
    assert cases["tariff_above_break_even"]["selected_powertrain"] == "ICE"
    assert cases["terminal_soc_without_charger"]["status"] == "INFEASIBLE"
    assert cases["one_port_for_two_simultaneous_bevs"]["status"] == "INFEASIBLE"
    assert cases["two_ports_for_two_simultaneous_bevs"]["status"] == "OPTIMAL"
    assert certificate["scope_guards"]["positive_pv"]["passed"] is True
    assert certificate["scope_guards"]["positive_bess"]["passed"] is True
    assert_certificate_integrity(certificate)


def test_certificate_bundle_is_hashed_and_human_readable(tmp_path) -> None:
    certificate = build_small_electric_oracle_certificate(
        require_integrated_gurobi=False
    )
    manifest = write_certificate_bundle(
        tmp_path,
        certificate,
        git_provenance={
            "git_sha": "a" * 40,
            "git_dirty": False,
            "git_dirty_rows": [],
        },
    )

    assert manifest["research_conclusion_eligible"] is False
    assert len(manifest["artifacts"]) == 3
    for artifact in manifest["artifacts"]:
        path = tmp_path / artifact["path"]
        assert path.is_file()
        assert sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    with (tmp_path / "small_electric_oracle_cases.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert "Hand break-even grid tariff" in (
        tmp_path / "small_electric_oracle_certificate.md"
    ).read_text(encoding="utf-8")

    stored = json.loads(
        (tmp_path / "small_electric_oracle_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored["payload_sha256"] == manifest["payload_sha256"]
    unsigned = dict(stored)
    declared = unsigned.pop("payload_sha256")
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert sha256(encoded).hexdigest() == declared


def test_certificate_self_hash_rejects_posthoc_change() -> None:
    certificate = build_small_electric_oracle_certificate(
        require_integrated_gurobi=False
    )
    certificate["coefficients"]["bev_kwh_per_km"] = 9.9

    with pytest.raises(ValueError, match="payload_sha256 mismatch"):
        assert_certificate_integrity(certificate)


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi is required")
def test_publishable_certificate_matches_integrated_gurobi() -> None:
    certificate = build_small_electric_oracle_certificate(
        require_integrated_gurobi=True
    )

    assert certificate["checks"][
        "independent_oracle_matches_integrated_milp"
    ] is True
    assert certificate["status"] == "VERIFIED"
    assert_certificate_integrity(
        certificate, require_integrated_gurobi=True
    )
    cases = {case["case_id"]: case for case in certificate["cases"]}
    for case_id in (
        "tariff_below_break_even",
        "tariff_above_break_even",
        "two_ports_for_two_simultaneous_bevs",
    ):
        assert cases[case_id]["integrated_milp_match"] is True
        assert cases[case_id]["integrated_milp"]["solver_status"] == "optimal"
    assert cases["tariff_below_break_even"]["integrated_milp"][
        "exact_vehicle_assignment_match"
    ] is True
    assert cases["tariff_above_break_even"]["integrated_milp"][
        "exact_vehicle_assignment_match"
    ] is True
    # Equal-count exact-clone duty ordering now canonicalizes the vehicle-ID
    # permutation as well as preserving the aggregate optimal schedule.
    assert cases["two_ports_for_two_simultaneous_bevs"]["integrated_milp"][
        "exact_vehicle_assignment_match"
    ] is True
