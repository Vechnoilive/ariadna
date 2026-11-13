"""Run apartment missions through two HTTP processes and publish an offline replay."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hackroi.audit import read_records
from hackroi.baselines import FixedController
from hackroi.client import Client
from hackroi.contracts import canonical
from hackroi.home import CASES, definition
from hackroi.research import branch
from hackroi.showcase import episode, frame
from hackroi.viewer_pack import save_packet
from scripts.run_demo import Process

PREFIX = 'window.ARIADNA_HOME_PACK = '
MODES = ('portable', 'fixed', 'reactive')


def run(directory, case, mode, seed=None):
    directory.mkdir(parents=True, exist_ok=False)
    design = CASES[case]
    map_definition = definition(case, seed)
    env_path, ctrl_path = (directory / (name+'.jsonl') for name in ('environment', 'controller'))
    map_path = directory / 'map.json'
    map_path.write_text(canonical(map_definition)+'\n', encoding='utf-8')
    environment = Process(['environment', '--port', '0', '--map-file', str(map_path), '--log-path', str(env_path)])
    controller = None
    try:
        url = environment.event('ready')['url']
        client = Client(url, max_response_bytes=64*1024*1024)
        capabilities = client.get('capabilities')
        flags = ['--portable'] if mode == 'portable' else ['--baseline', mode]
        controller = Process(['controller', '--port', '0', *flags, '--environment-url', url,
                              '--seed', str(map_definition['seed']), '--run-id', f'home_{case}_{map_definition["seed"]}',
                              '--max-decisions', str(map_definition['max_steps']+1), '--log-path', str(ctrl_path)])
        controller.event('ready')
        result = controller.event('episode_complete', timeout=180)
        trace = episode(case, design['title'], design['description'], read_records(env_path),
                        read_records(ctrl_path), capabilities, result)
        report = {'case': case, 'mode': mode, 'seed': map_definition['seed'], 'status': result['status'],
                  'time': result['time'], 'metrics': result['metrics'], 'audit': trace['audit']['status'],
                  'initial_sha256': hashlib.sha256(canonical(trace['frames'][0]).encode()).hexdigest(),
                  'operations': sorted({d['operation'] for d in trace['decisions']}),
                  'source_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in (map_path, env_path, ctrl_path)}}
        (directory/'summary.json').write_text(canonical(report)+'\n', encoding='utf-8')
        print(canonical(report), flush=True)
        return report, trace
    finally:
        if controller:
            controller.stop()
        environment.stop()


def impact_demo(directory):
    """Record a deliberately unsafe command on the same apartment physics."""
    directory.mkdir()
    map_path = directory/'map.json'
    map_path.write_text(canonical(definition('leak'))+'\n', encoding='utf-8')
    environment = Process(['environment', '--port', '0', '--map-file', str(map_path),
                           '--log-path', str(directory/'environment.jsonl')])
    try:
        client = Client(environment.event('ready')['url'])
        initial = client.post('reset', {'protocol_version': '1.0', 'request_id': 'impact_reset',
                                       'seed': CASES['leak']['seed'],
                                       'mission': {'id': 'search_and_rescue', 'parameters': {}}})
        decision = FixedController().decide(initial['observation'])
        decision['commands'] = [{'agent_id': 'vacuum_a', 'action': 'move', 'parameters': {'target': [4.5, 2., 0.]}}]
        result = client.post('step', decision)
        if result['command_results'][0].get('effect') != 'collision':
            raise ValueError('Impact replay did not hit the sofa')
        return {'id': 'impact', 'title': 'Проверка траектории',
                'description': 'Пылесос получает ошибочную команду и едет прямо на диван.',
                'frames': [frame(response['observation']) for response in (initial, result)],
                'summary': {'status': result['status']}, 'decisions': []}
    finally:
        environment.stop()


def build(directory, output, case_ids, seed):
    episodes, reports = [], []
    for case in case_ids:
        group = []
        for mode in MODES:
            row, trace = run(directory / case / mode, case, mode, seed)
            group.append(row)
            if mode == 'portable':
                if row['status'] != CASES[case]['expected']:
                    raise ValueError(f"{case}: expected {CASES[case]['expected']}, got {row['status']}")
                episodes.append(trace)
        if len({row['initial_sha256'] for row in group}) != 1:
            raise ValueError('Compared controllers started from different public states')
        reports.extend(group)
    research = None
    if 'leak' in case_ids:
        source = directory / 'leak' / 'portable'
        records = read_records(source/'controller.jsonl')
        incident = next(d for d in records if d['kind']=='decision' and
                        any(e['status']=='new' and e['type']=='infrastructure_failure' for e in d['observation']['events']))
        fork_directory = directory/'leak'/'fork'
        research = branch(source/'environment.jsonl', source/'controller.jsonl', fork_directory,
                          incident['decision_id'], map_definition=definition('leak', seed))
        research['time'] = incident['observation']['time']
        for candidate in research['branches']:
            observations = json.loads((fork_directory/candidate['candidate_id']/'replay.json').read_text(encoding='utf-8'))
            candidate['frames'] = [frame(o) for o in observations]
    package = {'format': 'ariadna.apartment.v1', 'episodes': episodes, 'results': reports, 'research': research,
               'impact_demo': impact_demo(directory/'impact')}
    save_packet(package, output, PREFIX)
    return package


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for raw evidence')
    parser.add_argument('--publish', type=Path, help='Write the compressed offline replay bundle')
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--mode', choices=MODES, default='portable')
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    if args.publish:
        build(args.output.resolve(), args.publish, args.cases, args.seed)
    else:
        for name in args.cases:
            run(args.output.resolve()/name/args.mode, name, args.mode, args.seed)
