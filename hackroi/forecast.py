"""Public short-horizon model and online residuals. No simulator or private state."""
import copy
import math

from .forecast_policy import add_footprints, information_gain
from .public_model import actions, blocked, guard, intersects, motion, move_towards, reachable

MODEL_VERSION = 'ariadna.public_forecast.v1'
HORIZON = 6
WEIGHTS = {'completion': 100., 'information': 3., 'energy': 3., 'stopped': 4., 'reserve': 8.}


def idle_cost(agent):
    declaration = next((c for c in agent['constraints'] if c.get('id') == 'ariadna.energy.v1'), {})
    return declaration.get('idle_energy', (motion(agent) or {}).get('idle_energy', 0.))


def completion(observation):
    targets = {t['id']: t for t in observation['targets']}
    objectives = [o for o in observation['mission']['objectives'] if o.get('type') == 'deliver']
    if objectives:
        total = sum(o.get('priority', 1.) for o in objectives)
        done = sum(o.get('priority', 1.) for o in objectives if targets.get(o.get('target_id'), {}).get('status') == 'delivered' or o.get('status') == 'completed')
    else:
        total = sum(t.get('priority', 1.) for t in targets.values())
        done = sum(t.get('priority', 1.) for t in targets.values() if t.get('status') == 'delivered')
    return done / total if total else 0.


def rebuild_network(observation, range_factor=1.):
    """Graph from declared coordinates, relay capabilities and public outages."""
    radius = observation['network'].get('link_range')
    if not isinstance(radius, (int, float)):
        return
    outages = {i for e in observation['events'] if e['type'] == 'connectivity_loss' and e['status'] in ('new', 'active') for i in e['targets']}
    nodes = {n['id']: n for n in observation['agents']+observation['infrastructure']
             if n['status'] in ('active', 'degraded', 'safe_mode', 'charging') and n['id'] not in outages}
    positions = {i: n['position'] if n['position'] is not None else n['communication'].get('anchor_position') for i,n in nodes.items()}
    graph, links = {i: [] for i in nodes}, []
    for index, identifier in enumerate(sorted(nodes)):
        p = positions[identifier]
        if p is None:
            continue
        for other in sorted(nodes)[index+1:]:
            q = positions[other]
            if q is None or math.dist(p, q) > radius*range_factor:
                continue
            if any(z['type'] == 'low_connectivity' and z['geometry'].get('type') == 'axis_aligned_box' and
                   intersects(p, q, z['geometry']['min'], z['geometry']['max']) for z in observation['zones']):
                continue
            graph[identifier].append(other); graph[other].append(identifier)
            links.append({'source': identifier, 'target': other, 'quality': observation['network']['average_link_quality'], 'delay': 1.})
    roots = sorted(i for i,n in nodes.items() if n.get('kind') == 'base_station')
    if not roots:
        return
    seen, connected, queue = set(roots), set(roots), list(roots)
    while queue:
        current = queue.pop(0)
        for other in sorted(graph[current]):
            connected.add(other)
            if other not in seen and 'relay' in nodes[other]['capabilities']:
                seen.add(other); queue.append(other)
    remaining, components = set(graph), 0
    while remaining:
        components += 1; stack = [remaining.pop()]
        while stack:
            for other in graph[stack.pop()]:
                if other in remaining:
                    remaining.remove(other); stack.append(other)
    participants = [a for a in observation['agents'] if a['status'] not in ('failed', 'offline')]
    score = sum(a['id'] in connected for a in participants) / max(1, len(participants))
    observation['network'].update(connectivity_score=score, reachable_agent_ratio=score,
                                  partition_count=max(0, components-1), known_links=links)
    for n in observation['agents']+observation['infrastructure']:
        n['communication']['connected'] = n['id'] in connected
        n['communication']['quality'] = observation['network']['average_link_quality'] if n['id'] in connected else 0.


