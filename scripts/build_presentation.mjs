/** Optional publisher using the Artifact Tool bundled authoring runtime. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const modules=process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES;if(!modules)throw Error('Bundled artifact authoring runtime is required; mission runtime does not need it');
const require=createRequire(path.join(modules,'.ariadna.cjs'));
const {Presentation,PresentationFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const workspace=path.resolve(process.argv[2]||path.join(root,'artifacts/presentation_build'));
await fs.mkdir(workspace,{recursive:true});
const data=JSON.parse((await fs.readFile(path.join(root,'viewer/legacy-data.js'),'utf8')).replace(/^window.ARIADNA_DEMO = /,'').replace(/;\n$/,''));
const stage4=JSON.parse(await fs.readFile(path.join(root,'experiments/results/stage4_summary.json'),'utf8'));
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const bg='#09141B',white='#E8EEE9',muted='#A6B7BD',mint='#8CE2C4',orange='#FFB86B',blue='#69B4EA',purple='#C2A7F2',font='DejaVu Sans';
const invisible={style:'solid',fill:'none',width:0};
function text(slide,value,x,y,w,h,size=28,color=white,bold=false){const s=slide.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:invisible});s.text=value;s.text.style={fontSize:size,typeface:font,color,bold,verticalAlignment:'top',wrap:true};return s;}
function slide(title,source){const s=deck.slides.add();s.background.fill=bg;if(title)text(s,title,60,42,1160,80,42,white,true);text(s,String(deck.slides.count).padStart(2,'0'),1195,665,40,26,16,muted);s.speakerNotes.text=source;return s;}
async function picture(slide,name,x,y,w,h){const bytes=await fs.readFile(path.join(root,'submission/assets',name));slide.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:'image/png',alt:'Записанный интерфейс Ариадны '+name,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
function chart(s,type,categories,series,pos,options={}){return s.charts.add(type,{position:pos,categories,series:series.map(s=>({...s,values:s.values.map(v=>Math.round(v*1e9)/1e9)})),lineOptions:{smooth:false},hasLegend:true,chartFill:bg,chartLine:invisible,plotAreaFill:bg,plotAreaLine:invisible,legend:{position:'bottom',textStyle:{typeface:font,fontSize:17,fill:muted}},xAxis:{textStyle:{typeface:font,fontSize:17,fill:muted},line:{style:'solid',fill:'#35505F',width:1}},yAxis:{min:0,textStyle:{typeface:font,fontSize:17,fill:muted},majorGridlines:{style:'solid',fill:'#29404C',width:1},line:invisible},...options});}
{
 const s=slide(null,'Источник: submission/assets/scene.png. Реальная WebGL-сцена редактора forest, браузерный контур CI 705c6ad, выпуск 0.8.0. Синтетическая среда спасения.');
 text(s,'АРИАДНА',60,76,800,92,76,white,true);text(s,'Контрфактический\nштаб для\nнеоднородного роя',64,225,565,230,38,mint);
 await picture(s,'scene.png',660,185,550,405);
 text(s,'Метарой 1.0 · Заречкин Артём · версия 0.8.0',64,638,1050,36,20,muted);
}
{
 const s=slide('Два процесса и проверяемый результат','Источники: docs/EXPLANATORY_NOTE.md; hackroi/client.py, environment.py, counterfactual.py, audit.py. Рабочий контроллер не импортирует симулятор.');
 // Required architecture diagram stays native/editable.
 const blocks=[['Контроллер','Убеждения → сценарии →\nбезопасные команды',70,180],['HTTP JSON','Наблюдения, возможности,\nрешения и результаты',450,180],['Среда','Физика, события,\nресурсы и mesh-сеть',830,180]];
 for(const [title,body,x,y] of blocks){const box=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:330,height:195},fill:'#101F29',line:{style:'solid',fill:'#3D5968',width:1}});text(s,title,x+18,y+18,294,50,26,mint,true);text(s,body,x+18,y+78,294,95,23,white);}
 text(s,'↔',405,239,50,60,40,orange);text(s,'↔',785,239,50,60,40,orange);
 text(s,'Оба журнала → повтор выбора аудитором → автономный просмотр',70,430,1120,62,30,white,true);
 text(s,'Скрытые цели и будущее расписание событий остаются в среде.\nОфлайн-ветвление собственной модели вынесено в исследовательский инструмент.',70,525,1110,106,25,muted);
}
{
 const ep=data.episodes.find(x=>x.id==='pressure'),d=ep.decisions[0],cs=d.forecast.candidates;
 const s=slide('Штаб сравнивает четыре допустимых плана','Источник: viewer/legacy-data.js → pressure.decisions[0].forecast. Seed 42, t=0. Оценка условная и не является официальной метрикой турнира. Формула и коэффициенты: docs/PROTOCOL.md.');
 chart(s,'bar',cs.map(x=>({meta:'Метаплан',frontier:'Разведка',nearby:'Ближняя цель',reserve:'Резерв'})[x.candidate_id]),[{name:'Устойчивая оценка',values:cs.map(x=>Math.round(x.score*1000)/1000),fill:mint}],{left:70,top:170,width:730,height:425},{hasLegend:false,barOptions:{direction:'column',grouping:'clustered'},dataLabels:{showValue:true,position:'outEnd',textStyle:{typeface:font,fontSize:20,fill:white}}});
 text(s,'Горизонт — 6 шагов',855,190,340,80,30,orange,true);
 text(s,'Только известные объекты\nи публичные ограничения',855,290,345,110,25,white);
 text(s,'После действия измеряется\nошибка прогноза; доверие\nк модели обновляется.',855,440,345,130,25,muted);
 text(s,'Прогнозы альтернатив условны; фактический ответ здесь есть только у выбранного плана.',70,630,1100,40,18,muted);
}
{
 const r=data.research,colors={meta:mint,frontier:blue,nearby:orange,reserve:purple};const names={meta:'Метаплан',frontier:'Разведка',nearby:'Ближняя цель',reserve:'Резерв'};
 const s=slide('Измеренные альтернативы из одной точки','Источники: submission/evidence.zip → branches/branches.json; viewer/legacy-data.js → research. Все fork_checkpoint_sha256 совпадают. Замороженные публичные намерения, 6 шагов, не полные миссии.');
 chart(s,'line',['0','1','2','3','4','5','6'],r.branches.map(b=>({name:names[b.candidate_id],values:[0,...b.actual_curve.map(x=>x.completion)],line:{style:'solid',fill:colors[b.candidate_id],width:3},marker:{symbol:'circle',size:5}})),{left:70,top:170,width:740,height:420},{yAxis:{min:0,max:.1,numberFormatCode:'0.0%',textStyle:{typeface:font,fontSize:18,fill:muted},majorGridlines:{style:'solid',fill:'#29404C',width:1}}});
 text(s,'+8,33 п.п.',870,195,335,100,48,orange,true);text(s,'Прирост выполнения\nnearby / reserve\nза шесть шагов',870,310,330,145,27,white);
 text(s,'Все ветви: running.\nДанные исследования\nне поступали контроллеру.',870,495,335,125,22,muted);
 text(s,'Одинаковое полное исходное состояние · фиксированное продолжение намерений',70,635,1080,35,19,muted);
}
{
 const s=slide('Отказы меняют исполнителей и роли','Источник: viewer/legacy-data.js → flood, seed 2027. Деградация лодки t=3, новый запрет t=4, отказ инфраструктуры t=5, отказ наземного агента t=8, противоречия t=9. Исход: success, t=29, аудит passed.');
 await picture(s,'flood.png',60,150,900,425);
 text(s,'13 агентов',990,175,240,70,32,mint,true);text(s,'8 целей',990,270,240,65,32,white,true);text(s,'29 шагов',990,365,240,65,32,orange,true);text(s,'Аудит пройден',990,465,230,80,25,muted);
 text(s,'Синтез DAG, безопасная остановка и другой интерфейс показаны отдельными эпизодами.',65,620,1130,55,23,muted);
}
{
 const groups=stage4.aggregate.groups.filter(x=>x.split==='holdout'),names={fixed:'Фиксированный',reactive:'Реактивный',meta:'Метаконтроллер',counterfactual:'Штаб'};
 const s=slide('Сравнение на отложенных условиях','Источник: experiments/results/stage4_summary.json, aggregate.groups, split=holdout. 4 случая × seed 101/202, старое семейство с фиксированной геометрией и seed%3. Penalized steps: неуспех получает полный лимит.');
 chart(s,'bar',groups.map(g=>names[g.controller]),[{name:'Средние шаги со штрафом за неуспех',values:groups.map(g=>g.mean_penalized_steps),fill:blue}],{left:70,top:170,width:740,height:420},{barOptions:{direction:'column'},dataLabels:{showValue:true,position:'outEnd',textStyle:{typeface:font,fontSize:20,fill:white}}});
 text(s,'Успешные миссии',875,180,330,60,27,mint,true);let y=260;for(const g of groups){text(s,`${names[g.controller]}: ${g.successes} / ${g.episodes}`,875,y,335,55,23,white);y+=65;}
 text(s,'Маленький собственный набор. На случае дефицита реактивный алгоритм быстрее штаба.',70,635,1130,40,19,muted);
}
{
 const s=slide('Переносимость и границы доказательства','Источники: experiments/results/stage5_summary.json; docs/TEST_PROTOCOL.md; tests/test_portable.py. Peer не импортирует hackroi и не является другой командой. Официальный минимальный порог M5 не подтверждён.');
 text(s,'26 / 26',70,165,600,100,74,mint,true);text(s,'успешных внутренних миссий',75,270,630,60,28,white);
 text(s,'8 / 8',70,370,600,100,70,orange,true);text(s,'ожидаемых реакций на повреждения',75,470,650,80,27,white);
 text(s,'Другая семантика действий и ресурсов\nЧастичное исполнение\nНагрузка до 43 агентов',760,180,450,200,27,white);
 text(s,'Реальных внешних команд: 0\nМежкомандный турнир ещё впереди.\nЛокальный стенд не закрывает M5.',760,440,455,165,26,orange);
}
{
 const s=slide('Пять разных мест спасения','Источники: scenarios/missions/*.json, docs/PROTOCOL.md; submission/assets/map-quarry.png записан браузерным контуром CI 705c6ad. Препятствия физические, поверхность кинематическая.');
 await picture(s,'map-quarry.png',60,160,850,440);
 text(s,'Лесной кордон\nРазлом в карьере\nГород без связи\nПолярная станция\nДельта после шторма',940,180,285,310,26,white);
 text(s,'Своя карта и запуск\nв той же 3D-сцене',940,520,290,95,25,mint,true);
 text(s,'Поиск скрытых целей, обход объёмов и перестройка после отказов через публичный HTTP.',65,635,1130,40,20,muted);
}
{
 const s=slide('Десять миссий завершены с аудитом','Источники: experiments/results/missions_080_summary.json и missions_080_validation.json, submission/missions_evidence.zip. Только внутренний демонстрационный набор. Baselines на этих тесных картах получили 10 ошибок коллизий, поэтому сравнение среднего времени с ними не вычисляется.');
 chart(s,'bar',['Лес','Карьер','Город','Снег','Дельта'],[{name:'Штатный seed карты',values:[21,51,34,50,32],fill:mint},{name:'Дополнительный seed 1009',values:[21,29,34,33,33],fill:blue}],{left:65,top:155,width:890,height:445},{barOptions:{direction:'column',grouping:'clustered'},dataLabels:{showValue:true,position:'outEnd',textStyle:{typeface:font,fontSize:19,fill:white}}});
 text(s,'10 / 10',990,195,250,90,55,mint,true);text(s,'success\nАудит passed',990,315,240,110,27,white);
 text(s,'Модельные шаги. Дополнительный seed меняет события. Официальный балл не вычислялся.',65,635,1140,45,19,muted);
}
{
 const s=slide('Комплект для проверки и защиты','Источники: docs/SUBMISSION.md; scripts/run_stage6.py; scripts/build_release.py; scripts/verify_release.py. Точный канал и срок сдачи требуют подтверждения организаторов.');
 text(s,'start.bat  /  python scripts/start_local.py --open',70,170,1130,70,37,mint,true);
 text(s,'Выбрать карту, запустить миссию и открыть проверенный повтор',70,260,1110,80,26,white);
 text(s,'Исходники и сценарии\nЗаписка DOCX / PDF\nПрезентация и скринкаст\nЖурналы, эксперименты и эссе',70,380,635,220,28,white);
 text(s,'MANIFEST.json\nSHA-256 каждого файла\nПроверка после распаковки',800,390,400,165,29,orange,true);
 text(s,'Закрытый архив или приватный репозиторий передаются по установленному каналу организаторов.',70,640,1100,40,18,muted);
}
for(let i=0;i<deck.slides.count;i++){const blob=await deck.export({slide:deck.slides.getItem(i),format:'png',scale:1});await fs.writeFile(path.join(workspace,`slide-${i+1}.png`),new Uint8Array(await blob.arrayBuffer()));}
const {finalizePresentation}=await import(pathToFileURL('/root/.codex/skills/builtins/presentations/container_tools/artifact_tool_utils.mjs').href);
const candidate=path.join(workspace,'candidate.pptx');await(await PresentationFile.exportPptx(deck)).save(candidate);
await fs.mkdir(path.join(workspace,'output'),{recursive:true});
const finalPath=path.join(workspace,'output/defense.pptx');
const result=await finalizePresentation({workspaceDir:workspace,candidatePath:candidate,finalPath,pythonExecutable:process.env.CODEX_PRIMARY_RUNTIME_PYTHON,integrityValidatorPath:'/root/.codex/skills/builtins/presentations/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:'/root/.codex/skills/builtins/presentations/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:10,requiredNativeChartOwnerSlides:[3,4,6,9],requiredNativeTableOwnerSlides:[],fontPolicy:{basis:'design',families:[font]},materializeLiteralChartWorkbooks:true,verifyArtifactToolImport:true,receiptPath:path.join(workspace,'validation.json')});
const checked=await PresentationFile.importPptx(await FileBlob.load(finalPath));for(let i=0;i<checked.slides.count;i++){const png=await checked.export({slide:checked.slides.getItem(i),format:'png',scale:1});await fs.writeFile(path.join(workspace,`final-${i+1}.png`),new Uint8Array(await png.arrayBuffer()));}
console.log(JSON.stringify({finalPath,slides:10,result}));
