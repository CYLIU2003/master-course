import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const root='C:/master-course';
const folder=path.join(root,'outcome/2026-09-05_august_progress_revision');
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const receipt=JSON.parse(await fs.readFile(path.join(root,'output/august_brushup_20260905/validation.json'),'utf8'));
assert.equal(receipt.finalSha256,'377ba861be7872e96dbd5f0197bd8ee03e23dfc7a934ef2863d1bd05cd1339ae');
assert.equal(receipt.presentationLayout.warning_count,0);
await fs.copyFile(path.join(root,'output/august_brushup_20260905/validation.json'),path.join(folder,'validation_receipt.json'));
const files=[];
for(const name of (await fs.readdir(folder)).sort()) {
  if(name==='artifact_inventory.json')continue;
  const bytes=await fs.readFile(path.join(folder,name));
  files.push({path:name,bytes:bytes.length,sha256:sha(bytes)});
}
const inventory={schema_version:'outcome_artifact_inventory_v1',created_date:'2026-09-05',
  scope:'August PPTX refinement; no solver run; original preserved',files,
  implementation:[...await Promise.all(['tools/thesis_authoring/build_august_progress_revision.mjs','tests/test_august_progress_revision.py'].map(async name=>({path:name,sha256:sha(await fs.readFile(path.join(root,name)))})))]};
await fs.writeFile(path.join(folder,'artifact_inventory.json'),JSON.stringify(inventory,null,2)+'\n');
console.log(JSON.stringify({file_count:files.length,inventory_sha256:sha(await fs.readFile(path.join(folder,'artifact_inventory.json'))),pptx_sha256:receipt.finalSha256}));
