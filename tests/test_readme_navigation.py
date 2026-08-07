"""Regression checks for the repository's GitHub-facing entry document."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPOSITORY_ROOT / "README.md"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _local_markdown_targets(markdown: str) -> list[tuple[Path, str, str]]:
    """Return local link targets as path, original target, and optional anchor."""
    targets: list[tuple[Path, str, str]] = []
    for match in MARKDOWN_LINK.finditer(markdown):
        target = match.group(1).strip().strip("<>")
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        document, _, anchor = unquote(target).partition("#")
        targets.append((README_PATH if not document else REPOSITORY_ROOT / document, target, anchor))
    return targets


def _github_heading_anchors(markdown: str) -> set[str]:
    """Build GitHub-compatible anchors for this repository's plain headings."""
    seen: Counter[str] = Counter()
    anchors: set[str] = set()
    for line in markdown.splitlines():
        match = MARKDOWN_HEADING.match(line)
        if not match:
            continue
        title = match.group(1).strip().casefold()
        title = re.sub(r"\s+#+$", "", title)
        title = re.sub(r"[^\w\s-]", "", title)
        base = re.sub(r"[\s-]+", "-", title).strip("-")
        suffix = "" if seen[base] == 0 else f"-{seen[base]}"
        anchors.add(f"{base}{suffix}")
        seen[base] += 1
    return anchors


def test_readme_keeps_the_verified_start_and_status_paths() -> None:
    """New users must find the real launcher and current evidence gate first."""
    markdown = README_PATH.read_text(encoding="utf-8")

    assert "python run_app.py" in markdown
    assert "Quick Setup 保存" in markdown
    assert "高速実行" in markdown
    assert "CURRENT_RESEARCH_RELEASE_BLOCKERS.md" in markdown
    assert "FORMAL_RUNBOOK_CURRENT.md" in markdown
    assert "`output/`" in markdown


def test_readme_local_links_resolve() -> None:
    """Keep the concise README navigable when detailed docs move elsewhere."""
    markdown = README_PATH.read_text(encoding="utf-8")
    missing = [
        target
        for path, target, _ in _local_markdown_targets(markdown)
        if not path.is_file()
    ]

    assert not missing, f"README has broken local links: {missing}"


def test_readme_local_anchors_resolve() -> None:
    """Detect renamed Markdown headings behind README navigation links."""
    markdown = README_PATH.read_text(encoding="utf-8")
    missing = []
    for path, target, anchor in _local_markdown_targets(markdown):
        if anchor and anchor not in _github_heading_anchors(path.read_text(encoding="utf-8")):
            missing.append(target)

    assert not missing, f"README has broken local anchors: {missing}"