def public_step(observation, commands, speed_factor=1., cost_factor=1., range_factor=1.):
    """Propagate known public entities only; never invent hidden targets or events."""
    state = copy.deepcopy(observation)
    agents = {a['id']: a for a in state['agents']}
    targets = {t['id']: t for t in state['targets']}
    accepted, checks = guard(state, commands)
    spent = 0.
    for command in accepted:
        a, action, parameters = agents[command['agent_id']], command['action'], command['parameters']
        limits = motion(a)
        descriptor = actions(a)[action]
        cost = descriptor.get('execution_energy', descriptor.get('energy_cost', 0.))
        if action == 'move':
            start, destination = a['position'], parameters['target']
            speed = limits['speed']*(limits.get('degraded_speed_factor', .5) if a['status'] == 'degraded' else 1.)*speed_factor
            distance = math.dist(start, destination)
            fraction = min(1., speed/distance) if distance else 0.
            end = [round(x+fraction*(y-x), 12) for x,y in zip(start, destination)]
            multiplier = max([z['cost'].get('energy', 1.) for z in state['zones'] if z['geometry'].get('type') == 'axis_aligned_box' and
                              intersects(start, end, z['geometry']['min'], z['geometry']['max'])]+[1.])
            cost = math.dist(start, end)*limits['energy_per_metre']*multiplier
            a['position'] = end
        elif action in ('observe', 'deliver'):
            target = targets[parameters['target_id']]
            if action == 'deliver':
                target['status'] = 'delivered'
                a['resources']['supplies']['value'] -= limits['delivery_supplies']
            elif target.get('status') != 'delivered':
                target['status'] = 'confirmed'
        elif action == 'charge':
            station = next(s for s in state['infrastructure'] if s['id'] == parameters['station_id'])
            resource = a['resources']['energy']
            stock = station['resources']['stock']
            amount = min(limits.get('charging_rate', 0.), resource['maximum']-resource['value'], stock['value'])
            stock['value'] = round(stock['value']-amount, 12)
            resource['value'] = round(resource['value']+amount, 12)
            a['status'] = 'active'; cost = 0.
        resource = a['resources']['energy']
        cost = min(max(0., resource['value']-resource['minimum']), cost*cost_factor)
        resource['value'] = round(resource['value']-cost, 12)
        spent += cost
    for a in state['agents']:
        if a['status'] not in ('active', 'degraded'):
            continue
        resource = a['resources'].get('energy')
        if resource is None:
            continue
        cost = min(max(0., resource['value']-resource['minimum']), idle_cost(a)*cost_factor)
        resource['value'] = round(resource['value']-cost, 12)
        spent += cost
        if resource['value'] <= resource['minimum']:
            a['status'] = 'safe_mode'
    state['time'] += 1.
    for o in state['mission']['objectives']:
        if targets.get(o.get('target_id'), {}).get('status') == 'delivered':
            o['status'] = 'completed'
    state['metrics']['energy_used'] = round(state['metrics'].get('energy_used', 0.)+spent, 12)
    state['metrics']['mission_completion'] = completion(state)
    state['metrics']['step_count'] = state['metrics'].get('step_count', 0)+1
    rebuild_network(state, range_factor)
    return state, checks[0]['rejected_commands']


def intent_commands(observation, intents, step_scale=1., routed=False):
    """Continue a finite intent; newly found objects never enter an existing forecast."""
    commands, claimed = [], set()
    if routed:
        from .public_model import routed_move
        move = routed_move
    else:
        move = move_towards
    agents = {a['id']: a for a in observation['agents']}
    targets = {t['id']: t for t in observation['targets']}
    for identifier, intent in sorted(intents.items()):
        a = agents.get(identifier)
        if not a or a['status'] not in ('active', 'degraded', 'safe_mode') or not a['communication'].get('connected', False):
            continue
        kind, command = intent['kind'], None
        if kind in ('service', 'confirm', 'deliver'):
            target = targets.get(intent.get('target_id'))
            if target is None or target.get('status') == 'delivered' or target['id'] in claimed:
                continue
            claimed.add(target['id'])
            if math.dist(a['position'], target['position']) > motion(a)['interaction_radius']:
                command = move(a, target['position'], observation, step_scale)
            elif target.get('status') != 'confirmed':
                command = {'agent_id': identifier, 'action': 'observe', 'parameters': {'target_id': target['id']}}
            elif kind != 'confirm':
                command = {'agent_id': identifier, 'action': 'deliver', 'parameters': {'target_id': target['id']}}
        elif kind == 'recover':
            station = next((s for s in observation['infrastructure'] if s['id'] == intent.get('station_id')), None)
            if station is not None and a['resources']['energy']['value'] < a['resources']['energy']['minimum']+.45:
                if math.dist(a['position'], station['position']) <= motion(a)['charge_radius']:
                    command = {'agent_id': identifier, 'action': 'charge', 'parameters': {'station_id': station['id']}}
                elif a['status'] != 'safe_mode':
                    command = move(a, station['position'], observation, step_scale)
        elif kind in ('search', 'relay') and intent.get('destination') is not None:
            destination = intent['destination']
            if math.dist(a['position'], destination) > 1.:
                command = move(a, destination, observation, step_scale)
            elif kind == 'relay':
                command = {'agent_id': identifier, 'action': 'relay', 'parameters': {}}
        # Announcements are one-shot rather than sent every predicted tick.
        if command:
            commands.append(command)
    return guard(observation, commands)[0]


