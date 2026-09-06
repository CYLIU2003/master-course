"""Check the presentation notes against the authored script, without a solver."""

from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "outcome/2026-09-06_speaker_notes"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def test_integrated_differences_preserve_other_slides_and_notes():
    changed = {8, 9, 14, 16, 17}
    with ZipFile(PACKAGE / "august_progress_with_speaker_notes_20260906.pptx") as before, ZipFile(
        PACKAGE / "progress_differences_integrated_20260906.pptx"
    ) as after:
        assert after.testzip() is None
        for name in before.namelist():
            match = re.fullmatch(r"ppt/(?:slides/slide|notesSlides/notesSlide)(\d+)\.xml", name)
            if match and int(match[1]) in changed:
                continue
            assert before.read(name) == after.read(name), name
        for number in changed:
            slide = ET.fromstring(after.read(f"ppt/slides/slide{number}.xml"))
            assert len(slide.findall(".//a:tbl", NS)) == 1
            notes = after.read(f"ppt/notesSlides/notesSlide{number}.xml").decode("utf-8")
            assert "【話す内容】" in notes and "【出典】" in notes
        result = after.read("ppt/slides/slide14.xml").decode("utf-8")
        assert all(value in result for value in ("108便", "75.06%", "64万円", "88%"))


def test_all_speaker_notes_match_authored_sections():
    script = (PACKAGE / "speaker_notes.md").read_text(encoding="utf-8")
    sections = re.split(r"^## \d+\. [^\n]+\n", script, flags=re.MULTILINE)[1:]
    assert len(sections) == 18
    with ZipFile(PACKAGE / "august_progress_with_speaker_notes_20260906.pptx") as deck:
        assert deck.testzip() is None
        for number, section in enumerate(sections, start=1):
            root = ET.fromstring(deck.read(f"ppt/notesSlides/notesSlide{number}.xml"))
            bodies = [
                shape
                for shape in root.findall(".//p:sp", NS)
                if (placeholder := shape.find("p:nvSpPr/p:nvPr/p:ph", NS))
                is not None and placeholder.get("type") == "body"
            ]
            assert len(bodies) == 1
            embedded = "".join(bodies[0].itertext())
            assert re.sub(r"\s+", "", embedded) == re.sub(r"\s+", "", section)
            assert "【話す内容】" in embedded
            assert "【出典】" in embedded


def test_unrelated_presentation_parts_remain_byte_identical():
    source = ROOT / "outcome/修士研究_2026年8月_進捗報告_先行研究図表パラメータ追加版.pptx"
    corrected_slides = {f"ppt/slides/slide{n}.xml" for n in (7, 10, 13, 14)}
    with ZipFile(source) as before, ZipFile(
        PACKAGE / "august_progress_with_speaker_notes_20260906.pptx"
    ) as after:
        original_parts = {name for name in before.namelist() if not name.endswith("/")}
        final_parts = {name for name in after.namelist() if not name.endswith("/")}
        assert original_parts == final_parts
        for name in original_parts:
            if name in corrected_slides or re.fullmatch(
                r"ppt/notesSlides/notesSlide\d+\.xml", name
            ):
                continue
            assert before.read(name) == after.read(name), name
