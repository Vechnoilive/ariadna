"""Audit satellite experiment evidence, replay frames and paired outage conditions."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.audit import audit
from hackroi.showcase import frame
from hackroi.adapters import PublicAdapter
from hackroi.viewer_pack import read_packet
from scripts.build_cosmic import PREFIX


def check():
    summary=json.loads((ROOT/'experiments/results/cosmic_summary.json').read_text())
    packet=read_packet((ROOT/'viewer/cosmic-data.js').read_text(),PREFIX)
    archive=ROOT/'submission/cosmic_evidence.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==summary['evidence_sha256']
    assert hashlib.sha256((ROOT/'viewer/cosmic-data.js').read_bytes()).hexdigest()==summary['viewer_sha256']
    assert packet['source_sha256']==summary['source_sha256']
    assert packet['comparison']==summary['comparison']
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist())==set(summary['source_sha256']) and z.testzip() is None
        for name,digest in summary['source_sha256'].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
        maps=[]
        for label in ('on','off'):
            env=[json.loads(line) for line in z.read('cosmic/'+label+'/environment.jsonl').splitlines()]
            ctrl=[json.loads(line) for line in z.read('cosmic/'+label+'/controller.jsonl').splitlines()]
            assert audit(env,ctrl)['status']=='passed'
            maps.append(json.loads(z.read('cosmic/'+label+'/map.json')))
            if label=='on':
                caps=next(r['capabilities'] for r in ctrl if r['kind']=='reset')
                adapter=PublicAdapter(caps)
                frames=[frame(adapter.normalize(r['output']['observation'])) for r in env if r['kind'] in ('reset','step')]
                assert frames==packet['episode']['frames']
                failed=next(f for f in frames if f['time']==4.)
                satellite=next(a for a in failed['agents'] if a['kind']=='cosmic')
                assert 'boat' in satellite['communication']['relayed_agents']
                assert any(d['roles'].get('orbital')=='relay' for d in packet['episode']['decisions'])
        assert maps[0].pop('include_cosmic') is True and maps[1].pop('include_cosmic') is False
        assert maps[0]==maps[1]
        assert packet['research']['incident']['time']==4.
        assert len({b['fork_checkpoint_sha256'] for b in packet['research']['branches']})==1
        for b in packet['research']['branches']:
            replay=json.loads(z.read('cosmic/branches/'+b['candidate_id']+'/replay.json'))
            assert b['frames']==[frame(o) for o in replay]
    return {'status':'passed','paired_runs':2,'branches':len(packet['research']['branches']),
            'comparison':summary['comparison']}


if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False,indent=2))
