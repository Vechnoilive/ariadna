"""Compatibility, diverse maps, faults and bounded load. No external team claims."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from hackroi.audit import audit,read_records
from hackroi.client import Client
from hackroi.contracts import ProtocolError,canonical
from hackroi.environment import Environment
from hackroi.http import EnvironmentApplication
from hackroi.portable import PortableController
from interop.faults import FaultServer
from scripts.run_demo import Process
from scripts.stage5_cases import parameters


class PeerProcess:
    def __init__(self,arguments):
        self.process=subprocess.Popen([sys.executable,'-u',str(ROOT/'interop/peer.py'),*arguments],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',cwd=ROOT,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1'})
        self.lines=queue.Queue();self.errors=[];self.side_events={}
        def stdout():
            for line in self.process.stdout:self.lines.put(line)
            self.lines.put(None)
        def stderr():self.errors.extend(self.process.stderr.readlines())
        self.threads=[threading.Thread(target=stdout,daemon=True),threading.Thread(target=stderr,daemon=True)]
        for t in self.threads:t.start()
    def event(self,kind,timeout=30):
        while True:
            line=self.lines.get(timeout=timeout)
            if line is None:raise RuntimeError('Peer process exited: '+''.join(self.errors))
            value=json.loads(line)
            if value.get('event')==kind:return value
            self.side_events[value.get('event')]=value
    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        for t in self.threads:t.join(timeout=2)
        self.process.stdout.close();self.process.stderr.close()


class MeasuredController(PortableController):
    def __init__(self,*args):super().__init__(*args);self.latencies=[];self.body_sizes=[]
    def decide(self,*args,**kwargs):
        start=time.perf_counter();result=super().decide(*args,**kwargs)
        self.latencies.append(time.perf_counter()-start);self.body_sizes.append(len(canonical(result).encode()))
        return result


def measurement(controller):
    values=sorted(controller.latencies)
    return {'decisions':len(values),'p95_decision_seconds':round(values[min(len(values)-1,math.ceil(.95*len(values))-1)],6) if values else None,
            'max_decision_bytes':max(controller.body_sizes,default=0),
            'forecast_skipped_steps':sum(r['kind']=='decision' and r['decision'].get('ariadna_portable',{}).get('mode')=='meta_budget' for r in controller.journal.records)}




@contextmanager
def atomic_zip(path):
    temporary=path.with_name(path.name+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            yield archive
        with temporary.open('r+b') as stream:
            stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def persist_sources(directory,environment_records,controller_records):
    """Persist actual captured records once, after writers stop; never fill missing results."""
    with atomic_zip(directory/'sources.zip') as archive:
        for name,records in (('environment.jsonl',environment_records),('controller.jsonl',controller_records)):
            if not records:continue
            data=(''.join(canonical(record)+'\n' for record in records)).encode('utf-8')
            (directory/name).write_bytes(data)
            archive.writestr(name,data)


def controlled_episode(directory,seed,mission=None,peer=False,partial=False):
    directory.mkdir(parents=True)
    arguments=['environment','--port','0','--log-path',str(directory/'environment.jsonl')]
    if peer and partial:arguments.append('--partial')
    env=PeerProcess(arguments) if peer else Process(arguments)
    sources=None
    try:
        url=env.event('ready')['url'];controller=MeasuredController(directory/'controller.jsonl')
        if mission:controller.mission_parameters=mission
        start=time.perf_counter();error=None
        try:summary=controller.run(url,seed,210,run_id='stage5_'+directory.name+'_'+str(seed))
        except ProtocolError as ex:
            error={'code':ex.code,'message':ex.message}
            records=read_records(directory/'environment.jsonl');final=records[-1]['output']
            summary={k:final[k] for k in ('episode_id','time','metrics')};summary['status']='protocol_error'
        c=controller.journal.snapshot();e=Client(url,max_response_bytes=64*1024*1024).get('logs')['records']
        sources=(e,c)
        verified=audit(e,c) if error is None else {'status':'incomplete','reason':'actual_error_preserved'}
        (directory/'replay.json').write_text(json.dumps([r['output']['observation'] for r in e if r['kind'] in ('reset','step')],ensure_ascii=False),encoding='utf-8')
        return {**summary,'error':error,'audit':verified,'performance':measurement(controller),'execution_seconds':round(time.perf_counter()-start,6),
                'initial_public_sha256':hashlib.sha256(canonical(e[0]['output']['observation']).encode()).hexdigest()}
    finally:
        env.stop()
        if sources:persist_sources(directory,*sources)


def peer_episode(directory,seed,peer_environment=False):
    directory.mkdir(parents=True)
    env=(PeerProcess if peer_environment else Process)(['environment','--port','0','--log-path',str(directory/'environment.jsonl')]);ctrl=None
    sources=None
    try:
        url=env.event('ready')['url'];ctrl=PeerProcess(['controller','--environment-url',url,'--seed',str(seed),'--log-path',str(directory/'controller.jsonl'),'--emit-log'])
        ready=ctrl.event('ready');health=Client(ready['url']).request('GET','/v1/controller/health')
        if health.get('status')!='ready':raise ValueError('Independent controller not ready')
        result=ctrl.event('episode_complete')
        c=ctrl.side_events['controller_log']['records'];e=Client(url,max_response_bytes=64*1024*1024).get('logs')['records'];sources=(e,c)
        steps=[r for r in e if r['kind']=='step']
        return {k:result[k] for k in ('status','time','metrics')} | {'foreign_scenario_ids_seen':sorted({sid for r in steps for sid in r['input']['selected_configuration']['scenario_ids']}),
            'audit':audit(e,c)}
    finally:
        if ctrl:ctrl.stop()
        env.stop()
        if sources:persist_sources(directory,*sources)


def fault_case(directory,mode):
    directory.mkdir(parents=True)
    environment=Environment(directory/'environment.jsonl');controller=MeasuredController(directory/'controller.jsonl');controller.max_response_bytes=65536
    with FaultServer(EnvironmentApplication(environment),mode) as proxy:
        error=None
        try:controller.run(proxy.url,42,5,run_id='fault_'+mode)
        except ProtocolError as ex:error={'code':ex.code,'message':ex.message}
        steps=[p for method,path,p in proxy.requests if path.endswith('/step')]
        closes=[p for method,path,p in proxy.requests if path.endswith('/close')]
        actual=environment.state['step_count'] if environment.state else 0
        expected='TIMEOUT' if mode in ('lost_after_commit','unavailable') else 'INVALID_REQUEST'
        passed=error is not None and error['code']==expected and len(steps)==(0 if mode=='unavailable' else 1) and actual==(0 if mode=='unavailable' else 1)
        if environment.state and closes:passed=passed and all(p['episode_id']==environment.state['episode_id'] for p in closes)
        persist_sources(directory,environment.journal.snapshot(),controller.journal.snapshot())
        (directory/'requests.json').write_text(json.dumps(proxy.requests,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'status':'passed' if passed else 'failed','expected_error':expected,'error':error,'step_http_requests':len(steps),'committed_steps':actual,
                'audit':{'status':'incomplete_expected','reason':'fault injected after request, no fabricated acknowledgment'}}


def run(output=None,suite='full'):
    design_path=ROOT/'experiments/stage5_design.json';design=json.loads(design_path.read_text(encoding='utf-8'))
    output=Path(output).resolve() if output else ROOT/'artifacts'/('stage5_'+uuid.uuid4().hex[:10]);output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):raise ValueError('Нужен пустой каталог результатов')
    rows=[]
    seeds=[('development',s) for s in design['development_seeds']]
    if suite=='full':seeds += [('holdout',s) for s in design['holdout_seeds']]
    for label,seed in seeds:
        for name in (design['native_cases'] if suite=='full' else ['flood_single']):
            result=controlled_episode(output/f'{label}_{seed}_{name}',seed,parameters(name));rows.append({'category':'native','split':label,'seed':seed,'case':name,**result})
            print('verified',label,seed,name,result['status'],flush=True,file=sys.stderr)
    for seed in (design['peer_seeds'] if suite=='full' else [42]):
        for partial in (False,True):
            name='portable_to_peer_partial' if partial else 'portable_to_peer'
            result=controlled_episode(output/f'{name}_{seed}',seed,peer=True,partial=partial);rows.append({'category':'interop','case':name,'seed':seed,**result})
        for peer in (False,True):
            name='peer_to_peer' if peer else 'peer_to_native'
            result=peer_episode(output/f'{name}_{seed}',seed,peer);rows.append({'category':'interop','case':name,'seed':seed,**result})
    for case in (design['load_cases'] if suite=='full' else design['load_cases'][:1]):
        name='load_'+str(case['cohorts']);p=parameters('flood_team');p.update(case)
        result=controlled_episode(output/name,42,p);rows.append({'category':'load','case':name,'seed':42,'agents':5*case['cohorts']+3,**result})
    for mode in design['fault_modes']:rows.append({'category':'fault','case':mode,**fault_case(output/mode,mode)})
    mission_rows=[r for r in rows if r['category']!='fault'];faults=[r for r in rows if r['category']=='fault']
    result={'format':'ariadna.stage5.v1','design':design,'design_sha256':hashlib.sha256(design_path.read_bytes()).hexdigest(),'suite':suite,'results':rows,
            'summary':{'mission_cases':len(mission_rows),'mission_successes':sum(r['status']=='success' for r in mission_rows),
                       'fault_probes':len(faults),'fault_probes_passed':sum(r['status']=='passed' for r in faults),'external_team_endpoints_tested':0},
            'scope':'Independent local implementations, not a third-party team tournament.'}
    # Persist one complete source archive after all writers have exited.
    with atomic_zip(output/'evidence.zip') as z:
        for packet in sorted(output.rglob('sources.zip')):
            with zipfile.ZipFile(packet) as captured:
                if captured.testzip() is not None:raise ValueError('Повреждён пакет исходных свидетельств')
                for name in captured.namelist():z.writestr(str(packet.parent.relative_to(output)/name).replace('\\','/'),captured.read(name))
    result['evidence_zip_sha256']=hashlib.sha256((output/'evidence.zip').read_bytes()).hexdigest()
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Испытания совместимости, отказов и нагрузки','','Версия 0.5.0.','','## 1 Область проверки','','Локальный стенд с двумя реализациями; реальный межкомандный турнир не проводился.','',
           '## 2 Результаты','','| Категория | Случай | Seed | Исход | Шаги | Выполнение |','|---|---|---|---|---|---|']
    for r in rows:lines.append(f"| {r['category']} | {r['case']} | {r.get('seed','—')} | {r['status']} | {r.get('time','—')} | {r.get('metrics',{}).get('mission_completion','—')} |")
    lines += ['','## 3 Ограничения','','Независимый peer — собственный тестовый стенд с отдельным кодом, а не участник хакатона. Реальный внешний турнир не выполнялся. Отказы с потерей подтверждения ожидаемо дают неполный аудит; повторный POST и выдуманный успех не применяются. Время вычисления зависит от оборудования.','']
    (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);p.add_argument('--suite',choices=['full','smoke'],default='full');a=p.parse_args()
    print(json.dumps(run(a.output,a.suite),ensure_ascii=False,indent=2))
