"""Independent test peer, not another team's entry. Standard library only.
This file deliberately imports no hackroi modules, schemas or physics helpers.
"""
import argparse
import copy
import hashlib
import json
import math
import random
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path


def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def resource(name,value=1.,minimum=0.,semantic=None):
    return {'id':name,'value':value,'minimum':minimum,'maximum':1.,'unit':'normalized',**({'semantic':semantic} if semantic else {})}
def schema(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
POSITION={'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}}
ALIASES={'move':('navigate',{'target':'destination'}),'observe':('inspect',{'target_id':'object_id'}),
         'deliver':('drop',{'target_id':'object_id'}),'charge':('recharge',{'station_id':'node_id'})}


class Peer:
    def __init__(self,log=None,partial=False,dt=1.):
        self.dt=dt
        self.log=Path(log) if log else None;self.records=[];self.state=None;self.cache={};self.lock=threading.RLock();self.partial=partial
    def append(self,record):
        self.records.append(copy.deepcopy(record))
        if self.log:
            self.log.parent.mkdir(parents=True,exist_ok=True)
            with self.log.open('a',encoding='utf-8',newline='\n') as stream:stream.write(canonical(record)+'\n')
    def health(self):return {'protocol_version':'1.0','component':'environment','status':'ready','environment_id':'independent_peer_fixture','capabilities_url':'/v1/environment/capabilities'}
    def capabilities(self):return {'protocol_version':'1.0','environment_id':'independent_peer_fixture','semantic_profile':'a2x.public-model.v1',
        'units':{'position':'metre','time':'second'},'reset_parameters':['max_steps'],'limits':{'max_body_bytes':65536},
        'execution_semantics':{'batch':'partial' if self.partial else 'atomic','configuration':'atomic'},
        'actions':[{'action':v[0],'semantic':k,'parameter_mapping':v[1]} for k,v in ALIASES.items()],
        **({'dt_seconds':self.dt} if self.dt!=1. else {})}
    def reset(self,p):
        if set(p['mission']['parameters'])-{'max_steps'}:raise ValueError('Foreign reset profile was not negotiated')
        rng=random.Random(p['seed']);ep='peer_'+hashlib.sha256(canonical(p).encode()).hexdigest()[:20]
        agents=[]
        for i in range(2):
            descriptors=[]
            for action,(wire,mapping) in ALIASES.items():
                key=next(iter(mapping.values()));properties={key:POSITION if action=='move' else {'type':'string'}}
                descriptors.append({'action':wire,'semantic':action,'parameter_mapping':mapping,'parameters_schema':schema(properties),
                                    'energy_cost':.0045,'execution_energy':.004 if action in ('observe','deliver') else 0.})
            agents.append({'id':'peer.unit.'+str(i),'kind':'ground','position':[101.,102.+4*i,0.],'status':'active',
                'capabilities':[x[0] for x in ALIASES.values()]+['sense'],'resources':{'battery':resource('battery',minimum=.08,semantic='energy'),'cargo':resource('cargo',semantic='supplies')},
                'communication':{'connected':True,'quality':1.},'role':None,'scenario_ids':[],'available_actions':descriptors,
                'constraints':[{'id':'public_drive','type':'motion_limits','bounds':{'lower':[100.,100.,0.],'upper':[160.,150.,0.]},
                    'speed':4.,'energy_per_metre':.001,'idle_energy':.0005,'action_energy':.004,'interaction_radius':1.,'charge_radius':3.,
                    'charging_rate':.12,'delivery_supplies':.2,'sensor_radius':12.,'degraded_speed_factor':.6},
                    {'id':'battery_drain','type':'energy_limits','idle_energy':.0005}]})
        def node(identifier,kind,position,resources,capabilities):return {'id':identifier,'kind':kind,'position':position,'status':'active','capabilities':capabilities,
            'resources':resources,'communication':{'connected':True,'quality':1.},'constraints':[]}
        infra=[node('peer.hub','base_station',[100.,100.,0.],{},['relay']),node('peer.dock','charging_station',[102.,102.,0.],{'charge':resource('charge',semantic='stock')},['charge'])]
        targets=[{'id':'peer.goal.'+str(i),'position':[x,y,0.],'priority':float(i+1),'status':'unconfirmed'} for i,(x,y) in enumerate(
            [(rng.uniform(114,122),rng.uniform(106,114)),(rng.uniform(139,150),rng.uniform(128,139)),(rng.uniform(112,124),rng.uniform(133,143))])]
        zone={'id':'peer.wall','type':'exclusion','semantic_type':'obstacle','geometry':{'type':'box','lower':[125.,100.,0.],'upper':[128.,120.,1.]},
              'access':{},'risk':0.,'cost':{'energy':1.,'time':1.},'communication':{},'constraints':[]}
        self.state={'episode_id':ep,'request_id':p['request_id'],'time':0.,'mission':{'id':'search_and_rescue','objectives':[
            {'id':'job.'+t['id'],'type':'deliver','target_id':t['id'],'priority':t['priority'],'status':'pending'} for t in targets],
            'priorities':['deliver','safety'],'directives':[],'constraints':[],'status':'active','termination':{'time_limit':p['mission']['parameters'].get('max_steps',150)*(self.dt if self.dt!=1. else 1)}},
            'agents':agents,'infrastructure':infra,'targets':targets,'zones':[zone],
            'network':{'connectivity_score':1.,'partition_count':0,'reachable_agent_ratio':1.,'average_link_quality':1.,'mesh_available':True,'link_range':1000.,
                       'known_links':[{'source':'peer.hub','target':a['id'],'quality':1.,'delay':1.} for a in agents]},
            'events':[],'constraints':[{'id':'collision_distance','minimum_metres':.5}],
            'metrics':{'mission_completion':0.,'step_count':0,'energy_used':0.},
            'observation_quality':{'global_completeness':0.,'maximum_delay':0.,'stale_data_ratio':0.,'contradiction_count':0,'unknown_state_ratio':1.},
            '_seen':set(),'_configuration':{'scenario_ids':[],'role_assignments':{}},'_parameters':{},'_status':'running','_closed':False}
        self.discover()
    def discover(self):
        s=self.state
        for t in s['targets']:
            if any(math.dist(a['position'],t['position'])<=12. for a in s['agents']):s['_seen'].add(t['id'])
        ratio=len(s['_seen'])/len(s['targets']);s['observation_quality'].update(global_completeness=ratio,unknown_state_ratio=1.-ratio)
    def observation(self):
        s=self.state;result={k:copy.deepcopy(v) for k,v in s.items() if not k.startswith('_')}
        result['protocol_version']='1.0';result['targets']=[t for t in result['targets'] if t['id'] in s['_seen']]
        return result
    def response(self,outcomes=None):
        s=self.state;return {'protocol_version':'1.0','episode_id':s['episode_id'],'request_id':s['request_id'],'time':s['time'],
            'status':s['_status'],'observation':self.observation(),'metrics':copy.deepcopy(s['metrics']),'events':[],'command_results':outcomes or []}
    def step(self,d):
        s=self.state
        if s['_closed'] or s['_status']!='running' or d['time']!=s['time'] or d['episode_id']!=s['episode_id']:raise ValueError('stale or closed episode')
        if d['previous_configuration']!=s['_configuration']:raise ValueError('previous configuration mismatch')
        ids=d['selected_configuration']['scenario_ids'];op=d['operation']
        if op=='keep' and (ids!=s['_configuration']['scenario_ids'] or d['role_assignments']!=s['_configuration']['role_assignments'] or d['selected_configuration']['parameters']!=s['_parameters']):raise ValueError('invalid keep')
        old=copy.deepcopy(s);results=[];used=set()
        try:
            for index,c in enumerate(d['commands']):
                a=next(a for a in s['agents'] if a['id']==c['agent_id']);wire=c['action'];p=c['parameters']
                if a['id'] in used:raise ValueError('duplicate agent')
                used.add(a['id'])
                if self.partial and s['time']==0. and index==0:
                    results.append({'agent_id':a['id'],'action':wire,'status':'rejected','reason':'fixture_transient_busy'});continue
                action=next(k for k,v in ALIASES.items() if v[0]==wire);cost=.004
                if action=='move':
                    target=p['destination'];start=a['position'];distance=math.dist(start,target);f=min(1.,4.*self.dt/distance) if distance else 0.
                    end=[round(x+f*(y-x),12) for x,y in zip(start,target)]
                    if not 100<=end[0]<=160 or not 100<=end[1]<=150 or end[2]!=0.:raise ValueError('bounds')
                    # Independent slab intersection implementation in two dimensions.
                    t0,t1=0.,1.
                    for dim,lo,hi in ((0,125.,128.),(1,100.,120.)):
                        dx=end[dim]-start[dim]
                        if dx==0:
                            if not lo<=start[dim]<=hi:t0,t1=1.,0.;break
                        else:
                            near,far=sorted(((lo-start[dim])/dx,(hi-start[dim])/dx));t0=max(t0,near);t1=min(t1,far)
                    if t0<=t1:raise ValueError('wall')
                    cost=math.dist(start,end)*.001;a['position']=end
                elif action in ('observe','deliver'):
                    t=next(t for t in s['targets'] if t['id']==p['object_id'] and t['id'] in s['_seen'])
                    if math.dist(a['position'],t['position'])>1.:raise ValueError('target range')
                    if action=='deliver':
                        if t['status']!='confirmed' or a['resources']['cargo']['value']<.2:raise ValueError('cargo or confirmation')
                        t['status']='delivered';a['resources']['cargo']['value']=round(a['resources']['cargo']['value']-.2,12)
                    else:t['status']='confirmed'
                elif action=='charge':
                    n=next(n for n in s['infrastructure'] if n['id']==p['node_id'])
                    if math.dist(a['position'],n['position'])>3.:raise ValueError('station range')
                    amount=min(.12,1.-a['resources']['battery']['value'],n['resources']['charge']['value'])
                    a['resources']['battery']['value']+=amount;n['resources']['charge']['value']-=amount;cost=0.
                if a['resources']['battery']['value']-cost<.08-1e-12:raise ValueError('energy reserve')
                a['resources']['battery']['value']=round(a['resources']['battery']['value']-cost,12);s['metrics']['energy_used']+=cost
                results.append({'agent_id':a['id'],'action':wire,'status':'applied'})
            for a in s['agents']:
                cost=min(.0005,max(0.,a['resources']['battery']['value']-.08));a['resources']['battery']['value']=round(a['resources']['battery']['value']-cost,12);s['metrics']['energy_used']+=cost
                a['role']=d['role_assignments'].get(a['id']);a['scenario_ids']=list(ids) if a['role'] else []
            s['time']=round(s['time']+self.dt,12);s['request_id']=d['request_id'];s['metrics']['step_count']+=1
            s['_configuration']={'scenario_ids':list(ids),'role_assignments':copy.deepcopy(d['role_assignments'])};s['_parameters']=copy.deepcopy(d['selected_configuration']['parameters'])
            self.discover();total=sum(t['priority'] for t in s['targets']);s['metrics']['mission_completion']=sum(t['priority'] for t in s['targets'] if t['status']=='delivered')/total
            s['metrics']['energy_used']=round(s['metrics']['energy_used'],12)
            for o,t in zip(s['mission']['objectives'],s['targets']):o['status']='completed' if t['status']=='delivered' else 'pending'
            if op=='safe_stop':s['_status']=s['mission']['status']='safe_stopped'
            elif all(t['status']=='delivered' for t in s['targets']):s['_status']='success';s['mission']['status']='completed'
            elif s['time']>=s['mission']['termination']['time_limit']:s['_status']='time_limit';s['mission']['status']='failed'
        except Exception:
            self.state=old;raise
        return results
    def dispatch(self,method,path,payload):
        with self.lock:
            operation=path.rsplit('/',1)[-1]
            if method=='GET':
                if operation=='health':return self.health()
                if operation=='capabilities':return self.capabilities()
                if operation=='observation':return self.observation()
                if operation=='logs':return {'protocol_version':'1.0','records':copy.deepcopy(self.records)}
                raise ValueError('unknown route')
            if method!='POST' or operation not in ('reset','step','close'):raise ValueError('unknown operation')
            key=payload['request_id'];fingerprint=canonical([operation,payload])
            if key in self.cache:
                old,response=self.cache[key]
                if old!=fingerprint:raise ValueError('idempotence conflict')
                return copy.deepcopy(response)
            if payload.get('protocol_version')!='1.0':raise ValueError('version')
            outcomes=[]
            if operation=='reset':self.reset(payload)
            elif operation=='step':outcomes=self.step(payload)
            else:
                self.state['_closed']=True;self.state['request_id']=key
                if self.state['_status']=='running':self.state['_status']=self.state['mission']['status']='safe_stopped'
            response=self.response(outcomes)
            self.append({'kind':operation,'protocol_version':'1.0','component':'environment','episode_id':response['episode_id'],
                         'request_id':key,'decision_id':payload.get('decision_id'),'time':response['time'],'input':payload,'output':response})
            self.cache[key]=(fingerprint,copy.deepcopy(response));return response


def serve(application,port=0,component='environment'):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle_request(self):
            payload=None
            try:
                if self.command=='POST':
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=65536:raise ValueError('request size')
                    payload=json.loads(self.rfile.read(length).decode('utf-8'))
                body=application(self.command,self.path,payload);code=200
            except Exception as ex:
                code=422;body={'protocol_version':'1.0','request_id':(payload or {}).get('request_id'),'episode_id':(payload or {}).get('episode_id'),
                               'error':{'code':'INVALID_COMMAND','message':str(ex),'details':{}}}
            data=canonical(body).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        do_GET=handle_request;do_POST=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();return server,thread


def peer_control(url,seed=42,max_steps=150,log_path=None,emit_log=False):
    records=[]
    def record(value):
        if emit_log:records.append(copy.deepcopy(value))
        if log_path:
            path=Path(log_path);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("a",encoding="utf-8",newline="\n") as stream:stream.write(canonical(value)+"\n")
    def request(operation,payload=None):
        path='/v1/environment/'+operation
        data=canonical(payload).encode() if payload else None
        with urllib.request.urlopen(urllib.request.Request(url+path,data=data,headers={'Content-Type':'application/json'}),timeout=5) as response:return json.load(response)
    capabilities=request('capabilities')
    params={'profile':'rescue_v2','events':[],'max_steps':max_steps} if 'rescue_v2' in capabilities.get('profiles',[]) else {'max_steps':max_steps}
    reset={'protocol_version':'1.0','request_id':'peer_reset_'+str(seed),'seed':seed,'mission':{'id':'search_and_rescue','parameters':params}}
    response=request('reset',reset)
    record({'protocol_version':'1.0','component':'controller','kind':'reset','episode_id':response['episode_id'],'input':reset,'output':response})
    previous={'scenario_ids':[],'role_assignments':{}}
    pending={};visited=set()
    for index in range(max_steps):
        o=response['observation'];roles={a['id']:'worker' for a in o['agents']};commands=[];used=set();occupied=set()
        for a in o['agents']:
            if a['id'] in pending and math.dist(a['position'],pending[a['id']])<=1.:
                visited.add((a['kind'],tuple(pending.pop(a['id']))))
        for a in sorted(o['agents'],key=lambda a:a['id']):
            if a['position'] is None or a['status'] not in ('active','degraded') or not a['communication'].get('connected'):continue
            lim=next((x for x in a['constraints'] if x.get('id')=='ariadna.motion.v1'),None)
            if lim is None:
                declaration=next((x for x in a['constraints'] if x.get('type')=='motion_limits'),None)
                if declaration:lim={**declaration,'min':declaration['bounds']['lower'],'max':declaration['bounds']['upper']}
            if lim is None:continue
            known=[]
            descriptors={d.get('semantic',d['action']):d for d in a['available_actions']}
            acts=set(descriptors)
            for t in o['targets']:
                if t['status']!='delivered' and t['id'] not in used and all(lo<=v<=hi for v,lo,hi in zip(t['position'],lim['min'],lim['max'])) and 'deliver' in acts:known.append(t)
            if known:
                pending.pop(a['id'],None)
                t=min(known,key=lambda t:(math.dist(a['position'],t['position']),t['id']));used.add(t['id'])
                action='move' if math.dist(a['position'],t['position'])>1. else ('deliver' if t['status']=='confirmed' else 'observe')
                p={'target':t['position']} if action=='move' else {'target_id':t['id']}
            elif 'move' in acts:
                destination=pending.get(a['id'])
                if destination is None:
                    candidates=[];spacing=lim.get('sensor_radius',12.)
                    for ix in range(1,21):
                        x=lim['min'][0]+ix*spacing
                        if x>lim['max'][0]:break
                        for iy in range(1,21):
                            y=lim['min'][1]+iy*spacing
                            if y>lim['max'][1]:break
                            point=[x,y,a['position'][2]];key=(a['kind'],tuple(point))
                            if key not in visited and key not in occupied:candidates.append(point)
                    if not candidates:continue
                    destination=min(candidates,key=lambda v:(math.dist(a['position'],v),v[1],v[0]));pending[a['id']]=destination
                occupied.add((a['kind'],tuple(destination)))
                action='move';p={'target':destination}
            else:continue
            if action=='move':
                for zone in o['zones']:
                    if zone.get('semantic_type',zone['type']) not in ('obstacle','restricted'):continue
                    g=zone['geometry'];lo=g.get('min',g.get('lower'));hi=g.get('max',g.get('upper'))
                    if lo is None:continue
                    first,last=0.,1.
                    for axis in range(3):
                        delta=p['target'][axis]-a['position'][axis]
                        if delta==0:
                            if not lo[axis]<=a['position'][axis]<=hi[axis]:first,last=1.,0.;break
                        else:
                            near,far=sorted(((lo[axis]-a['position'][axis])/delta,(hi[axis]-a['position'][axis])/delta));first=max(first,near);last=min(last,far)
                    if first<=last:
                        p={'target':[a['position'][0],min(lim['max'][1],hi[1]+.6),a['position'][2]]}
            desc=descriptors[action];mapping=desc.get('parameter_mapping',{})
            commands.append({'agent_id':a['id'],'action':desc['action'],'parameters':{mapping.get(k,k):v for k,v in p.items()}})
        fingerprint=hashlib.sha256(canonical(o).encode()).hexdigest()
        d={'protocol_version':'1.0','request_id':'peer_step_'+str(index),'episode_id':o['episode_id'],'decision_id':'peer_decision_'+str(index),'time':o['time'],
           'operation':'select' if not previous['scenario_ids'] else 'keep','previous_configuration':previous,
           'selected_configuration':{'scenario_ids':['foreign_rescue'],'parameters':{},'synthesized_scenario':None},'role_assignments':roles,'commands':commands,
           'candidate_evaluations':[{'scenario_id':'foreign_rescue','applicable':True,'selected':True}],
           'constraint_checks':[],'explanation':{'observation_refs':['sha256:'+fingerprint],'reason_codes':['independent_peer_policy'],'expected_effects':['deliver'],'confidence':1.}}
        record({'protocol_version':'1.0','component':'controller','kind':'decision','episode_id':o['episode_id'],'decision_id':d['decision_id'],'request_id':d['request_id'],'time':o['time'],'observation':o,'decision':d})
        response=request('step',d)
        record({'protocol_version':'1.0','component':'controller','kind':'result','episode_id':response['episode_id'],'decision_id':d['decision_id'],'request_id':d['request_id'],'output':response})
        previous={'scenario_ids':['foreign_rescue'],'role_assignments':roles}
        if response['status']!='running':break
    request('close',{'protocol_version':'1.0','episode_id':response['episode_id'],'request_id':'peer_close_'+str(seed)})
    if emit_log:print(canonical({'event':'controller_log','records':records}),flush=True)
    return {k:response[k] for k in ('episode_id','status','time','metrics')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['environment','controller']);parser.add_argument('--port',type=int,default=0);parser.add_argument('--log-path',type=Path);parser.add_argument('--partial',action='store_true');parser.add_argument('--environment-url');parser.add_argument('--seed',type=int,default=42);parser.add_argument('--dt',type=float,default=1.);parser.add_argument('--emit-log',action='store_true')
    args=parser.parse_args()
    if args.mode=='environment':
        peer=Peer(args.log_path,args.partial,args.dt);server,thread=serve(peer.dispatch,args.port)
        print(canonical({'event':'ready','url':'http://127.0.0.1:'+str(server.server_address[1])}),flush=True);thread.join()
    else:
        server,thread=serve(lambda m,p,b:{'protocol_version':'1.0','component':'controller','status':'ready','controller_id':'independent_peer_policy','supported_operations':['select','keep']},args.port,'controller')
        print(canonical({'event':'ready','url':'http://127.0.0.1:'+str(server.server_address[1])}),flush=True)
        print(canonical({'event':'episode_complete',**peer_control(args.environment_url,args.seed,log_path=args.log_path,emit_log=args.emit_log)}),flush=True)
        try:thread.join()
        except KeyboardInterrupt:server.shutdown();server.server_close()
