"""Measure satellite-on/off missions and publish audited public replay and branches."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_missions import run
from hackroi.audit import read_records
from hackroi.research import branch
from hackroi.showcase import frame
from hackroi.viewer_pack import save_packet

PREFIX='window.ARIADNA_COSMIC_PACK = '


def build(directory):
    directory=Path(directory);comparisons=[]
    for enabled,label in [(True,'on'),(False,'off')]:
        rows=run(directory/label,mission_ids=['cosmic'],dispersed=True,cosmic_enabled=enabled)
        row=rows[0]
        if row['audit']!='passed':raise ValueError('Cosmic audit failed')
        if enabled and row['status']!='success':raise ValueError('Satellite mission must complete')
        comparisons.append({'satellite':enabled,'time':row['time'],'status':row['status'],
                            'completion':row['metrics']['mission_completion'],'audit':row['audit']})
    folder=directory/'on/cosmic_42_portable'
    pack=json.loads((directory/'on/showcase.json').read_text())
    ep=pack['episodes'][0];ep.update(id='cosmic',map_id='cosmic',title='Орбитальный мост',presentation={'fit':'world'})
    records=read_records(folder/'controller.jsonl')
    selected=next(r for r in records if r['kind']=='decision' and r['decision']['time']==4.)
    definition=json.loads((folder/'map.json').read_text())
    research=branch(folder/'environment.jsonl',folder/'controller.jsonl',directory/'branches',
                    selected['decision_id'],6,map_definition=definition)
    research.update(episode_id='cosmic',incident=next(e for e in selected['observation']['events'] if e['time']==4.))
    for candidate in research['branches']:
        candidate['frames']=[frame(f) for f in json.loads((directory/'branches'/candidate['candidate_id']/'replay.json').read_text())]
    payloads={}
    for label in ('on','off'):
        for path in (directory/label/'cosmic_42_portable').iterdir():
            if path.suffix in ('.json','.jsonl'):payloads[label+'/'+path.name]=path.read_bytes()
    for path in (directory/'branches').rglob('*'):
        if path.is_file():payloads['branches/'+path.relative_to(directory/'branches').as_posix()]=path.read_bytes()
    hashes={'cosmic/'+name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(payloads.items())}
    save_packet({'episode':ep,'research':research,'comparison':comparisons,'source_sha256':hashes},
                ROOT/'viewer/cosmic-data.js',PREFIX)
    with zipfile.ZipFile(ROOT/'submission/cosmic_evidence.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,raw in sorted(payloads.items()):archive.writestr('cosmic/'+name,raw)
    summary={'status':'passed','model':'schematic_geostationary_relay','comparison':comparisons,
             'source_sha256':hashes,'viewer_sha256':hashlib.sha256((ROOT/'viewer/cosmic-data.js').read_bytes()).hexdigest(),
             'evidence_sha256':hashlib.sha256((ROOT/'submission/cosmic_evidence.zip').read_bytes()).hexdigest(),
             'historical_campaign_unchanged':True,'official_score':None}
    (ROOT/'experiments/results/cosmic_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary['comparison'],ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output:build(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='ariadna-cosmic-') as directory:build(directory)
