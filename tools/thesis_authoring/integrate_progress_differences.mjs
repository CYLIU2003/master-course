import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import crypto from 'node:crypto';

const root=path.resolve(import.meta.dirname,'../..');
const runtime='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const skill='C:/Users/RTDS_admin/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {Presentation,PresentationFile,FileBlob}=await import(pathToFileURL(path.join(runtime,'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const {default:JSZip}=await import(pathToFileURL(path.join(runtime,'node/node_modules/jszip/lib/index.js')).href);
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const output=path.join(root,'outcome/2026-09-06_speaker_notes');
const build=path.join(root,'output/progress_differences_build_20260906_v2');
await fs.mkdir(build,{recursive:true});
const source=path.join(output,'august_progress_with_speaker_notes_20260906.pptx');
const sourceBytes=await fs.readFile(source);
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const family='Meiryo', navy='#202B58', teal='#159A8C';
const evidence='出典：outcome/2026-09-06_speaker_notes/README.md、outcome/2026-09-05_research_progress/02_findings.md、docs/evidence/weather_dispatch_rerun_bb0c005/result_summary.json。実験SHA bb0c005。';
const pages=[
 {number:8,title:'前回から進んだこと',subtitle:'太陽光の条件を変えたときの違いを、具体的な運用で説明できるようにした',
 headers:['以前の課題','行った作業','確認できたこと'],rows:[
 ['ほぼ1案だけを詳しく評価\n高低PVでも同じ配車','22案の担当便と\n充電計画を比較','電気バスの担当が\n高PV 199便／低PV 91便'],
 ['一日の合計だけでは\n途中の矛盾が見えにくい','1時間ずつ計画を更新\n15分ごとの状態を検算','両条件で264便を担当\n電池・電力・費用も確認'],
 ['台数と総額だけでは\n違いの中身が分からない','同じ便を照合し\n電力と費用を分解','変わった108便と\n費用差の内訳を特定']],
 takeaway:'進捗：計画を比べ、その違いと確認範囲を説明できるようになった',
 caveat:'以前の状態は元の月次報告による。旧方式への速度・費用の改善率は未検証。',
 notes:'ここが今回の進捗の全体像です。左が以前の課題、中央が実際に行った作業、右がその結果です。以前はほぼ一つの配車を詳しく評価し、高低PVで同じ案になると月次資料で報告していました。そこで候補を22案へ増やし、充電まで評価して選ぶようにしました。この二条件では、電気バスの担当が199便と91便に分かれました。また、合計だけでなく時間ごとの電池と電力を検算しました。さらに既存結果を便単位で照合して、変更した108便を特定しました。これは研究の作業と到達点の差分です。同じ条件で旧方式を再実験した性能比較ではないため、何％速くなったとは言いません。次に、作業の順番を説明します。'},
 {number:9,title:'問題に対して、何をどう直したか',subtitle:'8月に計画を作り直し、9月5日にその結果を詳しく読み解いた',
 headers:['時期・目的','具体的な作業','その作業が必要な理由'],rows:[
 ['8月：比較方法を直す','複数の担当便案を作り\n各案の充電まで計算','一つの案だけでは\n他の選択肢と比べられない'],
 ['8月：条件をそろえる','同じ264便・車両・設備で\n太陽光の曲線だけを変更','運行条件の違いを\n太陽光の効果と混同しない'],
 ['8月：一日を確かめる','入力を確定して再計算\n24回の更新と費用を検算','途中の電池不足や\n金額の食い違いを見落とさない'],
 ['9月5日：理由を調べる','既存結果を便ごと・15分ごと\nに照合し、費用も分解','どの便が変わり、何が\n費用差につながったかを示す']],
 takeaway:'9月5日の追加分は、保存済みの計算結果を詳しく分析した成果',
 caveat:'9月5日および今回の資料更新では、新しい最適化実験を行っていない。',
 notes:'作業は目的を分けて進めました。8月には、比較する配車案を増やし、各案について充電できるかと評価額を計算しました。次に、太陽光以外の入力をそろえました。そうしないと、ダイヤや車両の違いによる結果を太陽光の違いと思い込んでしまいます。その条件で計算し直し、一時間ずつ進めた24回の更新と一日の費用を確認しました。9月5日は、新しい計画を求めたのではなく、保存済みの結果を便ごと、15分ごとに読み直しました。これで、合計値の裏側にある担当便と電力、費用を説明できるようになりました。'},
 {number:14,title:'追加分析で、結果の中身が分かった',subtitle:'9月5日の進捗：同じ結果を、便・時間・費用の内訳まで確認',
 headers:['これまでの説明','追加で調べたこと','新しく分かったこと'],rows:[
 ['電気バスの担当便数が違う','両条件で同じ便を\n1便ずつ対応付けた','エンジンから電気へ108便\n渋22：78便／渋23：30便'],
 ['太陽光が3,373 kWh余る','15分ごとの未利用電力と\n充電の有無を重ねた','抑制量の75.06%が未充電枠\n原因の特定はまだ必要'],
 ['評価額が約3.8万円違う','同じ費用と\n変化した費用を分けた','車両使用費64万円は共通\n差額の約88%は燃料費']],
 takeaway:'「違いがある」に加え、「どこが違うか」まで具体的に示せた',
 caveat:'抑制＝使わなかった太陽光。未充電だから車両不在、とは断定できない。',
 notes:'ここが9月5日の追加分析で新しく分かった部分です。最初は電気バスの便数が違うという説明でしたが、同じ便を一つずつ比べると、低PVでエンジン担当だった108便が高PVで電気担当に変わっていました。内訳は渋22の78便と渋23の30便です。次に、使わなかった太陽光を15分ごとに調べると、その75.06％が充電電力のない枠で発生していました。ただし、なぜ充電していなかったかまでは特定できていません。最後に費用を分けると、両条件に共通する車両使用費64万円があり、差額約3万8千円の約88％は燃料費でした。単に結果の合計を示す段階から、違いの場所と内訳を説明する段階へ進みました。'},
 {number:16,title:'確認できたことと、まだ分からないこと',subtitle:'動く計画ができたことと、最もよい計画であることは別の確認',
 headers:['確認できたこと','まだ分からないこと'],rows:[
 ['同じ264便を、両方の太陽光条件で担当\n電池・充電器・電力の条件を検算','全ての配車の中で最も安いか\n22候補の外には、よりよい案があるか'],
 ['採用した計画の一日の評価額と\n燃料費などの内訳を確認','単純な方法よりどれだけよいか\n実際の営業所でも同じ効果があるか'],
 ['どの便が変わり、いつ太陽光が余るか\nを具体的に示した','なぜその便を選び、その時間に余るか\n原因を分けた検証はまだ必要']],
 takeaway:'現時点の結論：二条件で、異なる実行可能な計画と説明材料を得た',
 caveat:'最適性・一般的な天候効果は未証明。設備費・劣化費・運転士費は評価額に含まない。',
 notes:'ここは、できたことと未確認のことを分けてお伝えするページです。両方の太陽光条件で全便を担当し、電池や充電器などの条件を守る計画を確認しました。金額の内訳も確認できました。しかし、全ての配車の中で一番安いかは分かりません。単純な方法より優れるか、実際の営業所でも同じ結果になるかも別に検証する必要があります。太陽光が余った時間は分かりましたが、原因の特定には追加比較が必要です。なお、配車段階の認証gapは高PV約9.52％、低PV約1.66％で、最終費用全体の誤差率ではありません。人間のレビューや発表承認も、計算の検算とは別の確認です。'},
 {number:17,title:'次の検証で、何を確かめるか',subtitle:'残る疑問ごとに、比較する条件を分けて決める',
 headers:['残る疑問','次に行う作業','分かるようにしたいこと'],rows:[
 ['現在の方法は\nどの程度よい答えか','8・12・24便で\n一体型の参照方法と比較','小さな問題での\n評価額と計算時間の違い'],
 ['候補や時間を増やすと\n選ぶ案は変わるか','候補範囲と計算時間を\n一つずつ変える','同じ案を選び続けるか\n費用がどれだけ変わるか'],
 ['太陽光が余る原因は何か','配車を固定するなど\n比較条件を決めて検証','車両の所在や残量条件等の\n影響を切り分ける']],
 takeaway:'指導教員への相談：比較範囲・費用項目・許容する差を決めてから実行',
 caveat:'いずれも今後の検証。追加実験は承認後に実施する。最適性や原因を先に決めつけない。',
 notes:'次の作業は、残った疑問と対応させています。まず、小さな8便、12便、24便の問題で、現在の二段階方式と配車と電力を一体で考える参照方法を比べます。目的の定義にも違いがあるため、金額差を全て二段階に分けた影響とは呼びません。次に、候補範囲と計算時間を一つずつ変えて、選ぶ案と費用がどう変わるかを確認します。低PVは次点の前日評価額との差が約567円だったため、この確認が必要です。太陽光が余る原因も、配車などを固定した比較の条件を決めて切り分けたいと考えています。今日は、比較の範囲、費用に含める項目、どの程度の差を許容するかをご相談したいです。追加実験は承認後に行います。'},
];
function text(slide,value,left,top,width,height,size,color=navy,bold=false){
 const shape=slide.shapes.add({geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;shape.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'};
}
for(const page of pages){
 const s=deck.slides.add();s.background.fill='#FFFFFF';
 text(s,page.title,44,25,1192,64,36,navy,true);
 text(s,page.subtitle,60,101,1160,60,25,'#59687B');
 const values=[page.headers,...page.rows];
 const table=s.tables.add({rows:values.length,columns:page.headers.length,left:60,top:180,width:1160,height:365,values,columnWidths:page.headers.length===2?[580,580]:[365,385,410]});
 for(let r=0;r<values.length;r++)for(let c=0;c<page.headers.length;c++){
  const cell=table.getCell(r,c);cell.fill=r===0?navy:(r%2?'#F1F5F8':'#FFFFFF');
  cell.text.style={typeface:family,fontSize:25,color:r===0?'#FFFFFF':navy,bold:r===0};
 }
 table.borders.assign({style:'solid',fill:'#DDE4EB',width:1});
 text(s,page.takeaway,60,571,1160,65,27,teal,true);
 text(s,page.caveat,60,645,1160,40,18,'#7E4D36');
 text(s,`${page.number}/18`,1170,685,90,30,12,'#66748B');
 s.speakerNotes.textFrame.setText(`【話す内容】\n${page.notes}\n\n【出典】\n${evidence}`);
}
const authored=path.join(build,'replacement-slides.pptx');
await(await PresentationFile.exportPptx(deck)).save(authored);
const zip=await JSZip.loadAsync(sourceBytes), replacements=await JSZip.loadAsync(await fs.readFile(authored));
const changed=[];
for(let i=0;i<pages.length;i++){
 const slideName=`ppt/slides/slide${pages[i].number}.xml`;
 zip.file(slideName,await replacements.file(`ppt/slides/slide${i+1}.xml`).async('nodebuffer'));changed.push(slideName);
 const noteName=`ppt/notesSlides/notesSlide${pages[i].number}.xml`;
 const original=await zip.file(noteName).async('string');
 const generated=await replacements.file(`ppt/notesSlides/notesSlide${i+1}.xml`).async('string');
 const body=xml=>[...xml.matchAll(/<p:sp[ >][\s\S]*?<\/p:sp>/g)].find(m=>/<p:ph\b[^>]*\btype="body"/.test(m[0]))?.[0];
 const oldBody=body(original),newBody=body(generated);
 if(!oldBody||!newBody)throw new Error('Missing notes body');
 zip.file(noteName,original.replace(oldBody,oldBody.replace(/<p:txBody>[\s\S]*?<\/p:txBody>/,newBody.match(/<p:txBody>[\s\S]*?<\/p:txBody>/)[0])));changed.push(noteName);
}
const candidatePath=path.join(build,'candidate.pptx');
await fs.writeFile(candidatePath,await zip.generateAsync({type:'nodebuffer'}));
const finalPath=path.join(output,'progress_differences_integrated_20260906.pptx');
await finalizePresentation({workspaceDir:root,candidatePath,finalPath,explicitTotalSlideCount:18,
 requiredNativeTableOwnerSlides:pages.map(p=>p.number),
 pythonExecutable:path.join(runtime,'python/python.exe'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000',...pages.flatMap(p=>['--require-native-table-slide',String(p.number)])],verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
const finalBytes=await fs.readFile(finalPath),finalZip=await JSZip.loadAsync(finalBytes),originalZip=await JSZip.loadAsync(sourceBytes);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
for(const [name,item]of Object.entries(originalZip.files))if(!item.dir&&!changed.includes(name)){
 if(!finalZip.file(name)||(await item.async('nodebuffer')).compare(await finalZip.file(name).async('nodebuffer'))!==0)throw new Error(`Unexpected change: ${name}`);
}
if(sha(sourceBytes)!==sha(await fs.readFile(source)))throw new Error('Source changed');
await fs.writeFile(path.join(build,'preservation.json'),JSON.stringify({source_sha256:sha(sourceBytes),final_sha256:sha(finalBytes),changed},null,2));
await fs.writeFile(path.join(build,'pages.json'),JSON.stringify(pages,null,2));
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<18;i++){
 const png=await finalDeck.slides.getItem(i).export({format:'png',scale:1});
 await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
console.log(finalPath);
