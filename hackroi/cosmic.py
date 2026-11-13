"""Public satellite relay model. Coordinates are schematic, not orbital mechanics."""
import math


def declaration(agent):
    return next((c for c in agent.get('constraints', []) if c.get('id') == 'ariadna.cosmic.v1'), None)


def link(a, b, pa, pb, factor=1.):
    """None means ordinary terrestrial radio; False means no satellite channel."""
    if a.get('kind') != 'cosmic' and b.get('kind') != 'cosmic':
        return None
    satellite, terminal = (a, b) if a.get('kind') == 'cosmic' else (b, a)
    sp, tp = (pa, pb) if satellite is a else (pb, pa)
    energy = satellite.get('resources', {}).get('energy', {})
    if energy.get('value', 1.) <= energy.get('minimum', 0.):
        return False
    model = declaration(satellite)
    if not model or sp is None or tp is None or tp[2] < 0 or terminal.get('kind') == 'cosmic':
        return False
    return (math.dist(sp, tp) <= model['slant_range']*factor and
            math.hypot(sp[0]-tp[0], sp[1]-tp[1]) <= model['footprint_radius']*factor)


def configure(agent):
    agent['constraints'].append({'id': 'ariadna.cosmic.v1', 'model': 'schematic_geostationary_relay',
                                'slant_range': 110., 'footprint_radius': 75.,
                                'link_delay': 2., 'subsurface_direct_link': False})
    # This mission uses a fixed relay, not a flying scout or omniscient sensor.
    agent['available_actions'] = [a for a in agent['available_actions'] if a['action'] in ('relay', 'send_message')]
    agent['capabilities'] = ['relay', 'send_message']
    agent['position'] = [50., 50., 60.]
    agent['appearance'] = {'name': 'Орбита 01', 'model': 'satellite'}
