"""Wire adapter and bounded production controller, driven only by public declarations."""
import copy
import hashlib
import math
from .adapters import PublicAdapter, sha
from .contracts import ProtocolError, canonical, validate
from .controller import Controller
from .counterfactual import CounterfactualController
from .forecast import PublicForecaster
from .forecast_policy import add_footprints, ForecastPlanner, PolicyController, STATE_FIELDS, available, information_gain, plan
from .metacontroller import MetaController
from .public_model import guard, actions, blocked, motion, routed_move

FORECAST_AGENT_LIMIT=24
FORECAST_TARGET_LIMIT=48


class PortablePlanner(ForecastPlanner):
    def move(self,agent,destination):
        return routed_move(agent,destination,self.o,self.scale)

    def search(self,context):
        if self.variant=='meta':return super().search(context)
        output=plan();occupied=set()
        for a in self.agents:
            limits=motion(a)
            if not available(a) or not limits or not {'move','observe'}<=actions(a).keys():continue
            radius=limits.get('sensor_radius',12.)
            candidates=[];pending=self.pending_cells.get(a['id'])
            if pending and math.dist(a['position'],pending[1])>1. and not blocked(pending[1],pending[1],self.o):
                candidates=[list(pending[1])]
            else:
                grid=[]
                for ix in range(1,21):
                    x=limits['min'][0]+ix*radius
                    if x>limits['max'][0]:break
                    for iy in range(1,21):
                        y=limits['min'][1]+iy*radius
                        if y>limits['max'][1]:break
                        p=[x,y,a['position'][2]]
                        if (a['kind'],tuple(p)) not in self.visited and not blocked(p,p,self.o):grid.append(p)
                candidates=sorted(grid,key=lambda p:(math.dist(a['position'],p),p[1],p[0]))[:8]
                for axis in limits.get('search_axes',(0,1)):
                    for sign in (1.,-1.):
                        p=list(a['position']);p[axis]=max(limits['min'][axis],min(limits['max'][axis],p[axis]+sign*radius))
                        candidates.append(p)
            ranked=[]
            for destination in candidates:
                if math.dist(a['position'],destination)<=1. or (a['kind'],tuple(destination)) in occupied:continue
                gain=information_gain(a,destination,self.footprints)
                distance=math.dist(a['position'],destination)
                score=10.*gain*self.belief['confidence']/(1.+distance/max(1.,limits['speed'])*.1)
                ranked.append((score,destination))
            for score,destination in sorted(ranked,key=lambda x:(-x[0],x[1][1],x[1][0])):
                if score<=0:break
                command=self.move(a,destination)
                if command:
                    occupied.add((a['kind'],tuple(destination)))
                    output['commands'].append(command);output['roles'][a['id']]='scout';output['utility']+=score
                    output['bids'].append({'agent_id':a['id'],'task_id':'coverage:'+canonical(destination),
                                          'destination':destination,'utility':round(score,6),'selected':True})
                    break
        return self.remember(output,'search')


class PortablePolicy(PolicyController):
    def check_commands(self,observation,commands):return guard(observation,commands,priority=True)

    def make_planner(self,observation,belief,visited,scale):
        self.forecast_planner=PortablePlanner(observation,belief,visited,scale,self.variant,self.footprints,self.pending_cells)
        return self.forecast_planner


class BudgetController(MetaController):
    def __init__(self,footprints):
        super().__init__()
        self.footprints=tuple(footprints)

    def make_planner(self,observation,belief,visited,scale):
        return PortablePlanner(observation,belief,visited,scale,'frontier',self.footprints,self.pending_cells)

    def check_commands(self,observation,commands):return guard(observation,commands,priority=True)


class RoutedForecaster(PublicForecaster):
    def rollout(self,*args,**kwargs):
        return super().rollout(*args,**kwargs,routed=True)


class Headquarters(CounterfactualController):
    def make_forecaster(self):return RoutedForecaster()

    def make_policy(self,source,variant,footprints):
        result=PortablePolicy(variant,footprints)
        if source:
            for key in STATE_FIELDS:setattr(result,key,copy.deepcopy(getattr(source,key)))
        return result


