"""Executable library, bounded DAG synthesis and safety arbitration over public JSON."""
import copy
import hashlib
import math

from .beliefs import Beliefs
from .contracts import canonical, validate
from .controller import Controller
from .public_model import actions, blocked, energy_cost, guard, motion, move_towards, reachable
from .scenarios import LIBRARY, synthesize, validate_graph


def available(agent):
    return agent['status'] in ('active', 'degraded') and agent['communication'].get('connected', False)


def plan():
    return {'commands': [], 'roles': {}, 'bids': [], 'utility': 0.}


class Planner:
    def __init__(self, observation, belief, visited, step_scale=1.):
        self.o, self.belief, self.visited, self.scale = observation, belief, visited, step_scale
        self.agents = sorted(observation['agents'], key=lambda a: a['id'])

    def move(self, agent, destination):
        return move_towards(agent, destination, self.o, self.scale)

    def service(self, context, mode='all'):
        result, edges = plan(), []
        directive_targets = context['directive_targets']
        for a in self.agents:
            if not available(a) or a['position'] is None:
                continue
            for t in self.o['targets']:
                if t.get('status') == 'delivered' or not isinstance(t.get('position'), list) or not reachable(a, t['position']):
                    continue
                if blocked(t['position'], t['position'], self.o):
                    continue
                if directive_targets and t['id'] not in directive_targets:
                    continue
                if not {'move', 'observe'} <= actions(a).keys():
                    continue
                if 'deliver' not in actions(a):
                    continue
                if a['resources'].get('supplies', {}).get('value', 0.) < motion(a).get('delivery_supplies', 0.):
                    continue
                confident = self.belief['confidence'] >= .55 or t['id'] in self.belief['verified_targets']
                status = t.get('status')
                distance = math.dist(a['position'], t['position'])
                action = 'move' if distance > motion(a)['interaction_radius'] else ('deliver' if status == 'confirmed' and confident and mode != 'confirm' else 'observe')
                if mode == 'deliver' and (status != 'confirmed' or not confident):
                    continue
                if mode == 'confirm' and status == 'confirmed' and confident:
                    continue
                command = self.move(a, t['position']) if action == 'move' else {'agent_id': a['id'], 'action': action, 'parameters': {'target_id': t['id']}}
                if command is None:
                    continue
                cost = energy_cost(a, command, self.o)
                if cost is None:
                    continue
                w = LIBRARY['priority_service'].weights
                confidence = 1. if t['id'] in self.belief['verified_targets'] else self.belief['confidence']
                reliability = self.belief['agent_reliability'].get(a['id'], .5)
                utility = w['priority']*t.get('priority', 1.)*confidence*(.5+.5*reliability)-w['distance']*distance-w['energy']*cost
                edges.append((utility, a['id'], t['id'], command, cost, distance))
        # Feasible positive marginal allocation in descending utility; one exclusive target per agent.
        assigned, goals = set(), set()
        for utility, agent_id, target_id, command, cost, distance in sorted(edges, key=lambda x: (-x[0], x[1], x[2])):
            chosen = utility > 0 and agent_id not in assigned and target_id not in goals
            result['bids'].append({'agent_id': agent_id, 'task_id': target_id, 'utility': round(utility, 6),
                                   'energy_cost': round(cost, 6), 'distance': round(distance, 6),
                                   'agent_reliability': self.belief['agent_reliability'].get(agent_id, .5), 'selected': chosen})
            if chosen:
                assigned.add(agent_id); goals.add(target_id)
                result['commands'].append(command)
                result['roles'][agent_id] = 'verifier' if command['action'] == 'observe' else 'executor'
                result['utility'] += utility
        return result

    def search(self, context):
        result, occupied = plan(), set()
        for a in self.agents:
            limits = motion(a)
            if not available(a) or limits is None or not {'move', 'observe'} <= actions(a).keys():
                continue
            # Search grid derived from publicly declared bounds and sensor radius.
            spacing = limits.get('sensor_radius', 12.)
            points = []
            for axis in (0, 1):
                low, high = limits['min'][axis], limits['max'][axis]
                values = []
                value = low + min(spacing, (high-low)/2.)
                while value < high and len(values) < 20:
                    values.append(value); value += spacing
                if not values:
                    values = [low]
                points.append(values)
            altitude = a['position'][2]
            for x in points[0]:
                for y in points[1]:
                    point = [x, y, altitude]
                    key = (a['kind'], tuple(point))
                    if key in occupied or key in self.visited or blocked(a['position'], point, self.o):
                        continue
                    distance = math.dist(a['position'], point)
                    if distance < 1.:
                        continue
                    w = LIBRARY['coverage_search'].weights
                    utility = w['new_cell']*self.belief['confidence'] - w['distance']*distance
                    command = self.move(a, point)
                    if command:
                        cost = energy_cost(a, command, self.o)
                        utility -= w['energy']*cost
                        candidates = (utility, tuple(point), command, key)
                        result.setdefault('_choices', []).append(candidates)
            choices = result.pop('_choices', [])
            if choices:
                utility, point, command, key = min(choices, key=lambda x: (-x[0], (x[1][1], x[1][0], x[1][2])))
                if utility > 0:
                    occupied.add(key)
                    result['commands'].append(command); result['roles'][a['id']] = 'scout'
                    result['bids'].append({'agent_id': a['id'], 'task_id': 'cell:'+canonical(list(point)), 'destination': list(point), 'utility': round(utility, 6), 'selected': True})
                    result['utility'] += utility
        return result

    def recover(self, context):
        result = plan()
        for a in self.agents:
            resource = a['resources'].get('energy', {})
            if a['id'] not in context['recovering_ids']:
                continue
            if a['status'] not in ('active', 'degraded', 'safe_mode') or not a['communication'].get('connected', False):
                continue
            result['roles'][a['id']] = 'holding'
            if a['position'] is None or 'charge' not in actions(a) or motion(a) is None:
                continue
            stations = [s for s in self.o['infrastructure'] if s['kind'] == 'charging_station' and s['status'] == 'active' and s['resources'].get('stock', {}).get('value', 0.) > 0 and reachable(a, s['position'])]
            for station in sorted(stations, key=lambda s: (math.dist(a['position'], s['position']), s['id'])):
                distance = math.dist(a['position'], station['position'])
                if distance <= motion(a)['charge_radius']:
                    command = {'agent_id': a['id'], 'action': 'charge', 'parameters': {'station_id': station['id']}}
                elif a['status'] != 'safe_mode':
                    # Require enough energy for the entire known return route and reserve.
                    need = distance*motion(a)['energy_per_metre'] + .01
                    if resource['value']-need < resource['minimum'] or blocked(a['position'], station['position'], self.o):
                        continue
                    command = self.move(a, station['position'])
                else:
                    continue
                if command:
                    utility = 30.-.05*distance
                    result['commands'].append(command)
                    result['roles'][a['id']] = 'charging' if command['action'] == 'charge' else 'returning'
                    result['bids'].append({'agent_id': a['id'], 'task_id': station['id'], 'utility': utility, 'selected': True})
                    result['utility'] += utility
                    break
        return result

    def relay(self, context):
        result = plan()
        disconnected = [a for a in self.agents if a['status'] in ('active', 'degraded') and not a['communication'].get('connected', False) and a['position'] is not None]
        link_range = self.o['network'].get('link_range')
        if not disconnected:
            for identifier in sorted(context['critical_relays']):
                a = next(a for a in self.agents if a['id'] == identifier)
                command = {'agent_id': identifier, 'action': 'relay', 'parameters': {}}
                result['commands'].append(command)
                result['roles'][identifier] = 'relay'
                result['utility'] += 15.
                result['bids'].append({'agent_id': identifier, 'task_id': 'maintain_connected_coalition', 'utility': 15., 'selected': True})
            return result
        if not isinstance(link_range, (int, float)):
            return result
        candidates = []
        for a in self.agents:
            if not available(a) or 'relay' not in actions(a) or motion(a) is None:
                continue
            anchors = [n for n in self.agents+self.o['infrastructure'] if n['id'] != a['id'] and n['status'] in ('active', 'degraded') and n['communication'].get('connected', False) and 'relay' in n['capabilities'] and n['position'] is not None]
            for beneficiary in disconnected:
                for anchor in anchors:
                    destination = [(x+y)/2. for x,y in zip(anchor['position'], beneficiary['position'])]
                    destination = [max(lo, min(hi, value)) for value, lo, hi in zip(destination, motion(a)['min'], motion(a)['max'])]
                    if math.dist(destination, anchor['position']) > link_range or math.dist(destination, beneficiary['position']) > link_range:
                        continue
                    command = self.move(a, destination)
                    if command is None:
                        command = {'agent_id': a['id'], 'action': 'relay', 'parameters': {}}
                    distance = math.dist(a['position'], destination)
                    cost = energy_cost(a, command, self.o)
                    if cost is None:
                        continue
                    utility = 15.-.05*distance-2.*cost
                    candidates.append((utility, a['id'], beneficiary['id'], anchor['id'], command, destination))
        if candidates:
            utility, identifier, beneficiary, anchor, command, destination = min(candidates, key=lambda c: (-c[0], c[1:4]))
            if utility > 0:
                result['commands'] = [command]
                result['roles'] = {identifier: 'relay', beneficiary: 'beneficiary'}
                result['utility'] = utility
                result['bids'] = [{'agent_id': identifier, 'task_id': beneficiary, 'anchor': anchor,
                                   'utility': round(utility, 6), 'selected': True, 'destination': destination}]
        return result

    def coordinate(self, context):
        result = plan()
        leader = context['leader']
        if leader is None:
            return result
        result['roles'][leader['id']] = 'coordinator'
        peers = [a for a in self.agents if a['id'] != leader['id'] and available(a)]
        for peer in peers:
            if public_route(self.o, leader['id'], peer['id']):
                result['commands'] = [{'agent_id': leader['id'], 'action': 'send_message', 'parameters': {
                    'recipient_id': peer['id'], 'payload': {'type': 'coordination_announcement', 'leader_id': leader['id'],
                                                             'configuration_epoch': context['epoch']}}}]
                break
        result['utility'] = context['leader_utility']
        result['bids'] = [{'agent_id': leader['id'], 'task_id': 'coordinator', 'utility': result['utility'], 'selected': True}]
        return result


