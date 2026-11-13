"""Apartment authoring profile for the same public A2X environment."""
import random

from .contracts import ProtocolError
from .environment import energy

FORMAT = 'ariadna.home.v1'
# XY envelopes include the whole chassis at any heading, including rotors or wheels.
BODIES = {
    'vacuum': (.31, 0., .28),
    'courier': (.38, 0., .45),
    'repeater': (.38, 0., .76),
    'drone': (.46, -.06, .15),
}
CLEARANCE = .12
# Doorway volumes use the same coordinates for physics, map and replay checks.
DOORS = {
    'door_lounge': ('Гостиная', [8.9, 3.1, 0.], [9.1, 6.1, 2.6]),
    'door_kitchen': ('Кухня', [8.9, 9.8, 0.], [9.1, 12.8, 2.6]),
    'door_utility': ('Прачечная', [14.9, 3.1, 0.], [15.1, 6.1, 2.6]),
    'door_study': ('Кабинет', [14.9, 9.8, 0.], [15.1, 12.8, 2.6]),
    'door_service': ('Служебная дверь', [18.1, 7.9, 0.], [21.4, 8.1, 2.6]),
}
CASES = {
    'leak': {
        'title': 'Ключ к вентилю',
        'description': 'Вода залила дверь прачечной. Термос везёт ключ к вентилю через кабинет и служебную дверь.',
        'seed': 42, 'max_steps': 80, 'expected': 'success',
    },
    'blackout': {
        'title': 'Свет после отключения',
        'description': 'Погас свет и отказала связь с кабинетом. Роботам нужно проверить сигнал жильца и доставить фонарь.',
        'seed': 109, 'max_steps': 80, 'expected': 'success',
    },
    'privacy': {
        'title': 'Закрытая дверь',
        'description': 'Датчик подаёт противоречивые сигналы. Жилец закрывает дверь кабинета и отменяет выезд роботов.',
        'seed': 307, 'max_steps': 80, 'expected': 'safe_stopped',
    },
}

LEGACY_TITLES = {
    'leak': 'Протечка после ужина',
    'blackout': 'Ночь без связи',
    'privacy': 'Не открывайте эту дверь',
}


def definition(case, seed=None):
    if not isinstance(case, str) or case not in CASES:
        raise ProtocolError('INVALID_REQUEST', 'Неизвестная операция «Квартиры 42»', 422)
    item = CASES[case]
    seed = item['seed'] if seed is None else seed
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ProtocolError('INVALID_REQUEST', 'Seed должен быть целым от 0 до 2147483647', 422)
    return {'format': FORMAT, 'case': case, 'seed': seed, 'max_steps': item['max_steps'],
            'title': item['title']}


def validate(value):
    if set(value)-{'format', 'case', 'seed', 'max_steps', 'title'}:
        raise ProtocolError('INVALID_REQUEST', 'Неизвестное поле домашней операции', 422)
    result = definition(value.get('case'), value.get('seed'))
    for key in ('max_steps', 'title'):
        if key=='title' and value.get(key)==LEGACY_TITLES[result['case']]:
            continue
        if key in value and value[key] != result[key]:
            raise ProtocolError('INVALID_REQUEST', 'Параметр управляется пресетом: '+key, 422)
    return result


