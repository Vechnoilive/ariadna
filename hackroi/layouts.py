"""Seeded floodplain family, opt-in only; historical rescue_v2 remains unchanged."""
import copy
import random
from .contracts import ProtocolError


def configure(state,parameters):
    if parameters.get('layout') == 'custom':
        from .home import FORMAT as HOME_FORMAT, configure as home_configure
        from .custom_maps import configure as custom_configure
        definition = parameters.get('custom_map')
        if not isinstance(definition, dict):
            raise ProtocolError('INVALID_REQUEST','Для custom нужна карта')
        configure_map = home_configure if definition.get('format') == HOME_FORMAT else custom_configure
        configure_map(state, parameters)
        return
    if parameters.get('layout','standard')=='standard':
        if parameters.get('cohorts',1)!=1 or parameters.get('targets_per_kind',1)!=1:
            raise ProtocolError('INVALID_REQUEST','Масштаб задаётся только для floodplain')
        return
    if parameters.get('layout')!='floodplain':raise ProtocolError('INVALID_REQUEST','Неизвестная карта')
    cohorts=parameters.get('cohorts',1);count=parameters.get('targets_per_kind',1)
    if type(cohorts) is not int or not 1<=cohorts<=8 or type(count) is not int or not 1<=count<=4:
        raise ProtocolError('INVALID_REQUEST','cohorts: 1..8; targets_per_kind: 1..4')
    rng=random.Random(state['seed'] ^ 0xA205)
    y=float(rng.randint(5,10))
    for a in state['agents']:
        if a['position'] is not None and a['kind']!='cosmic':a['position'][1]=y
    initial=list(state['agents'])
    for k in range(1,cohorts):
        for a in initial:
            if a['kind'] not in ('ground','aerial','underground','surface_water','underwater'):continue
            replica=copy.deepcopy(a);replica['id']=a['id']+'_'+str(k);replica['position'][1]+=2.*k
            state['agents'].append(replica)
    # Keep the original domains but provide mesh coverage across the tested region.
    bridge=next(n for n in state['infrastructure'] if n['kind']=='relay')
    for i,position in enumerate(([25.,26.,8.],[50.,26.,8.],[75.,26.,8.])):
        n=copy.deepcopy(bridge);n.update(id='flood_relay_'+str(i),position=position);state['infrastructure'].append(n)
    for station in state['infrastructure']:
        if station['kind']=='charging_station':
            reference=next((a for a in initial if a['kind']==station['id'].removeprefix('station_')),None)
            if station['id']=='infra_1':reference=next(a for a in initial if a['kind']=='ground')
            if reference:station['position']=copy.deepcopy(reference['position'])
            station['resources']['stock']['value']=1.
    # Additional stations provide finite shared resources for replicated agents.
    for a in state['agents']:
        if '_' not in a['id'] or a['kind'] not in ('ground','underground','surface_water','underwater'):continue
        station=copy.deepcopy(next(n for n in state['infrastructure'] if n['kind']=='charging_station'))
        station.update(id='dock_'+a['id'],position=copy.deepcopy(a['position']));state['infrastructure'].append(station)
    prototype=state['zones'][0]
    def volume(identifier,low,high):
        z=copy.deepcopy(prototype);z.update(id=identifier,type='obstacle');z['geometry']={'type':'axis_aligned_box','min':low,'max':high};return z
    state['zones']=[z for z in state['zones'] if z['type'] not in ('obstacle','restricted','hazard','limited_access','low_connectivity')]
    height=float(rng.randint(14,18))
    state['zones'] += [volume('flood_ground_wall',[15.,0.,0.],[18.,height,1.]),
                       volume('flood_tunnel_wall',[16.,0.,-12.],[19.,height,-1.]),
                       volume('flood_water_wall',[64.,0.,-15.],[66.,height,0.])]
    targets=[]
    for k in range(count):
        # Rejection sampling enforces physically distinct objects and free volumes.
        for kind in ('ground','surface_water','underground','underwater'):
            for _ in range(100):
                x=rng.uniform(23.,34.) if kind in ('ground','underground') else rng.uniform(73.,85.)
                yy=rng.uniform(height+3.,29. if kind=='underground' else 32.)
                z=0. if kind in ('ground','surface_water') else -5.
                p=[round(x,3),round(yy,3),z]
                if all(sum((a-b)**2 for a,b in zip(p,t['position']))>=4. for t in targets):break
            else:raise ProtocolError('INVALID_REQUEST','Не удалось разместить цели')
            targets.append({'id':f'flood_{kind}_{k}','position':p,'status':'unconfirmed','priority':float(rng.randint(1,5))})
    state['targets']=targets
    state['mission']['objectives']=[{'id':'rescue_'+t['id'],'target_id':t['id'],'type':'deliver','priority':t['priority'],'status':'pending'} for t in targets]
    state['layout']='floodplain'
