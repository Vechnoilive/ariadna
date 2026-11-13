import copy
import json
import tempfile
import unittest
from pathlib import Path

from hackroi.audit import audit, read_records
from hackroi.beliefs import Beliefs
from hackroi.contracts import canonical, validate
from hackroi.environment import Environment
from hackroi.metacontroller import MetaController, public_route
from hackroi.predicates import evaluate
from hackroi.public_model import guard, motion, swept_distance
from hackroi.scenarios import LIBRARY, declarations, synthesize, validate_graph
from scripts.run_stage3 import cases, run
from tests.helpers import reset_request


def make(**parameters):
    environment = Environment()
    request = reset_request(max_steps=100)
    request['mission']['parameters'].update({'profile': 'rescue_v2', 'events': [], **parameters})
    environment.mutate('reset', request)
    return environment


def execute(environment, controller, limit=100):
    previous, parameters, decisions = None, None, []
    for _ in range(limit):
        decision = controller.decide(environment.observation(), previous, parameters)
        validate('decision', decision)
        response = environment.mutate('step', decision)
        decisions.append(decision)
        previous = {'scenario_ids': decision['selected_configuration']['scenario_ids'], 'role_assignments': decision['role_assignments']}
        parameters = decision['selected_configuration']['parameters']
        if response['status'] != 'running':
            return response, decisions
    raise AssertionError('Episode did not finish')


class PredicateTests(unittest.TestCase):
    def test_all_required_structured_operators(self):
        c = {'x': 3, 'xs': [{'v': 1}, {'v': 2}], 'tags': ['safe', 'active']}
        for op, value, expected in [('eq', 3, True), ('ne', 3, False), ('lt', 4, True),
                                     ('le', 3, True), ('gt', 2, True), ('ge', 3, True)]:
            self.assertEqual(evaluate({'op': op, 'left': {'path': 'x'}, 'right': {'value': value}}, c), expected)
        yes = {'op': 'exists', 'arg': {'path': 'x'}}
        no = {'op': 'exists', 'arg': {'path': 'absent'}}
        self.assertTrue(evaluate({'op': 'and', 'args': [yes, {'op': 'not', 'arg': no}]}, c))
        self.assertTrue(evaluate({'op': 'or', 'args': [no, yes]}, c))
        self.assertTrue(evaluate({'op': 'in', 'left': {'value': 'safe'}, 'right': {'path': 'tags'}}, c))
        test = {'op': 'gt', 'left': {'path': 'item.v'}, 'right': {'value': 0}}
        self.assertTrue(evaluate({'op': 'all', 'items': {'path': 'xs'}, 'test': test}, c))
        self.assertTrue(evaluate({'op': 'any', 'items': {'path': 'xs'}, 'test': test}, c))
        self.assertEqual(evaluate({'op': 'count', 'items': {'path': 'xs'}, 'where': test}, c), 2)
        self.assertEqual(evaluate({'op': 'sum', 'items': {'path': 'xs'}, 'select': {'path': 'item.v'}}, c), 3)

    def test_missing_incompatible_and_code_are_not_executed(self):
        self.assertFalse(evaluate({'op': 'gt', 'left': {'path': 'missing'}, 'right': {'value': 0}}, {}))
        self.assertFalse(evaluate({'op': 'gt', 'left': {'value': []}, 'right': {'value': 0}}, {}))
        with self.assertRaises(ValueError):
            evaluate({'op': '__import__', 'value': 'os'}, {})


