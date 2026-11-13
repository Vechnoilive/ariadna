"""Validated author maps; private targets stay inside the environment process."""
import copy
import hashlib
import math
import random
from .contracts import ProtocolError, canonical

FORMAT = 'ariadna.map.v1'
SHAPES = {'tree': (3., 3., 8.), 'rock': (5., 4., 3.), 'ruin': (7., 6., 7.)}
TERRAINS = ('forest', 'quarry', 'city', 'snow', 'delta')
CONDITIONS = ('standard', 'aftershock', 'blackout', 'blizzard', 'flood', 'operation')
KINDS = ('ground', 'surface_water', 'underground', 'underwater')
MOBILE_KINDS = ('aerial', *KINDS)
START_CLEARANCE = 2.


def invalid(message):
    raise ProtocolError('INVALID_REQUEST', message, 422)


def point(value):
    return isinstance(value, list) and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in value)


def validate_map(value):
    from .home import FORMAT as HOME_FORMAT, validate as validate_home
    if isinstance(value, dict) and value.get('format') == HOME_FORMAT:
        return validate_home(value)
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        invalid('Ожидается карта ariadna.map.v1')
    if set(value) - {'format', 'title', 'seed', 'max_steps', 'cohorts', 'random_events', 'objects', 'targets', 'terrain', 'conditions', 'geography', 'deployment', 'physics'}:
        invalid('В карте есть неизвестные поля')
    if value.get('physics', 'legacy') not in ('legacy', 'solid_v1'):invalid('Неизвестная модель столкновений')
    result = copy.deepcopy(value)
    title = result.get('title', 'Своя операция')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 64:
        invalid('Название: от 1 до 64 символов')
    result['title'] = title.strip()
    for key, default, low, high in [('seed', 42, 0, 2147483647), ('max_steps', 120, 30, 180), ('cohorts', 2, 1, 3)]:
        number = result.get(key, default)
        if type(number) is not int or not low <= number <= high:
            invalid(f'{key}: целое от {low} до {high}')
        result[key] = number
    if type(result.get('random_events', False)) is not bool:
        invalid('random_events должен быть bool')
    result.setdefault('random_events', False)
    for key, allowed in [('terrain', TERRAINS), ('conditions', CONDITIONS)]:
        if key in result and (not isinstance(result[key],str) or result[key] not in allowed):
            invalid('Неизвестный профиль '+key)
    from .landscapes import PROFILES, blocked_point
    geography=result.get('geography')
    if geography is not None and (not isinstance(geography,str) or geography not in PROFILES):invalid('Неизвестный ландшафт')
    if result.get('conditions')=='operation' and geography is None:invalid('Для операции нужен ландшафт')
    objects, targets = result.get('objects'), result.get('targets')
    if not isinstance(objects, list) or len(objects) > 64 or not isinstance(targets, list) or not 1 <= len(targets) <= 12:
        invalid('Допускаются до 64 препятствий и от 1 до 12 целей')
    boxes = []
    for obj in objects:
        if not isinstance(obj, dict) or set(obj) != {'kind', 'position'} or not isinstance(obj['kind'],str) or obj['kind'] not in SHAPES or not point(obj['position']):
            invalid('Неверный объект карты')
        x, y, z = obj['position']; sx, sy, height = SHAPES[obj['kind']]
        if z != 0 or not sx/2+1 <= x <= 49-sx/2 or not sy/2+1 <= y <= 99-sy/2:
            invalid('Препятствия размещаются на суше внутри границ')
        box = ([x-sx/2, y-sy/2, 0.], [x+sx/2, y+sy/2, height])
        if any(all(box[0][i] < b[1][i]+1 and box[1][i] > b[0][i]-1 for i in (0, 1)) for b in boxes):
            invalid('Препятствия пересекаются или стоят слишком близко')
        if geography:
            physical=[(f['min'],f['max']) for f in PROFILES[geography]['features']]+[([a,b,-.25],[c,d,.1]) for a,b,c,d in PROFILES[geography]['cuts']]
            if any(all(box[0][i]<hi[i]+1 and box[1][i]>lo[i]-1 for i in range(3)) for lo,hi in physical):invalid('Препятствие пересекает ландшафт')
        boxes.append(box)
    def blocked(p, clearance=0.):
        return any(all(lo[i]-clearance <= p[i] <= hi[i]+clearance for i in range(3)) for lo, hi in boxes)
    for target in targets:
        if not isinstance(target, dict) or set(target) - {'kind', 'position', 'priority'} or target.get('kind') not in KINDS or not point(target.get('position')):
            invalid('Неверная цель')
        x, y, z = target['position']; kind = target['kind']
        expected = 0 if kind in ('ground', 'surface_water') else -5
        if z != expected or not 2 <= x <= 98 or not 2 <= y <= 98 or (kind == 'ground' and x >= 48) or (kind in ('surface_water', 'underwater') and x < 52) or (kind == 'underground' and (x > 38 or y > 38)):
            invalid('Цель не соответствует выбранной среде: суша, вода или подземная зона 0–40 м')
        priority = target.get('priority', 2)
        if type(priority) is not int or not 1 <= priority <= 5:
            invalid('Приоритет цели: 1–5')
        target['priority'] = priority
        if (geography and blocked_point(geography,target['position'],1.)) or blocked(target['position'], 1.):
            invalid('Цель находится внутри препятствия')
    for i, a in enumerate(targets):
        if any(math.dist(a['position'], b['position']) < 3 for b in targets[i+1:]):
            invalid('Цели должны находиться не ближе 3 м друг от друга')
    if 'deployment' in result:
        validate_deployment(result['deployment'], geography, blocked)
        launch = []
    else:
        launch = [[x, 8.+2*k, z] for x, z in [(5., 0.), (8., 10.)] for k in range(result['cohorts'])]
    fixed_sites = [[5., 5., 0.], [25., 8., 8.], [30., 8., 8.], [45., 8., 8.]]
    for position in launch + fixed_sites:
        if blocked(position, START_CLEARANCE):
            invalid('Препятствие перекрывает стартовую позицию или базу')
    if geography:
        for event in PROFILES[geography]['events']:
            p=event['parameters'].get('position')
            if p and (blocked_point(geography,p,1.) or blocked(p,1.)):invalid('Поздняя цель перекрыта препятствием')
    return result


