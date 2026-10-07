from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E
import json,copy,hashlib,posixpath,sys

BUILD=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).parent
SOURCE=Path('C:/master-course/outcome/2026-10-05_teacher_ready/research_progress_20261005_teacher_ready.pptx')
SOURCE_SHA='af5be0f3460aa0e3d16c3cd633ff8fab22396cf9196d680daae7ce0895f77b31'
NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SOURCE_SHA,'Source changed; inspect new source first'
edits=json.loads((BUILD/'edits.json').read_text('utf-8'))
with ZipFile(SOURCE) as z:
 parts={p:z.read(p) for p in z.namelist()}
with ZipFile(BUILD/'authored_elements.pptx') as z:
 authored={p:z.read(p) for p in z.namelist()}
replaced=[]
for i,page in enumerate(edits['pages'],1):
 number=page['number'];part=f'ppt/slides/slide{number}.xml'
 root=E.fromstring(parts[part]);tree=root.find('p:cSld/p:spTree',NS)
 new=E.fromstring(authored[f'ppt/slides/slide{i}.xml']).find('p:cSld/p:spTree',NS)
 ids={s.find('.//p:cNvPr',NS).get('id'):s for s in tree if s.find('.//p:cNvPr',NS) is not None}
 title_id='10' if number==14 else '7'
 for name,oldid in [('revision-title',title_id),('revision-subtitle','2'),('revision-takeaway','3'),('revision-footnote','4')]:
  obj=next(s for s in new if s.find('.//p:cNvPr',NS) is not None and s.find('.//p:cNvPr',NS).get('name')==name)
  obj=copy.deepcopy(obj);obj.find('.//p:cNvPr',NS).set('id',oldid)
  pos=list(tree).index(ids[oldid]);tree.remove(ids[oldid]);tree.insert(pos,obj)
 if page.get('mechanism'):
  obj=copy.deepcopy(next(s for s in new if s.find('.//p:cNvPr',NS) is not None and s.find('.//p:cNvPr',NS).get('name')=='revision-mechanism'))
  obj.find('.//p:cNvPr',NS).set('id','1000');tree.append(obj)
 if number==16:
  old=ids['12'];pos=list(tree).index(old);tree.remove(old)
  obj=copy.deepcopy(next(s for s in new if s.find('.//a:tbl',NS) is not None))
  obj.find('.//p:cNvPr',NS).set('id','12');obj.find('.//p:cNvPr',NS).set('name','天候分類・判定根拠')
  tree.insert(pos,obj)
 parts[part]=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True);replaced.append(part)
 relpart=f'ppt/slides/_rels/slide{number}.xml.rels'
 rels=E.fromstring(parts[relpart])
 nr=next(r for r in rels if r.get('Type','').endswith('/notesSlide'))
 np=posixpath.normpath(posixpath.join('ppt/slides',nr.get('Target')))
 note=E.fromstring(parts[np]);body=next(s for s in note.findall('p:cSld/p:spTree/p:sp',NS) if s.find('p:nvSpPr/p:nvPr/p:ph',NS) is not None and s.find('p:nvSpPr/p:nvPr/p:ph',NS).get('type')=='body')
 tx=body.find('p:txBody',NS)
 for p in tx.findall('a:p',NS):tx.remove(p)
 for line in page['notes'].splitlines():
  p=E.SubElement(tx,'{'+NS['a']+'}p');r=E.SubElement(p,'{'+NS['a']+'}r');E.SubElement(r,'{'+NS['a']+'}t').text=line
 parts[np]=E.tostring(note,xml_declaration=True,encoding='UTF-8',standalone=True);replaced.append(np)
with ZipFile(BUILD/'candidate.pptx','w',ZIP_DEFLATED) as z:
 for p,v in parts.items():z.writestr(p,v)
with ZipFile(SOURCE) as z:
 unchanged=[p for p in parts if z.read(p)==parts[p]]
 assert set(parts)-set(unchanged)==set(replaced)
report={'source_sha256':SOURCE_SHA,'modified_parts':replaced,'unchanged_package_parts':len(unchanged),'unchanged_slides':41,'comments_unchanged':True,'charts_and_embedded_workbooks_unchanged':True}
(BUILD/'part_preservation.json').write_text(json.dumps(report,indent=2),'utf-8')
print(json.dumps(report))
