import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile
from hackroi.custom_maps import campaign_map,validate_map,fingerprint,random_schedule
from hackroi.environment import Environment
from hackroi.contracts import ProtocolError,canonical
from hackroi.studio import Studio,make_studio_server

ROOT=Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT/'examples/custom_forest.json').read_text(encoding='utf-8'))


def reset(seed=42):
    return {'protocol_version':'1.0','request_id':'author_reset','seed':seed,'mission':{'id':'search_and_rescue','parameters':{'profile':'rescue_v2'}}}


class CustomMapTests(unittest.TestCase):
    def test_validation_copies_author_input(self):
        source=example();before=canonical(source);checked=validate_map(source);checked['objects'][0]['position'][0]=35
        self.assertEqual(canonical(source),before)
        self.assertEqual(fingerprint(source),fingerprint(example()))

    def test_rejects_bad_types_nonfinite_oversized_and_unknown_fields(self):
        for field,value in [('seed',True),('cohorts',10),('random_events','yes'),('max_steps',300),('extra','anything')]:
            bad=example();bad[field]=value
            with self.subTest(field=field),self.assertRaises(ProtocolError):validate_map(bad)
        for value in [float('nan'),float('inf')]:
            bad=example();bad['targets'][0]['position'][0]=value
            with self.assertRaises(ProtocolError):validate_map(bad)
        bad=example();bad['objects']*=10
        with self.assertRaises(ProtocolError):validate_map(bad)

    def test_rejects_overlap_blocked_goal_spawn_and_wrong_medium(self):
        values=[]
        m=example();m['objects'].append(copy.deepcopy(m['objects'][0]));values.append(m)
        m=example();m['targets'][0]['position']=[12,24,0];values.append(m)
        m=example();m['objects']=[{'kind':'rock','position':[5,8,0]}];values.append(m)
        m=example();m['targets'][0]['position']=[75,23,0];values.append(m)
        m=example();m['targets'][2]['position']=[28,80,-5];values.append(m)
        for m in values:
            with self.subTest(m=m),self.assertRaises(ProtocolError):validate_map(m)

    def test_frozen_configuration_and_no_hidden_targets_in_public_reset(self):
        definition=example();env=Environment(map_definition=definition)
        definition['targets'][0]['position']=[40,90,0]
        request=reset();before=canonical(request);response=env.mutate('reset',request)
        self.assertEqual(canonical(request),before)
        self.assertEqual(env.state['targets'][0]['position'],[29,23,0])
        self.assertEqual(response['observation']['targets'],[])
        self.assertEqual(len(response['observation']['agents']),13)
        self.assertNotIn('custom_map',env.journal.snapshot()[0]['input']['mission']['parameters'])
        obj=next(z for z in response['observation']['zones'] if z.get('appearance',{}).get('kind')=='tree')
        self.assertEqual(obj['geometry']['max'][2],8)

    def test_seed_reproduces_events_and_changes_them(self):
        a=Environment(map_definition=example());b=Environment(map_definition=example());c=Environment(map_definition=example())
        self.assertEqual(a.mutate('reset',reset()),b.mutate('reset',reset()))
        c.mutate('reset',reset(1009))
        self.assertEqual(a.state['schedule'],b.state['schedule'])
        self.assertNotEqual(a.state['schedule'],c.state['schedule'])
        m=example();m['random_events']=False;e=Environment(map_definition=m);e.mutate('reset',reset());self.assertEqual(e.state['schedule'],[])


class StudioHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.server=make_studio_server(port=0,output=self.temp.name)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.server.studio.close();self.thread.join(timeout=3);self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        req=Request(self.url+path,data=canonical(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        return urlopen(req,timeout=10)
    def test_health_assets_traversal_and_cross_origin(self):
        with self.request('/api/studio/health') as r:self.assertEqual(json.load(r)['status'],'ready')
        with self.request('/vendor/three.bundle.js') as r:self.assertGreater(len(r.read()),100000)
        with self.assertRaises(HTTPError) as error:self.request('/../hackroi/studio.py')
        self.assertEqual(error.exception.code,404)
        with self.assertRaises(HTTPError) as error:self.request('/api/studio/runs',example(),{'Origin':'https://other.example'})
        self.assertEqual(error.exception.code,403)
    def test_invalid_map_does_not_start_processes(self):
        m=example();m['targets']=[]
        with self.assertRaises(HTTPError) as error:self.request('/api/studio/runs',m)
        self.assertEqual(error.exception.code,422)
        self.assertIsNone(self.server.studio.active)
    def test_real_two_process_mission_audit_and_evidence(self):
        m=example();m['random_events']=False
        with self.request('/api/studio/runs',m) as r:job=json.load(r)
        with self.assertRaises(HTTPError) as error:self.request('/api/studio/runs',m)
        self.assertEqual(error.exception.code,409)
        until=time.monotonic()+110;seen=[]
        while time.monotonic()<until:
            with self.request('/api/studio/runs/'+job['id']) as r:value=json.load(r)
            if value.get('frame'):seen.append(value['frame'])
            if value['state']!='running':break
            time.sleep(.2)
        self.assertEqual(value['state'],'completed',value.get('error'))
        self.assertEqual(value['summary']['audit']['status'],'passed')
        self.assertEqual(value['summary']['status'],'success',value['summary'])
        self.assertEqual(value['summary']['metrics']['mission_completion'],1.)
        frames=value['result']['episodes'][0]['frames']
        self.assertEqual(frames[0]['targets'],[])
        self.assertGreater(len(frames[-1]['targets']),0)
        with self.request('/api/studio/runs/'+job['id']+'/evidence.zip') as r:raw=r.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertIsNone(z.testzip());self.assertEqual(set(z.namelist()),{'map.json','environment.jsonl','controller.jsonl','result.json'})
            ctrl=[json.loads(s) for s in z.read('controller.jsonl').decode().splitlines()]
            first=next(r for r in ctrl if r['kind']=='reset')
            self.assertNotIn('custom_map',first['input']['mission']['parameters'])
            self.assertNotIn('targets',first['input']['mission']['parameters'])
        (ROOT/'artifacts').mkdir(exist_ok=True)
        (ROOT/'artifacts/studio_acceptance.json').write_text(json.dumps({'summary':value['summary'],'public_frames':len(frames),'initial_visible_targets':len(frames[0]['targets']),'map_sha256':value['map_sha256']},ensure_ascii=False,indent=2),encoding='utf-8')



class VisualDeliveryTests(unittest.TestCase):
    def test_every_local_script_and_material_is_in_release_inventory(self):
        import base64
        import hashlib
        import re
        from hackroi.release import source_files
        files=source_files(ROOT)
        html=(ROOT/'viewer/index.html').read_text(encoding='utf-8')
        for src in re.findall(r'<script src="([^"]+)"',html):
            self.assertFalse(src.startswith(('http:','https:')))
            self.assertIn('viewer/'+src,files)
        pack=(ROOT/'viewer/textures.js').read_text(encoding='utf-8')
        values=json.loads(pack.removeprefix('window.ARIADNA_TEXTURES=').strip().removesuffix(';'))
        manifest=json.loads((ROOT/'viewer/assets/manifest.json').read_text())
        for name in ('grass','stone','bark','sand','snow','concrete'):
            path='viewer/assets/'+name+'.jpg'
            self.assertIn(path,files)
            raw=(ROOT/path).read_bytes()
            self.assertEqual(base64.b64decode(values[name].split(',',1)[1]),raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest[name]['sha256'])
        for path in ('viewer/vendor/THREE-LICENSE.md','package.json','start.bat'):
            self.assertIn(path,files)
        self.assertNotIn('viewer/__qa.html',files)


class StudioShutdownTests(unittest.TestCase):
    def test_closing_stops_owned_processes_and_prevents_another_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            studio=Studio(tmp);studio.start(example())
            until=time.monotonic()+10
            while time.monotonic()<until:
                with studio.lock:children=list(studio.children)
                if children:break
                time.sleep(.03)
            self.assertTrue(children)
            studio.close()
            self.assertTrue(all(p.poll() is not None for p in children))
            self.assertTrue(all(not t.is_alive() for t in studio.workers))
            with self.assertRaises(ProtocolError):studio.start(example())


if __name__=='__main__':unittest.main()


class MissionCatalogTests(unittest.TestCase):
    def test_five_maps_are_distinct_and_offline_catalog_matches(self):
        catalog=json.loads((ROOT/'scenarios/missions/catalog.json').read_text(encoding='utf-8'))
        deployments=json.loads((ROOT/'scenarios/campaign/deployments.json').read_text(encoding='utf-8'))
        bundled=json.loads((ROOT/'viewer/missions.js').read_text(encoding='utf-8').split('window.ARIADNA_MISSIONS=',1)[1].strip().removesuffix(';'))
        self.assertEqual(len(catalog),5)
        signatures=set()
        for item,display in zip(catalog,bundled):
            source=json.loads((ROOT/'scenarios/missions'/item['file']).read_text(encoding='utf-8'))
            definition=campaign_map(source,deployments)
            signatures.add(fingerprint(definition))
            self.assertEqual(display['map'],definition)
            self.assertEqual(display['id'],item['id'])
        self.assertEqual(len(signatures),5)

    def test_profiles_publish_terrain_keep_targets_private_and_seed_events(self):
        for name in ('forest','quarry','city','snow','delta'):
            m=json.loads((ROOT/f'scenarios/missions/{name}.json').read_text(encoding='utf-8'))
            a,b=Environment(map_definition=m),Environment(map_definition=m)
            obs=a.mutate('reset',reset(m['seed']))['observation'];b.mutate('reset',reset(m['seed']))
            self.assertEqual(obs['targets'],[])
            self.assertEqual(a.state['schedule'],b.state['schedule'])
            land=next(z for z in obs['zones'] if z['type']=='land')
            self.assertEqual(land['appearance']['terrain'],m['terrain'])
            entities={x['id'] for x in a.state['agents']+a.state['infrastructure']}
            self.assertTrue(all(set(e['targets'])<=entities for e in a.state['schedule']))
        for field in ('terrain','conditions'):
            m=example();m[field]='unknown'
            with self.assertRaises(ProtocolError):validate_map(m)

    def test_routing_handles_more_than_24_public_obstacles(self):
        from hackroi.routing import waypoint,intersects
        boxes=[((14.,4.,0.),(16.,16.,3.))]
        boxes += [((float(x),float(y),0.),(float(x+1),float(y+1),3.)) for x in range(22,47,4) for y in range(24,41,5)]
        self.assertGreater(len(boxes),24)
        start=(5.,10.,0.);goal=(30.,10.,0.)
        p=waypoint(start,goal,(0.,0.,0.),(49.,100.,0.),tuple(boxes))
        self.assertIsNotNone(p);self.assertNotEqual(p,goal)
        self.assertFalse(any(intersects(start,p,*b) for b in boxes))
