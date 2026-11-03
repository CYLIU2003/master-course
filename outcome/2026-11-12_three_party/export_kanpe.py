"""Write the speaker notes of three_party_20261112.pptx to a printable Markdown script (カンペ)."""
import html
import re
import zipfile
from pathlib import Path

here = Path(__file__).parent
z = zipfile.ZipFile(here / "three_party_20261112.pptx")
slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n).group(1)))
lines = ["# 三者ミーティング（2026年11月12日）カンペ", "", "スライドのノートと同じ内容。発表時間の目安は1ページ約40〜60秒。", ""]
for i, name in enumerate(slides, 1):
    xml = z.read(name).decode("utf-8")
    m = re.search(r'type="title".*?</p:sp>', xml, re.S)
    title = "".join(re.findall(r"<a:t>(.*?)</a:t>", m.group(0))) if m else "タイトル"
    rels = z.read(name.replace("slides/", "slides/_rels/") + ".rels").decode("utf-8")
    nm = re.search(r'Target="\.\./notesSlides/(notesSlide\d+\.xml)"', rels)
    note = ""
    if nm:
        nx = z.read("ppt/notesSlides/" + nm.group(1)).decode("utf-8")
        body = re.search(r'type="body".*?</p:sp>', nx, re.S)
        note = "".join(re.findall(r"<a:t>(.*?)</a:t>", body.group(0))) if body else ""
    lines += [f"## {i}. {html.unescape(title)}", "", html.unescape(note) or "（なし）", ""]
(here / "カンペ_20261112.md").write_text("\n".join(lines), encoding="utf-8")
print("wrote", len(slides))
