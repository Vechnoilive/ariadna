'use strict';
(() => {
const $=id=>document.getElementById(id),palette={meta:'#4f9074',frontier:'#6b95ca',nearby:'#c9a05d',reserve:'#9b8bb9'},policy={meta:'Метаплан',frontier:'Разведка',nearby:'Ближняя цель',reserve:'Резерв'};
const kindNames={aerial:['Дрон','Воздушный'],ground:['Ровер','Наземный'],underground:['Тоннель','Подземный'],surface_water:['Катер','Надводный'],underwater:['Батискаф','Подводный'],infrastructure:['Ретранслятор','Инфраструктурный'],digital:['Штаб','Цифровой'],operator:['Оператор','Оператор']};
const roleNames={scout:'Разведка',executor:'Исполнитель',verifier:'Подтверждение',relay:'Ретрансляция',coordinator:'Координация',returning:'Возвращается',charging:'Зарядка',holding:'Удержание',member:'Участник',beneficiary:'Получатель'};
const statusNames={active:'Активен',failed:'Отказ',degraded:'Деградация',safe_mode:'Резерв',success:'Успех',safe_stopped:'Безопасная остановка',running:'Выполняется',time_limit:'Лимит времени'};
const scenarioNames={coverage_search:'Поиск и покрытие',priority_service:'Приоритетная помощь',relay_coalition:'Восстановление связи',safe_degradation:'Восстановление ресурса',coordination_reconfiguration:'Реконфигурация'};
const eventNames={agent_failure:'Отказ агента',agent_degradation:'Деградация агента',infrastructure_failure:'Отказ инфраструктуры',restricted_zone_appeared:'Новая запретная зона',contradictory_information:'Противоречивые сведения',stale_information:'Устаревшие сведения',resource_shortage:'Дефицит ресурса',operator_directive:'Директива оператора',target_detected:'Обнаружена цель',target_state_changed:'Изменилось состояние цели',connectivity_loss:'Потеря связи',hazard_appeared:'Новая опасная зона'};
const operationNames={keep:'План сохранён',select:'Выбор плана',switch:'Смена плана',modify:'Изменение плана',compose:'Композиция',synthesize:'Синтез',safe_stop:'Безопасная остановка'};
const reasons={robust_public_forecast:'Лучший устойчивый прогноз среди допустимых вариантов.',mandatory_safe_response:'Обязательная безопасная реакция.',forecast_abstention_model_error:'Возврат к метаплану после ошибки прогноза.',no_safe_alternative:'Нет допустимого варианта для продолжения.'};
const actionNames={move:'Перемещение',navigate:'Перемещение',observe:'Подтверждение',inspect:'Подтверждение',deliver:'Доставка',drop:'Доставка',charge:'Зарядка',recharge:'Зарядка',relay:'Ретрансляция',send_message:'Передача сообщения'};
const pageTitles={overview:['Сценарии','Полевые миссии'],fleet:['Агенты','Отряд операции'],mission:['Операция','Обзор операции'],decisions:['Решения','Штаб решений'],branches:['Развилка','Исследование альтернатив'],journal:['Журнал','Журнал операции'],editor:['Своя карта','Конструктор операции']};
let data=null,current=null,index=0,page='mission',playing=false,raf=0,selected=null,names=new Map(),branchChoice='meta',branchIndex=0,tour=null,mapDebug={},showArchive=false;
const node=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=String(value);if(cls)n.className=cls;return n;};
const text=(id,value)=>$(id).textContent=String(value??'—'),pct=v=>Number.isFinite(v)?(v*100).toFixed(0)+'%':'—',number=(v,d=3)=>Number.isFinite(v)?v.toFixed(d):'—',position=p=>Array.isArray(p)&&p.length===3&&p.every(Number.isFinite);
function icon(id){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href','#i-'+id);svg.append(use);svg.setAttribute('aria-hidden','true');return svg;}
function error(message){text('error',message);$('error').hidden=false;}
function validate(input){
 if(!input||input.format!=='ariadna.showcase.v1'||!Array.isArray(input.episodes)||!input.episodes.length||input.episodes.length>64)throw Error('Ожидается пакет ariadna.showcase.v1 или replay.json');
 const ids=new Set();
 for(const ep of input.episodes){
  if(typeof ep.id!=='string'||ids.has(ep.id)||!Array.isArray(ep.frames)||!ep.frames.length||ep.frames.length>10001)throw Error('Некорректные эпизоды');ids.add(ep.id);
  let last=-1;for(const f of ep.frames){
   if(!Number.isFinite(f.time)||f.time<=last)throw Error('Время снимков должно возрастать');last=f.time;
   for(const k of ['agents','infrastructure','targets','zones'])if(!Array.isArray(f[k])||f[k].length>10000)throw Error('Некорректные публичные сущности');
   for(const a of [...f.agents,...f.infrastructure,...f.targets])if(a.position!==null&&a.position!==undefined&&!position(a.position))throw Error('Некорректные координаты');
   for(const z of f.zones){const lo=z.geometry?.min??z.geometry?.lower,hi=z.geometry?.max??z.geometry?.upper;if(!position(lo)||!position(hi)||lo.some((x,i)=>x>hi[i]))throw Error('Некорректная геометрия зоны');}
   if(!f.network||typeof f.metrics!=='object')throw Error('Нет сети или метрик');
  }
  if(ep.decisions!==undefined&&!Array.isArray(ep.decisions))throw Error('Некорректные решения');
 }
 return input;
}
const map=new window.AriadnaMap($('view'),{onSelect:selectUnit,onScale:scale=>{const unit=scale*20>120?10:20;$('scale-line').style.width=(unit*scale)+'px';text('map-scale',unit+' м');},onRender:detail=>mapDebug=detail});
let branchMap=null,referenceMap=null,branchCase='incident',renderedResearch=null,renderedBranch=null;
function makeNames(ep){const entities=new Map();for(const f of ep.frames)for(const a of f.agents)if(!entities.has(a.id))entities.set(a.id,a);const counts={};const output=new Map();for(const a of [...entities.values()].sort((a,b)=>String(a.id).localeCompare(String(b.id)))){counts[a.kind]=(counts[a.kind]||0)+1;const n=String(counts[a.kind]).padStart(2,'0'),k=kindNames[a.kind]||['Агент',a.kind];output.set(a.id,{name:k[0]+' '+n,kind:k[1],number:n,color:window.AriadnaMapColors[a.kind]||'#728c81'});}return output;}
function fillEpisodes(){const select=$('episode');select.replaceChildren();const main=data.episodes.filter(ep=>!ep.archived),archive=data.episodes.filter(ep=>ep.archived);for(const ep of main){const option=node('option',ep.title||ep.id);option.value=ep.id;select.append(option);}if(showArchive&&archive.length){const group=node('optgroup');group.label='Технический архив';for(const ep of archive){const option=node('option',ep.title||ep.id);option.value=ep.id;group.append(option);}select.append(group);}$('archive-toggle').hidden=!archive.length;$('archive-toggle').setAttribute('aria-pressed',String(showArchive));}
function install(value){validate(value);pause(false);data=value;showArchive=false;branchCase=value.incident?'incident':'initial';fillEpisodes();text('source-count',Object.keys(data.source_sha256||{}).length+' исходных файлов с SHA-256.');$('error').hidden=true;choose(data.default_episode&&data.episodes.some(ep=>ep.id===data.default_episode)?data.default_episode:data.episodes.find(ep=>!ep.archived)?.id||data.episodes[0].id);applyPage(page);}
function choose(id){const ep=data?.episodes.find(ep=>ep.id===id);if(!ep)throw Error('Неизвестный эпизод');pause(false);if(ep.archived&&!showArchive){showArchive=true;fillEpisodes();}current=ep;index=0;branchIndex=0;selected=null;names=makeNames(ep);map.setEpisode(ep.frames,names);if(ep.presentation?.fit==='world')map.fit(false);$('episode').value=id;$('run-scenario').hidden=!ep.map_id;$('preview-deployment').hidden=!ep.map_id;$('run-scenario').dataset.mapId=ep.map_id||'';$('mission-brief').hidden=!ep.map_id;text('mission-brief',ep.description||'');closeUnits();$('unit-detail').hidden=true;$('layers-panel').hidden=true;$('layers-toggle').setAttribute('aria-expanded','false');text('mission-name',ep.title||ep.id);const audited=ep.audit?.status==='passed';$('audit').querySelector('span').textContent=audited?'Запись проверена':'Без аудита';text('journal-audit',audited?'Аудит пройден':'Аудит не выполнялся');setupBranches();render();}
function decision(){return(current?.decisions||[]).find(d=>d.time===current.frames[index].time)||null;}
function currentResearch(){return branchCase==='incident'?data?.incident:data?.research;}
function currentBranch(){
 const research=currentResearch();
 return research?.branches.find(b=>b.candidate_id===branchChoice) ?? research?.branches[0] ?? null;
}
function referenceBranch(){
 const branches=currentResearch()?.branches ?? [], current=currentBranch();
 const chosen=branches.find(b=>b.selected_in_real_episode);
 return (chosen!==current?chosen:null) ?? branches.find(b=>b!==current) ?? current;
}
function setBranchMap(canvas,map,branch){
 const episode=data.episodes.find(ep=>ep.id===currentResearch().episode_id) ?? current;
 const scene=map ?? new window.AriadnaMap($(canvas),{});
 if(scene.branch!==branch){
  scene.branch=branch;
  scene.setEpisode(branch.frames,makeNames(episode));
  scene.fit(false);
 }
 return scene;
}
function setupBranches(){
 const research=currentResearch();
 $('branch-empty').hidden=Boolean(research);
 $('research').hidden=!research;
 $('branch-case').value=branchCase;
 $('branch-case').disabled=!(data?.incident&&data?.research);
 $('branch-case').options[0].hidden=!data?.incident;
 $('branch-case').options[1].hidden=!data?.research;
}
function applyPage(next){if(!pageTitles[next])next='overview';pause(false);if(next==='branches'&&currentResearch()&&current.id!==currentResearch().episode_id&&data.episodes.some(ep=>ep.id===currentResearch().episode_id))choose(currentResearch().episode_id);page=next;document.body.classList.toggle('is-editor',page==='editor');document.body.classList.toggle('is-overview',page==='overview');$('episode-control').hidden=page==='editor';$('audit').hidden=page==='editor';$('archive-toggle').hidden=page==='editor'||!data?.episodes.some(ep=>ep.archived);for(const id of Object.keys(pageTitles))$('page-'+id).hidden=id!==page;for(const link of document.querySelectorAll('[data-page]')){const active=link.dataset.page===page;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}text('page-breadcrumb',pageTitles[page][0]);text('page-title',pageTitles[page][1]);closeUnits();render();window.dispatchEvent(new CustomEvent('ariadna:page',{detail:{page}}));}
function go(next){if(!pageTitles[next])return;if(location.hash!=='#/'+next)location.hash='/'+next;applyPage(next);}
window.addEventListener('hashchange',()=>{const requested=location.hash.replace(/^#\/?/,'');if(current)applyPage(requested);});
function openUnits(){$('unit-drawer').hidden=false;$('unit-detail').hidden=true;}
function closeUnits(){$('unit-drawer').hidden=true;if(selected&&page==='mission')$('unit-detail').hidden=false;}
function selectUnit(id){selected=id;map.select(id);closeUnits();renderUnit();renderRoster();}
function clearUnit(){selected=null;map.select(null);$('unit-detail').hidden=true;renderRoster();}
function renderRoster(){if(!current)return;$('unit-list').replaceChildren();const f=current.frames[index],d=decision();for(const a of f.agents){const meta=names.get(a.id)||{name:String(a.id),kind:a.kind,number:'',color:'#728c81'},button=node('button',undefined,'unit-row'+(selected===a.id?' selected':''));button.type='button';button.setAttribute('aria-label',meta.name);const symbol=node('span',meta.number,'unit-row-symbol');symbol.style.setProperty('--unit-bg',meta.color+'15');symbol.style.setProperty('--unit-color',meta.color);const detail=node('div');detail.append(node('strong',meta.name),node('small',statusNames[a.status]||a.status));const e=a.resources?.energy?.value??a.resources?.battery?.value;button.append(symbol,detail,node('span',pct(e)));button.onclick=()=>selectUnit(a.id);$('unit-list').append(button);}}
function renderUnit(){if(!selected||!current){$('unit-detail').hidden=true;return;}const a=current.frames[index].agents.find(a=>a.id===selected);if(!a){clearUnit();return;}const meta=names.get(a.id),d=decision(),energy=a.resources?.energy?.value??a.resources?.battery?.value;const fieldName=meta?.name||String(a.id);text('unit-name',fieldName);text('unit-kind',meta?.kind||a.kind);text('unit-symbol',meta?.number||'');$('unit-symbol').style.background=(meta?.color||'#728c81')+'15';$('unit-symbol').style.color=meta?.color||'#728c81';text('unit-status',statusNames[a.status]||a.status);$('unit-status').classList.toggle('failed',a.status==='failed');text('unit-role',roleNames[d?.roles?.[a.id]??a.role]||'Участник');text('unit-energy',pct(energy));$('unit-energy-bar').style.width=(Number.isFinite(energy)?Math.max(0,Math.min(1,energy))*100:0)+'%';text('unit-dimensions',map.bodyDescription(a));text('unit-position',position(a.position)?a.position.map(v=>v.toFixed(1)).join(', ')+' м':'—');$('focus-unit').disabled=!position(a.position);$('unit-detail').hidden=page!=='mission'||!$('unit-drawer').hidden;}
function options(){return{network:$('network').checked,trails:$('trails').checked,labels:$('labels').checked,zones:$('zones').checked};}
function renderBranchMap(scene,branch,clock,prefix){
 const frames=branch.frames;
 const i=Math.max(0,frames.findLastIndex(f=>f.time<=clock));
 const frame=frames[i], next=frames[i+1];
 const fraction=next?Math.max(0,(clock-frame.time)/(next.time-frame.time)):0;
 scene.render(frame,frames.slice(0,i+1),{trails:true,labels:false,zones:true,network:$('branch-network').checked},next,fraction);
 text(prefix+'-step',`Шаг ${i} из ${frames.length-1} · ${frame.time} с`);
 text(prefix+'-completion',pct(frame.metrics.mission_completion));
 text(prefix+'-connectivity',pct(frame.network.reachable_agent_ratio??frame.network.connectivity_score));
 const energy=frame.metrics.energy_used, initial=frames[0].metrics.energy_used;
 text(prefix+'-energy',Number.isFinite(energy)&&Number.isFinite(initial)?number(energy-initial,3):'—');
}
function renderMaps(next=null,t=0){
 if(!current)return;
 if(page==='mission')map.render(current.frames[index],current.frames.slice(0,index+1),{...options(),hitboxes:$('hitboxes').checked},next,t);
 const branch=currentBranch();
 if(page!=='branches'||!branch)return;
 const reference=referenceBranch(), frame=branch.frames[branchIndex];
 const clock=frame.time+(next?(next.time-frame.time)*t:0);
 branchMap=setBranchMap('branch-view',branchMap,branch);
 referenceMap=setBranchMap('reference-view',referenceMap,reference);
 renderBranchMap(branchMap,branch,clock,'branch');
 renderBranchMap(referenceMap,reference,clock,'reference');
}
function feedbackRow(label,value){const row=node('div',undefined,'feedback-row');row.append(node('span',label),node('strong',value));$('feedback').append(row);}
function renderDecision(d){const cf=d?.forecast;text('operation',d?.operation||'—');$('operation').title=operationNames[d?.operation]||'';text('plan-name',cf?(policy[cf.selected_candidate]||cf.selected_candidate):d?.operation==='safe_stop'?'Безопасная остановка':d?.operation==='synthesize'?'Адаптивная коалиция':d?'Сценарная координация':'Операция завершена');text('plan-score',cf?number(cf.candidates.find(c=>c.selected)?.score):'—');text('reason',cf?(reasons[cf.selection_reason]||'Выбран допустимый план по публичному состоянию.'):d?.operation==='synthesize'?'Сценарий собран из проверенных примитивов.':d?.operation==='safe_stop'?'Выполнена обязательная безопасная реакция.':d?'Роли назначены по текущим условиям операции.':'На этом шаге новое решение не требуется.');text('horizon',cf?`${cf.horizon} шагов прогноза`:'');$('alternatives').replaceChildren();
 const candidates=cf?.candidates||[],scores=candidates.map(c=>c.score).filter(Number.isFinite),min=Math.min(0,...scores),max=Math.max(1,...scores);
 for(const candidate of candidates){const card=node('article',undefined,'candidate'+(candidate.selected?' selected':'')),heading=node('div',undefined,'candidate-title');heading.append(node('span',policy[candidate.candidate_id]||candidate.candidate_id));if(candidate.selected)heading.append(icon('check'));const bar=node('div',undefined,'bar'),fill=node('span');fill.style.width=(8+92*Math.max(0,(candidate.score-min)/(max-min)))+'%';bar.append(fill);const dl=node('dl');for(const [label,value] of [['Выполнение',pct(candidate.nominal?.known_completion_gain)],['Энергия',number(candidate.nominal?.energy)]]){const row=node('div');row.append(node('dt',label),node('dd',value));dl.append(row);}card.append(heading,node('strong',number(candidate.score),'candidate-score'),bar,dl);$('alternatives').append(card);}
 if(!candidates.length)$('alternatives').append(node('p',d?.portable?.mode==='meta_budget'?'Прогноз пропущен по вычислительному лимиту. Координация сохранена.':d?'Этот контроллер не строит многовариантный прогноз.':'Следующего решения нет.','empty-message'));
 $('feedback').replaceChildren();text('feedback-time',d?`t = ${d.result_time} с`:'');const feedback=d?.feedback;
 if(feedback?.status==='compared'){feedbackRow('Энергия: прогноз / факт',`${number(cf?.selected_one_step_prediction?.energy_delta,4)} / ${number(feedback.actual_energy_delta,4)}`);feedbackRow('Ошибка позиции',number(feedback.residuals?.position,3)+' м');feedbackRow('Выполнение после шага',pct(feedback.actual_completion));feedbackRow('Доверие к модели',pct(feedback.updated_calibration?.trust));}
 else feedbackRow('Результат',feedback?.status==='not_predicted'?'Без прогноза':d?(statusNames[d.result_status]||d.result_status||'—'):'Итоговое состояние');
 $('configuration').replaceChildren();for(const id of d?.configuration?.scenario_ids||[])$('configuration').append(node('span',scenarioNames[id]||(id.startsWith('synth_')?'Синтезированный сценарий':id),'scenario-tag'));
 $('checks').replaceChildren();for(const check of d?.constraints_checked||[]){const row=node('div',undefined,'check-row');const passed=check.status==='passed';row.append(icon(passed?'check':'help'),node('span',check.constraint_id==='operator_directives'?'Директивы оператора':check.constraint_id==='ariadna_public_command_guard'?'Команды и ограничения':check.constraint_id),node('span',passed?'Проверено':check.status));$('checks').append(row);}
 text('decision-id',d?'Решение: '+d.decision_id:'');text('observation-hash',d?'SHA-256 наблюдения: '+d.observation_sha256:'');text('evidence',JSON.stringify(d?{configuration:d.configuration,roles:d.roles,constraint_checks:d.constraints_checked,candidate_evaluations:d.candidate_evaluations,explanation:d.explanation,synthesized_scenario:d.synthesized_scenario}: {},null,2));
}
function renderJournal(d){const events=[],seen=new Set();for(const f of current.frames.slice(0,index+1))for(const e of f.events||[]){const key=e.id||JSON.stringify(e);if(!seen.has(key)){seen.add(key);events.push(e);}}$('events').replaceChildren();text('event-count',events.length+' · событий');for(const event of events.slice().reverse()){const row=node('article',undefined,'event-row'),dot=node('span',undefined,'event-dot'+(/failure|degradation/.test(event.type)?' danger':'')),detail=node('div'),button=node('button',eventNames[event.type]||event.type);button.type='button';button.onclick=()=>{const frameIndex=current.frames.findIndex(f=>f.time>=event.time);if(frameIndex>=0)seek(frameIndex);};detail.append(button,node('p',(event.targets||[]).map(id=>names.get(id)?.name||String(id)).join(', ')));row.append(node('span',event.time+' с','event-time'),dot,detail);$('events').append(row);}if(!events.length)$('events').append(node('p','Событий на этом шаге нет.','empty-message'));
 text('result-status',d?`t = ${d.result_time} с`:statusNames[current.summary?.status]||'Завершено');$('command-table').replaceChildren();for(const command of d?.commands||[]){const result=(d.command_results||[]).find(r=>r.agent_id===command.agent_id&&r.action===command.action),row=node('div',undefined,'command-row'),left=node('div');left.append(node('strong',names.get(command.agent_id)?.name||command.agent_id),node('span',actionNames[command.action]||command.action));row.append(left,node('span',result?.status==='applied'?'Исполнено':result?.status==='rejected'?'Отклонено':result?.status||'—','command-status'));$('command-table').append(row);}if(!d?.commands?.length)$('command-table').append(node('p','На этом шаге команд нет.','empty-message'));text('commands',JSON.stringify(d?{time:d.time,commands:d.commands,result_time:d.result_time,result_status:d.result_status,command_results:d.command_results}: {},null,2));
}
function branchGain(b){
 const initial=b.frames[0].metrics.mission_completion??0;
 return b.actual_completion_gain??((b.actual_curve.at(-1)?.completion??initial)-initial);
}
function branchName(branch){return policy[branch.candidate_id]??branch.candidate_id;}
function renderBranches(){
 if(page!=='branches')return;
 const research=currentResearch(), branch=currentBranch();
 if(!research||!branch)return;
 if(renderedResearch===research&&renderedBranch===branch){
  drawBranchChart();
  return;
 }
 renderedResearch=research;
 renderedBranch=branch;
 const reference=referenceBranch();
 for(const [prefix,entry] of [['reference',reference],['branch',branch]]){
  text(prefix+'-name',branchName(entry));
  text(prefix+'-metrics-title',branchName(entry));
  text(prefix+'-tag',entry.selected_in_real_episode?'Выбран в эпизоде':'Измеренная ветвь');
 }
 const event=research.incident;
 text('branch-incident',event?`${event.time} с · ${eventNames[event.type]??event.type} · ${(event.targets??[]).map(id=>names.get(id)?.name??id).join(', ')}`:'Стартовый снимок операции');
 $('branch-options').replaceChildren();
 for(const option of research.branches){
  const active=option===branch, button=node('button',undefined,'branch-option'+(active?' active':''));
  button.type='button';
  button.dataset.branch=option.candidate_id;
  button.style.setProperty('--branch-color',palette[option.candidate_id]??'#8aa98c');
  button.setAttribute('aria-pressed',String(active));
  const heading=node('span',undefined,'branch-option-title');
  heading.append(node('strong',branchName(option)),node('span',option.selected_in_real_episode?'✓':''));
  const gain=branchGain(option)*100;
  const metrics=node('span',undefined,'branch-option-metrics');
  metrics.append(node('strong',`${gain>0?'+':''}${gain.toFixed(2)} п.п.`),node('span','Энергия '+number(option.actual_energy)));
  button.append(heading,metrics);
  button.onclick=()=>{
   const time=branch.frames[branchIndex].time;
   pause(false);
   branchChoice=option.candidate_id;
   branchIndex=Math.max(0,option.frames.findLastIndex(f=>f.time<=time));
   render();
   $('branch-options').querySelector('[aria-pressed="true"]')?.focus();
  };
  $('branch-options').append(button);
 }
 text('fork-hash','SHA-256 исходного состояния: '+research.branches[0].fork_checkpoint_sha256);
 drawBranchChart();
}
function drawBranchChart(){
 const research=currentResearch(),canvas=$('branch-chart'),w=canvas.clientWidth,h=canvas.clientHeight;
 if(!research||!w||!h)return;
 const c=canvas.getContext('2d'), dpr=Math.min(2,devicePixelRatio||1);
 canvas.width=Math.round(w*dpr);
 canvas.height=Math.round(h*dpr);
 c.setTransform(dpr,0,0,dpr,0,0);
 const left=55,right=w-20,top=16,bottom=h-26, horizon=research.horizon;
 const curves=research.branches.flatMap(branch=>{
  const initial=branch.frames[0].metrics.mission_completion??0;
  return [false,true].map(predicted=>({
   branch, predicted, points:(predicted?branch.nominal_forecast:branch.actual_curve).map(p=>[
    p.step, predicted?(p.known_completion_gain??((p.completion??initial)-initial)):p.completion-initial,
   ]),
  }));
 });
 const gains=curves.flatMap(curve=>curve.points.map(([,gain])=>gain));
 const min=Math.floor(Math.min(0,...gains)*20)/20, max=Math.max(.05,Math.ceil(Math.max(0,...gains)*20)/20);
 const x=step=>left+(right-left)*step/horizon, y=gain=>bottom-(bottom-top)*(gain-min)/(max-min);
 c.font='11px system-ui';
 c.fillStyle='#486763';
 for(let i=0;i<=4;i++){
  const gain=min+(max-min)*i/4;
  c.strokeStyle='#dce8e3';
  c.beginPath();c.moveTo(left,y(gain));c.lineTo(right,y(gain));c.stroke();
  c.fillText((gain*100).toFixed(1)+' п.п.',1,y(gain)+4);
 }
 for(let step=0;step<=horizon;step++)c.fillText(String(step),x(step)-3,bottom+17);
 for(const {branch,predicted,points} of curves){
  c.strokeStyle=palette[branch.candidate_id]??'#5c726a';
  c.lineWidth=predicted?1.4:2.4;
  c.setLineDash(predicted?[5,4]:[]);
  c.globalAlpha=predicted?.64:1;
  c.beginPath();c.moveTo(x(0),y(0));
  for(const [step,gain] of points)c.lineTo(x(step),y(gain));
  c.stroke();
 }
 c.setLineDash([]);c.globalAlpha=1;
 $('chart-legend').replaceChildren();
 for(const branch of research.branches){
  const item=node('span'),dot=node('i');
  dot.style.background=palette[branch.candidate_id]??'#5c726a';
  item.append(dot,node('span',branchName(branch)));
  $('chart-legend').append(item);
 }
}
function framesForPlayer(){return page==='branches'?(currentBranch()?.frames||current.frames):current.frames;}
function playerIndex(){return page==='branches'&&currentBranch()?branchIndex:index;}
function renderTimeline(fraction=0){if(!current)return;const frames=framesForPlayer(),i=playerIndex(),currentTime=frames[i].time,nextTime=frames[Math.min(frames.length-1,i+1)].time;text('clock',(currentTime+(nextTime-currentTime)*fraction).toFixed(1));text('frame-count',(i+1)+' / '+frames.length);text('timeline-end',frames.at(-1).time+' с');$('time').max=frames.length-1;$('time').value=i;$('time').style.setProperty('--progress',((i+fraction)/Math.max(1,frames.length-1)*100)+'%');$('prev').disabled=i===0;$('next').disabled=i===frames.length-1;const label=playing?'Пауза':'Воспроизвести';if($('play').getAttribute('aria-label')!==label||!$('play').children.length){$('play').replaceChildren(icon(playing?'pause':'play'));$('play').setAttribute('aria-label',label);}}
function render(){if(!current)return;const f=current.frames[index],d=decision();text('completion',pct(f.metrics.mission_completion));text('connectivity',pct(f.network.connectivity_score));text('population',f.agents.filter(a=>a.status!=='failed').length+' / '+f.agents.length);text('units-count',f.agents.length);const latest=(f.events||[]).filter(e=>e.time===f.time).at(-1);$('map-event').hidden=!latest;text('map-event',latest?(eventNames[latest.type]||latest.type):'');$('mission-finish').hidden=index!==current.frames.length-1||page!=='mission';const live=current.summary?.status==='running';if(live)$('mission-finish').hidden=true;const stopped=current.summary?.status==='safe_stopped'||f.mission?.status==='safe_stopped';text('finish-title',stopped?'Операция остановлена':current.summary?.status==='success'?'Миссия выполнена':'Эпизод завершён');text('finish-subtitle',stopped?'Выполнена директива безопасности':`Выполнение ${pct(f.metrics.mission_completion)} · ${f.time} секунд`);renderTimeline();renderRoster();renderUnit();renderDecision(d);renderJournal(d);renderBranches();renderMaps();window.dispatchEvent(new CustomEvent('ariadna:frame'));}
function pause(redraw=true){playing=false;cancelAnimationFrame(raf);raf=0;if(redraw&&current)render();}
function seek(value){pause(false);const frames=framesForPlayer(),i=Math.max(0,Math.min(frames.length-1,Number(value)||0));if(page==='branches'&&currentBranch())branchIndex=i;else index=i;render();}
function play(){if(!current||tour?.active())return;if(playing){pause();return;}const frames=framesForPlayer();if(playerIndex()===frames.length-1){if(page==='branches'&&currentBranch())branchIndex=0;else index=0;}playing=true;render();animateStep();}
function animateStep(){if(!playing)return;const frames=framesForPlayer(),i=playerIndex();if(i>=frames.length-1){pause();return;}const start=performance.now(),duration=Math.max(80,Number($('speed').value)*(frames[i+1].time-frames[i].time)),reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;const tick=now=>{if(!playing)return;const t=Math.min(1,(now-start)/duration);renderMaps(reduced?null:frames[i+1],reduced?0:t);renderTimeline(t);if(t<1){raf=requestAnimationFrame(tick);return;}if(page==='branches'&&currentBranch())branchIndex++;else index++;render();animateStep();};raf=requestAnimationFrame(tick);}
$('archive-toggle').onclick=()=>{showArchive=!showArchive;fillEpisodes();if(!showArchive&&current.archived)choose(data.default_episode||data.episodes.find(ep=>!ep.archived).id);else $('episode').value=current.id;};$('run-scenario').onclick=()=>window.dispatchEvent(new CustomEvent('ariadna:run-scenario',{detail:{id:current?.map_id}}));
$('episode').onchange=()=>{choose($('episode').value);if(page==='branches'&&current.id!==currentResearch()?.episode_id)go('mission');};$('time').oninput=()=>seek($('time').value);$('play').onclick=play;$('prev').onclick=()=>seek(playerIndex()-1);$('next').onclick=()=>seek(playerIndex()+1);$('replay').onclick=()=>{seek(0);play();};$('units-toggle').onclick=()=>{$('unit-drawer').hidden?openUnits():closeUnits();};$('units-close').onclick=closeUnits;$('unit-close').onclick=clearUnit;$('focus-unit').onclick=()=>{map.zoom=Math.max(1.5,map.zoom);map.select(selected,true);};$('layers-toggle').onclick=()=>{$('layers-panel').hidden=!$('layers-panel').hidden;$('layers-toggle').setAttribute('aria-expanded',String(!$('layers-panel').hidden));};for(const id of ['network','trails','labels','zones','hitboxes'])$(id).onchange=()=>renderMaps();$('zoom-in').onclick=()=>map.changeZoom(1.3);$('zoom-out').onclick=()=>map.changeZoom(1/1.3);$('fit').onclick=()=>map.fit();$('section-toggle').onclick=()=>{map.setCutaway(!map.cutaway);$('section-toggle').setAttribute('aria-pressed',String(map.cutaway));};$('top').onclick=()=>{map.volume=!map.volume;$('top').setAttribute('aria-pressed',String(map.volume));map.redraw();};$('branch-info-toggle').onclick=()=>{
 $('branch-info').hidden=!$('branch-info').hidden;
 $('branch-info-toggle').setAttribute('aria-expanded',String(!$('branch-info').hidden));
};
$('branch-case').onchange=()=>{
 pause(false);branchCase=$('branch-case').value;branchIndex=0;setupBranches();applyPage('branches');
};
$('branch-network').onchange=()=>renderMaps();
$('branch-reset-view').onclick=()=>{branchMap?.fit(false);referenceMap?.fit(false);};
$('preview-deployment').onclick=()=>window.dispatchEvent(new CustomEvent('ariadna:run-scenario',{detail:{id:current?.map_id,preview:true}}));
$('fork').onclick=()=>{const id=currentResearch()?.decision_id;const d=current?.decisions?.find(d=>d.decision_id===id);if(d){pause(false);index=current.frames.findIndex(f=>f.time===d.time);go('decisions');}};document.querySelectorAll('[data-go]').forEach(button=>button.onclick=()=>go(button.dataset.go));
$('file').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>32*1024*1024)throw Error('Лимит файла: 32 MiB');let value;const content=await file.text();try{value=JSON.parse(content);}catch{value=content.split(/\r?\n/).filter(s=>s.trim()).map(s=>JSON.parse(s));}if(Array.isArray(value)){const frames=value[0]?.kind?value.filter(r=>['reset','step'].includes(r.kind)).map(r=>r.output.observation):value;value={format:'ariadna.showcase.v1',episodes:[{id:'import',title:file.name,frames,decisions:[]}]};}validate(value);if(tour?.active())tour.finish(false);page='mission';install(value);go('mission');}catch(err){error('Не удалось открыть журнал: '+err.message);}finally{e.target.value='';}};
function beginLive(id,title,f){const ep={id,title,frames:[f],decisions:[],summary:{status:'running'}};install({...window.ARIADNA_DEMO,episodes:[...window.ARIADNA_DEMO.episodes,ep]});choose(id);go('mission');}
function appendLive(f){if(!current||!current.id.startsWith('custom_'))return;if(f.time>current.frames.at(-1).time){current.frames.push(f);index=current.frames.length-1;render();}}
function finishLive(value){const ep=value.episodes[0];install({...window.ARIADNA_DEMO,episodes:[...window.ARIADNA_DEMO.episodes,ep]});choose(ep.id);go('mission');play();}
const api={currentEpisode:()=>current,agentNames:()=>names,beginLive,appendLive,finishLive,choose,seek,pause:()=>pause(),play,install,go,openUnits,closeUnits,selectUnit,state:()=>({episode:current?.id,page,index,frames:current?.frames.length,playing,selected,bounds:map.world,map:mapDebug,branchChoice,branchIndex,tourStep:tour?.step??-1})};window.ariadna=api;
tour=new window.AriadnaTour(api);document.addEventListener('keydown',e=>{if(tour.active()||/INPUT|SELECT|TEXTAREA|BUTTON/.test(e.target.tagName)||!current)return;if(e.key===' '){e.preventDefault();play();}if(e.key==='ArrowRight'){e.preventDefault();seek(playerIndex()+1);}if(e.key==='ArrowLeft'){e.preventDefault();seek(playerIndex()-1);}if(e.key==='Escape'){$('layers-panel').hidden=true;closeUnits();clearUnit();}});window.addEventListener('resize',()=>{if(page==='branches')drawBranchChart();});
window.ARIADNA_READY.then(value=>{if(data)return;install(value);applyPage(location.hash.replace(/^#\/?/,''));tour.init();}).catch(err=>error('Ошибка загрузки операций: '+err.message));
})();