class ScenarioTests(unittest.TestCase):
    def test_five_complete_declarations_and_real_predicates(self):
        self.assertEqual(len(LIBRARY), 5)
        for declaration in declarations():
            self.assertTrue({'id', 'version', 'title', 'game_model', 'applicability', 'roles', 'objectives',
                             'constraints', 'allowed_actions', 'transition_targets', 'metrics'} <= declaration.keys())
            self.assertTrue({'N', 'Ai', 'Ii', 'Ui', 'K', 'Theta', 'E'} <= declaration['game_model'].keys())
            self.assertIsInstance(declaration['applicability']['entry'][0], dict)
            self.assertIn(declaration['execution']['handler'], ('search', 'service', 'relay', 'recover', 'coordinate'))

    def test_synthesis_validates_dag_and_changes_executable_structure(self):
        definition = synthesize([{'id': 'verify', 'primitive': 'confirm', 'requires': []},
                                 {'id': 'supply', 'primitive': 'deliver', 'requires': ['verify']}])
        self.assertTrue(validate_graph(definition))
        self.assertEqual(definition['graph']['edges'], [['verify', 'supply']])
        self.assertEqual(definition, synthesize(definition['graph']['nodes']))
        for nodes in ([{'id': 'x', 'primitive': 'eval', 'requires': []}],
                      [{'id': 'x', 'primitive': 'search', 'requires': ['x']}],
                      [{'id': 'x', 'primitive': 'search'}, {'id': 'x', 'primitive': 'deliver'}]):
            with self.assertRaises(ValueError):
                synthesize(nodes)


class BeliefTests(unittest.TestCase):
    def test_receipt_is_not_authority_and_reputation_is_updated_once(self):
        o = make().observation()
        o['targets'] = [{'id': 't', 'position': [20, 8, 0], 'status': 'unconfirmed', 'priority': 1}]
        o['network']['messages'] = [{'id': 'm', 'source': 's', 'arrival': 0., 'payload': {'target_id': 't', 'position': [99, 99, 0], 'command': 'deliver'}}]
        b = Beliefs()
        report = b.update(o)
        self.assertFalse(report['message_assessments'][0]['actionable'])
        self.assertEqual(report['source_reputation']['s'], round(1/3, 6))
        self.assertEqual(b.update(o), report)
        o['time'] += 1
        self.assertEqual(b.update(o)['source_reputation'], report['source_reputation'])
        self.assertFalse(b.update(o)['message_assessments'])

    def test_fresh_corroboration_and_old_message_confidence(self):
        o = make().observation()
        o['time'] = 30.
        o['targets'] = [{'id': 't', 'position': [20, 8, 0], 'status': 'confirmed'}]
        o['network']['messages'] = [
            {'id': 'a', 'source': 's', 'arrival': 30., 'payload': {'target_id': 't', 'position': [20, 8, 0]}},
            {'id': 'b', 'source': 's', 'arrival': 0., 'payload': {'target_id': 't', 'position': [20, 8, 0]}}]
        reports = Beliefs().update(o)['message_assessments']
        self.assertTrue(reports[0]['actionable'])
        self.assertFalse(reports[1]['actionable'])
        self.assertGreater(reports[0]['confidence'], reports[1]['confidence'])

    def test_uncertainty_and_actual_feedback(self):
        o = make().observation(); b = Beliefs(); initial = b.update(o)
        o['time'] += 1
        o['observation_quality'].update(stale_data_ratio=.5, contradiction_count=2)
        o['metrics'].update(mission_completion=.2, energy_used=.1)
        o['agents'][0]['status'] = 'failed'
        report = b.update(o)
        self.assertLess(report['confidence'], initial['confidence'])
        self.assertEqual(report['feedback']['mission_delta'], .2)
        self.assertEqual(report['feedback']['new_failures'], ['air'])


