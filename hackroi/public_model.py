"""Geometry and feasibility using declared public limits, never simulator state."""
import math
from .contracts import ProtocolError, check
from .routing import body_contact, expanded_box, intersects, waypoint


def motion(agent):
    return next((c for c in agent['constraints'] if c.get('id') == 'ariadna.motion.v1'), None)


def actions(agent):
    return {a.get('action', a.get('name')): a for a in agent['available_actions']}


def inside(point, low, high):
    return all(a <= x <= b for x, a, b in zip(point, low, high))


def reachable(agent, point):
    limits = motion(agent)
    return limits is not None and inside(point, limits['min'], limits['max'])


def swept_distance(a0, a1, b0, b1):
    delta = [a-b for a, b in zip(a0, b0)]
    velocity = [(a-x)-(b-y) for a, x, b, y in zip(a1, a0, b1, b0)]
    squared = sum(v*v for v in velocity)
    time = max(0., min(1., -sum(d*v for d, v in zip(delta, velocity))/squared)) if squared else 0.
    return math.sqrt(sum((d+time*v)**2 for d, v in zip(delta, velocity)))


def body(agent):
    return next((c['body'] for c in agent['constraints'] if 'body' in c), None)


def obstacle_boxes(observation, shape=None):
    for zone in observation['zones']:
        if zone['type'] not in ('restricted', 'obstacle'):
            continue
        box = zone['geometry']
        if box.get('type') != 'axis_aligned_box':
            yield None
        elif shape:
            yield expanded_box(box['min'], box['max'], shape, shape['clearance'])
        else:
            yield tuple(box['min']), tuple(box['max'])


def blocked(start, end, observation, agent=None):
    shape = body(agent) if agent else None
    return any(box is None or intersects(start, end, *box) for box in obstacle_boxes(observation, shape))


def paths_conflict(a, end_a, b, end_b, minimum):
    shape_a, shape_b = body(a), body(b)
    if shape_a and shape_b:
        clearance = max(shape_a['clearance'], shape_b['clearance'])
        return body_contact(a['position'], end_a, shape_a, b['position'], end_b, shape_b, clearance) is not None
    return swept_distance(a['position'], end_a, b['position'], end_b) < minimum


def move_towards(agent, destination, observation, step_scale=1.):
    limits = motion(agent)
    if limits is None or not reachable(agent, destination):
        return None
    start = agent['position']
    distance = math.dist(start, destination)
    speed = limits['speed'] * (limits.get('degraded_speed_factor', .5) if agent['status'] == 'degraded' else 1.) * step_scale
    factor = min(1., speed/distance) if distance else 0.
    end = [round(a+factor*(b-a), 12) for a, b in zip(start, destination)]
    if blocked(start, end, observation, agent):
        candidates = []
        for axis in (1, 0, 2):
            for sign in (-1, 1):
                point = list(start)
                point[axis] += sign*speed
                if reachable(agent, point) and not blocked(start, point, observation, agent):
                    candidates.append(point)
        if not candidates:
            return None
        end = min(candidates, key=lambda p: (math.dist(p, destination), tuple(p)))
    if math.dist(start, end) < 1e-9:
        return None
    return {'agent_id': agent['id'], 'action': 'move', 'parameters': {'target': end}}


def energy_cost(agent, command, observation):
    limits = motion(agent)
    if command['action'] == 'move':
        if not limits:
            return None
        multiplier = 1.
        for zone in observation['zones']:
            box = zone['geometry']
            if box.get('type') == 'axis_aligned_box' and intersects(agent['position'], command['parameters']['target'], box['min'], box['max']):
                multiplier = max(multiplier, zone['cost'].get('energy', 1.))
        return math.dist(agent['position'], command['parameters']['target']) * limits['energy_per_metre'] * multiplier + limits.get('idle_energy', 0.)
    descriptor = actions(agent).get(command['action'], {})
    if command['action'] == 'charge':
        return 0.
    return descriptor.get('energy_cost')