def one_step_snapshot(before, after):
    return {'time': after['time'], 'energy_delta': round(after['metrics'].get('energy_used', 0.)-before['metrics'].get('energy_used', 0.), 12),
            'completion': round(completion(after), 9), 'connectivity': round(after['network']['connectivity_score'], 9),
            'positions': {a['id']: a['position'] for a in after['agents'] if a['position'] is not None},
            'resources': {a['id']: a['resources'].get('energy', {}).get('value') for a in after['agents']},
            'agent_statuses': {a['id']: a['status'] for a in after['agents']},
            'known_target_statuses': {t['id']: t.get('status') for t in after['targets'] if t['id'] in {x['id'] for x in before['targets']}}}


class PublicForecaster:
    def rollout(self, observation, decision, intents, footprints, horizon=HORIZON, stress=0., routed=False):
        if not 1 <= horizon <= 12:
            raise ValueError('Forecast horizon must be in [1,12]')
        state, footprints = copy.deepcopy(observation), copy.deepcopy(footprints)
        start_energy, initial_completion = state['metrics'].get('energy_used', 0.), completion(state)
        unknown = state['observation_quality']['unknown_state_ratio'] > 0.
        curves, first, information, discounted = [], None, 0., 0.
        stopped = decision['operation'] == 'safe_stop'
        rejected_total = 0
        confidence = decision['explanation']['confidence']
        for step in range(horizon):
            commands = decision['commands'] if step == 0 else intent_commands(state, intents, decision['selected_configuration']['parameters'].get('step_scale', 1.), routed=routed)
            if stopped:
                commands = []
            before_completion = completion(state)
            before = state
            state, rejected = public_step(state, commands, speed_factor=1.-.25*stress,
                                           cost_factor=1.+.5*stress, range_factor=1.-.1*stress)
            rejected_total += len(rejected)
            if first is None:
                first = one_step_snapshot(observation, state)
            for a in state['agents']:
                if a['position'] is not None and a['communication'].get('connected', False) and 'observe' in actions(a) and motion(a):
                    information += information_gain(a, a['position'], footprints) / max(1, len(intents))
            add_footprints(footprints, state)
            gain = completion(state)-before_completion
            discounted += gain*(.95**step)
            curves.append({'step': step+1, 'completion': round(completion(state), 9),
                           'energy': round(state['metrics'].get('energy_used', 0.)-start_energy, 9),
                           'connectivity': round(state['network']['connectivity_score'], 9),
                           'information_proxy': round(information if unknown else 0., 9)})
        energy = state['metrics'].get('energy_used', 0.)-start_energy
        exhausted = sum(a['resources'].get('energy', {}).get('value', 1.) <= a['resources'].get('energy', {}).get('minimum', 0.)
                        for a in state['agents'] if a['status'] not in ('failed', 'offline'))
        score = (WEIGHTS['completion']*discounted + WEIGHTS['information']*min(2., information)*confidence*unknown
                 - WEIGHTS['energy']*energy - WEIGHTS['reserve']*exhausted
                 - WEIGHTS['stopped']*stopped)
        return {'model': MODEL_VERSION, 'horizon': horizon, 'score': round(score, 9),
                'known_completion_gain': round(completion(state)-initial_completion, 9),
                'energy': round(energy, 9), 'information_proxy': round(min(2., information) if unknown else 0., 9),
                'rejected_future_commands': rejected_total, 'curve': curves, 'one_step': first}


