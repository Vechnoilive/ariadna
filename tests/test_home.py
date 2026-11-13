import unittest

from hackroi.baselines import FixedController
from hackroi.contracts import ProtocolError
from hackroi.environment import Environment
from hackroi.home import CASES, definition
from hackroi.public_model import blocked, guard, routed_move
from tests.helpers import reset_request


class ApartmentTests(unittest.TestCase):
    def reset(self, case):
        env = Environment(map_definition=definition(case))
        request = reset_request(CASES[case]['seed'])
        return env, env.mutate('reset', request)

    def test_home_is_reproducible_and_keeps_resident_private_until_search(self):
        first, response = self.reset('leak')
        second, same = self.reset('leak')
        self.assertEqual(response, same)
        self.assertEqual(first.state['schedule'], second.state['schedule'])
        observation = response['observation']
        self.assertEqual(len(observation['agents']), 11)
        self.assertEqual(len(observation['infrastructure']), 9)
        self.assertEqual([t['id'] for t in observation['targets']], ['routine'])
        self.assertIn('ariadna.home.v1', first.capabilities()['extensions'])

    def test_safe_route_respects_body_and_clearance(self):
        env, response = self.reset('leak')
        observation = response['observation']
        vacuum = next(a for a in observation['agents'] if a['id']=='vacuum_a')
        body = vacuum['constraints'][0]['body']
        self.assertEqual(body['clearance'], .12)
        start, too_close = [5.1, 2., 0.], [4.78, 2., 0.]
        vacuum['position'] = start
        self.assertFalse(blocked(start, too_close, observation))
        self.assertTrue(blocked(start, too_close, observation, vacuum))
        command = {'agent_id':'vacuum_a','action':'move','parameters':{'target':too_close}}
        self.assertEqual(guard(observation, [command])[0], [])
        detour = routed_move(vacuum, [2., 3.35, 0.], observation)
        self.assertIsNotNone(detour)
        self.assertFalse(blocked(start, detour['parameters']['target'], observation, vacuum))

    def test_detour_avoids_robot_outside_original_line_to_target(self):
        _, response = self.reset('leak')
        observation = response['observation']
        agents = {a['id']:a for a in observation['agents']}
        courier, peer = agents['carrier_b'], agents['carrier_c']
        courier['position'] = [18.219563229668, 9.034914169854, 0.]
        peer['position'] = [19.322871187435, 8.276491347356, 0.]
        observation['agents'] = [courier, peer]
        unsafe = {'agent_id':'carrier_b','action':'move','parameters':{'target':[18.74,8.74,0.]}}
        self.assertFalse(guard(observation, [unsafe], preserve_connectivity=False)[0])
        detour = routed_move(courier, [18.65,4.75,0.], observation)
        self.assertIsNotNone(detour)
        self.assertTrue(guard(observation, [detour], preserve_connectivity=False)[0])

    def test_wrong_trajectory_stops_at_sofa_and_fails_only_that_robot(self):
        env, response = self.reset('leak')
        command = FixedController().decide(response['observation'])
        command['commands'] = [
            {'agent_id':'vacuum_a','action':'move','parameters':{'target':[4.5,2.,0.]}},
            {'agent_id':'carrier_a','action':'move','parameters':{'target':[6.5,11.7,0.]}},
        ]
        result = env.mutate('step', command)
        self.assertEqual(env.mutate('step', command), result)
        vacuum = next(a for a in result['observation']['agents'] if a['id']=='vacuum_a')
        self.assertEqual(vacuum['position'], [4.71,2.,0.])
        self.assertEqual(vacuum['status'], 'failed')
        self.assertFalse(vacuum['communication']['connected'])
        self.assertEqual(result['command_results'][0]['effect'], 'collision')
        self.assertEqual(result['command_results'][1]['status'], 'applied')
        impact, = result['events']
        self.assertEqual((impact['type'],impact['source'],impact['targets']), ('agent_failure','physics',['vacuum_a']))
        self.assertEqual(impact['parameters']['collision_with'], 'sofa')
        followup = FixedController().decide(result['observation'],env.state['configuration'],env.state['parameters'])
        followup['commands'] = [command['commands'][0]]
        with self.assertRaises(ProtocolError) as caught:
            env.mutate('step', followup)
        self.assertEqual(caught.exception.code, 'INVALID_COMMAND')

    def test_swept_peer_collision_and_separate_flight_levels(self):
        env, _ = self.reset('leak')
        positions = {'vacuum_a':[11.,4.,0.], 'vacuum_b':[12.4,4.,0.], 'drone_a':[11.,4.,1.75]}
        for agent in env.state['agents']:
            if agent['id'] in positions:
                agent['position'] = positions[agent['id']]
        observation = env.observation()
        command = FixedController().decide(observation)
        command['commands'] = [
            {'agent_id':'vacuum_a','action':'move','parameters':{'target':[11.95,4.,0.]}},
            {'agent_id':'vacuum_b','action':'move','parameters':{'target':[11.45,4.,0.]}},
            {'agent_id':'drone_a','action':'move','parameters':{'target':[11.95,4.,1.75]}},
        ]
        safe, _ = guard(observation, command['commands'], preserve_connectivity=False)
        self.assertEqual([c['agent_id'] for c in safe], ['drone_a'])
        result = env.mutate('step', command)
        self.assertEqual({e['targets'][0] for e in result['events']}, {'vacuum_a','vacuum_b'})
        agents = {a['id']:a for a in result['observation']['agents']}
        self.assertEqual(agents['drone_a']['position'], [11.95,4.,1.75])
        self.assertAlmostEqual(agents['vacuum_b']['position'][0]-agents['vacuum_a']['position'][0], .62)

    def test_invalid_commands_leave_the_apartment_unchanged(self):
        env, response = self.reset('leak')
        command = FixedController().decide(response['observation'])
        command['commands'] = [{'agent_id':'vacuum_a','action':'deliver','parameters':{'target_id':'routine'}}]
        with self.assertRaises(ProtocolError) as caught:
            env.mutate('step',command)
        self.assertEqual(caught.exception.code,'INVALID_COMMAND')
        self.assertEqual(env.observation(),response['observation'])

    def test_privacy_stop_is_supported_by_the_control_baseline(self):
        env, response = self.reset('privacy')
        controller = FixedController()
        previous, parameters = None, None
        for _ in range(14):
            decision = controller.decide(response['observation'],previous,parameters)
            response = env.mutate('step',decision)
            previous, parameters = env.state['configuration'], env.state['parameters']
            if response['status']!='running':
                break
        self.assertEqual(response['status'],'safe_stopped')
        self.assertEqual(decision['commands'],[])
        self.assertIn('mandatory_operator_stop',decision['explanation']['reason_codes'])
