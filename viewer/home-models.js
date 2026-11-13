'use strict';
(() => {
 const T=window.THREE;
 const modelColors={vacuum:'#91b9aa',courier:'#f6b46c',drone:'#75c5e5',repeater:'#b7a1e8'};
 const floorColors={oak:'#d9ad78',terrazzo:'#dad8cd',ceramic:'#65928a'};
 const palette={plaster:'#e9ded0',trim:'#c29d72',steel:'#b5c6c3',panel:'#425c59',sofa:'#748365',desk:'#b17e55'};
 const geometry=z=>z.geometry;
 const point=p=>new T.Vector3(p[0],p[2],-p[1]);

 function doorway(map,zone,closed,flooded){
  const {min,max}=zone.geometry;
  const vertical=max[0]-min[0]<max[1]-min[1];
  const width=vertical?max[1]-min[1]:max[0]-min[0];
  const root=new T.Group();
  root.position.set((min[0]+max[0])/2,0,-(min[1]+max[1])/2);
  root.rotation.y=vertical?Math.PI/2:0;
  map.props.add(root);
  const color=closed?'#bc594f':flooded?'#e8a348':'#6ea98a';
  const wood=map.surface('oak','#bd905e',[2,1],{roughness:.7});
  map.cube(root,[width,.035,.40],[0,.021,0],color);
  for(const side of [-1,1]){
   map.cube(root,[.09,.72,.29],[side*(width/2-.045),.36,0],wood);
   map.cube(root,[.11,.07,.31],[side*(width/2-.045),.76,0],color);
  }
  if(closed){
   map.cube(root,[width-.14,.77,.12],[0,.40,0],map.material('#92504b'));
   map.cube(root,[width-.30,.05,.07],[0,.73,.08],color);
   map.cube(root,[.14,.05,.06],[width*.30,.45,.09],'#e6c283');
  }else{
   // Recessed sliding panel leaves the entire modeled opening free.
   map.cube(root,[.12,.59,.15],[-width/2+.06,.30,0],wood);
  }
 }

 function scene(map,frame) {
  map.scene.background.set('#d4ddd5');
  map.openTop(map.cube(map.terrain,[24.65,.44,16.65],[12,-.28,-8],'#354b46'));
  map.openTop(map.cube(map.terrain,[25.05,.13,17.05],[12,-.56,-8],'#203936'));
  for(const z of frame.zones){
   const {min,max}=geometry(z),w=max[0]-min[0],d=max[1]-min[1],h=max[2]-min[2];
   const x=(min[0]+max[0])/2,y=(min[1]+max[1])/2,kind=z.appearance?.kind;
   if(kind==='home_door'){
    const barriers=frame.zones.filter(other=>other.appearance?.door_id===z.id);
    doorway(map,z,barriers.some(other=>other.appearance.kind==='home_private'),barriers.some(other=>other.appearance.kind==='home_wet'));
    continue;
   }
   if(kind==='home_private'&&z.appearance.door_id)continue;
   if(kind==='home_floor'){
    const name=z.appearance.material;
    const floor=map.surface(name,floorColors[name],[w/3,d/3],{roughness:name==='ceramic'?.32:.68,bumpScale:.025});
    const mesh=map.mesh(map.terrain,new T.PlaneGeometry(w,d,...(map.software?[Math.ceil(w/2),Math.ceil(d/2)]:[1,1])),floor,x,.005,-y);
    mesh.rotation.x=-Math.PI/2;
    continue;
   }
   if(kind==='home_wet'||kind==='home_private'){
    const surface=kind==='home_wet'?
     map.surface('water','#52afbc',[Math.max(1,w/1.2),Math.max(1,d/1.2)],{transparent:true,opacity:.68,roughness:.2,depthWrite:false}):
     map.material('#d88d6b',{transparent:true,opacity:.58,depthWrite:false});
    const mesh=map.mesh(map.props,new T.PlaneGeometry(w,d),surface,x,.035,-y);
    mesh.rotation.x=-Math.PI/2;
    mesh.renderOrder=5;
    const border=[[min[0],min[1],.05],[max[0],min[1],.05],[max[0],max[1],.05],[min[0],max[1],.05],[min[0],min[1],.05]];
    const line=new T.Line(new T.BufferGeometry().setFromPoints(border.map(point)),new T.LineDashedMaterial({color:'#a35931',dashSize:.23,gapSize:.14}));
    line.computeLineDistances();map.props.add(line);
    continue;
   }
   if(!kind?.startsWith('home_')||kind==='home_floor')continue;
   const root=new T.Group();root.position.set(x,min[2],-y);map.props.add(root);
   const box=(size,p,material)=>map.cube(root,size,p,material);
   if(kind==='home_wall'){
    const height=map.cutaway?.19:.48;
    box([w,height,d],[0,height/2,0],palette.plaster);
    box([w+.025,.045,d+.025],[0,height+.023,0],palette.trim);
   } else if(kind==='home_sofa'){
    const fabric=map.surface('weave',palette.sofa,[3,2],{roughness:.9,bumpScale:.04});
    box([w,.26,d],[0,.19,0],fabric);
    box([w,.53,.24],[0,.56,d/2-.13],fabric);
    for(const side of [-1,1])box([.25,.38,d],[side*(w/2-.13),.43,0],fabric);
    for(let i=-1;i<=1;i++)box([w*.25,.15,d*.68],[i*w*.25,.36,-.06],map.surface('weave','#8e9a79',[2,2]));
    box([.47,.13,.38],[-.75,.54,.31],map.surface('weave','#e7c9a8',[2,2])).rotation.y=.17;
   } else if(kind==='home_fridge'||kind==='home_washer'){
    const metal=map.surface('metal',palette.steel,[2,2],{roughness:.36,metalness:.35});
    box([w,h,d],[0,h/2,0],metal);
    const front=d/2+.025;
    if(kind==='home_fridge'){
     box([w*.9,.018,.035],[0,h*.65,front],palette.panel);
     box([.045,.42,.07],[-w*.32,h*.44,front+.05],palette.panel);
    }else{
     const ring=map.cylinder(root,.32,.32,.06,[0,h*.46,front],palette.panel,24);
     ring.rotation.x=Math.PI/2;
     const glass=map.cylinder(root,.24,.24,.067,[0,h*.46,front+.014],'#477779',24);
     glass.rotation.x=Math.PI/2;
     box([.39,.065,.035],[w*.24,h*.81,front],'#8dccbd');
    }
   } else if(kind==='home_bookcase'){
    box([w,h,.1],[0,h/2,-d/2+.06],palette.desk);
    for(const side of [-1,1])box([.12,h,d],[side*(w/2-.06),h/2,0],palette.desk);
    for(let i=0;i<4;i++){
     box([w,.09,d],[0,.1+i*.55,0],palette.desk);
     for(let n=0;n<3;n++)box([.12,.29+(n%2)*.08,d*.66],[-w*.27+n*.18,.28+i*.55,0],['#ac714f','#58776b','#d3b98d'][n]);
    }
   } else {
    const top=kind==='home_counter'?map.surface('terrazzo','#e3ddca',[3,2],{roughness:.48}):
     map.surface('oak',palette.desk,[2,1],{roughness:.65});
    box([w,.10,d],[0,h-.05,0],top);
    if(kind==='home_counter'){
     box([w*.97,h-.11,d*.95],[0,(h-.11)/2,0],palette.panel);
     for(const offset of [-.24,0,.24])box([w*.16,.026,.045],[w*offset,h*.72,d/2+.018],'#c9b088');
    }else{
     for(const dx of [-1,1])for(const dz of [-1,1])box([.12,h-.1,.12],[dx*w*.38,(h-.1)/2,dz*d*.33],palette.panel);
    }
   }
  }
  for(const unit of frame.infrastructure){
   if(!Array.isArray(unit.position))continue;
   const root=new T.Group();root.position.copy(point(unit.position));map.props.add(root);
   const signal=unit.status==='failed'||!unit.communication?.connected?'#d26757':'#7fcea7';
   if(unit.kind==='charging_station'){
    map.cube(root,[.72,.09,.55],[0,.06,0],'#314c47');
    map.cube(root,[.72,.21,.11],[0,.16,-.2],'#49675c');
    map.cube(root,[.33,.015,.03],[0,.115,.12],signal);
   }else{
    map.cube(root,[.43,.17,.35],[0,.1,0],'#e6e9d8');
    map.cube(root,[.21,.04,.075],[0,.204,0],signal);
    if(unit.kind!=='sensor_node'){
     map.cylinder(root,.025,.03,.34,[-.14,.32,0],'#405654',7);
     map.cylinder(root,.025,.03,.28,[.14,.29,0],'#405654',7);
    }
   }
  }
 }

 function vehicle(map,agent) {
  const model=agent.appearance?.model;
  if(!modelColors[model])return null;
  const g=new T.Group();
  g.userData.agentId=agent.id;
  g.userData.rotors=[];
  const color=modelColors[model],base='#30413e';
  const tile=map.surface('rubber',base,[2,1],{roughness:.81,bumpScale:.022});
  if(model==='vacuum'){
   map.cylinder(g,.31,.31,.14,[0,.12,0],tile,24);
   map.cylinder(g,.29,.31,.035,[0,.205,0],color,24);
   map.cylinder(g,.065,.065,.065,[-.10,.24,.08],base,14);
   map.cube(g,[.09,.013,.09],[.11,.232,-.09],'#d8f3e4');
  }else if(model==='drone'){
   map.sphere(g,.14,[0,.055,0],color,2).scale.set(1.2,.55,1);
   for(const x of [-.22,.22])for(const z of [-.22,.22]){
    const rotor=new T.Group();rotor.position.set(x,.06,z);g.add(rotor);
    const rim=map.mesh(g,new T.TorusGeometry(.122,.022,7,16),map.material(base),x,.06,z);
    rim.rotation.x=Math.PI/2;
    map.cube(rotor,[.18,.015,.036],[0,0,0],color);
    g.userData.rotors.push(rotor);
   }
  }else{
   map.cube(g,[.43,.16,.55],[0,.17,0],color);
   for(const x of [-.21,.21])for(const z of [-.19,.19]){
    map.cylinder(g,.092,.092,.08,[x,.091,z],tile,12).rotation.z=Math.PI/2;
   }
   if(model==='courier'){
    map.cube(g,[.36,.19,.36],[0,.33,.018],'#d79d67');
    map.cube(g,[.35,.017,.07],[0,.438,.017],'#e9d6a4');
   }else{
    map.cylinder(g,.027,.035,.43,[0,.44,0],base,8);
    map.sphere(g,.065,[0,.69,0],color,1);
   }
   map.cube(g,[.27,.035,.02],[0,.20,-.282],'#f7e1a9');
  }
  const body=agent.constraints?.find(limit=>limit.body)?.body;
  if(body){
   const size=body.max.map((end,i)=>end-body.min[i]);
   const geometry=new T.BoxGeometry(size[0],size[2],size[1]);
   const outline=new T.LineSegments(new T.EdgesGeometry(geometry),new T.LineBasicMaterial({color:'#e6a64d'}));
   geometry.dispose();
   outline.position.y=(body.min[2]+body.max[2])/2;
   outline.visible=false;
   outline.raycast=()=>{};
   g.add(outline);
   g.userData.bodyOutline=outline;
  }
  const halo=map.mesh(g,new T.RingGeometry(.43,.48,36),new T.MeshBasicMaterial({color:'#f1be64',side:T.DoubleSide,depthTest:false}),0,.032,0);
  halo.rotation.x=-Math.PI/2;halo.userData.selection=true;halo.visible=false;
  return g;
 }

 window.AriadnaHomeModels={scene,vehicle};
})();
