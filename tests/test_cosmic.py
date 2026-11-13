import copy
import json
from pathlib import Path
import unittest

from hackroi.environment import Environment
from hackroi.cosmic import link
from hackroi.forecast import rebuild_network
from hackroi.simulation import events, network, route
from tests.helpers import reset_request

ROOT = Path(__file__).resolve().parents[1]


class CosmicTests(unittest.TestCase):
    def make(self, enabled=True):
        definition=json.loads((ROOT/'scenarios/missions/cosmic.json').read_text())
        definition['include_cosmic']=enabled
        e=Environment(map_definition=definition)
        e.mutate('reset', reset_request())
        return e

    def test_satellite_is_an_advertised_resource_limited_agent(self):
        e=self.make();a=next(a for a in e.state['agents'] if a['kind']=='cosmic')
        self.assertIn('cosmic',e.capabilities()['extension_agent_kinds']['ariadna.cosmic.v1'])
        self.assertEqual(a['capabilities'],['relay','send_message'])
        self.assertGreater(a['resources']['energy']['value'],a['resources']['energy']['minimum'])
        self.assertEqual(a['position'],[50.,50.,60.])

    def test_outage_routes_through_satellite_and_ablation_disconnects_boat(self):
        for enabled in (True,False):
            e=self.make(enabled);s=e.state;s['time']=4.;events(s);network(s)
            path=route(s,'infra_3','boat')
            if enabled:self.assertIn('orbital',path)
            else:self.assertIsNone(path)
        self.assertEqual(self.make(True).state['schedule'],self.make(False).state['schedule'])

    def test_no_direct_underwater_or_out_of_footprint_channel(self):
        e=self.make();sat=next(a for a in e.state['agents'] if a['kind']=='cosmic')
        boat=next(a for a in e.state['agents'] if a['id']=='boat')
        self.assertTrue(link(sat,boat,sat['position'],boat['position']))
        self.assertFalse(link(sat,boat,sat['position'],[55.,8.,-5.]))
        self.assertFalse(link(sat,boat,sat['position'],[200.,8.,0.]))

    def test_failed_satellite_is_not_a_graph_node(self):
        e=self.make();s=e.state;s['time']=4.;events(s)
        next(a for a in s['agents'] if a['kind']=='cosmic')['status']='failed'
        network(s);self.assertIsNone(route(s,'infra_3','boat'))
        satellite=next(a for a in s['agents'] if a['kind']=='cosmic')
        satellite['status']='safe_mode'
        satellite['resources']['energy']['value']=satellite['resources']['energy']['minimum']
        network(s);self.assertIsNone(route(s,'infra_3','boat'))

    def test_public_forecast_matches_satellite_connectivity(self):
        e=self.make();s=e.state;s['time']=4.;events(s);network(s)
        observation=e.observation();forecast=copy.deepcopy(observation);rebuild_network(forecast)
        self.assertEqual(forecast['network']['known_links'],observation['network']['known_links'])
        self.assertEqual([a['communication']['connected'] for a in forecast['agents']],
                         [a['communication']['connected'] for a in observation['agents']])

    def test_satellite_link_delay_is_public(self):
        e=self.make();links=[l for l in e.state['network']['known_links'] if l.get('kind')=='satellite']
        self.assertTrue(links)
        self.assertTrue(all(l['delay']==2. for l in links))