class Calibration:
    """Prequential chosen-action residuals, not an oracle for rejected alternatives."""
    def __init__(self):
        self.samples = 0
        self.errors = {'energy': 0., 'completion': 0., 'connectivity': 0., 'position': 0., 'state': 0., 'resource': 0.}
        self.energy_residuals = []
        self.interval_hits = 0

    def summary(self):
        radius = .01
        if self.energy_residuals:
            values = sorted(abs(x) for x in self.energy_residuals)
            radius = max(.001, values[min(len(values)-1, math.ceil(.9*len(values))-1)])
        trust = 1. / (1.+10.*self.errors['energy']+2.*self.errors['completion']+self.errors['connectivity']+.5*self.errors['position']+2.*self.errors['state']+5.*self.errors['resource'])
        return {'samples': self.samples, 'ewma_absolute_errors': {k: round(v, 9) for k,v in self.errors.items()},
                'trust': round(trust, 9), 'energy_error_radius': round(radius, 9),
                'energy_interval_hits': self.interval_hits,
                'interval_label': 'empirical_residual_envelope_not_statistical_guarantee'}

    def settle(self, pending, observation):
        if observation['episode_id'] != pending['episode_id'] or observation['time'] != pending['prediction']['time']:
            return {'status': 'not_comparable', 'reason': 'episode_or_time_mismatch'}
        prediction = pending['prediction']
        actual_energy = observation['metrics'].get('energy_used', 0.)-pending['energy_before']
        actual_completion = completion(observation)
        actual_positions = {a['id']: a['position'] for a in observation['agents'] if a['position'] is not None}
        distances = [math.dist(p, actual_positions[i]) for i,p in prediction['positions'].items() if i in actual_positions]
        position_error = math.sqrt(sum(d*d for d in distances)/max(1, len(distances)))
        actual_agents = {a['id']: a for a in observation['agents']}
        actual_targets = {t['id']: t for t in observation['targets']}
        state_checks = [actual_agents[i]['status'] != value for i,value in prediction.get('agent_statuses', {}).items() if i in actual_agents]
        state_checks += [actual_targets[i].get('status') != value for i,value in prediction['known_target_statuses'].items() if i in actual_targets]
        resource_errors = [abs(actual_agents[i]['resources'].get('energy', {}).get('value', value)-value)
                           for i,value in prediction.get('resources', {}).items() if i in actual_agents and value is not None]
        residuals = {'energy': actual_energy-prediction['energy_delta'],
                     'completion': actual_completion-prediction['completion'],
                     'connectivity': observation['network']['connectivity_score']-prediction['connectivity'],
                     'position': position_error, 'state': sum(state_checks)/max(1, len(state_checks)),
                     'resource': sum(resource_errors)/max(1, len(resource_errors))}
        for key, value in residuals.items():
            self.errors[key] = abs(value) if self.samples == 0 else .8*self.errors[key]+.2*abs(value)
        self.samples += 1
        self.energy_residuals.append(residuals['energy']); del self.energy_residuals[:-64]
        lower, upper = pending['energy_interval']
        hit = lower-1e-9 <= actual_energy <= upper+1e-9
        self.interval_hits += hit
        old_ids = set(prediction['known_target_statuses'])
        return {'status': 'compared', 'decision_id': pending['decision_id'], 'candidate_id': pending['candidate_id'],
                'time': observation['time'], 'actual_energy_delta': round(actual_energy, 12),
                'actual_completion': round(actual_completion, 9), 'energy_interval_hit': hit,
                'new_targets_not_predicted': len({t['id'] for t in observation['targets']}-old_ids),
                'residuals': {k: round(v, 9) for k,v in residuals.items()}, 'updated_calibration': self.summary()}
