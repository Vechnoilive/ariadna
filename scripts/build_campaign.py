"""Publish five measured campaign operations; retain technical fixtures as an archive."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi import __version__
from hackroi.contracts import canonical
from hackroi.showcase import FORMAT,frame
from hackroi.viewer_pack import read,save


def build(trial,final,branches):
    trial,final,branches=map(Path,(trial,final,branches));catalog=json.loads((ROOT/'scenarios/missions/catalog.json').read_text(encoding='utf-8'))
    legacy=read(ROOT/'viewer/legacy-data.js');entries=[];results=[];sources={};payloads={}
    def include(name,path):
        raw=Path(path).read_bytes();payloads[name]=raw;sources[name]=hashlib.sha256(raw).hexdigest()
    for item in (item for item in catalog if item['id'] != 'cosmic'):
        name=item['id'];definition=json.loads((ROOT/'scenarios/missions'/item['file']).read_text(encoding='utf-8'))
        parent=final if name in ('quarry','delta') else trial
        folder=parent/f"{name}_{definition['seed']}_portable"
        row=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        if row['status']!='success' or row['audit']!='passed':raise ValueError('Incomplete operation: '+name)
        recorded=json.loads((folder/'map.json').read_text(encoding='utf-8'))
        if recorded.get('physics')=='solid_v1':
            from hackroi.custom_maps import campaign_map
            definition=campaign_map(definition,json.loads((ROOT/'scenarios/campaign/deployments.json').read_text()))
        if recorded!=definition:raise ValueError('Stale map: '+name)
        pack=json.loads((parent/'showcase.json').read_text(encoding='utf-8'))
        ep=copy.deepcopy(next(e for e in pack['episodes'] if e['id']==folder.name))
        ep.update(id=name,map_id=name,title=item['title'],description=item['description'],presentation={'fit':'world'})
        entries.append(ep);results.append(row)
        for filename in ('map.json','environment.jsonl','controller.jsonl','summary.json'):include('missions/'+name+'/'+filename,folder/filename)
    include('landscapes.json',ROOT/'scenarios/campaign/landscapes.json')
    include('catalog.json',ROOT/'scenarios/missions/catalog.json')
    research=json.loads((branches/'branches.json').read_text(encoding='utf-8'))
    for path in sorted(branches.rglob('*')):
        if path.is_file():include('branches/'+path.relative_to(branches).as_posix(),path)
    for b in research['branches']:
        b['frames']=[frame(f) for f in json.loads((branches/b['candidate_id']/'replay.json').read_text(encoding='utf-8'))]
    data={'format':FORMAT,'version':__version__,'default_episode':'forest','episodes':entries+[{**ep,'archived':True} for ep in legacy['episodes']],
          'research':{'episode_id':'forest',**research},'archive_research':legacy['research'],'source_sha256':sources,'external_teams_tested':0}
    save(data,ROOT/'viewer/data.js')
    with zipfile.ZipFile(ROOT/'submission/campaign_evidence.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,raw in sorted(payloads.items()):archive.writestr(name,raw)
    summary={'format':'ariadna.campaign.v1','version':__version__,'default_ids':[e['id'] for e in entries],'results':results,'source_sha256':sources,
             'viewer_sha256':hashlib.sha256((ROOT/'viewer/data.js').read_bytes()).hexdigest(),'evidence_sha256':hashlib.sha256((ROOT/'submission/campaign_evidence.zip').read_bytes()).hexdigest(),
             'research_decision_id':research['decision_id'],'external_teams_tested':0,'official_score':None}
    (ROOT/'experiments/results/campaign_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'operations':len(entries),'packet_bytes':(ROOT/'viewer/data.js').stat().st_size,'sources':len(sources)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--final',type=Path,required=True);p.add_argument('--branches',type=Path,required=True);a=p.parse_args();build(a.trial,a.final,a.branches)
