/** Optional Playwright screencast. Captures the real offline viewer, with captions. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
const require=createRequire(import.meta.url);let chromium;try{({chromium}=require('playwright'));}catch{({chromium}=require(path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES||'','playwright')));}
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),out=path.resolve(process.argv[2]||path.join(root,'submission'));
await fs.mkdir(path.join(out,'assets'),{recursive:true});const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'ariadna-video-'));
const browser=await chromium.launch({headless:true,...(process.env.ARIADNA_BROWSER?{executablePath:process.env.ARIADNA_BROWSER}:{})});
const context=await browser.newContext({viewport:{width:1280,height:900},recordVideo:{dir:temporary,size:{width:1280,height:900}}});const recordingStarted=Date.now();const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));const captions=[];let clock=0;
async function caption(text,seconds){const actualStart=(Date.now()-recordingStarted)/1000;captions.push({start:actualStart,end:actualStart+seconds,text});clock+=seconds;await page.evaluate(text=>{let p=document.getElementById('recording-caption');if(!p){p=document.createElement('div');p.id='recording-caption';p.style.cssText='position:fixed;bottom:0;left:0;right:0;background:rgba(3,12,18,.97);border-top:1px solid #527263;color:#fff;padding:17px 45px;z-index:9999;font:19px/1.5 system-ui;text-align:center;pointer-events:none';document.body.append(p);}p.textContent=text;},text);await page.waitForTimeout(seconds*1000);}
async function show(id,step=0){await page.evaluate(([id,step])=>{window.ariadna.choose(id);window.ariadna.go('mission');window.ariadna.seek(step);window.scrollTo(0,0);},[id,step]);}
try{
 await page.goto(pathToFileURL(path.join(root,'viewer/index.html')).href);
 await page.locator('#tour-skip').click();
 for(const [id,step] of [['flood',8],['pressure',0],['peer',8]]){await show(id,step);await page.locator('#page-mission').screenshot({path:path.join(out,'assets',id+'.png')});if(id==='flood')await page.locator('#map-stage').screenshot({path:path.join(out,'assets','scene.png')});}
 if(process.argv.includes('--capture-only')){await context.close();console.log(JSON.stringify({status:'captured',output:out}));}
 else{
 await show('pressure',0);await caption('Ариадна: неоднородный рой и контрфактический штаб. Это записанные HTTP-эпизоды с пройденным аудитом.',7);
 await page.locator('#page-mission').scrollIntoViewIfNeeded();await caption('Перед действием сравниваются четыре допустимых плана. Горизонт шесть шагов; используются только публичные сведения.',8);
 for(const step of [1,2,4]){await page.evaluate(step=>window.ariadna.seek(step),step);await caption('Следующий шаг сопоставляется с прогнозом: расход энергии, координаты, выполнение и состояния. Ошибка обновляет доверие.',3);}
 await page.evaluate(()=>window.ariadna.go('branches'));await page.locator('#research').scrollIntoViewIfNeeded();await caption('Развилка измеряет альтернативы собственной среды из одинакового полного состояния. Факт ветви — сплошная линия, прогноз — пунктир.',9);
 await page.locator('[data-branch="meta"]').click();await page.evaluate(()=>window.ariadna.seek(5));await caption('На карте показана измеренная ветвь метаплана. Продолжаются фиксированные намерения, а не полная новая политика.',7);
 await show('flood',0);await page.locator('#page-mission').scrollIntoViewIfNeeded();await caption('Наводнение: 13 агентов и восемь целей. Положения и препятствия определены новым семейством карт, seed 2027.',6);
 for(const [step,message] of [[3,'Деградация лодки меняет доступную скорость.'],[5,'Отказ инфраструктуры меняет публичную сеть.'],[8,'Отказ наземного агента требует переназначения работы.'],[9,'Противоречивая информация снижает уверенность.'],[29,'Миссия завершена за 29 шагов, аудит пройден.']]){await page.evaluate(step=>window.ariadna.seek(step),step);await caption(message,4);}
 await show('synthesis',0);await page.locator('#page-mission').scrollIntoViewIfNeeded();await caption('Дефицит и противоречивые сведения вызывают synthesize: проверенный DAG восстановления, подтверждения и доставки.',7);await page.evaluate(()=>window.ariadna.go('decisions'));await page.locator('#decision-data').evaluate(el=>el.open=true);await page.locator('#evidence').scrollIntoViewIfNeeded();await caption('Исходное наблюдение, ограничения, применимость, команды и идентификатор решения сохранены в структурированных журналах.',6);
 await show('stop',2);await page.locator('#page-mission').scrollIntoViewIfNeeded();await caption('Директива оператора вызывает safe_stop. Финальный safe_stopped не объявляется успешной миссией.',6);
 await show('peer',8);await page.locator('#page-mission').scrollIntoViewIfNeeded();await caption('Независимый peer: другой код, область координат от 100 метров, другие действия и ресурсы. Перевод основан на публичной декларации.',7);
 await page.evaluate(()=>window.ariadna.go('journal'));await page.locator('#commands').scrollIntoViewIfNeeded();await caption('Wire-команды navigate, inspect и drop сохраняются вместе с фактическими ответами. Peer — наш стенд; реальных внешних команд пока ноль.',7);
 await show('pressure',20);await caption('В комплекте: исходники, записка DOCX/PDF, сценарии, журналы, эксперименты и эссе. SHA-256 каждого файла проверяется сборщиком архива.',7);
 if(errors.length)throw Error('Browser errors: '+errors.join('; '));
 const video=page.video();await context.close();const source=await video.path();const target=path.join(out,'screencast.mp4');
 const ff=spawnSync('ffmpeg',['-y','-i',source,'-an','-r','12','-c:v','libx264','-preset','medium','-crf','30','-pix_fmt','yuv420p','-movflags','+faststart',target],{encoding:'utf8'});if(ff.status!==0)throw Error(ff.stderr);
 const stamp=v=>{const ms=Math.round(v*1000),s=Math.floor(ms/1000);return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+'.'+String(ms%1000).padStart(3,'0');};
 await fs.writeFile(path.join(out,'screencast.vtt'),'WEBVTT\n\n'+captions.map((c,i)=>`${i+1}\n${stamp(c.start)} --> ${stamp(c.end)}\n${c.text}\n`).join('\n'));
 console.log(JSON.stringify({status:'passed',output:target,caption_seconds:clock,console_errors:errors}));
 }
}finally{await browser.close();await fs.rm(temporary,{recursive:true,force:true});}
