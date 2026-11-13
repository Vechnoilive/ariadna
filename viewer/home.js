'use strict';
(() => {
 const $=id=>document.getElementById(id);
 const text=(id,value)=>{$(id).textContent=value??'—';};
 const node=(tag,value,cls)=>{
  const element=document.createElement(tag);
  if(value!==undefined)element.textContent=String(value);
  if(cls)element.className=cls;
  return element;
 };
 const svgNS='http://www.w3.org/2000/svg';
 const svg=(tag,attributes)=>{
  const element=document.createElementNS(svgNS,tag);
  for(const [key,value] of Object.entries(attributes??{}))element.setAttribute(key,value);
  return element;
 };
 function icon(name){
  const element=svg('svg',{'aria-hidden':'true'});
  element.append(svg('use',{href:'#h-'+name}));
  return element;
 }
 const labels={
  pages:{overview:'Сценарии',live:'Операция',fleet:'Устройства',decisions:'Решения',compare:'Развилка'},
  status:{active:'В строю',failed:'Отказ',degraded:'Ограничен',safe_mode:'Режим резерва',offline:'Отключён',success:'Выполнено',time_limit:'Лимит времени',safe_stopped:'Безопасная остановка',running:'Выполняется'},
  modes:{portable:'Метаконтроллер',fixed:'Фиксированный сценарий',reactive:'Реактивный контроллер'},
  role:{scout:'Разведка',executor:'Исполнитель',verifier:'Подтверждение',relay:'Ретранслятор',coordinator:'Координатор',holding:'Удержание',charging:'Зарядка',returning:'Возврат',beneficiary:'Восстановление связи'},
  event:{restricted_zone_appeared:'Протечка перекрыла проход',infrastructure_failure:'Отказ узла',agent_failure:'Отказ робота',connectivity_loss:'Потеря канала',resource_shortage:'Дефицит энергии',stale_information:'Устаревший сигнал',contradictory_information:'Расхождение сигналов',operator_directive:'Директива оператора',mission_priority_change:'Новый приоритет',target_detected:'Запрос помощи'},
  action:{move:'Перемещение',observe:'Проверка цели',deliver:'Доставка',send_message:'Сообщение',relay:'Ретрансляция',charge:'Зарядка'},
  operation:{keep:'Продолжить текущий план',select:'Выбрать план',switch:'Переключить сценарий',modify:'Уточнить конфигурацию',compose:'Совместить сценарии',synthesize:'Собрать новый план',safe_stop:'Безопасно остановить рой'},
  scenario:{coverage_search:'Поиск по секторам',priority_service:'Приоритетная помощь',relay_coalition:'Коалиция связи',safe_degradation:'Энергорезерв',coordination_reconfiguration:'Смена координатора'},
  devices:{ground:'Наземный робот',aerial:'Мини-дрон',digital:'Цифровой штаб',operator:'Человек-оператор',sensor_node:'Сенсор',relay:'Ретранслятор',base_station:'Шлюз',charging_station:'Зарядный док'},
  plans:{meta:'Метаплан',frontier:'План разведки',nearby:'Ближняя задача',reserve:'Сохранение резерва'},
  primitives:{recover:'Сохранить ресурс',relay:'Восстановить связь',confirm:'Подтвердить цель',deliver:'Доставить помощь',coordinate:'Сменить координатора',search:'Поиск'},
  graph:{completed:'выполнено',running:'в работе',waiting:'ожидает зависимость'},
 };
 const briefs={
  leak:{label:'Протечка',tone:'water',icon:'network',copy:'Проведите взглядом курьера от залитой двери до вентиля.'},
  blackout:{label:'Потеря связи',tone:'power',icon:'branch',copy:'Проследите, кто вернёт связь и привезёт фонарь.'},
  privacy:{label:'Граница доступа',tone:'privacy',icon:'decision',copy:'Посмотрите, как роботы реагируют на закрытие дверей.'},
 };
 const tourSteps=[
  {target:'campaign',title:'Выберите сценарий',description:'В каждой карточке своя задача. Для примера откроем протечку.',before:()=>go('overview')},
  {target:'home-map-panel',title:'Осмотрите квартиру',description:'Перетащите карту для вращения. Цвет порога показывает, открыта ли дверь и можно ли через неё проехать.',before:()=>{selectCase('leak');const wet=state.eventStops.find(stop=>stop.title==='Вход залит');if(wet)seek(wet.index);}},
  {target:'incident-links',title:'Перейдите к событию',description:'Кнопки переносят к затоплению, обходу и доставке ключа.',before:()=>go('live')},
  {target:'home-player',title:'Управляйте повтором',description:'Запустите запись, поставьте её на паузу или передвиньте ползунок.',before:()=>go('live')},
  {target:'decision-times',title:'Посмотрите решение штаба',description:'Выберите момент, чтобы увидеть план, команды и проверки.',before:()=>go('decisions')},
  {target:'branch-choice',title:'Сравните планы',description:'Планы начинают из одного состояния. Выберите альтернативу и двигайте шкалу.',before:()=>go('compare')},
 ];
 const get=(group,key)=>labels[group]?.[key]??key??'—';
 const pct=value=>Number.isFinite(value)?Math.round(value*100)+'%':'—';
 const num=value=>Number.isFinite(value)?value.toFixed(3):'—';
 const actor=unit=>unit?.appearance?.name??unit?.id??'—';
 const badge=(value,tone='')=>node('span',value,'tag'+(tone?' '+tone:''));
 const state={page:'overview',data:null,caseId:'leak',trace:null,index:0,filter:'mobile',branch:'',branchIndex:0,
  map:null,links:false,busy:false,playing:false,animation:0,selected:null,eventFrames:null,eventStops:[],beats:[]};

 function error(message){
  text('app-error',message);
  $('app-error').hidden=!message;
 }
 function current(){return state.trace?.frames[state.index];}
 function entities(frame=current()){return frame?[...frame.agents,...frame.infrastructure]:[];}
 function name(id){return actor(entities().find(a=>a.id===id)??{id});}
 function currentDecision(){return state.trace?.decisions.find(d=>d.time===current()?.time);}
 function status(value){return get('status',value);}
 function eventTitle(event){
  if(event.source==='physics')return 'Столкновение';
  if(event.parameters?.appearance?.kind==='home_private')return 'Доступ к комнате закрыт';
  return get('event',event.type);
 }
 function eventAt(events){
  return events.find(item=>item.source==='physics')??events.find(item=>item.type==='contradictory_information')??
   events.find(item=>item.type!=='operator_directive')??events[0];
 }

 function route(){
  const next=location.hash.slice(1);
  const page=Object.hasOwn(labels.pages,next)?next:'overview';
  if(page!==state.page){
   pause();
   state.page=page;
   window.scrollTo(0,0);
  }
  for(const id of Object.keys(labels.pages))$('page-'+id).hidden=id!==page;
  for(const link of document.querySelectorAll('[data-page]')){
   const active=link.dataset.page===page;
   link.classList.toggle('active',active);
   if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  text('page-label',labels.pages[page]);
  render();
 }
 function go(page){
  if(location.hash!=='#'+page)location.hash=page;
  route();
 }

 function ensureMap(){
  if(state.map)return;
  state.map=new window.AriadnaMap($('home-map'),{onSelect:id=>selectAgent(id)});
 }
 function selectAgent(id,focus=false){
  state.selected=id||null;
  state.map?.select(state.selected,Boolean(id&&focus&&state.map.volume));
  renderSelected();
 }
 function renderSelected(){
  const selected=current()?.agents.find(a=>a.id===state.selected);
  $('map-agent').value=selected?.id??'';
  $('map-selected').hidden=!selected;
  if(selected)text('map-selected',[actor(selected),status(selected.status),selected.role&&get('role',selected.role)].filter(Boolean).join(' · '));
 }
 function mapMode(top){
  if(!state.map)return;
  state.map.volume=!top;
  state.map.controls.enableRotate=!top;
  state.map.controls.mouseButtons.LEFT=top?window.THREE.MOUSE.PAN:window.THREE.MOUSE.ROTATE;
  state.map.controls.touches.ONE=top?window.THREE.TOUCH.PAN:window.THREE.TOUCH.ROTATE;
  state.map.follow=false;
  $('map-top').setAttribute('aria-pressed',String(top));
  text('map-gesture',top?'Перетащите, чтобы сдвинуть':'Перетащите, чтобы повернуть');
  state.map.redraw();
 }
 function drawMap(next=null,fraction=0){
  const frame=current();
  if(!frame||state.page!=='live')return;
  ensureMap();
  if(state.map.trace!==state.trace){
   state.map.trace=state.trace;
   state.map.setEpisode(state.trace.frames,new Map(frame.agents.map(a=>[a.id,{name:actor(a)}])));
   const mobile=frame.agents.filter(a=>Array.isArray(a.position));
   $('map-agent').replaceChildren(option('','Все роботы'),...mobile.map(a=>option(a.id,actor(a))));
   $('room-legend').replaceChildren(...frame.zones.filter(z=>z.appearance?.kind==='home_floor').map(z=>node('span',z.appearance.label)));
   if(state.selected)state.map.select(state.selected);
   mapMode(false);
   state.map.fit(false);
  }
  const history=state.trace.frames.slice(0,state.index+1);
  const beat=state.beats.findLast(moment=>moment.index<=state.index);
  const blackout=state.caseId==='blackout'&&frame.events.some(event=>event.type==='infrastructure_failure');
  const wet=state.caseId==='leak'&&frame.zones.some(zone=>zone.appearance?.kind==='home_wet');
  const route=wet&&!state.busy?state.trace.frames.map(item=>item.agents.find(agent=>agent.id==='carrier_b').position):null;
  const tracked=state.selected??beat?.agent??null;
  $('scene-note').hidden=!wet&&!blackout;
  if(wet)text('scene-note','Пунктир · маршрут «Термоса» из записи');
  if(blackout)text('scene-note',state.links?'Радиоканалы после отключения':'Аварийное освещение');
  state.map.render(frame,history,{network:state.links,trails:false,track:tracked,route,blackout,labels:false,zones:true},next,fraction);
 }
 function selectCase(id,show=true){
  if(state.busy)return;
  const trace=id==='impact'?state.data?.impact_demo:state.data?.episodes.find(entry=>entry.id===id);
  if(!trace)return;
  pause();
  state.caseId=id;
  state.links=id==='blackout';
  $('map-links').setAttribute('aria-pressed',String(state.links));
  state.trace=trace;
  state.index=0;
  state.selected=null;
  $('case').value=id;
  error('');
  const impact=id==='impact';
  $('seed').value=state.data.results.find(r=>r.case===id&&r.mode==='portable')?.seed??'';
  $('evidence-link').hidden=true;
  $('run-tools').hidden=impact;
  $('decision-link').hidden=impact;
  text('live-status',impact?'Контрольная запись':'Проверенная запись');
  if(show)go('live');
  else render();
 }
 function decisionReason(decision){
  const reasons=decision?.explanation?.reason_codes??[];
  if(reasons.includes('mandatory_safe_response'))return 'Штаб выполнил команду оператора и остановил рой.';
  if(reasons.includes('verify_before_delivery'))return 'Сначала подтвердить цель, затем доставить помощь.';
  if(reasons.includes('unsafe_commands_filtered'))return 'Штаб исключил команды, которые нарушают ограничения.';
  return {
   compose:'Штаб объединил несколько сценариев.',
   switch:'Штаб переключил сценарий работы.',
   synthesize:'Штаб собрал план из отдельных действий.',
   modify:'Штаб уточнил распределение задач.',
   select:'Штаб выбрал план.',
   keep:'Роботы продолжают текущий план.',
  }[decision?.operation]??'';
 }
 function renderStory(frame,decision){
  const finished=state.index===state.trace.frames.length-1&&state.trace.summary&&state.trace.id!=='impact';
  const event=eventAt(frame.events.filter(event=>event.time===frame.time));
  const impact=event?.source==='physics';
  const beat=state.beats.findLast(moment=>moment.index<=state.index);
  let stage='Сейчас', headline='Роботы выполняют задачи', response=decisionReason(decision);
  if(impact){
   stage='Авария';
   headline=eventTitle(event);
   response=event.targets.map(name).join(', ')+' · выход из строя';
  }else if(finished&&!['success','safe_stopped'].includes(state.trace.summary.status)){
   stage='Итог';
   headline=status(state.trace.summary.status);
   response='Часть задач осталась незавершённой.';
  }else if(beat){
   stage=finished?'Итог':beat.index===0?'Начало':'Сейчас';
   headline=beat.title;
   response=beat.copy;
  }else if(finished){
   stage='Итог';
   headline=status(state.trace.summary.status);
   response={success:'Все задачи операции выполнены.',safe_stopped:'Роботы прекратили выполнение задач.'}[state.trace.summary.status]??'';
  }else if(event){
   stage='Событие';
   headline=eventTitle(event);
  }else if(state.index===0){
   stage='Начало';
   headline=state.trace.id==='impact'?'Команда отправлена пылесосу':'Роботы приступают к работе';
  }else if(decision){
   headline=get('operation',decision.operation);
  }
  text('story-stage',stage);
  text('story-title',headline);
  $('story-stage').classList.toggle('impact',impact);
  $('story-response').hidden=!response;
  text('story-response',response);
 }
 function renderStops(){
  const frames=state.trace.frames;
  if(frames!==state.eventFrames||state.eventBusy!==state.busy){
   state.eventFrames=frames;
   state.eventBusy=state.busy;
   state.beats=window.AriadnaHomeStory.beats(state.caseId,frames);
   state.eventStops=state.beats.length?state.beats.slice():[{index:0,title:'Начало'}];
   const seen=new Set();
   if(!state.beats.length)frames.forEach((frame,index)=>{
    const events=frame.events.filter(event=>!seen.has(event.id));
    events.forEach(event=>seen.add(event.id));
    if(!index||!events.length)return;
    const event=eventAt(events);
    state.eventStops.push({index,title:eventTitle(event)});
   });
   if(!state.busy&&state.eventStops.at(-1).index!==frames.length-1)state.eventStops.push({index:frames.length-1,title:'Итог'});
   $('incident-links').replaceChildren(...state.eventStops.map(stop=>{
    const button=node('button',stop.title);
    button.type='button';
    button.title=frames[stop.index].time+' с';
    button.onclick=()=>seek(stop.index);
    return button;
   }));
  }
  const active=state.eventStops.findLastIndex(stop=>stop.index<=state.index);
  [...$('incident-links').children].forEach((button,index)=>button.setAttribute('aria-pressed',String(index===active)));
 }
 function renderLive(){
  const frame=current();
  if(!frame)return;
  const decision=currentDecision();
  text('operation-title',state.trace.title);
  text('operation-description',state.trace.description);
  text('mission-value',pct(frame.metrics.mission_completion));
  text('network-value',frame.agents.filter(a=>a.communication.connected).length+' / '+frame.agents.length);
  renderStops();
  renderStory(frame,decision);
  text('clock',frame.time+' с');
  $('timeline').max=state.trace.frames.length-1;
  $('timeline').value=state.index;
  $('prev').disabled=state.index===0;
  $('next').disabled=state.index===state.trace.frames.length-1;
  renderTasks(frame);
  drawMap();
  renderSelected();
 }
 function renderTasks(frame){
  $('mission-tasks').replaceChildren(...frame.targets.map(target=>{
   const stage={unconfirmed:'Проверить',confirmed:'Подтверждено',delivered:'Готово'}[target.status];
   const row=node('span',undefined,'mission-task '+target.status);
   row.append(node('strong',target.appearance?.label??target.id),node('span',stage));
   return row;
  }));
 }
 function renderFleet(){
  const frame=current();
  if(!frame)return;
  text('fleet-context',state.trace.title+' · '+frame.time+' с');
  const mobile=frame.agents.filter(a=>Array.isArray(a.position));
  const units=state.filter==='site'?frame.infrastructure:state.filter==='digital'?frame.agents.filter(a=>!a.position):mobile;
  $('fleet').replaceChildren(...units.map(unit=>{
   const card=node('article',undefined,'fleet-card'), header=node('header');
   const mark=node('span',undefined,'fleet-icon');mark.append(icon(unit.kind==='relay'?'network':'fleet'));
   const identity=node('div');identity.append(node('h2',actor(unit)),node('p',get('devices',unit.kind),'quiet'));
   header.append(mark,identity);
   const tags=node('div',undefined,'tags');
   if(unit.status!=='active')tags.append(badge(status(unit.status),unit.status==='failed'?'danger':''));
   if(!unit.communication.connected)tags.append(badge('Нет связи','warn'));
   if(unit.role)tags.append(badge(get('role',unit.role)));
   card.append(header);
   if(tags.childElementCount)card.append(tags);
   const power=unit.resources.energy??unit.resources.stock;
   if(power){
    const bar=node('div',undefined,'energy-track'), fill=node('i');
    fill.style.width=pct(power.value);bar.append(fill);
    card.append(bar,node('p',(unit.resources.energy?'Энергия ':'Ресурс ')+pct(power.value),'quiet'));
   }
   if(state.filter==='mobile'){
    const locate=node('button','На карте','button secondary compact locate');
    locate.type='button';
    locate.setAttribute('aria-label','На карте: '+actor(unit));
    locate.onclick=()=>{go('live');selectAgent(unit.id,true);$('map-agent').focus({preventScroll:true});};
    card.append(locate);
   }
   return card;
  }));
 }
 function commandRow(left,right){
  const row=node('div',undefined,'command');
  row.append(node('strong',left),node('span',right));
  return row;
 }
 function renderDecisions(){
  const frame=current(), decisions=state.trace?.decisions??[];
  if(!frame)return;
  const decision=currentDecision()??decisions.filter(d=>d.time<=frame.time).at(-1);
  const eventTimes=new Set(state.trace.frames.flatMap(f=>f.events.map(e=>e.time)));
  const moments=decisions.filter(d=>d===decision||d.time===0||eventTimes.has(d.time)||['synthesize','safe_stop'].includes(d.operation));
  $('decision-times').replaceChildren(...moments.map(d=>{
   const button=node('button',d.time+' с · '+get('operation',d.operation),d===decision?'active':'');
   button.type='button';
   button.setAttribute('aria-pressed',String(d===decision));
   button.onclick=()=>{
    seek(state.trace.frames.findIndex(f=>f.time===d.time));
    $('decision-times').querySelector('[aria-pressed="true"]')?.focus({preventScroll:true});
   };
   return button;
  }));
  text('decision-time',state.trace.title+' · '+(decision?.time??frame.time)+' с');
  text('decision-title',decision?get('operation',decision.operation):'Ожидаем решение');
  text('decision-result',decision?decisionReason(decision):'Решения появятся после проверки прогона.');
  $('decision-scenarios').replaceChildren(...(decision?.configuration?.scenario_ids??[]).map(id=>badge(id.startsWith('synth_')?'Синтезированный граф':get('scenario',id))));
  const graph=decision?.configuration?.synthesized_scenario?.graph?.nodes??[];
  const graphStates=decision?.meta?.graph_execution??decision?.meta?.graph_states??[];
  $('decision-graph').replaceChildren(...graph.map(item=>{
   const phase=graphStates.find(n=>n.node_id===item.id)?.status;
   const dependency=item.requires?.length?' ← '+item.requires.map(id=>get('primitives',id)).join(', '):'';
   return badge(get('primitives',item.primitive)+dependency+(phase?' · '+get('graph',phase):''),'warn');
  }));
  $('decision-checks').replaceChildren(...(decision?.constraints_checked??[]).map(check=>{
   const names={ariadna_public_command_guard:'Резерв, доступность действий и траектории',operator_directives:'Директивы оператора'};
   return node('li',(names[check.constraint_id]??check.constraint_id)+' · '+(check.status==='passed'?'пройдено':check.status));
  }));
  $('decision-commands').replaceChildren(...(decision?.commands??[]).map(command=>{
   const result=decision.command_results.find(outcome=>outcome.agent_id===command.agent_id&&outcome.action===command.action);
   return commandRow(name(command.agent_id)+' · '+get('action',command.action),result?.effect==='collision'?'Столкновение':result?.status==='applied'?'Исполнено':result?.status??'—');
  }));
  if(!decision?.commands.length)$('decision-commands').append(node('p','На этом шаге активных команд нет.','quiet'));
  const forecasts=decision?.forecast?.candidates??[];
  $('decision-candidates').replaceChildren(...forecasts.map(candidate=>commandRow(get('plans',candidate.candidate_id),
   (candidate.selected?'Выбран · ':'')+'полезность '+num(candidate.score))));
  if(!forecasts.length)$('decision-candidates').append(node('p','Оценка вариантов появится в журнале решения.','quiet'));
  text('decision-json',decision?JSON.stringify(decision,null,2):'');
 }

 function drawFork(id,frame){
  const canvas=$(id),scale=10,y=value=>160-value*scale;
  const roomFill={oak:'#8d7558',terrazzo:'#b4aa92',ceramic:'#557f78'};
  canvas.replaceChildren();
  for(const zone of frame.zones){
   const kind=zone.appearance?.kind,{min,max}=zone.geometry;
   const fill=kind==='home_floor'?roomFill[zone.appearance.material]:kind==='home_wall'?'#e2dbbc':kind==='home_wet'?'#4fadaf':kind==='home_private'?'#cf8a73':zone.type==='obstacle'?'#384b40':null;
   if(fill)canvas.append(svg('rect',{x:min[0]*scale,y:y(max[1]),width:(max[0]-min[0])*scale,height:(max[1]-min[1])*scale,fill,stroke:'none'}));
  }
  const positions=new Map(entities(frame).filter(a=>a.position).map(a=>[a.id,a.position]));
  for(const link of frame.network.known_links??[]){
   const a=positions.get(link.source),b=positions.get(link.target);
   if(a&&b)canvas.append(svg('line',{x1:a[0]*scale,y1:y(a[1]),x2:b[0]*scale,y2:y(b[1]),stroke:'#cef5cc','stroke-opacity':.21}));
  }
  for(const unit of frame.agents.filter(a=>a.position)){
   const fill=unit.communication.connected?'#d8f5ba':'#ee8f74';
   const mark=svg('circle',{cx:unit.position[0]*scale,cy:y(unit.position[1]),r:unit.kind==='aerial'?3:2.5,fill,stroke:'#24392b'});
   const title=svg('title');title.textContent=actor(unit);mark.append(title);canvas.append(mark);
  }
 }
 function renderCompare(){
  const fork=state.data.research;
  const picked=fork.branches.find(b=>b.selected_in_real_episode);
  const other=fork.branches.find(b=>b.candidate_id===state.branch);
  const last=Math.max(picked.frames.length,other.frames.length)-1;
  $('branch-timeline').max=last;
  $('branch-timeline').value=state.branchIndex;
  text('fork-context','Оба плана стартуют из одного состояния после отказа узла связи.');
  text('branch-time','+'+state.branchIndex+' с');
  for(const [id,branch] of [['fork-reference',picked],['fork-alternative',other]]){
   const initial=branch.frames[0];
   const frame=branch.frames[Math.min(state.branchIndex,branch.frames.length-1)];
   text(id+'-title',get('plans',branch.candidate_id)+(branch===picked?' · выбран штабом':' · альтернатива'));
   drawFork(id,frame);
   $(id+'-metrics').replaceChildren(
    badge('Миссия '+pct(frame.metrics.mission_completion)),
    badge('На связи '+pct(frame.network.reachable_agent_ratio)),
    badge('Энергия '+(frame.metrics.energy_used-initial.metrics.energy_used).toFixed(1),'warn'),
   );
  }
  const rows=state.data.results.filter(r=>r.case===$('compare-case').value);
  $('compare-table').replaceChildren(...rows.map(row=>{
   const tr=node('tr');
   tr.append(...[get('modes',row.mode),status(row.status),pct(row.metrics.mission_completion),row.time+' с',num(row.metrics.energy_used),row.audit==='passed'?'Пройден':'—'].map(value=>node('td',value)));
   return tr;
  }));
 }
 function render(){
  if(!state.data)return;
  if(state.page==='live')renderLive();
  if(state.page==='fleet')renderFleet();
  if(state.page==='decisions')renderDecisions();
  if(state.page==='compare')renderCompare();
 }

 function pause(){
  state.playing=false;
  cancelAnimationFrame(state.animation);
  $('play').setAttribute('aria-label','Воспроизвести');
  $('play').replaceChildren(icon('play'));
 }
 function seek(index){
  if(!state.trace)return;
  pause();
  state.index=Math.max(0,Math.min(index,state.trace.frames.length-1));
  render();
 }
 function play(){
  if(!state.trace||state.busy)return;
  if(state.playing){pause();drawMap();return;}
  if(state.index===state.trace.frames.length-1)state.index=0;
  state.playing=true;
  $('play').setAttribute('aria-label','Пауза');
  $('play').replaceChildren(icon('pause'));
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const step=()=>{
   const next=state.trace.frames[state.index+1], start=performance.now();
   if(!next){pause();return;}
   const tick=now=>{
    if(!state.playing)return;
    const ratio=Math.min(1,(now-start)/Number($('speed').value));
    if(ratio<1){
     if(!reduced)drawMap(next,ratio);
     state.animation=requestAnimationFrame(tick);
    }else{
     state.index++;
     render();
     step();
    }
   };
   state.animation=requestAnimationFrame(tick);
  };
  render();
  step();
 }
 function setBusy(busy){
  state.busy=busy;
  for(const id of ['case','seed','run','play'])$(id).disabled=busy;
  for(const element of $('campaign').querySelectorAll('button'))element.disabled=busy;
 }
 async function serverReady(){
  if(location.protocol==='file:')return false;
  try{
   const response=await fetch('/api/studio/health',{cache:'no-store'});
   return response.ok&&(await response.json()).status==='ready';
  }catch{return false;}
 }
 async function run(){
  if(state.busy||!state.data||state.caseId==='impact')return;
  error('');
  const seed=Number($('seed').value);
  if(!Number.isInteger(seed)||seed<0||seed>2147483647){error('Допустимый seed — целое число от 0 до 2147483647.');return;}
  pause();
  setBusy(true);
  $('evidence-link').hidden=true;
  text('live-status','Запускаются независимые среда и контроллер…');
  const authored=state.data.episodes.find(e=>e.id===state.caseId);
  try{
   if(!await serverReady())throw Error('Для нового прогона запустите python scripts/start_local.py --open. Записи работают автономно.');
   const response=await fetch('/api/studio/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format:'ariadna.home.v1',case:state.caseId,seed})});
   const job=await response.json();
   if(!response.ok)throw Error(job.error);
   state.trace={...authored,frames:[authored.frames[0]],decisions:[],summary:null};
   state.index=0;
   state.selected=null;
   while(true){
    const response=await fetch('/api/studio/runs/'+encodeURIComponent(job.id),{cache:'no-store'});
    const value=await response.json();
    if(!response.ok||value.state==='failed')throw Error(value.error??'Среда завершилась с ошибкой');
    if(value.frames?.length){
     state.trace.frames=value.frames;
     state.index=value.frames.length-1;
     text('live-status',value.phase==='checking'?'Проверяем журнал решений…':'Миссия выполняется · '+current().time+' с');
     render();
    }
    if(value.state==='completed'){
     state.trace={...value.result.episodes[0],description:authored.description};
     state.index=state.trace.frames.length-1;
     setBusy(false);
     text('live-status',status(state.trace.summary.status)+' · аудит '+(state.trace.audit.status==='passed'?'пройден':'требует проверки'));
     $('evidence-link').href='/api/studio/runs/'+encodeURIComponent(job.id)+'/evidence.zip';
     $('evidence-link').hidden=false;
     render();
     break;
    }
    await new Promise(resolve=>setTimeout(resolve,420));
   }
  }catch(problem){
   setBusy(false);
   selectCase(state.caseId,false);
   error(problem.message);
   text('live-status','Прогон прерван · открыта запись');
  }finally{setBusy(false);}
 }
 function option(value,label){
  const element=node('option',label);
  element.value=value;
  return element;
 }
 function install(data){
  if(data.format!=='ariadna.apartment.v1'||!data.episodes.length||!data.research?.branches.length)throw Error('Пакет квартиры повреждён');
  state.data=data;
  for(const id of ['case','compare-case'])$(id).replaceChildren(...data.episodes.map(ep=>option(ep.id,ep.title)));
  if(data.impact_demo)$('case').append(option('impact',data.impact_demo.title));
  const alternatives=data.research.branches.filter(b=>!b.selected_in_real_episode);
  $('branch-choice').replaceChildren(...alternatives.map(b=>option(b.candidate_id,get('plans',b.candidate_id))));
  state.branch=alternatives[0].candidate_id;
  $('campaign').replaceChildren(...data.episodes.map(ep=>{
   const brief=briefs[ep.id];
   const button=node('button',undefined,'campaign-card '+(brief?.tone??''));
   button.type='button';
   const label=node('span',brief?.label??'Сценарий','case-label');
   label.prepend(icon(brief?.icon??'map'));
   const link=node('span','Открыть сценарий','text-link');link.append(icon('arrow'));
   button.append(label,node('strong',ep.title),node('p',brief?.copy??ep.description,'quiet'),link);
   button.onclick=()=>selectCase(ep.id);
   return button;
  }));
  selectCase('leak',false);
  route();
  const tour=new window.AriadnaTour({pause,go,seek,play},{
   key:'ariadna.apartment.onboarding.v2',steps:tourSteps,onFinish:start=>{
    if(start){selectCase('leak');play();$('play').focus();}
    else $('guide-open').focus({preventScroll:true});
   },
  });
  if(state.page==='overview')tour.init();
 }

 window.addEventListener('hashchange',route);
 for(const link of document.querySelectorAll('[data-page], #decision-link, #return-live')){
  link.addEventListener('click',event=>{
   if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
   event.preventDefault();
   go(link.hash.slice(1));
   $('page-'+state.page).querySelector('h1').focus({preventScroll:true});
  });
 }
 for(const heading of document.querySelectorAll('.page h1'))heading.tabIndex=-1;
 $('case').onchange=()=>selectCase($('case').value,false);
 $('compare-case').onchange=renderCompare;
 $('branch-choice').onchange=()=>{state.branch=$('branch-choice').value;state.branchIndex=0;renderCompare();};
 $('branch-timeline').oninput=()=>{state.branchIndex=Number($('branch-timeline').value);renderCompare();};
 $('open-fork-decision').onclick=event=>{
  event.preventDefault();
  if(state.busy)return;
  selectCase('leak',false);
  seek(state.trace.frames.findIndex(f=>f.time===state.data.research.time));
  go('decisions');
 };
 $('fleet-filter').onclick=event=>{
  const button=event.target.closest('[data-filter]');
  if(!button)return;
  state.filter=button.dataset.filter;
  for(const item of $('fleet-filter').querySelectorAll('[data-filter]')){
   item.classList.toggle('active',item===button);
   item.setAttribute('aria-pressed',String(item===button));
  }
  renderFleet();
 };
 $('map-links').onclick=()=>{
  state.links=!state.links;
  $('map-links').setAttribute('aria-pressed',String(state.links));
  drawMap();
 };
 $('map-fit').onclick=()=>{mapMode(false);state.map?.fit(false);};
 $('map-top').onclick=()=>mapMode(state.map?.volume);
 $('map-zoom-in').onclick=()=>state.map?.changeZoom(1.2);
 $('map-zoom-out').onclick=()=>state.map?.changeZoom(1/1.2);
 $('map-agent').onchange=()=>selectAgent($('map-agent').value,true);
 $('prev').onclick=()=>seek(state.index-1);
 $('next').onclick=()=>seek(state.index+1);
 $('timeline').oninput=()=>seek(Number($('timeline').value));
 $('play').onclick=play;
 $('run').onclick=run;
 $('home-map').onkeydown=event=>{
  if(![' ','ArrowLeft','ArrowRight','+','-'].includes(event.key))return;
  event.preventDefault();
  if(event.key===' ')play();
  else if(event.key==='+')state.map?.changeZoom(1.2);
  else if(event.key==='-')state.map?.changeZoom(1/1.2);
  else if(event.shiftKey&&state.map?.volume){
   const {camera,controls}=state.map;
   const angle=event.key==='ArrowLeft'?.18:-.18;
   state.map.follow=false;
   camera.position.sub(controls.target).applyAxisAngle(new window.THREE.Vector3(0,1,0),angle).add(controls.target);
   controls.update();
  }else seek(state.index+(event.key==='ArrowRight'?1:-1));
 };
 decodeAriadnaPacket(window.ARIADNA_HOME_PACK).then(install).catch(problem=>error(problem.message));
})();
