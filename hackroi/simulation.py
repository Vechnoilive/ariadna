"""Детерминированная гражданская среда второго этапа."""
import copy
import hashlib
import math
from collections import deque

from .contracts import ACTION_SCHEMAS, ProtocolError, canonical, check
from .environment import agent, closest_distance, intersects_box
from .routing import body_contact, contact_time, expanded_box

PROFILES = {
    'aerial': (6.0, 0.002, ['move','observe','relay','send_message']),
    'ground': (3.0, 0.003, ['move','observe','deliver','charge','send_message']),
    'underground': (2.0, 0.004, ['move','observe','deliver','charge','send_message']),
    'surface_water': (4.0, 0.003, ['move','observe','deliver','charge','relay','send_message']),
    'underwater': (2.0, 0.004, ['move','observe','deliver','charge','send_message']),
    'cosmic': (10.0, 0.001, ['move','observe','relay','send_message']),
    'infrastructure': (0.0, 0.001, ['relay','send_message']),
    'digital': (0.0, 0.001, ['send_message']),
    'operator': (0.0, 0.0, ['send_message']),
}
EVENT_TYPES = {'agent_failure','agent_degradation','infrastructure_failure','connectivity_loss',
               'mission_priority_change','operator_directive','hazard_appeared','restricted_zone_appeared',
               'resource_shortage','target_detected','target_state_changed','contradictory_information',
               'stale_information','environment_change'}


def fail(message, code='CONSTRAINT_VIOLATION'):
    raise ProtocolError(code, message, 422)


def zone(identifier, kind, low, high, risk=0.0):
    return {'id':identifier,'type':kind,'geometry':{'type':'axis_aligned_box','min':low,'max':high},
            'access':{},'risk':risk,'cost':{'energy':1.0+risk,'time':1.0+risk},
            'communication':{},'constraints':[]}


def add_agent(s, identifier, kind, position, available=None):
    available = PROFILES[kind][2] if available is None else list(available)
    a=agent(identifier,kind,position,available)
    a['capabilities']=list(available)+(['sense'] if 'observe' in available else [])
    # Public execution limits: the controller need not import simulator constants.
    bounds = {'ground':([0,0,0],[49.999,100,0]),
              'surface_water':([50,0,0],[100,100,0]),
              'underwater':([50,0,-15],[100,100,-1]),
              'underground':([0,0,-12],[40,40,-1]),
              'aerial':([0,0,1],[100,100,30]),
              'cosmic':([0,0,50],[100,100,100])}.get(kind)
    if bounds:
        a['constraints'].append({'id':'ariadna.motion.v1','min':bounds[0],'max':bounds[1],
                                 'speed':PROFILES[kind][0], 'degraded_speed_factor':.5,
                                 'energy_per_metre':PROFILES[kind][1], 'idle_energy':.001,
                                 'action_energy':.005, 'interaction_radius':1., 'charge_radius':3.,
                                 'delivery_supplies':.25, 'sensor_radius':12., 'charging_rate':.1})
    for descriptor in a['available_actions']:
        descriptor['energy_cost'] = .001 if descriptor['action'] in ('relay','send_message') else .006
        descriptor['execution_energy'] = .001 if descriptor['action'] in ('relay','send_message') else (.005 if descriptor['action'] in ('observe','deliver') else 0.)
    a['constraints'].append({'id':'ariadna.energy.v1', 'idle_energy':.001})
    a['resources']['supplies']={'id':'supplies','value':1.0,'minimum':0.0,'maximum':1.0,'unit':'normalized'}
    s['agents'].append(a)
    return a