def guard(observation, commands, priority=False, *, preserve_connectivity=True):
    """Reject unsafe commands, resolve swept collisions, retain independent safe work."""
    agents = {a['id']: a for a in observation['agents']}
    accepted, checks, rejected = [], [], []
    used = set()
    for command in commands:
        a = agents.get(command['agent_id'])
        reason = None
        unsupported = [c for c in observation['constraints']+observation['mission']['constraints']+
                       (a['constraints'] if a else []) if c.get('mandatory') is True and
                       c.get('id') not in ('energy_reserve', 'collision_distance', 'ariadna.motion.v1', 'ariadna.energy.v1')]
        if unsupported:
            reason = 'unsupported_mandatory_constraint'
        elif a is None or a['id'] in used:
            reason = 'unknown_or_duplicate_agent'
        elif a['status'] not in ('active', 'degraded', 'safe_mode') or (a['status'] == 'safe_mode' and command['action'] != 'charge'):
            reason = 'agent_unavailable'
        elif not a['communication'].get('connected', False):
            reason = 'no_command_channel'
        elif command['action'] not in actions(a):
            reason = 'unavailable_action'
        elif command['action'] == 'move' and (not reachable(a, command['parameters']['target']) or blocked(a['position'], command['parameters']['target'], observation, a)):
            reason = 'space_constraint'
        else:
            cost = energy_cost(a, command, observation)
            resource = a['resources'].get('energy')
            if cost is None or resource is None:
                reason = 'undeclared_execution_cost'
            elif resource['value'] - cost < resource['minimum'] - 1e-12:
                reason = 'energy_reserve'
        if reason is None:
            descriptor = actions(a)[command['action']]
            try:
                check(command['parameters'], descriptor.get('parameters_schema', {}))
            except ProtocolError:
                reason = 'action_parameters_schema'
        if reason is None and command['action'] in ('observe', 'deliver'):
            target = next((t for t in observation['targets'] if t['id'] == command['parameters'].get('target_id')), None)
            limits = motion(a)
            if target is None or limits is None or a['position'] is None or math.dist(a['position'], target['position']) > limits['interaction_radius']:
                reason = 'target_out_of_reach'
            elif body(a) and blocked(a['position'], target['position'], observation):
                reason = 'target_behind_obstacle'
            elif command['action'] == 'deliver' and (target.get('status') != 'confirmed' or a['resources'].get('supplies', {}).get('value', 0.) < limits['delivery_supplies']):
                reason = 'unconfirmed_target_or_missing_supplies'
        if reason is None and command['action'] == 'charge':
            station = next((n for n in observation['infrastructure'] if n['id'] == command['parameters'].get('station_id')), None)
            limits = motion(a)
            if station is None or limits is None or a['position'] is None or station['status'] != 'active' or station['kind'] != 'charging_station' or station['resources'].get('stock', {}).get('value', 0.) <= 0. or math.dist(a['position'], station['position']) > limits['charge_radius']:
                reason = 'station_unavailable'
        if reason:
            rejected.append({'agent_id': command['agent_id'], 'action': command['action'], 'reason': reason})
        else:
            used.add(a['id'])
            accepted.append(command)
    # Removing one move can create a collision with a newly stationary agent; iterate.
    distance = max([c.get('minimum_metres', 0.) for c in observation['constraints'] if c.get('id') == 'collision_distance'] + [.5])
    while True:
        moves = {c['agent_id']: c for c in accepted if c['action'] == 'move'}
        conflicts = set()
        connected = predicted_connections(observation, moves) if preserve_connectivity else None
        if connected is not None:
            missing = {identifier for identifier, a in agents.items() if a['position'] is not None and
                       a['status'] in ('active', 'degraded', 'safe_mode') and
                       a['communication'].get('connected', False) and identifier not in connected}
            conflicts.update(identifier for identifier in missing if identifier in moves)
            if missing - set(moves):
                conflicts.update(identifier for identifier in moves if 'relay' in agents[identifier]['capabilities'])
        order={c['agent_id']:i for i,c in enumerate(accepted)}
        spatial = [a for a in agents.values() if a['position'] is not None]
        for i, a in enumerate(spatial):
            for b in spatial[i+1:]:
                end_a = moves.get(a['id'], {}).get('parameters', {}).get('target', a['position'])
                end_b = moves.get(b['id'], {}).get('parameters', {}).get('target', b['position'])
                if paths_conflict(a, end_a, b, end_b, distance):
                    moving=[identifier for identifier in (a['id'],b['id']) if identifier in moves]
                    if priority and len(moving)==2:
                        kept=None
                        for loser in sorted(moving,key=lambda i:order[i],reverse=True):
                            aa=a['position'] if loser==a['id'] else end_a
                            bb=b['position'] if loser==b['id'] else end_b
                            if not paths_conflict(a, aa, b, bb, distance):
                                kept=loser;break
                        if kept is not None:conflicts.add(kept)
                        else:conflicts.update(moving)
                    else:conflicts.update(moving)
        if not conflicts:
            break
        accepted = [c for c in accepted if not (c['action'] == 'move' and c['agent_id'] in conflicts)]
        rejected.extend({'agent_id': identifier, 'action': 'move', 'reason': 'collision_or_connection_constraint'} for identifier in sorted(conflicts))
    checks.append({'constraint_id': 'ariadna_public_command_guard', 'status': 'passed',
                   'accepted': len(accepted), 'rejected_commands': rejected})
    return accepted, checks


