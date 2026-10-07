"""Align cached chart literals with unchanged embedded workbook cells."""
import io, json, posixpath, re
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

folder=Path(__file__).parent
source=folder/'native_merge_candidate_v2.pptx'
target=folder/'aligned_candidate.pptx'
ns={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships','s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
updates=[]
with ZipFile(source) as src,ZipFile(target,'w',ZIP_DEFLATED) as dst:
    for item in src.infolist():
        raw=src.read(item.filename)
        if re.fullmatch(r'ppt/charts/chart\d+\.xml',item.filename):
            e=E.fromstring(raw)
            rels=E.fromstring(src.read(posixpath.join(posixpath.dirname(item.filename),'_rels',posixpath.basename(item.filename)+'.rels')))
            ext=e.find('c:externalData',ns)
            if ext is not None:
                rid=ext.get('{'+ns['r']+'}id')
                target_part=next(r.get('Target') for r in rels if r.get('Id')==rid)
                workbook=posixpath.normpath(posixpath.join(posixpath.dirname(item.filename),target_part)).lstrip('/')
                with ZipFile(io.BytesIO(src.read(workbook))) as w:
                    assert len([n for n in w.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n)])==1
                    sheet=E.fromstring(w.read('xl/worksheets/sheet1.xml'))
                cells={c.get('r'):c.find('s:v',ns).text for c in sheet.findall('.//s:c',ns) if c.find('s:v',ns) is not None}
                points=0;maximum=Decimal(0)
                for ref in e.findall('.//c:numRef',ns):
                    match=re.search(r'\$([A-Z]+)\$(\d+):\$([A-Z]+)\$(\d+)',ref.find('c:f',ns).text)
                    if not match:raise ValueError('Unsupported reference; do not invent workbook data')
                    col,start,last_col,end=match.groups();assert col==last_col
                    for pt in ref.findall('c:numCache/c:pt',ns):
                        value=pt.find('c:v',ns);exact=cells[col+str(int(start)+int(pt.get('idx')))]
                        delta=abs(Decimal(value.text)-Decimal(exact))
                        if delta:
                            assert delta<=Decimal('0.000000000001'),(item.filename,delta)
                            maximum=max(maximum,delta);points+=1;value.text=exact
                # PowerPoint insertion defaults newly authored scatter charts to smoothing.
                # Keep raw points and explicitly use linear lines, as in the source deck.
                style_changed=False
                if int(re.search(r'chart(\d+)',item.filename).group(1)) > 44:
                    for smooth in e.findall('.//c:smooth',ns):
                        smooth.set('val','0');style_changed=True
                    for style in e.findall('.//c:scatterStyle',ns):
                        style.set('val','line');style_changed=True
                if points or style_changed:
                    raw=E.tostring(e,encoding='UTF-8',xml_declaration=True,standalone=True)
                    updates.append({'chart':item.filename,'points_aligned':points,'max_absolute_serialization_delta':str(maximum),'source_workbook':workbook,'workbook_modified':False,'linear_style_enforced':style_changed})
        dst.writestr(item.filename,raw)
(folder/'chart_cache_alignment.json').write_text(json.dumps(updates,indent=2),encoding='utf-8')
print(json.dumps({'charts_aligned':len(updates),'points':sum(u['points_aligned'] for u in updates),'max_delta':str(max(Decimal(u['max_absolute_serialization_delta']) for u in updates))}))


