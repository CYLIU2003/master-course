import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const build=path.resolve(process.argv[2] ?? 'C:/master-course/output/teacher_revision_20261002');
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.930.11008/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {Presentation,PresentationFile,FileBlob}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const source='C:/master-course/outcome/2026-09-28_september_presentation/september_progress_20260928_v4_ur.pptx';
const imported=await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot=await imported.inspect({kind:'slide,textbox,table,chart,notes,thread',maxChars:16000});
await fs.writeFile(path.join(build,'artifact_import_inspection.ndjson'),snapshot.ndjson);
// Native package edits preserve all modern comment parts and existing chart workbooks.
// Artifact Tool authors only the new evidence slides; existing slide objects are kept.
const d=JSON.parse(await fs.readFile(path.join(build,'analysis.json'),'utf8'));
const rainCsv=await fs.readFile(path.join(build,'summer_rain_example_20250710.csv'),'utf8');
const rain=rainCsv.replace(/^\uFEFF/,'').trim().split(/\r?\n/).slice(1).map(s=>{const a=s.split(',');return {h:+a[1],ghi:+a[2],clear:+a[3],rate:+a[4]};});
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const font='Noto Sans JP', navy='#202B58',teal='#159A8C',blue='#2F70B9',amber='#C99021';
function text(s,value,x,y,w,h,size=24,color=navy,bold=false){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=value;a.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return a;}
function page(n,title,sub,takeaway,foot,note){const s=deck.slides.add();s.background.fill='#FFFFFF';text(s,title,54,26,1170,65,36,navy,true);text(s,sub,70,108,1140,58,24,'#59687B');text(s,takeaway,70,604,1140,53,25,teal,true);text(s,foot,70,662,1110,40,16,'#854A30');text(s,String(n),1210,681,45,25,15,'#59687B');s.speakerNotes.textFrame.setText(note);return s;}
function table(s,values,widths,{y=182,h=405,size=23}={}){const t=s.tables.add({rows:values.length,columns:values[0].length,left:60,top:y,width:1160,height:h,values,columnWidths:widths});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const a=t.getCell(r,c);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';a.text.style={typeface:font,fontSize:size,color:r===0?'#FFFFFF':navy,bold:r===0};}t.borders.assign({style:'solid',fill:'#CBD3DD',width:1});return t;}
function chart(s,series,{y,h,unit,max}){const c=s.charts.add('scatter',{position:{left:75,top:y,width:760,height:h},series:series.map(a=>({...a,xValues:rain.map(r=>r.h),smooth:false,marker:{symbol:'none'},line:{fill:a.fill,width:1.5}})),scatterOptions:{style:'line'},lineOptions:{smooth:false},hasLegend:series.length>1 && series[0].name!=='降水強度',legend:{position:'bottom',textStyle:{typeface:font,fontSize:18}},xAxis:{title:'時刻 [JST h]',min:0,max:24,majorUnit:6,textStyle:{typeface:font,fontSize:18}},yAxis:{title:unit,min:0,max,textStyle:{typeface:font,fontSize:18}}});for(let i=0;i<series.length;i++)c.series.getItemAt(i).smooth=false;applyPresentationChartFont(c,{fontFamily:font});return c;}
let s=page(37,'補足：雨分類でも日中に日射が高い日がある','2025年7月10日（雨分類）の15分推定値。分類は日単位、日射は時刻別','夏の雨20日中、明るい昼＋15時以降の降水は2日。多数とはいえない','追加の探索集計。夕立の発生原因は判定していない。P90曲線は実在する1日を表さない。', '先生コメント6への回答。昼間は晴天時GHI>=20W/m²。雨分類は昼間降水積算>=1mm。夏雨20日のうち10:00–14:00積算GHI/晴天時GHI>=0.7は6日、その中で15:00以降の昼間降水>=1mmは2日。7/10は10–14時の比0.879、15時前昼間降水0.30mm、15時以降1.10mm。これは事後の探索的閾値で公式の夕立分類ではない。P90が高いのは雨の日の集合にも日射が高い時間帯が含まれるため。時刻ごとの90%点で、曲線全体が同じ日ではない。原CSV:summer_rain_days.csv、summer_rain_example_20250710.csv。');
chart(s,[{name:'水平面GHI',values:rain.map(r=>r.ghi),fill:teal},{name:'晴天時GHI',values:rain.map(r=>r.clear),fill:amber}],{y:168,h:247,unit:'W/m²',max:1100});
chart(s,[{name:'降水強度',values:rain.map(r=>r.rate),fill:blue},{name:'0 mm/h基準',values:rain.map(()=>0),fill:'#87949F'}],{y:403,h:191,unit:'mm/h',max:1});
text(s,'7月10日の例',860,195,335,40,26,navy,true);
text(s,'10〜14時の日射比\n0.879\n\n昼間の降水量\n15時前：0.30 mm\n15時以降：1.10 mm',860,247,335,255,25);
text(s,'降水量 = 降水強度\n[mm/h] × 0.25 h の合計',860,508,335,76,22,'#59687B');
s=page(38,'補足：水平面日射と、PVの設置面日射を分ける','冬の太陽高度・日長と、設置角・方位は別々の要因','設置面日射への変更には、角度・方位を確定した別入力版が必要','今回の12週は水平面日射に基づく条件付き評価。傾斜面への補正・再計算は未実施。','先生コメント7への回答。既存データのGHIは水平面全天日射、DNIは法線面直達、DHIは水平面散乱。既存PV換算はcapacity×clamp(GHI/1000×performance_ratio,0,1)×時間刻みで、設置角・方位を反映していない。先生の傾斜面日射採用の指摘を受け入れる。設置角・方位とモデルを確定した別入力版で評価が必要。既存12週へ後付け補正はしない。傾斜により冬季の日射受光が変わり得るが、冬夏差の解消や費用順位の変化は未計算。既存GHIカーブは地点の水平面の記述統計として保持。公式参照:https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html');
table(s,[['量・条件','今回の扱いと、必要な訂正'],['水平面全天日射 GHI','現在の標準カーブ。水平な面が受ける直達＋散乱日射'],['設置面日射 POA / GTI','傾斜角・方位を持つPV面への日射。GHIとは同じでない'],['冬と夏の日射差','水平面の日長・太陽高度の差。実PVの発電量差とは断定しない'],['今回のPV換算','GHIに容量等を掛ける簡易換算。設置角・方位が未反映'],['本番に向けた修正','設置条件を確認し、直達・散乱日射から設置面日射を算定'],['今は主張できないこと','傾斜面を採用済み、実設備の発電再現、季節の費用順位の保証']],[310,850],{size:23});
s=page(39,'補足：夜間受電が増えた区間の供給と充電需要','3月6日・11月14日、04:15〜04:30の採用区間を追跡','PVなし・BESS下限・出庫前の補充が重なり、同時充電を系統が供給','受電の供給理由は確認できる。04:15への集中が不可避・最適かは別の検証が必要。','先生コメント9への回答。以下は最終実行系列の観測された組合せであり、比較実験による因果効果の証明ではない。BESS下限1200kWh、充電器10基90kW、BEV翌朝目標90%。ピーク開始の状態と次の営業便発車を車両ID別に照合した。各車両の帰庫から出庫までの代替充電余地、予測誤差、ローリング窓制約、探索到達度の寄与は分離していない。200kWは超過モデル料金の閾値で実設備の上限ではない。PV/BESS/初終端在庫の違いを総費用削減と呼ばない。原CSV:peak_vehicle_evidence.csvと既存energy_15min.csv、charging_schedule.csv、vehicle_soc.csv、vehicle_schedule.csv。');
table(s,[['ピーク区間の記録','3月6日','11月14日'],['15分平均系統受電','630.0 kW','732.2 kW'],['PV直接供給 / BESS放電','0 / 0 kW','0 / 0 kW'],['BESS開始→終了残量','1,200 → 1,200 kWh','1,200 → 1,200 kWh'],['同時に充電する台数','8台','10台'],['充電車両SOC（区間開始）','58.2〜86.8%','52.8〜80.0%'],['その車両の次の営業便発車','05:51〜07:26','05:51〜07:13'],['翌朝出庫までのSOC目標','90%','90%'],['週の受電量のうち0〜6時','86.0%','92.4%']],[480,340,340],{size:22});
const draft=path.join(build,'supplement_draft.pptx');await(await PresentationFile.exportPptx(deck)).save(draft);
await fs.mkdir(path.join(build,'supplement_final'),{recursive:true});
await finalizePresentation({workspaceDir:'C:/master-course',candidatePath:draft,finalPath:path.join(build,'supplement_final/supplement_v2.pptx'),explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[2,3],requiredNativeChartOwnerSlides:[1],materializeLiteralChartWorkbooks:true,pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--require-native-table-slide','2','--require-native-table-slide','3'],fontPolicy:{basis:'reference',families:[font],referencePath:source,referenceSha256:JSON.parse(await fs.readFile(path.join(build,'source_inventory.json'),'utf8')).sha256},verifyArtifactToolImport:true,receiptPath:path.join(build,'supplement_validation_v2.json')});
console.log('Supplement created and validated');



