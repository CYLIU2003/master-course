"""Refresh numeric display caches from unchanged embedded Excel cells.

PowerPoint's save expanded decimal strings in the supplied deck. Only rounding
differences of at most 1e-9 are accepted; workbook data and formulas stay intact.
"""
from __future__ import annotations
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from lxml import etree as E

SKILL_TOOLS = 'C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.1004.11800/skills/presentations/container_tools'
sys.path.insert(0, SKILL_TOOLS)
import native_quantitative_chart_gate as gate


def main(build: Path):
    path = build / 'candidate.pptx'
    changed, point_count, maximum = [], 0, Decimal(0)
    with zipfile.ZipFile(path) as package:
        parts = {n: package.read(n) for n in package.namelist()}
        for name, data in list(parts.items()):
            if not (name.startswith('ppt/charts/chart') and name.endswith('.xml')):
                continue
            tree = E.fromstring(data)
            external = tree.find('c:externalData', gate.NS)
            relation = gate._relationships(package, name)[external.get('{' + gate.NS['r'] + '}id')]
            workbook = gate._workbook_cells(package, relation['target'])
            dirty = False
            for reference in tree.findall('.//c:numRef', gate.NS):
                formula = reference.find('c:f', gate.NS).text
                cells = gate._referenced_cells(workbook, formula, label=name)
                for point in reference.findall('c:numCache/c:pt', gate.NS):
                    value = point.find('c:v', gate.NS)
                    cell = cells[int(point.get('idx'))]
                    if cell.kind != 'number':
                        raise ValueError('Numeric cache points at a nonnumeric worksheet cell')
                    difference = abs(Decimal(value.text) - cell.value)
                    if difference > Decimal('1e-9'):
                        raise ValueError(f'Non-rounding chart disagreement: {name}')
                    if difference:
                        maximum = max(maximum, difference)
                        value.text = str(cell.value)
                        point_count += 1
                        dirty = True
            if dirty:
                parts[name] = E.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)
                changed.append(name)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as package:
        for name, data in parts.items():
            package.writestr(name, data)
    (build / 'chart_cache_sync.json').write_text(json.dumps({'changed_chart_parts': changed,
        'refreshed_numeric_cache_points': point_count, 'maximum_original_difference': str(maximum),
        'embedded_workbooks_changed': False, 'source_deck_changed': False,
        'reason': 'PowerPoint decimal serialization normalized to exact unchanged worksheet cells'}, indent=2), encoding='utf-8')
    print(f'{point_count} display cache values synchronized; max difference {maximum}; embedded workbooks unchanged.')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
