"""Check the delivered files and relative references without AI or a solver."""
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

DEST = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((DEST / "bundle_manifest.json").read_text("utf-8"))
    for relative, expected in manifest.items():
        path = (DEST / relative).resolve()
        if not path.is_relative_to(DEST.resolve()) or sha256(path) != expected:
            raise ValueError(f"Bundle content changed: {relative}")
    links = []
    for file in [DEST / name for name in ["README.md", "teacher_response.md", "speaker_notes.md", "claude_review.md", "RESEARCH_EXPLANATION.md"]]:
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", file.read_text("utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            path = (file.parent / target.split("#", 1)[0]).resolve()
            if not path.exists():
                raise FileNotFoundError(f"Broken local reference: {file.name}: {target}")
            links.append({"document": file.name, "target": target})
    response = (DEST / "teacher_response.md").read_text("utf-8")
    if len(re.findall(r"^## \d+\. 元ページ", response, re.MULTILINE)) != 11:
        raise ValueError("The response mapping must include all 11 teacher comments")
    pdf = DEST / "research_progress_20261005_teacher_ready.pdf"
    pages = PdfReader(pdf).pages
    if len(pages) != 18:
        raise ValueError("Expected 18 visible main slides in the PDF")
    # Office can encode Japanese and Latin glyph runs as separate PDF lines.
    text = re.sub(r"\s+", "", "\n".join(page.extract_text() for page in pages))
    for required in ["連続7", "1,704", "57.6", "BESS", "2024"]:
        if required not in text:
            raise ValueError(f"Missing expected native PDF text: {required}")
    report = {"status": "PASS", "bundle_files": len(manifest), "relative_links": links,
              "teacher_comment_answers": 11, "pdf_pages": len(pages),
              "claim_scope": "Packaged file integrity, document references and native PDF text only; visual and research checks are in verification.json"}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
