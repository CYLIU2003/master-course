"""Fail-closed QA for the thesis authoring bundle.

The validator is deliberately read-only with respect to frozen evidence and
the optimization system. It validates the authoring tree and writes only its
own deterministic manifest under that tree.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


REQUIRED_FILES = (
    "00_README.md",
    "01_research_questions_and_contributions.md",
    "02_system_overview.md",
    "03_mathematical_formulation.md",
    "04_code_equation_traceability.csv",
    "05_assumptions_parameters_units.md",
    "06_experiment_protocol.md",
    "07_results_analysis.md",
    "08_discussion_and_limitations.md",
    "09_claim_evidence_matrix.csv",
    "09_claim_evidence_matrix.md",
    "10_literature_evidence_matrix.csv",
    "10_literature_evidence_matrix.md",
    "11_missing_evidence_register.md",
    "12_advisor_decision_memo.md",
    "13_expected_questions_and_answers.md",
    "14_thesis_writing_checklist.md",
    "chapter_drafts/chapter1_introduction.md",
    "chapter_drafts/chapter2_related_work.md",
    "chapter_drafts/chapter3_problem_and_method.md",
    "chapter_drafts/chapter4_experimental_setup.md",
    "chapter_drafts/chapter5_results.md",
    "chapter_drafts/chapter6_discussion.md",
    "chapter_drafts/chapter7_conclusion.md",
)

CHAPTER_MINIMUM_CHARACTERS = {
    "chapter_drafts/chapter1_introduction.md": 3000,
    "chapter_drafts/chapter2_related_work.md": 4000,
    "chapter_drafts/chapter3_problem_and_method.md": 4000,
    "chapter_drafts/chapter4_experimental_setup.md": 6000,
    "chapter_drafts/chapter5_results.md": 3000,
    "chapter_drafts/chapter6_discussion.md": 5000,
    "chapter_drafts/chapter7_conclusion.md": 5000,
    "chapter_drafts/chapter8_conclusion.md": 2000,
}

CLAIM_COLUMNS = {
    "claim_id",
    "chapter",
    "claim_text",
    "claim_strength",
    "primary_evidence",
    "secondary_evidence",
    "equation_or_metric",
    "supported_scope",
    "limitation",
    "status",
    "advisor_decision_needed",
}
EQUATION_COLUMNS = {
    "equation_id",
    "meaning",
    "implementation_file",
    "class_or_function",
    "implementation_variable",
    "artifact",
    "test",
    "implementation_status",
    "notes",
}
ALLOWED_CLAIM_STATUSES = {"SUPPORTED", "CONDITIONAL", "NOT_SUPPORTED", "MISSING_EVIDENCE", "ADVISOR_DECISION"}
ALLOWED_EQUATION_STATUSES = {"EXACT", "APPROXIMATED", "POST_PROCESS", "NOT_IMPLEMENTED", "UNKNOWN", "ACCOUNTING"}
UNSUPPORTED_ASSERTIONS = (
    "統合最適化を達成した",
    "大域最適解である",
    "一般的な雨天効果を証明",
    "導入経済性を証明した",
    "実運用可能性を証明した",
    "実支出である",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def validate_bundle(repo_root: Path) -> dict[str, object]:
    bundle = repo_root / "docs/thesis/authoring_v1"
    missing = [relative for relative in REQUIRED_FILES if not (bundle / relative).is_file()]
    if missing:
        raise RuntimeError(f"missing required authoring files: {missing}")
    for relative, minimum in CHAPTER_MINIMUM_CHARACTERS.items():
        actual = len((bundle / relative).read_text(encoding="utf-8"))
        if actual < minimum:
            raise RuntimeError(f"chapter draft is shorter than its target: {relative} ({actual} < {minimum})")

    claim_fields, claims = read_csv(bundle / "09_claim_evidence_matrix.csv")
    if set(claim_fields) != CLAIM_COLUMNS:
        raise RuntimeError(f"claim columns differ: {claim_fields}")
    if not claims or any(row["status"] not in ALLOWED_CLAIM_STATUSES for row in claims):
        raise RuntimeError("claim matrix is empty or has an invalid status")
    for row in claims:
        primary = repo_root / row["primary_evidence"]
        if not primary.exists():
            raise RuntimeError(f"missing primary evidence for {row['claim_id']}: {primary}")

    equation_fields, equations = read_csv(bundle / "04_code_equation_traceability.csv")
    if set(equation_fields) != EQUATION_COLUMNS:
        raise RuntimeError(f"equation columns differ: {equation_fields}")
    if not equations:
        raise RuntimeError("equation mapping is empty")
    for row in equations:
        if row["implementation_status"] not in ALLOWED_EQUATION_STATUSES:
            raise RuntimeError(f"invalid equation status: {row['equation_id']}")
        for raw_path in row["implementation_file"].split(";"):
            if raw_path and not (repo_root / raw_path).is_file():
                raise RuntimeError(f"missing implementation path for {row['equation_id']}: {raw_path}")

    qa_text = "\n".join(path.read_text(encoding="utf-8") for path in bundle.rglob("*.md"))
    question_count = len(re.findall(r"^##\s+\d+\.\s", (bundle / "13_expected_questions_and_answers.md").read_text(encoding="utf-8"), re.MULTILINE))
    if question_count < 30:
        raise RuntimeError(f"only {question_count} defense questions")
    found_assertions = [phrase for phrase in UNSUPPORTED_ASSERTIONS if phrase in qa_text]
    if found_assertions:
        raise RuntimeError(f"unsupported affirmative claims found: {found_assertions}")

    literature_fields, literature = read_csv(bundle / "10_literature_evidence_matrix.csv")
    for row in literature:
        source = repo_root / row["source_path"]
        if not source.is_file() or sha256_file(source) != row["source_sha256"]:
            raise RuntimeError(f"literature source mismatch: {row['paper_id']}")

    manifest_path = bundle / "evidence_supplements/authoring_bundle_manifest.json"
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path != manifest_path:
            files.append({
                "path": path.relative_to(repo_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return {
        "schema_version": "thesis_authoring_bundle_manifest_v1",
        "status": "THESIS_AUTHORING_BASELINE_COMPLETE_WITH_OPEN_EXPERIMENTS",
        "base_tag": "thesis-pause-20260830",
        "canonical_execution_sha": "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d",
        "question_count": question_count,
        "claim_count": len(claims),
        "equation_count": len(equations),
        "literature_count": len(literature),
        "files": files,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = validate_bundle(repo_root)
    output = repo_root / "docs/thesis/authoring_v1/evidence_supplements/authoring_bundle_manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS_THESIS_AUTHORING_BUNDLE_QA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
