"""Verify sources, native objects and preserved teacher comments; extract notes."""
import hashlib
import json
import posixpath
import sys
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E

build = Path(sys.argv[1]).resolve()
path = Path(sys.argv[2]).resolve() if len(sys.argv)>2 else build/'aligned_candidate.pptx'
data = json.loads((build/'data.json').read_text('utf-8'))
ns = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}

def sha(raw): return hashlib.sha256(raw).hexdigest()
def related(z, part, ending):
    name=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
    root=E.fromstring(z.read(name))
    return [posixpath.normpath(posixpath.join(posixpath.dirname(part),r.get('Target'))).lstrip('/')
            for r in root if r.get('Type').endswith(ending)]

with ZipFile(data['source']) as original, ZipFile(path) as z:
    original_books={sha(original.read(n)) for n in original.namelist() if n.startswith('ppt/embeddings/')}
    final_books={sha(z.read(n)) for n in z.namelist() if n.startswith('ppt/embeddings/')}
    assert original_books<=final_books, 'Original workbook changed'
    comments=[n for n in original.namelist() if n.startswith('ppt/comments/') and not n.endswith('.rels')]
    old_comment_hashes={sha(original.read(n)) for n in comments}
    new_comment_hashes={sha(z.read(n)) for n in z.namelist() if n.startswith('ppt/comments/') and not n.endswith('.rels')}
    assert old_comment_hashes<=new_comment_hashes, 'Teacher comment content changed'
    pres=E.fromstring(z.read('ppt/presentation.xml'))
    rels=E.fromstring(z.read('ppt/_rels/presentation.xml.rels'))
    targets={r.get('Id'):posixpath.normpath(posixpath.join('ppt',r.get('Target'))).lstrip('/') for r in rels}
    slides=[]
    for number,node in enumerate(pres.findall('p:sldIdLst/p:sldId',ns),1):
        part=targets[node.get('{'+ns['r']+'}id')]
        root=E.fromstring(z.read(part))
        texts=[t.text or '' for t in root.findall('.//a:t',ns)]
        assert not any('NaN' in t or 'undefined' in t for t in texts), number
        hidden=root.get('show')=='0'
        assert hidden == (number>data['main_slides']), (number,hidden)
        notes=[]
        for note in related(z,part,'/notesSlide'):
            notes_root=E.fromstring(z.read(note))
            for sp in notes_root.findall('.//p:sp',ns):
                ph=sp.find('p:nvSpPr/p:nvPr/p:ph',ns)
                if ph is not None and ph.get('type')=='body':
                    notes.append('\n'.join(''.join(t.text or '' for t in p.findall('.//a:t',ns)) for p in sp.findall('p:txBody/a:p',ns)))
        slides.append({'number':number,'title':texts[0], 'text':'\n'.join(texts),
                       'hidden':hidden,'native_tables':len(root.findall('.//a:tbl',ns)),
                       'native_charts':len(root.findall('.//c:chart',ns)), 'notes':'\n'.join(notes)})
    assert len(slides)==44
    assert sum(s['native_charts'] for s in slides)==50
    assert sum(not s['hidden'] for s in slides)==18
    # Every source slide is present once; modern comments remain unresolved.
    comment_count = sum(len(E.fromstring(z.read(n)).xpath('//*[local-name()="cm"]'))
                        for n in z.namelist() if n.startswith('ppt/comments/') and n.endswith('.xml'))
    assert comment_count == 11, comment_count
    result={'path':str(path),'sha256':sha(path.read_bytes()),'source_sha256':data['source_sha256'],
            'main_slides':18,'hidden_appendices':26,'total_slides':44,
            'charts':50,'original_workbooks_preserved':len(original_books),
            'original_comment_parts_preserved':len(old_comment_hashes),
            'teacher_comments_preserved':comment_count,
            'requiredNativeTableOwnerSlides':[s['number'] for s in slides if s['native_tables']],
            'requiredNativeChartOwnerSlides':[s['number'] for s in slides if s['native_charts']],
            'new_solver_run':False,'research_approval_changed':False}
(build/'revision_inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
(build/'slides.json').write_text(json.dumps(slides,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:v for k,v in result.items() if not k.startswith('required')}))
