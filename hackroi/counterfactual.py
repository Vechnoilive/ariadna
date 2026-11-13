"""Counterfactual headquarters: public alternatives, robust forecasts and outcome audit."""
import copy
import hashlib

from .contracts import canonical, validate
from .controller import Controller
from .forecast import Calibration, HORIZON, MODEL_VERSION, PublicForecaster
from .forecast_policy import POLICIES, add_footprints, clone_policy


class CounterfactualController(Controller):
    audit_profile = 'ariadna.counterfactual.v4'
    mission_parameters = {'profile': 'rescue_v2', 'max_steps': 100}

    def __init__(self, log_path=None):
        super().__init__(log_path)
        self.reset_planning()

    def reset_planning(self):
        self.policy = None
        self.calibration = Calibration()
        self.footprints = []
        self.pending = None
        self.last_feedback = None
        self.episode, self.last_time = None, -1.
        self.cached_key, self.cached_decision = None, None
        self.last_candidates = {}

    def health(self):
        result = super().health()
        result.update(controller_id='ariadna_counterfactual', profile=self.audit_profile,
                      forecast_model=MODEL_VERSION, forecast_horizon=HORIZON, alternative_policies=list(POLICIES),
                      privileged_environment_access=False)
        return result

    def observe_result(self, response):
        observation = response['observation']
        if self.pending is None:
            return None
        feedback = self.calibration.settle(self.pending, observation)
        self.pending = None
        self.last_feedback = feedback
        return copy.deepcopy(feedback)

    def make_forecaster(self):
        return PublicForecaster()

    def make_policy(self, source, variant, footprints):
        return clone_policy(source, variant, footprints)

    def decide(self, observation, previous=None, parameters=None):
        validate('observation', observation)
        previous = copy.deepcopy(previous or {'scenario_ids': [], 'role_assignments': {}})
        parameters = copy.deepcopy(parameters or {})
        key = canonical([observation, previous, parameters])
        if key == self.cached_key:
            return copy.deepcopy(self.cached_decision)
        if self.episode != observation['episode_id'] or observation['time'] < self.last_time:
            self.reset_planning()
        self.episode, self.last_time = observation['episode_id'], observation['time']
        if self.pending:
            self.observe_result({'observation': observation})
        add_footprints(self.footprints, observation)
        calibration = self.calibration.summary()
        core_parameters = {k:v for k,v in parameters.items() if k != 'ariadna_counterfactual'}
        incumbent = parameters.get('ariadna_counterfactual', {}).get('policy', 'meta')
        alternatives, forecast_cache = {}, {}
        confidence = 1.
        for variant in POLICIES:
            controller = self.make_policy(self.policy, variant, self.footprints)
            decision = controller.decide(observation, previous, core_parameters)
            intents = controller.intents_for(decision)
            confidence = decision['explanation']['confidence']
            uncertainty = max(.05, 1.-confidence, min(.8, 2.*(1.-calibration['trust'])))
            signature = canonical([decision['commands'], decision['selected_configuration'], intents])
            if signature in forecast_cache:
                nominal, stressed, equivalent = forecast_cache[signature]
            else:
                model = self.make_forecaster()
                nominal = model.rollout(observation, decision, intents, self.footprints)
                stressed = model.rollout(observation, decision, intents, self.footprints, stress=uncertainty)
                equivalent = None
                forecast_cache[signature] = (nominal, stressed, variant)
            score = (1.-uncertainty)*nominal['score'] + uncertainty*stressed['score']
            alternatives[variant] = {'controller': controller, 'decision': decision, 'intents': intents,
                                     'nominal': nominal, 'stressed': stressed, 'score': round(score, 9),
                                     'equivalent_to': equivalent, 'uncertainty': uncertainty}
        base = alternatives['meta']['decision']
        protected = base['ariadna_meta']['features']['hard_stop'] or 'operator_directive_conflict' in base['explanation']['reason_codes']
        if protected:
            selected, reason = 'meta', 'mandatory_safe_response'
        elif calibration['trust'] < .35:
            selected, reason = 'meta', 'forecast_abstention_model_error'
        else:
            # A stop cannot beat available safe work merely by consuming less energy.
            feasible = [v for v in POLICIES if alternatives[v]['decision']['commands']]
            if not feasible:
                selected, reason = 'meta', 'no_safe_alternative'
            else:
                selected = min(feasible, key=lambda v: (-alternatives[v]['score'], POLICIES.index(v)))
                if incumbent in feasible and alternatives[incumbent]['score'] >= alternatives[selected]['score']-.05:
                    selected = incumbent
                reason = 'robust_public_forecast'
        chosen = alternatives[selected]
        result = copy.deepcopy(chosen['decision'])
        selected_parameters = result['selected_configuration']['parameters']
        if result['operation'] != 'safe_stop':
            selected_parameters['ariadna_counterfactual'] = {'policy': selected, 'model': MODEL_VERSION, 'horizon': HORIZON}
            if result['selected_configuration']['scenario_ids'] == previous['scenario_ids']:
                result['operation'] = 'keep' if selected_parameters == parameters and result['role_assignments'] == previous['role_assignments'] else 'modify'
        else:
            result['selected_configuration']['parameters'] = copy.deepcopy(parameters)
        evidence = []
        for variant, entry in alternatives.items():
            evidence.append({'candidate_id': variant, 'selected': variant == selected, 'score': entry['score'],
                             'scenario_ids': entry['decision']['selected_configuration']['scenario_ids'],
                             'commands': entry['decision']['commands'], 'intents': entry['intents'],
                             'nominal': {k:v for k,v in entry['nominal'].items() if k != 'one_step'},
                             'stressed': {k:v for k,v in entry['stressed'].items() if k != 'one_step'},
                             'equivalent_to': entry['equivalent_to'],
                             'reason_codes': [reason] if variant == selected else ['lower_robust_score_or_inertia']})
        one_step = chosen['nominal']['one_step']
        radius = calibration['energy_error_radius']
        interval = [round(max(0., one_step['energy_delta']-radius), 12), round(one_step['energy_delta']+radius, 12)]
        result['ariadna_counterfactual'] = {
            'version': '0.4', 'model': MODEL_VERSION, 'horizon': HORIZON, 'selected_candidate': selected,
            'selection_reason': reason, 'calibration_before_selection': calibration,
            'uncertainty': round(chosen['uncertainty'], 9), 'candidates': evidence,
            'selected_one_step_prediction': one_step, 'selected_energy_interval': interval,
            'previous_forecast_feedback': copy.deepcopy(self.last_feedback),
            'public_observation_ref': 'sha256:'+hashlib.sha256(canonical(observation).encode()).hexdigest(),
            'model_step_budget': len(forecast_cache)*2*HORIZON,
            'assumptions': ['known_entities_only', 'frozen_intent_continuation', 'no_unannounced_events',
                            'horizontal_information_proxy_not_hidden_target_prediction', 'stress_envelope_not_confidence_interval']}
        result['explanation']['reason_codes'] += ['counterfactual_headquarters', reason]
        result['explanation']['expected_effects'] = ['execute_forecast_selected_safe_plan'] if result['commands'] else ['safe_stop']
        validate('decision', result)
        self.policy = chosen['controller']
        self.policy.beliefs.issued(result['commands'])
        self.pending = {'episode_id': observation['episode_id'], 'decision_id': result['decision_id'],
                        'candidate_id': selected, 'energy_before': observation['metrics'].get('energy_used', 0.),
                        'prediction': copy.deepcopy(one_step), 'energy_interval': interval}
        self.last_candidates = alternatives
        self.cached_key, self.cached_decision = key, copy.deepcopy(result)
        return result
