import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'../..');
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {PresentationFile,FileBlob}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const out=path.join(root,'outcome/2026-09-07_urabe_progress_review');
const build=path.join(root,'tmp/progress_urabe_review_20260907/final');
await fs.mkdir(build,{recursive:true});
const source=path.join(root,'outcome/2026-09-06_speaker_notes/progress_differences_integrated_20260906.pptx');
const bytes=await fs.readFile(source);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const data=JSON.parse(await fs.readFile(path.join(out,'analysis/review_data.json'),'utf8'));
for(const [file,hash] of Object.entries(data.source_sha256)){
  if(sha(await fs.readFile(path.join(root,file)))!==hash)throw new Error(`Source changed: ${file}`);
}
const summary=JSON.parse(await fs.readFile(path.join(root,'docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json'),'utf8'));
const deck=await PresentationFile.importPptx(await FileBlob.load(source));
const font='Meiryo',navy='#202B58',muted='#59687B',teal='#159A8C',rain='#6B54A3';
const colors=['#159A8C','#3978BF','#E49336','#BA4F60','#8A94A4'];
const tables=[],charts=[],pages=[];
const names=['SUNNY','RAIN'];
const f=(x,n=1)=>Number(x).toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n});
const terms={SUNNY:'高PV（SUNNY）',RAIN:'低PV（RAIN）'};
const genericSource='数値：実験SHA bb0c005のaccepted Rolling実行区間。最終費用：rolling_hourly_chain/executed_day_accounting.json。出典ファイルとSHA-256：analysis/review_data.json。2026-09-07は再集計のみで新規solveなし。';
const hu='Hu, X., Li, H., Xie, C. (2025). Optimal charging scheduling of an electric bus fleet with photovoltaic-storage-charging stations. Applied Energy 390, 125714. https://doi.org/10.1016/j.apenergy.2025.125714 手元原本 No63.pdf。';
const zhou='Zhou, X., An, K., Schmöcker, J.-D. (2025). Optimization of charging and discharging schedules for battery electric buses under the V2G environment. Transportmetrica B: Transport Dynamics 13(1), 2506689. https://doi.org/10.1080/21680566.2025.2506689 手元原本 No06.pdf。';
function text(s,value,x,y,w,h,size=25,color=navy,bold=false){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=value;t.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return t;
}
function page(title,subtitle,takeaway,caveat,notes=''){
 const s=deck.slides.add();s.background.fill='#FFFFFF';
 const n=deck.slides.items.length;
 text(s,title,44,25,1192,64,36,navy,true);
 text(s,subtitle,60,104,1160,56,23,muted);
 text(s,takeaway,60,597,1160,52,25,teal,true);
 text(s,caveat,60,653,1120,38,17,'#7E4D36');
 text(s,`補足 ${n-18}`,1170,683,100,28,13,muted);
 s.speakerNotes.textFrame.setText(`${notes}\n\n${genericSource}`);
 pages.push({slide:n,title,subtitle,takeaway,caveat,notes});return s;
}
function table(s,values,widths,{top=179,height=391,size=23}={}){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:60,top,width:1160,height,values,columnWidths:widths});
 values.forEach((row,r)=>row.forEach((_,c)=>{
  const cell=t.getCell(r,c);cell.fill=r===0?navy:(r%2?'#F1F5F8':'#FFFFFF');
  cell.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':navy,bold:r===0};
 }));t.borders.assign({style:'solid',fill:'#DDE4EB',width:1});
 tables.push(deck.slides.items.indexOf(s)+1);return t;
}
function line(s,title,series,{x=65,y=179,w=1150,h=390,max=1000,min=0,xmax=24,unit='kW'}={}){
 const chart=s.charts.add('scatter',{position:{left:x,top:y,width:w,height:h},title,
  titleTextStyle:{typeface:font,fontSize:23,bold:true,fill:navy},
  series:series.map((row,i)=>({name:row.name,xValues:row.x??row.values.map((_,j)=>j/4),values:row.values.map(v=>Number(v.toFixed(6))),
   line:{fill:row.color??colors[i],width:2.3,style:'solid'},marker:{symbol:'none'}})),
  scatterOptions:{style:'line'},hasLegend:true,legend:{position:'bottom',overlay:false,textStyle:{typeface:font,fontSize:17}},
  xAxis:{min:0,max:xmax,majorUnit:xmax===24?6:4,title:'時刻 [h]',numberFormatCode:'0',textStyle:{typeface:font,fontSize:17},majorGridlines:null},
  yAxis:{min,max,title:unit,numberFormatCode:'0',textStyle:{typeface:font,fontSize:17},majorGridlines:{fill:'#DFE4EA',width:1}},
  chartFill:'#FFFFFF',plotAreaFill:'#FFFFFF'});
 applyPresentationChartFont(chart,{fontFamily:font});charts.push(deck.slides.items.indexOf(s)+1);return chart;
}
function paired(s,fields,max,unit='kW'){
 names.forEach((name,i)=>line(s,terms[name],fields.map(([field,label,color])=>({name:label,color,
   // Duplicate each boundary to represent a piecewise-constant 15-minute power.
   x:data.scenarios[name].slots.flatMap((_,j)=>[j/4,(j+1)/4]),
   values:data.scenarios[name].slots.flatMap(row=>[row[field]*4,row[field]*4])})),{x:60+i*590,w:570,max,unit}));
}
// Shorten the existing takeaway that ran beyond its intended one-line region.
 const old='高PV：抑制が発生。原因の特定は今後の課題　／　低PV：ほぼ全量を使い、不足分を系統から補う';