def initialize(s, request):
    p=request['mission']['parameters']
    for key, default in [('link_range',35.0),('message_loss',0.0)]:
        value=p.get(key,default)
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100:
            fail('Неверный параметр '+key,'INVALID_REQUEST')
    if p.get('message_loss',0)>1:fail('message_loss вне [0,1]','INVALID_REQUEST')
    if type(p.get('include_cosmic',False)) is not bool:fail('include_cosmic должен быть bool','INVALID_REQUEST')
    if type(p.get('include_compute_node',False)) is not bool:fail('include_compute_node должен быть bool','INVALID_REQUEST')
    s.update(profile='rescue_v2',seed=request['seed'],discovered=set(),pending_messages=[],
             delivered_messages=[],message_count=0,drop_count=0,energy_spent=0.0,
             link_range=float(p.get('link_range',35)),message_loss=float(p.get('message_loss',0)))
    initial=[('air','aerial',[8.,8.,10.]),('land','ground',[5.,8.,0.]),
             ('tunnel','underground',[8.,8.,-5.]),('boat','surface_water',[55.,8.,0.]),
             ('sub','underwater',[58.,8.,-5.]),('mast','infrastructure',[30.,8.,8.]),
             ('fusion','digital',None),('operator','operator',None)]
    if p.get('include_cosmic',False) or p.get('custom_map',{}).get('include_cosmic',False):initial.append(('orbital','cosmic',[10.,10.,60.]))
    s['agents']=[]
    for identifier,kind,position in initial:
        a = add_agent(s, identifier, kind, position)
        if kind == 'cosmic':
            from .cosmic import configure as configure_cosmic
            configure_cosmic(a)
    s['zones']=[zone('land','land',[0,0,0],[49.999,100,0]),zone('water','water',[50,0,-15],[100,100,0]),
                zone('sky','air',[0,0,1],[100,100,30]),zone('tunnel','underground',[0,0,-12],[40,40,-1]),
                zone('wall','obstacle',[42,40,-15],[46,60,30]),zone('forbidden','restricted',[80,80,-15],[90,90,100]),
                zone('unstable','hazard',[30,30,0],[35,35,20],.4),
                zone('mud','limited_access',[15,40,0],[25,60,0],.2),
                zone('shadow','low_connectivity',[65,40,-15],[80,60,30]),
                zone('depot','infrastructure',[0,0,-12],[10,10,10])]
    for i,node in enumerate(s['infrastructure']):
        node['position']=[[25.,8.,8.],[5.,5.,0.],[45.,8.,8.],[0.,0.,0.]][i]
        node['capabilities']={'relay':['relay'],'charging_station':['charge'],'sensor_node':['sense'],'base_station':['relay']}[node['kind']]
        node['resources']={'stock':{'id':'stock','value':1.,'minimum':0.,'maximum':1.,'unit':'normalized'}}
    bridge=copy.deepcopy(s['infrastructure'][0]);bridge.update(id='water_relay',position=[50.,8.,8.])
    s['infrastructure'].append(bridge)
    for a in s['agents']:
        if a['kind'] not in ('underground','surface_water','underwater'):continue
        station=copy.deepcopy(s['infrastructure'][1]);station.update(id='station_'+a['kind'],position=list(a['position']))
        s['infrastructure'].append(station)
    offset=request['seed']%3
    s['targets']=[{'id':f'person_{i}','position':pos,'status':'unconfirmed','priority':priority}
                  for i,(pos,priority) in enumerate([([25.+offset,8.,0.],2.),([75.,8.+offset,0.],3.),
                                                    ([25.,8.+offset,-5.],1.),([75.,8.,-5.],1.)])]
    s['mission']['objectives']=[{'id':'rescue_'+t['id'],'target_id':t['id'],'type':'deliver','priority':t['priority'],'status':'pending'} for t in s['targets']]
    s['mission']['priorities']=['search','confirm','deliver','connectivity','safety']
    s['constraints']=[{'id':'energy_reserve','minimum':.15},{'id':'collision_distance','minimum_metres':.5}]
    from .layouts import configure
    configure(s,p)
    if p.get('include_compute_node', False):
        from .compute import node
        s['infrastructure'].append(node())
    schedule=p.get('events',[
        {'time':12.,'type':'agent_degradation','targets':['boat'],'parameters':{}},
        {'time':16.,'type':'infrastructure_failure','targets':['infra_0'],'parameters':{}},
        {'time':22.,'type':'contradictory_information','targets':[],'parameters':{}},
        {'time':25.,'type':'hazard_appeared','targets':[],'parameters':{'min':[35,35,0],'max':[40,40,20]}},
    ])
    if not isinstance(schedule,list) or len(schedule)>100:fail('Неверный список событий','INVALID_REQUEST')
    s['schedule']=[]
    for i,event in enumerate(schedule):
        check(event,{'type':'object','required':['time','type','targets','parameters'], 'properties':{
            'time':{'type':'number','minimum':0},'type':{'enum':sorted(EVENT_TYPES)},
            'targets':{'type':'array','items':{'type':'string'}},'parameters':{'type':'object'}}})
        event=copy.deepcopy(event)
        if event['type'] in ('hazard_appeared','restricted_zone_appeared','environment_change'):
            low=event['parameters'].get('min',[35,35,0]); high=event['parameters'].get('max',[40,40,20])
            check(low,{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}})
            check(high,{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}})
            if any(a>b for a,b in zip(low,high)):fail('Перевёрнутые границы события','INVALID_REQUEST')
        known={a['id'] for a in s['agents']+s['infrastructure']+s['targets']}
        if any(t not in known for t in event['targets']):fail('Неизвестная сущность события','INVALID_REQUEST')
        if event['type']=='target_detected' and 'position' in event['parameters']:
            check(event['parameters']['position'],{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}})
            check(event['parameters'].get('priority',1.),{'type':'number','minimum':0.001,'maximum':100.})
        event.update(id='event_'+str(i),source='scenario',confidence=1.0,status='new')
        s['schedule'].append(event)
    s['fired']=set()
    events(s)
    network(s)
    discover(s)
    metrics(s)


