"""Public evidence, source reputation and outcome feedback, isolated per episode."""
import copy
import hashlib
import math
from .contracts import canonical


class Beliefs:
    def __init__(self):
        self.reset()

    def reset(self):
        self.episode = None
        self.time = -1
        self.digest = None
        self.snapshot = None
        self.sources = {}
        self.agents = {}
        self.seen = set()
        self.verified = set()
        self.previous = None
        self.last_commands = []

    def update(self, observation):
        digest = hashlib.sha256(canonical(observation).encode()).hexdigest()
        if self.episode != observation['episode_id'] or observation['time'] < self.time:
            self.reset()
        if digest == self.digest:
            return copy.deepcopy(self.snapshot)
        self.episode, self.time, self.digest = observation['episode_id'], observation['time'], digest
        targets = {t['id']: t for t in observation['targets']}
        quality = observation['observation_quality']
        confidence = max(.1, (1 - .5 * quality['stale_data_ratio']) /
                         (1 + .5 * quality['contradiction_count'] + .05 * quality['maximum_delay']))
        if self.previous is not None:
            for command in self.last_commands:
                if command['action'] == 'observe':
                    identifier = command['parameters']['target_id']
                    if targets.get(identifier, {}).get('status') == 'confirmed':
                        self.verified.add(identifier)
        # A changed claim invalidates earlier confirmation, including target_state_changed.
        for target in targets.values():
            if target.get('status') == 'unconfirmed':
                self.verified.discard(target['id'])
        reports = []
        for message in sorted(observation['network'].get('messages', []), key=lambda m: m.get('id', '')):
            identifier = message.get('id')
            if not isinstance(identifier, str) or identifier in self.seen:
                continue
            if len(self.seen) >= 4096:
                break
            self.seen.add(identifier)
            source = message.get('source', 'unknown')
            positive, negative = self.sources.get(source, [1., 1.])
            claim = message.get('payload', {})
            target = targets.get(claim.get('target_id')) if isinstance(claim, dict) else None
            position = claim.get('position') if isinstance(claim, dict) else None
            valid_position = isinstance(position, list) and len(position) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in position)
            consistent = target is not None and valid_position and math.dist(target['position'], position) <= 1.
            contradiction = target is not None and valid_position and not consistent
            if consistent:
                positive += 1
            elif contradiction:
                negative += 1
                self.verified.discard(target['id'])
            self.sources[source] = [positive, negative]
            age = max(0., observation['time'] - message.get('arrival', observation['time']))
            reliability = positive / (positive + negative)
            score = reliability * observation['network']['average_link_quality'] / (1 + age / 10.)
            reports.append({'message_id': identifier, 'source': source, 'reliability': reliability,
                            'confidence': round(score, 6), 'corroborated': consistent,
                            'actionable': consistent and score >= .55,
                            'reason': 'contradicts_public_target' if contradiction else ('corroborated' if consistent else 'unverified_claim')})
        feedback = {'mission_delta': 0., 'energy_delta': 0., 'new_failures': [], 'command_outcomes': []}
        if self.previous:
            feedback['mission_delta'] = observation['metrics'].get('mission_completion', 0.) - self.previous['metrics'].get('mission_completion', 0.)
            feedback['energy_delta'] = observation['metrics'].get('energy_used', 0.) - self.previous['metrics'].get('energy_used', 0.)
            old = {a['id']: a['status'] for a in self.previous['agents']}
            feedback['new_failures'] = sorted(a['id'] for a in observation['agents'] if a['status'] == 'failed' and old.get(a['id']) != 'failed')
            current_agents = {a['id']: a for a in observation['agents']}
            prior_agents = {a['id']: a for a in self.previous['agents']}
            for command in self.last_commands:
                identifier, action = command['agent_id'], command['action']
                a = current_agents.get(identifier)
                success = None
                if a is not None and action == 'move':
                    success = a['position'] is not None and math.dist(a['position'], command['parameters']['target']) < 1e-6
                elif action in ('observe', 'deliver'):
                    target = targets.get(command['parameters']['target_id'], {})
                    success = target.get('status') in (('confirmed', 'delivered') if action == 'observe' else ('delivered',))
                elif a is not None and identifier in prior_agents and action == 'charge':
                    success = a['resources']['energy']['value'] > prior_agents[identifier]['resources']['energy']['value']
                if success is not None:
                    evidence = self.agents.setdefault(identifier, [1., 1.])
                    evidence[0 if success else 1] += 1.
                    feedback['command_outcomes'].append({'agent_id': identifier, 'action': action, 'success': success})
        self.snapshot = {'confidence': round(confidence, 6), 'verified_targets': sorted(self.verified),
                         'agent_reliability': {k: round(v[0]/sum(v), 6) for k,v in sorted(self.agents.items())},
                         'source_reputation': {k: round(v[0] / sum(v), 6) for k, v in sorted(self.sources.items())},
                         'message_assessments': reports, 'feedback': feedback,
                         'unknown_state_ratio': quality['unknown_state_ratio']}
        self.previous = copy.deepcopy(observation)
        return copy.deepcopy(self.snapshot)

    def issued(self, commands):
        self.last_commands = copy.deepcopy(commands)
