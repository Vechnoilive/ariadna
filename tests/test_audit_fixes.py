"""Regression cases found by the independent protocol and portability audit."""
import copy
import unittest

from hackroi.adapters import base_profile_limits
from hackroi.baselines import FixedController
from hackroi.compute import SERVICE
from hackroi.contracts import ProtocolError, validate
from hackroi.environment import Environment
from hackroi.http import EnvironmentApplication, background_server
from hackroi.portable import PortableController
from hackroi.simulation import metrics, network
from tests.helpers import reset_request


class ResponseProfileTests(unittest.TestCase):
    def test_reset_accepts_minimal_reply_but_step_still_requires_outcomes(self):
        response = Environment().mutate('reset', reset_request())
        for key in ('command_results', 'events', 'metrics'):
            response.pop(key)
        validate('reset_response', response)
        with self.assertRaises(ProtocolError):
            validate('response', response)
        response['observation']['agents'][0]['resources']['energy']['value'] = .01
        with self.assertRaises(ProtocolError):
            validate('reset_response', response)

    def test_controller_runs_with_normative_reset_reply_over_http(self):
        class MinimalReset(EnvironmentApplication):
            def dispatch(self, method, path, payload=None):
                response = super().dispatch(method, path, payload)
                if path.endswith('/reset'):
                    for key in ('command_results', 'events', 'metrics'):
                        response.pop(key)
                return response

        server, thread = background_server(MinimalReset(Environment()))
        try:
            result = PortableController().run(f'http://127.0.0.1:{server.server_address[1]}', 42, 100)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(result['status'], 'success')


class BaseSpatialTests(unittest.TestCase):
    def test_published_volume_keeps_vertical_motion_and_surface_elevation(self):
        for kind, medium in [('aerial', 'air'), ('underground', 'underground'), ('underwater', 'water')]:
            with self.subTest(kind=kind):
                limits = base_profile_limits({'kind': kind, 'position': [5., 5., 2.]},
                    [{'type': medium, 'geometry': {'type': 'axis_aligned_box', 'min': [0., 0., 0.], 'max': [10., 10., 5.]}}])
                self.assertEqual((limits['min'][2], limits['max'][2]), (0., 5.))
        for kind, medium in [('ground', 'land'), ('surface_water', 'water')]:
            limits = base_profile_limits({'kind': kind, 'position': [5., 5., 2.]},
                [{'type': medium, 'geometry': {'type': 'axis_aligned_box', 'min': [0., 0., -5.], 'max': [10., 10., 5.]}}])
            self.assertEqual((limits['min'][2], limits['max'][2]), (2., 2.))

    def run_water_mission(self, hidden):
        class BaseWater(EnvironmentApplication):
            def dispatch(self, method, path, payload=None):
                if path.endswith('/capabilities'):
                    return {'protocol_version': '1.0'}
                if path.endswith('/reset'):
                    payload['mission']['parameters'].update(profile='rescue_v2', events=[], max_steps=30)
                response = super().dispatch(method, path, payload)
                if path.endswith('/reset'):
                    state = self.environment.state
                    agent = copy.deepcopy(next(a for a in state['agents'] if a['kind'] == 'underwater'))
                    agent['position'] = [58., 8., -1. if hidden else -8.]
                    state['agents'] = [agent]
                    state['targets'] = [{'id': 'victim', 'position': [58., 8., -15. if hidden else -5.], 'priority': 1., 'status': 'unconfirmed' if hidden else 'confirmed'}]
                    state['discovered'] = set() if hidden else {'victim'}
                    state['mission']['objectives'] = [{'id': 'rescue', 'type': 'deliver', 'target_id': 'victim', 'priority': 1., 'status': 'pending'}]
                    network(state); metrics(state)
                    response = self.environment._response(state)
                if 'observation' in response:
                    for agent in response['observation']['agents']:
                        agent['constraints'] = [c for c in agent['constraints'] if not c.get('id', '').startswith('ariadna.')]
                        agent['available_actions'] = [{'action': a['action']} for a in agent['available_actions']]
                    response['observation']['network'].pop('link_range', None)
                return response

        server, thread = background_server(BaseWater(Environment()))
        controller = PortableController()
        try:
            result = controller.run(f'http://127.0.0.1:{server.server_address[1]}', 42, 30)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual((result['status'], result['metrics']['mission_completion']), ('success', 1.))
        decisions = [r['decision'] for r in controller.journal.records if r['kind'] == 'decision']
        self.assertTrue(any(c['action'] == 'move' and c['parameters']['target'][2] != (-1. if hidden else -8.)
                            for d in decisions for c in d['commands']))
        self.assertTrue(all(d['ariadna_portable']['mode'] == 'base_profile' for d in decisions))
        return controller

    def test_underwater_delivery_changes_depth_without_optional_extensions_over_http(self):
        self.run_water_mission(hidden=False)

    def test_vertical_search_discovers_hidden_target_before_delivery_over_http(self):
        controller = self.run_water_mission(hidden=True)
        reset = next(r for r in controller.journal.records if r['kind'] == 'reset')
        self.assertEqual(reset['output']['observation']['targets'], [])
        self.assertTrue(any(r['kind'] == 'decision' and r['observation']['targets']
                            for r in controller.journal.records))