def medium(kind, position):
    x,y,z=position
    if not 0<=x<=100 or not 0<=y<=100 or not -15<=z<=100: return False
    return {'ground':z==0 and x<50,'surface_water':z==0 and x>=50,
            'underwater':-15<=z<=-1 and x>=50,'underground':-12<=z<=-1 and x<=40 and y<=40,
            'aerial':1<=z<=30,'cosmic':50<=z<=100}.get(kind,False)


def network(s):
    nodes={a['id']:a for a in s['agents']+s['infrastructure'] if a['status'] in ('active','degraded','charging','safe_mode') and not a.get('link_disabled')}
    graph={k:[] for k in nodes}; links=[]
    def position(a):return a['position'] if a['position'] is not None else [0,0,0]
    for i,(key,a) in enumerate(sorted(nodes.items())):
        for other,b in sorted(nodes.items())[i+1:]:
            from .cosmic import link as cosmic_link
            satellite = cosmic_link(a,b,position(a),position(b))
            if satellite or (satellite is None and math.dist(position(a),position(b))<=s['link_range']):
                blocked=satellite is None and any(z['type']=='low_connectivity' and intersects_box(position(a),position(b),z['geometry']['min'],z['geometry']['max']) for z in s['zones'])
                if blocked:continue
                graph[key].append(other);graph[other].append(key)
                links.append({'source':key,'target':other,'quality':1.-s['message_loss'],'delay':2. if satellite else 1., **({'kind':'satellite'} if satellite else {})})
    s['graph']=graph
    reachable=set()
    for identifier in nodes:
        if route(s,'infra_3',identifier,nodes) is not None:reachable.add(identifier)
    spatial=[a for a in s['agents'] if a['status'] not in ('failed','offline')]
    ratio=sum(a['id'] in reachable for a in spatial)/max(1,len(spatial))
    remaining=set(graph); components=0
    while remaining:
        components+=1;stack=[remaining.pop()]
        while stack:
            for v in graph[stack.pop()]:
                if v in remaining:remaining.remove(v);stack.append(v)
    s['network']={'connectivity_score':ratio,'partition_count':max(0,components-1),
                  'reachable_agent_ratio':ratio,'average_link_quality':1.-s['message_loss'],
                  'mesh_available':True,'known_links':links,'link_range':s['link_range']}
    for a in s['agents']+s['infrastructure']:
        a['communication']={'connected':a['id'] in reachable,'quality':1.-s['message_loss'] if a['id'] in reachable else 0.}
        if a['position'] is None:
            a['communication']['anchor_position']=[0.,0.,0.]
        if a['kind']=='cosmic':
            served=[peer['id'] for peer in spatial if peer['id']!=a['id'] and a['id'] in (route(s,'infra_3',peer['id'],nodes) or [])[1:-1]]
            a['communication'].update(relayed_agents=served, relay_steps=s.get('cosmic_relay_steps',0),
                                      active_links=sum(a['id'] in (l['source'],l['target']) for l in links))


