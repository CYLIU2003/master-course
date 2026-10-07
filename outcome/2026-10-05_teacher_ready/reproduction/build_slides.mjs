import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const build=path.resolve(process.argv[2]);
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.930.11008/skills/presentations';
process.env.RUNTIME_NODE_MODULES=runtime+'/node/node_modules';
const {Presentation,PresentationFile}=await import(pathToFileURL(runtime+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const d=JSON.parse(await fs.readFile(path.join(build,'data.json'),'utf8'));
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const font='Noto Sans JP',navy='#202B58',teal='#159A8C',blue='#2F70B9',amber='#C99021';
function text(s,value,x,y,w,h,size=24,color=navy,bold=false,name){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0},name});a.text=value;a.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return a;}
function page(old,title,sub,takeaway,foot,note){const s=deck.slides.add();s.background.fill='#FFFFFF';text(s,title,54,26,1170,65,36,navy,true);text(s,sub,70,108,1140,54,23,'#59687B');text(s,takeaway,70,603,1140,51,24,teal,true);text(s,foot,70,661,1120,39,16,'#854A30');text(s,String(d.old_to_new[old]),1210,681,45,25,15,'#59687B');s.speakerNotes.textFrame.setText(note+'\n固定計算版 f524eca2552a4386bd033a15bbe046c14dc09281。原本manifest SHA256 '+d.evidence_manifest_sha256+'。原正式採用BLOCKED/DIAGNOSTIC/NOT USED FOR RESEARCH CONCLUSIONSを保持。今回の追加集計は新しい求解ではない。');return s;}
function table(s,values,widths,{y=178,h=412,size=22}={}){const t=s.tables.add({rows:values.length,columns:values[0].length,left:60,top:y,width:1160,height:h,values,columnWidths:widths});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const a=t.getCell(r,c);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';a.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':navy,bold:r===0};}t.borders.assign({style:'solid',fill:'#CBD3DD',width:1});return t;}
function chart(s,series,{x=75,y,h=130,w=790,unit,max,min=0,xmax=48,major=12,legend=true}){const rounded=series.map(a=>({...a,values:a.values.map(v=>{if(!Number.isFinite(v))throw Error('Nonfinite chart data');return Number(v.toFixed(6));})}));const c=s.charts.add('scatter',{position:{left:x,top:y,width:w,height:h},series:rounded.map(a=>({...a,smooth:false,marker:{symbol:'none'},line:{fill:a.fill,width:1.5}})),scatterOptions:{style:'line'},lineOptions:{smooth:false},hasLegend:legend,legend:{position:'bottom',textStyle:{typeface:font,fontSize:16}},xAxis:{min:0,max:xmax,majorUnit:major,textStyle:{typeface:font,fontSize:16}},yAxis:{title:unit,min,max,textStyle:{typeface:font,fontSize:16}}});for(let i=0;i<series.length;i++)c.series.getItemAt(i).smooth=false;applyPresentationChartFont(c,{fontFamily:font});return c;}
const april=d.weeks.find(r=>r.week==='2025-04-07'),may=d.weeks.find(r=>r.week==='2025-05-12');
const n=(r,k)=>Number(r[k]),fmt=(v,dp=0)=>Number(v).toLocaleString('ja-JP',{minimumFractionDigits:dp,maximumFractionDigits:dp});
const diff=n(may,'total_cost')-n(april,'total_cost'),over=n(may,'contract_overage_cost')-n(april,'contract_overage_cost');
if(Math.abs(diff-576380.85397538)>1e-6 || Math.abs(over-524900.18403343)>1e-6)throw Error('Pair evidence changed');
let s=page(40,'PV総量が近い4月・5月でも、費用は57.6万円違う','同じ路線・各週1,704便。記録された計画の比較であり、PVだけを変えた実験ではない','仮定単価500円/kWhのもとでは、差の約91%が超過モデル費','超過費は実際の電気料金ではない。差には配車・予測・探索・終端在庫の違いも含まれる。','原本weekly_summary.csv。4月と5月の車両日費はともに412万円（206車両日）。2026-10-03検討メモの410万円は誤記で本日訂正。PV差281.1375kWh、1.0666%。総差576380.85397538円、超過差524900.18403343円、91.0683%。買電費差56419.54867896円、燃料評価差-5779.56882743円、CO2差840.69009043円。固定計画の恒等式は差51480.66994195円＋超過単価×1049.80036806685kWh。単価を変えて再最適化していない。燃料は走行距離による暫定消費評価、給油支払額ではない。設備費・保守・劣化・人件費未計上。');
table(s,[['指標','4/7開始週','5/12開始週','5月−4月'],['利用可能PV [kWh]',fmt(n(april,'pv_generated_kwh')),fmt(n(may,'pv_generated_kwh')),'+281（約1%）'],['モデル総費用 [万円]',fmt(n(april,'total_cost')/1e4,1),fmt(n(may,'total_cost')/1e4,1),'+57.6'],['車両日費 [万円]','412.0','412.0','0.0'],['超過モデル費 [万円]',fmt(n(april,'contract_overage_cost')/1e4,1),fmt(n(may,'contract_overage_cost')/1e4,1),'+52.5'],['買電費 [万円]',fmt(n(april,'electricity_cost')/1e4,2),fmt(n(may,'electricity_cost')/1e4,2),'+5.64'],['燃料評価 / CO₂費の差','—','—','−0.58 / +0.08万円'],['BESS初期→終端 [kWh]','3,000 → 1,200','3,000 → 1,489','在庫減少量は異なる']],[370,245,245,300],{size:22,h:410});
// Piecewise-constant power; BESS state is plotted at the interval end.
const x=d.may_energy.flatMap((_,i)=>[i*.25,(i+1)*.25]);
const pow=k=>d.may_energy.flatMap(r=>[n(r,k)*4,n(r,k)*4]);
const pv=d.may_energy.flatMap(r=>{const p=(n(r,'pv_to_bus_kwh')+n(r,'pv_to_bess_kwh')+n(r,'pv_curtailed_kwh'))*4;return[p,p];});
const bessX=[0,...d.may_energy.map((_,i)=>(i+1)*.25)],bess=[3000,...d.may_energy.map(r=>n(r,'bess_soc_end_kwh'))];
const daily = day => d.may_energy.filter(r=>r.interval_start_jst.startsWith(day));
const sum=(rows,k)=>rows.reduce((a,r)=>a+n(r,k),0);
const day12=daily('2025-05-12'),day13=daily('2025-05-13');
const rainLabel=d.weather_labels.find(r=>r.date==='2025-05-12').weather_class;
const sunLabel=d.weather_labels.find(r=>r.date==='2025-05-13').weather_class;
if(rainLabel!=='rainy'||sunLabel!=='sunny')throw Error('Saved day labels changed');
s=page(41,'翌未明に買電し、同日の日中にはPVを抑制する','5/12〜13の保存された実行系列。PVは水平面日射比例の推計、BESSは残存電力量','週積算では見えない、日射・充電要求・BESS残量の前後関係','この時間配分が不可避・最適とは未確認。2024年1年の日射で計画し、2025年履歴で更新。','原本energy_15min.csvの最初の192区間。15分区間の電力は電力量/0.25hを階段線で表示。BESSは区間末端を結ぶ。5/12PV1797.325kWh、日末BESS1200。5/13 00–06買電2242.9178996kWh、日PV6333.35kWh、抑制2431.40kWh。5/13抑制正の23区間は全て区間末BESS4800kWh。12:15〜18:00の間に出現するが連続全区間とはいわない。この観測から別配車・別充電による抑制回避が不可能とはいえない。2025-05-12は雨、05-13晴れの保存済み研究分類。日射総量と費用の因果効果は未識別。');
chart(s,[{name:'利用可能PV',xValues:x,values:pv,fill:amber},{name:'PV抑制',xValues:x,values:pow('pv_curtailed_kwh'),fill:'#929FAA'}],{y:164,h:138,unit:'電力 [kW]',max:1000});
chart(s,[{name:'系統受電',xValues:x,values:pow('grid_import_kwh'),fill:blue},{name:'バス充電',xValues:x,values:pow('bus_charge_kwh'),fill:teal},{name:'モデル閾値200kW',xValues:[0,48],values:[200,200],fill:'#BA5B46'}],{y:306,h:138,unit:'電力 [kW]',max:1000});
chart(s,[{name:'BESS残量',xValues:bessX,values:bess,fill:teal},{name:'上下限',xValues:[0,48,48,0],values:[1200,1200,4800,4800],fill:'#A0ABB5'}],{y:448,h:138,unit:'残量 [kWh]',max:6000});
text(s,'5/12：PV 1,797 kWh\n日末BESS 1,200 kWh',900,180,310,85,23);
text(s,'5/13：00〜06時\n買電 2,243 kWh\n\n同日の日中\nPV 6,333 kWh\n抑制 2,431 kWh',900,307,310,170,23);
text(s,'抑制区間では\nBESSが上限4,800 kWh',900,499,310,76,22,teal,true);
// Date labels / midnight separators are added from native PlotArea geometry after insertion.
s=page(42,'今回分かったことと、次に確かめること','7日間の成立確認から、時間的な電力利用の評価へ','日射総量だけでなく、充電できる時刻と残量を合わせて評価する','条件付きの代表週評価。統合最適性・実設備の運用保証・設備投資の採算は未確認。','12代表週を4季節の4実験や52週連続運用に読み替えない。保存物理判定と原本CSV収支・費目照合の範囲。全native成果物の新規独立監査ではない。夜間集中の供給理由は確認したが、集中が不可避かは未確認。次の比較は計画情報、配車、SOC、料金、予算を揃えた充電時刻比較を予定案として提示。設置面日射は設置角・方位確認後の新入力版が必要で、今回実施していない。題目・研究貢献候補は10/8先生とのMTGで確認。');
table(s,[['問い','今回の答え / 次の確認'],['7日間の計画は成立したか','12週の各1,704便と、翌朝までの残量・電力収支・費用を照合'],['何が費用差に現れたか','4月・5月の57.6万円差の91%は、仮定単価による超過費の差'],['時系列から何が分かったか','翌未明の買電と、その後のPV抑制が同じ週に生じる'],['次に確かめること①','同じ配車・情報・制約で、夜間充電を分散できるか比較する'],['次に確かめること②','設置角・方位を確認し、設置面日射の別入力版で評価する']],[350,810],{size:24,h:404});
s=page(43,'補足：同じ6時間内の平坦化だけでは収まらない','5/13 00〜06時の買電量を固定した算術確認。帰庫〜出庫の全可能時間ではない','確認できるのは、この買電量をこの6時間だけで配分する場合に限る','前日への充電移動・別配車は含めない。週次問題の下界、不可行性、最適性の証明ではない。','買電2242.9178996kWhを固定。200kW×6h=1200kWh、差1042.9178996kWh。実系列の超過1092.9178996kWh。各車両の充電可能時間を利用した最小超過解ではない。この量の差を削減可能額と扱わない。night_energy_relaxation.csvとenergy_15min.csvを参照。');
table(s,[['算術の対象','値'],['00〜06時の記録された買電量','2,243 kWh'],['モデル閾値200 kW × 6時間','1,200 kWh'],['上の量と時間を固定した超過の下限','1,043 kWh'],['実系列の同時間帯の超過電力量','1,093 kWh'],['この確認に含めていない選択肢','前日深夜への移動、車両割当変更、全帰庫〜出庫窓の最適化']],[620,540],{size:24,h:410});
s=page(44,'同じ天候分類でも、日射は日ごと・時刻ごとに異なる','2025年Solcast履歴推定の記述統計。今回の予測は2024年の別データ','「雨の日＝終日低日射」ではない。平均と日ごとのばらつきを分けて見る','図は水平面GHIの平均。設置面日射・実PV計測ではない。全季節のP10/P90は補足に収録。','原本weather/seasonal_curves.csv、weather_labels.csv。平均は同じ季節・分類の各時刻の集合。2025年364日分類、3/3降水形態未判定1日除外は分類のみ。今回の4線は夏/冬×晴れ/雨の平均に限定して取捨選択。くもりと全季節・経験分位点は元スライド8〜11の補足。研究分類、雨優先、昼間clearsky_ghi>=20W/m²、昼間降水>=1mm、非雨の日の昼間GHI/clearsky_ghi>=0.7晴れ。夏雨20日中10〜14時比>=0.7は6日、かつ15時以降昼間降水>=1mmは2日。これらは事後の探索集計で夕立の多数・気象原因は未同定。P10/P90は時刻別経験分位点で実在する1日や予測区間ではない。');
const configs=[['summer','sunny','夏・晴れ',amber],['winter','sunny','冬・晴れ',blue],['summer','rainy','夏・雨',teal],['winter','rainy','冬・雨','#8997A4']];
const series=configs.map(([season,kind,label,fill])=>{const rows=d.weather_curves.filter(r=>r.season===season&&r.weather_class===kind);if(rows.length!==96)throw Error('Curves must contain 96 intervals');return {name:`${label}（${rows[0].source_day_count}日）`,xValues:rows.map(r=>n(r,'interval_start_minute_jst')/60+.125),values:rows.map(r=>n(r,'mean')),fill};});
chart(s,series,{x:72,y:171,w:810,h:412,unit:'水平面GHI [W/m²]',max:1000,xmax:24,major:6});
text(s,'夏の雨20日の中でも',920,200,290,44,25,navy,true);
text(s,'10〜14時の日射比\n0.7以上：6日\n\nそのうち15時以降の\n昼間降水1 mm以上：2日',920,255,290,204,23);
text(s,'時刻ごとのP10/P90は\n実在する1日の曲線でも\n予測区間でもない',920,486,290,90,22,teal,true);
const draft=path.join(build,'new_slides_draft.pptx');await(await PresentationFile.exportPptx(deck)).save(draft);
await fs.mkdir(path.join(build,'final_supplement'),{recursive:true});
await finalizePresentation({workspaceDir:'C:/master-course',candidatePath:draft,finalPath:path.join(build,'final_supplement/new_slides.pptx'),explicitTotalSlideCount:5,requiredNativeTableOwnerSlides:[1,3,4],requiredNativeChartOwnerSlides:[2,5],materializeLiteralChartWorkbooks:true,pythonExecutable:runtime+'/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000',...[1,3,4].flatMap(i=>['--require-native-table-slide',String(i)])],fontPolicy:{basis:'reference',families:[font],referencePath:d.source,referenceSha256:d.source_sha256},verifyArtifactToolImport:true,receiptPath:path.join(build,'new_slides_validation.json')});
console.log('Five new native slides validated');