class GuardTests(unittest.TestCase):
    def test_reserve_and_unknown_execution_limits_fail_closed(self):
        o = make().observation()
        land = next(a for a in o['agents'] if a['id'] == 'land')
        land['resources']['energy']['value'] = .151
        command = {'agent_id': 'land', 'action': 'move', 'parameters': {'target': [8, 8, 0]}}
        accepted, checks = guard(o, [command])
        self.assertFalse(accepted)
        self.assertEqual(checks[0]['rejected_commands'][0]['reason'], 'energy_reserve')
        land['constraints'] = []
        self.assertFalse(guard(o, [command])[0])

    def test_forbidden_volume_filters_whole_segment(self):
        o = make().observation()
        o['zones'].append({'id': 'new', 'type': 'restricted', 'geometry': {'type': 'axis_aligned_box', 'min': [6, 0, 0], 'max': [7, 100, 0]}})
        accepted, checks = guard(o, [{'agent_id': 'land', 'action': 'move', 'parameters': {'target': [8, 8, 0]}}])
        self.assertFalse(accepted)
        self.assertEqual(checks[0]['rejected_commands'][0]['reason'], 'space_constraint')

    def test_swept_collision_not_just_endpoints(self):
        self.assertEqual(swept_distance([0, 0, 0], [2, 0, 0], [2, 0, 0], [0, 0, 0]), 0.)
        o = make().observation()
        land = next(a for a in o['agents'] if a['id'] == 'land')
        other = copy.deepcopy(land); other.update(id='other', position=[8., 8., 0.])
        o['agents'].append(other)
        commands = [{'agent_id': 'land', 'action': 'move', 'parameters': {'target': [8, 8, 0]}},
                    {'agent_id': 'other', 'action': 'move', 'parameters': {'target': [5, 8, 0]}}]
        self.assertFalse(guard(o, commands)[0])

    def test_duplicate_agent_invalid_params_and_station_stock(self):
        o = make().observation()
        command = {'agent_id': 'land', 'action': 'charge', 'parameters': {'station_id': 'infra_1'}}
        self.assertEqual(len(guard(o, [command, command])[0]), 1)
        next(s for s in o['infrastructure'] if s['id'] == 'infra_1')['resources']['stock']['value'] = 0
        self.assertFalse(guard(o, [command])[0])
        command['parameters'] = {'station_id': 42}
        self.assertFalse(guard(o, [command])[0])

    def test_unknown_mandatory_constraint_blocks_execution(self):
        o = make().observation()
        o['mission']['constraints'] = [{'id': 'external_unsupported_rule', 'mandatory': True}]
        command = {'agent_id': 'land', 'action': 'move', 'parameters': {'target': [8., 8., 0.]}}
        accepted, checks = guard(o, [command])
        self.assertFalse(accepted)
        self.assertEqual(checks[0]['rejected_commands'][0]['reason'], 'unsupported_mandatory_constraint')

    def test_unconfirmed_delivery_is_rejected(self):
        o = make().observation()
        o['targets'] = [{'id': 't', 'position': [5, 8, 0], 'status': 'unconfirmed'}]
        commands = [{'agent_id': 'land', 'action': 'deliver', 'parameters': {'target_id': 't'}}]
        self.assertFalse(guard(o, commands)[0])


