"""Verify the shipped viewer against original public JSONL and branch replays."""
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.showcase import episode,frame,validate_showcase
from hackroi.viewer_pack import read_packet
from scripts.build_incident import PREFIX as INCIDENT_PREFIX
from scripts.run_home import PREFIX as HOME_PREFIX


def check_legacy(root=ROOT):
    root=Path(root)
    source=(root/'viewer/legacy-data.js').read_text(encoding='utf-8')
    if not source.startswith('window.ARIADNA_DEMO = ') or not source.endswith(';\n'):
        raise ValueError('Unexpected data.js wrapper')
    data=validate_showcase(json.loads(source.removeprefix('window.ARIADNA_DEMO = ')[:-2]))
    summary=json.loads((root/'experiments/results/stage6_summary.json').read_text(encoding='utf-8'))
    if hashlib.sha256((root/'viewer/legacy-data.js').read_bytes()).hexdigest()!=summary['viewer_sha256']:
        raise ValueError('Viewer checksum differs from summary')
    decisions=0
    with zipfile.ZipFile(root/'submission/evidence.zip') as archive:
        if archive.testzip():raise ValueError('Evidence CRC mismatch')
        for name,expected in summary['source_sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=expected:raise ValueError('Evidence checksum mismatch: '+name)
        if summary['source_sha256']!=data['source_sha256']:raise ValueError('Viewer source inventory mismatch')
        for ep in data['episodes']:
            prefix='evidence/'+ep['id']+'/'
            env=[json.loads(line) for line in archive.read(prefix+'environment.jsonl').decode('utf-8').splitlines()]
            ctrl=[json.loads(line) for line in archive.read(prefix+'controller.jsonl').decode('utf-8').splitlines()]
            reset=next(r for r in ctrl if r['kind']=='reset')
            caps=reset.get('capabilities',{'protocol_version':'1.0'})
            rebuilt=episode(ep['id'],ep['title'],ep['description'],env,ctrl,caps,ep['summary'])
            if rebuilt!=ep:raise ValueError('Viewer differs from audited public records: '+ep['id'])
            decisions+=len(ep['decisions'])
        research=data['research'];actual=json.loads(archive.read('branches/branches.json'))
        if research['decision_id']!=actual['decision_id']:raise ValueError('Research fork mismatch')
        if len({b['fork_checkpoint_sha256'] for b in actual['branches']})!=1:raise ValueError('Branch initial states differ')
        for b in research['branches']:
            measured=next(x for x in actual['branches'] if x['candidate_id']==b['candidate_id'])
            if {k:v for k,v in b.items() if k!='frames'}!=measured:raise ValueError('Research metrics mismatch')
            frames=json.loads(archive.read('branches/'+b['candidate_id']+'/replay.json'))
            if b['frames']!=[frame(x) for x in frames]:raise ValueError('Research public replay mismatch')
    return {'status':'passed','episodes':len(data['episodes']),'decisions':decisions,'source_files':len(summary['source_sha256']),'branches':len(data['research']['branches']),'external_teams_tested':data['external_teams_tested']}


def check(root=ROOT):
    root=Path(root);legacy=check_legacy(root)
    home=check_home(root)
    from hackroi.viewer_pack import read
    data=read(root/'viewer/data.js');summary=json.loads((root/'experiments/results/campaign_summary.json').read_text(encoding='utf-8'))
    if hashlib.sha256((root/'viewer/data.js').read_bytes()).hexdigest()!=summary['viewer_sha256']:raise ValueError('Campaign packet checksum differs')
    if hashlib.sha256((root/'submission/campaign_evidence.zip').read_bytes()).hexdigest()!=summary['evidence_sha256']:raise ValueError('Campaign evidence checksum differs')
    ids=['forest','quarry','city','snow','delta'];main=[e for e in data['episodes'] if not e.get('archived')]
    if [e['id'] for e in main]!=ids or data.get('default_episode')!='forest':raise ValueError('Wrong default campaign')
    signatures=set();decisions=0
    with zipfile.ZipFile(root/'submission/campaign_evidence.zip') as archive:
        if archive.testzip():raise ValueError('Campaign CRC mismatch')
        if data['source_sha256']!=summary['source_sha256']:raise ValueError('Campaign source inventory differs')
        if set(archive.namelist())!=set(summary['source_sha256']):raise ValueError('Campaign source names differ')
        for name,digest in summary['source_sha256'].items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('Campaign source mismatch: '+name)
        if archive.read('landscapes.json')!=(root/'scenarios/campaign/landscapes.json').read_bytes():raise ValueError('Stale landscape profile')
        for ep in main:
            prefix='missions/'+ep['id']+'/'
            definition=json.loads(archive.read(prefix+'map.json'))
            expected=json.loads((root/'scenarios/missions'/str(ep['map_id']+'.json')).read_text(encoding='utf-8'))
            if definition.get('physics')=='solid_v1':
                from hackroi.custom_maps import campaign_map
                expected=campaign_map(expected,json.loads((root/'scenarios/campaign/deployments.json').read_text()))
            if definition!=expected:raise ValueError('Stale campaign map')
            env=[json.loads(l) for l in archive.read(prefix+'environment.jsonl').decode('utf-8').splitlines()]
            ctrl=[json.loads(l) for l in archive.read(prefix+'controller.jsonl').decode('utf-8').splitlines()]
            caps=next(r['capabilities'] for r in ctrl if r['kind']=='reset')
            rebuilt=episode(ep['id'],ep['title'],ep['description'],env,ctrl,caps,ep['summary'])
            if rebuilt!={k:v for k,v in ep.items() if k not in ('map_id','presentation')}:raise ValueError('Campaign replay differs: '+ep['id'])
            if ep['summary']['status']!='success':raise ValueError('Incomplete mission')
            initial=env[0]['output']['observation']
            for target in initial['targets']:
                if not any(a['position'] is not None and a['status'] in ('active','degraded') and a['communication']['connected'] and 'sense' in a['capabilities'] and math.dist(a['position'],target['position'])<=12. for a in initial['agents']):
                    raise ValueError('Initial target is outside all public sensors')
            if len(ep['frames'][-1]['targets'])<=len(definition['targets']):raise ValueError('Missing SOS wave')
            signatures.add(json.dumps(ep['frames'][0]['zones'],sort_keys=True));decisions+=len(ep['decisions'])
        actual=json.loads(archive.read('branches/branches.json'));research=data['research']
        if research['episode_id']!='forest' or research['decision_id']!=actual['decision_id']:raise ValueError('Wrong campaign research fork')
        if research['decision_id'] not in {d['decision_id'] for d in main[0]['decisions']}:raise ValueError('Detached research decision')
        for component in ('environment','controller'):
            if actual['source_'+component+'_sha256']!=summary['source_sha256']['missions/forest/'+component+'.jsonl']:raise ValueError('Research source differs')
        if len({b['fork_checkpoint_sha256'] for b in actual['branches']})!=1:raise ValueError('Campaign branches differ at fork')
        for b in research['branches']:
            measured=next(x for x in actual['branches'] if x['candidate_id']==b['candidate_id'])
            if {k:v for k,v in b.items() if k!='frames'}!=measured:raise ValueError('Campaign branch metrics differ')
            if b['frames']!=[frame(x) for x in json.loads(archive.read('branches/'+b['candidate_id']+'/replay.json'))]:raise ValueError('Campaign branch replay differs')
        check_incident(root,main[0],archive)
    if len(signatures)!=5:raise ValueError('Campaign maps are duplicated')
    return {'status':'passed','campaign_episodes':5,'campaign_decisions':decisions,'legacy_episodes':legacy['episodes'],'branches':len(data['research']['branches']),'source_files':len(summary['source_sha256']),'apartment':home,'external_teams_tested':0}


def check_home(root):
    from hackroi.contracts import canonical
    from hackroi.home import CASES

    packet=read_packet((root/'viewer/home-data.js').read_text(encoding='utf-8'),HOME_PREFIX)
    if packet['format']!='ariadna.apartment.v1' or {e['id'] for e in packet['episodes']}!=set(CASES):
        raise ValueError('Wrong apartment campaign')
    if len(packet['results'])!=3*len(CASES):
        raise ValueError('Apartment comparison is incomplete')
    for ep in packet['episodes']:
        rows=[r for r in packet['results'] if r['case']==ep['id']]
        portable=next(r for r in rows if r['mode']=='portable')
        initial=ep['frames'][0]
        digest=hashlib.sha256(canonical(initial).encode()).hexdigest()
        if {r['mode'] for r in rows}!={'portable','fixed','reactive'} or any(
            r['initial_sha256']!=digest or r['audit']!='passed' for r in rows
        ):
            raise ValueError('Apartment controllers must share an audited initial state')
        if ep['audit']['status']!='passed' or ep['summary']['status']!=CASES[ep['id']]['expected'] or (
            portable['status'],portable['time'],portable['metrics']
        )!=(ep['summary']['status'],ep['summary']['time'],ep['summary']['metrics']):
            raise ValueError('Apartment replay differs from the reported result')
        if ep['id']=='blackout' and not any(d['operation']=='synthesize' for d in ep['decisions']):
            raise ValueError('Blackout replay lost its synthesized plan')
    demo=packet.get('impact_demo', {})
    demo_frames=demo.get('frames', [])
    if len(demo_frames)!=2:
        raise ValueError('Missing apartment impact replay')
    active, failed = [next(a for a in f['agents'] if a['id']=='vacuum_a') for f in demo_frames]
    if active['status']!='active' or failed['status']!='failed' or not any(
        e['source']=='physics' and e['type']=='agent_failure' and e['parameters'].get('position')==failed['position']
        for e in demo_frames[1]['events']
    ):
        raise ValueError('Apartment impact replay does not show a physical failure')
    for ep in packet['episodes']:
        mobile=[a for a in ep['frames'][0]['agents'] if a['position'] is not None]
        if not all(any(c.get('body', {}).get('clearance', 0.)>0 for c in a['constraints']) for a in mobile):
            raise ValueError('Apartment agents are missing collision geometry')
    from hackroi.routing import expanded_box, intersects

    def agent(frame, identifier):
        return next(a for a in frame['agents'] if a['id']==identifier)

    leak, blackout, privacy = (next(e for e in packet['episodes'] if e['id']==case) for case in ('leak','blackout','privacy'))
    frames=leak['frames']
    doors={z['id']:z['geometry'] for z in frames[0]['zones'] if z.get('appearance', {}).get('kind')=='home_door'}
    if len(doors)!=5:
        raise ValueError('Incomplete apartment door geometry')
    path=[agent(f,'carrier_b')['position'] for f in frames]
    entry, service = (next((i for i,(a,b) in enumerate(zip(path,path[1:]),1)
                            if intersects(a,b,doors[name]['min'],doors[name]['max'])), -1)
                      for name in ('door_study','door_service'))
    flooded=next(i for i,f in enumerate(frames) if any(z.get('appearance',{}).get('kind')=='home_wet' for z in f['zones']))
    water=next(z['geometry'] for z in frames[flooded]['zones'] if z.get('appearance',{}).get('kind')=='home_wet')
    body=agent(frames[0],'carrier_b')['constraints'][0]['body']
    bounds=expanded_box(water['min'],water['max'],body,body['clearance'])
    if not flooded<entry<service or any(intersects(a,b,*bounds) for a,b in zip(path[flooded:],path[flooded+1:])):
        raise ValueError('The courier did not use both dry doors after flooding')
    if not any(t.get('appearance',{}).get('kind')=='valve' and t['status']=='delivered' for t in frames[-1]['targets']):
        raise ValueError('The valve task was not completed')
    links=[agent(f,'vacuum_b')['communication']['connected'] for f in blackout['frames']]
    if False not in links or not any(links[links.index(False)+1:]):
        raise ValueError('Blackout replay does not recover from a real connection loss')
    locked={z['appearance'].get('door_id') for z in privacy['frames'][-1]['zones']
            if z.get('appearance',{}).get('kind')=='home_private'}
    if locked!={'door_study','door_service'}:
        raise ValueError('Privacy replay must lock both routes into the study')
    research=packet['research']
    leak=next(e for e in packet['episodes'] if e['id']=='leak')
    reference=next((f for f in leak['frames'] if f['time']==research['time']),None)
    if not any(d['decision_id']==research['decision_id'] and d['time']==research['time'] for d in leak['decisions']):
        raise ValueError('Apartment fork is detached from the episode')
    branches=research['branches']
    if len(branches)<2 or sum(b['selected_in_real_episode'] for b in branches)!=1 or any(
        b['frames'][0]!=reference for b in branches
    ):
        raise ValueError('Apartment branches have different initial frames')
    return {'episodes':len(packet['episodes']),'runs':len(packet['results']),'branches':len(branches)}


def check_incident(root, episode, archive):
    packet=read_packet((root/'viewer/incident-data.js').read_text(encoding='utf-8'),INCIDENT_PREFIX)
    event=packet['incident']
    decision=next((d for d in episode['decisions'] if d['decision_id']==packet['decision_id']),None)
    initial=next((f for f in episode['frames'] if f['time']==event['time']),None)
    if (packet['episode_id']!=episode['id'] or not decision or not initial or
            decision['time']!=event['time'] or event not in initial['events'] or event['type']!='agent_failure'):
        raise ValueError('Incident fork does not point to a recorded failure and decision')
    for component in ('environment','controller'):
        source=archive.read(f"missions/{episode['id']}/{component}.jsonl")
        if hashlib.sha256(source).hexdigest()!=packet['source_'+component+'_sha256']:
            raise ValueError('Incident branch source differs')
    candidates=packet['branches']
    if (len(candidates)<2 or sum(b['selected_in_real_episode'] for b in candidates)!=1 or
            len({b['fork_checkpoint_sha256'] for b in candidates})!=1):
        raise ValueError('Incident branches are not comparable')
    for branch in candidates:
        frames=branch['frames']
        if frames[0]!=candidates[0]['frames'][0] or frames[0]['time']!=event['time']:
            raise ValueError('Incident branches do not share their public starting frame')
        if len(frames)-1!=len(branch['actual_curve']):
            raise ValueError('Incident telemetry does not cover the measured branch')
        for observation,point in zip(frames[1:],branch['actual_curve']):
            if (observation['metrics']['mission_completion']!=point['completion'] or
                    observation['network']['connectivity_score']!=point['connectivity']):
                raise ValueError('Incident chart differs from measured public replay')


if __name__=='__main__':
    print(json.dumps(check(),ensure_ascii=False,indent=2))
