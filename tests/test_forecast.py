import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from hackroi.audit import audit, read_records
from hackroi.contracts import canonical
from hackroi.counterfactual import CounterfactualController
from hackroi.forecast import Calibration, HORIZON, MODEL_VERSION, WEIGHTS, PublicForecaster, public_step
from hackroi.forecast_policy import POLICIES, add_footprints, clone_policy
from hackroi.research import branch
from scripts.run_stage4 import aggregate, case_parameters, run
from scripts.run_stage3 import cases
from tests.test_metacontroller import make

ROOT = Path(__file__).resolve().parents[1]


def advance(environment, controller, limit=100):
    previous, parameters, decisions, feedbacks = None, None, [], []
    for _ in range(limit):
        decision = controller.decide(environment.observation(), previous, parameters)
        response = environment.mutate('step', decision)
        feedbacks.append(controller.observe_result(response))
        decisions.append(decision)
        previous = {'scenario_ids': decision['selected_configuration']['scenario_ids'], 'role_assignments': decision['role_assignments']}
        parameters = decision['selected_configuration']['parameters']
        if response['status'] != 'running':
            return response, decisions, feedbacks
    raise AssertionError('Episode did not finish')


class ModelTests(unittest.TestCase):
    def test_model_has_no_simulator_import_and_no_future_seed_access(self):
        forbidden = {'environment', 'simulation', 'research'}
        for name in ('forecast', 'forecast_policy', 'counterfactual', 'public_model', 'metacontroller', 'controller'):
            source = (ROOT/'hackroi'/f'{name}.py').read_text(encoding='utf-8')
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(set(node.module.split('.')) & forbidden, (name, node.module))
        observation = make().observation()
        a, b = CounterfactualController(), CounterfactualController()
        a.mission_parameters = {'seed': 42, 'events': [{'time': 5, 'type': 'agent_failure'}]}
        b.mission_parameters = {'seed': 99, 'events': []}
        self.assertEqual(a.decide(observation), b.decide(observation))

    def test_public_step_matches_real_known_dynamics_and_preserves_input(self):
        environment = make()
        observation = environment.observation(); before = copy.deepcopy(observation)
        decision = CounterfactualController().decide(observation)
        predicted, rejected = public_step(observation, decision['commands'])
        actual = environment.mutate('step', decision)['observation']
        self.assertFalse(rejected)
        self.assertEqual(before, observation)
        self.assertEqual(predicted['metrics']['energy_used'], actual['metrics']['energy_used'])
        self.assertEqual(predicted['network']['connectivity_score'], actual['network']['connectivity_score'])
        self.assertEqual([(a['position'], a['resources']) for a in predicted['agents']],
                         [(a['position'], a['resources']) for a in actual['agents']])

    def test_hidden_targets_are_not_created_in_public_prediction(self):
        environment = make(); o = environment.observation(); controller = CounterfactualController()
        d = controller.decide(o)
        self.assertFalse(o['targets'])
        for candidate in d['ariadna_counterfactual']['candidates']:
            self.assertEqual(candidate['nominal']['known_completion_gain'], 0.)
        predicted, _ = public_step(o, d['commands'])
        self.assertEqual(predicted['targets'], [])
        actual = environment.mutate('step', d)['observation']
        self.assertEqual(predicted['time'], actual['time'])

    def test_charge_uses_declared_rate_and_real_stock(self):
        e = make(**cases()['resource_recovery']); o = e.observation()
        c = CounterfactualController(); d = c.decide(o)
        self.assertTrue(any(cmd['action'] == 'charge' for cmd in d['commands']))
        forecast, _ = public_step(o, d['commands']); actual = e.mutate('step', d)['observation']
        self.assertEqual(forecast['infrastructure'], actual['infrastructure'])
        self.assertEqual([(a['position'], a['resources'], a['status'], a['communication']) for a in forecast['agents']],
                         [(a['position'], a['resources'], a['status'], a['communication']) for a in actual['agents']])

    def test_forecast_is_deterministic_bounded_and_stress_is_distinct(self):
        o = make(**case_parameters('priority_pressure')).observation()
        controller = CounterfactualController(); decision = controller.decide(o)
        entry = controller.last_candidates['nearby']; model = PublicForecaster()
        first = model.rollout(o, entry['decision'], entry['intents'], controller.footprints)
        second = model.rollout(o, entry['decision'], entry['intents'], controller.footprints)
        self.assertEqual(first, second)
        self.assertEqual(len(first['curve']), HORIZON)
        self.assertNotEqual(first, model.rollout(o, entry['decision'], entry['intents'], controller.footprints, stress=.8))
        for horizon in (0, 13):
            with self.assertRaises(ValueError):
                model.rollout(o, decision, entry['intents'], [], horizon=horizon)

    def test_design_and_runtime_parameters_are_identical(self):
        design = json.loads((ROOT/'experiments/stage4_design.json').read_text(encoding='utf-8'))
        self.assertEqual(design['model'], MODEL_VERSION)
        self.assertEqual(design['horizon'], HORIZON)
        self.assertEqual(design['weights'], WEIGHTS)
        self.assertFalse(set(design['development_seeds']) & set(design['holdout_seeds']))


