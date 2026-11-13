"""Declared physical terrain for authored operations; never imported by a controller."""
import copy
import json
from pathlib import Path

PROFILES=json.loads((Path(__file__).resolve().parents[1]/'scenarios/campaign/landscapes.json').read_text(encoding='utf-8'))


def surface_tiles(name):
    tiles=[[0.,0.,49.999,100.]]
    for x0,y0,x1,y1 in PROFILES[name]['cuts']:
        result=[]
        for a,b,c,d in tiles:
            left,bottom,right,top=max(a,x0),max(b,y0),min(c,x1),min(d,y1)
            if left>=right or bottom>=top:result.append([a,b,c,d]);continue
            result += [[a,b,left,d],[right,b,c,d],[left,b,right,bottom],[left,top,right,d]]
        tiles=[r for r in result if r[2]-r[0]>.001 and r[3]-r[1]>.001]
    return tiles


def zones(name, terrain):
    from .simulation import zone
    profile=PROFILES[name];result=[]
    for i,(x0,y0,x1,y1) in enumerate(surface_tiles(name)):
        z=zone('land_'+str(i),'land',[x0,y0,0.],[x1,y1,0.]);z['appearance']={'terrain':terrain};result.append(z)
    result.append(zone('water','water',[50.,0.,-15.],[100.,100.,0.]))
    for i,(x0,y0,x1,y1) in enumerate(profile['cuts']):
        result.append(zone('inlet_'+str(i),'water',[x0,y0,-15.],[x1,y1,0.]))
        z=zone('inlet_bank_'+str(i),'obstacle',[x0,y0,-.25],[x1,y1,.10]);z['appearance']={'kind':'water_bank'};result.append(z)
    for item in profile['features']:
        z=zone(item['id'],'obstacle',item['min'],item['max']);z['appearance']={'kind':item['kind']};result.append(z)
    for i,bridge in enumerate(profile.get('bridges',[])):
        # Surface support already exists as an uncut land strip. This box is visual only.
        z=zone('bridge_'+str(i),'infrastructure',bridge['min'],bridge['max']);z['appearance']={'kind':'bridge'};result.append(z)
    return result


def blocked_point(name, position, clearance=0.):
    x,y,z=position
    profile=PROFILES[name]
    if z==0 and any(a-clearance<=x<=c+clearance and b-clearance<=y<=d+clearance for a,b,c,d in profile['cuts']):return True
    return any(all(lo-clearance<=p<=hi+clearance for p,lo,hi in zip(position,f['min'],f['max'])) for f in profile['features'])


def extra_events(name):
    return copy.deepcopy(PROFILES[name]['events'])
