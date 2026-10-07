"""Verify the final weather appendix, original slide renders, and evidence retention."""
from __future__ import annotations
import csv
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from lxml import etree as E
from pypdf import PdfReader

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(build: Path, output: Path):
    folder = Path(__file__).parent
    pptx = output / 'research_progress_20261006_daily_weather.pptx'
    pdf = output / 'research_progress_20261006_daily_weather.pdf'
    rows = list(csv.DictReader((output / 'daily_weather_84days.csv').open(encoding='utf-8-sig')))
    with zipfile.ZipFile(folder / 'source_base.pptx') as source, zipfile.ZipFile(pptx) as final:
        assert len(rows) == len({r['date'] for r in rows}) == 84
        assert len({r['representative_week_start'] for r in rows}) == 12
        original_render_changes = [i for i in range(1,45) if digest(build / 'render_source' / f'slide-{i}.png') != digest(build / 'render' / f'slide-{i}.png')]
        assert not original_render_changes, original_render_changes
        for i in range(1,45):
            part = f'ppt/slides/slide{i}.xml'
            original, appended = E.fromstring(source.read(part)), E.fromstring(final.read(part))
            assert original.xpath('//a:t/text()', namespaces=NS) == appended.xpath('//a:t/text()', namespaces=NS)
            assert original.get('show','1') == appended.get('show','1')
        books = [n for n in source.namelist() if n.endswith('.xlsx')]
        comments = [n for n in source.namelist() if n.startswith('ppt/comments/') and n.endswith('.xml')]
        assert all(source.read(n) == final.read(n) for n in books)
        assert all(source.read(n) == final.read(n) for n in comments)
        assert len(books) == 50 and len(comments) == 7
        for month in range(1,13):
            slide = E.fromstring(final.read(f'ppt/slides/slide{44+month}.xml'))
            assert slide.get('show','1') != '0'
            tables = slide.findall('.//a:tbl', NS)
            assert len(tables) == 1
            native_rows = tables[0].findall('a:tr', NS)
            assert len(native_rows) == 8
            monthly = [r for r in rows if int(r['representative_week_start'][5:7]) == month]
            for row, native in zip(monthly, native_rows[1:], strict=True):
                texts = [''.join(cell.xpath('.//a:t/text()', namespaces=NS)) for cell in native.findall('a:tc', NS)]
                day = row['date']; expected = f'{int(day[5:7])}/{int(day[8:10])}（{row["weekday_ja"]}）'
                assert texts == [expected, row['weather_ja'], f'{float(row["daily_irradiation_kwh_m2"]):.3f}',
                                 f'{float(row["daylight_clearsky_ratio"]):.3f}',
                                 f'{float(row["daylight_precipitation_mm"]):.3f}', f'{float(row["precipitation_mm"]):.3f}']
    document = PdfReader(str(pdf)).pages
    assert len(document) == 30
    for month in range(1,13):
        page = document[17+month]
        assert f'{month}月代表週' in ''.join(page.extract_text().split())
    assert '未判定' in ''.join(document[20].extract_text().split())
    result = {'total_pptx_slides': 56, 'visible_pptx_slides_and_pdf_pages': 30,
              'original_hidden_appendices_preserved': 26, 'appendix_slide_numbers': [45,56],
              'pdf_weather_page_numbers': [19,30], 'daily_rows': 84, 'editable_weather_tables': 12,
              'original_44_renders_identical': True, 'original_44_slide_texts_and_visibility_preserved': True,
              'original_embedded_excel_files_preserved_byte_for_byte': len(books),
              'original_teacher_comment_xml_files_preserved_byte_for_byte': len(comments),
              'pptx_sha256': digest(pptx), 'pdf_sha256': digest(pdf),
              'csv_sha256': digest(output / 'daily_weather_84days.csv'),
              'human_teacher_approval': 'NOT_ASSESSED'}
    (build / 'delivery_verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