class ComputeNodeTests(unittest.TestCase):
    def make(self, **parameters):
        environment = Environment()
        request = reset_request(max_steps=30)
        request['mission']['parameters'].update(profile='rescue_v2', events=[], include_compute_node=True, **parameters)
        environment.mutate('reset', request)
        return environment

    def step(self, environment, payload=None):
        decision = FixedController().decide(environment.observation(),
            environment.state['configuration'] if environment.state['configuration']['scenario_ids'] else None,
            environment.state['parameters'])
        decision['commands'] = [] if payload is None else [{'agent_id': 'fusion', 'action': 'send_message',
            'parameters': {'recipient_id': 'compute_node_0', 'payload': payload}}]
        return environment.mutate('step', decision), decision

    def request(self, values):
        return {'service': SERVICE, 'task_id': 'sensor_fusion', 'operation': 'mean', 'values': values}

    def reply(self, environment):
        return next((m['payload'] for m in environment.observation()['network']['messages']
                     if m['source'] == 'compute_node_0'), None)

    def test_compute_service_consumes_budget_and_delivers_delayed_reproducible_reply(self):
        first, second = self.make(), self.make()
        for environment in (first, second):
            self.assertIn('compute_node', environment.capabilities()['infrastructure_kinds'])
            result, decision = self.step(environment, self.request([.2, .4]))
            self.assertIsNone(self.reply(environment))
            before = copy.deepcopy(environment.state)
            self.assertEqual(environment.mutate('step', decision), result)
            self.assertEqual(environment.state, before)
            self.step(environment); self.assertIsNone(self.reply(environment))
            self.step(environment)
            reply = self.reply(environment)
            self.assertEqual(reply['status'], 'completed')
            self.assertAlmostEqual(reply['value'], .3)
            node = next(n for n in environment.observation()['infrastructure'] if n['kind'] == 'compute_node')
            self.assertEqual(node['resources']['compute_budget']['value'], .98)
        self.assertEqual(first.observation(), second.observation())

    def test_exhaustion_malformed_tasks_and_network_loss_do_not_execute_work(self):
        for mode in ('exhausted', 'invalid', 'huge_integer', 'lost'):
            with self.subTest(mode=mode):
                environment = self.make(message_loss=1. if mode == 'lost' else 0.)
                node = next(n for n in environment.state['infrastructure'] if n['kind'] == 'compute_node')
                if mode == 'exhausted':
                    node['resources']['compute_budget']['value'] = 0.
                values = [True] if mode == 'invalid' else [10**400] if mode == 'huge_integer' else [.2, .4]
                budget = node['resources']['compute_budget']['value']
                self.step(environment, self.request(values))
                self.step(environment); self.step(environment)
                self.assertEqual(next(n for n in environment.state['infrastructure'] if n['kind'] == 'compute_node')['resources']['compute_budget']['value'], budget)
                reply = self.reply(environment)
                if mode == 'lost':
                    self.assertIsNone(reply)
                    self.assertEqual(environment.observation()['metrics']['messages_dropped'], 1)
                else:
                    self.assertEqual(reply['code'], 'RESOURCE_EXHAUSTED' if mode == 'exhausted' else 'INVALID_TASK')