class CalibrationTests(unittest.TestCase):
    def test_final_actual_result_is_settled_once(self):
        e = make(); c = CounterfactualController(); result, decisions, feedbacks = advance(e, c)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(c.calibration.samples, len(decisions))
        self.assertTrue(all(f['status'] == 'compared' for f in feedbacks))
        self.assertIsNone(c.observe_result(result))
        self.assertEqual(c.calibration.samples, len(decisions))
        self.assertTrue(all(f['residuals']['energy'] == 0. for f in feedbacks))

    def test_observed_model_error_changes_policy_to_abstention(self):
        e = make(**case_parameters('priority_pressure')); c = CounterfactualController()
        first = c.decide(e.observation()); result = e.mutate('step', first)
        corrupted = copy.deepcopy(result)
        for a in corrupted['observation']['agents']:
            if a['position'] is not None:
                a['position'][0] += 30.
        feedback = c.observe_result(corrupted)
        self.assertLess(feedback['updated_calibration']['trust'], .35)
        previous = {'scenario_ids': first['selected_configuration']['scenario_ids'], 'role_assignments': first['role_assignments']}
        next_decision = c.decide(result['observation'], previous, first['selected_configuration']['parameters'])
        self.assertEqual(next_decision['ariadna_counterfactual']['selected_candidate'], 'meta')
        self.assertEqual(next_decision['ariadna_counterfactual']['selection_reason'], 'forecast_abstention_model_error')

    def test_error_envelope_uses_chosen_residual_history_and_is_not_a_guarantee(self):
        c = Calibration(); before = c.summary()
        pending = {'episode_id': 'e', 'decision_id': 'd', 'candidate_id': 'nearby', 'energy_before': 0.,
                   'energy_interval': [0., .02], 'prediction': {'time': 1., 'energy_delta': .01,
                   'completion': 0., 'connectivity': 1., 'positions': {}, 'known_target_statuses': {}}}
        o = make().observation(); o.update(episode_id='e', time=1.)
        o['metrics']['energy_used'] = .2
        result = c.settle(pending, o)
        self.assertFalse(result['energy_interval_hit'])
        self.assertGreater(c.summary()['energy_error_radius'], before['energy_error_radius'])
        self.assertIn('not_statistical_guarantee', c.summary()['interval_label'])
        self.assertEqual(c.samples, 1)
        o['time'] = 3.
        self.assertEqual(c.settle(pending, o)['status'], 'not_comparable')
        self.assertEqual(c.samples, 1)

    def test_unannounced_failure_reduces_model_trust_from_observed_state_error(self):
        e = make(events=[{'time': 1., 'type': 'agent_failure', 'targets': ['boat'], 'parameters': {}}])
        c = CounterfactualController(); d = c.decide(e.observation()); result = e.mutate('step', d)
        feedback = c.observe_result(result)
        self.assertGreater(feedback['residuals']['state'], 0.)
        self.assertLess(feedback['updated_calibration']['trust'], 1.)
        self.assertEqual(d['ariadna_counterfactual']['selected_one_step_prediction']['agent_statuses']['boat'], 'active')
        self.assertEqual(next(a['status'] for a in result['observation']['agents'] if a['id'] == 'boat'), 'failed')

    def test_discoveries_are_reported_separately_from_guessed_targets(self):
        e = make(); c = CounterfactualController(); previous = parameters = None; found = 0
        for _ in range(4):
            d = c.decide(e.observation(), previous, parameters); r = e.mutate('step', d)
            feedback = c.observe_result(r); found += feedback['new_targets_not_predicted']
            previous = {'scenario_ids': d['selected_configuration']['scenario_ids'], 'role_assignments': d['role_assignments']}
            parameters = d['selected_configuration']['parameters']
        self.assertGreater(found, 0)