def compact(decision,limit):
    """Only optional witnesses are compacted; commands and normative fields remain intact."""
    result=copy.deepcopy(decision)
    if len(canonical(result).encode())<=limit:return result
    proof=result.get('ariadna_counterfactual',{})
    for candidate in proof.get('candidates',[]):
        for key in ('commands','intents'):
            if key in candidate:
                value=candidate.pop(key);candidate[key+'_sha256']=sha(value)
        for key in ('nominal','stressed'):
            value=candidate.get(key,{})
            if len(value.get('curve',[]))>1:
                curve=value['curve'];value['curve_sha256']=sha(curve);value['curve']=[curve[-1]]
    for candidate in result['candidate_evaluations']:
        evaluation=candidate.get('game_evaluation',{});bids=evaluation.get('bids',[])
        if len(bids)>16:
            evaluation['full_bids_sha256']=sha(bids);evaluation['full_bids_count']=len(bids)
            evaluation['bids']=sorted(bids,key=lambda b:(not b.get('selected',False),-b.get('utility',0.)))[:16]
    if 'semantic_mapping' in result.get('ariadna_portable',{}):
        value=result['ariadna_portable'].pop('semantic_mapping')
        result['ariadna_portable']['semantic_mapping_sha256']=sha(value)
    if len(canonical(result).encode())>limit:
        raise ProtocolError('RESOURCE_EXHAUSTED','Обязательное решение не помещается в объявленный размер запроса',413)
    result['explanation']['reason_codes'].append('optional_evidence_compacted')
    if len(canonical(result).encode())>limit:raise ProtocolError('RESOURCE_EXHAUSTED','Превышен размер решения',413)
    return result