def route(s, source, destination, nodes=None):
    nodes=nodes or {a['id']:a for a in s['agents']+s['infrastructure']}
    graph=s['graph']
    if source not in graph or destination not in graph:return None
    queue=deque([[source]]);seen={source}
    while queue:
        path=queue.popleft();u=path[-1]
        if u==destination:return path
        if u!=source and 'relay' not in nodes[u]['capabilities']:continue
        for v in sorted(graph[u]):
            if v not in seen:seen.add(v);queue.append(path+[v])
    return None


def discover(s):
    home = s.get('layout') == 'home'
    for a in s['agents']:
        if a['status'] not in ('active','degraded') or not a['communication']['connected'] or 'sense' not in a['capabilities']:continue
        for t in s['targets']:
            if home and t['id']=='resident' and s['time']<s['home_release_at']:
                continue
            radius = a['constraints'][0]['sensor_radius'] if home else 12.
            if math.dist(a['position'],t['position'])<=radius and (
                not home or not obstructed(s, a['position'], t['position'])
            ):
                s['discovered'].add(t['id'])
    count=len(s['targets'])
    s['observation_quality']['global_completeness']=len(s['discovered'])/max(1,count)
    s['observation_quality']['unknown_state_ratio']=1.-s['observation_quality']['global_completeness']


def events(s):
    s['events']=[dict(e,status='active') for e in s['events']]
    entities={a['id']:a for a in s['agents']+s['infrastructure']}
    for event in s['schedule']:
        if event['id'] in s['fired'] or event['time']>s['time']:continue
        s['fired'].add(event['id']);e=copy.deepcopy(event);s['events'].append(e)
        kind=e['type'];p=e['parameters']
        for identifier in e['targets']:
            a=entities.get(identifier)
            if a is not None:
                if kind in ('agent_failure','infrastructure_failure'):a['status']='failed'
                elif kind=='agent_degradation':a['status']='degraded'
                elif kind=='connectivity_loss':a['link_disabled']=True
                elif kind=='resource_shortage':
                    resource=a['resources'].get('energy',a['resources'].get('stock',a['resources'].get('compute_budget')))
                    if resource is not None:
                        resource['value']=resource['minimum']
            for t in s['targets']:
                if t['id']==identifier:
                    if kind=='target_detected':s['discovered'].add(identifier)
                    if kind=='target_state_changed':t['status']='unconfirmed'
        if kind=='target_detected' and 'position' in p:
            identifier=e['id']+'_target'
            t={'id':identifier,'position':copy.deepcopy(p['position']),'priority':p.get('priority',1.),'status':'unconfirmed'}
            if s.get('layout')=='home' and 'appearance' in p:
                t['appearance']=copy.deepcopy(p['appearance'])
            s['targets'].append(t);s['discovered'].add(identifier)
            s['mission']['objectives'].append({'id':'rescue_'+identifier,'target_id':identifier,'type':'deliver','priority':t['priority'],'status':'pending'})
        if kind=='mission_priority_change':s['mission']['priorities']=list(reversed(s['mission']['priorities']))
        if kind=='operator_directive':
            if p.get('cancel_id'):
                s['mission']['directives']=[d for d in s['mission']['directives'] if d['id']!=p['cancel_id']]
            else:s['mission']['directives'].append({'id':e['id'],**p})
        if kind in ('hazard_appeared','restricted_zone_appeared','environment_change'):
            new_zone=zone(e['id'], 'hazard' if kind=='hazard_appeared' else 'restricted',p.get('min',[35,35,0]),p.get('max',[40,40,20]),.6)
            if s.get('layout')=='home' and 'appearance' in p:
                new_zone['appearance']=copy.deepcopy(p['appearance'])
            s['zones'].append(new_zone)
        if kind=='contradictory_information':s['observation_quality']['contradiction_count']+=1
        if kind=='stale_information':s['observation_quality']['stale_data_ratio']=.5