class MetaTests(unittest.TestCase):
    def test_normal_mission_reaches_all_targets_multiple_seeds(self):
        for seed in (0, 1, 7, 42):
            e = make(); request = reset_request(seed=seed, max_steps=100)
            request['request_id'] = 'other'; request['mission']['parameters'].update(profile='rescue_v2', events=[])
            e.mutate('reset', request)
            response, decisions = execute(e, MetaController())
            self.assertEqual(response['status'], 'success')
            self.assertEqual(response['metrics']['mission_completion'], 1.)
            self.assertIn('compose', {d['operation'] for d in decisions})
            for d in decisions:
                self.assertEqual(len({c['agent_id'] for c in d['commands']}), len(d['commands']))

    def test_repeat_decision_does_not_mutate_inputs_or_double_update_beliefs(self):
        o = make().observation(); before = copy.deepcopy(o); c = MetaController()
        d = c.decide(o)
        d['explanation']['reason_codes'].append('mutated_copy')
        self.assertNotIn('mutated_copy', c.decide(o)['explanation']['reason_codes'])
        self.assertEqual(o, before)
        self.assertEqual(MetaController().decide(o), c.decide(o))

    def test_public_limits_allow_new_category_without_private_enum(self):
        o = make().observation()
        mapping = {a['id']: 'external_'+a['id'] for a in o['agents']+o['infrastructure']}
        def rename(value):
            if isinstance(value, dict):
                return {k: rename(v) for k,v in value.items()}
            if isinstance(value, list):
                return [rename(v) for v in value]
            return mapping.get(value, value) if isinstance(value, str) else value
        expected = rename(MetaController().decide(o)['commands'])
        o = rename(o)
        for a in o['agents']:
            a['kind'] = 'foreign_'+a['kind']
        d = MetaController().decide(o)
        self.assertEqual(d['commands'], expected)
        self.assertTrue(d['commands'])
        self.assertTrue(all(c['agent_id'].startswith('external_') for c in d['commands']))

    def test_missing_optional_dynamics_yields_explained_safe_stop(self):
        o = make().observation()
        for a in o['agents']:
            a['constraints'] = []
        d = MetaController().decide(o)
        self.assertEqual(d['operation'], 'safe_stop')
        self.assertFalse(d['commands'])

    def test_low_confidence_requires_new_confirmation_before_delivery(self):
        o = make().observation()
        o['observation_quality'].update(stale_data_ratio=.5, contradiction_count=2)
        o['targets'] = [{'id': 't', 'position': [5., 8., 0.], 'status': 'confirmed', 'priority': 2.}]
        d = MetaController().decide(o)
        command = next(c for c in d['commands'] if c['agent_id'] == 'land')
        self.assertEqual(command['action'], 'observe')
        self.assertIn('verify_before_delivery', d['explanation']['reason_codes'])

    def test_feedback_reliability_changes_next_allocation(self):
        e = make(); c = MetaController(); d = c.decide(e.observation()); e.mutate('step', d)
        o = e.observation()
        o['targets'] = [{'id': 't', 'position': [25., 8., 0.], 'status': 'unconfirmed', 'priority': 2.}]
        previous = {'scenario_ids': d['selected_configuration']['scenario_ids'], 'role_assignments': d['role_assignments']}
        next_decision = c.decide(o, previous, d['selected_configuration']['parameters'])
        belief = next_decision['ariadna_meta']['beliefs']
        self.assertGreater(belief['agent_reliability']['land'], .5)
        self.assertTrue(belief['feedback']['command_outcomes'])
        bids = next(v['game_evaluation']['bids'] for v in next_decision['candidate_evaluations'] if v['scenario_id'] == 'priority_service')
        self.assertGreater(next(b['agent_reliability'] for b in bids if b['agent_id'] == 'land'), .5)

    def test_resource_recovery_hysteresis_prevents_charge_return_cycle(self):
        e = make(**cases()['resource_recovery'])
        response, decisions = execute(e, MetaController())
        self.assertEqual(response['status'], 'success')
        land_commands = [c['action'] for d in decisions for c in d['commands'] if c['agent_id'] == 'land']
        self.assertGreaterEqual(land_commands.count('charge'), 4)
        self.assertLess(response['time'], 25)
        self.assertIn('safe_degradation', {s for d in decisions for s in d['selected_configuration']['scenario_ids']})

    def test_failed_coordinator_is_replaced_and_announcement_is_sent(self):
        e = make(**cases()['leader_failure'])
        response, decisions = execute(e, MetaController())
        self.assertEqual(response['status'], 'success')
        self.assertEqual(decisions[0]['selected_configuration']['parameters']['leader_id'], 'mast')
        self.assertNotEqual(decisions[2]['selected_configuration']['parameters']['leader_id'], 'mast')
        self.assertTrue(any('coordination_reconfiguration' in d['selected_configuration']['scenario_ids'] for d in decisions))
        self.assertGreaterEqual(response['metrics']['messages_sent'], 1)
        self.assertFalse(any(c['agent_id'] == 'mast' for d in decisions[2:] for c in d['commands']))

    def test_infrastructure_connectivity_reports_actual_public_network(self):
        e = make(events=[{'time': 0., 'type': 'connectivity_loss', 'targets': ['infra_0'], 'parameters': {}}])
        infrastructure = next(n for n in e.observation()['infrastructure'] if n['id'] == 'infra_0')
        self.assertFalse(infrastructure['communication']['connected'])
        self.assertFalse(any('infra_0' in (link['source'], link['target']) for link in e.observation()['network']['known_links']))
        result, _ = execute(e, MetaController())
        self.assertEqual(result['status'], 'success')

    def test_relay_coalition_restores_and_maintains_connection(self):
        e = make(**cases()['relay_recovery']); c = MetaController()
        self.assertLess(e.observation()['network']['connectivity_score'], 1.)
        response, decisions = execute(e, c)
        self.assertEqual(response['status'], 'success')
        self.assertLess(response['time'], 30)
        self.assertTrue(any(c['action'] == 'relay' for d in decisions for c in d['commands']))
        self.assertEqual(e.observation()['network']['connectivity_score'], 1.)

    def test_synthesized_dependencies_execute_and_finish_not_metadata_only(self):
        e = make(**cases()['synthesis']); response, decisions = execute(e, MetaController())
        self.assertEqual(response['status'], 'success')
        self.assertEqual(decisions[0]['operation'], 'synthesize')
        definition = decisions[0]['selected_configuration']['synthesized_scenario']
        self.assertTrue(validate_graph(definition))
        self.assertEqual(next(n['status'] for n in decisions[0]['ariadna_meta']['graph_execution'] if n['primitive'] == 'deliver'), 'waiting')
        self.assertTrue(any(c['action'] == 'deliver' for d in decisions for c in d['commands']))
        for d in decisions:
            states = {n['node_id']: n['status'] for n in d['ariadna_meta']['graph_execution']}
            for agent, owner in d['ariadna_meta']['command_owners'].items():
                if owner == 'deliver':
                    self.assertEqual(states['confirm'], 'completed')

    def test_unsafe_operator_priority_and_conflicting_directives(self):
        o = make().observation()
        o['targets'] = [{'id': 'blocked', 'position': [85., 85., 0.], 'priority': 100, 'status': 'confirmed'}]
        o['mission']['directives'] = [{'id': 'go', 'type': 'prioritize_target', 'target_id': 'blocked'}]
        d = MetaController().decide(o)
        self.assertEqual(d['operation'], 'safe_stop')
        self.assertIn('operator_directive_conflict', d['explanation']['reason_codes'])
        o['targets'].append({'id': 'other', 'position': [20., 8., 0.], 'priority': 1, 'status': 'confirmed'})
        o['mission']['directives'].append({'id': 'go2', 'type': 'prioritize_target', 'target_id': 'other'})
        self.assertEqual(MetaController().decide(o)['operation'], 'safe_stop')

    def test_operator_stop_and_unrecognized_mandatory_semantics(self):
        for directive in ({'id': 'stop', 'type': 'safe_stop'}, {'id': 'unknown', 'type': 'teleport'}):
            o = make().observation(); o['mission']['directives'] = [directive]
            d = MetaController().decide(o)
            self.assertEqual(d['operation'], 'safe_stop')
            self.assertFalse(d['commands'])

    def test_feasible_priority_is_honored(self):
        o = make().observation()
        o['targets'] = [{'id': 'low', 'position': [20., 8., 0.], 'priority': 1., 'status': 'unconfirmed'},
                        {'id': 'high', 'position': [30., 8., 0.], 'priority': 10., 'status': 'unconfirmed'}]
        o['mission']['directives'] = [{'id': 'urgent', 'type': 'prioritize_target', 'target_id': 'low'}]
        d = MetaController().decide(o)
        bids = next(x['game_evaluation']['bids'] for x in d['candidate_evaluations'] if x['scenario_id'] == 'priority_service')
        self.assertEqual({b['task_id'] for b in bids if b['selected']}, {'low'})
        self.assertIn('urgent', d['ariadna_meta']['accepted_directives'])

    def test_parameter_modification_follows_uncertainty_and_feedback_is_used(self):
        e = make(); c = MetaController(); d = c.decide(e.observation()); e.mutate('step', d)
        o = e.observation(); o['observation_quality'].update(stale_data_ratio=.5, contradiction_count=1)
        p = {'scenario_ids': d['selected_configuration']['scenario_ids'], 'role_assignments': d['role_assignments']}
        d2 = c.decide(o, p, d['selected_configuration']['parameters'])
        self.assertEqual(d2['operation'], 'modify')
        self.assertEqual(d2['selected_configuration']['parameters']['step_scale'], .5)
        self.assertGreater(d2['ariadna_meta']['beliefs']['feedback']['energy_delta'], 0.)