class HeadquartersTests(unittest.TestCase):
    def test_priority_alternatives_differ_and_short_horizon_affects_real_choice(self):
        o = make(**case_parameters('priority_pressure')).observation(); c = CounterfactualController()
        d = c.decide(o); w = d['ariadna_counterfactual']
        self.assertIn(w['selected_candidate'], ('nearby', 'reserve'))
        candidates = {x['candidate_id']: x for x in w['candidates']}
        self.assertNotEqual(candidates['meta']['commands'], candidates['nearby']['commands'])
        self.assertGreater(candidates['nearby']['nominal']['known_completion_gain'], candidates['meta']['nominal']['known_completion_gain'])
        self.assertEqual(d['commands'], candidates[w['selected_candidate']]['commands'])
        self.assertEqual(sum(x['selected'] for x in w['candidates']), 1)
        self.assertLessEqual(w['model_step_budget'], len(POLICIES)*2*HORIZON)

    def test_urgent_visible_task_can_reverse_nearest_policy_choice(self):
        e = make(events=[
            {'time': 0., 'type': 'target_detected', 'targets': [], 'parameters': {'position': [8.,8.,0.], 'priority': 1.}},
            {'time': 0., 'type': 'target_detected', 'targets': [], 'parameters': {'position': [17.,8.,0.], 'priority': 50.}}
        ])
        o = e.observation(); c = CounterfactualController(); d = c.decide(o)
        selected = d['ariadna_counterfactual']['selected_candidate']
        alternatives = {x['candidate_id']: x for x in d['ariadna_counterfactual']['candidates']}
        self.assertNotIn(selected, ('nearby', 'reserve'))
        self.assertGreater(alternatives[selected]['score'], alternatives['nearby']['score'])
        self.assertNotEqual(alternatives[selected]['intents']['land']['target_id'], alternatives['nearby']['intents']['land']['target_id'])
        result = e.mutate('step', d); c.observe_result(result)
        previous = {'scenario_ids': d['selected_configuration']['scenario_ids'], 'role_assignments': d['role_assignments']}
        d2 = c.decide(result['observation'], previous, d['selected_configuration']['parameters'])
        nearby = next(x for x in d2['ariadna_counterfactual']['candidates'] if x['candidate_id'] == 'nearby')
        self.assertNotEqual(next(command for command in d2['commands'] if command['agent_id'] == 'land'),
                            next(command for command in nearby['commands'] if command['agent_id'] == 'land'))

    def test_candidates_have_isolated_public_memory_and_inputs_unchanged(self):
        o = make().observation(); saved = copy.deepcopy(o); c = CounterfactualController(); d = c.decide(o)
        self.assertEqual(o, saved)
        rejected = next(k for k in POLICIES if k != d['ariadna_counterfactual']['selected_candidate'])
        c.last_candidates[rejected]['controller'].visited.add(('fake', (1,2,3)))
        self.assertNotIn(('fake', (1,2,3)), c.policy.visited)
        self.assertEqual(c.calibration.samples, 0)
        self.assertEqual(d, c.decide(o))

    def test_cache_defensive_copy_and_episode_isolation(self):
        o = make().observation(); c = CounterfactualController(); d = c.decide(o)
        d['commands'].clear()
        self.assertTrue(c.decide(o)['commands'])
        c.calibration.errors['position'] = 100.
        new = copy.deepcopy(o); new['episode_id'] = 'another_episode'
        reset_decision = c.decide(new)
        self.assertEqual(reset_decision['ariadna_counterfactual']['calibration_before_selection']['samples'], 0)
        self.assertEqual(reset_decision['ariadna_counterfactual']['calibration_before_selection']['trust'], 1.)

    def test_operator_directive_cannot_be_overridden_by_forecast(self):
        for directive in ({'id': 'stop', 'type': 'safe_stop'}, {'id': 'invalid', 'type': 'teleport'}):
            o = make(**case_parameters('priority_pressure')).observation(); o['mission']['directives'] = [directive]
            d = CounterfactualController().decide(o)
            self.assertEqual(d['operation'], 'safe_stop')
            self.assertFalse(d['commands'])
            self.assertEqual(d['ariadna_counterfactual']['selection_reason'], 'mandatory_safe_response')

    def test_missing_motion_limits_is_explained_stop(self):
        o = make().observation()
        for a in o['agents']:
            a['constraints'] = []
        d = CounterfactualController().decide(o)
        self.assertEqual(d['operation'], 'safe_stop')
        self.assertEqual(d['ariadna_counterfactual']['selection_reason'], 'no_safe_alternative')

    def test_six_stage3_cases_still_work_with_forecast_and_fit_protocol_limit(self):
        for case, parameters in cases().items():
            response, decisions, feedback = advance(make(**parameters), CounterfactualController())
            self.assertEqual(response['status'], 'safe_stopped' if case == 'operator_stop' else 'success', case)
            for decision in decisions:
                self.assertLessEqual(len(canonical(decision).encode('utf-8')), 65536)
                self.assertEqual(len(decision['commands']), len({x['agent_id'] for x in decision['commands']}))
            self.assertTrue(all(f is not None for f in feedback))

    def test_search_commitment_matches_frozen_intent_and_releases_on_service(self):
        e = make(); c = CounterfactualController(); d = c.decide(e.observation())
        selected = d['ariadna_counterfactual']['selected_candidate']
        state = c.last_candidates[selected]['controller']
        initial_cell = state.pending_cells['tunnel']
        e.mutate('step', d)
        previous = {'scenario_ids': d['selected_configuration']['scenario_ids'], 'role_assignments': d['role_assignments']}
        d2 = c.decide(e.observation(), previous, d['selected_configuration']['parameters'])
        self.assertEqual(c.policy.pending_cells['tunnel'], initial_cell)
        self.assertEqual(next(x for x in d2['commands'] if x['agent_id'] == 'tunnel')['parameters']['target'][1], 8.)


