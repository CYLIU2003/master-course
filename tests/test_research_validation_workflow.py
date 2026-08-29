from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "research-validation.yml"


def test_research_validation_is_manual_only() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow)
    assert not re.search(r"(?m)^  (?:push|pull_request):\s*$", workflow)
