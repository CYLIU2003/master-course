"""Regenerate the thesis weather package and verify exact committed bytes."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import tempfile

try:
    from scripts import build_thesis_weather_result_package as builder
except ModuleNotFoundError:  # Direct execution via ``python scripts/...``.
    import build_thesis_weather_result_package as builder


def _inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def verify_exact_package(
    evidence_dir: Path,
    committed_dir: Path,
    parameter_evidence_dir: Path | None = None,
) -> None:
    """Fail unless regeneration produces the exact committed file inventory."""

    committed = committed_dir.resolve()
    builder._validate_package_inventory(committed)
    expected = _inventory(committed)
    with tempfile.TemporaryDirectory(prefix="thesis-weather-package-") as temp:
        regenerated = Path(temp) / "weather_results_bb0c005"
        builder.build_package(
            evidence_dir.resolve(),
            regenerated,
            parameter_evidence_dir.resolve() if parameter_evidence_dir else None,
        )
        actual = _inventory(regenerated)
    if actual != expected:
        unexpected = sorted(set(actual) - set(expected))
        missing = sorted(set(expected) - set(actual))
        changed = sorted(
            name for name in set(actual) & set(expected) if actual[name] != expected[name]
        )
        raise builder.EvidenceValidationError(
            "Committed thesis package is not exactly reproducible: "
            f"unexpected={unexpected}, missing={missing}, changed={changed}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--parameter-evidence-dir", type=Path)
    parser.add_argument("--committed-dir", type=Path, required=True)
    args = parser.parse_args()
    verify_exact_package(
        args.evidence_dir,
        args.committed_dir,
        args.parameter_evidence_dir,
    )
    print("PASS_EXACT_THESIS_WEATHER_RESULT_PACKAGE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
