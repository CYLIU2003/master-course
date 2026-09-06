"""Guard simplified layout and links without executing application commands."""
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    "docs/README.md",
    "docs/guides/professor_review.md",
    "docs/guides/operations.md",
    "docs/frontend/DESIGN.md",
    "docs/archive/implementation_notes/param_editor_instructions.md",
    "docs/guides/accounting_output_contract.md",
    "docs/guides/agent_handoff_boundaries.md",
    "docs/guides/dispatch_contracts.md",
    "docs/guides/dispatch_preprocess_config.md",
    "docs/guides/professor_system_model_guide.md",
    "docs/guides/REMOTE_SSH.md",
    "docs/reviews/accounting_dataflow_audit.md",
    "docs/reviews/AI_AGENT_REMEDIATION_20260726.md",
    "docs/reviews/core_final_validation_report_20260317.md",
    "docs/reviews/core_parameter_preservation_manifest.md",
    "docs/reviews/fixed_scope_model_fix_report_20260406.md",
    "docs/reviews/fixed_scope_unserved_fix_report_20260405.md",
    "docs/reviews/route24_solver_report_20260405.md",
    "docs/frontend/master_course_backend_v1_2_task_breakdown.md",
    "docs/frontend/tkinter_feature_parity_backlog.md",
    "docs/reproduction/reproduction_spec.md"
]


def test_relocated_document_links_resolve():
    missing = []
    for name in DOCUMENTS:
        document = ROOT / name
        for target in re.findall(r"!?\[[^\]\n]+\]\(([^)\n]+)\)", document.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            path = unquote(target.split("#", 1)[0]).strip("<>")
            if not (document.parent / path).exists():
                missing.append((name, target))
    assert not missing, missing


def test_obsolete_intermediate_directories_do_not_return():
    for name in ("tools/catalog", "tools/validation", "scripts/fleet"):
        assert not (ROOT / name).exists(), name
    assert len(list((ROOT / "docs").glob("*.md"))) == 3
