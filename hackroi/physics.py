"""Public AABB bodies and deterministic swept contacts for the solid-v1 profile."""
import math
from .routing import body_contact, contact_time, expanded_box

# XY envelopes contain the entire vehicle at any heading. Metres, one tick = 1 s.
BODIES = {'aerial':(.65,-.22,.35), 'ground':(.55,0.,1.05),
          'underground':(.55,-.25,.85), 'surface_water':(.6,-.25,1.1),
          'underwater':(.55,-.4,.4), 'cosmic':(.75,-.35,.35)}


def shape(agent):
    return next((c['body'] for c in agent.get('constraints',[]) if 'body' in c), None)


def configure(state):
    state['solid_contacts'] = True
    for a in state['agents']:
        if a['kind'] in BODIES:
            r,lo,hi=BODIES[a['kind']]
            a['constraints'][0]['body']={'min':[-r,-r,lo], 'max':[r,r,hi], 'clearance':.12}
            a['constraints'][0]['collision']={'model':'solid_v1', 'failure_normal_speed':3. if a['kind']=='aerial' else 2.}
        elif a['position'] is not None:
            a['constraints'].append({'id':'ariadna.body.v1','body':{'min':[-.35,-.35,-a['position'][2]],'max':[.35,.35,.5],'clearance':.12}})


def sweep_contact(start,end,lower,upper):
    fraction=contact_time(start,end,lower,upper)
    if fraction==0.:
        for p,q,lo,hi in zip(start,end,lower,upper):
            if (abs(p-lo)<1e-10 and q<=p) or (abs(p-hi)<1e-10 and q>=p):
                return None
    return fraction


def normal_speed(start,end,lower,upper,fraction):
    """Closing speed along the first contacted face; tangential motion is harmless."""
    velocity=[b-a for a,b in zip(start,end)]
    p=[a+fraction*v for a,v in zip(start,velocity)]
    faces=[]
    for axis,(x,lo,hi,v) in enumerate(zip(p,lower,upper,velocity)):
        if abs(x-lo)<1e-7 and v>0:faces.append(abs(v))
        if abs(x-hi)<1e-7 and v<0:faces.append(abs(v))
    return max(faces,default=0.)


def resolve(state,agents,destinations):
    shapes={k:shape(a) for k,a in agents.items() if a['position'] is not None and shape(a)}
    positions={k:list(agents[k]['position']) for k in shapes}
    moving={k:list(end) for k,(end,_) in destinations.items() if k in shapes and positions[k]!=end}
    origins={k:list(p) for k,p in positions.items()}
    velocities={k:[e-s for s,e in zip(positions[k],end)] for k,end in moving.items()}
    obstacles=[z for z in state['zones'] if z['type']=='obstacle']
    impacts={};elapsed=0.
    # Each pass stops at least one moving body, so the loop is bounded by fleet size.
    while moving:
        contacts=[]
        for k,end in moving.items():
            for z in obstacles:
                g=z['geometry'];lo,hi=expanded_box(g['min'],g['max'],shapes[k])
                fraction=sweep_contact(positions[k],end,lo,hi)
                if fraction is not None:
                    # Current subsegment spans the remaining time of the same tick.
                    speed=normal_speed(positions[k],end,lo,hi,fraction)/max(1e-12,1-elapsed)
                    contacts.append((fraction,k,z['id'],False,speed))
        keys=sorted(positions)
        for i,a in enumerate(keys):
            for b in keys[i+1:]:
                if a not in moving and b not in moving:continue
                pa,pb=positions[a],positions[b]
                ea,eb=moving.get(a,pa),moving.get(b,pb)
                lo,hi=expanded_box(shapes[b]['min'],shapes[b]['max'],shapes[a])
                start=[x-y for x,y in zip(pa,pb)];end=[x-y for x,y in zip(ea,eb)]
                fraction=sweep_contact(start,end,lo,hi)
                if fraction is not None:
                    speed=normal_speed(start,end,lo,hi,fraction)/max(1e-12,1-elapsed)
                    contacts.append((fraction,a,b,True,speed))
        first=min((c[0] for c in contacts),default=1.)
        elapsed+=(1-elapsed)*first
        for k,end in moving.items():positions[k]=[a+first*(b-a) for a,b in zip(positions[k],end)]
        if not contacts:break
        stopped=set()
        for fraction,a,b,peer,speed in sorted(contacts):
            if fraction>first+1e-10:break
            impacts.setdefault(a,{'with':b,'fraction':elapsed,'normal_speed':speed})
            stopped.add(a)
            if peer:
                impacts.setdefault(b,{'with':a,'fraction':elapsed,'normal_speed':speed})
                stopped.add(b)
        for k in stopped:moving.pop(k,None)
    for k,impact in impacts.items():
        limits=next((c for c in agents[k]['constraints'] if 'collision' in c),{})
        threshold=limits.get('collision',{}).get('failure_normal_speed',.75)
        impact['severe']=impact['normal_speed']>=threshold
        impact['contact_position']=list(positions[k])
    # A light contact backs away on an independently swept, free path. Never teleport
    # through a peer, wall or out of the public operating volume.
    for k,impact in sorted(impacts.items()):
        if impact['severe'] or k not in velocities:continue
        speed=math.sqrt(sum(v*v for v in velocities[k]))
        if speed<1e-12:continue
        retreat=shapes[k]['clearance']+.025
        start=positions[k];goal=[p-v/speed*retreat for p,v in zip(start,velocities[k])]
        limits=next((c for c in agents[k]['constraints'] if c.get('id')=='ariadna.motion.v1'),None)
        if not limits or not all(lo<=v<=hi for lo,v,hi in zip(limits['min'],goal,limits['max'])):continue
        # Move the test origin a tiny distance off the contact face to distinguish
        # separating motion from a new penetration of the obstacle.
        probe=[p+(q-p)*1e-5 for p,q in zip(start,goal)]
        clear=not any(contact_time(probe,goal,*expanded_box(z['geometry']['min'],z['geometry']['max'],shapes[k])) is not None for z in obstacles)
        for other,p in positions.items():
            if other==k:continue
            lo=[min(x,y)+offset for x,y,offset in zip(origins[other],p,shapes[other]['min'])]
            hi=[max(x,y)+offset for x,y,offset in zip(origins[other],p,shapes[other]['max'])]
            if contact_time(probe,goal,*expanded_box(lo,hi,shapes[k])) is not None:clear=False
        if clear:
            positions[k]=goal;impact['retreated']=True
    for k,p in positions.items():agents[k]['position']=[round(v,12) for v in p]
    return impacts