def metrics(s):
    weight=sum(t['priority'] for t in s['targets'])
    completion=sum(t['priority'] for t in s['targets'] if t['status']=='delivered')/weight
    s['metrics']={'mission_completion':completion,'step_count':s['step_count'],
                  'energy_used':round(s['energy_spent'],12),'messages_sent':s['message_count'],
                  'messages_dropped':s['drop_count'],'messages_delivered':len(s['delivered_messages'])}
    for o,t in zip(s['mission']['objectives'],s['targets']):o['status']='completed' if t['status']=='delivered' else 'pending'


def obstructed(state, start, end):
    return any(z['type'] in ('obstacle','restricted') and
               intersects_box(start, end, z['geometry']['min'], z['geometry']['max'])
               for z in state['zones'])


def resolve_home_motion(state, agents, destinations):
    """Advance to each first contact, then leave wrecks in the scene for the rest of the tick."""
    shapes = {a['id']: a['constraints'][0]['body'] for a in agents.values() if a['position'] is not None}
    positions = {identifier: agents[identifier]['position'] for identifier in shapes}
    moving = {identifier: end for identifier, (end, _) in destinations.items() if positions[identifier] != end}
    obstacles = [z for z in state['zones'] if z['type'] == 'obstacle']
    impacts = {}
    elapsed = 0.
    while moving:
        contacts = []
        for identifier, end in moving.items():
            for z in obstacles:
                g = z['geometry']
                fraction = contact_time(positions[identifier], end, *expanded_box(g['min'], g['max'], shapes[identifier]))
                if fraction is not None:
                    contacts.append((fraction, identifier, z['id'], False))
        for i, (a, pa) in enumerate(positions.items()):
            for b, pb in list(positions.items())[i+1:]:
                if a not in moving and b not in moving:
                    continue
                fraction = body_contact(pa, moving.get(a, pa), shapes[a], pb, moving.get(b, pb), shapes[b])
                if fraction is not None:
                    contacts.append((fraction, a, b, True))
        first = min((contact[0] for contact in contacts), default=1.)
        elapsed += (1.-elapsed)*first
        for identifier, end in moving.items():
            positions[identifier] = [a+first*(b-a) for a,b in zip(positions[identifier], end)]
        if not contacts:
            break
        stopped = set()
        for fraction, a, b, peer in sorted(contacts):
            if fraction > first+1e-10:
                break
            impacts.setdefault(a, (b, elapsed))
            stopped.add(a)
            if peer:
                impacts.setdefault(b, (a, elapsed))
                stopped.add(b)
        for identifier in stopped:
            moving.pop(identifier, None)
    for identifier, position in positions.items():
        agents[identifier]['position'] = [round(value,12) for value in position]
    return impacts


