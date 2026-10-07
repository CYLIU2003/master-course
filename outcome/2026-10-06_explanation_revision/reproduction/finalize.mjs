import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const b=process.argv[2],out=process.argv[3],filename=process.argv[4]??'research_progress_20261006_explained.pptx';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.1004.11800/skills/presentations';
const rt='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=rt+'/node/node_modules';
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const inventory=JSON.parse(await fs.readFile('C:/master-course/output/presentation_finish_20261005_delivery/revision_inventory.json','utf8'));
await fs.mkdir(out,{recursive:true});
await finalizePresentation({
 workspaceDir:'C:/master-course',candidatePath:b+'/candidate.pptx',finalPath:out+'/'+filename,explicitTotalSlideCount:44,
 requiredNativeTableOwnerSlides:inventory.requiredNativeTableOwnerSlides,
 requiredNativeChartOwnerSlides:inventory.requiredNativeChartOwnerSlides,
 materializeLiteralChartWorkbooks:false,
 pythonExecutable:rt+'/python/python.exe',
 integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...inventory.requiredNativeTableOwnerSlides.flatMap(i=>['--require-native-table-slide',String(i)])],
 fontPolicy:{basis:'reference',families:['Noto Sans JP'],referencePath:'C:/master-course/outcome/2026-10-05_teacher_ready/research_progress_20261005_teacher_ready.pptx',referenceSha256:'af5be0f3460aa0e3d16c3cd633ff8fab22396cf9196d680daae7ce0895f77b31'},
 verifyArtifactToolImport:true,receiptPath:b+'/'+filename+'.validation.json'
});
console.log('Final edited presentation validated.');
