import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const b=process.argv[2];
const rt='C:/Users/RTDS_admin/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const {Presentation,PresentationFile}=await import(pathToFileURL(rt+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const edit=JSON.parse(await fs.readFile(b+'/edits.json','utf8'));
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const navy='#202B58',teal='#159A8C',grey='#59687B',brown='#854A30';
function text(s,name,value,x,y,w,h,size,color=navy,bold=false){
 const a=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 a.text=value;a.text.style={typeface:'Noto Sans JP',fontSize:size,color,bold,autoFit:'none'};return a;
}
for(const p of edit.pages){
 const s=deck.slides.add();s.background.fill='#FFFFFF';
 text(s,'revision-title',p.title,54,26,1170,65,p.title_size??36,navy,true);
 text(s,'revision-subtitle',p.subtitle,70,105,1140,73,p.subtitle_size??22,grey);
 text(s,'revision-takeaway',p.takeaway,70,p.takeaway_y??600,1140,p.takeaway_h??55,p.takeaway_size??23,teal,true);
 text(s,'revision-footnote',p.footnote,70,661,1120,39,p.footnote_size??16,brown);
 if(p.mechanism)text(s,'revision-mechanism',p.mechanism,70,574,1140,30,21,navy);
 if(p.table){
  const c=p.table,tab=s.tables.add({rows:c.values.length,columns:c.values[0].length,left:c.x??60,top:c.y??180,width:c.w??1160,height:c.h??396,values:c.values,columnWidths:c.widths});
  for(let r=0;r<c.values.length;r++)for(let j=0;j<c.values[0].length;j++){
   const a=tab.getCell(r,j);a.fill=r===0?navy:r%2?'#F1F5F8':'#FFFFFF';a.text.style={typeface:'Noto Sans JP',fontSize:c.size??22,color:r===0?'#FFFFFF':navy,bold:r===0};
  }
  tab.borders.assign({style:'solid',fill:'#CBD3DD',width:1});
 }
 s.speakerNotes.textFrame.setText(p.notes);
}
await(await PresentationFile.exportPptx(deck)).save(b+'/authored_elements.pptx');
console.log('Three Claude-authored editable page revisions exported.');
