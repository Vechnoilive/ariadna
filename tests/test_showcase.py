"""Evidence preservation, foreign geometry and safe closed-package handoff."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from hackroi.release import build, safe_name, verify
from hackroi.showcase import FORMAT, episode, save, validate_showcase
from hackroi.baselines import ReactiveController
from scripts.run_stage6 import capture

ROOT=Path(__file__).resolve().parents[1]


class ShowcaseTests(unittest.TestCase):
    def sample(self):
        return {'format':FORMAT,'episodes':[{'id':'x','audit':{'status':'passed'},'frames':[
            {'time':0.,'agents':[],'infrastructure':[],'targets':[],'zones':[],'network':{},'metrics':{}},
            {'time':1.,'agents':[],'infrastructure':[],'targets':[],'zones':[],'network':{},'metrics':{}}]}]}

    def test_bad_clocks_duplicates_and_unaudited_sources_rejected(self):
        for change in ('clock','duplicate','audit','nan'):
            data=self.sample()
            if change=='clock':data['episodes'][0]['frames'][1]['time']=0.
            if change=='duplicate':data['episodes']*=2
            if change=='audit':data['episodes'][0]['audit']['status']='incomplete'
            if change=='nan':data['episodes'][0]['frames'][1]['time']=float('nan')
            with self.subTest(change=change),self.assertRaises(ValueError):validate_showcase(data)

    def test_script_payload_escapes_html_without_changing_data(self):
        data=self.sample();data['title']='</script><img src=x onerror=alert(1)>\u2028&'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.js';save(data,path);source=path.read_text(encoding='utf-8')
            self.assertNotIn('</script>',source)
            self.assertEqual(json.loads(source.removeprefix('window.ARIADNA_DEMO = ').rstrip(';\n')),data)

    def test_actual_http_capture_is_audited_and_published_after_process_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'mission'
            summary,caps,records=capture(directory,'test',ReactiveController,{'profile':'rescue_v2','max_steps':40},42)
            self.assertEqual(summary['status'],'success')
            data=episode('test','HTTP','actual',*records,caps,summary)
            self.assertEqual(len(data['frames']),len(data['decisions'])+1)
            self.assertEqual(data['decisions'][0]['time'],data['frames'][0]['time'])
            self.assertEqual(data['decisions'][-1]['result_time'],data['frames'][-1]['time'])
            with zipfile.ZipFile(directory/'sources.zip') as archive:
                for name in ('environment.jsonl','controller.jsonl'):
                    self.assertEqual(archive.read(name),(directory/name).read_bytes())
            bad=copy.deepcopy(records);bad[1][1]['decision']['commands']=[]
            with self.assertRaises(ValueError):episode('bad','bad','bad',*bad,caps,summary)


class ReleaseTests(unittest.TestCase):
    def fixture(self,root):
        for name in ('README.md','.gitignore','.gitattributes'):(root/name).write_text('fixture\n')
        (root/'pyproject.toml').write_text('[project]\nversion="0.6.0"\n')
        (root/'hackroi').mkdir();(root/'hackroi/main.py').write_text('print("ok")\n')
        (root/'artifacts').mkdir();(root/'artifacts/private.txt').write_text('not a deliverable')
        (root/'.env').write_text('not a deliverable')

    def test_inventory_reproducibility_and_secret_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);a=root/'a.zip';b=root/'b.zip'
            result=build(root,a);build(root,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(verify(a)['status'],'passed')
            self.assertFalse(result['documents'])
            with zipfile.ZipFile(a) as z:
                self.assertNotIn('.env',z.namelist());self.assertNotIn('artifacts/private.txt',z.namelist())
            with self.assertRaises(ValueError):build(root,a)

    def test_payload_tamper_inventory_tamper_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);a=root/'a.zip';build(root,a)
            with zipfile.ZipFile(a) as z:members={n:z.read(n) for n in z.namelist()}
            for mode in ('changed','added','traversal'):
                data=dict(members)
                if mode=='changed':data['hackroi/main.py']=b'print("changed")'
                if mode=='added':data['unexpected.py']=b'x'
                if mode=='traversal':data['../outside.py']=b'x'
                path=root/(mode+'.zip')
                with zipfile.ZipFile(path,'w') as z:
                    for name,content in data.items():z.writestr(name,content)
                with self.subTest(mode=mode),self.assertRaises(ValueError):verify(path)

    def test_unsafe_names_and_missing_final_media_rejected(self):
        for name in ('/a','../x','a/../x','a\\b','C:/x','a//b','./x'):
            with self.subTest(name=name),self.assertRaises(ValueError):safe_name(name)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            with self.assertRaises(ValueError):build(root,root/'out.zip',media=root)

    def test_binary_final_materials_are_fingerprinted(self):
        from hackroi.release import MEDIA_FILES
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root);media=root/'final';media.mkdir()
            for name in MEDIA_FILES:(media/name).write_bytes(b'\x00binary\xff'+name.encode())
            result=build(root,root/'out.zip',media=media)
            self.assertFalse(result['screencast']);self.assertTrue(verify(root/'out.zip')['material_status']['documents'])
