"""Два контрольных алгоритма без метасценарного планировщика."""
import copy
import math
from .controller import Controller
from .public_model import guard, move_towards
from .simulation import medium


class FixedController(Controller):
    mode='fixed'
    mission_parameters={'profile':'rescue_v2','max_steps':60}

    def health(self):
        result=super().health()
        result.update(controller_id="ariadna_"+self.mode,profile="rescue_v2",supported_operations=["select","keep","safe_stop"])
        return result

    def decide(self, observation, previous=None, parameters=None):
        result=super().decide(observation,previous,parameters)
        roles={a['id']:'worker' for a in observation['agents']}
        result.update(operation='keep' if previous else 'select',role_assignments=roles,commands=[],candidate_evaluations=[])
        result['selected_configuration']={'scenario_ids':[self.mode+'_control'],'parameters':{},'synthesized_scenario':None}
        result['explanation'].update(reason_codes=[self.mode+'_baseline'],expected_effects=['search_confirm_deliver'])
        stop = next((d for d in observation['mission']['directives']
                     if d.get('type',d.get('action')) in ('stop','safe_stop')), None)
        if stop:
            previous = previous or {'scenario_ids':[], 'role_assignments':{}}
            result.update(operation='safe_stop',role_assignments=previous['role_assignments'])
            result['selected_configuration'].update(scenario_ids=previous['scenario_ids'],parameters=parameters or {})
            if 'id' in stop:
                result['explanation']['observation_refs'].append(stop['id'])
            result['explanation'].update(reason_codes=['mandatory_operator_stop'],expected_effects=['safe_stop'])
            return result
        waypoints={'ground':[18.,8.,0.],'surface_water':[65.,9.,0.],
                   'underwater':[65.,8.,-5.],'underground':[15.,9.,-5.],'aerial':[25.,8.,10.]}
        deliveries=set()
        for a in observation['agents']:
            if a['status'] not in ('active','degraded') or not a['communication']['connected'] or a['kind'] not in waypoints:continue
            choices=[t for t in observation['targets'] if t['status']!='delivered' and medium(a['kind'],t['position'])]
            if self.mode=='reactive':choices.sort(key=lambda t:(-t['priority'],math.dist(a['position'],t['position']),tuple(t['position'])))
            else:choices.sort(key=lambda t:tuple(t['position']))
            if choices:
                t=choices[0];distance=math.dist(a['position'],t['position'])
                action='move' if distance>1 else ('deliver' if t['status']=='confirmed' else 'observe')
                p={'target':t['position']} if action=='move' else {'target_id':t['id']}
            else:
                action='move';p={'target':waypoints[a['kind']]}
                if math.dist(a['position'],p['target'])<=1:continue
            if self.mode=='reactive' and a['resources']['energy']['value']<.25:
                stations=[n for n in observation['infrastructure'] if n['kind']=='charging_station' and n['status']=='active' and medium(a['kind'],n['position'])]
                if not stations:continue
                station=min(stations,key=lambda n:math.dist(a['position'],n['position']))
                action='charge' if math.dist(a['position'],station['position'])<=3 else 'move'
                p={'station_id':station['id']} if action=='charge' else {'target':station['position']}
            if action=='move':
                command=move_towards(a,p['target'],observation)
                if command:
                    result['commands'].append(command)
                continue
            if action=='deliver':
                if p['target_id'] in deliveries:
                    continue
                if a['resources']['supplies']['value'] < .25:
                    continue
                deliveries.add(p['target_id'])
            result['commands'].append({'agent_id':a['id'],'action':action,'parameters':copy.deepcopy(p)})
        result['commands'],checks=guard(observation,result['commands'],priority=True,preserve_connectivity=False)
        result['constraint_checks'].extend(checks)
        return result


class ReactiveController(FixedController):
    mode='reactive'
