"""Reproducible HTTP acceptance suite for executable metascenario operations."""
import argparse
import json
import sys
import uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.audit import audit, read_records
from hackroi.metacontroller import MetaController
from hackroi.scenarios import declarations
from scripts.run_demo import Process


def cases():
    return {
        'clean': {'events': []},
        'leader_failure': {'events': [{'time': 2., 'type': 'agent_failure', 'targets': ['mast'], 'parameters': {}}]},
        'relay_recovery': {'events': [
            {'time': 0., 'type': 'infrastructure_failure', 'targets': ['infra_0'], 'parameters': {}},
            {'time': 0., 'type': 'agent_failure', 'targets': ['mast'], 'parameters': {}}]},
        'resource_recovery': {'events': [{'time': 0., 'type': 'resource_shortage', 'targets': ['land'], 'parameters': {}}]},
        'synthesis': {'events': [
            {'time': 0., 'type': 'target_detected', 'targets': ['person_0', 'person_1', 'person_2', 'person_3'], 'parameters': {}},
            {'time': 0., 'type': 'resource_shortage', 'targets': ['land'], 'parameters': {}},
            {'time': 0., 'type': 'contradictory_information', 'targets': [], 'parameters': {}},
            {'time': 0., 'type': 'stale_information', 'targets': [], 'parameters': {}}]},
        'operator_stop': {'events': [{'time': 2., 'type': 'operator_directive', 'targets': [], 'parameters': {'type': 'safe_stop'}}]},
    }


def run(seed=42, output=None):
    output = Path(output).resolve() if output else ROOT/'artifacts'/('stage3_'+uuid.uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Нужен пустой каталог результатов')
    summaries, all_operations = [], set()
    (output/'scenarios.json').write_text(json.dumps(declarations(), ensure_ascii=False, indent=2), encoding='utf-8')
    for name, parameters in cases().items():
        directory = output/name
        directory.mkdir()
        environment = Process(['environment', '--port', '0', '--log-path', str(directory/'environment.jsonl')])
        try:
            url = environment.event('ready')['url']
            controller = MetaController(directory/'controller.jsonl')
            controller.mission_parameters = {**controller.mission_parameters, **parameters}
            summary = controller.run(url, seed, 120, run_id='stage3_'+name+'_'+str(seed))
            environment_records = read_records(directory/'environment.jsonl')
            controller_records = read_records(directory/'controller.jsonl')
            report = audit(environment_records, controller_records)
            decisions = [r['decision'] for r in controller_records if r['kind'] == 'decision']
            operations = sorted({d['operation'] for d in decisions})
            all_operations.update(operations)
            summaries.append({'case': name, **summary, 'operations': operations, 'audit': report})
            observations = [r['output']['observation'] for r in environment_records if r['kind'] in ('reset', 'step')]
            (directory/'replay.json').write_text(json.dumps(observations, ensure_ascii=False), encoding='utf-8')
        finally:
            environment.stop()
    result = {'seed': seed, 'operations_observed': sorted(all_operations), 'results': summaries, 'output_directory': str(output)}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.seed, args.output), ensure_ascii=False, indent=2))
