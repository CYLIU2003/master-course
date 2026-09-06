// Notes-only authoring via Artifact Tool; retain the original visual package.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const root = path.resolve(import.meta.dirname, '../..');
const runtime = 'C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill = 'C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
process.env.RUNTIME_NODE_MODULES = path.join(runtime, 'node/node_modules');
const moduleAt = relative => import(pathToFileURL(path.join(runtime, 'node/node_modules', relative)).href);
const {PresentationFile, FileBlob} = await moduleAt('@oai/artifact-tool/dist/artifact_tool.mjs');
const {default: JSZip} = await moduleAt('jszip/lib/index.js');
const {finalizePresentation} = await import(pathToFileURL(path.join(skill, 'container_tools/artifact_tool_utils.mjs')).href);
const source = path.join(root, 'outcome/修士研究_2026年8月_進捗報告_先行研究図表パラメータ追加版.pptx');
const output = path.join(root, 'outcome/2026-09-06_speaker_notes');
const build = path.join(root, 'output/speaker_notes_build_20260906');
await fs.mkdir(build, {recursive:true});
const sourceBytes = await fs.readFile(source);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const markdown = await fs.readFile(path.join(output, 'speaker_notes.md'), 'utf8');
const sections = [...markdown.matchAll(/^## (\d+)\. ([^\n]+)\n([\s\S]*?)(?=^## \d+\.|$(?![\s\S]))/gm)];
if (sections.length !== 18) throw new Error(`Expected 18 note sections, got ${sections.length}`);
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await presentation.inspect({kind:'slide,layout',maxChars:100000});
await fs.writeFile(path.join(build,'source-inspect.ndjson'),snapshot.ndjson);
const slides = snapshot.ndjson.split('\n').filter(Boolean).map(line=>JSON.parse(line)).filter(row=>row.kind==='slide');
if (slides.length !== 18) throw new Error('Unexpected source slide count');
if (process.argv.includes('--inspect-only')) {
  for (const row of slides) {
    const slide = presentation.resolve(row.id);
    const png = await slide.export({format:'png',scale:1});
    await fs.writeFile(path.join(build,`source-${row.slide}.png`),new Uint8Array(await png.arrayBuffer()));
  }
  console.log('Rendered source slides');
  process.exit(0);
}
for (const row of slides) {
  const section = sections[row.slide-1];
  if (Number(section[1]) !== row.slide) throw new Error('Nonsequential notes');
  presentation.resolve(row.id).speakerNotes.textFrame.setText(section[3].trim());
}
const authored = path.join(build,'artifact-notes.pptx');
await (await PresentationFile.exportPptx(presentation)).save(authored);
const originalZip = await JSZip.loadAsync(sourceBytes);
const authoredZip = await JSZip.loadAsync(await fs.readFile(authored));
const changed = [];
// Both decks have existing note parts. Transfer only the authored body, retaining
// source relationships, note master, slide-number placeholders, and all media.
function bodyShape(xml) {
  const shapes = [...xml.matchAll(/<p:sp[ >][\s\S]*?<\/p:sp>/g)];
  const body = shapes.find(match=>/<p:ph\b[^>]*\btype="body"/.test(match[0]));
  if (!body) throw new Error('Missing notes body placeholder');
  return body[0];
}
for (let number=1;number<=18;number++) {
  const name = `ppt/notesSlides/notesSlide${number}.xml`;
  const before = await originalZip.file(name).async('string');
  const generated = await authoredZip.file(name).async('string');
  const oldShape = bodyShape(before), newShape = bodyShape(generated);
  const newBody = newShape.match(/<p:txBody>[\s\S]*?<\/p:txBody>/)?.[0];
  if (!newBody) throw new Error('Missing generated text body');
  const replacement = oldShape.replace(/<p:txBody>[\s\S]*?<\/p:txBody>/,newBody);
  originalZip.file(name,before.replace(oldShape,replacement));
  changed.push(name);
}
const corrections = [
  [7,'全体上限','要求上限'],
  [7,'BEV候補範囲','構成探索範囲'],
  [10,'PVを使える時間にBEVを活用','高PVでBEV担当が増加'],
  [10,'充電できる量に合わせICEを増加','低PVでICE担当が増加'],
  [13,'高PV：余剰は多いが、充電できる時間と合わず抑制が発生','高PV：抑制が発生。原因の特定は今後の課題'],
  [14,'高PVでも時間が合わず余る','抑制の原因は未特定'],
];
for (const [number,oldText,newText] of corrections) {
  const name=`ppt/slides/slide${number}.xml`;
  const xml=await originalZip.file(name).async('string');
  if (!xml.includes(oldText)) throw new Error(`Missing correction text: ${oldText}`);
  originalZip.file(name,xml.replace(oldText,newText));
  if (!changed.includes(name)) changed.push(name);
}
const candidatePath = path.join(build,'candidate.pptx');
await fs.writeFile(candidatePath,await originalZip.generateAsync({type:'nodebuffer'}));
const finalPath=path.join(output,'august_progress_with_speaker_notes_20260906.pptx');
const sourceXml=await originalZip.file('ppt/presentation.xml').async('string');
const size=sourceXml.match(/<p:sldSz\b[^>]*cx="(\d+)"[^>]*cy="(\d+)"/);
await finalizePresentation({workspaceDir:root,candidatePath,finalPath,
  pythonExecutable:path.join(runtime,'python/python.exe'),
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu',`${size[1]},${size[2]}`],
  explicitTotalSlideCount:18,verifyArtifactToolImport:true,
  receiptPath:path.join(build,'validation.json')});
const finalBytes=await fs.readFile(finalPath);
const finalZip=await JSZip.loadAsync(finalBytes);
const sourceZip=await JSZip.loadAsync(sourceBytes);
for (const name of Object.keys(sourceZip.files).filter(name=>!sourceZip.files[name].dir)) {
  if (!changed.includes(name) && digest(await sourceZip.file(name).async('nodebuffer'))!==digest(await finalZip.file(name).async('nodebuffer'))) {
    throw new Error(`Unintended package change: ${name}`);
  }
}
if (digest(await fs.readFile(source))!==digest(sourceBytes)) throw new Error('Source changed during edit');
await fs.writeFile(path.join(build,'preservation.json'),JSON.stringify({source,source_sha256:digest(sourceBytes),finalPath,final_sha256:digest(finalBytes),changed_parts:changed},null,2));
const verified = await PresentationFile.importPptx(await FileBlob.load(finalPath));
for (let index=0;index<18;index++) {
  const png=await verified.slides.getItem(index).export({format:'png',scale:1});
  await fs.writeFile(path.join(build,`final-${index+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
console.log(finalPath);
