"""Build the offline, audited jury demonstration from real HTTP episodes."""
import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi import __version__
from hackroi.audit import audit
from hackroi.client import Client
from hackroi.counterfactual import CounterfactualController
from hackroi.metacontroller import MetaController
from hackroi.portable import PortableController
from hackroi.research import branch
from hackroi.showcase import FORMAT, episode, fingerprint, frame, save
from scripts.run_demo import Process
from scripts.run_stage3 import cases
from scripts.run_stage4 import case_parameters
from scripts.run_stage5 import PeerProcess, atomic_zip, persist_sources
from scripts.stage5_cases import parameters


def capture(directory, name, controller_type, mission, seed, peer=False):
    directory.mkdir(parents=True)
    arguments = ['environment', '--port', '0', '--log-path', str(directory/'environment.jsonl')]
    process = PeerProcess(arguments) if peer else Process(arguments)
    sources = None
    try:
        url = process.event('ready')['url']
        client = Client(url, max_response_bytes=64*1024*1024)
        capabilities = client.get('capabilities')
        controller = controller_type(directory/'controller.jsonl')
        if mission is not None:
            controller.mission_parameters = mission
        summary = controller.run(url, seed, 210, run_id='stage6_'+name+'_'+str(seed))
        environment_records = client.get('logs')['records']
        controller_records = controller.journal.snapshot()
        sources = environment_records, controller_records
        summary['audit'] = audit(*sources)
    finally:
        process.stop()
        if sources:
            persist_sources(directory, *sources)
    return summary, capabilities, sources


def run(output=None):
    output = Path(output).resolve() if output else ROOT/'artifacts'/('stage6_'+uuid.uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Нужен пустой каталог результатов')
    plan = [
        ('pressure', 'Конкурирующие приоритеты', 'Сравнение четырёх прогнозов и измеренных ветвей из одной точки.',
         CounterfactualController, {'profile': 'rescue_v2', 'max_steps': 100, **case_parameters('priority_pressure')}, 42, False),
        ('flood', 'Наводнение и отказы', 'Новая карта, два звена, восемь целей, отказы после начала миссии.',
         PortableController, parameters('flood_faults'), 2027, False),
        ('synthesis', 'Синтез при неопределённости', 'Противоречивая информация и дефицит ресурса вызывают исполнимый DAG.',
         MetaController, {'profile': 'rescue_v2', 'max_steps': 100, **cases()['synthesis']}, 42, False),
        ('stop', 'Директива оператора', 'Безопасная остановка сохраняется как остановка, а не успешная миссия.',
         MetaController, {'profile': 'rescue_v2', 'max_steps': 100, **cases()['operator_stop']}, 42, False),
        ('peer', 'Независимый стенд', 'Другой код среды, геометрия и имена действий. Собственный peer, не другая команда.',
         PortableController, None, 1009, True),
    ]
    entries, rows, sources = [], [], {}
    for name, title, description, cls, mission, seed, peer in plan:
        directory = output/'evidence'/name
        summary, capabilities, records = capture(directory, name, cls, mission, seed, peer)
        expected = 'safe_stopped' if name == 'stop' else 'success'
        if name == 'stop':
            if summary['status'] != expected:
                raise AssertionError('Expected explicit operator stop: '+str(summary))
        elif summary['status'] != expected:
            raise AssertionError('Demonstration did not finish: '+str(summary))
        entries.append(episode(name, title, description, *records, capabilities, summary))
        rows.append({'case': name, 'seed': seed, **summary})
        for file in ('environment.jsonl', 'controller.jsonl'):
            path = directory/file
            sources[str(path.relative_to(output))] = fingerprint(path)
    branches = branch(output/'evidence/pressure/environment.jsonl', output/'evidence/pressure/controller.jsonl', output/'branches')
    for item in branches['branches']:
        path = output/'branches'/item['candidate_id']/'replay.json'
        item['frames'] = [frame(value) for value in json.loads(path.read_text(encoding='utf-8'))]
    data = {'format': FORMAT, 'version': __version__, 'episodes': entries,
            'research': {'episode_id': 'pressure', **branches}, 'source_sha256': sources,
            'external_teams_tested': 0}
    viewer = output/'viewer'
    shutil.copytree(ROOT/'viewer', viewer, ignore=shutil.ignore_patterns('data.js', '__qa.html', '__pycache__'))
    save(data, viewer/'data.js')
    summary = {'format': 'ariadna.stage6.v1', 'version': __version__, 'results': rows,
               'source_sha256': sources, 'viewer_sha256': fingerprint(viewer/'data.js'),
               'research_decision_id': branches['decision_id'], 'external_teams_tested': 0}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # All processes and writers are stopped. Publish only complete packets.
    with atomic_zip(output/'evidence.zip') as archive:
        for name in sorted(sources):
            archive.write(output/name, name)
        for path in sorted((output/'branches').rglob('*')):
            if path.is_file():
                archive.write(path, str(path.relative_to(output)))
    return {'output': str(output), 'viewer': str(viewer/'index.html'), 'summary': summary}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
