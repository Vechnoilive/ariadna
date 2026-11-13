"""Reproducible five-map benchmark through independent HTTP processes; no UI pacing."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_demo import Process
from hackroi.audit import audit,read_records
from hackroi.client import Client
from hackroi.contracts import canonical
from hackroi.custom_maps import campaign_map
from hackroi.showcase import episode,FORMAT
from hackroi import __version__

def run(directory,modes=('portable',),seeds=None,mission_ids=None,*,dispersed=False,cosmic_enabled=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    catalog=json.loads((ROOT/'scenarios/missions/catalog.json').read_text(encoding='utf-8'));results=[];episodes=[]
    deployments=json.loads((ROOT/'scenarios/campaign/deployments.json').read_text(encoding='utf-8')) if dispersed else None
    if mission_ids:catalog=[entry for entry in catalog if entry['id'] in mission_ids]
    for entry in catalog:
      source=json.loads((ROOT/'scenarios/missions'/entry['file']).read_text(encoding='utf-8'))
      if deployments is not None:source=campaign_map(source,deployments)
      for seed in seeds or [source['seed']]:
       for mode in modes:
        name=f"{entry['id']}_{seed}_{mode}";folder=directory/name;folder.mkdir(exist_ok=False)
        definition={**source,'seed':seed}
        if entry['id']=='cosmic' and cosmic_enabled is not None:definition['include_cosmic']=cosmic_enabled
        map_path=folder/'map.json';map_path.write_text(canonical(definition)+'\n',encoding='utf-8')
        env=ctrl=None;started=time.monotonic()
        try:
            env=Process(['environment','--port','0','--map-file',str(map_path.resolve()),'--log-path',str((folder/'environment.jsonl').resolve())]);url=env.event('ready')['url'];client=Client(url,max_response_bytes=64*1024*1024);caps=client.get('capabilities')
            flag=['--portable'] if mode=='portable' else ['--baseline',mode]
            ctrl=Process(['controller','--port','0',*flag,'--environment-url',url,'--seed',str(seed),'--max-decisions','181','--run-id',name,'--log-path',str((folder/'controller.jsonl').resolve())]);ctrl.event('ready');summary=ctrl.event('episode_complete',timeout=300)
            records=client.get('logs')['records'];ctrl.stop();ctrl=None;control=read_records(folder/'controller.jsonl')
            ep=episode(name,source['title'],entry['description'],records,control,caps,summary)
            report=ep['audit'];summary['audit']=report
            if mode=='portable' and seed==source['seed']:episodes.append(ep)
            frames=ep['frames'];turns=0;paths={};direct={}
            for a in frames[0]['agents']:
                points=[next(b['position'] for b in f['agents'] if b['id']==a['id']) for f in frames if any(b['id']==a['id'] for b in f['agents'])];points=[p for p in points if p is not None];vectors=[[q[i]-p[i] for i in range(3)] for p,q in zip(points,points[1:]) if math.dist(p,q)>.01]
                for u,v in zip(vectors,vectors[1:]):
                    cos=sum(x*y for x,y in zip(u,v))/(math.sqrt(sum(x*x for x in u))*math.sqrt(sum(x*x for x in v)))
                    if cos<.95:turns+=1
                paths[a['id']]=round(sum(math.dist(p,q) for p,q in zip(points,points[1:])),5)
            record={'mission':entry['id'],'seed':seed,'controller':mode,'status':summary['status'],'time':summary['time'],'metrics':summary['metrics'],'audit':report['status'],'heading_changes':turns,'paths_metres':paths,'events':sorted({e['type'] for f in frames for e in f['events']}),'operations':sorted({r['decision']['operation'] for r in control if r['kind']=='decision'}),'map_sha256':hashlib.sha256(map_path.read_bytes()).hexdigest(),'seconds':round(time.monotonic()-started,3),'files':{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ['map.json','environment.jsonl','controller.jsonl']}}
            (folder/'summary.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');results.append(record);print(json.dumps({k:record[k] for k in ['mission','seed','controller','status','time','audit','heading_changes','seconds']},ensure_ascii=False),flush=True)
        except Exception as error:
            record={'mission':entry['id'],'seed':seed,'controller':mode,'status':'error','audit':'not_completed','error':str(error),'seconds':round(time.monotonic()-started,3)}
            (folder/'summary.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');results.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
        finally:
            if ctrl:ctrl.stop()
            if env:env.stop()
    (directory/'summary.json').write_text(json.dumps({'version':__version__,'results':results,'external_teams_tested':0,'official_score':None},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (directory/'showcase.json').write_text(canonical({'format':FORMAT,'version':__version__,'episodes':episodes,'external_teams_tested':0})+'\n',encoding='utf-8')
    with zipfile.ZipFile(directory/'evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(directory.rglob('*')):
            if f.is_file() and f.suffix in ('.json','.jsonl'):z.write(f,f.relative_to(directory).as_posix())
    return results
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'artifacts/missions_080');p.add_argument('--baselines',action='store_true');p.add_argument('--seeds',type=int,nargs='+');p.add_argument('--missions',nargs='+',choices=['forest','quarry','city','snow','delta','cosmic'])
    p.add_argument('--dispersed', action='store_true', help='Use the current studio deployment presets')
    a=p.parse_args();rows=run(a.output,('portable','fixed','reactive') if a.baselines else ('portable',),a.seeds,a.missions,dispersed=a.dispersed)
    if any(r['audit']!='passed' or (r['controller']=='portable' and r['status']!='success') for r in rows):raise SystemExit(1)
