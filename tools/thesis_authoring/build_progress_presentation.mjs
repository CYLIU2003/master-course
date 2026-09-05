// Local explanatory deck from the frozen-result reanalysis. No solver calls.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root = path.resolve(import.meta.dirname, '../..');
const runtime = 'C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES = path.join(runtime, 'node/node_modules');
const skill = 'C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.903.11726/skills/presentations';
const {Presentation, PresentationFile, FileBlob} = await import(pathToFileURL(path.join(runtime, 'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation, applyPresentationChartFont} = await import(pathToFileURL(path.join(skill, 'container_tools/artifact_tool_utils.mjs')).href);
const out = path.join(root, 'outcome/2026-09-05_research_progress');
const build = path.join(root, 'output/progress_presentation_build_20260905');
await fs.mkdir(build, {recursive:true});
const data = JSON.parse(await fs.readFile(path.join(out, 'analysis/summary.json'), 'utf8'));
const family = 'Meiryo';
const navy = '#18323D', green = '#147D76', purple = '#574CA0';
const presentation = Presentation.create({slideSize:{width:1280,height:720}});
const money = n => n.toLocaleString('ja-JP',{maximumFractionDigits:0});
function text(slide, value, left, top, width, height, size=28, color=navy, bold=false) {
  const shape = slide.shapes.add({geometry:'textbox', position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
  shape.text=value;
  shape.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'};
  return shape;
}
function page(title, note) {
  const slide=presentation.slides.add();
  slide.background.fill='#FFFFFF';
  text(slide,title,60,42,1160,80,42,navy,true);
  text(slide,`${presentation.slides.items.length}　2026年9月5日　凍結実験 bb0c005`,60,672,1160,30,17,'#536772');
  slide.speakerNotes.textFrame.setText(note);
  return slide;
}
function table(slide, values, top=175, height=310, widths=[500,300,300]) {
  const tab=slide.tables.add({rows:values.length,columns:values[0].length,left:60,top,width:1160,height,values,columnWidths:widths});
  for(let r=0;r<values.length;r++) for(let c=0;c<values[0].length;c++) {
    const cell=tab.getCell(r,c);
    cell.fill=r===0?navy:(r%2?'#F2F6F7':'#FFFFFF');
    cell.text.style={typeface:family,fontSize:24,color:r===0?'#FFFFFF':navy,bold:r===0};
  }
  tab.borders.assign({style:'solid',fill:'#DAE3E7',width:1});
  return tab;
}
const source='資料源: outcome/2026-09-05_research_progress/analysis/summary.json と manifest.json。凍結実行 bb0c005、分析時HEAD c0b82ae3。';
let s=page('PVと混成バス運用の研究進捗', source+' 本日は新しい最適化結果ではなく、既存の高PV・低PV2計画を、営業距離・担当便・充電の観点で分析し直した結果を説明します。運用とはモデル上の計算であり実車実証ではありません。');
text(s,'BEV／ICEの配車・充電計画',60,195,1160,88,50,navy,true);
text(s,'既存結果の説明分析と、次の手法検証',60,304,1160,70,34,green);
text(s,'電力システム研究室　劉 承洋',60,475,1160,50,28);
text(s,'モデル上の264便運行を確認済み。手法の比較実験は準備段階。',60,564,1160,60,26);

s=page('研究の問いと二段階方式', '出典: docs/thesis/authoring_v1/03_mathematical_formulation.md。Stage 1は車両と便接続に加え時刻別エネルギーの緩和表現を扱います。Stage 2では配車を固定して具体的な電力運用を解きます。候補選択後のRollingでも配車は固定です。太陽光が多くても、営業所にいない時間にはバスへ充電できません。まずこの時間の結び付きが研究の難しさだと説明します。');
text(s,'全便を守り、PV条件に応じた配車と充電を計画する',60,140,1160,55,30,green,true);
table(s,[['段階','決めること'],['Stage 1','充電の見込みを含めて配車候補を作る'],['Stage 2','配車を固定し、充電・PV・BESSを計画'],['候補選択','評価した有限候補から採用案を選ぶ'],['毎時のRolling','配車を固定して残りの電力計画を更新']],215,315,[280,880]);
text(s,'制約の例：全便を1台ずつ担当、便間接続、SOC、充電器・受電上限',60,564,1160,72,25);

s=page('固定運行・高PV／低PVの確認済み結果', source+' docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json。運行はどちらも2025年8月5日のWEEKDAYです。低PVは8月10日由来のPV曲線を適用します。日曜の実車運行や一般の天候効果は評価していません。両方で物理検算と24回のRollingおよび費用会計を確認しました。Stage 1のgapを最終費用の誤差率と解釈しないでください。');
table(s,[['指標','高PV','低PV'],['全便担当','264 / 264','264 / 264'],['使用BEV / ICE','28 / 4 台','21 / 11 台'],['BEV / ICE担当便','199 / 65 便','91 / 173 便'],['Rolling','24 / 24 回','24 / 24 回'],['Stage 1認証gap','9.52%','1.66%']],150,365,[540,310,310]);
text(s,'同じ平日運行に2種類のPV曲線を適用した、モデル内の比較。',60,551,1160,50,25);
text(s,'Stage 1 gapは、その段階の目的に対する値。最終評価額の誤差率ではない。',60,607,1160,50,24,'#7D4729');

s=page('BEVの担当量を距離と時間で捉える', source+' 営業距離のみで回送は除きます。距離は停留所列から計算したPrepared入力値で、実走行距離の計測値ではありません。便数割合より距離・時間割合が小さいため、便数だけを示すとBEVの運行量を大きく見せる可能性があります。これで短い便を選んだ理由まで証明したわけではありません。');
const bev=data.dispatch.filter(r=>r.powertrain==='BEV');
let chart=s.charts.add('bar',{position:{left:60,top:155,width:1160,height:395},categories:['便数割合','営業距離割合','営業時間割合'],series:bev.map((r,i)=>({name:i===0?'高PV':'低PV',values:[r.trip_share,r.service_distance_share,r.service_time_share].map(n=>Number(n.toFixed(6))),fill:i===0?green:purple})),barOptions:{direction:'column',grouping:'clustered',gapWidth:90},hasLegend:true,legend:{position:'bottom',textStyle:{typeface:family,fontSize:23}},yAxis:{min:0,max:1,numberFormatCode:'0%',textStyle:{typeface:family,fontSize:23}},xAxis:{textStyle:{typeface:family,fontSize:23}},dataLabels:{showValue:false}});
applyPresentationChartFont(chart,{fontFamily:family});
text(s,'BEV営業距離比：高PV 72.8% ／ 低PV 29.7%',60,561,1160,50,30,green,true);
text(s,'距離は停留所列由来の入力値。営業便を対象とし、回送距離を含まない。',60,614,1160,44,23);

s=page('108便のICE担当が高PVではBEVに変わる', source+' 詳細はanalysis/trip_powertrain_changes.csv。渋21/22/23は16 route IDをまとめた3つの系統群です。低PVでBEVだった91便は高PVでもBEVで、逆方向の置換はありません。営業便の位置はanalysis/figures/01_dispatch_by_route.pngで確認できます。高PV条件から低PV条件へ時間が進んだという意味ではなく、同じ便を2計画で照合した比較です。');
table(s,[['系統群','両方BEV','低PV ICE → 高PV BEV','両方ICE'],['渋21','42','0','0'],['渋22','32','78','0'],['渋23','17','30','65'],['合計','91','108','65']],170,330,[270,240,410,240]);
text(s,'置換は渋22の78便と渋23の30便に集中',60,541,1160,54,31,green,true);
text(s,'この2計画の差として確認。一般の天候効果や置換原因の証明は今後の課題。',60,605,1160,52,24);

s=page('共通車両使用費を除いた評価額の内訳', source+' 費用の正本はRollingのexecuted_day_accounting.json。高PV合計660983.7838045002円、低PV698598.6286431606円。両方32台のため64万円の車両使用費が共通ですが、車両費はモデル全体では決定変数に依存し、常に消せる定数ではありません。差37614.8448386603円の約87.9%は燃料費です。RAINのday-ahead候補評価698296.465283954円は別の費用基準です。設備投資、運転士、保守等を含む採算評価ではありません。');
chart=s.charts.add('bar',{position:{left:60,top:160,width:745,height:390},categories:['高PV','低PV'],series:[['燃料費','fuel_jpy','#AE6635'],['系統電力費','electricity_jpy','#574CA0'],['CO₂費用','co2_jpy','#87989D']].map(([name,key,fill])=>({name,values:data.costs.map(r=>Number(r[key].toFixed(2))),fill})),barOptions:{direction:'column',grouping:'stacked'},hasLegend:true,legend:{position:'bottom',textStyle:{typeface:family,fontSize:23}},yAxis:{title:'円',numberFormatCode:'#,##0',textStyle:{typeface:family,fontSize:22}},xAxis:{textStyle:{typeface:family,fontSize:24}},dataLabels:{showValue:false}});
applyPresentationChartFont(chart,{fontFamily:family});
text(s,'車両使用費以外',850,180,355,50,28);
text(s,`高PV ${money(data.costs[0].excluding_vehicle_usage_jpy)}円\n低PV ${money(data.costs[1].excluding_vehicle_usage_jpy)}円`,850,245,355,130,30,green,true);
text(s,'差額の87.9%は燃料費',850,421,355,85,26);
text(s,'両計画の車両使用費は64万円。全体評価額は高PV 660,984円／低PV 698,599円。',60,562,1160,56,24);
text(s,'費用の範囲：モデル評価額。設備投資・運転士費などを含む採算評価は未実施。',60,619,1160,42,22,'#7D4729');

s=page('PV抑制時の状態と、説明できる限界', source+' analysis/executed_slots.csvから計算。高PVの抑制3373.22 kWhのうち2531.995 kWh、75.06%は正の充電電力がない枠で生じます。抑制枠末のBESS SOCは最大3644.33 kWhで上限4800 kWhに達していません。これらは同時に観測した状態であり、原因の比率ではありません。帰庫、必要電力量、終端SOC、運用モード、同費用の別解を切り分けるには別の分析が必要です。全ポート使用数は電力1e-6 kW超で定義しています。');
table(s,[['高PVの抑制枠での観測','結果'],['PV抑制量','3,373.22 kWh'],['未充電枠で発生した抑制の割合','75.06%'],['10ポート全使用と重なる抑制','0 kWh'],['BESS枠末SOCが上限と重なる抑制','0 kWh']],170,330,[790,370]);
text(s,'「BESSが満杯」「充電器が満杯」だけでは説明できない',60,540,1160,55,30,green,true);
text(s,'同時に観測した状態。原因の割合、充電待ち時間、設備の最小必要数は未識別。',60,604,1160,55,24);

s=page('次の手法検証と比較の定義', '出典: docs/research/november_2026/signoff/02_small_oracle_contract.md と scripts/audit_small_integrated_weather_milp.py。小規模実験には既存の承認テンプレートがあり未署名です。既存M0は全ICE統合参照、M1は混成Phase3でPV/BESSなし、M2は現行Phase3、M3は統合scalar参照です。これは既定配車と先着順充電の比較ではありません。単純方式のルールと評価対象を結果を見る前に決める必要があります。');
text(s,'1. RAIN 8・12・24便の統合参照比較',60,161,1160,62,34,green,true);
text(s,'同一入力で二段階方式と統合参照を評価。\n呼称は「Phase 3整合小規模解とscalar統合参照解の評価額差」。\n結果は未取得。承認済み条件と時間上限に従って実行する。',60,235,1160,150,27);
text(s,'2. 単純方式のbaselineを定義',60,411,1160,60,34,green,true);
text(s,'既定配車と先着順充電の規則を固定する。\n既存M0〜M3は別の比較。PV/BESSを同時に変更すると、\n配車・充電のどちらが効いたか分離できない。',60,480,1160,150,27);

s=page('今回の進捗と次回までの説明課題', source+' 今回は既存の凍結結果を再集計し、研究の説明力を増やしました。新たな手法性能や一般化を証明したわけではありません。本人には、研究の入力と出力、全便を守ることと最安を証明することの差、小規模比較が期待通りでなかった場合に分かることを、自分の言葉で説明していただきます。次の判断は小規模比較の承認とbaseline定義です。');
text(s,'進捗：便数に加えて、距離・置換箇所・充電状態を確認',60,151,1160,100,33,green,true);
text(s,'残る中心課題：単純方式に対する利点と、選択結果の安定性',60,267,1160,92,31);
text(s,'次回の説明課題',60,395,1160,54,32,navy,true);
text(s,'研究は何を入力し、何を決めるか。\n実行可能な計画と、最も安い計画はどう違うか。\n統合参照との差が大きかったら、何が分かるか。',60,460,1160,158,28);

const candidate=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(candidate);
const finalPath=path.join(out,'research_progress_20260905.pptx');
const finalResult=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath,
  pythonExecutable:path.join(runtime,'python/python.exe'),
  integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[2,3,5,7].flatMap(n=>['--require-native-table-slide',String(n)])],
  explicitTotalSlideCount:9, requiredNativeTableOwnerSlides:[2,3,5,7], requiredNativeChartOwnerSlides:[4,6],
  materializeLiteralChartWorkbooks:true,
  fontPolicy:{basis:'design',families:[family]}, verifyArtifactToolImport:true,
  receiptPath:path.join(build,'validation.json')});
console.log(JSON.stringify(finalResult));
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<finalDeck.slides.items.length;i++) {
  const blob=await finalDeck.export({slide:finalDeck.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(finalPath);
