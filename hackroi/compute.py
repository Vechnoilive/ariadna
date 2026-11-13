"""Bounded sensor aggregation service carried by the existing mesh messages."""
import math

SERVICE = 'ariadna.compute.v1'
KINDS = ('relay', 'charging_station', 'sensor_node', 'base_station', 'compute_node')
MAX_SAMPLES = 32
COST_PER_SAMPLE = .01


def declaration():
    return {'service': SERVICE, 'operation': 'mean', 'max_samples': MAX_SAMPLES,
            'sample_range': [-1., 1.], 'cost_per_sample': COST_PER_SAMPLE,
            'processing_seconds': 1., 'request_action': 'send_message',
            'reset_parameter': 'include_compute_node'}


def node():
    return {'id': 'compute_node_0', 'kind': 'compute_node', 'position': [5., 5., 2.],
            'status': 'active', 'capabilities': ['compute', 'aggregate'],
            'resources': {'compute_budget': {'id': 'compute_budget', 'value': 1.,
                          'minimum': 0., 'maximum': 1., 'unit': 'normalized'}},
            'communication': {'connected': True, 'quality': 1.},
            'constraints': [{'id': SERVICE, **declaration()}]}


def process_message(state, message):
    """Return a delayed reply; compute only after actual, successful delivery."""
    target = next((n for n in state['infrastructure']
                   if n['id'] == message['recipient'] and n['kind'] == 'compute_node'), None)
    if target is None:
        return None
    request = message['payload']
    task_id = request.get('task_id')
    values = request.get('values')
    reply = {'service': SERVICE, 'status': 'rejected', 'code': 'INVALID_TASK'}
    if isinstance(task_id, str) and 1 <= len(task_id) <= 128:
        reply['task_id'] = task_id
        if (request.get('service') == SERVICE and request.get('operation') == 'mean'
                and isinstance(values, list) and 1 <= len(values) <= MAX_SAMPLES
                and all(type(v) in (int, float) and -1 <= v <= 1 and math.isfinite(v) for v in values)):
            budget = target['resources']['compute_budget']
            cost = round(len(values)*COST_PER_SAMPLE, 12)
            if budget['value'] - cost < budget['minimum'] - 1e-12:
                reply['code'] = 'RESOURCE_EXHAUSTED'
            else:
                budget['value'] = max(budget['minimum'], round(budget['value'] - cost, 12))
                reply = {'service': SERVICE, 'task_id': task_id, 'status': 'completed',
                         'value': math.fsum(values)/len(values), 'samples': len(values), 'cost': cost}
    from .simulation import route
    path = route(state, target['id'], message['source'])
    if path is None:
        return None
    identifier = 'message_' + str(state['message_count'])
    state['message_count'] += 1
    return {'id': identifier, 'source': target['id'], 'recipient': message['source'],
            'payload': reply, 'path': path,
            'arrival': state['time'] + 1. + max(1, len(path)-1)}