class PortableController(Controller):
    audit_profile='ariadna.portable.v5'
    mission_parameters={'profile':'rescue_v2','max_steps':150}

    def __init__(self,log_path=None):
        super().__init__(log_path)
        self.configure_capabilities({'protocol_version':'1.0'})
        self.headquarters=Headquarters();self.current_mode=None
        self.cached_key=None;self.cached_decision=None;self.episode=None;self.last_time=-1.

    def configure_capabilities(self,capabilities):
        self.capabilities=copy.deepcopy(capabilities);self.adapter=PublicAdapter(capabilities)
        declared=capabilities.get('limits',{}).get('max_body_bytes',65536)
        if type(declared) is not int or declared<1024:raise ProtocolError('INVALID_REQUEST','Недопустимый предел тела запроса')
        self.body_limit=min(65536,declared)

    def reset_parameters(self,capabilities):
        proposed=copy.deepcopy(self.mission_parameters)
        if 'rescue_v2' in capabilities.get('profiles',[]):return proposed
        allowed=capabilities.get('reset_parameters',[])
        return {k:v for k,v in proposed.items() if k in allowed}

    def reset_evidence(self):return {'capabilities':copy.deepcopy(self.capabilities)}

    def validate_reply(self,response,request):
        o=response['observation']
        valid=(response['request_id']==request['request_id'] and o['request_id']==response['request_id'] and
               o['episode_id']==response['episode_id'] and o['time']==response['time'])
        if 'decision_id' in request:
            valid=valid and response['episode_id']==request['episode_id'] and response['time']>request['time']
            outcomes=response['command_results'];commands=request['commands']
            partial=self.capabilities.get('execution_semantics',{}).get('batch')=='partial' and self.capabilities.get('execution_semantics',{}).get('configuration')=='atomic'
            allowed={'applied','rejected'} if partial else {'applied'}
            valid=valid and len(outcomes)==len(commands) and all(
                r.get('agent_id')==c['agent_id'] and r.get('action')==c['action'] and r.get('status') in allowed for c,r in zip(commands,outcomes))
        if not valid:
            self.journal.append({'kind':'invalid_response','protocol_version':'1.0','component':'controller',
                                 'expected_request_id':request['request_id'],'output':response})
            raise ProtocolError('INVALID_REQUEST','Ответ среды не соответствует запросу или объявленной семантике исполнения',502)

    def health(self):
        result=super().health();result.update(controller_id='ariadna_portable',profile=self.audit_profile,
            semantic_profiles=['native_public','a2x.public-model.v1'],forecast_agent_limit=FORECAST_AGENT_LIMIT,
            external_access='public_HTTP_only')
        return result

    def decide(self,observation,previous=None,parameters=None):
        previous=copy.deepcopy(previous or {'scenario_ids':[],'role_assignments':{}});parameters=copy.deepcopy(parameters or {})
        key=canonical([observation,previous,parameters,self.capabilities])
        if key==self.cached_key:return copy.deepcopy(self.cached_decision)
        if self.episode!=observation['episode_id'] or observation['time']<self.last_time:
            self.headquarters=Headquarters()
        self.episode,self.last_time=observation['episode_id'],observation['time']
        normalized=self.adapter.normalize(observation)
        if self.headquarters.pending:self.headquarters.observe_result({'observation':normalized})
        core_parameters={k:v for k,v in parameters.items() if k!='ariadna_portable'}
        large=len(normalized['agents'])>FORECAST_AGENT_LIMIT or len(normalized['targets'])>FORECAST_TARGET_LIMIT
        if large or self.adapter.base_profile:
            add_footprints(self.headquarters.footprints,normalized)
            source=self.headquarters.policy
            core=BudgetController(self.headquarters.footprints)
            if source:
                for k in STATE_FIELDS:setattr(core,k,copy.deepcopy(getattr(source,k)))
            decision=core.decide(normalized,previous,core_parameters)
            self.headquarters.policy=core
            self.headquarters.episode=normalized['episode_id'];self.headquarters.last_time=normalized['time']
            if self.adapter.base_profile:
                self.current_mode='base_profile'
                decision['explanation']['reason_codes'].append('forecast_undeclared_dynamics')
            else:
                self.current_mode='meta_budget'
                decision['explanation']['reason_codes'].append('forecast_budget_abstention')
        else:
            decision=self.headquarters.decide(normalized,previous,core_parameters);self.current_mode='counterfactual'
        result=copy.deepcopy(decision)
        result['time']=observation['time']
        result['commands']=self.adapter.encode_commands(decision['commands'])
        digest=sha(observation);result['request_id']='step_'+digest[:24];result['decision_id']='decision_'+digest[:24]
        marker={'profile':self.adapter.profile,'capabilities_sha256':sha(self.capabilities)}
        if result['operation']!='safe_stop':
            result['selected_configuration']['parameters']['ariadna_portable']=marker
            if result['selected_configuration']['scenario_ids']==previous['scenario_ids']:
                result['operation']='keep' if result['selected_configuration']['parameters']==parameters and result['role_assignments']==previous['role_assignments'] else 'modify'
        else:result['selected_configuration']['parameters']=parameters
        result['explanation']['observation_refs']=list(dict.fromkeys(['sha256:'+digest]+result['explanation']['observation_refs']))
        result['explanation']['reason_codes'].append('public_semantic_adapter')
        result['ariadna_portable']={'version':'0.5','mode':self.current_mode,**marker,'raw_observation_sha256':digest,
            'normalized_observation_sha256':sha(normalized),'semantic_mapping':copy.deepcopy(self.adapter.mapping),
            'diagnostics':copy.deepcopy(self.adapter.diagnostics)}
        if self.adapter.dt!=1.:result['ariadna_portable']['time_normalization']={'dt_seconds':self.adapter.dt,'wire_time':observation['time'],'model_tick':normalized['time']}
        result=compact(result,self.body_limit)
        validate('decision',result)
        if self.headquarters.pending:self.headquarters.pending['decision_id']=result['decision_id']
        self.cached_key,self.cached_decision=key,copy.deepcopy(result)
        return result

    @property
    def last_candidates(self):return self.headquarters.last_candidates

    def observe_result(self,response):
        if self.current_mode=='meta_budget':return {'status':'not_predicted','reason':'forecast_budget'}
        if self.current_mode=='base_profile':return {'status':'not_predicted','reason':'undeclared_dynamics'}
        adapted=copy.deepcopy(response);adapted['observation']=self.adapter.normalize(response['observation'])
        return self.headquarters.observe_result(adapted)
