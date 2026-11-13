"""Bounded alternative policies and intent extraction from public observations."""
import copy
import math
from functools import lru_cache
from .contracts import canonical
from .metacontroller import MetaController, Planner, available, plan
from .public_model import actions, blocked, energy_cost, motion, reachable

POLICIES = ('meta', 'frontier', 'nearby', 'reserve')
STATE_FIELDS = ('beliefs', 'visited', 'pending_cells', 'episode', 'last_time', 'cached_key', 'cached_decision')


def clone_policy(source, variant, footprints):
    result = PolicyController(variant, footprints)
    if source:
        for name in STATE_FIELDS:
            setattr(result, name, copy.deepcopy(getattr(source, name)))
    return result


def add_footprints(footprints, observation):
    for a in sorted(observation['agents'], key=lambda a: a['id']):
        if available(a) and a['position'] is not None and 'observe' in actions(a) and motion(a):
            item = (a['kind'], tuple(a['position']), motion(a).get('sensor_radius', 0.))
            if item not in footprints:
                footprints.append(item)
    # Explicit bounded memory, recent coverage rather than a claim of complete mapping.
    del footprints[:-512]


def information_gain(agent, point, footprints):
    limits=motion(agent)
    if not limits:return 0.
    return _information_gain(agent['kind'],tuple(point),tuple(limits['min']),tuple(limits['max']),
                             limits.get('sensor_radius',0.),tuple(footprints))


@lru_cache(maxsize=4096)
def _information_gain(kind,point,lower,upper,radius,footprints):
    if radius<=0:return 0.
    relevant=[(position,reach) for category,position,reach in reversed(footprints)
              if category==kind and math.dist(point,position)<=radius+reach+1e-9]
    samples=new=0
    for ix in range(-2,3):
        for iy in range(-2,3):
            p=[point[0]+ix*radius/2.,point[1]+iy*radius/2.,point[2]]
            if math.dist(point,p)>radius+1e-9 or not all(lo<=x<=hi for x,lo,hi in zip(p,lower,upper)):continue
            samples+=1
            if not any(math.dist(position,p)<=reach+1e-9 for position,reach in relevant):new+=1
    return new/max(1,samples)


class ForecastPlanner(Planner):
    def __init__(self, observation, belief, visited, scale, variant, footprints, pending_cells=None):
        super().__init__(observation, belief, visited, scale)
        self.variant, self.footprints = variant, footprints
        self.intents = {}
        self.pending_cells = pending_cells or {}

    def remember(self, output, kind):
        agents = {a['id']: a for a in self.agents}
        bids = {b['agent_id']: b for b in output['bids'] if b.get('selected')}
        for command in output['commands']:
            a = agents[command['agent_id']]
            bid = bids.get(a['id'], {})
            intent = {'kind': kind, 'agent_id': a['id']}
            if kind in ('service', 'confirm', 'deliver'):
                intent['target_id'] = bid.get('task_id', command['parameters'].get('target_id'))
                intent['mode'] = kind
            elif kind in ('search', 'relay'):
                intent['destination'] = bid.get('destination', a['position'])
            elif kind == 'recover':
                intent['station_id'] = bid.get('task_id', command['parameters'].get('station_id'))
            else:
                intent['command'] = copy.deepcopy(command)
            self.intents[canonical(command)] = intent
        return output

    def service(self, context, mode='all'):
        output = super().service(context, mode)
        if self.variant in ('nearby', 'reserve'):
            by_agent = {a['id']: a for a in self.agents}
            targets = {t['id']: t for t in self.o['targets']}
            for bid in output['bids']:
                bid['selected'] = False
            used, assigned = set(), set()
            output['commands'], output['roles'], output['utility'] = [], {}, 0.
            def ranking(bid):
                a = by_agent[bid['agent_id']]
                speed = motion(a)['speed']*(motion(a).get('degraded_speed_factor', .5) if a['status'] == 'degraded' else 1.)
                steps = math.ceil(max(0., bid['distance']-motion(a)['interaction_radius']) / max(.001, speed))
                # A distinct finite strategy: finish a nearby positive-utility task first.
                return (steps, -targets[bid['task_id']].get('priority', 1.), -bid['utility'], a['id'], bid['task_id'])
            for bid in sorted(output['bids'], key=ranking):
                a, t = by_agent[bid['agent_id']], targets[bid['task_id']]
                if bid['utility'] <= 0 or a['id'] in used or t['id'] in assigned:
                    continue
                confident = self.belief['confidence'] >= .55 or t['id'] in self.belief['verified_targets']
                if math.dist(a['position'], t['position']) > motion(a)['interaction_radius']:
                    command = self.move(a, t['position'])
                else:
                    action = 'deliver' if t.get('status') == 'confirmed' and confident and mode != 'confirm' else 'observe'
                    command = {'agent_id': a['id'], 'action': action, 'parameters': {'target_id': t['id']}}
                if command:
                    bid['selected'] = True
                    bid['ranking_strategy'] = 'nearest_positive_bid'
                    used.add(a['id']); assigned.add(t['id'])
                    output['commands'].append(command)
                    output['roles'][a['id']] = 'verifier' if command['action'] == 'observe' else 'executor'
                    output['utility'] += bid['utility']
        return self.remember(output, 'service' if mode == 'all' else mode)

    def search(self, context):
        if self.variant == 'meta':
            return self.remember(super().search(context), 'search')
        output, assigned = plan(), set()
        for a in self.agents:
            limits = motion(a)
            if not available(a) or not limits or not {'move', 'observe'} <= actions(a).keys():
                continue
            radius = limits.get('sensor_radius', 12.)
            candidates = []
            pending = self.pending_cells.get(a['id'])
            destinations = []
            if pending and math.dist(a['position'], pending[1]) > 1. and not blocked(a['position'], pending[1], self.o):
                destinations.append(list(pending[1]))
            else:
                for axis in (0, 1):
                    for sign in (1., -1.):
                        destination = list(a['position'])
                        destination[axis] = max(limits['min'][axis], min(limits['max'][axis], destination[axis]+sign*radius))
                        destinations.append(destination)
            for destination in destinations:
                key = (a['kind'], tuple(destination))
                if key in assigned or blocked(a['position'], destination, self.o):
                    continue
                command = self.move(a, destination)
                if command is None:
                    continue
                gain = information_gain(a, destination, self.footprints)
                cost = energy_cost(a, command, self.o)
                utility = 10.*gain*self.belief['confidence']-.05*math.dist(a['position'], destination)-2.*cost
                candidates.append((utility, destination, command, key, gain))
            if candidates:
                utility, destination, command, key, gain = min(candidates, key=lambda x: (-x[0], x[1][1], x[1][0], x[1][2]))
                if utility > 0:
                    assigned.add(key)
                    output['commands'].append(command); output['roles'][a['id']] = 'scout'
                    output['utility'] += utility
                    output['bids'].append({'agent_id': a['id'], 'task_id': 'frontier:'+canonical(destination),
                                           'destination': destination, 'utility': round(utility, 6),
                                           'information_proxy': round(gain, 6), 'selected': True})
        return self.remember(output, 'search')

    def recover(self, context):
        return self.remember(super().recover(context), 'recover')

    def relay(self, context):
        return self.remember(super().relay(context), 'relay')

    def coordinate(self, context):
        return self.remember(super().coordinate(context), 'coordinate')


