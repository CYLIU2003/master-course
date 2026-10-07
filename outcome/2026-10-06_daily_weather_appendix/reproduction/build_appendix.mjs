import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const b=process.argv[2];
const rt='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const {Presentation,PresentationFile}=await import(pathToFileURL(rt+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {slides}=JSON.parse(await fs.readFile(b+'/slides.json','utf8'));
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const navy='#202B58',teal='#159A8C',grey='#59687B',brown='#854A30';
function text(s,name,value,x,y,w,h,size,color=navy,bold=false){
 const a=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=value;a.text.style={typeface:'Noto Sans JP',fontSize:size,color,bold,autoFit:'none'};
}
for(const p of slides){
 const s=deck.slides.add();s.background.fill='#FFFFFF';
 text(s,'weather-title',p.title,54,26,1170,65,36,navy,true);
 text(s,'weather-period',p.subtitle,70,105,1140,73,21,grey);
 const tab=s.tables.add({rows:8,columns:6,left:60,top:196,width:1160,height:400,values:p.values,columnWidths:[195,160,225,180,200,200]});
 tab.rows[0].height=64;
 for(let r=1;r<8;r++)tab.rows[r].height=48;
 for(let r=0;r<8;r++)for(let j=0;j<6;j++){
  const a=tab.getCell(r,j);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';
  a.text.style={typeface:'Noto Sans JP',fontSize:r===0?21:24,color:r===0?'#FFFFFF':navy,bold:r===0};
 }
 tab.borders.assign({style:'solid',fill:'#CBD3DD',width:1});
 text(s,'weather-week-sum',p.takeaway,70,607,1140,35,21,teal,true);
 text(s,'weather-definition',p.footnote,70,655,1120,54,16,brown);
 text(s,'weather-page',String(p.number),1211,682,45,24,15,grey);
 s.speakerNotes.textFrame.setText(p.notes);
}
await(await PresentationFile.exportPptx(deck)).save(b+'/appendix.pptx');
console.log('12 editable daily weather tables exported.');