def zones(zone):
    rooms = [
        ('lounge', [0, 0, 0], [9, 8, 0], 'lounge', 'Гостиная', 'oak'),
        ('kitchen', [0, 8, 0], [9, 16, 0], 'kitchen', 'Кухня', 'terrazzo'),
        ('hall', [9, 0, 0], [15, 16, 0], 'hall', 'Прихожая', 'oak'),
        ('utility', [15, 0, 0], [24, 8, 0], 'utility', 'Прачечная', 'ceramic'),
        ('study', [15, 8, 0], [24, 16, 0], 'study', 'Кабинет', 'oak'),
    ]
    out = []
    for identifier, lo, hi, kind, title, material in rooms:
        room = zone(identifier, 'land', lo, hi)
        room['appearance'] = {'kind': 'home_floor', 'room': kind, 'label': title, 'material': material}
        out.append(room)
    out.append(zone('home_air', 'air', [0, 0, 0.7], [24, 16, 2.55]))
    features = [
        ('wall_west', [0, 0, 0], [.18, 16, 2.6], 'wall'),
        ('wall_east', [23.82, 0, 0], [24, 16, 2.6], 'wall'),
        ('wall_north', [0, 15.82, 0], [24, 16, 2.6], 'wall'),
        ('wall_south', [0, 0, 0], [24, .18, 2.6], 'wall'),
        ('lounge_partition', [0, 7.9, 0], [9.1, 8.1, 2.6], 'wall'),
        ('east_partition_west', [14.9, 7.9, 0], [18.1, 8.1, 2.6], 'wall'),
        ('east_partition_east', [21.4, 7.9, 0], [24, 8.1, 2.6], 'wall'),
        ('sofa', [1, 1, 0], [4.4, 2.45, .92], 'sofa'),
        ('coffee_table', [2.7, 3.2, 0], [4.35, 4.05, .5], 'table'),
        ('fridge', [1, 13.3, 0], [2.5, 15.3, 2.1], 'fridge'),
        ('kitchen_counter', [3.15, 14, 0], [8, 15.3, .92], 'counter'),
        ('washer', [20.4, 1, 0], [22.2, 2.7, 1.1], 'washer'),
        ('desk', [20, 13.1, 0], [23.15, 14.6, .88], 'desk'),
        ('bookcase', [22.1, 9.25, 0], [23.35, 11.9, 2], 'bookcase'),
    ]
    for x in (9, 15):
        for i, (start, end) in enumerate(((0, 3.1), (6.1, 9.8), (12.8, 16))):
            features.append((f'partition_{x}_{i}', [x-.1, start, 0], [x+.1, end, 2.6], 'wall'))
    for identifier, lo, hi, kind in features:
        obj = zone(identifier, 'obstacle', lo, hi)
        obj['appearance'] = {'kind': 'home_'+kind}
        out.append(obj)
    for identifier, (name, lo, hi) in DOORS.items():
        door = zone(identifier, 'limited_access', lo, hi)
        door['appearance'] = {'kind': 'home_door', 'label': name}
        out.append(door)
    return out