class PolicyController(MetaController):
    def __init__(self, variant='meta', footprints=None):
        super().__init__()
        if variant not in POLICIES:
            raise ValueError('Unknown forecast policy')
        self.variant = variant
        self.footprints = copy.deepcopy(footprints or [])
        self.forecast_planner = None

    def make_planner(self, observation, belief, visited, scale):
        self.forecast_planner = ForecastPlanner(observation, belief, visited, scale, self.variant, self.footprints, self.pending_cells)
        return self.forecast_planner

    def recovery_threshold(self, agent, recovering, observation):
        threshold = super().recovery_threshold(agent, recovering, observation)
        if self.variant != 'reserve' or not motion(agent) or agent['position'] is None or 'charge' not in actions(agent):
            return threshold
        limits = motion(agent)
        tasks = [t for t in observation['targets'] if t.get('status') != 'delivered' and reachable(agent, t['position'])]
        stations = [s for s in observation['infrastructure'] if s['kind'] == 'charging_station' and s['status'] == 'active' and s['resources'].get('stock', {}).get('value', 0.) > 0. and reachable(agent, s['position'])]
        if not tasks or not stations:
            return threshold
        t = min(tasks, key=lambda t: math.dist(agent['position'], t['position']))
        travel = math.dist(agent['position'], t['position'])
        return_trip = min(math.dist(t['position'], s['position']) for s in stations)
        budget = (travel+return_trip)*limits['energy_per_metre'] + .02
        return min(agent['resources']['energy']['maximum']-.05,
                   max(threshold, agent['resources']['energy']['minimum']+budget))

    def decide(self, observation, previous=None, parameters=None):
        decision = super().decide(observation, previous, parameters)
        for command in decision['commands']:
            if decision['ariadna_meta']['command_owners'].get(command['agent_id']) not in ('search', 'coverage_search'):
                self.pending_cells.pop(command['agent_id'], None)
        return decision

    def intents_for(self, decision):
        if self.forecast_planner is None:
            return {}
        return {c['agent_id']: copy.deepcopy(self.forecast_planner.intents.get(canonical(c),
                    {'kind': 'one_shot', 'agent_id': c['agent_id'], 'command': c})) for c in decision['commands']}
