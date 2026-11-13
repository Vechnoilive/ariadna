import copy
import unittest
from hackroi.environment import Environment
from hackroi.baselines import FixedController,ReactiveController
from hackroi.contracts import ProtocolError
from hackroi.simulation import EVENT_TYPES,medium,route
from hackroi.http import EnvironmentApplication,background_server
from tests.helpers import reset_request

class SimulationTests(unittest.TestCase):
    def make(self,**parameters):
        e=Environment();r=reset_request(max_steps=60);r['mission']['parameters'].update(profile='rescue_v2',**parameters);e.mutate('reset',r);return e
    def decision(self,e,commands=None):
        d=FixedController().decide(e.observation(),e.state['configuration'] if e.state['configuration']['scenario_ids'] else None)
        d['commands']=commands or [];return d
    def test_search_does_not_publish_hidden_targets(self):
        e=self.make();self.assertEqual(e.observation()['targets'],[]);self.assertEqual(len(e.state['targets']),4)
    def test_all_categories_and_optional_cosmic_extension(self):
        e=self.make(include_cosmic=True);self.assertEqual(len(e.state['agents']),9)
        self.assertTrue(medium('underwater',[60,5,-10]));self.assertFalse(medium('ground',[60,5,0]))
        self.assertFalse(medium('surface_water',[10,5,0]));self.assertTrue(medium('cosmic',[5,5,80]))
    def test_charge_consumes_station_stock(self):
        e=self.make();e.state['agents'][1]['resources']['energy']['value']=.5
        e.mutate('step',self.decision(e,[{'agent_id':'land','action':'charge','parameters':{'station_id':'infra_1'}}]))
        self.assertGreater(e.state['agents'][1]['resources']['energy']['value'],.5)
        self.assertLess(e.state['infrastructure'][1]['resources']['stock']['value'],1)
    def test_resource_shortage_can_deplete_a_station(self):
        e=self.make(events=[{'time':1.,'type':'resource_shortage','targets':['infra_1'],'parameters':{}}])
        e.mutate('step',self.decision(e))
        stock=e.observation()['infrastructure'][1]['resources']['stock']
        self.assertEqual(stock['value'],stock['minimum'])
    def test_invalid_medium_is_atomic(self):
        e=self.make();before=e.observation()
        with self.assertRaises(ProtocolError):e.mutate('step',self.decision(e,[{'agent_id':'boat','action':'move','parameters':{'target':[10,8,0]}}]))
        self.assertEqual(before,e.observation())
    def test_message_has_hop_delay(self):
        e=self.make();path=route(e.state,'fusion','sub');self.assertGreater(len(path),2)
        d=self.decision(e,[{'agent_id':'fusion','action':'send_message','parameters':{'recipient_id':'sub','payload':{'data':1}}}])
        e.mutate('step',d);self.assertEqual(e.state['delivered_messages'],[])
        for _ in range(len(path)):e.mutate('step',self.decision(e))
        self.assertEqual(e.state['delivered_messages'][0]['payload'],{'data':1})
    def test_packet_loss_and_failure_of_inflight_route(self):
        for parameters in ({'message_loss':1.0},{'events':[{'time':1,'type':'agent_failure','targets':['sub'],'parameters':{}}]}):
            e=self.make(**parameters);e.mutate('step',self.decision(e,[{'agent_id':'fusion','action':'send_message','parameters':{'recipient_id':'sub','payload':{}}}]))
            for _ in range(6):e.mutate('step',self.decision(e))
            self.assertEqual(e.state['drop_count'],1);self.assertFalse(e.state['delivered_messages'])
    def test_each_event_type_is_executable_and_reproducible(self):
        for kind in EVENT_TYPES:
            targets=['person_0'] if kind.startswith('target_') else ['boat']
            params={'events':[{'time':1.,'type':kind,'targets':targets,'parameters':{}}]}
            a=self.make(**params);b=self.make(**params);d=self.decision(a)
            self.assertEqual(a.mutate('step',d),b.mutate('step',d));self.assertEqual(a.state['events'][0]['type'],kind)
    def test_failure_blocks_commands_and_changes_network(self):
        e=self.make(events=[{'time':1.,'type':'agent_failure','targets':['boat'],'parameters':{}}]);e.mutate('step',self.decision(e))
        self.assertEqual(next(a for a in e.observation()['agents'] if a['id']=='boat')['status'],'failed')
        with self.assertRaises(ProtocolError):e.mutate('step',self.decision(e,[{'agent_id':'boat','action':'move','parameters':{'target':[60,8,0]}}]))
    def test_invalid_schedule_rejected_before_reset_commit(self):
        for events in ([{'time':1,'type':'fake','targets':[],'parameters':{}}], [{'time':1,'type':'hazard_appeared','targets':[],'parameters':{'min':[1,2]}}]):
            with self.assertRaises(ProtocolError):self.make(events=events)
    def test_both_controls_finish_same_seed_via_http(self):
        for cls in (FixedController,ReactiveController):
            for seed in (0,1,42):
                e=Environment();server,thread=background_server(EnvironmentApplication(e))
                try:
                    result=cls().run('http://127.0.0.1:'+str(server.server_address[1]),seed,100)
                    self.assertEqual(result['status'],'success');self.assertEqual(result['metrics']['mission_completion'],1.)
                finally:server.shutdown();server.server_close();thread.join()
    def test_degraded_speed_is_reduced(self):
        e=self.make(events=[{'time':1,'type':'agent_degradation','targets':['boat'],'parameters':{}}]);e.mutate('step',self.decision(e));old=next(a for a in e.state['agents'] if a['id']=='boat')['position'][:]
        e.mutate('step',self.decision(e,[{'agent_id':'boat','action':'move','parameters':{'target':[75,8,0]}}]))
        self.assertEqual(next(a for a in e.state['agents'] if a['id']=='boat')['position'][0]-old[0],2.)
    def test_baseline_policies_choose_different_priorities(self):
        e=self.make();o=e.observation();o['targets']=[{'id':'low','position':[5.,20.,0.],'status':'unconfirmed','priority':1.}, {'id':'high','position':[30.,8.,0.],'status':'unconfirmed','priority':10.}]
        fixed=FixedController().decide(o);reactive=ReactiveController().decide(o)
        def land(d):return next(c for c in d['commands'] if c['agent_id']=='land')['parameters']['target']
        self.assertEqual(land(fixed),[5.,11.,0.]);self.assertEqual(land(reactive),[8.,8.,0.])
    def test_event_effects_and_delivery_require_confirmation(self):
        e=self.make(events=[{'time':1.,'type':'stale_information','targets':[],'parameters':{}}, {'time':1.,'type':'operator_directive','targets':[],'parameters':{'priority':'urgent'}}])
        e.mutate('step',self.decision(e));self.assertEqual(e.state['observation_quality']['stale_data_ratio'],.5);self.assertEqual(e.state['mission']['directives'][0]['priority'],'urgent')
        e.state['discovered'].add('person_0');e.state['agents'][1]['position']=e.state['targets'][0]['position'][:]
        with self.assertRaises(ProtocolError):e.mutate('step',self.decision(e,[{'agent_id':'land','action':'deliver','parameters':{'target_id':'person_0'}}]))
    def test_new_profile_preserves_idempotence(self):
        e=self.make();d=self.decision(e);first=e.mutate('step',d);count=len(e.journal.records)
        self.assertEqual(e.mutate('step',d),first);self.assertEqual(len(e.journal.records),count)
    def test_time_zero_can_add_a_new_search_object(self):
        e=self.make(events=[{'time':0.,'type':'target_detected','targets':[],'parameters':{'position':[20,10,0],'priority':4.}}])
        self.assertEqual(len(e.state['targets']),5)
        self.assertTrue(any(t['id']=='event_0_target' for t in e.observation()['targets']))
        self.assertEqual(len(e.state['mission']['objectives']),5)