def validate_deployment(deployment, geography, blocked):
    from .landscapes import blocked_point
    from .simulation import medium

    if not isinstance(deployment, dict) or set(deployment) != set(MOBILE_KINDS):
        invalid('Развёртывание требует стартовые точки для пяти мобильных классов')
    positions = [[30., 8., 8.]]
    for kind in MOBILE_KINDS:
        slots = deployment[kind]
        if not isinstance(slots, list) or len(slots) != 3:
            invalid('Для каждого класса нужны три стартовые точки')
        for position in slots:
            if not point(position) or not medium(kind, position):
                invalid('Стартовая точка не соответствует среде агента')
            if blocked(position, START_CLEARANCE) or (
                geography and blocked_point(geography, position, START_CLEARANCE)
            ):
                invalid('Стартовая точка перекрыта препятствием')
            if any(math.dist(position, other) < START_CLEARANCE for other in positions):
                invalid('Стартовые точки должны быть разнесены минимум на 2 м')
            positions.append(position)


def campaign_map(definition, deployments):
    """Build the live preset while keeping the original evidence map replayable."""
    return validate_map({**definition, 'physics':'solid_v1', 'deployment': deployments[definition['geography']]})


def fingerprint(value):
    return hashlib.sha256(canonical(validate_map(value)).encode()).hexdigest()