const matches=deck.slides.getItem(12).shapes.items.filter(s=>String(s.text).includes(old));
if(matches.length===1)matches[0].text.replace(old,'高PVでは抑制が発生。低PVではほぼ全量を利用し、不足分を系統から補う');
deck.resolve('sh/pgbul0fu').text='入力20～90% ※';
deck.resolve('sh/ml07i9sv').text='※ SOC上限90%は保存実行へ反映されていない。補足17で不一致を報告。';
deck.resolve('sh/547mhg3m').text='保存済みの検証結果と、追加確認で見つかった限界';
deck.resolve('sh/18vup4bm').text='旧検証24回通過';
deck.resolve('sh/idkv6pc3').text='旧検証の範囲';
deck.resolve('sh/87e10r6p').text='入力上限90%との一致は\n追加確認で不成立';
deck.resolve('sh/l4nipcny').text='検証ログのPASSだけでは、入力した全条件を満たす証明にならない。';
deck.resolve('tb/bilk7uh4').getCell(1,0).value='同じ264便を両条件で担当\nSOC上限に不一致を追加発見';
deck.resolve('sh/ytkf2h8j').text='現時点の結論：保存結果は診断用。SOC上限の修正・再実験が必要';
deck.resolve('sh/1c7e50ni').text='最優先はSOC上限の契約修正と再検証。下表の比較はその後に行う';
text(deck.slides.getItem(0),'9月7日 追記：SOC上限に不一致を発見。数値は診断用、研究結論には未使用',60,594,1160,65,24,'#A23D37',true);

