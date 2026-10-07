"""Preserve workbook originals and remove Office serialization discrepancies."""
import io
import json
import posixpath
import re
import sys
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

folder = Path(sys.argv[1]).resolve()
ns = {'c':'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      's':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
updates = []
with ZipFile(folder/'native_merge_candidate.pptx') as src, ZipFile(folder/'aligned_candidate.pptx','w',ZIP_DEFLATED) as dst:
    for item in src.infolist():
        raw = src.read(item.filename)
        if re.fullmatch(r'ppt/charts/chart\d+\.xml',item.filename):
            root = E.fromstring(raw)
            rels = E.fromstring(src.read(posixpath.join(posixpath.dirname(item.filename),'_rels',posixpath.basename(item.filename)+'.rels')))
            ext = root.find('c:externalData',ns)
            points = 0
            if ext is not None:
                rid = ext.get('{'+ns['r']+'}id')
                target = next(r.get('Target') for r in rels if r.get('Id')==rid)
                workbook = posixpath.normpath(posixpath.join(posixpath.dirname(item.filename),target)).lstrip('/')
                with ZipFile(io.BytesIO(src.read(workbook))) as w:
                    sheet = E.fromstring(w.read('xl/worksheets/sheet1.xml'))
                cells = {c.get('r'):c.find('s:v',ns).text for c in sheet.findall('.//s:c',ns) if c.find('s:v',ns) is not None}
                for ref in root.findall('.//c:numRef',ns):
                    match = re.search(r'\$([A-Z]+)\$(\d+):\$([A-Z]+)\$(\d+)',ref.find('c:f',ns).text)
                    if not match: raise ValueError('Unsupported workbook reference')
                    col,start,last_col,end = match.groups()
                    assert col == last_col
                    for pt in ref.findall('c:numCache/c:pt',ns):
                        value = pt.find('c:v',ns)
                        exact = cells[col+str(int(start)+int(pt.get('idx')))]
                        delta = abs(Decimal(value.text)-Decimal(exact))
                        if delta:
                            assert delta <= Decimal('0.000000000001'), (item.filename,delta)
                            value.text = exact
                            points += 1
            # Source scatter lines already use linear interpolation. Newly inserted ones must too.
            for smooth in root.findall('.//c:smooth',ns): smooth.set('val','0')
            for style in root.findall('.//c:scatterStyle',ns): style.set('val','line')
            raw = E.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
            updates.append({'chart':item.filename,'serialization_points_aligned':points,'workbook_modified':False})
        dst.writestr(item.filename,raw)
(folder/'chart_cache_alignment.json').write_text(json.dumps(updates,indent=2),encoding='utf-8')
print(json.dumps({'charts':len(updates),'points_aligned':sum(r['serialization_points_aligned'] for r in updates)}))
