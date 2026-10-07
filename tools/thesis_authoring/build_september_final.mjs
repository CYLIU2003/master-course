// Editable September evidence deck. Inputs only; no solver or API calls.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const [inputArg, buildArg, outputArg]=process.argv.slice(2);
if(!inputArg||!buildArg||!outputArg) throw Error('Usage: node build_september_final.mjs EVIDENCE NEW_BUILD OUTPUT.pptx');
const input=path.resolve(inputArg), build=path.resolve(buildArg), output=path.resolve(outputArg);
for(const target of [output,path.join(path.dirname(output),'speaker_notes.md')]) {
 try { await fs.access(target); } catch(error) { if(error.code==='ENOENT') continue; throw error; }
 throw Error('Use a new destination; existing artifact is preserved: '+target);
}
const runtime=process.env.RUNTIME_DEPENDENCIES, skill=process.env.PRESENTATIONS_SKILL_DIR;
if(!runtime||!skill) throw Error('Set runtime and skill paths');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const manifest=JSON.parse(await fs.readFile(path.join(input,'manifest.json'),'utf8'));
for(const [name,digest] of Object.entries(manifest)) if(hash(await fs.readFile(path.join(input,name)))!==digest) throw Error('Evidence changed: '+name);
const d=JSON.parse(await fs.readFile(path.join(input,'presentation_data.json'),'utf8'));
if(d.weeks.length!==12||d.new_solver_run!==false) throw Error('Expected twelve frozen weeks');
await fs.mkdir(build,{recursive:false});
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const font='Noto Sans JP', navy='#202B58', teal='#159A8C', blue='#2F70B9', amber='#C99021', grey='#87949F', purple='#78589A';
const money=(x,n=2)=>Number(x).toLocaleString('ja-JP',{minimumFractionDigits:n,maximumFractionDigits:n});
const rows=d.weeks.map(w=>w.summary), notes=[], tables=[], charts=[];
if(rows.some(r=>!/^2025-\d{2}-\d{2}$/.test(r.week))) throw Error('This deck requires date-only CY2025 week identifiers');
const source=`計算固定版 ${d.source_sha}。比較revision ${d.revision}。出典は同梱evidence/。研究採用BLOCKEDを保持。チャート系列は小数6桁に表示用丸め、CSVは原値を保持。`;
function text(s,value,x,y,w,h,size=25,color=navy,bold=false){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=value;a.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return a;}
function page(title,subtitle,takeaway,foot,note=''){
 const s=deck.slides.add();s.background.fill='#FFFFFF';const n=deck.slides.items.length;
 text(s,title,54,26,1170,65,36,navy,true);text(s,subtitle,70,108,1140,58,24,'#59687B');
 text(s,takeaway,70,604,1140,53,25,teal,true);text(s,foot,70,662,1110,40,16,'#854A30');text(s,String(n),1210,681,45,25,15,'#59687B');
 const full=`${note}\n${source}\n${foot}`;s.speakerNotes.textFrame.setText(full);notes.push({page:n,title,notes:full});return s;
}
function table(s,values,widths,{x=60,y=183,w=1160,h=393,size=24}={}){tables.push(deck.slides.items.length);const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const a=t.getCell(r,c);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';a.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':navy,bold:r===0};}t.borders.assign({style:'solid',fill:'#CBD3DD',width:1});return t;}
function bar(s,categories,series,{x=70,y=182,w=1130,h=399,unit='',max,stacked=false}={}){charts.push(deck.slides.items.length);const c=s.charts.add('bar',{position:{left:x,top:y,width:w,height:h},categories,series:series.map(v=>({...v,values:v.values.map(x=>Number(x.toFixed(6)))})),barOptions:{direction:'column',grouping:stacked?'stacked':'clustered'},hasLegend:true,legend:{position:'bottom',textStyle:{typeface:font,fontSize:21}},yAxis:{title:unit,min:0,max,numberFormatCode:'0',textStyle:{typeface:font,fontSize:20}},xAxis:{textStyle:{typeface:font,fontSize:21}},dataLabels:{showValue:false}});for(let i=0;i<series.length;i++) c.series.getItemAt(i).smooth=false;applyPresentationChartFont(c,{fontFamily:font});return c;}
function scatter(s,series,{x=70,y=185,w=1130,h=395,unit='kW',xmax=174,ymax=1000,step=24,title='週開始からの時間 [h]',legend=true,compact=false}={}){charts.push(deck.slides.items.length);const c=s.charts.add('scatter',{position:{left:x,top:y,width:w,height:h},series:series.map(v=>({...v,values:v.values.map(x=>Number(x.toFixed(6)))})),scatterOptions:{style:'line'},lineOptions:{smooth:false},hasLegend:legend,legend:{position:'bottom',textStyle:{typeface:font,fontSize:18}},xAxis:{title,min:0,max:xmax,majorUnit:step,numberFormatCode:'0',textStyle:{typeface:font,fontSize:18}},yAxis:{title:unit,min:0,max:ymax,majorUnit:compact?(ymax===100?50:500):undefined,numberFormatCode:'0',textStyle:{typeface:font,fontSize:18}},dataLabels:{showValue:false}});for(let i=0;i<series.length;i++) c.series.getItemAt(i).smooth=false;applyPresentationChartFont(c,{fontFamily:font});return c;}
const line=(name,values,color,xValues)=>({name,values,xValues,smooth:false,fill:color,line:{fill:color,width:1.5},marker:{symbol:'none'}});
function stepSeries(name,values,color){return line(name,values.flatMap(v=>[v,v]),color,values.flatMap((_,i)=>[i*.25,(i+1)*.25]));}
const months=rows.map(r=>`${Number(r.week.slice(5,7))}月`), march=d.weeks[2], nov=d.weeks[10];
if([march,nov].some(w=>w.energy.length!==695)) throw Error('March/November coverage changed');
let s=page('修士論文研究　2026年9月進捗報告','仮・正式用 ／ 弦巻営業所 渋21・22・23','各月の代表1週について、運用と費用を原本から説明する','診断結果の条件付き週次評価。統合最適性・独立した正式研究採用は未確認。','9月19日版の構成と用語を継承し、結果はf524eca2の12週に更新した。旧版の数値と混ぜない。');
text(s,'混成バスの7日間運用・充電計画',70,235,1140,90,47,navy,true);text(s,'12代表週の費用・電力利用と\n季節別・天候別の日射カーブ',70,354,1140,110,35);text(s,'電力システム研究室　劉 承洋　／　2026年9月28日更新',70,531,1140,44,25,'#59687B');
s=page('研究の目的と、前回MTGからの進捗','全便を運行する条件で、配車と充電の費用を評価する','7日間の成立と費用差の内訳を、同じ入力版で確認した','月1週の記述的比較。手法の優越性・PVだけの因果効果は今回の結論に含めない。','前回の宿題は7日間への拡張、季節4区分と晴れ・くもり・雨の標準曲線、天候によるばらつき。最適化ケース数は12で、4季節は気象の分類である。');
table(s,[['前回の課題','今回示す結果'],['連続7日間の運用','各日の日付別ダイヤ・PVと、車両/BESS状態を継承'],['週次費用と月別の差','全12週の費目、電力量、車両使用を同じ形式で比較'],['天候ごとの標準カーブ','2025年35,040区間から、4季節×3天候の平均と分布'],['先生への回答','3月と11月の受電時系列・超過時間・費用差を照合']],[310,850]);
s=page('対象システムと用語','太陽光・系統からの電力で、電気バスの運行を支える','車載電池と営業所の蓄電池を分けて扱う','PVは総発電入力。走行以外の営業所負荷を0とするモデル上の仮定。');
table(s,[['名称','意味','今回の役割'],['BEV / ICE','電気バス / エンジンバス','各便を担当する車両'],['PV','太陽光発電','バスへの直接供給と、余剰の蓄電'],['BESS','営業所の定置用蓄電池','余剰PVを貯め、必要時に放電'],['SOC','電池容量に対する残量の割合','車載電池とBESSそれぞれの上下限を確認'],['系統からの受電','外部電力系統からの購入','不足する充電電力を供給']],[210,420,530],{size:23});
s=page('車両・設備・境界条件','各月で共通の設備と費用定義を使用','BEVは翌朝出庫までに運用上限へ。BESSは終端復元を課さない','設備定格の実証ではなく設定条件の検算。200 kWは有料超過の課金閾値。','出典：DAY_WEEK_PARAMETER_COMPARISON_20260927.mdと各週のPrepared。BEVとBESSのSOC上限を混同しない。1日実験から終端方針とPV境界等が変わり、単純な費用比較はしない。');
table(s,[['項目','設定'],['車両・消費','BEV35台 / ICE25台、314 kWh、1.316 kWh/km、4.52 km/L'],['車載電池 / 充電器','SOC20～90%、翌朝目標90%、90 kW×10基'],['PV / BESS','1,000 kW / 6,000 kWh・900 kW、充放電効率各0.95'],['BESS残量・運用','初期3,000、下限1,200、上限4,800 kWh。系統充電なし'],['主な費用係数','買電30円/kWh、軽油150円/L、車両20,000円/台日'],['超過・CO₂','200 kW超過分500円/kWh、CO₂ 1円/kg']],[285,875],{size:23});
s=page('計画・実行と、評価期間','配車を決めた後、充電を毎時更新し、採用した区間だけを集計','営業168時間に、最終翌朝の充電・受電・費用を加える','実車運行の観測ではなく計算上の実行。重複する計画窓を合算しない。','Phase 3は配車と固定配車下の充電を分ける。各段階のgapは週間統合gapではない。予測は学習年のみのclimatology、評価は2025年の履歴推定。');
table(s,[['段階・指標','扱い'],['事前計画','配車の候補を作り、固定配車の下で充電を計画'],['毎時の更新','実行SOC・BESS残量等を引き継ぎ、次の採用区間を決める'],['営業期間','7日間＝168時間＝672区間（15分刻み）'],['費用・購入電力量・受電ピーク','最終翌朝を含む。3月/11月は173.75時間・695区間'],['平均受電電力','営業168時間平均と、評価期間全体平均を区別']],[400,760],{size:24});
s=page('2025年の各月から選んだ12代表週','平日5日・土曜1日・日曜1日。各週1,704便','月ごとのシナリオを増やさず、「仮・正式用」の12期間として管理','2026年の固定ダイヤを2025年の気象で評価する仮想実験。各月平均への外挿はしない。');
table(s,[['月','開始日','月','開始日'],...Array.from({length:6},(_,i)=>[`${i+1}月`,rows[i].week,`${i+7}月`,rows[i+6].week])],[190,390,190,390],{size:25});
s=page('天候カーブの分類とデータ範囲','弦巻地点、2025年1月1日～12月31日、15分値35,040件','季節4区分×晴れ・くもり・雨。平均と日々の分布を示す','公式の天気分類・長期平年値・予測区間ではない。2025年評価の予測学習には使わない。','昼間は晴天時GHIが20 W/m²以上。昼間降水1 mm以上を雨、その他は日射/晴天時日射の比0.7以上を晴れ、未満をくもり。2℃以下で昼間降水1 mm以上は降水形態を識別できず除外。3月3日の1日を除き364日を分類。P10とP90は各時刻の経験分位点で、一つの実際の日の曲線でも信頼区間でもない。');
table(s,[['分類','固定した規則'],['季節','春3～5月、夏6～8月、秋9～11月、冬12～2月'],['雨','昼間の降水量が1 mm以上'],['晴れ / くもり','雨以外で、晴天時日射に対する比が0.7以上 / 未満'],['低温降水の扱い','2℃以下の降水で判別困難な3月3日を分類から除外'],['ばらつき','各時刻の平均・P10・P90。全分類で10日以上']],[340,820],{size:24});
const seasonNames={spring:'春（3～5月）',summer:'夏（6～8月）',autumn:'秋（9～11月）',winter:'冬（12～2月）'};
const weatherNames={sunny:'晴れ',cloudy:'くもり',rainy:'雨'};
for(const season of ['spring','summer','autumn','winter']){
 const cells=d.weather.curves.filter(c=>c.season===season);
 s=page(`${seasonNames[season]}の天候別日射カーブ`,'全天日射強度 GHI [W/m²]。2025年の同じ分類の日から集計','平均だけでなく、同じ季節・天候内の日々のばらつきがある','P10/P90は時刻別の経験分位点。PV発電量[kW]や将来の予測範囲とは別。',`出典：evidence/weather/seasonal_curves.csv。${cells.map(c=>weatherNames[c.weather_class]+c.source_day_count+'日').join('、')}。分類ルールは前ページ。`);
 cells.forEach((c,i)=>{text(s,`${weatherNames[c.weather_class]}　n=${c.source_day_count}日`,65+i*397,178,382,40,26,navy,true);scatter(s,[line('平均',c.ghi.mean,teal,c.ghi.mean.map((_,j)=>(j+.5)/4)),line('P10',c.ghi.p10,grey,c.ghi.mean.map((_,j)=>(j+.5)/4)),line('P90',c.ghi.p90,amber,c.ghi.mean.map((_,j)=>(j+.5)/4))],{x:58+i*400,y:224,w:390,h:356,unit:'W/m²',xmax:24,ymax:1100,step:6,title:'時刻 [JST h]'});});
}
s=page('12週で運行・電力収支・費用の照合が成立','全便、車両SOC、翌朝の補充と会計を保存原本で確認','計算結果を使った条件付き週次評価として、12週を比較できる','DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。独立した正式研究採用は未承認。','全12週の原本ZIPとPrepared hash、physical accepted、account eligible、missing/duplicate slotsなし、全便充足と日別台帳を再照合した。1・11・12月は原FAILEDを残した図表復旧。図の生成だけを計算完了と数えていない。');
table(s,[['確認項目','結果'],['運行','12/12週、各1,704便。全対象便を一度ずつ担当'],['物理・会計','各週の物理判定を通過。最終実行会計・日別台帳を照合'],['日境界・最終翌朝','SOC状態列と評価区間数を照合。日次の無料リセットなし'],['図表復旧','1・11・12月は原FAILEDを保全。検算済み原本から収録'],['未証明の範囲','週間統合最適性・対照手法への優越性・実設備の運用保証']],[320,840],{size:24});
s=page('月別代表週のPV供給と購入電力量','左：PVの受け渡し先。右：系統からの週間購入電力量','PV供給量と、運行・充電の時間帯の両方が電力利用に関係する','PV→BESSと、その後のBESS→バスを同じ発電量として二重計上しない。');
bar(s,months,[['バスへ直接','pv_to_bus_kwh',teal],['BESSへ','pv_to_bess_kwh','#86B4A0'],['抑制','pv_curtailed_kwh','#BAC1C9']].map(([name,k,fill])=>({name,values:rows.map(r=>r[k]/1000),fill})),{x:55,w:575,unit:'MWh',stacked:true,max:35});
bar(s,months,[{name:'週間購入電力量',values:rows.map(r=>r.grid_import_kwh/1000),fill:blue}],{x:663,w:560,unit:'MWh',max:12});
s=page('週次費用は車両日費と電力関連費に分けて読む','総費用の比較に加えて、車両日費を除く内訳を表示','車両日費が大きいため、総額だけでは電力利用の差が見えにくい','単位：万円。設備投資・保守・劣化・運転士費等は未計上。超過モデル費は実請求額ではない。');
bar(s,months,[{name:'車両日費',values:rows.map(r=>r.vehicle_usage_cost/10000),fill:grey},{name:'その他の費用',values:rows.map(r=>(r.total_cost-r.vehicle_usage_cost)/10000),fill:teal}],{x:55,w:575,unit:'万円',stacked:true,max:650});
bar(s,months,[['買電','electricity_cost',blue],['燃料','fuel_cost',amber],['超過モデル費','contract_overage_cost',purple],['CO₂','co2_cost',grey]].map(([name,k,fill])=>({name,values:rows.map(r=>r[k]/10000),fill})),{x:663,w:560,unit:'万円',stacked:true,max:210});
s=page('3月と11月の受電時系列','横軸は日付：上段3月・下段11月。薄い破線は0時の日境界','11月の最大値は高いが、3月は200 kWを超える区間が多い','15分平均受電電力。ピークの高さだけで、購入電力量や超過費用は決まらない。');
scatter(s,[stepSeries('3月',march.energy.map(v=>v.grid_import_kwh*4),blue),stepSeries('11月',nov.energy.map(v=>v.grid_import_kwh*4),teal),line('課金閾値200 kW',[200,200],'#B95D4C',[0,173.75])],{ymax:800});
s=page('3月と11月：購入量・時間・最大値の違い','営業168時間と、翌朝を含む評価173.75時間を分ける','3月の超過電力量は3,319 kWh、11月は1,500 kWh','超過時間は200 kW+0.001 kWを超えた区間を数える。電力量は原値を積算。');
table(s,[['指標','3月3日開始週','11月10日開始週'],['週間購入電力量 [kWh]',... [march,nov].map(w=>money(w.summary.grid_import_kwh))],['受電ピーク [kW]',...[march,nov].map(w=>money(w.summary.peak_grid_kw))],['週間平均受電電力 [kW]（168 h）',...[march,nov].map(w=>money(w.power.service_week.mean_grid_kw))],['評価期間平均受電電力 [kW]（173.75 h）',...[march,nov].map(w=>money(w.power.full_period.mean_grid_kw))],['200 kW超過時間 [h]',...[march,nov].map(w=>money(w.power.full_period.over_contract_hours))],['200 kW超過電力量 [kWh]',...[march,nov].map(w=>money(w.power.full_period.over_contract_kwh))]],[610,275,275],{size:22});
s=page('受電ピークの周辺を同じ時間幅で確認','各週の最大区間と前後3時間。横軸は各対象日の実時刻 [JST]','最大値は3月6日04:15、11月14日04:15の区間で発生','同時に観測した計画の説明。ピークを回避できたかの対照計算は未実施。');
for(const [i,w] of [march,nov].entries()){const p=w.power.full_period.peak_slot; if(p<12||p+12>=w.energy.length) throw Error('Peak window lacks three hours on either side'); const left=p-12, vals=w.energy.slice(left,p+13).map(v=>v.grid_import_kwh*4);text(s,`${i===0?'3月6日':'11月14日'}　受電ピーク ${money(w.summary.peak_grid_kw,1)} kW`,65+i*603,180,590,45,25);scatter(s,[stepSeries('受電電力',vals,i===0?blue:teal),line('課金閾値',[200,200],'#B95D4C',[0,vals.length/4])],{x:55+i*610,y:234,w:590,h:346,xmax:6.25,ymax:800,step:1,title:'表示開始からの時間 [h]'});}
s=page('3月と11月の費用差を費目へ分解','同じ1,704便・206台日。表示は万円、原値は最終実行会計','主な差は超過モデル費。料金係数と受電時系列を併せて解釈する','超過モデル費＝200 kWを超える電力量×500円/kWh。実請求差・手法の削減効果ではない。');
const costKeys=[['車両日費','vehicle_usage_cost'],['買電費','electricity_cost'],['燃料費','fuel_cost'],['超過モデル費','contract_overage_cost'],['CO₂費','co2_cost'],['総費用','total_cost']];
table(s,[['費目 [万円]','3月','11月','差（3月−11月）'],...costKeys.map(([n,k])=>[n,money(march.summary[k]/10000),money(nov.summary[k]/10000),money((march.summary[k]-nov.summary[k])/10000)])],[400,240,240,280],{size:24});
s=page('BESSの初期・終端在庫と解釈','毎週3,000 kWhから開始し、下限1,200 kWhを満たす','在庫の取り崩しを、毎週繰り返せる節約とは扱わない','BESSは余剰PVで充電。原本のbalancedは終端方針の充足であり、初終端一致ではない。');
bar(s,months,[{name:'初期残量',values:rows.map(r=>r.bess_terminal.tsurumaki.initial_soc_kwh),fill:grey},{name:'終端残量',values:rows.map(r=>r.bess_terminal.tsurumaki.terminal_soc_kwh),fill:teal}],{unit:'kWh',max:5000});
s=page('今回の結論と、主張できる範囲','月別代表週の運用と費用を、日付・時系列・費目で説明できる','12週の整合した結果と天候別カーブが、次の比較の土台になった','正式研究採用BLOCKEDを保持。DIAGNOSTIC / NOT USED FOR RESEARCH CONCLUSIONS。','今回の価値は週次成立と費用の説明。対照実験がないので削減額や優越性は言わない。電費一定で空調季節変動を評価していない。各月1週と2025年1年の記述統計から月平均・長期傾向を断定しない。');
table(s,[['問い','今回の回答'],['7日間をつなげられたか','全12週で全便・物理・会計・最終翌朝の範囲を照合'],['費用は何で変わったか','車両日費を分離。3月/11月の主な差は超過モデル費'],['天候のムラを示せたか','4季節×3天候の平均とP10/P90を、日数付きで提示'],['次に確かめること','実設備条件・距離根拠、同条件の対照、探索ばらつき'],['現状の限界','統合最適性未証明、電費一定、各月1週、設備投資未評価']],[335,825],{size:24});
const mainCount=deck.slides.items.length;
for(const start of [0,6]){s=page(`補足：費用と単位当たり費用（${start+1}～${start+6}月）`,'営業7日間＋最終翌朝。円/営業kmには回送kmを分母として含めない','同じ便数でも、月別の購入量と受電時間帯を確認する','燃料費は消費在庫の評価を含む。営業距離は停留所列に基づく代理距離。');table(s,[['月','総費用 [万円]','車両日費 [万円]','円/営業km','円/便'],...rows.slice(start,start+6).map(r=>[`${Number(r.week.slice(5,7))}月`,money(r.total_cost/10000),money(r.vehicle_usage_cost/10000),money(r.cost_per_service_km_jpy),money(r.cost_per_trip_jpy)])],[140,275,285,230,230],{size:24});}
s=page('補足：代表週の日射量と、月全体との差','2025年の日積算GHIで事後確認。週は結果を見て選び直していない','3月の選択週は月平均より日射が少ない。月の平均結果と呼ばない','GHI [kWh/m²/日]とPV発電量[kWh]は別量。分類除外日も日射量の記述集計には含む。');
const repr=rows.map(r=>{const dates=d.weather.daily_labels.filter(v=>v.date>=r.week&&v.date<new Date(new Date(r.week).getTime()+7*864e5).toISOString().slice(0,10));const month=d.weather.daily_labels.filter(v=>v.date.slice(0,7)===r.week.slice(0,7));if(dates.length!==7||month.length<28) throw Error('Incomplete daily irradiance coverage');const avg=a=>a.reduce((s,x)=>s+x.daily_irradiation_kwh_m2,0)/a.length;return [r.week,avg(dates),avg(month),100*(avg(dates)/avg(month)-1)];});
table(s,[['対象','選択週の日平均','月全体の日平均','差 [%]'],...repr.filter(r=>['03','07','10','11'].includes(r[0].slice(5,7))).map(r=>[r[0],money(r[1],3),money(r[2],3),money(r[3],1)])],[310,295,295,260],{h:320});
s=page('補足：求解品質と検証の範囲','実行可能性、会計、最適性、研究採用を区別','統合週間gapは未算出。段階別gapを総費用の誤差率には使わない','原本・入力・会計・各CSVのhashと再生成手順を同梱。最適化の再実行なし。');
table(s,[['項目','記録と位置付け'],['計算固定版','f524eca2552a4386bd033a15bbe046c14dc09281'],['求解構成','配車と充電の二段階、固定配車の毎時充電更新'],['予測 / 評価','学習年のみのclimatology / 2025年Solcast履歴推定'],['時間上限・gap','時間上限内の可行解を含む。全体最適性を証明していない'],['正式判定','BLOCKEDを保存。対照比較・独立承認等は未完了'],['CO₂図表の注意','係数照合の描画失敗は別記。会計正本のCO₂費を使用']],[320,840],{size:22});
for(const w of d.weeks){const m=Number(w.summary.week.slice(5,7)),ns=w.energy.length;
 s=page(`補足：${m}月代表週の電力需給と車両SOC`,`${w.summary.week}開始 ／ ${ns*.25}時間（最終翌朝含む）／ ${w.summary.trips}便 ／ 運行BEV ${w.soc.length}台`,`日別使用台数：${w.daily.map(x=>x.used_vehicles).join('、')}台。原値は同梱CSVを参照`,'日付は各日の中央、破線は0時。上：15分平均電力。下：運行BEVのSOC最小・中央値・最大（未使用車を除く）。',`出典：evidence/${w.summary.week}/energy_15min.csv、vehicle_soc.csv、vehicle_schedule.csv、charging_schedule.csv。SOC時点0は週初。時点${ns}は最終翌朝の終端。ICEに電池SOCはない。日ごとに無料補充する処理ではない。`);
 scatter(s,[stepSeries('バス充電',w.energy.map(v=>v.bus_charge_kwh*4),navy),stepSeries('系統受電',w.energy.map(v=>v.grid_import_kwh*4),blue),stepSeries('PV供給可能',w.energy.map(v=>(v.pv_to_bus_kwh+v.pv_to_bess_kwh+v.pv_curtailed_kwh)*4),amber)],{y:165,h:235,xmax:ns*.25,ymax:1100,legend:true,title:'',compact:true});
 const quant=[];for(let i=0;i<=ns;i++){const a=w.soc.map(v=>v.values[i]).sort((a,b)=>a-b);quant.push([a[0],a.length%2?a[(a.length-1)/2]:(a[a.length/2-1]+a[a.length/2])/2,a.at(-1)]);}
 scatter(s,[line('最小',quant.map(v=>v[0]),purple,quant.map((_,i)=>i*.25)),line('中央値',quant.map(v=>v[1]),teal,quant.map((_,i)=>i*.25)),line('最大',quant.map(v=>v[2]),grey,quant.map((_,i)=>i*.25))],{y:388,h:214,xmax:ns*.25,ymax:100,unit:'SOC [%]',title:'',compact:true});
}
const draft=path.join(build,'candidate.pptx');await(await PresentationFile.exportPptx(deck)).save(draft);
const calendarDraft=path.join(build,'calendar.pptx');
execFileSync('powershell.exe',['-NoProfile','-File','tools/thesis_authoring/apply_calendar_axes.ps1','-InputPptx',draft,'-OutputPptx',calendarDraft,'-Evidence',path.join(input,'presentation_data.json')],{stdio:'inherit'});
const normalizedDraft=path.join(build,'normalized.pptx');
execFileSync(path.join(runtime,'python/python.exe'),['tools/thesis_authoring/normalize_chart_cache.py',calendarDraft,normalizedDraft],{stdio:'inherit'});
const sourcePath=path.resolve('outcome/2026-09-19_urabe_terminology/monthly_progress_20260919_terms_v2.pptx');
await finalizePresentation({workspaceDir:path.resolve('.'),candidatePath:normalizedDraft,finalPath:output,explicitTotalSlideCount:deck.slides.items.length,requiredNativeTableOwnerSlides:[...new Set(tables)],requiredNativeChartOwnerSlides:[...new Set(charts)],materializeLiteralChartWorkbooks:true,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000',...[...new Set(tables)].flatMap(n=>['--require-native-table-slide',String(n)])],fontPolicy:{basis:'reference',families:[font],referencePath:sourcePath,referenceSha256:hash(await fs.readFile(sourcePath))},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
await fs.writeFile(path.join(path.dirname(output),'speaker_notes.md'),notes.map(n=>`## ${n.page}. ${n.title}\n\n${n.notes}\n`).join('\n'));
await fs.writeFile(path.join(build,'contents.json'),JSON.stringify({main_slides:mainCount,total_slides:notes.length,notes},null,2));
console.log(JSON.stringify({output,slides:notes.length,main_slides:mainCount}));
