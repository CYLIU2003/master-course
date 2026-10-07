import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const build=process.argv[2] ?? 'C:/master-course/output/teacher_revision_20261002';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.930.11008/skills/presentations';
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=runtime+'/node/node_modules';
const {finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const inventory=JSON.parse(await fs.readFile(build+'/source_inventory.json','utf8'));
await finalizePresentation({workspaceDir:'C:/master-course',candidatePath:build+'/aligned_candidate.pptx',finalPath:process.argv[3] ?? 'C:/master-course/outcome/2026-10-02_teacher_comments/september_progress_20261002_v5_teacher_revised.pptx',explicitTotalSlideCount:39,requiredNativeTableOwnerSlides:[7,12,20,24,38,39],requiredNativeChartOwnerSlides:[8,9,10,11,13,14,15,17,19,25,26,27,28,29,30,31,32,33,34,35,36,37],materializeLiteralChartWorkbooks:false,pythonExecutable:runtime+'/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000',...[7,12,20,24,38,39].flatMap(i=>['--require-native-table-slide',String(i)])],fontPolicy:{basis:'reference',families:['Noto Sans JP'],referencePath:inventory.source,referenceSha256:inventory.sha256},verifyArtifactToolImport:true,receiptPath:build+'/verified_final_validation.json'});
console.log('Final deck validation passed');



