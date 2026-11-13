"""Campaign geography is physical, public, seeded, and independent of controller code."""
import json
from pathlib import Path
import tempfile
import unittest
from hackroi.landscapes import PROFILES,surface_tiles,zones,blocked_point
from hackroi.viewer_pack import save,read
from hackroi.contracts import ProtocolError
from hackroi.custom_maps import campaign_map, validate_map
from hackroi.environment import Environment
from tests.helpers import reset_request
ROOT=Path(__file__).resolve().parents[1]

class CampaignTests(unittest.TestCase):
    def test_live_presets_start_at_the_authored_coordinates(self):
        deployments=json.loads((ROOT/'scenarios/campaign/deployments.json').read_text(encoding='utf-8'))
        for name in deployments:
            with self.subTest(mission=name):
                source=json.loads((ROOT/'scenarios/missions'/f'{name}.json').read_text(encoding='utf-8'))
                definition=campaign_map(source,deployments)
                request=reset_request(definition['seed'])
                request['mission']['parameters']['profile']='rescue_v2'
                observation=Environment(map_definition=definition).mutate('reset',request)['observation']
                by_kind={kind:[] for kind in definition['deployment']}
                for agent in observation['agents']:
                    if agent['kind'] in by_kind:
                        by_kind[agent['kind']].append(agent['position'])
                for kind, positions in by_kind.items():
                    self.assertEqual(positions, definition['deployment'][kind][:definition['cohorts']])

    def test_map_rejects_spawn_inside_closed_water_cut_or_another_agent(self):
        definition=json.loads((ROOT/'scenarios/missions/forest.json').read_text(encoding='utf-8'))
        deployment=json.loads((ROOT/'scenarios/campaign/deployments.json').read_text(encoding='utf-8'))['forest']
        definition['deployment']=deployment
        for position in ([4,37,0],deployment['ground'][1]):
            deployment['ground'][0]=position
            with self.assertRaises(ProtocolError):
                validate_map(definition)

    def test_land_does_not_cover_inlets_and_bridges_remain_supported(self):
        for name,profile in PROFILES.items():
            tiles=surface_tiles(name)
            for x0,y0,x1,y1 in profile['cuts']:
                self.assertTrue(blocked_point(name,[(x0+x1)/2,(y0+y1)/2,0]))
                for a,b,c,d in tiles:self.assertFalse(max(a,x0)<min(c,x1) and max(b,y0)<min(d,y1))
            for bridge in profile.get('bridges',[]):
                x,y=[(a+b)/2 for a,b in zip(bridge['min'],bridge['max'])][:2]
                self.assertTrue(any(a<=x<=c and b<=y<=d for a,b,c,d in tiles))
                self.assertFalse(blocked_point(name,[x,y,0]))

    def test_target_cannot_be_placed_inside_fixed_building(self):
        m=json.loads((ROOT/'scenarios/missions/city.json').read_text(encoding='utf-8'))
        m['targets'][0]['position']=[14,25,0]
        with self.assertRaises(ProtocolError):validate_map(m)

    def test_compressed_packet_roundtrip_and_digest_failure(self):
        from hackroi.viewer_pack import PREFIX
        from hackroi.showcase import FORMAT
        f={'time':0,'agents':[],'infrastructure':[],'targets':[],'zones':[]}
        data={'format':FORMAT,'episodes':[{'id':'test','frames':[f],'audit':{'status':'passed'}}]}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.js';save(data,p);self.assertEqual(read(p),data)
            packet=json.loads(p.read_text()[len(PREFIX):-2]);packet['sha256']='0'*64;p.write_text(PREFIX+json.dumps(packet)+';\n')
            with self.assertRaises(ValueError):read(p)

if __name__=='__main__':unittest.main()
