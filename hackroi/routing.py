"""Bounded visibility routing over public axis-aligned volumes."""
import heapq
import math
from functools import lru_cache


def contact_time(a, b, lower, upper):
    """First fraction of the segment that touches a closed box, or None."""
    first, last = 0., 1.
    for x,y,lo,hi in zip(a,b,lower,upper):
        delta = y-x
        if abs(delta) < 1e-12:
            if not lo <= x <= hi:
                return None
        else:
            near,far = sorted(((lo-x)/delta,(hi-x)/delta))
            first,last = max(first,near), min(last,far)
            if first > last:
                return None
    return first


def intersects(a, b, lower, upper):
    return contact_time(a, b, lower, upper) is not None


def expanded_box(lower, upper, body, clearance=0.):
    return (tuple(x-hi-clearance for x,hi in zip(lower,body['max'])),
            tuple(x-lo+clearance for x,lo in zip(upper,body['min'])))


def body_contact(a0, a1, body_a, b0, b1, body_b, clearance=0.):
    relative_start = tuple(a-b for a,b in zip(a0,b0))
    relative_end = tuple(a-b for a,b in zip(a1,b1))
    return contact_time(relative_start, relative_end, *expanded_box(body_b['min'], body_b['max'], body_a, clearance))


@lru_cache(maxsize=2048)
def waypoint(start, goal, lower, upper, boxes, corner_offset=.6):
    """Shortest visibility path on the current plane; bounded, no private map."""
    def inside(p):
        return all(lo <= x <= hi for x,lo,hi in zip(p,lower,upper))
    def clear(a,b):
        return not any(intersects(a,b,lo,hi) for lo,hi in boxes)
    if not inside(goal) or not clear(start,start) or not clear(goal,goal):
        return None
    if clear(start,goal):
        return goal
    if len(boxes) > 128:
        return None
    points = {start,goal}
    for lo,hi in boxes:
        if lo[2] <= start[2] <= hi[2]:
            for x in (lo[0]-corner_offset,hi[0]+corner_offset):
                for y in (lo[1]-corner_offset,hi[1]+corner_offset):
                    p=(x,y,start[2])
                    if inside(p) and clear(p,p):
                        points.add(p)
    # Aerial/underwater domains may also bypass a volume vertically.
    for lo,hi in boxes:
        for z in (lo[2]-corner_offset,hi[2]+corner_offset):
            for p in ((start[0],start[1],z),(goal[0],goal[1],z)):
                if inside(p) and clear(p,p):
                    points.add(p)
    nodes=sorted(points)
    if len(nodes)>520:
        return None
    distance={start:0.}; parent={}; queue=[(math.dist(start,goal),0.,start)]; expanded=0
    while queue and expanded<520:
        _,cost,current=heapq.heappop(queue)
        if cost>distance.get(current,float('inf'))+1e-12:
            continue
        expanded+=1
        if current==goal:
            while parent.get(current)!=start:
                current=parent.get(current)
                if current is None:return None
            return current
        for other in nodes:
            if other==current or not clear(current,other):continue
            candidate=cost+math.dist(current,other)
            if candidate<distance.get(other,float('inf'))-1e-12:
                distance[other]=candidate;parent[other]=current
                heapq.heappush(queue,(candidate+math.dist(other,goal),candidate,other))
    return None