def configure(state, parameters):
    from .simulation import PROFILES, add_agent, zone

    config = validate(parameters['custom_map'])
    case = config['case']
    state['layout'] = 'home'
    state['link_range'] = 8.
    state['zones'] = zones(zone)
    state['agents'] = []
    move = ('move', 'observe', 'send_message')
    courier = (*move, 'deliver', 'charge')
    fleet = [
        ('vacuum_a', 'ground', [5.6, 2, 0], 'vacuum', 'Пылесос «Щётка»', (*move, 'charge'), .84),
        ('vacuum_b', 'ground', [20, 5.7, 0], 'vacuum', 'Пылесос «Клевер»', (*move, 'relay', 'charge'), .76),
        ('carrier_a', 'ground', [6.5, 11.45, 0], 'courier', 'Курьер «Тост»', courier, .96),
        ('carrier_b', 'ground', [12, 7.2, 0], 'courier', 'Курьер «Термос»', courier, .87),
        ('carrier_c', 'ground', [20, 11.15, 0], 'courier', 'Курьер «Блик»', courier, .93),
        ('drone_a', 'aerial', [5.2, 5.8, 1.75], 'drone', 'Мини-дрон «Искра»', (*move, 'relay'), .86),
        ('drone_b', 'aerial', [19.6, 10.7, 1.9], 'drone', 'Мини-дрон «Фонарь»', (*move, 'relay'), .88),
        ('mesh_cart', 'ground', [9.8, 5.05, 0], 'repeater', 'Ретранслятор «Маяк»', (*move, 'relay', 'charge'), .83),
        ('mesh_spare', 'ground', [12.8, 9.1, 0], 'repeater', 'Ретранслятор «Мост»', (*move, 'relay', 'charge'), .92),
        ('fusion', 'digital', None, 'hub', 'Домашний штаб', ('send_message',), 1.),
        ('operator', 'operator', None, 'operator', 'Оператор', ('send_message',), 1.),
    ]
    for identifier, kind, position, model, name, available, power in fleet:
        if case == 'leak':
            if identifier == 'carrier_b':
                position = [12., 4.8, 0.]
            else:
                available = tuple(action for action in available if action != 'deliver')
        unit = add_agent(state, identifier, kind, position, available)
        unit['resources'].update(energy(power))
        unit['appearance'] = {'model': model, 'name': name}
        if kind in ('aerial', 'ground'):
            ground = kind == 'ground'
            half_width, bottom, top = BODIES[model]
            limits = unit['constraints'][0]
            limits.update(min=[.3,.3,0 if ground else .85], max=[23.7,15.7,0 if ground else 2.3],
                          speed=.95 if ground else 1.55, sensor_radius=3.8 if ground else 4.8,
                          charge_radius=1.45, energy_per_metre=PROFILES[kind][1],
                          body={'min':[-half_width,-half_width,bottom],
                                'max':[half_width,half_width,top], 'clearance':CLEARANCE})
    sites = [
        ('infra_3', 'base_station', [4.75,5.3,1.1], 'Шлюз с резервом'),
        ('infra_0', 'relay', [12.2,4.8,1.4], 'Роутер прихожей'),
        ('relay_east', 'relay', [18.7,4.8,1.3], 'Узел прачечной'),
        ('relay_north', 'relay', [18,11.8,1.3], 'Узел кабинета'),
        ('infra_1', 'charging_station', [5.7,2.4,0], 'Док гостиной'),
        ('dock_hall', 'charging_station', [11.7,7.6,0], 'Док прихожей'),
        ('dock_east', 'charging_station', [20,11.5,0], 'Док кабинета'),
        ('infra_2', 'sensor_node', [20.5,3.3,.15], 'Датчик протечки'),
        ('occupancy', 'sensor_node', [20.8,12,.15], 'Датчик присутствия'),
    ]
    state['infrastructure'] = []
    for identifier, kind, position, name in sites:
        capabilities = {'base_station':['relay'], 'relay':['relay'],
                        'charging_station':['charge'], 'sensor_node':['sense']}[kind]
        state['infrastructure'].append({
            'id': identifier, 'kind': kind, 'position': position, 'status': 'active',
            'capabilities': capabilities, 'communication': {}, 'constraints': [],
            'resources': {'stock': {'id':'stock','value':1.,'minimum':0.,'maximum':1.,'unit':'normalized'}},
            'appearance': {'name': name},
        })
    state['targets'] = [
        {'id':'routine', 'position':[4.8,11.25,0], 'status':'confirmed', 'priority':1.,
         'appearance':{'label':'Бутылка у кухни','kind':'routine'}},
        {'id':'resident', 'position':[21.2,12.35,0], 'status':'unconfirmed', 'priority':6.,
         'appearance':{'label':'Связь с жильцом','kind':'resident'}},
    ]
    if case == 'leak':
        state['targets'] = [{'id':'routine', 'position':[11.85,4.65,0.], 'status':'confirmed', 'priority':1.,
                             'appearance':{'label':'Забрать ключ', 'kind':'routine'}}]
    elif case == 'blackout':
        state['targets'][0]['appearance']['label'] = 'Проверить набор на кухне'
    else:
        state['targets'][0]['appearance']['label'] = 'Вернуть доставку на кухню'
    state['discovered'].add('routine')
    state['mission']['objectives'] = [
        {'id':'task_'+t['id'],'target_id':t['id'],'type':'deliver','priority':t['priority'],'status':'pending'}
        for t in state['targets']
    ]
    state['mission']['priorities'] = ['routine','search','confirm','deliver','connectivity','safety']
    rng = random.Random(state['seed'] ^ 0xF042)
    alarm = 5. + rng.randint(0, 2)
    if case == 'leak':
        alarm -= 3.
    state['home_release_at'] = alarm + (20 if case == 'privacy' else 1)
    def event(offset, kind, targets=(), **params):
        return {'time':alarm+offset,'type':kind,'targets':list(targets),'parameters':params}
    kit = event(4, 'target_detected', position=[18.85,10.9,0], priority=5.,
                appearance={'label':'Фонарь и пауэрбанк','kind':'kit'})
    if case == 'leak':
        schedule = [
            event(0,'restricted_zone_appeared', ['infra_2'], min=[14.3,2.8,0.], max=[16.6,6.4,.7],
                  appearance={'kind':'home_wet', 'door_id':'door_utility'}),
            event(1,'infrastructure_failure', ['relay_east']),
            event(2,'target_detected', position=[18.65,4.75,0.], priority=5.,
                  appearance={'label':'Ключ у вентиля','kind':'valve'}),
        ]
    elif case == 'blackout':
        schedule = [
            event(0,'infrastructure_failure',['infra_0']),
            event(1,'connectivity_loss',['relay_north']),
            event(3,'resource_shortage',['carrier_b']),
            event(3,'stale_information',['occupancy']),
            event(3,'contradictory_information',['occupancy']),
            kit,
        ]
    else:
        schedule = [
            event(0,'stale_information',['occupancy']),
            event(1,'contradictory_information',['occupancy']),
            event(2,'restricted_zone_appeared', min=DOORS['door_study'][1], max=DOORS['door_study'][2],
                  appearance={'kind':'home_private', 'door_id':'door_study'}),
            event(2,'restricted_zone_appeared', min=DOORS['door_service'][1], max=DOORS['door_service'][2],
                  appearance={'kind':'home_private', 'door_id':'door_service'}),
            event(2,'operator_directive', ['operator'], type='safe_stop', reason='room_access_withdrawn'),
        ]
    parameters['events'] = schedule