class AcceptanceTests(unittest.TestCase):
    def test_two_process_meta_cli_and_exact_reproducibility(self):
        from scripts.run_demo import Process
        from hackroi.client import Client
        with tempfile.TemporaryDirectory() as temporary:
            traces = []
            for run_number in (0, 1):
                directory = Path(temporary)/str(run_number)
                directory.mkdir()
                environment = Process(['environment', '--port', '0', '--log-path', str(directory/'environment.jsonl')])
                controller = None
                try:
                    url = environment.event('ready')['url']
                    controller = Process(['controller', '--meta', '--port', '0', '--environment-url', url,
                                          '--run-id', 'meta_reproducible', '--log-path', str(directory/'controller.jsonl')])
                    ready = controller.event('ready')
                    self.assertEqual(Client(ready['url']).request('GET', '/v1/controller/health')['controller_id'], 'ariadna_meta')
                    self.assertEqual(controller.event('episode_complete')['status'], 'success')
                    self.assertEqual(audit(read_records(directory/'environment.jsonl'), read_records(directory/'controller.jsonl'))['status'], 'passed')
                finally:
                    if controller:
                        controller.stop()
                    environment.stop()
                traces.append([(directory/name).read_bytes() for name in ('environment.jsonl', 'controller.jsonl')])
            self.assertEqual(traces[0], traces[1])

    def test_http_suite_all_operations_and_replayable_game_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run(42, Path(temporary)/'results')
            self.assertEqual(set(result['operations_observed']), {'select', 'keep', 'modify', 'switch', 'compose', 'synthesize', 'safe_stop'})
            for case in result['results']:
                self.assertEqual(case['status'], 'safe_stopped' if case['case'] == 'operator_stop' else 'success')
                self.assertEqual(case['audit']['meta_decisions_reproduced'], case['metrics']['step_count'])
            directory = Path(result['output_directory'])/'clean'
            environment, controller = read_records(directory/'environment.jsonl'), read_records(directory/'controller.jsonl')
            stripped_environment = copy.deepcopy(environment)
            stripped_controller = copy.deepcopy(controller)
            stripped = next(r for r in stripped_controller if r['kind'] == 'decision')
            del stripped['decision']['ariadna_meta']
            next(r for r in stripped_environment if r['kind'] == 'step')['input'] = copy.deepcopy(stripped['decision'])
            with self.assertRaisesRegex(ValueError, 'метаобоснование'):
                audit(stripped_environment, stripped_controller)
            # Tamper both identical journal copies: basic command equality is insufficient.
            d = next(r for r in controller if r['kind'] == 'decision')
            d['decision']['candidate_evaluations'][0]['utility'] += 1
            next(r for r in environment if r['kind'] == 'step')['input'] = copy.deepcopy(d['decision'])
            with self.assertRaisesRegex(ValueError, 'Метаобоснование'):
                audit(environment, controller)


if __name__ == '__main__':
    unittest.main()
