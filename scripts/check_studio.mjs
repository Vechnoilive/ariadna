/** Browser -> local API -> independent processes -> audited 3D replay. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'ariadna-studio-'));
const output=process.env.ARIADNA_UI_OUTPUT?path.resolve(process.env.ARIADNA_UI_OUTPUT):null;
if(output)await fs.mkdir(output,{recursive:true});
const child=spawn(process.platform==='win32'?'python':'python3',['-u','scripts/start_local.py','--port','0','--output',path.join(temporary,'runs')],{stdio:['ignore','pipe','pipe']});let diagnostics='';child.stderr.on('data',b=>diagnostics+=b);const lines=createInterface({input:child.stdout});
let page,browser,context;const errors=[],checks=[],captions=[];let recordingStarted=0;function mark(text){const t=(Date.now()-recordingStarted)/1000;if(captions.length)captions.at(-1).end=t;captions.push({start:t,end:t+1,text});}
async function checkApartmentWidth(page, label) {
 const layout=await page.evaluate(()=>{
  const width=document.documentElement.scrollWidth;
  return {width, viewport:innerWidth, outside:width>innerWidth+1?[...document.querySelectorAll('body *')]
   .filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,8)
   .map(el=>el.id||el.getAttribute('class')||el.tagName):[]};
 });
 assert.ok(layout.width<=layout.viewport+1,'Apartment overflow '+label+' '+JSON.stringify(layout));
}
try{
 const url=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Studio startup: '+diagnostics)),15000);lines.on('line',line=>{const match=line.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});child.on('exit',code=>reject(Error('Studio exited '+code+': '+diagnostics)));});
 browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader'],...(process.env.ARIADNA_BROWSER?{executablePath:process.env.ARIADNA_BROWSER}:{})});
 context=await browser.newContext({viewport:{width:1440,height:1100}});recordingStarted=Date.now();page=await context.newPage();mark('Ариадна 0.9.0. Полевые миссии и редактор карт. Запуск «Лесной переправы» из интерфейса.');page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/#/mission');await page.locator('#tour-skip').click();
 assert.deepEqual(await page.locator('#episode option').evaluateAll(xs=>xs.map(x=>x.value)),['forest','quarry','city','snow','delta','cosmic']);await page.locator('#run-scenario').click();await page.waitForFunction(()=>window.ARIADNA_EDITOR.state().busy);
 const forestJob=await page.evaluate(()=>window.ARIADNA_EDITOR.state().job);
 assert.equal((await page.evaluate(()=>window.ARIADNA_EDITOR.getMap())).geography,'forest');await page.waitForFunction(()=>!window.ARIADNA_EDITOR.state().busy&&window.ARIADNA_EDITOR.state().hasResult,{},{timeout:300000});assert.match(await page.locator('#run-progress').textContent(),/Миссия выполнена/);checks.push('default_campaign_real_rerun');
 const forestRun=await (await page.request.get(url+'/api/studio/runs/'+forestJob)).json();
 assert.ok(forestRun.summary.metrics.step_count>0&&forestRun.summary.metrics.step_count<=180);
 assert.equal(forestRun.summary.audit.status,'passed');
 await page.locator('#watch-mission').click();
 await page.evaluate(()=>{window.ariadna.pause();window.ariadna.seek(9999);});
 mark('«Лесная переправа» завершена. Все цели закрыты, аудит журналов пройден.');
 if(output){await page.screenshot({path:path.join(output,'forest-current.png')});await page.waitForTimeout(2500);}
 await page.locator('[data-page="editor"]').click();await page.waitForFunction(()=>window.ariadna.state().page==='editor');await page.waitForFunction(()=>window.ARIADNA_EDITOR.state().connected);await page.waitForFunction(()=>document.querySelector('#editor-view').dataset.texturesLoaded==='6');assert.equal(await page.locator('#editor-view').getAttribute('data-renderer'),'webgl2');checks.push('studio_connected','webgl_editor','local_textures');
 assert.equal(await page.locator('[data-preset]').count(),6);for(const id of ['quarry','city','snow','delta','forest']){await page.locator('[data-preset="'+id+'"]').click();assert.equal((await page.evaluate(()=>window.ARIADNA_EDITOR.getMap())).terrain,id);if(output){await page.waitForTimeout(250);await page.locator('#editor-stage').screenshot({path:path.join(output,'map-'+id+'.png')});}}checks.push('five_distinct_missions');
 // Place and remove an actual obstacle by clicking the top-down 3D canvas.
 mark('На карте можно разместить препятствия и цели. Физическая карта фиксируется перед запуском.');await page.locator('#map-clear').click();await page.locator('#editor-top').click();const bounds=await page.locator('#editor-view').boundingBox();await page.mouse.click(bounds.x+bounds.width*.25,bounds.y+bounds.height*.5);assert.equal((await page.evaluate(()=>window.ARIADNA_EDITOR.getMap())).objects.length,1);await page.locator('[data-tool="erase"]').click();await page.mouse.click(bounds.x+bounds.width*.25,bounds.y+bounds.height*.5);assert.equal((await page.evaluate(()=>window.ARIADNA_EDITOR.getMap())).objects.length,0);checks.push('canvas_place_and_erase');
 await page.locator('#map-import').setInputFiles('examples/custom_forest.json');await page.waitForFunction(()=>window.ARIADNA_EDITOR.getMap().targets.length===4);assert.equal((await page.evaluate(()=>window.ARIADNA_EDITOR.getMap())).targets.length,4);await page.locator('#editor-3d').click();if(output)await page.screenshot({path:path.join(output,'studio-editor.png'),fullPage:true});
 await page.locator('#map-export').click();mark('Запуск миссии прямо на созданной карте. Среда и контроллер работают отдельными процессами через HTTP.');await page.locator('#run-mission').click();await page.waitForFunction(()=>window.ARIADNA_EDITOR.state().busy);assert.equal(await page.locator('#map-clear').isDisabled(),true);assert.equal(await page.locator('#map-title').isDisabled(),true);const job=await page.evaluate(()=>window.ARIADNA_EDITOR.state().job);checks.push('map_import_export','editing_frozen_during_mission');
 await page.waitForFunction(()=>window.ARIADNA_EDITOR.state().liveFrames>3,{},{timeout:150000});assert.equal(await page.locator('#page-editor').isVisible(),true);assert.equal(await page.locator('#editor-live').isVisible(),true);checks.push('live_execution_on_authored_map');await page.reload({waitUntil:'domcontentloaded',timeout:90000});await page.waitForFunction(()=>window.ARIADNA_EDITOR.state().busy&&window.ARIADNA_EDITOR.state().liveFrames>3,{},{timeout:150000});assert.equal(await page.locator('#map-clear').isDisabled(),true);checks.push('live_restore_after_reload');if(output)await page.screenshot({path:path.join(output,'studio-live.png'),fullPage:true});mark('Агенты ищут скрытые цели, обходят препятствия и принимают решения автономно. Редактирование во время миссии заблокировано.');await page.waitForFunction(()=>!window.ARIADNA_EDITOR.state().busy&&window.ARIADNA_EDITOR.state().hasResult,{},{timeout:150000});mark('Миссия завершена. Повтор показывает исполнение, планы штаба и проверенные журналы.');await page.locator('#watch-mission').click();await page.evaluate(()=>{window.ariadna.pause();window.ariadna.seek(9999);});assert.equal(await page.locator('#completion').textContent(),'100%');assert.match(await page.locator('#audit').textContent(),/Запись проверена/);assert.equal(await page.locator('#mission-finish').isVisible(),true);assert.ok((await page.evaluate(()=>window.ariadna.state())).frames>10);checks.push('real_http_mission','discovery_and_completion','audited_replay');
 const packet=await page.request.get(url+'/api/studio/runs/'+job);const value=await packet.json();assert.equal(value.summary.status,'success');assert.equal(value.summary.audit.status,'passed');assert.equal(value.result.episodes[0].frames[0].targets.length,0);const archive=await page.request.get(url+'/api/studio/runs/'+job+'/evidence.zip');assert.ok(archive.ok());assert.equal((await archive.body()).subarray(0,2).toString(),'PK');checks.push('hidden_targets_stay_private','downloadable_raw_evidence');
 for(const [id,step,name] of [['pressure',0,'pressure'],['flood',8,'flood'],['peer',8,'peer']]){await page.evaluate(([id,step])=>{window.ariadna.choose(id);window.ariadna.go('mission');window.ariadna.seek(step);},[id,step]);if(output)await page.locator('#page-mission').screenshot({path:path.join(output,name+'.png')});}await page.evaluate(id=>window.ariadna.choose('custom_'+id),job);await page.evaluate(()=>window.ariadna.seek(12));await page.locator('#section-toggle').click();if(output)await page.screenshot({path:path.join(output,'studio-mission.png'),fullPage:true});
 mark('Исторический контрольный эпизод: штаб сравнивает планы по публичному наблюдению. Оценка прогноза и ограничения сохранены в решении.');await page.evaluate(()=>{window.ariadna.choose('pressure');window.ariadna.seek(0);window.ariadna.go('decisions');});assert.equal(await page.locator('#alternatives > *').count()>0,true);await page.waitForTimeout(1800);if(output)await page.screenshot({path:path.join(output,'decisions.png'),fullPage:true});
 mark('Исследовательская развилка контрольного эпизода: альтернативы из одного состояния. Это отдельное исследование, а не управление активной миссией.');await page.evaluate(()=>window.ariadna.go('branches'));await page.waitForTimeout(1500);
 mark('Исторический эпизод «Наводнение»: отказ меняет доступных исполнителей. Фактические состояния взяты из проверенного журнала.');await page.evaluate(()=>{window.ariadna.choose('flood');window.ariadna.go('mission');window.ariadna.seek(8);});await page.waitForTimeout(1500);
 mark('Журнал связывает наблюдение, метасценарное решение, команды и фактические результаты. Внешних команд в проверке пока ноль.');await page.evaluate(()=>window.ariadna.go('journal'));await page.waitForTimeout(1800);if(output)await page.screenshot({path:path.join(output,'journal.png'),fullPage:true});checks.push('defense_meta_decisions_branches_journal');
 for(const width of [390,768,1440]){await page.setViewportSize({width,height:1000});await page.locator('[data-page="editor"]').click();await page.waitForFunction(()=>window.ariadna.state().page==='editor');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Editor overflow '+width);}
 await page.locator('#map-clear').click();assert.equal(await page.locator('#mission-result').isVisible(),false);assert.equal(await page.locator('#run-evidence').isVisible(),false);checks.push('editing_clears_previous_result');checks.push('responsive_studio');
 const apartment=page;
 mark('Квартира 42. Обучение подсвечивает элементы интерфейса. Трёхмерную сцену можно вращать и приближать.');
 await apartment.setViewportSize({width:320,height:900});
 await apartment.goto(url+'/home.html');
 await apartment.locator('#campaign button').first().waitFor();
 await checkApartmentWidth(apartment,'welcome');
 await apartment.setViewportSize({width:1440,height:1100});
 assert.equal(await apartment.locator('#campaign button').count(),3);
 assert.equal(await apartment.locator('.page:not([hidden])').count(),1);
 await apartment.locator('#tour-start').click();
 assert.equal(await apartment.locator('#tour-progress').textContent(),'01 / 06');
 assert.equal(await apartment.locator('#tour-focus').isVisible(),true);
 await apartment.locator('#tour-next').click();
 assert.equal(await apartment.locator('#tour-progress').textContent(),'02 / 06');
 await apartment.waitForFunction(()=>document.getElementById('home-map').dataset.renderer==='webgl2');
 assert.match(await apartment.locator('#scene-note').textContent(),/маршрут «Термоса»/);
 if(output)await apartment.screenshot({path:path.join(output,'apartment-tour.png')});
 for(let index=3;index<=6;index++){
  await apartment.locator('#tour-next').click();
  assert.equal(await apartment.locator('#tour-progress').textContent(),'0'+index+' / 06');
 }
 await apartment.locator('#tour-close').click();
 assert.equal(await apartment.locator('#tour-overlay').isVisible(),false);
 await apartment.locator('[data-page="overview"]').click();
 if(output)await apartment.screenshot({path:path.join(output,'apartment-campaign.png'),fullPage:true});
 await apartment.locator('#campaign button').first().click();
 assert.equal(await apartment.locator('#network-value').textContent(),'11 / 11');
 const map=apartment.locator('#home-map');
 await map.scrollIntoViewIfNeeded();
 const view=await map.boundingBox();
 const picture=()=>map.evaluate(canvas=>canvas.toDataURL());
 const beforeOrbit=await picture();
 await apartment.mouse.move(view.x+view.width*.46,view.y+view.height*.46);
 await apartment.mouse.down();
 await apartment.mouse.move(view.x+view.width*.57,view.y+view.height*.50,{steps:4});
 await apartment.mouse.up();
 assert.notEqual(await picture(),beforeOrbit,'Dragging must rotate the paused map');
 const beforeZoom=await picture();
 await apartment.locator('#map-zoom-in').click();
 assert.notEqual(await picture(),beforeZoom);
 await apartment.locator('#map-top').click();
 assert.equal(await apartment.locator('#map-top').getAttribute('aria-pressed'),'true');
 await apartment.locator('#map-fit').click();
 assert.equal(await apartment.locator('#map-top').getAttribute('aria-pressed'),'false');
 await apartment.locator('#map-agent').selectOption('vacuum_a');
 assert.match(await apartment.locator('#map-selected').textContent(),/Щётка/);
 await apartment.getByRole('button',{name:'Вход залит',exact:true}).click();
 assert.equal(await apartment.locator('#story-title').textContent(),'Вход залит');
 assert.match(await apartment.locator('#scene-note').textContent(),/маршрут/);
 await apartment.getByRole('button',{name:'Через кабинет',exact:true}).click();
 assert.match(await apartment.locator('#story-response').textContent(),/сухую дверь/);
 mark('При протечке робот обходит мокрый вход через кабинет и подходит к вентилю через служебную дверь.');
 await apartment.getByRole('button',{name:'Через служебную дверь',exact:true}).click();
 assert.match(await apartment.locator('#story-response').textContent(),/к вентилю/);
 await apartment.getByRole('button',{name:'Ключ у вентиля',exact:true}).click();
 assert.match(await apartment.locator('#mission-tasks').textContent(),/Ключ у вентиляГотово/);
 if(output)await apartment.screenshot({path:path.join(output,'apartment-operation.png'),fullPage:true});
 await apartment.locator('[data-page="fleet"]').click();
 await apartment.locator('.fleet-card').first().waitFor();
 assert.equal(await apartment.locator('.fleet-card').count(),9);
 await apartment.locator('.fleet-card button').first().click();
 assert.match(await apartment.locator('#map-selected').textContent(),/Щётка/);
 await apartment.locator('[data-page="fleet"]').click();
 await apartment.locator('[data-filter="site"]').click();
 assert.equal(await apartment.locator('.fleet-card').count(),9);
 assert.match(await apartment.locator('.fleet-card').filter({hasText:'Узел прачечной'}).textContent(),/Отказ/);
 await apartment.locator('[data-filter="digital"]').click();
 assert.equal(await apartment.locator('.fleet-card').count(),2);
 await apartment.locator('[data-page="live"]').click();
 await apartment.locator('#case').selectOption('impact');
 await apartment.locator('#incident-links button').filter({hasText:'Столкновение'}).click();
 assert.match(await apartment.locator('#story-response').textContent(),/Щётка.*выход из строя/);
 assert.equal(await apartment.locator('#run-tools').isVisible(),false);
 await apartment.locator('#case').selectOption('blackout');
 await apartment.getByRole('button',{name:'Связь прервалась',exact:true}).click();
 assert.equal(await apartment.locator('#network-value').textContent(),'10 / 11');
 await apartment.getByRole('button',{name:'Связь вернулась',exact:true}).click();
 assert.equal(await apartment.locator('#network-value').textContent(),'11 / 11');
 await apartment.locator('[data-page="decisions"]').click();
 await apartment.locator('#decision-times button').filter({hasText:'Собрать новый план'}).first().click();
 assert.ok(await apartment.locator('#decision-graph .tag').count()>1);
 if(output)await apartment.screenshot({path:path.join(output,'apartment-decisions.png'),fullPage:true});
 await apartment.locator('[data-page="compare"]').click();
 mark('Развилка сопоставляет два плана из одного состояния после отказа узла связи.');
 assert.equal(await apartment.locator('#compare-table tr').count(),3);
 await apartment.locator('#branch-timeline').fill('6');
 assert.equal(await apartment.locator('#branch-time').textContent(),'+6 с');
 assert.ok(await apartment.locator('#fork-reference circle').count()>0);
 if(output)await apartment.screenshot({path:path.join(output,'apartment-branches.png'),fullPage:true});
 for(const width of [320,390,768]){
  await apartment.setViewportSize({width,height:900});
  for(const id of ['overview','live','fleet','decisions','compare']){
   await apartment.locator('[data-page="'+id+'"]').click();
   await checkApartmentWidth(apartment,id);
  }
 }
 await apartment.setViewportSize({width:1440,height:1000});
 await apartment.locator('[data-page="live"]').click();
 await apartment.locator('#case').selectOption('privacy');
 await apartment.getByRole('button',{name:'Жилец закрыл двери',exact:true}).click();
 assert.match(await apartment.locator('#story-response').textContent(),/служебная дверь закрыты/);
 await apartment.getByRole('button',{name:'Рой остановился',exact:true}).click();
 assert.match(await apartment.locator('#story-response').textContent(),/остались на своих местах/);
 mark('Когда обе двери закрыты, штаб останавливает роботов. Новый HTTP-прогон подтверждает безопасную остановку.');
 await apartment.locator('#run-tools > summary').click();
 await apartment.locator('#run').click();
 await apartment.locator('#evidence-link').waitFor({state:'visible',timeout:150000});
 assert.match(await apartment.locator('#live-status').textContent(),/Безопасная остановка · аудит пройден/);
 const apartmentEvidence=await apartment.request.get(new URL(await apartment.locator('#evidence-link').getAttribute('href'),url).href);
 assert.ok(apartmentEvidence.ok());
 assert.equal((await apartmentEvidence.body()).subarray(0,2).toString(),'PK');
 await apartment.goto(url+'/home.html');
 await apartment.locator('#campaign button').first().waitFor();
 assert.equal(await apartment.locator('#welcome').isVisible(),false);
 await apartment.locator('#guide-open').click();
 assert.equal(await apartment.locator('#tour-progress').textContent(),'01 / 06');
 await apartment.locator('#tour-close').click();
 checks.push('apartment_guided_tour', 'apartment_orbit_zoom_selection_and_impact', 'apartment_campaign_webgl', 'apartment_devices', 'apartment_dag_and_fork', 'apartment_responsive', 'apartment_live_http_and_evidence');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'passed',checks,summary:value.summary,console_errors:errors}));
}catch(error){if(page&&output)await page.screenshot({path:path.join(output,'studio-failure.png'),fullPage:true}).catch(()=>{});throw error;}
finally{if(context)await context.close();if(browser)await browser.close();child.kill('SIGTERM');lines.close();await fs.rm(temporary,{recursive:true,force:true});}