{
 const s=page('補足資料：先生の質問との対応','日合計の説明を、時間別の動きと計算根拠までつなげる',
  '新しい計算結果を増やさず、保存済み結果から説明の不足を補った',
  'Slackで確認した研究上の指摘を要約。先生の承認・納得を得たという意味ではない。',
  '対応するSlack発言とリンクは同梱READMEの指摘対応表を参照。6月の旧設定と8月29日の固定入力を混ぜない。');
 table(s,[['確認したい点','本編での状態','補足の回答'],['何を直したか・用語','8–9枚目に差分あり','方法・用語の定義'],['晴雨の電力と燃料','12–14枚目は日合計中心','15分電力・配車距離・費用'],['充電時間と台数のピーク','時間別の根拠が不足','正電力セッション数・車両例'],['BESSの始終端と上下限','日量フロー中心','残量軌跡と始終端の数値'],['台数費用・計算時間','設定値のみでは不十分','費用式・実測時間・残る検証']],[330,390,440]);
}
{
 const s=page('先行文献から取り入れた図表の構成','論文の図を貼るのではなく、本研究の数値を同じ観点で示す',
  '残量・電力・運行・費用・計算時間を対応させる',
  '文献の条件・費用範囲・通貨は本研究と異なる。直接の性能比較には使わない。',hu+'\nFig.6–9, Table 5–6。\n'+zhou+'\nTable 5、Fig.4–5。');
 table(s,[['原本で確認した例','図表の役割','今回の資料'],['Huら (2025) Fig.6','SOCと充電時刻を対応','車両例の残量・充電電力'],['Huら (2025) Fig.8–9','蓄電池と供給量を時間比較','BESS残量・15分電力'],['Huら (2025) Table 5','費用と電力量を分解','最終台帳に一致する内訳表'],['Zhouら (2025) Table 5','費用と計算時間を併記','設定時間と実測時間を区別']],[375,380,405]);
}
{
 const s=page('PV発電の行き先：15分ごとの比較','同一の縦軸。電力 [kW] = 各15分枠の電力量 [kWh] ÷ 0.25 h',
  '高PVの抑制は日中に発生し、低PVの抑制はほぼゼロ',
  '営業所・時刻別のsolver-nativeフロー。抑制原因の反実仮想による分解は未実施。',hu+'\nFig.9のエネルギー分解を参考に、累積量ではなく15分平均電力で表示。');
 paired(s,[['pv_to_bus_kwh','バスへ',colors[0]],['pv_to_bess_kwh','BESSへ',colors[1]],['pv_curtailed_kwh','抑制',colors[2]]],1000);
}
{
 const s=page('BEV充電電力と系統購入の時間分布','各供給元の電力合計が、バスへの充電器入力となる',
  '高PVは系統購入ゼロ。低PVの系統購入は合計130.85 kWh',
  '折れ線は15分平均の段差表示。車両ごとの電源割当は比例配分であり、ここでは使わない。',hu+'\nFig.7、9を参考。配車を固定したaccepted Rollingの実行区間のみ。');
 paired(s,[['pv_to_bus_kwh','PV',colors[0]],['bess_to_bus_kwh','BESS',colors[1]],['grid_to_bus_kwh','系統',colors[2]]],1000);
}
{
 const s=page('BESS残量：両条件とも3,000 kWhへ戻る','設備容量6,000 kWh、許容範囲1,200～4,800 kWh',
  '初期エネルギーの使い切りで、当日の費用を下げてはいない',
  '残量は各15分枠の終端値。高PVの最小値は数値誤差を丸めて1,200 kWh。',hu+'\nFig.8を参考。始終端は最終台帳と照合。');
 line(s,'BESSエネルギー残量',[
  ...names.map((n,i)=>({name:terms[n],values:[3000,...data.scenarios[n].slots.map(r=>r.bess_soc_end_kwh)],color:i?rain:teal})),
  {name:'下限',values:[1200,1200],x:[0,24],color:'#AAB2BC'},
  {name:'上限',values:[4800,4800],x:[0,24],color:'#7D8795'}],{y:164,h:290,max:6000,unit:'kWh'});
 table(s,[['条件','開始','最小','最大','終了 / 差'],...names.map(n=>[terms[n],'3,000',f(data.scenarios[n].bess_min_kwh),f(data.scenarios[n].bess_max_kwh),'3,000 / 0 kWh'])],[260,195,210,210,285],{top:470,height:111,size:20});
}
{
 const s=page('BESSの充電・放電電力','両方向を正値で表示。SOCは充電効率95%・放電効率95%で更新',
  '高PVでは日中に蓄え、バスの充電時に放電する',
  '充電電力と放電電力の差だけではSOC差にならない。両方向の効率を含める。',hu+'\nFig.8–9。状態式 S[t+1]=S[t]+0.95×Pcharge×0.25−Pdischarge×0.25/0.95。');
 paired(s,[['pv_to_bess_kwh','PVから充電',colors[0]],['bess_to_bus_kwh','バスへ放電',colors[1]]],900);
}
{
 const s=page('同時充電台数と、充電に必要な時間','15分単位。正の充電電力を持つ車両数を集計',
  '「同時に10台」と「1台が短時間で満充電」は別の数量',
  '台数は電力>1e−6 kWのセッション数。接続中台数・待ち台数・必要最小ポート数ではない。',
  '6/17のSlack質問への回答。エネルギー188.4 kWh / 90 kW = 2.0933 hは無損失かつ連続定格の理論最短。設備競合・停車時間・実際の効率を入れると長くなる。');
 line(s,'正の電力を持つ充電セッション',names.map((n,i)=>({name:terms[n],color:i?rain:teal,
  x:data.scenarios[n].slots.flatMap((_,j)=>[j/4,(j+1)/4]),values:data.scenarios[n].slots.flatMap(r=>[r.charging_sessions_gt_1e_minus6_kw,r.charging_sessions_gt_1e_minus6_kw])})),{y:171,h:290,max:10,unit:'台'});
 text(s,'20%から80%まで：314 × (0.80−0.20) = 188.4 kWh',80,478,1110,45,26,navy,true);
 text(s,'90 kWで連続充電しても、無損失の理論最短は2.09時間',80,527,1110,45,26,navy);
}
{
 const s=page('車両別の充電電力：最大充電量の車両例','各条件で一日の充電器入力が最大の1台を選ぶ。同一車両・平均車両の比較ではない',
  '高PVの例は4.00時間、低PVの例は3.25時間に分けて充電',
  '時間は正の充電電力がある15分枠の合計。連続した充電時間ではない。',hu+'\nFig.6(b)を参考。例の選定規則と完全な車両ID、担当便はreview_data.json。');
 names.forEach((n,i)=>{const e=data.scenarios[n].example;
  line(s,`${terms[n]}  ${f(e.charging_kw.reduce((a,b)=>a+b,0)/4)} kWh`,[{name:'充電器入力',color:i?rain:teal,
   x:e.charging_kw.flatMap((_,j)=>[j/4,(j+1)/4]),values:e.charging_kw.flatMap(p=>[p,p])}],{x:60+590*i,w:570,max:90});
 });
}
{
 const s=page('同じ車両例のSOC軌跡','前ページの各車両を追跡。上昇は充電、低下はモデル上の運行消費',
  '高PVの例は最大93.37%。入力上限90%との不一致を検出',
  'SOCは15分枠の開始値と24時終端値。上限線は入力指定値。保存モデルは容量100%を上限とする。',hu+'\nFig.6(a)を参考。各例は最大充電量という規則で選択。高PVで入力maxSocとの不一致を発見したため診断用に限定。');
 names.forEach((n,i)=>line(s,`${terms[n]}  ${data.scenarios[n].example.trips.length}便担当`,[
  {name:'SOC',values:data.scenarios[n].example.soc_kwh.map(v=>v/314*100),color:i?rain:teal},
  {name:'下限20%',x:[0,24],values:[20,20],color:'#AAB2BC'},
  {name:'入力上限90%',x:[0,24],values:[90,90],color:'#A23D37'}],{x:60+i*590,w:570,max:100,unit:'%'}));
}
{
 const s=page('配車と燃料：便数だけでなく距離で確認','営業便の総距離は両条件とも2,136.74 km。担当車種だけが変わる',
  '高PVではBEVが担う営業距離が増え、燃料消費が減った',
  '営業距離は回送を除く。燃料は回送等を含む最終台帳であり、営業距離だけから再計算しない。',zhou+'\nFig.4の費用分解を参考。凍結された2条件の記述比較であり、一般的な天候効果の証明ではない。');
 table(s,[['指標','高PV','低PV'],['稼働台数 BEV / ICE','28 / 4','21 / 11'],['担当便 BEV / ICE','199 / 65','91 / 173'],['BEV営業距離 [km]',f(data.scenarios.SUNNY.dispatch[0].service_distance_km,2),f(data.scenarios.RAIN.dispatch[0].service_distance_km,2)],['ICE営業距離 [km]',f(data.scenarios.SUNNY.dispatch[1].service_distance_km,2),f(data.scenarios.RAIN.dispatch[1].service_distance_km,2)],['燃料消費 [L]',f(summary.scenarios.SUNNY.executed_day_fuel_liters,3),f(summary.scenarios.RAIN.executed_day_fuel_liters,3)]],[540,310,310]);
}
{
 const a=data.scenarios.SUNNY.accounting.cost_breakdown,b=data.scenarios.RAIN.accounting.cost_breakdown;
 const s=page('使用台数費用を含む、一日の評価額','C使用 = 20,000 JPY/台日 × 使用台数。係数は固定、使用台数は配車で決まる',
  `使用台数は両条件32台。差額${f(b.total_cost-a.total_cost,2)}円の主因は燃料費`,
  '燃料は未補給分の在庫評価を含む。現金支払額・総保有費用とは異なる。',hu+'\nTable 5、'+zhou+'\nFig.4を参考。需要料金・PV/BESS限界費用は設定0、設備費・劣化費・運転士費を含まない。');
 const fields=[['車両使用費','vehicle_usage_cost'],['燃料費','fuel_cost'],['系統電気料金','electricity_cost'],['CO₂費','co2_cost'],['合計','total_cost']];
 table(s,[['項目 [JPY/日]','高PV','低PV','低PV − 高PV'],...fields.map(([label,k])=>[label,f(a[k],2),f(b[k],2),f(b[k]-a[k],2)])],[390,255,255,260]);
}
{
 const s=page('計算時間：設定上限と実測を分ける','Intel Core i7-12700、Gurobi 13.0.1、1 thread、seed 42',
  '毎時処理は配車を固定し、残り一日の充電・電力運用だけを再計算',
  '実測は保存フィールドの範囲。候補生成等を含む全工程のwall timeや速度改善率とは異なる。',zhou+'\nTable 5を参考。solve_time_secondsはStage 1と採用候補Stage 2の和に対応し、22候補全体の時間ではない。');
 table(s,[['時間項目 [秒]','上限設定','高PV 実測','低PV 実測'],['Stage 1','435',f(summary.scenarios.SUNNY.stage1_runtime_seconds,2),f(summary.scenarios.RAIN.stage1_runtime_seconds,2)],['採用候補のStage 2','30 / 候補',f(summary.scenarios.SUNNY.stage2_runtime_seconds,2),f(summary.scenarios.RAIN.stage2_runtime_seconds,2)],['保存solve_time_seconds','全体要求585',f(summary.scenarios.SUNNY.solve_time_seconds,2),f(summary.scenarios.RAIN.solve_time_seconds,2)],['毎時処理24回のelapsed合計','solver 30 / 回',f(data.scenarios.SUNNY.rolling_elapsed_sum_seconds,2),f(data.scenarios.RAIN.rolling_elapsed_sum_seconds,2)],['毎時処理elapsed最大','solver 30 / 回',f(Math.max(...data.scenarios.SUNNY.rolling_elapsed_seconds),2),f(Math.max(...data.scenarios.RAIN.rolling_elapsed_seconds),2)]],[490,240,215,215],{size:21});
}
{
 const s=page('毎時再計算の処理時間：24回すべてを表示','elapsed_secondsはsolverだけでなく、その毎時処理に含まれる処理を計測',
  '今回の固定2条件では、各回の処理は約3～5.4秒だった',
  '単発の保存実行における値。分布の安定性・旧方式への高速化率・実運用応答保証は未検証。',
  'rolling_chain_summary.json steps[].elapsed_seconds。折れ線は各正時の実測点を接続し、点間の値を測定したという意味ではない。');
 const c=line(s,'毎時処理の実測時間',names.map((n,i)=>({name:terms[n],values:data.scenarios[n].rolling_elapsed_seconds,x:Array.from({length:24},(_,j)=>j),color:i?rain:teal})),{max:6,unit:'秒'});
}
{
 const s=page('Stage 1の下界と、毎時更新の範囲','日量の楽観的な見積もりと、時刻別の実行可能な計画を区別',
  'Stage 1のgapは代理目的のgap。最終費用全体の最適性を表さない',
  '初期・終端BESSは今回3,000 kWh。7月資料の旧設定300 kWhを転記しない。',
  '充電量下界はエネルギー収支から導く。走行・回送と終端要求を含め、時間と設備の競合を緩和する。docs/guides/professor_review.md §3.1–3.2に用語説明、実験の数値設定は凍結bundleに従う。');
 text(s,'最低充電器入力 = max(走行・回送消費 + 終端要求 − 初期残量, 0) / 充電効率',65,182,1150,75,25,navy,true);
 text(s,'初期BESSの持ち出し可能量 = max(3,000 − 3,000, 0) × 0.95 = 0 kWh',65,267,1150,65,25,navy,true);
 table(s,[['計算','決定するもの','確認上の限界'],['Stage 1','便割当・日量の費用代理','充電時刻と設備競合を省略'],['Stage 2','割当固定の充電・電力','候補外の配車は探索しない'],['毎時Rolling','残り一日の電力計画','配車固定、先頭60分のみ実行']],[230,475,455],{top:354,height:223,size:22});
}
{
 const s=page('先行文献の性能表と、本研究の残る比較','Zhouら (2025) Table 5の一部を再構成。論文内の50便・418便の比較',
  '費用と時間を併記する形式を採用し、本研究のbaseline比較は未実施と明示',
  'CNYとJPY、V2G、費用範囲、計算機が異なる。本研究と直接比較して速い・安いとは言えない。',zhou+'\nPDF p.14、印刷頁13 Table 5。200/418便Gurobiは6時間以内に実行可能解を得ていない。');
 table(s,[['規模','手法','費用 [CNY]','時間 [秒]'],['50便','Gurobi','4,599.4','617.6'],['50便','ALNS-SA','4,630.9','14.7'],['418便','Gurobi','実行可能解なし','6時間制限'],['418便','ALNS-SA','8,758.3','202.3'],['本研究 264便','同条件baseline比較','未実施','未実施']],[210,335,330,285],{size:23});
}
{
 const s=page('発表で示せる結論と、残る研究上の確認','説明資料の補強と、研究としての採択・最適性・発表承認は別の段階',
  '保存された2条件の結果を示し、SOC上限の不一致を優先して修正する',
  'teacher_release_status = BLOCKED。未検証項目を解決済みとして発表しない。',
  '既存authoring manifestのうちscripts/build_thesis_weather_result_package.pyの過去ハッシュ不一致が未解消。今回のraw bundle検証は合格だが旧manifest全体の合格を意味しない。CURRENT_RESEARCH_RELEASE_BLOCKERS.md参照。');
 table(s,[['項目','今回示すもの','残る確認'],['物理・会計','台帳一致、SOC上限に不一致','上限修正と新しい凍結実験'],['最適性','22候補内の選択結果','統合全体の最適性・候補安定性'],['計算時間','保存された実測値','同条件baseline・複数回測定'],['PV抑制','いつ・どれだけ発生したか','配車や設備条件の因果分解'],['研究公開・承認','実験SHAと出典を明示','来歴の残件・独立レビュー・承認']],[280,435,445],{size:23});
}
{
 const a=data.scenarios.SUNNY.prepared_soc_upper_audit,b=data.scenarios.RAIN.prepared_soc_upper_audit;
 const s=page('追加確認：BEVの入力SOC上限と実行結果が不一致',
  'P1：入力maxSoc=0.90に対し、実験SHA bb0c005のStage 2は容量100%を上限としていた',
  '上限の契約を直し、独立検証を追加してから、クリーンな新SHAで再実験する',
  '図表のためにSOC値を切り詰めたり、入力上限を100%に読み替えたりしていない。',
  '根拠：prepared maxSoc=0.9、hourly_solver_result.jsonのvehicle_soc_kwh_by_vehicle_slot。BEV軌跡はslot開始値。凍結solver_adapter.pyのstage2.addVar ub=capとterminal_soc_expr<=cap。高PV12 vehicle-slot点、3台で超過。モデル修正・再実験は本資料更新の範囲外で未実施。');
 table(s,[['確認項目','高PV','低PV'],['Preparedで指定したSOC上限','90%','90%'],['保存された最大SOC',`${f(a.maximum_soc_percent,3)}%`,`${f(b.maximum_soc_percent,3)}%`],['90%超過の車両数',String(a.affected_vehicle_count),String(b.affected_vehicle_count)],['90%超過の車両×15分境界点',String(a.exceedance_count),String(b.exceedance_count)],['今回の扱い','診断用、研究結論には未使用','比較ペアとして診断用']],[545,310,305],{size:22});
}
for(const s of deck.slides.items){
 text(s,'DIAGNOSTIC  /  NOT USED FOR RESEARCH CONCLUSIONS  /  SOC入力上限の不一致は補足17',60,700,1160,18,12,'#A23D37');
 s.speakerNotes.append('\n【2026-09-07訂正】入力SOC上限90%との不一致を高PVの3台・12境界点で検出。旧検証PASSはその上限への適合を保証しない。この資料の数値はDIAGNOSTIC、NOT USED FOR RESEARCH CONCLUSIONS。モデル修正と新SHAでの再実験は未実施。補足17を参照。図の数値はExcel互換のため小数6桁に丸め、元の精度はanalysis/review_data.jsonに保持。');
}