def public_route(observation, source, target, exclude=()):
    nodes = {a['id']: a for a in observation['agents']+observation['infrastructure'] if a['id'] not in exclude}
    if source not in nodes or target not in nodes:
        return False
    graph = {key: [] for key in nodes}
    for link in observation['network']['known_links']:
        u, v = link.get('source'), link.get('target')
        if u in graph and v in graph:
            graph[u].append(v); graph[v].append(u)
    queue, seen = [source], {source}
    while queue:
        current = queue.pop(0)
        if current == target:
            return True
        if current != source and 'relay' not in nodes.get(current, {}).get('capabilities', []):
            continue
        for other in sorted(graph.get(current, [])):
            if other not in seen:
                seen.add(other); queue.append(other)
    return False


class MetaController(Controller):
    audit_profile = 'ariadna.meta.v3'
    mission_parameters = {'profile': 'rescue_v2', 'max_steps': 100}

    def __init__(self, log_path=None):
        super().__init__(log_path)
        self.beliefs = Beliefs()
        self.visited = set()
        self.pending_cells = {}
        self.episode = None
        self.last_time = -1
        self.cached_key = None
        self.cached_decision = None

    def health(self):
        result = super().health()
        result.update(controller_id='ariadna_meta', profile='ariadna.meta.v3', scenario_ids=list(LIBRARY))
        return result

    def check_commands(self, observation, commands):
        return guard(observation, commands)

    def make_planner(self, observation, belief, visited, scale):
        return Planner(observation, belief, visited, scale)

    def recovery_threshold(self, agent, recovering, observation):
        return agent['resources'].get('energy', {}).get('minimum', 0.) + (.45 if agent['id'] in recovering else .12)

    def decide(self, observation, previous=None, parameters=None):
        validate('observation', observation)
        previous = copy.deepcopy(previous or {'scenario_ids': [], 'role_assignments': {}})
        parameters = copy.deepcopy(parameters or {})
        key = canonical([observation, previous, parameters])
        if key == self.cached_key:
            return copy.deepcopy(self.cached_decision)
        if self.episode != observation['episode_id'] or observation['time'] < self.last_time:
            self.visited.clear(); self.pending_cells.clear(); self.beliefs.reset()
        self.episode, self.last_time = observation['episode_id'], observation['time']
        for a in observation['agents']:
            cell = self.pending_cells.get(a['id'])
            if cell and a['position'] is not None and math.dist(a['position'], cell[1]) < 1.:
                self.visited.add((cell[0], tuple(cell[1])))
        belief = self.beliefs.update(observation)
        active = [a for a in observation['agents'] if available(a)]
        degrees = {a['id']: sum(a['id'] in (l.get('source'), l.get('target')) for l in observation['network']['known_links']) for a in active}
        leaders = [a for a in active if 'send_message' in actions(a)]
        def leadership(a):
            reliability = belief['source_reputation'].get(a['id'], .5)
            return 10.*reliability + 5.*a['resources'].get('energy', {}).get('value', 0.) + degrees[a['id']]
        leader = min(leaders, key=lambda a: (-leadership(a), a['id'])) if leaders else None
        old_leader = parameters.get('leader_id')
        incumbent = next((a for a in leaders if a['id'] == old_leader), None)
        if incumbent and leader and (leadership(incumbent) >= leadership(leader)-3. or observation['time']-parameters.get('leader_epoch', 0.) < 3.):
            leader = incumbent
        directives, conflicts, directive_targets, hard_stop = [], [], [], False
        target_ids = {t['id'] for t in observation['targets'] if t.get('status') != 'delivered'}
        for directive in observation['mission']['directives']:
            directive_id = directive.get('id', 'directive_'+hashlib.sha256(canonical(directive).encode()).hexdigest()[:16])
            kind = directive.get('type', directive.get('action'))
            if kind in ('stop', 'safe_stop'):
                hard_stop = True; directives.append(directive_id)
            elif kind == 'prioritize_target':
                if directive.get('target_id') in target_ids:
                    directive_targets.append(directive['target_id']); directives.append(directive_id)
                else:
                    conflicts.append({'directive_id': directive.get('id'), 'reason': 'unknown_or_completed_target'})
            elif kind is not None:
                conflicts.append({'directive_id': directive.get('id'), 'reason': 'unsupported_directive_semantics'})
                hard_stop = True
        if len(set(directive_targets)) > 1:
            conflicts.append({'reason': 'conflicting_exclusive_priorities', 'target_ids': sorted(set(directive_targets))})
            hard_stop = True
        searchers = [a for a in active if motion(a) and {'move', 'observe'} <= actions(a).keys()]
        pairs = [(a, t) for a in searchers for t in observation['targets'] if t.get('status') != 'delivered' and isinstance(t.get('position'), list) and reachable(a, t['position']) and 'deliver' in actions(a)]
        recovering = set(parameters.get('recovering_ids', []))
        endangered = []
        for a in observation['agents']:
            resource = a['resources'].get('energy', {})
            if a['status'] not in ('active', 'degraded', 'safe_mode'):
                continue
            threshold = self.recovery_threshold(a, recovering, observation)
            if resource.get('value', 1.) < threshold or resource.get('value', 1.) <= resource.get('minimum', 0.):
                endangered.append(a)
        recovering = {a['id'] for a in endangered}
        roots = [n for n in observation['infrastructure'] if n['kind'] == 'base_station' and n['status'] == 'active']
        critical_relays = set()
        for a in active:
            if motion(a) is None or 'relay' not in actions(a) or not roots:
                continue
            if any(peer['id'] != a['id'] and peer['position'] is not None and not public_route(observation, roots[0]['id'], peer['id'], exclude=(a['id'],)) for peer in active):
                critical_relays.add(a['id'])
        features = {'critical_relays': len(critical_relays), 'searchers': len(searchers), 'service_pairs': len(pairs),
                    'disconnected': sum(a['status'] in ('active', 'degraded') and not a['communication'].get('connected', False) for a in observation['agents']),
                    'relays': sum('relay' in actions(a) and motion(a) is not None for a in active),
                    'endangered': len(endangered), 'leaders': len(leaders),
                    'leader_change': old_leader is not None and (leader is None or old_leader != leader['id']),
                    'hard_stop': hard_stop}
        context = {'features': features, 'directive_targets': directive_targets, 'recovering_ids': recovering, 'critical_relays': critical_relays, 'leader': leader,
                   'leader_utility': leadership(leader) if leader else 0., 'epoch': observation['time']}
        scale = .5 if belief['confidence'] < .55 else 1.
        planner = self.make_planner(observation, belief, self.visited, scale)
        plans, evaluations = {}, []
        for identifier, scenario in LIBRARY.items():
            applicable = scenario.applicable(context)
            output = scenario.execute(planner, context) if applicable else plan()
            plans[identifier] = output
            evaluations.append({'scenario_id': identifier, 'applicable': applicable, 'utility': round(output['utility'], 6),
                                'risk': round(1.-belief['confidence'], 6), 'selected': False,
                                'rejected_reason_codes': [] if applicable else ['entry_predicate_false'],
                                'game_evaluation': {'criterion': 'positive_marginal_potential', 'bids': output['bids']}})
        unknown = sum(o.get('status') != 'completed' for o in observation['mission']['objectives']) > len([t for t in observation['targets'] if t.get('status') != 'delivered'])
        selected = []
        for identifier in ('safe_degradation', 'relay_coalition', 'coordination_reconfiguration', 'priority_service', 'coverage_search'):
            if not LIBRARY[identifier].applicable(context):
                continue
            if identifier == 'coverage_search' and pairs and not unknown:
                continue
            if plans[identifier]['commands'] or plans[identifier]['roles']:
                selected.append(identifier)
        definition = None
        needs_synthesis = bool(pairs) and belief['confidence'] < .55 and bool(features['endangered'] or features['disconnected'])
        execution, graph_states = [], []
        if needs_synthesis:
            nodes = []
            if features['endangered']:
                nodes.append({'id': 'recover', 'primitive': 'recover', 'requires': []})
            if features['disconnected']:
                nodes.append({'id': 'relay', 'primitive': 'relay', 'requires': []})
            if features['leader_change']:
                nodes.append({'id': 'coordinate', 'primitive': 'coordinate', 'requires': []})
            nodes.extend([{'id': 'confirm', 'primitive': 'confirm', 'requires': ['relay'] if features['disconnected'] else []},
                          {'id': 'deliver', 'primitive': 'deliver', 'requires': ['confirm']}])
            if unknown:
                nodes.append({'id': 'search', 'primitive': 'search', 'requires': []})
            definition = synthesize(nodes)
        elif previous['scenario_ids'] and parameters.get('synthesized_definition'):
            # Continue an emitted DAG until its dependent tasks finish or a hard constraint intervenes.
            if pairs or features['endangered'] or features['disconnected']:
                definition = copy.deepcopy(parameters['synthesized_definition'])
        if definition:
            validate_graph(definition)
            states = {}
            pending = [t for t in observation['targets'] if t.get('status') != 'delivered']
            for node in definition['graph']['nodes']:
                primitive = node['primitive']
                done = {'recover': not endangered, 'relay': not features['disconnected'],
                        'confirm': bool(pending) and all(t.get('status') == 'confirmed' and (belief['confidence'] >= .55 or t['id'] in belief['verified_targets']) for t in pending),
                        'deliver': not pending and not unknown, 'search': not unknown,
                        'coordinate': not features['leader_change']}[primitive]
                ready = all(states[d] == 'completed' for d in node.get('requires', []))
                state = 'completed' if done else ('running' if ready else 'waiting')
                states[node['id']] = state
                graph_states.append({'node_id': node['id'], 'primitive': primitive, 'status': state})
                if state == 'running':
                    output = planner.service(context, primitive) if primitive in ('confirm', 'deliver') else getattr(planner, primitive)(context)
                    execution.append((node['id'], output))
            ids = [definition['id']]
        else:
            execution = [(identifier, plans[identifier]) for identifier in selected]
            ids = selected
        commands, roles, owners = [], {}, {}
        # Emergency holding owns the agent even when no charging/return action is feasible.
        reserved = set(plans['safe_degradation']['roles'])
        for identifier, output in execution:
            for agent_id, role in output['roles'].items():
                if agent_id not in roles and (agent_id not in reserved or identifier in ('safe_degradation', 'recover')):
                    roles[agent_id] = role
            for command in output['commands']:
                agent_id = command['agent_id']
                if agent_id in owners or (agent_id in reserved and identifier not in ('safe_degradation', 'recover')):
                    continue
                owners[agent_id] = identifier
                commands.append(command)
        if leader:
            roles[leader['id']] = roles.get(leader['id'], 'coordinator')
        commands, checks = self.check_commands(observation, commands)
        # A directive is feasible only if at least one safe command can serve its target.
        if directive_targets and not any(c['parameters'].get('target_id') in directive_targets or owners.get(c['agent_id']) in ('priority_service', 'confirm', 'deliver') for c in commands):
            conflicts.append({'reason': 'priority_target_has_no_safe_executor', 'target_ids': directive_targets})
            hard_stop = True
        new_parameters = {'leader_id': leader['id'] if leader else None,
                          'leader_epoch': parameters.get('leader_epoch', observation['time']) if leader and leader['id'] == old_leader else observation['time'], 'step_scale': scale,
                          'allocation': copy.deepcopy(roles), 'directive_targets': sorted(directive_targets),
                          'recovering_ids': sorted(recovering)}
        if definition:
            new_parameters['synthesized_definition'] = definition
        if hard_stop or not commands:
            operation = 'safe_stop'
            commands = []
            ids = previous['scenario_ids']
            roles = previous['role_assignments']
            new_parameters = parameters
            definition = None
        elif definition and ids != previous['scenario_ids']:
            operation = 'synthesize'
        elif ids == previous['scenario_ids']:
            operation = 'keep' if new_parameters == parameters and roles == previous['role_assignments'] else 'modify'
        elif len(ids) > 1:
            operation = 'compose'
        else:
            operation = 'select' if not previous['scenario_ids'] else 'switch'
        for candidate in evaluations:
            candidate['selected'] = candidate['scenario_id'] in ids
            if not candidate['selected'] and not candidate['rejected_reason_codes']:
                identifier = candidate['scenario_id']
                if definition:
                    candidate['rejected_reason_codes'] = ['evaluated_as_synthesis_primitive']
                elif not plans[identifier]['commands'] and not plans[identifier]['roles']:
                    candidate['rejected_reason_codes'] = ['no_feasible_positive_bid']
                else:
                    candidate['rejected_reason_codes'] = ['not_needed_or_superseded']
        if definition:
            evaluations.append({'scenario_id': definition['id'], 'applicable': True, 'selected': True,
                                'utility': round(sum(output['utility'] for _, output in execution), 6),
                                'risk': round(1.-belief['confidence'], 6), 'rejected_reason_codes': []})
        digest = hashlib.sha256(canonical(observation).encode()).hexdigest()
        reasons = [operation, 'public_observation_only', 'game_utility_allocation']
        if belief['confidence'] < .55:
            reasons.append('verify_before_delivery')
        if conflicts:
            reasons.append('operator_directive_conflict')
        if checks[0]['rejected_commands']:
            reasons.append('unsafe_commands_filtered')
        result = {'protocol_version': '1.0', 'episode_id': observation['episode_id'],
                  'request_id': 'step_'+digest[:24], 'decision_id': 'decision_'+digest[:24],
                  'time': observation['time'], 'operation': operation,
                  'previous_configuration': previous,
                  'selected_configuration': {'scenario_ids': ids, 'parameters': new_parameters, 'synthesized_scenario': definition},
                  'candidate_evaluations': evaluations, 'role_assignments': roles, 'commands': commands,
                  'constraint_checks': checks + [{'constraint_id': 'operator_directives', 'status': 'failed' if conflicts else 'passed', 'conflicts': conflicts}],
                  'explanation': {'observation_refs': ['sha256:'+digest], 'reason_codes': reasons,
                                  'expected_effects': ['execute_checked_tasks'] if commands else ['safe_stop'], 'confidence': belief['confidence']},
                  'ariadna_meta': {'version': '0.3', 'beliefs': belief, 'features': features,
                                   'graph_execution': graph_states, 'command_owners': {c['agent_id']: owners[c['agent_id']] for c in commands},
                                   'accepted_directives': directives}}
        validate('decision', result)
        self.beliefs.issued(commands)
        for identifier, output in execution:
            for bid in output['bids']:
                if bid.get('selected') and bid.get('destination') and owners.get(bid['agent_id']) == identifier and identifier in ('coverage_search', 'search'):
                    kind = next(a['kind'] for a in observation['agents'] if a['id'] == bid['agent_id'])
                    self.pending_cells[bid['agent_id']] = (kind, bid['destination'])
        self.cached_key, self.cached_decision = key, copy.deepcopy(result)
        return result
