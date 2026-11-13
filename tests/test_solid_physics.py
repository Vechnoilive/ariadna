"""Swept volume contacts, damage thresholds and recovery on public geometry."""
import copy
import unittest
from hackroi.physics import resolve
from hackroi.routing import body_contact, expanded_box, intersects
from hackroi.public_model import routed_move


def agent(identifier,p,speed=1.):
    return {'id':identifier,'kind':'ground','position':list(p),'status':'active',
            'constraints':[{'id':'ariadna.motion.v1','min':[-10,-10,0],'max':[10,10,0],
             'speed':speed,'sensor_radius':3.,'interaction_radius':1.,
             'body':{'min':[-.3,-.3,0],'max':[.3,.3,.6],'clearance':.12},
             'collision':{'model':'solid_v1','failure_normal_speed':2.}}]}


def obstacle(lo,hi):
    return {'id':'wall','type':'obstacle','geometry':{'type':'axis_aligned_box','min':lo,'max':hi}}


class SolidPhysicsTests(unittest.TestCase):
    def test_body_can_separate_or_slide_after_contact_without_becoming_stuck(self):
        for target in ([1.,0.,0.],[1.7,2.,0.]):
            a=agent('a',[1.7,0,0]);scene={'zones':[obstacle([2,-3,0],[2.1,3,2])]}
            self.assertEqual(resolve(scene,{'a':a},{'a':(target,1.)}),{})
            self.assertEqual(a['position'],target)

    def test_fast_body_does_not_tunnel_through_thin_wall(self):
        a=agent('a',[0,0,0]);scene={'zones':[obstacle([2,-3,0],[2.01,3,2])]}
        impacts=resolve(scene,{'a':a},{'a':([6,0,0],1.)})
        self.assertAlmostEqual(a['position'][0],1.7)
        self.assertTrue(impacts['a']['severe'])
        self.assertEqual(impacts['a']['normal_speed'],6.)

    def test_light_contact_survives_retreats_and_public_planner_can_detour(self):
        a=agent('a',[1.4,0,0],.5);scene={'zones':[obstacle([2,-1,0],[2.1,1,2])]}
        impacts=resolve(scene,{'a':a},{'a':([1.9,0,0],1.)})
        self.assertFalse(impacts['a']['severe']);self.assertTrue(impacts['a']['retreated'])
        self.assertLess(a['position'][0],1.7-.12)
        observation={**scene,'agents':[a]}
        command=routed_move(a,[4,0,0],observation)
        self.assertIsNotNone(command)
        self.assertNotEqual(command['parameters']['target'][1],0.)
        self.assertFalse(intersects(a['position'],command['parameters']['target'],*expanded_box([2,-1,0],[2.1,1,2],a['constraints'][0]['body'],.12)))

    def test_glancing_hit_uses_normal_speed_not_tangential_speed(self):
        a=agent('a',[1.5,0,0]);scene={'zones':[obstacle([2,-4,0],[2.1,4,2])]}
        impact=resolve(scene,{'a':a},{'a':([1.9,3,0],1.)})['a']
        self.assertFalse(impact['severe']);self.assertAlmostEqual(impact['normal_speed'],.4)

    def test_opposing_bodies_cannot_swap_even_if_endpoints_are_clear(self):
        a,b=agent('a',[0,0,0]),agent('b',[4,0,0]);scene={'zones':[]}
        impacts=resolve(scene,{'a':a,'b':b},{'a':([4,0,0],1.),'b':([0,0,0],1.)})
        self.assertEqual(set(impacts),{'a','b'});self.assertTrue(all(v['severe'] for v in impacts.values()))
        self.assertAlmostEqual(b['position'][0]-a['position'][0],.6)

    def test_different_heights_are_independent_and_replay_is_deterministic(self):
        fleet={'a':agent('a',[0,0,0]),'b':agent('b',[4,0,2])}
        commands={'a':([4,0,0],1.),'b':([0,0,2],1.)}
        other=copy.deepcopy(fleet)
        self.assertEqual(resolve({'zones':[]},fleet,commands),{})
        self.assertEqual(resolve({'zones':[]},other,commands),{})
        self.assertEqual(fleet,other)

    def test_retreat_is_cancelled_if_another_robot_blocks_it(self):
        a,b=agent('a',[1.5,0,0]),agent('b',[.85,0,0]);scene={'zones':[obstacle([1.82,-1,0],[2.1,1,2])]}
        # A stationary peer behind the contact must never be crossed during recovery.
        before=b['position'][:]
        impacts=resolve(scene,{'a':a,'b':b},{'a':([1.9,0,0],1.)})
        self.assertFalse(impacts['a'].get('retreated',False))
        self.assertEqual(b['position'],before)
        self.assertGreaterEqual(a['position'][0],b['position'][0])

class SolidEnvironmentTests(unittest.TestCase):
    def make(self,start):
        import json
        from pathlib import Path
        from hackroi.environment import Environment
        from tests.helpers import reset_request
        definition=json.loads((Path(__file__).resolve().parents[1]/'examples/custom_forest.json').read_text())
        definition['physics']='solid_v1'
        env=Environment(map_definition=definition);env.mutate('reset',reset_request(42))
        a=next(a for a in env.state['agents'] if a['kind']=='ground')
        a['position']=list(start);env.state['agents']=[a];env.state['schedule']=[]
        wall=obstacle([12,5,0],[12.1,11,3]);wall.update(access={},risk=0.,cost={'energy':1.,'time':1.},communication={},constraints=[])
        env.state['zones']=[wall]
        return env,a

    def decision(self,env,target):
        from hackroi.baselines import FixedController
        d=FixedController().decide(env.observation());d['commands']=[{'agent_id':'land','action':'move','parameters':{'target':target}}]
        return d

    def test_hard_contact_is_a_committed_failure_and_request_retry_is_idempotent(self):
        env,a=self.make([9,8,0]);d=self.decision(env,[15,8,0]);response=env.mutate('step',d)
        self.assertEqual(response,env.mutate('step',d))
        a=response['observation']['agents'][0]
        self.assertEqual(a['status'],'failed');self.assertAlmostEqual(a['position'][0],11.45)
        self.assertEqual(response['command_results'][0]['severity'],'severe')
        self.assertTrue(any(e['source']=='physics' and e['type']=='agent_failure' for e in response['events']))

    def test_light_contact_preserves_agent_reports_retreat_and_charges_actual_path(self):
        env,a=self.make([11.3,8,0]);d=self.decision(env,[11.6,8,0]);initial=a['resources']['energy']['value']
        response=env.mutate('step',d);a=response['observation']['agents'][0]
        self.assertEqual(a['status'],'active');self.assertTrue(response['command_results'][0]['retreated'])
        self.assertTrue(all(e['type']!='agent_failure' for e in response['events']))
        self.assertAlmostEqual(a['position'][0],11.305)
        self.assertAlmostEqual(initial-a['resources']['energy']['value'],(.15+.145)*.003+.001)