def advance(state, decision):
    s=copy.deepcopy(state);agents={a['id']:a for a in s['agents']};results=[];processed=set()
    home=s.get('layout')=='home'
    solid=bool(s.get('solid_contacts'))
    destinations={}
    if any(i not in agents for i in decision['role_assignments']):fail('Неизвестный агент в назначениях','INVALID_COMMAND')
    before={a['id']:copy.deepcopy(a['position']) for a in s['agents']}
    for a in s['agents']:
        a['role']=decision['role_assignments'].get(a['id']);a['scenario_ids']=list(decision['selected_configuration']['scenario_ids']) if a['role'] else []
    for c in decision['commands']:
        a=agents.get(c['agent_id']);action=c['action'];p=c['parameters']
        if a is None or a['id'] in processed:fail('Неизвестный агент или повтор команды','INVALID_COMMAND')
        processed.add(a['id'])
        if a['status'] not in ('active','degraded','safe_mode') or (a['status']=='safe_mode' and action!='charge') or action not in {d['action'] for d in a['available_actions']}:fail('Действие недоступно','INVALID_COMMAND')
        if not a['communication']['connected']:fail('Нет канала доставки команды','INVALID_COMMAND')
        if action not in ACTION_SCHEMAS:fail('Неизвестное действие','INVALID_COMMAND')
        try:check(p,ACTION_SCHEMAS[action])
        except ProtocolError as error:fail(error.message,'INVALID_COMMAND')
        cost=0.
        if action=='move':
            target=p['target'];start=a['position']
            limits=a['constraints'][0]
            allowed = all(lo<=v<=hi for lo,v,hi in zip(limits['min'],target,limits['max'])) if home else medium(a['kind'],target)
            if not allowed:fail('Недоступная среда перемещения')
            distance=math.dist(start,target);speed=limits['speed']*(.5 if a['status']=='degraded' else 1.)
            factor=min(1.,speed/distance) if distance else 0.
            end=[round(x+factor*(y-x),12) for x,y in zip(start,target)]
            multiplier=1.
            for z in s['zones']:
                low, high = z['geometry']['min'], z['geometry']['max']
                if (home or solid) and z['type']=='restricted':
                    low, high = expanded_box(low, high, limits['body'])
                if intersects_box(start,end,low,high):
                    if z['type']=='restricted' or (not home and not solid and z['type']=='obstacle'):
                        fail('Пересечение запрещённого объёма')
                    multiplier=max(multiplier,z['cost']['energy'])
            if home or solid:
                destinations[a['id']] = (end, multiplier)
            else:
                cost=math.dist(start,end)*PROFILES[a['kind']][1]*multiplier
                a['position']=end
        elif action in ('observe','deliver'):
            t=next((t for t in s['targets'] if t['id']==p['target_id'] and t['id'] in s['discovered']),None)
            if t is None or a['position'] is None or math.dist(a['position'],t['position'])>1.:fail('Цель недоступна','INVALID_COMMAND')
            if home and obstructed(s,a['position'],t['position']):fail('Цель за препятствием','INVALID_COMMAND')
            if action=='deliver':
                if t['status']!='confirmed' or a['resources']['supplies']['value']<.25:fail('Нет подтверждения или груза','INVALID_COMMAND')
                t['status']='delivered';a['resources']['supplies']['value']-=.25
            elif t['status']!='delivered':t['status']='confirmed'
            cost=.005
        elif action=='charge':
            station=next((n for n in s['infrastructure'] if n['id']==p['station_id'] and n['kind']=='charging_station' and n['status']=='active'),None)
            if station is None or a['position'] is None or math.dist(a['position'],station['position'])>a['constraints'][0]['charge_radius']:fail('Зарядная станция недоступна','INVALID_COMMAND')
            amount=min(.1,1.-a['resources']['energy']['value'],station['resources']['stock']['value'])
            station['resources']['stock']['value']=round(station['resources']['stock']['value']-amount,12)
            a['resources']['energy']['value']=round(a['resources']['energy']['value']+amount,12);a['status']='active'
        elif action=='send_message':
            path=route(s,a['id'],p['recipient_id'])
            if path is None:fail('Нет маршрута сообщения','INVALID_COMMAND')
            if len(s['pending_messages'])>=1000:fail('Очередь сообщений заполнена','RESOURCE_EXHAUSTED')
            identifier='message_'+str(s['message_count']);s['message_count']+=1
            s['pending_messages'].append({'id':identifier,'source':a['id'],'recipient':p['recipient_id'],
                                          'payload':copy.deepcopy(p['payload']),'path':path,'arrival':s['time']+max(1,sum(next(l['delay'] for l in s['network']['known_links'] if {l['source'],l['target']}=={u,v}) for u,v in zip(path,path[1:]))) })
            cost=.001
        elif action=='relay':
            cost=.001
            if a['kind']=='cosmic':s['cosmic_relay_steps']=s.get('cosmic_relay_steps',0)+1
        resource=a['resources']['energy']
        if resource['value']-cost<resource['minimum']-1e-12:fail('Нарушение резерва энергии','RESOURCE_EXHAUSTED')
        resource['value']=max(resource['minimum'],round(resource['value']-cost,12));s['energy_spent']+=cost
        results.append({'agent_id':a['id'],'action':action,'status':'applied'})
    if solid:
        from .physics import resolve
        contacts=resolve(s,agents,destinations)
        impacts={k:(v['with'],v['fraction']) for k,v in contacts.items()}
    else:
        contacts={}
        impacts = resolve_home_motion(s, agents, destinations) if home and destinations else {}
    if home or solid:
        for outcome in results:
            identifier = outcome['agent_id']
            if identifier in destinations:
                a = agents[identifier]
                resource = a['resources']['energy']
                travel = math.dist(before[identifier], a['position'])
                if solid and identifier in contacts:
                    at=contacts[identifier]['contact_position']
                    travel=math.dist(before[identifier],at)+math.dist(at,a['position'])
                cost = travel*PROFILES[a['kind']][1]*destinations[identifier][1]
                if resource['value']-cost<resource['minimum']-1e-12:
                    fail('Нарушение резерва энергии','RESOURCE_EXHAUSTED')
                resource['value'] = max(resource['minimum'], round(resource['value']-cost,12))
                s['energy_spent'] += cost
            if identifier in impacts:
                outcome.update(effect='collision', collision_with=impacts[identifier][0])
                if solid:
                    outcome.update(severity='severe' if contacts[identifier]['severe'] else 'light',
                                   normal_speed=round(contacts[identifier]['normal_speed'],6),
                                   retreated=contacts[identifier].get('retreated',False))
        failed = {identifier for identifier in impacts if agents[identifier]['status']!='failed' and (not solid or contacts[identifier]['severe'])}
        for identifier in failed:
            agents[identifier]['status'] = 'failed'
    else:
        spatial=[a for a in s['agents'] if a['position'] is not None]
        for i,a in enumerate(spatial):
            for b in spatial[i+1:]:
                if closest_distance(before[a['id']],a['position'],before[b['id']],b['position'])<.5:
                    fail('Коллизия траекторий')
    s['time']+=1.;s['step_count']+=1;s['request_id']=decision['request_id'];s['decision_ids'].add(decision['decision_id'])
    s['configuration']={'scenario_ids':list(decision['selected_configuration']['scenario_ids']),'role_assignments':copy.deepcopy(decision['role_assignments'])}
    s['parameters']=copy.deepcopy(decision['selected_configuration']['parameters'])
    for a in s['agents']:
        if a['status'] not in ('active','degraded'):continue
        r=a['resources']['energy'];cost=min(.001,max(0.,r['value']-r['minimum']))
        r['value']=round(r['value']-cost,12);s['energy_spent']+=cost
        if r['value']<=r['minimum']:a['status']='safe_mode'
    events(s)
    if home or solid:
        for identifier in sorted(impacts):
            if not solid and identifier not in failed:continue
            obstacle, fraction = impacts[identifier]
            s['events'].append({
                'id': f"impact_{s['step_count']}_{identifier}", 'type': 'agent_failure' if identifier in failed else 'environment_change',
                'time': s['time'], 'source': 'physics', 'targets': [identifier], 'confidence': 1., 'status': 'new',
                'parameters': {'collision_with': obstacle, 'position': agents[identifier]['position'],
                               'fraction': round(fraction,12), **({'severity':'severe' if contacts[identifier]['severe'] else 'light', 'normal_speed':round(contacts[identifier]['normal_speed'],6),'contact_position':contacts[identifier]['contact_position'],'retreated':contacts[identifier].get('retreated',False)} if solid else {})},
            })
    network(s)
    pending=[]
    for m in s['pending_messages']:
        if m['arrival']>s['time']:pending.append(m);continue
        sample=int(hashlib.sha256(f"{s['seed']}:{m['id']}".encode()).hexdigest()[:12],16)/16**12
        intact=all(v in s['graph'].get(u,[]) for u,v in zip(m['path'],m['path'][1:]))
        if not intact or sample<s['message_loss']:s['drop_count']+=1
        else:
            s['delivered_messages'].append(m)
            from .compute import process_message
            reply=process_message(s,m)
            if reply is not None:pending.append(reply)
    s['pending_messages']=pending;discover(s);metrics(s)
    if decision['operation']=='safe_stop':s['status'],s['mission']['status']='safe_stopped','safe_stopped'
    elif all(t['status']=='delivered' for t in s['targets']) and (
        not home or all(e['id'] in s['fired'] for e in s['schedule'])
    ):s['status'],s['mission']['status']='success','completed'
    elif s['step_count']>=s['max_steps']:s['status'],s['mission']['status']='time_limit','failed'
    return s,results
