"""Normalize documented wire semantics and derive a bounded base-profile plan."""
import copy
import hashlib
from .contracts import ProtocolError, canonical, check, validate

KNOWN_ACTIONS={'move','observe','deliver','charge','relay','send_message'}
MOTION_FIELDS=('speed','energy_per_metre','idle_energy','action_energy','interaction_radius',
               'charge_radius','charging_rate','delivery_supplies','sensor_radius','degraded_speed_factor')
MEDIUM = {'ground': 'land', 'aerial': 'air', 'underground': 'underground',
          'surface_water': 'water', 'underwater': 'water', 'cosmic': 'space'}


def base_profile_limits(agent, zones):
    """Use the published operating volume; surface agents keep their elevation."""
    position = agent['position']
    if position is None:
        return None
    boxes = [z['geometry'] for z in zones if z['type'] == MEDIUM.get(agent['kind'])
             and z['geometry'].get('type') == 'axis_aligned_box']
    containing = [b for b in boxes if all(lo <= p <= hi for lo, p, hi in zip(b['min'], position, b['max']))]
    if not containing:
        return None
    box = min(containing, key=lambda b: (b['min'], b['max']))
    lower, upper = list(box['min']), list(box['max'])
    if agent['kind'] in ('ground', 'surface_water'):
        lower[2] = upper[2] = position[2]
    # These are planning allowances, not estimates of the peer's physical constants.
    # An atomic environment still decides whether a command is executable.
    return {'id': 'ariadna.motion.v1', 'min': lower,
            'max': upper, 'speed': 2., 'energy_per_metre': .01,
            'idle_energy': .005, 'interaction_radius': .75, 'charge_radius': .75,
            'delivery_supplies': .25, 'sensor_radius': 4.,
            'search_axes': [i for i in range(3) if lower[i] < upper[i]]}


def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