await fs.writeFile(path.join(build,'supplement_pages.json'),JSON.stringify(pages,null,2));
const candidatePath=path.join(build,'candidate.pptx');
await(await PresentationFile.exportPptx(deck)).save(candidatePath);
const finalPath=path.join(out,process.argv[2]??'progress_with_urabe_supplement_20260907_final.pptx');
await finalizePresentation({workspaceDir:root,candidatePath,finalPath,
 explicitTotalSlideCount:deck.slides.items.length,requiredNativeTableOwnerSlides:[...new Set(tables)],
 requiredNativeChartOwnerSlides:[...new Set(charts)],materializeLiteralChartWorkbooks:true,
 fontPolicy:{basis:'reference',families:['Meiryo','Noto Sans CJK JP','Arial'],referencePath:source,referenceSha256:sha(bytes)},
 pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000',...[...new Set(tables)].flatMap(n=>['--require-native-table-slide',String(n)])],verifyArtifactToolImport:true,
 receiptPath:path.join(build,`${path.basename(finalPath)}.validation.json`)});
if(sha(bytes)!==sha(await fs.readFile(source)))throw new Error('Original modified');
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(const [i,s]of finalDeck.slides.items.entries()){
 const png=await s.export({format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log(`Rendered ${i+1}/${finalDeck.slides.items.length}`);
}
await fs.writeFile(path.join(out,'analysis/presentation_manifest.json'),JSON.stringify({
 source: path.relative(root,source),source_sha256:sha(bytes),final_sha256:sha(await fs.readFile(finalPath)),
 total_slides:finalDeck.slides.items.length,supplement_slides:pages.length,
 native_table_slides:[...new Set(tables)],native_chart_slides:[...new Set(charts)],
 execution_sha:data.execution_sha,solver_runs:0,builder_sha256:sha(await fs.readFile(import.meta.filename)),
 data_sha256:sha(await fs.readFile(path.join(out,'analysis/review_data.json')))},null,2));
console.log(finalPath);
