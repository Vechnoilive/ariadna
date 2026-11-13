"""Five executable cooperation classes and their machine-readable game models."""
import copy
import hashlib
from .contracts import canonical
from .predicates import comparison, evaluate


SPECS = [
    ('coverage_search', 'Распределённый поиск и покрытие', 'potential', 'search',
     comparison('features.searchers', 'gt', 0), ['scout'], ['move', 'observe'],
     '10*new_cell*confidence - distance*0.05 - energy_cost*2',
     {'new_cell': 10., 'distance': .05, 'energy': 2.}),
    ('priority_service', 'Выполнение приоритетной задачи', 'assignment', 'service',
     comparison('features.service_pairs', 'gt', 0), ['executor', 'verifier'], ['move', 'observe', 'deliver'],
     '20*priority*confidence*(0.5+0.5*agent_reliability) - distance*0.05 - energy_cost*2',
     {'priority': 20., 'distance': .05, 'energy': 2.}),
    ('relay_coalition', 'Временная коалиция ретрансляции', 'coalition', 'relay',
     {'op': 'and', 'args': [{'op': 'or', 'args': [comparison('features.disconnected', 'gt', 0), comparison('features.critical_relays', 'gt', 0)]}, comparison('features.relays', 'gt', 0)]},
     ['relay', 'beneficiary'], ['move', 'relay'],
     '15*newly_connected_members - distance*0.05 - energy_cost*2',
     {'connectivity': 15., 'distance': .05, 'energy': 2.}),
    ('safe_degradation', 'Безопасный режим при деградации', 'constrained', 'recover',
     comparison('features.endangered', 'gt', 0), ['returning', 'charging', 'holding'], ['move', 'charge'],
     '30*recoverable_agents - distance*0.05 - energy_cost*2',
     {'recovery': 30., 'distance': .05, 'energy': 2.}),
    ('coordination_reconfiguration', 'Реконфигурация координации', 'leader_election', 'coordinate',
     {'op': 'and', 'args': [comparison('features.leader_change', 'eq', True), comparison('features.leaders', 'gt', 0)]},
     ['coordinator', 'member'], ['send_message'],
     '10*reliability + 5*energy + degree - reassignment_cost',
     {'reliability': 10., 'energy': 5., 'degree': 1., 'switch': 3.}),
]


class Scenario:
    def __init__(self, spec):
        self.id, self.title, self.game_class, self.executor, self.entry, self.roles, self.actions, self.utility, self.weights = spec

    def applicable(self, context):
        return bool(evaluate(self.entry, context))

    def execute(self, planner, context):
        return getattr(planner, self.executor)(context)

    def declaration(self):
        return {'id': self.id, 'version': '1.0', 'title': self.title,
                'purpose': self.title, 'participants': {'selection': 'public capability and feasible task pairs'},
                'required_capabilities': self.actions,
                'game_model': {'class': self.game_class, 'players': self.roles,
                    'N': 'eligible public agents', 'Ai': self.actions + ['hold'],
                    'Ii': 'public observation and previously received public observations only',
                    'Ui': self.utility, 'utility_weights': self.weights,
                    'K': ['one_command_per_agent', 'reserve', 'space', 'connection', 'directives'],
                    'Theta': ['source_reputation', 'freshness', 'consistency', 'observation_confidence', 'observed_action_reliability'],
                    'E': 'deterministic_positive_marginal_potential_then_safety_filter',
                    'information_structure': 'partial',
                    'stability_criterion': 'positive feasible marginal utility; incumbent coordinator retained within 3 utility units; minimum 3 ticks unless unavailable'},
                'applicability': {'entry': [self.entry], 'continuation': [self.entry],
                    'exit': [{'op': 'not', 'arg': self.entry}],
                    'emergency_exit': [comparison('features.hard_stop', 'eq', True)]},
                'roles': self.roles, 'objectives': [self.title],
                'constraints': ['public_limits_required', 'one_command_per_agent', 'reserve',
                                'swept_collision', 'restricted_zone', 'operator_safety'],
                'allowed_actions': self.actions,
                'execution': {'handler': self.executor, 'arbitration': 'recovery > relay > service > search',
                              'completion': 're-evaluate entry after each public observation',
                              'messages': 'coordination announcements; no remote command injection',
                              'journal': 'observation hash, candidates, utilities, roles, safety, result'},
                'transition_targets': [s[0] for s in SPECS if s[0] != self.id],
                'metrics': ['mission_completion', 'energy_used', 'connectivity_score', 'assignment_utility']}


LIBRARY = {s[0]: Scenario(s) for s in SPECS}


def declarations():
    return [s.declaration() for s in LIBRARY.values()]


def synthesize(nodes):
    """Compile a new bounded DAG from compatible action primitives, never source code."""
    nodes = copy.deepcopy(nodes)
    graph = {'nodes': nodes, 'edges': [[d, n['id']] for n in nodes for d in n.get('requires', [])]}
    digest = hashlib.sha256(canonical(graph).encode()).hexdigest()[:16]
    definition = {'id': 'synth_' + digest, 'version': '1.0', 'title': 'Адаптивная коалиция подтверждения и восстановления',
                  'graph': graph, 'constraints': ['unique_agent_command', 'dependency_success', 'public_safety'],
                  'origin': 'bounded_composition_of_action_primitives'}
    validate_graph(definition)
    return definition


def validate_graph(definition):
    nodes = definition['graph']['nodes']
    if not 1 <= len(nodes) <= 16:
        raise ValueError('Graph size outside [1,16]')
    ids = [n['id'] for n in nodes]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate graph node')
    edges = []
    seen = set()
    for node in nodes:
        if node['primitive'] not in ('recover', 'relay', 'confirm', 'deliver', 'search', 'coordinate'):
            raise ValueError('Unknown graph primitive')
        if any(d not in seen for d in node.get('requires', [])):
            raise ValueError('Graph is not in dependency order')
        edges.extend([[d, node['id']] for d in node.get('requires', [])])
        seen.add(node['id'])
    if edges != definition['graph']['edges']:
        raise ValueError('Edges disagree with dependencies')
    return True
