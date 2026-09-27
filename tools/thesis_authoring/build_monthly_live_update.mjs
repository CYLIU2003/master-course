// Build editable update slides from a hash-verified monthly report; never solve.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const [reportRoot, buildDir] = process.argv.slice(2).map(p=>path.resolve(p));
if (!reportRoot || !buildDir) throw new Error('Usage: node build_monthly_live_update.mjs REPORT_ROOT NEW_BUILD_DIR');
const runtime=process.env.RUNTIME_DEPENDENCIES;
const skill=process.env.PRESENTATIONS_SKILL_DIR;
if (!runtime || !skill) throw new Error('Set RUNTIME_DEPENDENCIES and PRESENTATIONS_SKILL_DIR from workspace dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const latest=await read(path.join(reportRoot,'latest.json'));
const directory=path.resolve(latest.directory);
if (!directory.startsWith(path.resolve(reportRoot,'revisions')+path.sep)) throw new Error('Revision escaped report root');
const manifest=await read(path.join(directory,'manifest.json'));
const raw=await fs.readFile(path.join(directory,'comparison.json'));
if (sha(raw)!==manifest['comparison.json']) throw new Error('Comparison hash mismatch');
const data=JSON.parse(raw), rows=data.rows;
const numericFields=['total_cost','vehicle_usage_cost','electricity_cost','fuel_cost','contract_overage_cost','co2_cost','grid_import_kwh','pv_generated_kwh'];
if (rows.length<2 || rows.some(r=>r.trips!==1704 || numericFields.some(k=>typeof r[k]!=='number' || !Number.isFinite(r[k])))) throw new Error('This Shibu21-23 report requires verified 1704-trip weeks and finite cost/energy values');
for (const r of rows) {
 const listed=['vehicle_usage_cost','electricity_cost','fuel_cost','contract_overage_cost','co2_cost'].reduce((a,k)=>a+r[k],0);
 if (Math.abs(listed-r.total_cost)>1e-6) throw new Error('Unlisted cost component: revise the slide table before publishing');
}
if (rows.length!==latest.included || data.cases.length!==latest.declared) throw new Error('Coverage mismatch');
if (new Set(rows.map(r=>r.week)).size!==rows.length || rows.some(r=>r.git_sha!==data.source_sha || r.evaluation_status!=='VERIFIED_CONDITIONAL_WEEKLY_EVALUATION')) throw new Error('Unverified or mixed results');
await fs.mkdir(buildDir,{recursive:false});
await fs.writeFile(path.join(buildDir,'comparison.json'),raw);
await fs.mkdir(path.join(buildDir,'validated'));
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const font='Noto Sans JP', navy='#202B58', teal='#159A8C';
const fmt=(v,d=0)=>Number(v).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
const included=rows.length, missing=data.cases.filter(c=>!c.included).map(c=>`${Number(c.week.slice(5,7))}月`).join('・');
const recoveredMonths=data.cases.filter(c=>c.state==='REPORTING_RECOVERED').map(c=>`${Number(c.week.slice(5,7))}月`).join('・');
const coverageLabel=latest.complete?'全12週の集計更新':'途中報告';
const sourceNote=`出典：${directory}/comparison.json\nSHA256 ${sha(raw)}\n計算固定版 ${data.source_sha}\nグラフはMWh小数6桁に表示用丸め。原値は同梱comparison.json。\n元の実行会計と物理検証を照合した週だけ収録。図表復旧と原FAILEDは別記録。`;
function text(s,value,x,y,w,h,size=25,color=navy,bold=false){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=value;a.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return a;}
function page(title,subtitle,takeaway,foot){const s=deck.slides.add();s.background.fill='#FFFFFF';text(s,title,54,25,1170,66,36,navy,true);text(s,subtitle,70,106,1145,64,24,'#59687B');text(s,takeaway,70,595,1145,54,25,teal,true);text(s,foot,70,659,1145,38,16,'#854A30');s.speakerNotes.textFrame.setText(`${sourceNote}\n${subtitle}\n${takeaway}\n${foot}`);return s;}
function table(s,values,widths,height=382,size=23){const t=s.tables.add({rows:values.length,columns:values[0].length,left:60,top:184,width:1160,height,values,columnWidths:widths});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const a=t.getCell(r,c);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';a.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':navy,bold:r===0};}t.borders.assign({style:'solid',fill:'#CBD3DD',width:1});}
let s=page(`9月進捗：月別代表週 ${included}／${latest.declared}週を検算`, '仮・正式用 ／ 渋21・22・23 ／ 2025年の各月から連続7日間', '各日の日付別ダイヤ・PVを使用し、車両と蓄電池の状態を引き継ぐ', `現版 ${data.source_sha.slice(0,8)} の${coverageLabel}。以降の旧24枚は履歴として非表示で保管。`);
table(s,[['確認項目','現在の結果'],['収録した代表週',rows.map(r=>Number(r.week.slice(5,7))+'月').join('、')],['残る対象',missing?`${missing}：回収・検算後に追加`:'全12週を収録'],['運行と評価期間','1週1,704便。営業7日間＋最終翌朝の充電・受電・費用'],['図表の注意',recoveredMonths?`${recoveredMonths}を原本から図表復旧。原FAILEDを保持、再求解なし`:'図表復旧による追加収録なし'],['結果の位置付け','検算済みの条件付き週次評価。統合最適性・正式研究採用は未証明']],[290,870],392,23);
for(const start of [1,7]){s=page(`月別の週次費用（${start}〜${start+5}月）`,'単位：万円。営業7日間と最終翌朝までの実行会計を集計','車両日費と、買電・燃料・契約超過モデル費を分けて読む','燃料は消費在庫の評価を含む。超過モデル費は実契約の請求額ではない。設備投資費は未計上。');
 const values=[['月／週開始','総費用','車両日費','買電費','燃料費','超過モデル費','CO₂費']];
 for(let m=start;m<start+6;m++){const r=rows.find(r=>Number(r.week.slice(5,7))===m);values.push(r?[`${m}月 ${r.week.slice(5)}`,...['total_cost','vehicle_usage_cost','electricity_cost','fuel_cost','contract_overage_cost','co2_cost'].map(k=>fmt(r[k]/10000,2))]:[`${m}月`,'未収録','—','—','—','—','—']);}
 table(s,values,[184,156,164,148,148,202,158],382,23);
}
s=page('代表週の購入電力量とPV供給可能量','単位：MWh。収録済みの各月1週を比較（営業7日間＋最終翌朝）','月平均・年間合計ではなく、それぞれの代表週の結果を示す','電費・燃費は一定。PVだけの因果効果や、冷暖房負荷を含む季節差とは解釈しない。');
let chart=s.charts.add('bar',{position:{left:70,top:184,width:1130,height:390},categories:rows.map(r=>Number(r.week.slice(5,7))+'月'),series:[{name:'購入電力量',values:rows.map(r=>Number((r.grid_import_kwh/1000).toFixed(6))),fill:'#287CB2'},{name:'PV供給可能量',values:rows.map(r=>Number((r.pv_generated_kwh/1000).toFixed(6))),fill:'#E4AD32'}],barOptions:{direction:'column',grouping:'clustered'},hasLegend:true,legend:{position:'bottom'},yAxis:{numberFormatCode:'0'},dataLabels:{showValue:false}});applyPresentationChartFont(chart,{fontFamily:font});
const lo=rows.reduce((a,b)=>a.total_cost<b.total_cost?a:b),hi=rows.reduce((a,b)=>a.total_cost>b.total_cost?a:b);
s=page('費用差の内訳',`収録${included}週の最高額 ${Number(hi.week.slice(5,7))}月と最低額 ${Number(lo.week.slice(5,7))}月の差。最適費用の順位ではない`, `週次費用差は ${fmt((hi.total_cost-lo.total_cost)/10000,2)}万円。費目と入力条件を併せて解釈する`, '差は観測した計画間の記述値。PVの効果・手法の削減効果・年間節約額を直接示さない。');
const keys=[['車両日費','vehicle_usage_cost'],['買電費','electricity_cost'],['燃料費（消費在庫の評価含む）','fuel_cost'],['契約超過モデル費','contract_overage_cost'],['CO₂費','co2_cost']];
table(s,[['費目',`${Number(hi.week.slice(5,7))}月 − ${Number(lo.week.slice(5,7))}月 [万円]`],...keys.map(([label,k])=>[label,fmt((hi[k]-lo[k])/10000,2)])],[680,480],382,25);
s=page('確認できたことと残る範囲','週次運行・経済性・月別の違いを、原本に対応する数値で説明する','図表の注意と、運行・会計の不整合を区別して結果を積み上げる','DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。独立した正式研究採用承認は別途必要。');
const dec=rows.find(r=>r.week.startsWith('2025-12'));
const bess=dec?.bess_terminal?.tsurumaki;
table(s,[['論点','結果・解釈の範囲'],['連続7日間',`${included}週で全便・SOC・電力収支・会計を確認。${missing?missing+'は未収録。':'全12週を収録。'}`],['週間費用',`${fmt(lo.total_cost/10000,2)}〜${fmt(hi.total_cost/10000,2)}万円。設備投資の採算は評価外。`],['BESSの在庫',bess?`12月：${fmt(bess.initial_soc_kwh)} → ${fmt(bess.terminal_soc_kwh,2)} kWh。初期在庫利用を含む。`:'初期・終端の在庫差を別記。継続可能な節約と混同しない。'],['季節の説明','電費一定・各月1週の条件差。空調負荷・季節全体の平均は未評価。'],['次の更新',missing?`${missing}の原本回収・検算後に同じ表を更新。旧版成功週は混ぜない。`:'全月の運用・費用・気象標準カーブを最終資料へ統合。']],[275,885],382,23);
const candidatePath=path.join(buildDir,'update-draft.pptx');await(await PresentationFile.exportPptx(deck)).save(candidatePath);
await finalizePresentation({workspaceDir:buildDir,candidatePath,finalPath:path.join(buildDir,'validated/update-slides.pptx'),explicitTotalSlideCount:6,requiredNativeTableOwnerSlides:[1,2,3,5,6],requiredNativeChartOwnerSlides:[4],materializeLiteralChartWorkbooks:true,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000',...[1,2,3,5,6].flatMap(n=>['--require-native-table-slide',String(n)])],fontPolicy:{basis:'reference',families:[font],referencePath:path.resolve('outcome/2026-09-19_urabe_terminology/monthly_progress_20260919_terms_v2.pptx'),referenceSha256:sha(await fs.readFile('outcome/2026-09-19_urabe_terminology/monthly_progress_20260919_terms_v2.pptx'))},verifyArtifactToolImport:true,receiptPath:path.join(buildDir,'validation.json')});
await fs.writeFile(path.join(buildDir,'evidence.json'),JSON.stringify({report_revision:latest.revision,comparison_sha256:sha(raw),source_sha:data.source_sha,included,declared:latest.declared,missing,generated_slides:6},null,2));
console.log(path.join(buildDir,'validated/update-slides.pptx'));