def random_schedule(seed, state, conditions='standard', geography=None):
    rng = random.Random(seed ^ 0xE71A)
    if conditions=='operation':
        from .landscapes import extra_events
        schedule=extra_events(geography)
        for event in schedule:event['time']+=rng.randint(0,2)
        return schedule
    degradable = [a['id'] for a in state['agents'] if a['kind'] in ('ground', 'surface_water', 'underwater')]
    schedule = [
        {'time': float(rng.randint(5, 9)), 'type': 'agent_degradation', 'targets': [rng.choice(degradable)], 'parameters': {}},
        {'time': float(rng.randint(10, 14)), 'type': 'infrastructure_failure', 'targets': [rng.choice(['infra_0', 'infra_2'])], 'parameters': {}},
        {'time': float(rng.randint(15, 20)), 'type': 'contradictory_information', 'targets': [], 'parameters': {}},
    ]

    extra = {
        'aftershock': [{'time': 7., 'type': 'restricted_zone_appeared', 'targets': [], 'parameters': {'min':[18.,36.,0.], 'max':[25.,43.,6.]}}, {'time':12.,'type':'agent_failure','targets':['land'],'parameters':{}}],
        'blackout': [{'time': 4., 'type': 'connectivity_loss', 'targets': ['infra_0','infra_2'], 'parameters': {}}, {'time':8.,'type':'resource_shortage','targets':['land'],'parameters':{}}],
        'blizzard': [{'time': 4., 'type': 'agent_degradation', 'targets': ['air'], 'parameters': {}}, {'time':8.,'type':'stale_information','targets':[],'parameters':{}}],
        'flood': [{'time': 6., 'type': 'hazard_appeared', 'targets': [], 'parameters': {'min':[30.,45.,0.], 'max':[46.,57.,2.]}}, {'time':10.,'type':'mission_priority_change','targets':[],'parameters':{}}],
    }
    # Times are seed-dependent, while event kinds express each mission's conditions.
    for event in extra.get(conditions,[]):
        event['time'] += rng.randint(0,2)
        schedule.append(event)
    return schedule


def configure(state, parameters):
    from .simulation import zone
    value = validate_map(parameters['custom_map'])
    count = value['cohorts']
    deployment = value.get('deployment')
    initial = list(state['agents'])
    if deployment:
        for a in initial:
            if a['kind'] in deployment:
                a['position'] = list(deployment[a['kind']][0])
    for k in range(1, count):
        for a in initial:
            if a['kind'] not in MOBILE_KINDS:
                continue
            b = copy.deepcopy(a)
            b['id'] = a['id']+'_'+str(k)
            if deployment:
                b['position'] = list(deployment[a['kind']][k])
            else:
                b['position'][1] += 2*k
            state['agents'].append(b)
    state['zones'] = [z for z in state['zones'] if z['type'] in ('land', 'water', 'air', 'underground', 'infrastructure')]
    for z in state['zones']:
        if z['type']=='land':
            z['appearance']={'terrain':value.get('terrain','forest'),'version':'ariadna.visual.v1'}
    if value.get('geography'):
        from .landscapes import zones
        state['zones']=[z for z in state['zones'] if z['type'] not in ('land','water')] + zones(value['geography'],value.get('terrain','forest'))
    for i, obj in enumerate(value['objects']):
        sx, sy, height = SHAPES[obj['kind']]; x,y,_ = obj['position']
        z = zone('custom_object_'+str(i), 'obstacle', [x-sx/2,y-sy/2,0.], [x+sx/2,y+sy/2,height])
        z['appearance'] = {'kind': obj['kind'], 'version': 'ariadna.visual.v1'}
        state['zones'].append(z)
    state['targets'] = [{'id': 'custom_target_'+str(i), 'position': t['position'], 'priority': float(t['priority']), 'status': 'unconfirmed'} for i,t in enumerate(value['targets'])]
    state['mission']['objectives'] = [{'id': 'rescue_'+t['id'], 'target_id': t['id'], 'type': 'deliver', 'priority': t['priority'], 'status': 'pending'} for t in state['targets']]
    prototype = next(n for n in state['infrastructure'] if n['kind'] == 'relay')
    for i, p in enumerate(([20.,30.,8.], [45.,30.,8.], [70.,30.,8.], [95.,30.,8.], [20.,60.,8.], [45.,60.,8.], [70.,60.,8.], [95.,60.,8.], [20.,90.,8.], [45.,90.,8.], [70.,90.,8.], [95.,90.,8.])):
        n = copy.deepcopy(prototype); n.update(id='custom_relay_'+str(i),position=[p[0],p[1],12.]);state['infrastructure'].append(n)
    for a in state['agents']:
        if a['kind'] not in ('ground','underground','surface_water','underwater'):
            continue
        n = copy.deepcopy(next(n for n in state['infrastructure'] if n['kind']=='charging_station'))
        n.update(id='custom_station_'+a['id'], position=copy.deepcopy(a['position']))
        state['infrastructure'].append(n)
    parameters['events'] = random_schedule(state['seed'],state,value.get('conditions','standard'),value.get('geography')) if value['random_events'] else []
    state['layout'] = 'custom'
    if value.get('physics')=='solid_v1':
        from .physics import configure as configure_physics
        configure_physics(state)