class PublicAdapter:
    def __init__(self,capabilities=None):
        self.capabilities=copy.deepcopy(capabilities or {'protocol_version':'1.0'})
        if self.capabilities.get('protocol_version')!='1.0':
            raise ProtocolError('UNSUPPORTED_PROTOCOL_VERSION','Адаптер поддерживает протокол 1.0')
        for key in ('profiles','reset_parameters'):
            if key in self.capabilities:check(self.capabilities[key],{'type':'array','items':{'type':'string'}})
        for key in ('units','limits','execution_semantics'):
            if key in self.capabilities:check(self.capabilities[key],{'type':'object'})
        self.dt=self.capabilities.get('dt_seconds',1.)
        check(self.dt,{'type':'number','minimum':.000001,'maximum':60.})
        self.profile=self.capabilities.get('semantic_profile','native_public')
        self.mapping={};self.diagnostics=[];self.base_profile=False

    def normalize(self,raw):
        validate('observation',raw)
        result=copy.deepcopy(raw);self.mapping={};self.diagnostics=[];self.base_profile=False
        units=self.capabilities.get('units',{})
        if units.get('position','metre')!='metre' or units.get('time','second')!='second':
            result['constraints'].append({'id':'unsupported_adapter_units','mandatory':True})
            self.diagnostics.append('unsupported_units_no_implicit_conversion')
        for target in result['targets']:
            check(target,{'type':'object','required':['id','position','status'],'properties':{
                'id':{'type':'string','minLength':1},'position':{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}},
                'status':{'enum':['unconfirmed','confirmed','delivered']},'priority':{'type':'number','minimum':0}}})
        for entity in result['agents']+result['infrastructure']:
            entity['kind']=entity.get('semantic_kind',entity['kind'])
            resources={}
            for key,value in entity['resources'].items():
                if not isinstance(value,dict):raise ProtocolError('INVALID_REQUEST','Требуется объект публичного ресурса')
                semantic=value.get('semantic',key) if isinstance(value,dict) else key
                if semantic in resources:
                    raise ProtocolError('INVALID_REQUEST','Неоднозначная семантика ресурса')
                resources[semantic]=value
            entity['resources']=resources
            constraints=[]
            for c in entity['constraints']:
                if c.get('type')=='motion_limits':
                    bounds=c.get('bounds',{})
                    m={'id':'ariadna.motion.v1','min':bounds.get('lower'),'max':bounds.get('upper')}
                    m.update({k:c[k] for k in MOTION_FIELDS if k in c})
                    position={'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}}
                    check(m,{'type':'object','required':['min','max','speed','energy_per_metre','idle_energy','interaction_radius','charge_radius','delivery_supplies','sensor_radius'],
                             'properties':{'min':position,'max':position,**{k:{'type':'number','minimum':0} for k in MOTION_FIELDS}}})
                    if m['speed']<=0 or any(a>b for a,b in zip(m['min'],m['max'])):
                        raise ProtocolError('INVALID_REQUEST','Неверные публичные пределы движения')
                    constraints.append(m)
                elif c.get('type')=='energy_limits':
                    check(c.get('idle_energy'),{'type':'number','minimum':0,'maximum':1})
                    constraints.append({'id':'ariadna.energy.v1','idle_energy':c['idle_energy']})
                else:constraints.append(c)
            entity['constraints']=constraints
            if 'available_actions' not in entity:continue
            mapping={};descriptors=[]
            for descriptor in entity['available_actions']:
                wire=descriptor.get('action',descriptor.get('name'))
                semantic=descriptor.get('semantic',wire)
                if semantic not in KNOWN_ACTIONS:
                    continue
                if semantic in mapping:raise ProtocolError('INVALID_REQUEST','Неоднозначная семантика действия')
                parameters=descriptor.get('parameter_mapping',{})
                if not isinstance(parameters,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in parameters.items()) or len(set(parameters.values()))!=len(parameters):
                    raise ProtocolError('INVALID_REQUEST','Неверное сопоставление параметров')
                inverse={v:k for k,v in parameters.items()}
                normalized=copy.deepcopy(descriptor);normalized['action']=semantic
                schema=normalized.get('parameters_schema',{})
                if 'properties' in schema:check(schema['properties'],{'type':'object'})
                if 'required' in schema:check(schema['required'],{'type':'array','items':{'type':'string'}})
                if 'properties' in schema:schema['properties']={inverse.get(k,k):v for k,v in schema['properties'].items()}
                if 'required' in schema:schema['required']=[inverse.get(k,k) for k in schema['required']]
                descriptors.append(normalized);mapping[semantic]={'action':wire,'parameters':parameters}
            entity['available_actions']=descriptors
            entity['capabilities']=[next((k for k,v in mapping.items() if v['action']==c),c) for c in entity['capabilities']]
            self.mapping[entity['id']]=mapping
        for z in result['zones']:
            z['type']=z.get('semantic_type',z['type'])
            g=z['geometry']
            if g.get('type')=='box':
                z['geometry']={'type':'axis_aligned_box','min':g.get('lower'),'max':g.get('upper')}
                check(z['geometry']['min'],{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}})
                check(z['geometry']['max'],{'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}})
                if any(a>b for a,b in zip(z['geometry']['min'],z['geometry']['max'])):raise ProtocolError('INVALID_REQUEST','Перевёрнутые границы зоны')
        if self.dt!=1.:
            result['time']=round(raw['time']/self.dt,9)
            result['observation_quality']['maximum_delay']/=self.dt
            for event in result['events']:event['time']/=self.dt
            for link in result['network']['known_links']:
                if isinstance(link.get('delay'),(int,float)):link['delay']/=self.dt
            for message in result['network'].get('messages',[]):
                if isinstance(message.get('arrival'),(int,float)):message['arrival']/=self.dt
            termination=result['mission']['termination']
            if isinstance(termination.get('time_limit'),(int,float)):termination['time_limit']/=self.dt
            for agent in result['agents']:
                for c in agent['constraints']:
                    if c.get('id')=='ariadna.motion.v1':c['speed']*=self.dt
        for agent in result['agents']:
            descriptors = agent['available_actions']
            spatial = any(a['action'] in ('move', 'observe', 'deliver', 'charge') for a in descriptors)
            if spatial and not any(c.get('id') == 'ariadna.motion.v1' for c in agent['constraints']):
                self.base_profile = True
                limits = base_profile_limits(agent, result['zones'])
                if limits:
                    agent['constraints'].append(limits)
            if 'energy' in agent['resources']:
                for action in descriptors:
                    if 'energy_cost' not in action:
                        self.base_profile = True
                        action['energy_cost'] = .025
        if self.base_profile:
            self.diagnostics.append('base_profile_planning_allowances')
        validate('observation',result)
        return result

    def encode_commands(self,commands):
        output=[]
        for command in commands:
            descriptor=self.mapping[command['agent_id']][command['action']]
            mapping=descriptor['parameters']
            output.append({'agent_id':command['agent_id'],'action':descriptor['action'],
                           'parameters':{mapping.get(k,k):copy.deepcopy(v) for k,v in command['parameters'].items()}})
        return output