class ForecastAcceptanceTests(unittest.TestCase):
    def test_two_process_cli_and_exact_reproducibility(self):
        from scripts.run_demo import Process
        from hackroi.client import Client
        with tempfile.TemporaryDirectory() as temporary:
            traces = []
            for i in (0,1):
                directory = Path(temporary)/str(i); directory.mkdir()
                env = Process(['environment', '--port', '0', '--log-path', str(directory/'environment.jsonl')])
                ctrl = None
                try:
                    url = env.event('ready')['url']
                    ctrl = Process(['controller', '--counterfactual', '--port', '0', '--environment-url', url,
                                    '--run-id', 'counterfactual_reproducible', '--log-path', str(directory/'controller.jsonl')])
                    ready = ctrl.event('ready')
                    health = Client(ready['url']).request('GET', '/v1/controller/health')
                    self.assertFalse(health['privileged_environment_access'])
                    self.assertEqual(ctrl.event('episode_complete', timeout=60)['status'], 'success')
                    verified = audit(read_records(directory/'environment.jsonl'), read_records(directory/'controller.jsonl'))
                    self.assertGreater(verified['forecast_updates_checked'], 0)
                finally:
                    if ctrl:
                        ctrl.stop()
                    env.stop()
                traces.append([(directory/name).read_bytes() for name in ('environment.jsonl', 'controller.jsonl')])
            self.assertEqual(traces[0], traces[1])

    def test_paired_http_comparison_branching_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'experiment'
            result = run(output, split='development', selected_cases=['priority_pressure','resource_recovery'])
            rows = result['results']
            for name in ('priority_pressure', 'resource_recovery'):
                matching = [r for r in rows if r['case'] == name]
                self.assertEqual(len({r['initial_public_sha256'] for r in matching}), 1)
                self.assertEqual(len(matching), 4)
            cf = next(r for r in rows if r['case'] == 'priority_pressure' and r['controller'] == 'counterfactual')
            meta = next(r for r in rows if r['case'] == 'priority_pressure' and r['controller'] == 'meta')
            self.assertEqual(cf['status'], 'success')
            self.assertLess(cf['time'], meta['time'])
            fixed = next(r for r in rows if r['case'] == 'resource_recovery' and r['controller'] == 'fixed')
            self.assertEqual(fixed['status'], 'time_limit')
            self.assertIsNone(fixed['error'])
            self.assertEqual(fixed['audit']['status'], 'passed')
            self.assertEqual(cf['calibration']['samples'], cf['metrics']['step_count'])
            directory = output/'development_42_priority_pressure'/'counterfactual'
            self.assertTrue((directory/'headquarters.md').is_file())
            environment, controller = read_records(directory/'environment.jsonl'), read_records(directory/'controller.jsonl')
            for kind in ('score', 'feedback', 'missing', 'missing_meta'):
                e,c = copy.deepcopy(environment), copy.deepcopy(controller)
                if kind == 'feedback':
                    next(r for r in c if r['kind'] == 'result')['forecast_feedback']['residuals']['energy'] += .1
                else:
                    record = next(r for r in c if r['kind'] == 'decision')
                    if kind == 'score':
                        record['decision']['ariadna_counterfactual']['candidates'][0]['score'] += 1.
                    elif kind == 'missing_meta':
                        del record['decision']['ariadna_meta']
                    else:
                        del record['decision']['ariadna_counterfactual']
                    next(r for r in e if r['kind'] == 'step')['input'] = copy.deepcopy(record['decision'])
                with self.assertRaises(ValueError):
                    audit(e,c)
            branches = branch(directory/'environment.jsonl', directory/'controller.jsonl', Path(temporary)/'branches')
            self.assertEqual(len({b['fork_checkpoint_sha256'] for b in branches['branches']}), 1)
            values = {b['candidate_id']: b['actual_completion_gain'] for b in branches['branches']}
            self.assertGreater(values['nearby'], values['meta'])
            self.assertTrue(all(b['status'] == 'running' for b in branches['branches']))
            # Replay sources remain unchanged, and a second reconstruction is byte-identical.
            again = branch(directory/'environment.jsonl', directory/'controller.jsonl', Path(temporary)/'branches_again')
            self.assertEqual(branches, again)
            for name in POLICIES:
                self.assertEqual((Path(temporary)/'branches'/name/'interventions.jsonl').read_bytes(),
                                 (Path(temporary)/'branches_again'/name/'interventions.jsonl').read_bytes())

    def test_failure_aggregation_does_not_reward_early_failure(self):
        rows = [{'split':'development', 'controller':name, 'case':'x', 'seed':42, 'status':'protocol_error',
                 'time':0., 'max_steps':100, 'metrics':{'mission_completion':0.}, 'error':{'code':'X'}} for name in ('fixed',)]
        summary = aggregate(rows)['groups'][0]
        self.assertEqual(summary['mean_penalized_steps'], 100.)
        self.assertEqual(summary['successes'], 0)

    def test_branch_horizon_is_bounded_before_file_access(self):
        for horizon in (0, 13):
            with self.assertRaises(ValueError):
                branch('not-present', 'not-present', 'not-created', horizon=horizon)


if __name__ == '__main__':
    unittest.main()
