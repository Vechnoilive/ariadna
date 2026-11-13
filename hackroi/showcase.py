"""Read-only presentation of audited public traces. Never controls a mission."""
import copy
import hashlib
import json
import math
from pathlib import Path

from .adapters import PublicAdapter
from .audit import audit
from .contracts import canonical

FORMAT = 'ariadna.showcase.v1'


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame(observation):
    """Keep public geometry/resources, omit verbose action schemas in the viewer."""
    keep = ('episode_id', 'time', 'mission', 'agents', 'infrastructure', 'targets',
            'zones', 'network', 'events', 'metrics', 'observation_quality')
    value = copy.deepcopy({k: observation[k] for k in keep if k in observation})
    for agent in value.get('agents', []):
        agent.pop('available_actions', None)
        agent.pop('orientation', None)
        if not agent.get('appearance', {}).get('model'):
            agent.pop('capabilities', None)
        agent['constraints'] = [{k: c[k] for k in ('id', 'min', 'max', 'body') if k in c}
                                for c in agent.get('constraints', []) if c.get('id') in ('ariadna.motion.v1','ariadna.body.v1')]
    return value


def episode(identifier, title, description, environment_records, controller_records, capabilities, summary):
    verification = audit(environment_records, controller_records)
    adapter = PublicAdapter(capabilities)
    observations = [r['output']['observation'] for r in environment_records if r['kind'] in ('reset', 'step')]
    frames = []
    for observation in observations:
        normalized = adapter.normalize(observation)
        normalized['time'] = observation['time']  # viewer clock remains seconds on the wire
        frames.append(frame(normalized))
    results = {r['decision_id']: r for r in controller_records if r['kind'] == 'result'}
    decisions = []
    for record in controller_records:
        if record['kind'] != 'decision':
            continue
        d = record['decision']
        result = results.get(record['decision_id'], {})
        actual = result.get('output', {})
        forecast = copy.deepcopy(d.get('ariadna_counterfactual'))
        if forecast:
            for candidate in forecast['candidates']:
                for key in ('commands', 'intents'):
                    candidate.pop(key, None)
        portable = d.get('ariadna_portable')
        decisions.append({'decision_id': record['decision_id'], 'time': d['time'],
                          'operation': d['operation'], 'configuration': d['selected_configuration'],
                          'roles': d['role_assignments'], 'commands': d['commands'],
                          'explanation': d['explanation'], 'constraints_checked': d['constraint_checks'],
                          'candidate_evaluations': d.get('candidate_evaluations', []),
                          'meta': d.get('ariadna_meta'), 'forecast': forecast,
                          'portable': {k: portable[k] for k in ('version', 'mode', 'capabilities_sha256') if k in portable} if portable else None,
                          'synthesized_scenario': d.get('synthesized_scenario'),
                          'result_time': actual.get('time'), 'result_status': actual.get('status'),
                          'command_results': actual.get('command_results', []),
                          'feedback': result.get('forecast_feedback'),
                          'observation_sha256': hashlib.sha256(canonical(record['observation']).encode()).hexdigest()})
    return {'id': identifier, 'title': title, 'description': description,
            'summary': summary, 'audit': verification, 'frames': frames, 'decisions': decisions,
            'scope': 'Recorded public observations; forecasts are conditional predictions, not measured rejected outcomes.'}


def validate_showcase(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('Expected ariadna.showcase.v1')
    episodes = data.get('episodes')
    if not isinstance(episodes, list) or not episodes or len(episodes) > 64:
        raise ValueError('Expected 1..64 episodes')
    identifiers = set()
    for item in episodes:
        if item['id'] in identifiers:
            raise ValueError('Duplicate episode id')
        identifiers.add(item['id'])
        frames = item.get('frames')
        if not frames or len(frames) > 10001:
            raise ValueError('Invalid frame count')
        previous = -1.
        for value in frames:
            time = value.get('time')
            if not isinstance(time, (int, float)) or not math.isfinite(time) or time <= previous:
                raise ValueError('Frame clocks must increase')
            previous = time
            for group in ('agents', 'infrastructure', 'targets', 'zones'):
                if not isinstance(value.get(group), list):
                    raise ValueError('Missing public entity group')
        if item.get('audit', {}).get('status') != 'passed':
            raise ValueError('Unaudited showcase episode')
    return data


def save(data, path):
    validate_showcase(data)
    # No eval/fetch, works directly via file://; escape script and HTML delimiters.
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    Path(path).write_text('window.ARIADNA_DEMO = '+payload+';\n', encoding='utf-8')
