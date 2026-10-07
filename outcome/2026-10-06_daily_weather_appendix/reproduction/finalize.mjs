import fs from 'node:fs/promises';
import {pathToFileURL,fileURLToPath} from 'node:url';
import path from 'node:path';
const b=process.argv[2],out=process.argv[3];
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.1004.11800/skills/presentations';
const rt='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=rt+'/node/node_modules';
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const config=JSON.parse(await fs.readFile(new URL('./weather_inputs.json',import.meta.url),'utf8'));
const inventory=JSON.parse(await fs.readFile(new URL('./revision_inventory.json',import.meta.url),'utf8'));
const tableSlides=[...inventory.requiredNativeTableOwnerSlides,...Array.from({length:12},(_,i)=>45+i)];
const filename='research_progress_20261006_daily_weather.pptx';
await fs.mkdir(out,{recursive:true});
await finalizePresentation({
 workspaceDir:'C:/master-course',candidatePath:b+'/candidate.pptx',finalPath:out+'/'+filename,explicitTotalSlideCount:56,
 requiredNativeTableOwnerSlides:tableSlides,requiredNativeChartOwnerSlides:inventory.requiredNativeChartOwnerSlides,
 materializeLiteralChartWorkbooks:false,pythonExecutable:rt+'/python/python.exe',
 integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...tableSlides.flatMap(i=>['--require-native-table-slide',String(i)])],
 fontPolicy:{basis:'reference',families:['Noto Sans JP'],referencePath:path.resolve(path.dirname(fileURLToPath(import.meta.url)),'source_base.pptx'),referenceSha256:config.source_deck_sha256},
 verifyArtifactToolImport:true,receiptPath:b+'/'+filename+'.validation.json'
});
console.log('56-slide deck finalized with 12 appended native tables.');