def predicted_connections(observation, moves):
    """One-tick declared link geometry, not a simulator call or stage-4 forecast."""
    radius = observation['network'].get('link_range')
    if not isinstance(radius, (int, float)):
        return None
    nodes = {n['id']: n for n in observation['agents']+observation['infrastructure']
             if n['status'] in ('active', 'degraded', 'safe_mode', 'charging') and
             (n['communication'].get('connected', False) or n['id'] in moves)}
    roots = [n['id'] for n in nodes.values() if n.get('kind') == 'base_station']
    if not roots:
        return None
    positions = {key: moves.get(key, {}).get('parameters', {}).get('target', n['position']) for key, n in nodes.items()}
    graph = {key: [] for key in nodes}
    for key, point in positions.items():
        if point is None:
            continue
        for other, destination in positions.items():
            if key == other or destination is None or math.dist(point, destination) > radius:
                continue
            shadow = any(z['type'] == 'low_connectivity' and z['geometry'].get('type') == 'axis_aligned_box' and
                         intersects(point, destination, z['geometry']['min'], z['geometry']['max']) for z in observation['zones'])
            if not shadow:
                graph[key].append(other)
    seen, queue = set(roots), list(roots)
    reachable_nodes = set(roots)
    while queue:
        node = queue.pop(0)
        for other in graph[node]:
            reachable_nodes.add(other)
            if other not in seen and 'relay' in nodes[other]['capabilities']:
                seen.add(other); queue.append(other)
    return reachable_nodes


def routed_move(agent, destination, observation, step_scale=1.):
    limits = motion(agent)
    if not limits or agent['position'] is None or not reachable(agent,destination):return None
    shape = body(agent)
    if shape:
        return route_with_body(agent, destination, observation, limits, shape, step_scale)
    destination=list(destination)
    occupied=any(other['id']!=agent['id'] and other['position'] is not None and math.dist(other['position'],destination)<.5 for other in observation['agents'])
    distance=math.dist(agent['position'],destination)
    if occupied and distance>limits.get('interaction_radius',1.):
        minimum=max([c.get('minimum_metres',0.) for c in observation['constraints'] if c.get('id')=='collision_distance']+[.5])
        radius=limits.get('interaction_radius',1.)
        if radius<=minimum:return None
        clearance=(radius+minimum)/2.
        destination=[g+(s-g)*clearance/distance for s,g in zip(agent['position'],destination)]
    boxes = list(obstacle_boxes(observation))
    if None in boxes:
        return None
    # Static occupancy of peers prevents repeated head-on swaps.
    for other in observation['agents']:
        if other['id']==agent['id'] or other['position'] is None:continue
        p=other['position']
        if math.dist(p,destination)<.6:continue
        lo,hi=tuple(x-.51 for x in p),tuple(x+.51 for x in p)
        if intersects(agent['position'],destination,lo,hi):boxes.append((lo,hi))
    point=waypoint(tuple(agent['position']),tuple(destination),tuple(limits['min']),tuple(limits['max']),tuple(sorted(boxes)))
    return move_towards(agent,list(point),observation,step_scale) if point else None


def route_with_body(agent, destination, observation, limits, shape, step_scale):
    start, goal = tuple(agent['position']), tuple(destination)
    boxes = list(obstacle_boxes(observation, shape))
    if None in boxes:
        return None
    occupied_goal = False
    detour_boxes = []
    for other in observation['agents']:
        peer = body(other)
        if other['id']==agent['id'] or other['position'] is None or peer is None:
            continue
        lower = [x+offset for x,offset in zip(other['position'], peer['min'])]
        upper = [x+offset for x,offset in zip(other['position'], peer['max'])]
        box = expanded_box(lower, upper, shape, max(shape['clearance'], peer['clearance']))
        if intersects(start, goal, *box):
            boxes.append(box)
            occupied_goal |= inside(goal, *box)
        else:
            detour_boxes.append(box)
    goals = [goal]
    if occupied_goal:
        # The task can be serviced beside a robot blocking its exact location.
        radius = limits['interaction_radius'] - .01
        goals = [(goal[0]+radius*math.cos(angle), goal[1]+radius*math.sin(angle), goal[2])
                 for angle in (i*math.pi/4 for i in range(8))]
        goals.sort(key=lambda point: math.dist(start, point))
    lower, upper = tuple(limits['min']), tuple(limits['max'])
    for point in goals:
        hop = waypoint(start, point, lower, upper, tuple(sorted(boxes)), corner_offset=.14)
        if hop is not None and any(intersects(start, hop, *box) for box in detour_boxes):
            # A wall detour can meet a peer that was clear of the original line to the goal.
            hop = waypoint(start, point, lower, upper, tuple(sorted(boxes+detour_boxes)), corner_offset=.14)
        if hop is not None:
            return move_towards(agent, list(hop), observation, step_scale)
    return None
