'use strict';
// Public XY projections of measured replay frames, with the same scale in both panes.
(() => {
 const ns='http://www.w3.org/2000/svg';
 const element=(tag,attrs={})=>{const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);return el;};
 class BranchMap {
  constructor(canvas){this.canvas=canvas;canvas.dataset.renderer='schematic2d';}
  setEpisode(frames,names){this.names=names;this.frames=frames;}
  fit(){this.redraw();}
  redraw(){if(this.last)this.render(...this.last);}
  render(frame,history,options,next=null,t=0){
   this.last=[frame,history,options,next,t];
   const svg=this.canvas;svg.replaceChildren();svg.setAttribute('viewBox','-10 -10 124 124');
   svg.append(element('rect',{x:-10,y:-10,width:124,height:124,fill:'#e7eee6'}));
   const y=v=>100-v;
   const fills={land:'#ced8b8',water:'#8dc7ca',obstacle:'#627569',restricted:'#d9a08b',hazard:'#dec38a',low_connectivity:'#bdc1c3'};
   for(const z of frame.zones){
    const lo=z.geometry.min,hi=z.geometry.max;
    if(!fills[z.type]||!lo||!hi)continue;
    const r=element('rect',{x:lo[0],y:y(hi[1]),width:Math.max(.4,hi[0]-lo[0]),height:Math.max(.4,hi[1]-lo[1]),fill:fills[z.type],opacity:z.type==='low_connectivity'?.45:.85});
    svg.append(r);
   }
   const pos=new Map();
   for(const a of [...frame.agents,...frame.infrastructure]){
    if(!a.position)continue;
    const b=next?.agents.find(b=>b.id===a.id);
    pos.set(a.id,b?.position?a.position.map((v,i)=>v+(b.position[i]-v)*t):a.position);
   }
   if(options.network)for(const link of frame.network.known_links??[]){
    const a=pos.get(link.source),b=pos.get(link.target);if(!a||!b)continue;
    svg.append(element('line',{x1:a[0],y1:y(a[1]),x2:b[0],y2:y(b[1]),stroke:link.kind==='satellite'?'#9364be':'#426c58','stroke-width':link.kind==='satellite'?.6:.3,'stroke-opacity':.5,...(link.kind==='satellite'?{'stroke-dasharray':'2 1'}:{})}));
   }
   if(options.trails)for(const a of frame.agents){
    const points=history.map(f=>f.agents.find(b=>b.id===a.id)?.position).filter(Boolean);
    if(points.length>1)svg.append(element('polyline',{points:points.map(p=>p[0]+','+y(p[1])).join(' '),fill:'none',stroke:'#608a76','stroke-width':.45,'stroke-opacity':.65}));
   }
   for(const target of frame.targets){
    if(target.status==='delivered'||!target.position)continue;
    const [x,yy]=target.position;svg.append(element('rect',{x:x-1,y:y(yy)-1,width:2,height:2,fill:'#d89538',transform:`rotate(45 ${x} ${y(yy)})`}));
   }
   for(const unit of [...frame.infrastructure,...frame.agents]){
    const p=pos.get(unit.id);if(!p)continue;
    const failed=['failed','offline'].includes(unit.status),connected=unit.communication?.connected;
    const fill=failed?'#bb6454':unit.kind==='cosmic'?'#9364be':connected?'#edf8d4':'#df946d';
    const mark=element(unit.kind==='cosmic'?'rect':'circle',unit.kind==='cosmic'?{x:p[0]-1.5,y:y(p[1])-1.5,width:3,height:3}:{cx:p[0],cy:y(p[1]),r:unit.kind==='base_station'?1.7:unit.kind==='aerial'?1.3:1.05});
    for(const [k,v] of Object.entries({fill,stroke:'#304e40','stroke-width':.35}))mark.setAttribute(k,v);
    mark.dataset.agentId=unit.id;
    const title=element('title');title.textContent=(this.names?.get(unit.id)?.name??unit.id)+` · z=${p[2]} · `+(failed?'отказ':connected?'на связи':'нет связи');mark.append(title);svg.append(mark);
    if(unit.kind==='cosmic'||unit.kind==='base_station'){
     const label=element('text',{x:p[0]+2,y:y(p[1])-2,fill:'#304e40','font-size':2.5});label.textContent=unit.kind==='cosmic'?'Спутник · z=60':'База';svg.append(label);
    }
   }
   const note=element('text',{x:0,y:110,fill:'#426453','font-size':2.6});note.textContent='Вид сверху · 100 × 100 м · цвет: связь / отказ';svg.append(note);
  }
 }
 window.AriadnaBranchMap=BranchMap;
})();
