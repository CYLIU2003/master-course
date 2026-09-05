/** Edit the August deck using sealed, local evidence; never invoke optimization. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'../..');
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.903.11726/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {PresentationFile,FileBlob}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
if(process.argv.includes('--help')) {
  console.log('node build_august_progress_revision.mjs [--finalize] [--output-dir PATH] [--build-dir PATH]\nUse fresh directories when finalizing again; existing final PPTX and receipt are never overwritten.');
  process.exit(0);
}
function directoryOption(name,fallback) {
  const index=process.argv.indexOf(name);
  if(index<0)return path.join(root,fallback);
  const value=process.argv[index+1];assert(value&&!value.startsWith('--'),`Missing ${name}`);
  const absolute=path.resolve(root,value);const relative=path.relative(root,absolute);
  assert(relative&&!relative.startsWith('..')&&!path.isAbsolute(relative),'Output must stay inside repository');
  return absolute;
}
const out=directoryOption('--output-dir','outcome/2026-09-05_august_progress_revision');
const build=directoryOption('--build-dir','output/august_brushup_20260905');
const source=path.join(root,'outcome/修士研究_2026年8月_進捗報告_先行研究図表パラメータ追加版.pptx');
const sourceHash='15de444f1407faa24ffb83a86dc2c60999edeb087fea144400dda8248f365b27';
const analysis='outcome/2026-09-05_research_progress/analysis';
const evidence='docs/evidence/weather_dispatch_rerun_bb0c005';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const read=relative=>fs.readFile(path.join(root,relative),'utf8');
const json=async relative=>JSON.parse(await read(relative));
const sources={};
async function check(relative,expected) {
  const actual=sha(await fs.readFile(path.join(root,relative)));
  assert.equal(actual,expected,`Source changed: ${relative}`); sources[relative]=actual;
}
// Verify the existing evidence/derivation manifest, not just copied slide numbers.
const manifest=await json(`${analysis}/manifest.json`);
for(const [name,hash] of Object.entries(manifest.source_sha256)) await check(name,hash);
for(const [name,hash] of Object.entries(manifest.outputs)) await check(`${analysis}/${name}`,hash);
await check(path.relative(root,source).replaceAll('\\','/'),sourceHash);
const data=await json(`${analysis}/summary.json`);
const result=await json(`${evidence}/result_summary.json`);
assert.equal(result.execution_git_sha,'bb0c0050883a91dd86a9e8813ae88d4b6d8c361d');
assert.equal(result.status,'PASS_NORMAL_PATH_CONFIRMATION');
assert.equal(result.teacher_release_status,'BLOCKED');
const S=result.scenarios.SUNNY, R=result.scenarios.RAIN;
for(const row of [S,R]) {
  assert.equal(row.served_trips,264); assert.equal(row.unserved_trips,0);
  assert.equal(row.rolling_steps,'24/24'); assert.equal(row.physical_validation,'VALID');
  assert.equal(row.accounting_reconciliation,'OK');
}
// These two generated CSVs have no quoted or multiline cells.
function simpleCsv(text) {
  assert(!text.includes('"'),'Use a CSV parser if the schema gains quoted fields');
  const [header,...lines]=text.trim().split(/\r?\n/); const keys=header.split(',');
  return lines.map(line=>{const cells=line.split(',');assert.equal(cells.length,keys.length);
    return Object.fromEntries(keys.map((key,index)=>[key,cells[index]]));});
}
const slots=simpleCsv(await read(`${analysis}/executed_slots.csv`));
for(const scenario of ['SUNNY','RAIN']) {
  const rows=slots.filter(row=>row.scenario===scenario);assert.equal(rows.length,96);
  rows.forEach((row,index)=>{assert.equal(+row.slot_index,index);assert.equal(+row.slot_minutes,15);});
  const total=rows.reduce((sum,row)=>sum + +row.pv_generated_kwh,0);
  assert(Math.abs(total-result.scenarios[scenario].executed_day_pv_generated_kwh)<1e-6);
}
const candidatePath='docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis.csv';
const candidateSummaryPath='docs/thesis/authoring_v1/tables/cross_weather_candidate_analysis_summary.json';
const candidateMeta=await json(candidateSummaryPath);
for(const item of Object.values(candidateMeta.source_files)) await check(item.path,item.sha256);
await check(candidateMeta.published_matrix.path,candidateMeta.published_matrix.sha256);
const candidates=simpleCsv(await read(candidatePath));assert.equal(candidates.length,22);
assert.equal(new Set(candidates.map(c=>c.physical_assignment_sha256)).size,22);
for(const [name,row] of [['SUNNY',S],['RAIN',R]]) {
  const selected=candidates.find(c=>c[`selected_${name.toLowerCase()}`]==='True');
  assert.equal(selected.physical_assignment_sha256,row.selected_physical_assignment_sha256);
  assert(Math.abs(+selected[`${name.toLowerCase()}_cost_jpy`]-row.day_ahead_selected_cost_jpy)<1e-6);
}
for(const relative of [candidatePath,candidateSummaryPath,'docs/thesis/authoring_v1/03_mathematical_formulation.md',
  'docs/thesis/authoring_v1/05_assumptions_parameters_units.md','outcome/2026-09-05_literature_review/01_critical_review.md',
  'outcome/2026-09-05_literature_review/02_adoption_protocol.md','outcome/2026-09-05_research_progress/04_parameter_sources.csv']) {
  sources[relative]=sha(await fs.readFile(path.join(root,relative)));
}
await fs.mkdir(out,{recursive:true}); await fs.mkdir(build,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(source));assert.equal(p.slides.items.length,18);
const originalSlides=[...p.slides.items];
const snapshot=await p.inspect({kind:'textbox',maxChars:300000});
const anchors=snapshot.ndjson.split('\n').filter(Boolean).map(x=>JSON.parse(x)).filter(x=>x.kind==='textbox');
const family='Noto Sans CJK JP';
const navy='#202A59',ink='#172033',muted='#66768D',teal='#1A9C8B',blue='#346BB7',gold='#E8B448',brown='#8A6B59';
const notes=[]; const tableOwners=new Set(),chartOwners=new Set();
const money=n=>Math.round(n).toLocaleString('en-US');
function text(s,value,left,top,width,height,size=25,color=ink,bold=false) {
  const shape=s.shapes.add({geometry:'textbox',name:value.slice(0,48),position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
  shape.text=value;shape.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'};return shape;
}
function note(s,title,body,refs=[]) {
  const value=`${title}\n\n${body}\n\n出典\n${refs.join('\n')}\n\n実験SHA: ${result.execution_git_sha}\n資料改訂: 2026-09-05。新規solver実験なし。`;
  s.speakerNotes.textFrame.setText(value);notes.push({slide:p.slides.items.indexOf(s)+1,title,body,sources:refs});
}
function reset(number,title) {
  const s=originalSlides[number-1];s.shapes.deleteAll();
  for(const collection of [s.images,s.tables,s.charts]) for(const item of [...collection.items]) collection.deleteById(item.id);
  chrome(s,number,title);return s;
}
function chrome(s,number,title) {
  s.background.fill='#FFFFFF';text(s,title,43,20,1194,48,32,ink,true);
  s.shapes.add({geometry:'line',position:{left:43,top:70,width:1176,height:0},fill:'none',line:{fill:blue,width:2}});
  text(s,'8月進捗報告 改訂版 ｜ 凍結結果 bb0c005',46,687,1030,20,12,muted);
  text(s,`${number}/22`,1162,683,72,22,12,muted);
}
function add(title) {const s=p.slides.add();chrome(s,p.slides.items.length,title);return s;}
function takeaway(s,value,color=teal) {text(s,value,64,613,1152,62,24,color,true);}
function table(s,values,{left=64,top=140,width=1152,height=405,widths,size=23}={}) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left,top,width,height,values,columnWidths:widths});
  for(let r=0;r<values.length;r++) for(let c=0;c<values[0].length;c++) {
    const cell=t.getCell(r,c);cell.fill=r===0?navy:r%2?'#F6F8FA':'#FFFFFF';
    cell.text.style={typeface:family,fontSize:size,color:r===0?'#FFFFFF':ink,bold:r===0||c===0,autoFit:'none'};
  }
  t.borders.assign({style:'solid',fill:'#E3E9F0',width:1});tableOwners.add(p.slides.items.indexOf(s)+1);return t;
}
function chart(s,type,config) {
  // Chart workbooks use six decimal places; the sealed physical/accounting data
  // and source-linked notes retain their original precision.
  const series=config.series.map(item=>({...item,
    values:item.values?.map(value=>Number(value.toFixed(6))),
    xValues:item.xValues?.map(value=>Number(value.toFixed(6)))}));
  const c=s.charts.add(type,{...config,series,chartFill:'#FFFFFF',plotAreaFill:'#FFFFFF'});
  applyPresentationChartFont(c,{fontFamily:family});chartOwners.add(p.slides.items.indexOf(s)+1);return c;
}
const axis={textStyle:{typeface:family,fontSize:19},majorGridlines:{fill:'#E3E9F0',width:1,style:'solid'}};
const legend={position:'bottom',textStyle:{typeface:family,fontSize:20}};
function replace(number,old,value,size) {
  const found=anchors.find(a=>a.slide===number&&a.text===old);assert(found,`Missing source text: ${old}`);
  const sh=p.resolve(found.id);sh.text=value;if(size)sh.text.style={typeface:family,fontSize:size,color:ink};return sh;
}

// Retain the original cover, background, scenario diagram and energy-flow diagram.
replace(1,'修士論文研究　8月進捗報告','修士論文研究　8月進捗報告・改訂版',43);
const coverTitle=p.resolve(anchors.find(a=>a.slide===1&&a.text==='修士論文研究　8月進捗報告').id);
coverTitle.text.style={typeface:family,fontSize:43,color:'#FFFFFF',bold:true};
replace(1,'― 前回からの改善点と、11月に向けた次の検証 ―','― 何が分かり、何を次に証明するか ―',25);
replace(1,'2026年8月31日　電力システム研究室　劉 承洋','原版 2026年8月31日 ／ 改訂 9月5日　電力システム研究室　劉 承洋',19);
replace(1,'1/18','1/22',12);
note(originalSlides[0],'研究の一文説明','固定平日時刻表を守りながら、BEVとICEの担当便を選び、その配車で可能な充電・PV・BESS運用を比較する研究です。今日は8月に得た二つの実行可能な結果と、優位性の検証に足りない証拠を分けて説明します。改訂によって新しい最適化結果が出たわけではありません。',[`${evidence}/result_summary.json`]);
replace(2,'2/18','2/22',12);
note(originalSlides[1],'背景と決定のつながり','BEVは安価な電源を使えるだけでは足りず、次便に間に合う場所と時間で充電できる必要があります。充電設備・受電上限・SOCを守ると、どの便をBEVにするかと充電の時刻が結び付きます。「まとめて考える」はシステム全体の意味で、現行法が一体型の大域最適解を求めるという意味ではありません。',['docs/thesis/authoring_v1/03_mathematical_formulation.md']);

let s=reset(3,'研究課題：PVを考慮した配車判断に、どこまで価値があるか');
table(s,[['問い','測るもの','現在の到達点'],['RQ1：配車・電源利用は変わるか','便数・営業距離・燃料・費用','2つの固定PV条件で差を確認'],['RQ2：二段階法の評価額は妥当か','小規模統合参照との同一尺度差','未実験。目的の違いも分離'],['RQ3：判断は計算条件に頑健か','候補範囲・時間を変えた配車と費用','未実験。次点差だけでは不十分']],{top:153,height:330,widths:[430,355,367],size:23});
text(s,'貢献候補：固定条件での運用上の違いと、その判断が成り立つ範囲を示す。',64,526,1152,62,26,navy,true);
takeaway(s,'「混成配車＋充電を扱うこと」自体は新規性ではない。優位性は比較で示す。');
note(s,'三つの問いを別々に答える','RQ1は選択済み計画の記述的結果まで進んでいます。RQ2/RQ3は未実験です。結果を見てから都合よく仮説を作らず、比較の対象・費用尺度・失敗時の扱いを固定します。単純方式への性能優位や天候一般への因果効果は現在の二条件からは言えません。',['docs/thesis/authoring_v1/01_research_questions_and_contributions.md','outcome/2026-09-05_literature_review/02_adoption_protocol.md','https://research.chalmers.se/en/publication/538305']);

replace(4,'4/18','4/22',12);
replace(4,'車両60台：BEV 35台／ICE 25台','Prepare確定の有効車両60台：\nBEV 35台／ICE 25台',22);
note(originalSlides[3],'比較対象は晴雨の観測二日ではない','SUNNY 771d115b-75b0-49f7-a7f0-25f259a2cd21、RAIN b23fd26c-1233-4c73-bb9e-bdb8b1584760。両者ともservice_dateは2025-08-05、WEEKDAY、弦巻264便で固定し、RAINには8月10日由来の低PV曲線を与えます。日曜ダイヤや電費まで変えた晴雨比較ではありません。60台はこの凍結Prepareの有効集合であり、一般設定の固定台数ではありません。入力ハッシュの一致はresult_summary.input_contractに記録されています。充電器・PV・BESS設備はケース設定で、実際の営業所の設置実績と確認した値ではありません。',[`${evidence}/result_summary.json`,'outcome/2026-09-05_research_progress/04_parameter_sources.csv']);

s=reset(5,'研究手法：配車候補を作り、電力計画で評価してから選ぶ');
const steps=[['1 入力固定','Prepare・時刻表\n車両・設備・PV'],['2 Stage 1','配車候補を生成\nエネルギーは緩和'],['3 Stage 2','配車を固定\n充電・PV・BESS'],['4 候補選択','前日費用で比較\n有限22候補内'],['5 Rolling','選択配車は固定\n電力を毎時更新'],['6 実行日検算','96区間を接続\n物理・費用を検算']];
for(const [i,[title,body]] of steps.entries()) {const x=49+i*198;
  text(s,title,x,161,181,60,26,i%2?blue:navy,true);
  text(s,body,x,245,181,145,22);
  if(i<5)text(s,'→',x+170,208,35,45,25,muted);
}
text(s,'選択に使う費用と、Rolling後に報告する費用は別。',64,436,1152,60,30,navy,true);
text(s,'RAIN：前日 698,296円 → 実行日 698,599円。残余問題の目的値は足し合わせない。',64,507,1152,80,25);
takeaway(s,'Stage 1のgapは、最終的な24時間総費用の誤差保証ではない。');
note(s,'二段階法を正しく説明する','Stage 1には時刻別エネルギーrecourseの緩和があり、電力を全く考えない配車ではありません。しかしStage 2の厳密な電力スケジュールとは異なります。候補ごとに配車を固定して電力計画を求め、canonicalな前日評価額、使用車両数、物理割当hashの辞書順で選択します。その後のRollingは配車を変えず残りの電力計画を更新します。最終費用の唯一の正本はrolling_hourly_chain/executed_day_accounting.jsonです。',['docs/thesis/authoring_v1/03_mathematical_formulation.md',`${evidence}/result_summary.json`]);

s=reset(6,'設定①：運行・車両・設備の値と、その根拠を分ける');
table(s,[['項目','凍結ケースの設定','根拠・解釈'],['運行・有効車両','264便・16路線 ／ BEV35・ICE25台','時刻表・Prepare由来。使用台数とは別'],['BEV','314 kWh、1.316 kWh/km、充電90 kW','電費の実測較正は未確認'],['BEV SOC・効率','20–90%、初期21.95–77.43%、効率95%','終端は各車の初期SOCへ戻す'],['ICE','160 L、初期144 L、4.52 km/L','車両入力。燃費の実証は未確認'],['充電器・受電','90 kW × 10基・各1口 ／ 受電200 kW','設備仮定。V2Gなし'],['PV・BESS','PV 1,000 kW ／ BESS 6,000 kWh・900 kW','実営業所の設置実績とは未確認'],['BESS SOC・効率','1,200–4,800 kWh、3,000→3,000 kWh','充放電各95%。代表日の境界条件']],{top:126,height:454,widths:[220,489,443],size:21});
takeaway(s,'「入力に保存されている」≠「実測・文献により妥当性を検証済み」。');
note(s,'パラメータは変更せず弱点を開示する','元版のパラメータを維持して、効率・SOC上下限・終端条件を補いました。充電設備やBESSの設定が実在設備として確認されたとは言いません。文献の図表構成を参考にしたことと、その文献から数値を採用したことは別です。感度分析や車両仕様の原典確認は今後の課題です。',['docs/thesis/authoring_v1/05_assumptions_parameters_units.md','outcome/2026-09-05_research_progress/04_parameter_sources.csv']);

s=reset(7,'設定②：評価費用・要求制御・実効探索条件を明示する');
table(s,[['項目','値・条件','読み方'],['評価係数','電力30円/kWh、軽油150円/L、CO₂ 1円/kg','実支出・LCCではない'],['使用車両費','20,000円/台日','使用台数で変わる。常に定数ではない'],['含めない費用','設備投資・運転士・劣化等、需要料金0','導入採算の結論には使えない'],['要求時間上限','全体585 s ／ S1 435 s ／ S2 30 s/候補','実測wall timeとは区別する'],['要求gap・共通制御','10%、seed 42、1 thread、15分／60分Rolling','BestObjStop・selector強化・ICE集約OFF'],['実効候補探索','22候補、構成radius 4、frontier 15–35台・120 s','生成された候補のBEV範囲は14–35台'],['選択と禁止事項','前日費用 → 使用台数 → 物理配車hash','fallback・repair・synthetic PVなし']],{top:128,height:451,widths:[220,541,391],size:21});
takeaway(s,'frontierの探索設定と、得られた候補全体の範囲は同じものではない。');
note(s,'設定と実測を混同しない','585秒は要求された上限の値で、22候補と24回Rollingを含む全工程wall timeが585秒以内だったという意味ではありません。実効上限は22候補・radius4であり、frontierの15–35台以外の生成経路も含むため候補全体は14–35台です。元版の設定表を残しつつ意味を修正しました。solver timeは補足20に出典の定義のまま示します。',[`${evidence}/result_summary.json`,'docs/thesis/authoring_v1/05_assumptions_parameters_units.md',candidateSummaryPath]);

s=reset(8,'先行研究の強みを、こちらの比較設計へ取り込む');
table(s,[['文献・確認範囲','強み／前提・限界','本研究で取り入れること'],['Cui 2023［要旨］','混成配車＋有限充電器の共同最適化\n詳細な目的・証明は本文照合が必要','新規性を混成だけに置かない\n近い比較対象として精読'],['Hu 2025［本文］','PV・蓄電・充電を一体評価、LR＋DP\n配車固定・PV完全予測等の前提','電源フロー・設備感度を分離\n数値gapの定義を揃える'],['Zhou 2025［本文］','小規模Gurobi参照と大規模ALNSを分離\n50便の差を大規模へ外挿しない','小規模の参照差と\n264便の実行可能性を別に示す'],['Manzolli 2025［本文］','実測データと不確実性下の計画評価\n頑健化の費用増加も開示','固定計画のストレスと再計画を分離\n失敗・追加費用も結果として報告']],{top:127,height:419,widths:[250,499,403],size:22});
takeaway(s,'文献の弱点を列挙するだけでは勝てない。同じ条件で比べられる証拠を作る。');
note(s,'先行研究を公平に評価する','Cuiらは著者所属機関の要旨を確認した範囲です。本文未読の部分を欠陥と断定しません。Huのsolution gapはGurobiとの費用差であり本研究のcertified MIP gapとは同一ではありません。Zhouの約0.7%は50便例で、418便の保証ではありません。Manzolliの約12%はBAUとの比較で、頑健解が名目解より必ず安いという意味ではありません。Soltanpourらは混成車両・分散電源・天候も既に扱うため、その単なる組合せを未開拓とは書きません。詳細は補足22。',['https://research.chalmers.se/en/publication/538305','https://doi.org/10.1016/j.apenergy.2025.125714','https://doi.org/10.1080/21680566.2025.2506689','https://doi.org/10.1016/j.apenergy.2024.125137','https://journals.sagepub.com/doi/10.1177/03611981221112405','outcome/2026-09-05_literature_review/01_critical_review.md']);

s=reset(9,'8月の到達点：実行可能性の証拠と、優位性の証拠を分ける');
table(s,[['確認項目','高PV / 低PV','証明すること・しないこと'],['全便・物理・会計','264/264、独立物理VALID、会計OK','この入力で実行可能な選択計画を得た'],['Rolling','24/24 accepted','更新連鎖が成立。更新の優位性は別実験'],['Stage 1 certified gap','9.521% / 1.656%','Stage 1の緩和を含む目的に対する証明'],['Stage 1 raw gap','9.521% / 9.521%','RAINのcertified値と区別する'],['未完了の証明','統合参照差・単純方式比較・安定性','大域最適・一般天候効果・研究releaseは未達']],{top:135,height:405,widths:[335,380,437],size:23});
takeaway(s,'検算PASSは重要な土台。ただし「先行研究より良い」という結論の代わりにはならない。');
note(s,'前回との差を研究の到達点で示す','元版の月内作業一覧を、現在の証拠が答える問いへ置き換えました。コード変更の前後を別SHAのまま性能比較することはしません。RAINのraw best boundは640000円ですがcertified best boundは695632.938124円です。両方を残し、同じStage 1 incumbent707349.173370円に対するgapの定義を説明します。最終実行日費用のgapではありません。teacher_release_statusはBLOCKEDのままです。',[`${evidence}/result_summary.json`,`${evidence}/RAIN/solver_metrics.json`]);

s=reset(10,'配車の違い：低PVでICEだった108便が、高PVではBEVへ');
for(const [i,key,title,max] of [[0,'vehicles','使用車両数［台］',32],[1,'trips','担当便数［便］',264]]) {
  text(s,title,64+i*585,115,550,46,28,navy,true);
  chart(s,'bar',{position:{left:64+i*585,top:174,width:550,height:296},categories:['高PV','低PV'],series:[
    {name:'BEV',values:key==='vehicles'?[S.used_bev,R.used_bev]:[S.bev_trips,R.bev_trips],fill:teal},
    {name:'ICE',values:key==='vehicles'?[S.used_ice,R.used_ice]:[S.ice_trips,R.ice_trips],fill:brown}],
    barOptions:{direction:'column',grouping:'stacked',gapWidth:90},hasLegend:true,legend,
    yAxis:{...axis,min:0,max,majorUnit:key==='vehicles'?8:66},xAxis:{textStyle:{typeface:family,fontSize:23}},
    dataLabels:{showValue:true,position:'center',textStyle:{typeface:family,fontSize:23,fill:'#FFFFFF',bold:true}}});
}
text(s,'BEV営業距離比：高PV 72.8% ／ 低PV 29.7%',64,501,1152,58,29,navy,true);
text(s,'共通BEV 91便、低PV ICE→高PV BEV 108便、逆方向0便、共通ICE 65便。',64,561,1152,48,24);
takeaway(s,'便数・距離・台数は別指標。営業距離は停留所座標由来の推定で、回送は除外。');
note(s,'同じ便を照合して違いを説明する','単に使用台数を比べず同じtrip IDを対応づけました。変更108便は渋22が78便、渋23が30便です。BEV担当便比は75.38%/34.47%ですが営業距離比は72.78%/29.73%で、便数だけでは輸送仕事量の違いを十分に表せません。営業距離は実測オドメータではなく停留所座標を結んだ推定で回送を含みません。なぜこの便が選ばれたかの因果分解は未完了です。',[`${analysis}/summary.json`,`${analysis}/trip_powertrain_changes.csv`,`${analysis}/dispatch_assignments.csv`]);

s=reset(11,'22候補内の評価：BEV台数だけでは費用の大小は決まらない');
const sorted=[...candidates].sort((a,b)=>+a.used_bev-+b.used_bev);
chart(s,'scatter',{position:{left:57,top:130,width:785,height:415},series:[
  ...[['高PV','sunny_cost_jpy',teal,'circle'],['低PV','rain_cost_jpy',blue,'square']].map(([name,key,fill,symbol])=>({name,xValues:sorted.map(x=>+x.used_bev),values:sorted.map(x=>+x[key]/1000),fill,marker:{symbol,size:7}}))],
  scatterOptions:{style:'marker'},hasLegend:true,legend,xAxis:{...axis,min:14,max:36,majorUnit:4,title:'使用BEV［台］'},yAxis:{...axis,min:640,max:1140,majorUnit:100,title:'前日候補評価額［千円］'}});
text(s,'選択された配車',873,151,340,50,28,navy,true);
text(s,'高PV：BEV28・ICE4台\n低PV：BEV21・ICE11台',873,218,341,109,25);
text(s,'低PVの次点差\n566.62円（前日評価）',873,365,341,105,26,blue,true);
text(s,'同じ配車hashを両PVで評価した診断表。全候補の24回Rollingを検証した図ではない。',64,555,1152,51,22,muted);
takeaway(s,'探索範囲・時間を変えても選択が保たれるかは未検証。全体最適性は示さない。');
note(s,'候補図の読み方と限界','同じBEV台数を同じ配車とみなすのではなく、physical_assignment_sha256で22候補を対応づけた表を用いています。候補図は固定配車の前日recourse評価で、24/24 Rollingを通った選択計画の実行日費用とは区別します。診断表でfeasible/selectableであっても全候補のformal acceptanceを意味しません。低PVの選択698296.465284円と次点698863.087754円の差は566.622470円です。差が小さいことは安定性検証の動機で、不安定性の証明そのものではありません。大きなBEV台数で高費用になる点は総使用車両数も変わる候補であり、BEVを増やす単一介入の因果曲線ではありません。',[candidatePath,candidateSummaryPath,`${evidence}/cross_weather_fixed_dispatch_matrix.csv`]);

s=reset(12,'費用差37,615円の約88%は燃料費：何を評価した差か');
const cost=data.costs;
chart(s,'bar',{position:{left:60,top:142,width:720,height:409},categories:['高PV','低PV'],series:[['燃料','fuel_jpy',brown],['系統電力','electricity_jpy',blue],['CO₂','co2_jpy',teal]].map(([name,key,fill])=>({name,values:cost.map(c=>c[key]),fill})),barOptions:{direction:'column',grouping:'stacked',gapWidth:110},hasLegend:true,legend,yAxis:{...axis,min:0,max:60000,majorUnit:20000,numberFormatCode:'#,##0',title:'車両使用費を除く評価額［円］'},xAxis:{textStyle:{typeface:family,fontSize:24}},dataLabels:{showValue:false}});
text(s,'実行日評価額',828,144,370,48,29,navy,true);
text(s,`高PV ${money(S.executed_day_cost_jpy)}円\n低PV ${money(R.executed_day_cost_jpy)}円`,828,216,387,119,28);
text(s,'差の内訳（低PV−高PV）\n燃料 +33,054円\n電力   +3,926円\nCO₂      +635円',828,369,387,182,25);
text(s,'車両使用費は両計画とも32台×20,000円＝640,000円。図では共通額を分離。',64,556,1152,52,23);
takeaway(s,'PV設備を導入した採算や、単純方式に対する改善率を表す数字ではない。');
note(s,'費用の比較対象を必ず言う','比較は同一の非PV入力に対して得た二つの選択済み運用です。高PV660983.7838045円、低PV698598.6286432円で差37614.8448387円です。車両使用費がたまたま両方64万円なので差額は燃料・系統・CO2で説明できますが、異なる台数の候補比較で車両使用費を落としてはいけません。設備投資、劣化、運転士等を含む実際の総運用費ではありません。費用差は入力PVの比較であり手法の優位性の比較ではありません。',[`${analysis}/summary.json`,`${evidence}/SUNNY/executed_day_accounting.json`,`${evidence}/RAIN/executed_day_accounting.json`]);

replace(13,'13/18','13/22',12);
replace(13,'先行研究の電力フロー図にならい、PV・BESS・系統の流れを日合計で整理','PV・BESS・系統の流れを、実行日の日合計で整理',32);
const energyEnd=anchors.find(a=>a.slide===13&&a.text.startsWith('高PV：余剰'));
assert(energyEnd);const energyShape=p.resolve(energyEnd.id);energyShape.text='高PV：抑制3,373 kWhが残る ／ 低PV：PVをほぼ全量利用し、系統から131 kWh補給';
energyShape.text.style={typeface:family,fontSize:20,color:navy,bold:true};
const energyCitation=anchors.find(a=>a.slide===13&&a.text.startsWith('参考構成'));
assert(energyCitation);p.resolve(energyCitation.id).text='出典：凍結bb0c005の実行日会計。電源別の営業所集計であり、車両別の電源帰属ではない。';
note(originalSlides[12],'電力フローの図は維持し、因果の言い過ぎを除く','PVの発電は高PV6056.25、低PV996.2 kWhです。高PVは直接110.0518、BESSへ2572.9774、抑制3373.2208 kWh。低PVは直接230.5677、BESSへ765.6323 kWhです。BESSからbusへ2322.1121/690.9831 kWh、系統から0/130.8519 kWh。BESS境界が等しいため充放電の差250.8653/74.6491 kWhはこの会計境界の損失です。bus充電後の車載電池効率とは別です。高PVなのに直接充電が少ない理由や抑制原因は、この日合計図だけでは特定できません。元版の「時間と合わず」という断定を除きました。',[`${evidence}/result_summary.json`,`${analysis}/executed_slots.csv`]);

s=reset(14,'時間別の実績を読む：日合計だけでは分からない充電の時刻');
for(const [i,scenario,title] of [[0,'SUNNY','高PV：発電と充電の時刻を重ねる'],[1,'RAIN','低PV：小さいPVを使い切る']]) {
  const rows=slots.filter(r=>r.scenario===scenario);
  text(s,title,64+i*590,123,560,52,25,navy,true);
  chart(s,'scatter',{position:{left:54+i*590,top:195,width:570,height:365},series:[['PV発電','pv_generated_kwh',gold],['BEV充電','bev_charging_load_kwh',teal],['PV抑制','pv_curtailed_kwh',muted]].map(([name,key,color])=>({name,xValues:rows.map(r=>+r.slot_index/4),values:rows.map(r=>+r[key]*4),line:{fill:color,width:2},marker:{symbol:'none'},fill:color})),scatterOptions:{style:'line'},hasLegend:true,legend:{...legend,textStyle:{typeface:family,fontSize:19}},xAxis:{...axis,min:0,max:24,majorUnit:6,title:'時刻［時］'},yAxis:{...axis,min:0,max:900,majorUnit:300,title:'15分平均電力［kW］'}});
}
takeaway(s,'各点は15分区間の平均電力。左右の軸は同一。時系列の一致は因果の証明ではない。');
note(s,'区間電力量から平均電力へ変換する','24回Rollingで実行された各1時間のprefixを接続した96区間の値を用います。kWhの区間電力量を0.25時間で割りkWの平均電力としました。横軸は区間開始時刻、線は点を結んだ表示であり15分内の瞬時変動を測ったものではありません。高PVと低PVは同一軸です。発電・充電・抑制を重ねても帰庫状況や終端SOCによる原因分離はまだできません。BESS残量は補足21で確認できます。',[`${analysis}/executed_slots.csv`]);

s=reset(15,'PV抑制の考察：「設備が満杯だった」とはまだ言えない');
table(s,[['高PVの選択計画で観測したこと','結果','解釈'],['抑制の総量','3,373.22 kWh ／ 26区間','利用しなかった電力量'],['充電電力ゼロの区間と重なる抑制','2,531.995 kWh（75.06%）','同時に起きた割合。原因の割合ではない'],['10ポート全使用と重なる抑制','0 kWh','全基使用だけでは説明できない'],['BESS区間末SOCが上限と重なる抑制','0 kWh','SOC上限4,800 kWh\n満杯だけでは説明できない']],{top:136,height:366,widths:[490,270,392],size:22});
text(s,'次に切り分ける仮説：帰庫・必要電力量・終端SOC・同費用の別解。',64,542,1152,55,26,navy,true);
takeaway(s,'充電待ち時間、原因別の抑制率、最小必要充電器数は、この結果からは未識別。');
note(s,'相関する状態を原因と呼ばない','全ポート使用は充電電力1e-6 kW超で数え、tiny powerの影響を1 kW以上という別指標でも開示しています。抑制枠末のBESS SOC最大は3644.33 kWhで、上限4800に達していません。ただし区間末の状態だけをもって設備制約が一切効かないとは言えません。車両不在か、不要な充電をしない最適行動か、PV抑制と同じ費用になる別解かを判定するには配車固定の比較や一因子変更が必要です。',[`${analysis}/charging_and_curtailment_summary.csv`,`${analysis}/executed_slots.csv`]);

s=reset(16,'残る研究上の弱点と、それを解消する証拠');
table(s,[['不足しているもの','なぜ必要か','解消の方向'],['手法の内的妥当性','二段階法でどれだけ評価額を失うか未確認','8/12/24便の統合参照比較'],['結果の安定性','低PVは候補内の次点差が566.62円','候補範囲×時間を分けて検証'],['説明可能なbaseline','PV差と手法差を混同しないため','同じ配車・設備・情報で方策を比較'],['入力の実証・一般化','電費・設備仮定、PV二曲線に依存','原典確認、別日・ストレス評価'],['費用と情報の適用範囲','投資費用や予測誤差への効果は未評価','運用費と導入採算、予測と実現を区別']],{top:136,height:414,widths:[295,460,397],size:23});
takeaway(s,'新機能の数より、比較可能性・再現性・失敗も含む説明の厚さを上げる。');
note(s,'弱点は次に解ける問いへ変える','最適性、安定性、単純方策への優位性は別の不足です。実行可能性の監査だけを増やしてもそれらは埋まりません。二日分のPV入力にsolver seedを増やしても天候サンプル数は増えません。入力電費と設備値の出典やSOC境界が結果へ与える影響も課題です。性能が改善しなかった場合も効果が成立しない範囲として報告します。',['outcome/2026-09-05_literature_review/02_adoption_protocol.md','docs/research/november_2026/signoff/01_decision_sheet.md']);

s=reset(17,'次の一歩：既存の小規模参照比較を、承認された範囲で行う');
table(s,[['順序','比較・固定する条件','判定／開始条件'],['最優先 E0','RAIN 8・12・24便：Phase 3整合解と\nscalar統合参照を同一尺度で評価','既存承認JSON・予算・停止条件を検証\n参照の証明がなければ厳密誤差と呼ばない'],['次：既存P0','候補範囲×計算時間の安定性','実用同等の閾値を事前承認\n全ケース・失敗を残す'],['その後 E1','同じ配車・PV・設備・SOC・情報で\n単純方策と最適化を比較','優先順・充電目標・BESS方策を事前固定\n共同変更なら共同最適化と命名'],['その後 E2','固定計画ストレスと再計画を分離','名目計画の失敗と救済の効果を混ぜない\n追加条件・予算の承認後に実行']],{top:137,height:376,widths:[200,466,486],size:21});
text(s,'指導教員への判断事項：主結果の軸、許容差、範囲・予算、gap開示方針。',64,538,1152,63,25,navy,true);
takeaway(s,'現状は未署名・未実験。承認だけでなく、実行前検証とcleanな凍結SHAが必要。');
note(s,'次の実験を勝手に開始しない','E0は既存の11月P0契約を再利用し、8/12/24便の各subsetだけを比較します。Phase 3とscalar統合目的には違いがあるため評価額差を純粋な分解誤差としません。既存M0全ICE、M1混成PV/BESSなし、M2現行Phase3、M3scalar参照は単純先着順充電baselineではありません。既存P0の安定性比較はE2ストレスとは別です。E1の方策ルールは未定義の部分があり、実装済みと書きません。安定性の実用同等閾値等も人間の承認事項です。コマンドは既存exact_execution_commands.ps1の該当コマンドを承認後に個別実行します。PS1全体を実行してはいけません。',['docs/research/november_2026/signoff/01_decision_sheet.md','docs/research/november_2026/signoff/exact_execution_commands.ps1','outcome/2026-09-05_literature_review/02_adoption_protocol.md']);

s=reset(18,'まとめ：説明できる結果から、比較で支えた研究へ');
text(s,'分かったこと',65,135,1120,55,32,teal,true);
text(s,'同じ264便・設備条件で、二つのPV入力から異なる実行可能な配車を得た。\n便数だけでなく営業距離・電源・費用・時間別の動きを追跡できる。',65,211,1138,126,27);
text(s,'まだ証明していないこと',65,382,1120,55,32,blue,true);
text(s,'二段階法の精度、単純方式より良いこと、別の日でも判断が安定すること。',65,455,1138,102,27);
takeaway(s,'次回は「実験を回した」ではなく、「一つの問いにどこまで答えたか」を報告する。');
note(s,'本人の言葉で締める','30秒の要約：この研究は、固定時刻表の全便を守りながら、混成車両の担当と充電電源を組み合わせて考えます。二つの固定PV条件で違う実行可能計画が選ばれました。ですが最も安い保証や先行研究への優位性はまだありません。次に小規模統合参照と比べ、二段階法の判断を評価します。自分で答える三問は、何を固定し何を決めるか、gapは何に対する値か、どんな結果なら自分の期待が否定されるか、です。',[`${evidence}/result_summary.json`,'outcome/2026-09-05_literature_review/02_adoption_protocol.md']);

s=add('補足：数理モデルの核を、決定と制約で説明する');
table(s,[['役割','式・記号（説明用抜粋）','意味'],['全便担当','Σᵥ yᵥᵢ = 1、 yᵥᵢ ∈ {0,1}','便iを必ず1台に割り当てる'],['便接続','到着ᵢ ＋ 折返しᵢ ＋ 回送ᵢⱼ ≤ 出発ⱼ','接続可能な便だけを同じ車両へ'],['BEV蓄電量','Sᵥ,ₜ₊₁ = Sᵥ,ₜ + η qᵥ,ₜ Δ − Eᵥ,ₜ','Δ=0.25 h、走行消費と充電を計上'],['PV収支','PVₜ = PV→busₜ + PV→BESSₜ + 抑制ₜ','各項は区間電力量［kWh］'],['候補選択','k* = argminₖ∈K feasible (Cdayahead,k, Nₖ, hashₖ)','有限候補内で前日費用・台数・hash順'],['報告費用','Cexec = 車両使用費 + 燃料費 + 系統費 + CO₂費','実行96区間から一度だけ評価']],{top:134,height:415,widths:[192,587,373],size:22});
takeaway(s,'式は抜粋。充電器競合・SOC上下限・終端・BESS排他なども同時に満たす。');
note(s,'数式の説明で外してはいけない点','これは実装全体を置き換える簡略モデルではなく説明用抜粋です。SはkWh、qはkWで、qに0.25時間と充電効率を掛けます。運行中・回送中・home depot不在時の充電は禁止です。Stage 1はエネルギーrecourse緩和を含む別の目的J1を用い、Stage 2は配車を固定して電力変数を選びます。車両別電源帰属の推定をsolver-nativeと主張しないため、ここではPV収支を営業所レベルで書いています。',['docs/thesis/authoring_v1/03_mathematical_formulation.md']);

s=add('補足：主要指標・solver記録と、解釈の境界');
table(s,[['指標','高PV','低PV'],['燃料［L］ ／ 系統購入［kWh］','137.521 ／ 0','357.881 ／ 130.852'],['peak受電［kW］ ／ 最低BEV SOC［kWh］','0 ／ 68.91','122.302 ／ 68.91'],['Stage 1 incumbent［円］',money(S.stage1_surrogate_incumbent_jpy),money(R.stage1_surrogate_incumbent_jpy)],['Stage 1 certified bound［円］',money(S.stage1_certified_best_bound_jpy),money(R.stage1_certified_best_bound_jpy)],['raw gap ／ certified gap','9.521% ／ 9.521%','9.521% ／ 1.656%'],['solve_time_seconds（記録値）','380.982 s','380.019 s'],['Stage 1 ／ Stage 2 runtime（記録値）','378.968 s ／ 2.014 s','378.638 s ／ 1.381 s'],['Stage 1 変数 ／ 二値 ／ 制約','825,858 ／ 726,240 ／ 151,574','左と同じ']],{top:123,height:448,widths:[542,305,305],size:20});
takeaway(s,'runtimeは単回の記録値。全工程wall time、反復性能比較、peak RSSの証拠ではない。');
note(s,'不足する計測値を作らない','数値はresult_summaryとsolver_metricsの記録欄をそのまま表にしたものです。solve_time_secondsはStage1+Stage2の記録値で、24回Rollingを含むエンドツーエンド時間ではありません。Stage2の記録値を22候補の総評価時間と呼びません。peak RSSは正本のper-run指標として残っておらず、約2.9GBというBFFサンプルをpeakに流用しません。最低SOC68.91kWhは214ではなく314kWh容量との比で約21.95%です。外部人間レビュー、承認、再開実験は別ゲートです。',[`${evidence}/result_summary.json`,`${evidence}/SUNNY/solver_metrics.json`,`${evidence}/RAIN/solver_metrics.json`]);

s=add('補足：BESSは初期・終端を同じ蓄電量に揃えて比較する');
chart(s,'scatter',{position:{left:71,top:155,width:1125,height:385},series:[['SUNNY','高PV',teal],['RAIN','低PV',blue]].map(([name,label,color])=>({name:label,xValues:[0,...slots.filter(r=>r.scenario===name).map(r=>(+r.slot_index+1)/4)],values:[3000,...slots.filter(r=>r.scenario===name).map(r=>+r.bess_soc_end_kwh)],line:{fill:color,width:3},marker:{symbol:'none'},fill:color})),scatterOptions:{style:'line'},hasLegend:true,legend,xAxis:{...axis,min:0,max:24,majorUnit:6,title:'時刻［時］'},yAxis:{...axis,min:0,max:6000,majorUnit:1500,title:'BESS蓄電量［kWh］'}});
text(s,'許容範囲 1,200–4,800 kWh ／ 初期・終端 3,000 kWh ／ 定格6,000 kWh。',64,551,1152,55,24);
takeaway(s,'「24回更新できた」だけでは予測誤差への強さは示せない。情報条件も比較する。');
note(s,'SOC境界と情報条件','t=0の3000kWhに96区間末のSOCを加えた97点です。許容範囲と初期・終端条件は高低PVで一致します。残量を翌日へ持ち越す条件やhorizonを変えれば結果は変わり得ます。中野2025は2日horizon・日次更新であり、本研究の毎時更新と同じ設定ではありません。将来情報、更新間隔、予測と実績、終端条件を揃えずRollingのみの効果と解釈しないことを学びます。',[`${analysis}/executed_slots.csv`,'docs/thesis/authoring_v1/05_assumptions_parameters_units.md','先行文献/電気バスの低炭素運用に向けたモデル予測型逐次充電計画の導入評価.pdf']);

s=add('補足：主要文献と、確認した範囲');
table(s,[['文献','書誌・識別子','利用した内容'],['Cui et al. (2023)','TR Part E 180, 103335\n10.1016/j.tre.2023.103335','所属機関の要旨：混成配車・充電器制約\n全文比較は次の課題'],['Hu, Li & Xie (2025)','Applied Energy 390, 125714\n10.1016/j.apenergy.2025.125714','No63本文：PV・BESS充電最適化\n仮定・gapの定義に注意'],['Zhou, An & Schmöcker (2025)','Transportmetrica B: Transport Dynamics\n10.1080/21680566.2025.2506689','No06本文：小規模参照と大規模探索\n規模をまたぐ誤差保証ではない'],['Manzolli et al. (2025)','Applied Energy 381, 125137\n10.1016/j.apenergy.2024.125137','No64本文：不確実性・実測データ\nBAU比較と名目計画比較を区別'],['Soltanpour et al. (2023)','Transportation Research Record 2677(2)\n10.1177/03611981221112405','出版社要旨：混成・分散電源・天候\n組合せだけの新規性主張を避ける'],['中野ら (2025)','電気バスの低炭素運用に向けた\nモデル予測型逐次充電計画の導入評価','提供PDF本文：2日horizon・日次更新\n毎時更新とは異なる']],{top:127,height:443,widths:[277,482,393],size:19});
takeaway(s,'元版の文献は削除せず原本に保存。未確認の図表参照・数値出典は改訂版へ継承しない。');
note(s,'参考文献の確認範囲と追加候補','本改訂は網羅的systematic reviewではなく、提供文献の再レビューと近接研究の追補です。2026-09-05にCuiのChalmers所属機関ページ、SoltanpourのSAGE要旨を確認しました。Cuiの著者公開PDFへのリンクも発見しましたが、本資料では要旨範囲の確認とし本文精読を偽りません。元版のFei、Najafi、Zhang等を否定したわけではなく、図表番号やパラメータの由来を確認せず本研究の実測根拠にしないためです。文献の長所・限界の詳細と他の23提供PDFの目録はOutcomeの文献レビューを参照してください。',['https://research.chalmers.se/en/publication/538305','https://research.chalmers.se/publication/538305/file/538305_Fulltext.pdf','https://journals.sagepub.com/doi/10.1177/03611981221112405','outcome/2026-09-05_literature_review/01_critical_review.md','outcome/2026-09-05_literature_review/source_inventory.json']);

assert.equal(p.slides.items.length,22);
await fs.writeFile(path.join(out,'speaker_notes.md'),'# 発表者ノート・説明練習\n\n'+notes.map(n=>`## ${n.slide}. ${n.title}\n\n${n.body}\n\n出典：\n\n${n.sources.map(x=>`- ${x}`).join('\n')}\n`).join('\n'));
await fs.writeFile(path.join(out,'source_manifest.json'),JSON.stringify({schema_version:'august_progress_revision_sources_v1',source_pptx:source,source_sha256:sourceHash,execution_git_sha:result.execution_git_sha,derivation_head:result.execution_git_sha===data.execution_git_sha?data.derivation_head:null,slide_count:22,solver_runs:0,sources,web_sources:[{url:'https://research.chalmers.se/en/publication/538305',accessed:'2026-09-05',scope:'author institutional abstract'},{url:'https://journals.sagepub.com/doi/10.1177/03611981221112405',accessed:'2026-09-05',scope:'publisher abstract'}]},null,2)+'\n');
const candidate=path.join(build,'revised_candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(candidate);
const tableNumbers=[...tableOwners],chartNumbers=[...chartOwners];
await fs.writeFile(path.join(build,'requirements.json'),JSON.stringify({slide_count:22,tableNumbers,chartNumbers}));
// Preview first; only the explicit --finalize invocation promotes a verified deck.
if(process.argv.includes('--finalize')) {
  const finalPath=path.join(out,'august_progress_revised_20260905.pptx');
  const receipt=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,
    pythonExecutable:path.join(runtime,'python/python.exe'),
    integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
    layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tableNumbers.flatMap(n=>['--require-native-table-slide',String(n)])],
    explicitTotalSlideCount:22,requiredNativeTableOwnerSlides:tableNumbers,requiredNativeChartOwnerSlides:chartNumbers,
    materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'reference',families:[family,'Arial'],referencePath:source,referenceSha256:sourceHash},
    verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
  console.log(JSON.stringify(receipt));
}
const view=await PresentationFile.importPptx(await FileBlob.load(process.argv.includes('--finalize')?path.join(out,'august_progress_revised_20260905.pptx'):candidate));
for(const [index,slide] of view.slides.items.entries()) {
  const png=await slide.export({format:'png',scale:1});
  await fs.writeFile(path.join(build,`revised-${String(index+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
assert.equal(sha(await fs.readFile(source)),sourceHash);
console.log(`Rendered ${view.slides.items.length} slides. Original unchanged. Verified ${Object.keys(sources).length} inputs.`);
