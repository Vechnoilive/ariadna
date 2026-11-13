"""Reproduce the failure fork from the shipped forest journals."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.audit import read_records
from hackroi.research import branch
from hackroi.showcase import frame
from hackroi.viewer_pack import save_packet

PREFIX='window.ARIADNA_INCIDENT_PACK = '


def build(output):
    with TemporaryDirectory() as temp:
        root=Path(temp)
        env,ctrl=root/'environment.jsonl',root/'controller.jsonl'
        with ZipFile(ROOT/'submission/campaign_evidence.zip') as archive:
            for path in (env,ctrl):
                path.write_bytes(archive.read('missions/forest/'+path.name))
            definition=json.loads(archive.read('missions/forest/map.json'))
        record=next(row for row in read_records(ctrl) if row['kind']=='decision' and any(
            e['status']=='new' and e['type']=='agent_failure' for e in row['observation']['events']
        ))
        event=next(e for e in record['observation']['events'] if e['status']=='new' and e['type']=='agent_failure')
        directory=root/'branch'
        packet=branch(env,ctrl,directory,record['decision_id'],map_definition=definition)
        for candidate in packet['branches']:
            replay=json.loads((directory/candidate['candidate_id']/'replay.json').read_text(encoding='utf-8'))
            candidate['frames']=[frame(observation) for observation in replay]
        packet.update(episode_id='forest', incident=event)
        return save_packet(packet,output,PREFIX)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'viewer/incident-data.js')
    print(build(parser.parse_args().output))
